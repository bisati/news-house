"""Render an edition to a self-contained HTML page plus JSON (the static preview)."""
from __future__ import annotations

import copy
import json
from collections import Counter
import re
import shutil
from datetime import date, timedelta
from importlib import resources
from pathlib import Path
from urllib.parse import urlsplit

from jinja2 import Environment, PackageLoader
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from newshouse.catalogue import photo_eligible
from newshouse.config import Settings
from newshouse.edition_config import EditionConfig, load_edition_config
from newshouse.live import SHORT_NAMES, aqi_url, schedule_url
from newshouse.models import AlsoHappened, Card, Cluster, ClusterItem, Edition, Item, ItemSource, Source
from newshouse.present import (PALETTE, value_class, TOPIC_NAMES, _chart, _table, colour_world, deck_for,  # noqa: F401
                               safe_image_url, topic_family, topic_name, tune_chips, visual_for,
                               HEADLINE_FIRST, countdown_days, date_bar, number_bars)
from newshouse.select import primary_topic


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def safe_url(url) -> str | None:
    """The URL only when its scheme is http or https, else None."""
    try:
        return url if urlsplit(str(url).strip()).scheme.lower() in ("http", "https") else None
    except ValueError:
        return None


def _stack_rows(stack) -> list[dict]:
    """A card's stack rows with each link through ``safe_url`` (no link when unsafe)."""
    return [{**r, "url": safe_url(r.get("url")) if r.get("url") else None}
            for r in (stack or []) if isinstance(r, dict)]


def _sources(session: Session, item_ids: list[str]) -> list[dict]:
    out = []
    for iid in item_ids or []:
        item = session.get(Item, iid)
        if item is None:
            continue
        srcs = list(session.scalars(
            select(Source).join(ItemSource, ItemSource.source_id == Source.id)
            .where(ItemSource.item_id == iid).order_by(Source.id)))
        src = srcs[0] if srcs else None
        outlet = src.name if src else ""
        photo_ok = photo_eligible(s.kind for s in srcs)
        out.append({"item_id": iid, "title": item.title, "outlet": outlet,
                    "url": safe_url(item.url), "published_at": _iso(item.published_at),
                    "image_url": safe_image_url(item.image_url) if photo_ok else None,
                    "paywall": bool(src and src.paywall) or "paywall" in outlet.lower(),
                    "gnews": bool(src and src.kind == "gnews") or "google news" in outlet.lower()})
    return out


def _card_view(session: Session, c: Card) -> dict:
    cluster = session.get(Cluster, c.cluster_id)
    sources = _sources(session, c.cited_item_ids)
    return {"id": c.id, "rank": c.rank, "cluster_id": c.cluster_id, "thread_id": c.thread_id,
            "chapter": c.chapter, "format": c.format, "visual": c.visual or "none",
            "slides": list(c.slides or []), "stack": _stack_rows(c.stack), "tone": c.tone, "payload": c.payload, "headline": c.headline,
            "line": c.line, "para": c.para, "brief": c.brief, "why": c.why,
            "est_seconds": c.est_seconds, "cited_item_ids": list(c.cited_item_ids or []),
            "breaking": bool(c.breaking), "unverified": bool(c.unverified),
            "topics": list(cluster.topics or []) if cluster else [],
            "sources": sources, "n_sources": len(sources)}


def strip_outlet(title: str, *, gnews: bool) -> str:
    """Drop a trailing `` - <Outlet>`` when the remainder is short, for Google News titles only
    (other sources' dashes belong to the headline)."""
    title = (title or "").strip()
    if not gnews:
        return title
    i = title.rfind(" - ")
    if i > 0 and len(title) - (i + 3) < 40:
        return title[:i].rstrip()
    return title


def latest_title(session: Session, cluster_id: str) -> str:
    """The newest item's title in the cluster, without its outlet suffix ("" when none)."""
    row = session.execute(
        select(Item.id, Item.title).join(ClusterItem, ClusterItem.item_id == Item.id)
        .where(ClusterItem.cluster_id == cluster_id)
        .order_by(Item.published_at.desc()).limit(1)).first()
    if row is None:
        return ""
    gnews = session.scalars(
        select(Source.id).join(ItemSource, ItemSource.source_id == Source.id)
        .where(ItemSource.item_id == row[0], Source.kind == "gnews").limit(1)).first() is not None
    return strip_outlet(row[1] or "", gnews=gnews)


def _also_line(session: Session, a: AlsoHappened) -> str:
    """The stored line, except that a stored classifier reason (older builds) shows the
    latest item's title instead, so a re-render shows facts without a backfill."""
    cluster = session.get(Cluster, a.cluster_id)
    if cluster is not None and cluster.reason and a.line == cluster.reason:
        return latest_title(session, a.cluster_id) or a.line
    return a.line


def _also_topic(session: Session, a: AlsoHappened) -> str:
    cluster = session.get(Cluster, a.cluster_id)
    return primary_topic(cluster.topics if cluster is not None else None)


def edition_view(session: Session, edition: Edition) -> dict:
    cards = session.scalars(select(Card).where(Card.edition_id == edition.id)).all()
    # breaking cards (rank 0) lead; then everything in rank order
    cards = sorted(cards, key=lambda c: (not c.breaking, c.rank, c.id))
    views = [_card_view(session, c) for c in cards]
    also = session.scalars(select(AlsoHappened).where(AlsoHappened.edition_id == edition.id)
                           .order_by(AlsoHappened.rank)).all()
    return {"id": edition.id, "date": edition.date.isoformat(), "built_at": _iso(edition.built_at),
            "budget_seconds": edition.budget_seconds, "cut_score": edition.cut_score,
            "cards": views,
            "top_ids": list(edition.top_ids or []), "warnings": list(edition.warnings or []),
            "live": dict(edition.live or {}),
            "also": [{"rank": a.rank, "line": _also_line(session, a), "cluster_id": a.cluster_id,
                      "cut_reason": a.cut_reason, "is_top": bool(a.is_top),
                      "folded": bool(a.folded), "topic": _also_topic(session, a)} for a in also],
            "counts": {"cards": len(views),
                       "est_minutes": round(sum(v["est_seconds"] for v in views) / 60),
                       "saved": 0, "breaking": sum(1 for v in views if v["breaking"])}}


MAX_URGENT = 2  # breaking cards with the tomato bar per edition (spec 3.6)


def read_time(seconds: int) -> str:
    """``35 sec`` under a minute, else whole minutes (``2 min``)."""
    seconds = int(seconds or 0)
    return f"{seconds} sec" if seconds < 60 else f"{max(1, round(seconds / 60))} min"


def short_date(d: date) -> str:
    """``Fri 30 Oct``."""
    return f"{d:%a} {d.day} {d:%b}"


def next_edition(d: date) -> str:
    """``Saturday morning, 31 October`` for the day after ``d``."""
    n = d + timedelta(days=1)
    return f"{n:%A} morning, {n.day} {n:%B}"


def chapter_date(value) -> str:
    """An ISO date as ``30 Oct``; anything else unchanged."""
    try:
        d = date.fromisoformat(str(value)[:10])
    except ValueError:
        return str(value or "")
    return f"{d.day} {d:%b}"


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def _present(ctx: dict, cfg: EditionConfig) -> None:
    """Add the template-only extras (world, vis, ...) to each card of the template context."""
    previous: list[str] = []
    position = 0
    urgent = 0
    for c in ctx["cards"]:
        # tomato is for urgent news only: the first two breaking cards get the bar
        c["urgent"] = bool(c["breaking"]) and urgent < MAX_URGENT
        urgent += c["urgent"]
        vis = visual_for(c)
        world = colour_world(c, position=position, previous=previous, cfg=cfg, visual=vis["kind"])
        c["lead"] = position == 0 and not c["breaking"]
        if not c["breaking"]:  # the lead is the first story that is not breaking news
            position += 1
        previous.append(world.name)
        if vis["kind"] == "chart":
            vis["payload"] = _chart(vis["payload"] or {})
        elif vis["kind"] == "table":
            vis["payload"] = _table(vis["payload"] or {})
        elif vis["kind"] == "number":
            vis["payload"] = {**(vis["payload"] or {}), "bars": number_bars(vis["payload"] or {})}
        elif vis["kind"] == "changes":
            p = vis["payload"] or {}
            vis["payload"] = {**p, "bar": date_bar(p.get("from"), p.get("to"), date.fromisoformat(ctx["date"]))}
        elif vis["kind"] == "countdown":
            vis["payload"] = {**vis["payload"], **countdown_days(vis["payload"]["date"], date.fromisoformat(ctx["date"]))}
        elif vis["kind"] == "timeline":
            p = dict(vis["payload"] or {})
            p["chapters"] = [{**ch, "date": chapter_date(ch.get("date"))} for ch in p.get("chapters") or []]
            vis["payload"] = p
        c["world"] = world
        c["style"] = world.style()
        c["vis"] = vis
        c["headline_first"] = not c["slides"] and vis["kind"] in HEADLINE_FIRST
        if c["slides"]:
            c["deck"] = deck_for(c, world)
        c["topic_name"] = topic_name(c["topics"])
        c["read_time"] = read_time(c["est_seconds"])
        c["brief_paras"] = _paragraphs(c["brief"])
    ctx["live_src"] = live_sources(cfg)
    for a in ctx["also"]:
        f = topic_family(a.get("topic"), cfg)
        # the number is text, so by day it takes the family ink (the accent is a mark colour)
        a["style"] = f"--l-accent:{f.ink};--d-accent:{f.night_accent}"
    ctx["also_lines"] = [a for a in ctx["also"] if not a["folded"]]
    ctx["also_folds"] = also_folds([a for a in ctx["also"] if a["folded"]])
    ctx["tune"] = tune_chips(ctx, per_topic=cfg.also_per_topic)


def live_sources(cfg: EditionConfig) -> dict:
    """The URLs the page refreshes the live tiles from (the same ones the build used)."""
    live = cfg.live or {}
    aqi, fx = live.get("aqi") or {}, live.get("fixtures") or {}
    out: dict = {}  # the market tile has no refresh: Yahoo refuses Vercel's servers
    if "lat" in aqi and "lon" in aqi:
        out["aqi"] = aqi_url(lat=aqi["lat"], lon=aqi["lon"])
    if "team_id" in fx:
        out["match"] = schedule_url(fx["team_id"])
        out["team_id"] = int(fx["team_id"])
        team = fx.get("team", "")
        out["short"] = SHORT_NAMES.get(team.lower(), team)
    return out


def _fold_phrase(reason: str | None) -> str:
    if reason and reason.startswith("topic cap"):
        return "cut by the topic cap"
    if reason == "duplicate thread home":
        return "cut as duplicates"
    return f"cut: {reason}" if reason else "cut"


def also_folds(rows: list[dict]) -> list[dict]:
    """Folded also rows grouped by primary topic, in first-seen order, each with its one
    visible label: "+N more <Topic> stories <the group's most common cut reason>"."""
    groups: dict[str, list[dict]] = {}
    for a in rows:
        groups.setdefault(a["topic"], []).append(a)
    out = []
    for topic, items in groups.items():
        reason = Counter(a["cut_reason"] for a in items).most_common(1)[0][0]
        n = len(items)
        label = (f"+{n} more {topic_name([topic])} {'story' if n == 1 else 'stories'} "
                 f"{_fold_phrase(reason)}")
        out.append({"topic": topic, "label": label, "rows": items})
    return out


def _static(name: str) -> str:
    return resources.files("newshouse").joinpath("static", name).read_text(encoding="utf-8")


def _copy_fonts(out_dir: Path) -> None:
    """Copy the packaged woff2 files to ``out/fonts/``, skipping files already there at the same size."""
    dest = out_dir / "fonts"
    dest.mkdir(parents=True, exist_ok=True)
    for f in resources.files("newshouse").joinpath("static", "fonts").iterdir():
        if not f.name.endswith(".woff2"):
            continue
        target = dest / f.name
        with resources.as_file(f) as src:
            if target.exists() and target.stat().st_size == Path(src).stat().st_size:
                continue
            shutil.copyfile(src, target)


def _env() -> Environment:
    env = Environment(loader=PackageLoader("newshouse", "templates"), autoescape=True)
    env.globals["value_class"] = value_class
    return env


def _css() -> str:
    return _static("fonts.css") + "\n" + _static("edition.css")


def render_index(session: Session, out_dir: Path) -> Path:
    """Write ``index.html``: every built edition, newest first, linking to its page."""
    totals = {eid: (n, secs or 0) for eid, n, secs in session.execute(
        select(Card.edition_id, func.count(Card.id), func.sum(Card.est_seconds)).group_by(Card.edition_id))}
    editions = session.scalars(select(Edition).where(Edition.built_at.is_not(None))
                               .order_by(Edition.date.desc())).all()
    rows = []
    for e in editions:
        n, secs = totals.get(e.id, (0, 0))
        rows.append({"date": e.date.isoformat(), "label": f"{e.date:%A} {e.date.day} {e.date:%B %Y}",
                     "cards": n, "minutes": round(secs / 60)})
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "index.html"
    path.write_text(_env().get_template("index.html.j2").render(rows=rows, css=_css()), encoding="utf-8")
    return path


def render_edition(session: Session, edition: Edition, out_dir: Path, *, validate: bool = False,
                   cfg=None, profile_text: str = "", banned=None) -> Path:
    """Write the edition's HTML and JSON. With ``validate`` the edition validator runs in
    report mode first (no model, no retry, no fallback) and its problems become the warnings."""
    if validate:
        from newshouse.validate import Banned, validate_edition  # validate imports this module
        problems = validate_edition(session, edition, cfg=cfg or EditionConfig(),
                                    profile_text=profile_text, banned=banned or Banned())
        # fallback warnings are facts about the build, not re-derivable from the stored card
        kept = [w for w in edition.warnings or [] if w.get("rule") == "payload-fallback"]
        edition.warnings = [{"rule": p.rule, "text": p.text, "card_id": p.card_id}
                            for p in problems] + kept
        session.flush()
    view = edition_view(session, edition)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ctx = copy.deepcopy(view)  # template-only extras stay out of the JSON
    _present(ctx, cfg if cfg is not None else load_edition_config(Settings().edition_config_path))
    _copy_fonts(out_dir)
    d = edition.date
    html = _env().get_template("edition.html.j2").render(
        v=ctx, short_date=short_date(d), next_edition=next_edition(d),
        css=_css(), js=_static("edition.js"))
    html_path = out_dir / f"{view['date']}.html"
    html_path.write_text(html, encoding="utf-8")
    (out_dir / f"{view['date']}.json").write_text(json.dumps(view, ensure_ascii=False, indent=2),
                                                  encoding="utf-8")
    render_index(session, out_dir)
    return html_path
