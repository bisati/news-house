"""The single scheduled entry point: run the pipeline, then build or look for breaking news."""
from __future__ import annotations

import logging
import shutil
import uuid
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from newshouse.breaking import run_breaking
from newshouse.build import build_edition, prune_old
from newshouse.classify import classify_clusters
from newshouse.cluster import cluster_fresh_items
from newshouse.config import Settings
from newshouse.db import ensure_columns
from newshouse.embed import embed_new_items
from newshouse.health import check_sources
from newshouse.inbox import inbox_engine, sync_feedback
from newshouse.ingest import ingest
from newshouse.live import fetch_market
from newshouse.llm.backend import snapshot_of, usage_delta
from newshouse.models import Edition, Run
from newshouse.profile import load_profile
from newshouse.publish import REPO_ROOT, publish
from newshouse.render_static import render_edition
from newshouse.sources import load_sources, sync_sources
from newshouse.threads import close_quiet_threads, match_threads

BUILD_HOUR = 6
STATS = ("cluster", "classify", "threads", "feedback_sync", "market", "publish")  # kept in run.stats
log = logging.getLogger(__name__)


def _sync(session: Session, settings: Settings, now: datetime) -> int | None:
    path = Path(settings.sources_path)
    mtime = path.stat().st_mtime
    last = session.scalar(select(Run).where(Run.kind == "sync").order_by(Run.started_at.desc()).limit(1))
    if last is not None and mtime <= (last.stats or {}).get("mtime", 0):
        return None
    n = sync_sources(session, load_sources(path))
    session.add(Run(id=uuid.uuid4().hex, kind="sync", started_at=now,
                    finished_at=datetime.now(timezone.utc),
                    status="ok", stats={"mtime": mtime, "count": n}))
    session.commit()
    return n


def refresh_market(session: Session, edition: Edition, client, out_dir: Path) -> str:
    """Put NSE's latest Nifty numbers on today's edition and re-render it when they differ
    from the tile's: "updated", "unchanged", "failed" (no numbers) or "error". A weekend or
    holiday tick sees the last close again, so it re-renders nothing."""
    try:
        snap = fetch_market(client)
        if snap is None:
            return "failed"
        if (edition.live or {}).get("market") == snap:
            return "unchanged"
        edition.live = {**(edition.live or {}), "market": snap}  # a new dict, so the JSON column saves
        session.commit()
        html = render_edition(session, edition, out_dir)
        shutil.copyfile(html, Path(out_dir) / "latest.html")
        return "updated"
    except Exception as e:  # a tile never fails a tick
        session.rollback()
        log.warning("market refresh failed: %s", type(e).__name__)
        return "error"


def tick(session: Session, backend, *, settings: Settings, now: datetime, client, embedder,
         out_dir: Path) -> dict:
    """One scheduled run. Its own Run row (kind "tick") records the model usage of the
    stages it runs itself, per stage; the build's usage is in the build Run."""
    ensure_columns(session.get_bind())
    out: dict = {}
    usage: dict[str, dict] = {}
    run = Run(id=uuid.uuid4().hex, kind="tick", started_at=now, status="running", stats={})
    session.add(run)
    session.commit()
    run_id = run.id

    def stage(name: str, fn):
        before = snapshot_of(backend)
        result = fn()
        d = usage_delta(before, snapshot_of(backend))
        if d:
            usage[name] = d
        # Commit after every stage so a crash loses at most the stage in flight.
        session.commit()
        return result

    try:
        return _tick_stages(session, backend, settings=settings, now=now, client=client,
                            embedder=embedder, out_dir=out_dir, out=out, usage=usage,
                            stage=stage, run_id=run_id)
    except Exception as e:
        session.rollback()
        run = session.get(Run, run_id)
        run.status, run.error = "error", str(e)[:2000]
        run.finished_at = datetime.now(timezone.utc)
        run.stats = {"usage": usage, **{k: v for k, v in out.items() if k in STATS}}
        session.commit()
        raise


def _tick_stages(session: Session, backend, *, settings: Settings, now: datetime, client,
                 embedder, out_dir: Path, out: dict, usage: dict, stage, run_id: str) -> dict:
    out["sync"] = stage("sync", lambda: _sync(session, settings, now))
    out["ingest"] = stage("ingest", lambda: ingest(session, now=now, client=client).model_dump())
    out["embed"] = stage("embed", lambda: embed_new_items(session, embedder))
    out["cluster"] = stage("cluster", lambda: len(cluster_fresh_items(
        session, backend, now=now, window_hours=settings.cluster_window_hours)))
    profile = load_profile(session, settings)
    out["classify"] = stage("classify", lambda: classify_clusters(
        session, backend, profile_text=profile.text, batch=settings.classify_batch, now=now,
        profile_id=settings.profile_id))
    out["threads"] = stage("threads", lambda: match_threads(session, backend, now=now))

    out["feedback_sync"] = None
    if settings.neon_database_url:  # taps from the hosted page, recorded before the build decision
        try:
            eng = inbox_engine(settings.neon_database_url)
            try:
                out["feedback_sync"] = sync_feedback(
                    session, eng, profile_id=settings.profile_id, now=now)
            finally:
                eng.dispose()
        except Exception as e:  # never log the message: it can carry the connection URL
            session.rollback()
            log.warning("feedback sync failed: %s", type(e).__name__)
            out["feedback_sync"] = {"error": type(e).__name__}

    tz = ZoneInfo(settings.tz)
    local = now.astimezone(tz)
    built = session.scalar(select(Edition).where(
        Edition.profile_id == settings.profile_id, Edition.date == local.date(),
        Edition.built_at.is_not(None)))
    out.update(built=None, rendered=None, breaking=[], market=None, publish=None)
    if built is None and local.time() >= time(BUILD_HOUR):
        ed = build_edition(session, backend, settings=settings, now=now, client=client,
                           embedder=embedder)
        out["built"] = ed.id
        html = render_edition(session, ed, out_dir)
        shutil.copyfile(html, Path(out_dir) / "latest.html")
        out["rendered"] = str(html)
    else:
        out["breaking"] = [c.id for c in stage("breaking", lambda: run_breaking(
            session, backend, settings=settings, now=now, client=client))]
        if built is not None:  # the paper is out: keep its market tile current through the day
            out["market"] = stage("market", lambda: refresh_market(session, built, client, out_dir))

    # Every tick, not only after a render: publish() skips unchanged content and retries a
    # push that failed earlier. Publishing never fails the tick (Ruling 5).
    if settings.publish_remote:
        try:
            out["publish"] = publish(
                Path(out_dir), repo=REPO_ROOT, remote=settings.publish_remote,
                branch=settings.publish_branch, worktree=settings.publish_worktree, now=now,
                author_name=settings.publish_author_name,
                author_email=settings.publish_author_email)
        except Exception as e:  # never log the message: it can carry the remote URL
            log.warning("publish failed: %s", type(e).__name__)
            out["publish"] = {"status": "error", "error": type(e).__name__}

    out["threads_closed"] = close_quiet_threads(session, now=now)
    midnight = datetime.combine(local.date(), time(0), tzinfo=tz)
    pruned = session.scalar(select(Run.id).where(Run.kind == "prune", Run.started_at >= midnight))
    out["pruned"] = None
    if pruned is None:
        n = prune_old(session, now=now)
        session.add(Run(id=uuid.uuid4().hex, kind="prune", started_at=now,
                        finished_at=datetime.now(timezone.utc),
                        status="ok", stats={"pruned": n}))
        session.commit()
        out["pruned"] = n

    out["health"] = None
    if local.weekday() == 6 and session.scalar(select(Run.id).where(
            Run.kind == "health", Run.started_at >= midnight).limit(1)) is None:
        out["health"] = check_sources(session, client=client, now=now)
    run = session.get(Run, run_id)
    run.status, run.finished_at = "ok", datetime.now(timezone.utc)
    run.stats = {"usage": usage, **{k: out[k] for k in STATS}}
    session.commit()
    return out
