"""The daily build: one idempotent edition per profile and date."""
from __future__ import annotations

import hashlib
import logging
import time
import uuid
from contextlib import contextmanager
from datetime import date as date_, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from newshouse.classify import classify_clusters
from newshouse.cluster import cluster_fresh_items
from newshouse.config import Settings
from newshouse.edition_config import EditionConfig, load_edition_config
from newshouse.embed import embed_new_items
from newshouse.enrich import enrich_clusters
from newshouse.live import fetch_live
from newshouse.lessons import make_stubs, read_lessons
from newshouse.llm.backend import snapshot_of, usage_delta
from newshouse.models import AlsoHappened, Card, Cluster, ClusterItem, Edition, Feedback, Item, Run
from newshouse.profile import load_profile
from newshouse.render_static import edition_view, latest_title
from newshouse.select import score_and_select, stack_seconds
from newshouse.stacks import MAX_STACKS, headline_rows, write_stack_lines
from newshouse.threads import close_quiet_threads, match_threads
from newshouse.catalogue import visual_seconds
from newshouse.validate import (Banned, Problem, card_problems, cited_items, load_banned,
                                previous_headline, profile_tokens, validate_edition)
from newshouse.write import _fallback, write_card

log = logging.getLogger(__name__)


def get_or_create_edition(session: Session, *, profile_id: str, date: date_,
                          budget_seconds: int) -> Edition:
    ed = session.scalars(select(Edition).where(Edition.profile_id == profile_id,
                                               Edition.date == date)).first()
    if ed is None:
        ed = Edition(id=uuid.uuid4().hex, profile_id=profile_id, date=date,
                     built_at=None, budget_seconds=budget_seconds)
        session.add(ed)
        session.flush()
    return ed


def prune_old(session: Session, *, now: datetime, days: int = 90) -> int:
    items = session.scalars(select(Item).where(Item.first_seen_at < now - timedelta(days=days))).all()
    n = 0
    for it in items:
        if it.body is not None or it.embedding is not None:
            it.body = None
            it.embedding = None
            n += 1
    session.flush()
    return n


def _uncard(session: Session, cluster_ids) -> None:
    for cid in cluster_ids:
        cl = session.get(Cluster, cid)
        if cl is not None:
            cl.carded = False


def _reset_edition(session: Session, edition: Edition) -> None:
    for c in session.scalars(select(Card).where(Card.edition_id == edition.id)).all():
        _uncard(session, [r["cluster_id"] for r in c.stack or []])
        if c.breaking:  # a breaking card stays; the build regroups its stack
            c.est_seconds -= stack_seconds(c.stack)
            c.stack = []
            continue
        _uncard(session, [c.cluster_id])
        session.delete(c)
    session.execute(delete(AlsoHappened).where(AlsoHappened.edition_id == edition.id))
    session.flush()


def _read_chapters(session: Session, cluster: Cluster, edition: Edition) -> frozenset:
    if not cluster.thread_id:
        return frozenset()
    rows = session.scalars(
        select(Card.chapter).join(Edition, Edition.id == Card.edition_id)
        .where(Card.thread_id == cluster.thread_id, Edition.built_at.is_not(None),
               Edition.id != edition.id, Card.chapter.is_not(None),
               select(Feedback.id).where(Feedback.card_id == Card.id,
                                         Feedback.profile_id == edition.profile_id,
                                         Feedback.action.in_(("seen", "read"))).exists()))
    return frozenset(rows)


def _latest_title(session: Session, cluster: Cluster) -> str:
    """The also line: the newest item's title, outlet suffix stripped (a fact, not a reason)."""
    return latest_title(session, cluster.id)


def card_id_for(edition_id: str, cluster_id: str) -> str:
    """A card's id is stable per edition and cluster, so a reaction survives ``build --force``."""
    return hashlib.sha1(f"{edition_id}:{cluster_id}".encode()).hexdigest()[:32]


def _write_cards(session: Session, backend, edition: Edition, selected: list[str], *,
                 profile_text: str, stats: dict) -> None:
    rank = 0
    fallbacks: dict[str, str] = stats.setdefault("write_fallbacks", {})
    tones: dict[str, list] = stats.setdefault("tone_changes", {})
    for cid in selected:
        cluster = session.get(Cluster, cid)
        notes: list[str] = []
        try:
            card = write_card(session, backend, cluster, profile_text=profile_text,
                              read_chapters=_read_chapters(session, cluster, edition), notes=notes)
        except Exception:
            log.exception("write_card failed for cluster %s; storing fallback", cid)
            items = session.scalars(select(Item).join(ClusterItem, ClusterItem.item_id == Item.id)
                                    .where(ClusterItem.cluster_id == cid)).all()
            if not items:
                continue
            card = _fallback(cluster, items)
            cluster.carded = True
            stats["cards_fallback"] += 1
            notes = []
        stable = card_id_for(edition.id, cid)
        if session.get(Card, stable) is None:  # a breaking card may already hold it
            card.id = stable
        if notes:
            fallbacks[card.id] = "; ".join(notes)
        if card.tone and cluster.tone and card.tone != cluster.tone:
            tones[card.id] = [cluster.tone, card.tone]  # Ruling 9: logged, no reason asked
        rank += 1
        card.edition_id, card.rank = edition.id, rank
        session.add(card)
    session.flush()
    stats["cards"] = rank


def _write_stacks(session: Session, backend, edition: Edition, stacks: dict[str, list[str]], *,
                  stats: dict) -> None:
    """Each chosen lead's card gets its members' rows (Ruling 4) and 10 s per member;
    members are carded (printed inside the stack), so they get no card of their own.
    Only the first ``MAX_STACKS`` leads (best score first) get a writer call; the rest get
    headline-only rows. A stack that fails falls back to headline-only rows (a member
    with no readable items is skipped): stacks never fail the build."""
    groups = members_n = failed = capped = 0
    written = 0
    for lead, member_ids in stacks.items():
        card = session.scalars(select(Card).where(Card.edition_id == edition.id,
                                                  Card.cluster_id == lead)).first()
        if card is None:  # the lead's card was never written
            continue
        members = [m for m in (session.get(Cluster, i) for i in member_ids) if m is not None]
        if written < MAX_STACKS:
            written += 1
            try:
                rows = write_stack_lines(card, members, backend)
            except Exception as e:
                log.warning("stack for lead %s failed; headline-only rows: %r", lead, e)
                rows = headline_rows(members)
                failed += len(rows)
            else:
                failed += sum(1 for r in rows if not r["line"])
        else:
            rows = headline_rows(members)
            capped += 1
        if not rows:
            continue
        card.stack = rows
        card.est_seconds += stack_seconds(rows)
        in_rows = {r["cluster_id"] for r in rows}
        for m in members:
            if m.id in in_rows:
                m.carded = True
        groups, members_n = groups + 1, members_n + len(rows)
    session.flush()
    stats["stacks"] = {"groups": groups, "members": members_n, "lines_failed": failed,
                       "capped": capped}


REWRITTEN = ("format", "visual", "payload", "slides", "tone", "headline", "line", "para", "brief",
             "why", "est_seconds", "cited_item_ids", "unverified")
NO_RETRY = {"headline-long"}  # Ruling 8: a soft rule is not worth an Opus call
FALLBACK_RULES = {"payload", "slides"}


def _candidate_problems(session: Session, view: dict, new: Card, *, profile: set[str],
                        banned: Banned) -> list[Problem]:
    """Validator problems the card would carry with the new reply's fields."""
    cand = {**view, **{f: getattr(new, f) for f in REWRITTEN}}
    items = set(session.scalars(select(ClusterItem.item_id)
                                .where(ClusterItem.cluster_id == cand["cluster_id"])))
    return card_problems(cand, profile=profile, banned=banned,
                         previous_headline=previous_headline(session, cand), cluster_item_ids=items,
                         items=cited_items(session, cand))


def _retry_card(session: Session, backend, edition: Edition, card: Card, view: dict,
                problems: list[Problem], *, profile_text: str, banned: Banned,
                write_fallbacks: dict[str, str]) -> None:
    """One more model attempt with the problems; keep it only if it is strictly better.
    A kept reply replaces the card's write-time fallback note with its own (or none)."""
    cluster = session.get(Cluster, card.cluster_id)
    notes: list[str] = []
    try:
        new = write_card(session, backend, cluster, profile_text=profile_text,
                         read_chapters=_read_chapters(session, cluster, edition),
                         problems=[p.text for p in problems], notes=notes)
    except Exception:
        log.exception("validator retry failed for card %s; keeping it", card.id)
        return
    if new.unverified:  # write_card fell back: the reply failed validate_card
        return
    after = _candidate_problems(session, view, new, profile=profile_tokens(profile_text),
                                banned=banned)
    # a visual fallback (the reply's deck or payload failed) counts as a problem on
    # either side, so a text fix never trades away a working visual
    if len(after) + bool(notes) < len(problems) + (card.id in write_fallbacks):
        for f in REWRITTEN:
            setattr(card, f, getattr(new, f))
        card.est_seconds += stack_seconds(card.stack)  # the new reply knows nothing of it
        write_fallbacks.pop(card.id, None)
        if notes:
            write_fallbacks[card.id] = "; ".join(notes)


def apply_validation(session: Session, backend, edition: Edition, *, cfg: EditionConfig,
                     profile_text: str, banned: Banned, stats: dict,
                     lessons=None, noise_floor: int | None = None,
                     window_hours: int | None = None,
                     now: datetime | None = None) -> list[Problem]:
    """Validate the written edition, give each failing card one more attempt, fall back
    on a still-broken payload or deck, and store what remains (plus the writer's own
    visual fallbacks, ``stats["write_fallbacks"]``) as the edition's warnings."""
    write_fallbacks: dict[str, str] = stats.setdefault("write_fallbacks", {})
    owed = {"lessons": lessons, "noise_floor": noise_floor, "window_hours": window_hours,
            "now": now}  # built_at is set after validation (and is stale on a --force rebuild)
    before = validate_edition(session, edition, cfg=cfg, profile_text=profile_text, banned=banned,
                              **owed)
    by_card: dict[str, list[Problem]] = {}
    for p in before:
        if p.card_id is not None:  # edition-level rules (count, floor, top, thread) never retry
            by_card.setdefault(p.card_id, []).append(p)
    by_card = {k: ps for k, ps in by_card.items() if any(p.rule not in NO_RETRY for p in ps)}
    if by_card:
        views = {v["id"]: v for v in edition_view(session, edition)["cards"]}
        for card_id, problems in by_card.items():
            _retry_card(session, backend, edition, session.get(Card, card_id), views[card_id],
                        problems, profile_text=profile_text, banned=banned,
                        write_fallbacks=write_fallbacks)
        session.flush()
    after = validate_edition(session, edition, cfg=cfg, profile_text=profile_text, banned=banned,
                             **owed)
    broken: dict[str, list[str]] = {}
    for p in after:
        if p.rule in FALLBACK_RULES:
            broken.setdefault(p.card_id, []).append(p.text)
    fallbacks: list[Problem] = []
    for card_id, texts in broken.items():
        card = session.get(Card, card_id)
        card.format, card.payload, card.visual, card.slides = "A", {}, "none", []
        card.est_seconds = visual_seconds("none", []) + stack_seconds(card.stack)
        write_fallbacks.pop(card_id, None)  # this warning says it now
        fallbacks.append(Problem("payload-fallback",
                                 f"{card.headline or card.id}: {'; '.join(texts)}", card.id))
    if fallbacks:  # describe the edition as it now is (minutes change with the format)
        session.flush()
        after = validate_edition(session, edition, cfg=cfg, profile_text=profile_text,
                                 banned=banned, **owed)
    remaining = after + fallbacks + [Problem("payload-fallback", text, card_id)
                                     for card_id, text in write_fallbacks.items()]
    edition.warnings = [{"rule": p.rule, "text": p.text, "card_id": p.card_id} for p in remaining]
    session.flush()
    stats["validator"] = {"problems": len(before), "retried": len(by_card),
                          "warnings": len(remaining), "fallbacks": len(fallbacks)}
    return remaining


def _run_stages(session: Session, backend, edition: Edition, *, settings: Settings,
                now: datetime, client, embedder, stats: dict,
                cfg: EditionConfig) -> None:
    secs: dict[str, float] = stats["seconds"]
    usage: dict[str, dict] = stats.setdefault("usage", {})

    @contextmanager
    def timed(name):
        t0 = time.monotonic()
        u0 = snapshot_of(backend)
        try:
            yield
        finally:
            secs[name] = round(time.monotonic() - t0, 3)
            d = usage_delta(u0, snapshot_of(backend))
            if d:
                usage[name] = d

    lessons = read_lessons(settings.lessons_path)  # stubbed by build_edition, before any reset
    with timed("profile"):
        profile = load_profile(session, settings)
        stats["profile_version"] = profile.version
    with timed("embed"):
        stats["items_embedded"] = embed_new_items(session, embedder)
    with timed("cluster"):
        stats["clusters_new"] = len(cluster_fresh_items(
            session, backend, now=now, window_hours=settings.cluster_window_hours))
    with timed("classify"):
        stats["clusters_scored"] = classify_clusters(
            session, backend, profile_text=profile.text, batch=settings.classify_batch,
            now=now, profile_id=settings.profile_id, lessons_path=settings.lessons_path)
    with timed("threads"):
        stats["threads_matched"] = match_threads(session, backend, now=now)
        stats["threads_closed"] = close_quiet_threads(session, now=now)
    with timed("select"):
        sel = score_and_select(session, now=now, settings=settings, cfg=cfg, edition=edition,
                               backend=backend)
        stats["selected"], stats["also"] = len(sel.selected), len(sel.also)
        stats["tune"] = sel.tune
        stats["cuts"], stats["unmet_floors"] = sel.cuts, sel.unmet_floors
        edition.top_ids = list(sel.top_ids)
    with timed("live"):  # never raises: a failed fetch is a missing tile
        try:
            edition.live = fetch_live(client, cfg, now=now)
        except Exception as e:  # e.g. a malformed live block in the edition config
            log.warning("live tiles skipped: %r", e)
            edition.live = {}
        stats["live"] = sorted(edition.live)
    # the breaking lane may have made the row; a tune tap may have moved today's budget
    edition.budget_seconds = sel.budget_seconds
    with timed("enrich"):
        stats["bodies"] = enrich_clusters(session, sel.selected, client=client)
    with timed("write"):
        _write_cards(session, backend, edition, sel.selected,
                     profile_text=profile.text, stats=stats)
    with timed("stacks"):
        _write_stacks(session, backend, edition, sel.stacks, stats=stats)
    with timed("also"):
        reasons: dict[str, str] = {}
        rows = [(cid, False) for cid in sel.also] + [(cid, True) for cid in sel.folded]
        for n, (cid, folded) in enumerate(rows, start=1):
            cluster = session.get(Cluster, cid)
            reasons[cid] = cluster.reason or ""
            session.add(AlsoHappened(edition_id=edition.id, cluster_id=cid, rank=n,
                                     line=_latest_title(session, cluster) or cluster.reason or "",
                                     cut_reason=sel.cuts.get(cid), is_top=cid in sel.top_ids,
                                     folded=folded))
        stats["also_reasons"] = reasons  # the classifier's why, for the run log only
        session.flush()
    with timed("validate"):  # after "also": the top-story rule reads the cut reasons
        apply_validation(session, backend, edition, cfg=cfg, profile_text=profile.text,
                         banned=load_banned(), stats=stats, lessons=lessons,
                         noise_floor=settings.noise_floor,
                         window_hours=settings.cluster_window_hours, now=now)
    edition.built_at = datetime.now(timezone.utc)  # wall clock; `now` dates the edition
    edition.cut_score = sel.cut_score
    edition.profile_version = profile.version
    session.flush()


def _stub_lessons(session: Session, settings: Settings, *, now: datetime, stats: dict) -> None:
    t0 = time.monotonic()
    try:
        stats["lesson_stubs"] = make_stubs(
            session, settings.lessons_path, profile_id=settings.profile_id,
            today=now.astimezone(ZoneInfo(settings.tz)).date())
    except Exception as e:  # a broken ledger file must not stop the edition
        log.warning("lesson stubs skipped: %r", e)
        stats["lesson_stubs"] = 0
    stats["seconds"]["lessons"] = round(time.monotonic() - t0, 3)


def build_edition(session: Session, backend, *, settings: Settings, now: datetime, client,
                  embedder, force: bool = False, date: date_ | None = None,
                  cfg: EditionConfig | None = None) -> Edition | None:
    day = date or now.astimezone(ZoneInfo(settings.tz)).date()
    if cfg is None:
        cfg = load_edition_config(settings.edition_config_path)
    edition = get_or_create_edition(session, profile_id=settings.profile_id, date=day,
                                    budget_seconds=cfg.budget_seconds)
    if edition.built_at is not None and not force:
        return edition
    run = Run(id=uuid.uuid4().hex, kind="build", started_at=now, status="running", stats={})
    session.add(run)
    session.commit()  # the Run row survives a failed build
    edition_id, run_id = edition.id, run.id
    stats: dict = {"cards_fallback": 0, "seconds": {}, "usage": {}}
    try:
        # stubs for "Should have been in" taps (ruling 8: here, not the server), before a
        # forced reset deletes today's also rows the taps point at
        _stub_lessons(session, settings, now=now, stats=stats)
        if force:
            _reset_edition(session, edition)
        _run_stages(session, backend, edition, settings=settings, now=now, client=client,
                    embedder=embedder, stats=stats, cfg=cfg)
        run.status, run.stats, run.finished_at = "ok", stats, datetime.now(timezone.utc)
        session.commit()
    except Exception as e:
        session.rollback()
        run = session.get(Run, run_id)
        run.status, run.error, run.stats = "error", str(e), stats
        run.finished_at = datetime.now(timezone.utc)
        session.commit()
        raise
    return session.get(Edition, edition_id)
