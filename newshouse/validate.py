"""Edition-level validator: reads an edition's view and returns problems.

It never writes to the database and never raises on content. Reports problems
without fixing them.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from newshouse.catalogue import ItemFacts, effective_visual, payload_problems, slide_problems
from newshouse.edition_config import EditionConfig
from newshouse.lessons import Lesson, read_lessons
from newshouse.models import Card, Cluster, ClusterItem, Edition, Item, ItemSource, Source
from newshouse.present import visual_for
from newshouse.render_static import edition_view
from newshouse.select import primary_topic
from newshouse.write import item_facts

TEXT_FIELDS = ("headline", "line", "para", "brief", "why")
STOPWORDS = {"that", "this", "with", "from", "have", "they", "them", "their", "what", "when", "which",
             "your", "will", "more", "than", "into", "about", "also", "been", "were", "there", "these"}
MINUTES_MIN, MINUTES_MAX = 12, 24  # about 20 minutes, up to 36 posts
HEADLINE_MAX_WORDS, LINE_MAX_WORDS = 12, 40
REPEAT_SHARE = 0.6


@dataclass
class Problem:
    rule: str
    text: str
    card_id: str | None = None


class Banned(BaseModel):
    words: list[str] = []
    patterns: list[str] = []


def load_banned(path: Path = Path("config/banned.yaml")) -> Banned:
    raw = yaml.safe_load(path.read_text()) or {}
    return Banned(**raw)


def profile_tokens(profile_text: str) -> set[str]:
    """Lowercase alphabetic tokens of 4+ letters, minus stopwords."""
    return set(re.findall(r"[a-z]{4,}", (profile_text or "").lower())) - STOPWORDS


def _word_tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


# --- card rules -------------------------------------------------------------

def _length_problems(card: dict) -> list[Problem]:
    out = []
    n = len((card.get("headline") or "").split())
    if n > HEADLINE_MAX_WORDS:
        out.append(Problem("headline-long", f"headline has {n} words (max {HEADLINE_MAX_WORDS})", card["id"]))
    n = len((card.get("line") or "").split())
    if n > LINE_MAX_WORDS:
        out.append(Problem("gist-long", f"line has {n} words (max {LINE_MAX_WORDS})", card["id"]))
    return out


def _why_problems(card: dict, profile: set[str]) -> list[Problem]:
    why = card.get("why") or ""
    if why.strip() and not (profile_tokens(why) & profile):
        return [Problem("why-generic", "why shares no word with the reader's profile", card["id"])]
    return []


def _banned_problems(card: dict, banned: Banned) -> list[Problem]:
    out = []
    for f in TEXT_FIELDS:
        text = card.get(f) or ""
        words = [w for w in banned.words if re.search(rf"\b{re.escape(w)}\b", text, re.IGNORECASE)]
        if words:
            out.append(Problem("banned-word", f"{f} uses banned words: {', '.join(words)}", card["id"]))
        pats = [p for p in banned.patterns if re.search(p, text)]
        if pats:
            out.append(Problem("banned-pattern", f"{f} matches banned patterns: {', '.join(pats)}", card["id"]))
    return out


def _repeat_problems(card: dict, previous_headline: str | None) -> list[Problem]:
    if (card.get("chapter") or 0) < 2 or not previous_headline:
        return []
    mine, prev = _word_tokens(card.get("headline")), _word_tokens(previous_headline)
    if mine and len(mine & prev) / len(mine) >= REPEAT_SHARE:
        return [Problem("chapter-repeats", f"headline repeats chapter {card['chapter'] - 1}: "
                        f"{previous_headline!r}", card["id"])]
    return []


def _payload_rule(card: dict, items: dict[str, ItemFacts]) -> list[Problem]:
    cited = set(card.get("cited_item_ids") or [])
    visual = effective_visual(card.get("visual"), card.get("format"))
    payload = card.get("payload")
    if visual == "cover" and not (isinstance(payload, dict) and str(payload.get("big") or "").strip()):
        visual = "none"  # a stored automatic cover (before 2026-11-05) renders as no visual
    issues = payload_problems(visual, card.get("payload"), cited=cited, items=items,
                              expected_chapters=None)
    return [Problem("payload", "; ".join(issues), card["id"])] if issues else []


def _slides_rule(card: dict, items: dict[str, ItemFacts]) -> list[Problem]:
    slides = card.get("slides") or []
    if not slides:
        return []
    issues = slide_problems(slides, brief=card.get("brief") or "",
                            cited=set(card.get("cited_item_ids") or []), items=items)
    return [Problem("slides", "; ".join(issues), card["id"])] if issues else []


def _citation_problems(card: dict, cluster_item_ids: set[str]) -> list[Problem]:
    stray = [i for i in card.get("cited_item_ids") or [] if i not in cluster_item_ids]
    if stray:
        return [Problem("citation", f"cited items not in the cluster: {', '.join(stray)}", card["id"])]
    return []


def card_problems(card: dict, *, profile: set[str], banned: Banned, previous_headline: str | None,
                  cluster_item_ids: set[str],
                  items: dict[str, ItemFacts] | None = None) -> list[Problem]:
    """``items``: the card's cited items (see ``cited_items``); the payload and slide
    truth checks read them."""
    items = items or {}
    return (_length_problems(card) + _why_problems(card, profile) + _banned_problems(card, banned)
            + _repeat_problems(card, previous_headline) + _payload_rule(card, items)
            + _slides_rule(card, items) + _citation_problems(card, cluster_item_ids))


def cited_items(session: Session, card: dict) -> dict[str, ItemFacts]:
    """Facts for the card's cited items that exist (images only from non-Google-News sources)."""
    ids = list(dict.fromkeys(card.get("cited_item_ids") or []))
    if not ids:
        return {}
    items = list(session.scalars(select(Item).where(Item.id.in_(ids))))
    sbi: dict[str, list[Source]] = {i.id: [] for i in items}
    for item_id, src in session.execute(
            select(ItemSource.item_id, Source).join(Source, Source.id == ItemSource.source_id)
            .where(ItemSource.item_id.in_(list(sbi)))):
        sbi[item_id].append(src)
    return item_facts(items, sbi)


# --- edition rules ----------------------------------------------------------

def _count_problems(view: dict, cfg: EditionConfig) -> list[Problem]:
    n, out = len(view["cards"]), []
    if n < cfg.cards_floor:
        out.append(Problem("count", f"{n} cards, below the floor of {cfg.cards_floor}"))
    if n > cfg.cards_cap:
        out.append(Problem("count", f"{n} cards, above the cap of {cfg.cards_cap}"))
    minutes = view["counts"]["est_minutes"]
    if n and not MINUTES_MIN <= minutes <= MINUTES_MAX:
        out.append(Problem("count", f"{minutes} minutes, outside {MINUTES_MIN} to {MINUTES_MAX}"))
    return out


def _floor_problems(view: dict, cfg: EditionConfig) -> list[Problem]:
    have = Counter(primary_topic(c["topics"]) for c in view["cards"])
    return [Problem("floor", f"topic {topic} has {have[topic]} cards, below its floor of {rule.min}")
            for topic, rule in cfg.topics.items() if rule.min > 0 and have[topic] < rule.min]


def _top_problems(view: dict) -> list[Problem]:
    printed = {c["cluster_id"] for c in view["cards"]}
    explained = {a["cluster_id"] for a in view["also"] if a["cut_reason"]}
    return [Problem("top-unexplained", f"top story {cid} is neither printed nor explained")
            for cid in view["top_ids"] if cid not in printed and cid not in explained]


def _thread_problems(view: dict) -> list[Problem]:
    homes = Counter(c["thread_id"] for c in view["cards"] if c["thread_id"])
    return [Problem("thread-home", f"thread {tid} has {n} cards in one edition")
            for tid, n in homes.items() if n > 1]


VISUAL_SHARE_MIN = 0.8  # docs/design-visuals.md G1
FORMAT_MIX_MAX, FORMAT_MIX_MIN_POSTS = 1 / 3, 6


def _shown_kind(card: dict) -> str:
    """What the post shows: a deck, its visual (photo fallback included), else none.
    A cover counts as a number (one family for the format-mix cap)."""
    if card.get("slides"):
        return "deck"
    kind = visual_for(card)["kind"]
    return "number" if kind == "cover" else kind


def _visual_problems(view: dict) -> list[Problem]:
    cards = view["cards"]
    if not cards:
        return []
    kinds = Counter(_shown_kind(c) for c in cards)
    out = []
    shown = len(cards) - kinds.get("none", 0)
    if shown / len(cards) < VISUAL_SHARE_MIN:
        out.append(Problem("visual-share", f"{shown} of {len(cards)} posts show a visual "
                           f"(target {VISUAL_SHARE_MIN:.0%})"))
    if len(cards) >= FORMAT_MIX_MIN_POSTS:
        for kind, n in sorted(kinds.items()):
            # photos follow the story's shape (people, disasters, events) and the photo fallback
            if kind not in ("none", "deck", "photo") and n / len(cards) > FORMAT_MIX_MAX:
                out.append(Problem("format-mix", f"{kind} fills {n} of {len(cards)} posts (at most a third)"))
    return out


def _owed_problems(session: Session, view: dict, edition: Edition, lessons: list[Lesson], *,
                   noise_floor: int, window_hours: int,
                   now: datetime | None = None) -> list[Problem]:
    """An open lesson that owes a topic or thread: a cluster scored in this edition's
    window that matches it, at or above the noise floor, and not already printed in
    another edition, must be printed or explained. The window ends at ``now`` (the
    build's clock), else at the edition's ``built_at`` (report mode). One warning per
    lesson, with the count and up to three cluster ids."""
    owed = [l for l in lessons if l.status == "open" and isinstance(l.owed, dict)
            and (l.owed.get("topic") or l.owed.get("thread_id"))]
    if not owed:
        return []
    ref = now or edition.built_at or datetime.now(timezone.utc)
    clusters = session.scalars(select(Cluster).where(
        Cluster.scored_at.is_not(None), Cluster.scored_at <= ref,
        Cluster.scored_at >= ref - timedelta(hours=window_hours),
        Cluster.importance >= noise_floor,
        Cluster.carded == False)).all()  # noqa: E712  (printed elsewhere is carried)
    printed = {c["cluster_id"] for c in view["cards"]}
    explained = {a["cluster_id"] for a in view["also"] if a["cut_reason"]}
    out = []
    for lesson in owed:
        topic, thread = lesson.owed.get("topic"), lesson.owed.get("thread_id")
        missed = sorted((c for c in clusters if c.id not in printed and c.id not in explained
                         and ((topic and primary_topic(c.topics) == topic)
                              or (thread and c.thread_id == thread))),
                        key=lambda c: (-(c.importance or 0), c.id))
        if missed:
            what = f"topic {topic}" if topic else f"thread {thread}"
            ids = ", ".join(c.id for c in missed[:3]) + (", ..." if len(missed) > 3 else "")
            out.append(Problem("owed", f"lesson {lesson.id} owes {what}: {len(missed)} "
                               f"cluster(s) above noise neither printed nor explained ({ids})"))
    return out


def previous_headline(session: Session, card: dict) -> str | None:
    if not card["thread_id"] or (card["chapter"] or 0) < 2:
        return None
    return session.scalars(
        select(Card.headline).join(Edition, Edition.id == Card.edition_id)
        .where(Card.thread_id == card["thread_id"], Card.chapter == card["chapter"] - 1)
        .order_by(Edition.date.desc(), Edition.built_at.desc())).first()


_previous_headline = previous_headline  # the v1 name


def validate_edition(session: Session, edition: Edition, *, cfg: EditionConfig, profile_text: str,
                     banned: Banned, lessons: list[Lesson] | None = None,
                     noise_floor: int | None = None,
                     window_hours: int | None = None,
                     now: datetime | None = None) -> list[Problem]:
    """``now``: the build's clock, the end of the owed window (default: ``built_at``).
    ``lessons``, ``noise_floor`` and ``window_hours`` default to the settings' ledger
    (read tolerantly: a missing or broken file is no lessons), noise floor and cluster
    window."""
    if lessons is None or noise_floor is None or window_hours is None:
        from newshouse.config import get_settings
        settings = get_settings()
        if lessons is None:
            lessons = read_lessons(settings.lessons_path)
        noise_floor = settings.noise_floor if noise_floor is None else noise_floor
        window_hours = settings.cluster_window_hours if window_hours is None else window_hours
    view = edition_view(session, edition)
    profile = profile_tokens(profile_text)
    out = (_count_problems(view, cfg) + _floor_problems(view, cfg) + _top_problems(view)
           + _thread_problems(view) + _visual_problems(view)
           + _owed_problems(session, view, edition, lessons, noise_floor=noise_floor,
                            window_hours=window_hours, now=now))
    for card in view["cards"]:
        items = set(session.scalars(select(ClusterItem.item_id)
                                    .where(ClusterItem.cluster_id == card["cluster_id"])))
        out += card_problems(card, profile=profile, banned=banned,
                             previous_headline=previous_headline(session, card), cluster_item_ids=items,
                             items=cited_items(session, card))
    return out
