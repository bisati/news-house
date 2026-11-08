"""Classify and score fresh clusters against the owner's profile."""
from __future__ import annotations

import logging
from datetime import datetime
from importlib import resources
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from newshouse.catalogue import TONES
from newshouse.lessons import read_lessons, recent
from newshouse.llm.backend import LLMError, cheap_effort
from newshouse.llm.schemas import CLASSIFY_SCHEMA, STORY_TYPES
from newshouse.models import Card, Cluster, ClusterItem, Feedback, Item, ItemSource, Source

log = logging.getLogger(__name__)

KNOWN_TOPICS = {"ai-models", "ai-built", "startups", "ai-tools", "india-tech-biz", "intl-biz-tech", "edtech-competitors",
                "product-design", "solutions", "geopolitics", "india-news", "gurgaon-local",
                "movies", "football", "cricket", "tennis-f1"}


def _system_prompt_text() -> str:
    return resources.files("newshouse.llm").joinpath("prompts/classify.system.md").read_text()


def feedback_examples(session: Session, *, profile_id: str = "mihir",
                      n: int = 20) -> tuple[list[str], list[str]]:
    rows = session.execute(
        select(Feedback.card_id, Feedback.action, Feedback.at)
        .where(Feedback.profile_id == profile_id, Feedback.card_id.is_not(None))
        .order_by(Feedback.at.desc())
    ).all()
    latest: dict[str, str] = {}
    order: list[str] = []
    for card_id, action, _at in rows:  # newest first: first seen is latest
        if card_id not in latest:
            latest[card_id] = action
            order.append(card_id)
    headlines = dict(session.execute(
        select(Card.id, Card.headline).where(Card.id.in_(order))).all()) if order else {}
    pos: list[str] = []
    neg: list[str] = []
    for cid in order:
        if cid not in headlines:
            continue
        act = latest[cid]
        if act in ("worth", "later") and len(pos) < n:
            pos.append(headlines[cid])
        elif act == "skip" and len(neg) < n:
            neg.append(headlines[cid])
    return pos, neg


def lessons_block(path: Path | None = None) -> str:
    """``## Lessons``: the last ten lessons, each ``- <miss>`` plus `` Fix: <fix>``."""
    if path is None:
        from newshouse.config import get_settings
        path = get_settings().lessons_path
    lines = [f"- {l.miss}" + (f" Fix: {l.fix}" if l.fix.strip() else "")
             for l in recent(read_lessons(path), n=10)]
    return "\n\n## Lessons\n" + "\n".join(lines) if lines else ""


def render_cluster_for_classify(cluster: Cluster, items: list[Item],
                                sources_by_item: dict[str, list[Source]],
                                *, now: datetime | None = None) -> str:
    from datetime import timezone
    now = now or datetime.now(timezone.utc)
    names: list[str] = []
    for it in items:
        for s in sources_by_item.get(it.id, []):
            label = f"{s.name} ({s.tier})"
            if label not in names:
                names.append(label)
    recent = sorted(items, key=lambda i: i.published_at, reverse=True)[:5]
    lines = [f"### cluster {cluster.id}",
             f"topics: {', '.join(cluster.topics or [])}",
             f"sources: {', '.join(names[:8])}",
             f"items: {len(items)}"]
    for it in recent:
        hours = max(0, round((now - it.published_at).total_seconds() / 3600))
        lines.append(f"- [{hours}h] {it.title} — {(it.teaser or '')[:300]}")
    return "\n".join(lines)


def _clamp(v, default: int = 0) -> int:
    try:
        return max(0, min(100, int(v)))
    except (TypeError, ValueError):
        return default


def _load_batch_context(session: Session, clusters: list[Cluster]):
    ids = [c.id for c in clusters]
    items_by_cluster: dict[str, list[Item]] = {c.id: [] for c in clusters}
    for cid, item in session.execute(
            select(ClusterItem.cluster_id, Item).join(Item, Item.id == ClusterItem.item_id)
            .where(ClusterItem.cluster_id.in_(ids))).all():
        items_by_cluster[cid].append(item)
    item_ids = [i.id for lst in items_by_cluster.values() for i in lst]
    sources_by_item: dict[str, list[Source]] = {}
    if item_ids:
        for iid, src in session.execute(
                select(ItemSource.item_id, Source).join(Source, Source.id == ItemSource.source_id)
                .where(ItemSource.item_id.in_(item_ids))).all():
            sources_by_item.setdefault(iid, []).append(src)
    return items_by_cluster, sources_by_item


def classify_clusters(session: Session, backend, *, profile_text: str, batch: int = 50,
                      model: str = "haiku", now: datetime, profile_id: str = "mihir",
                      lessons_path: Path | None = None) -> int:
    """``lessons_path``: the lessons ledger (default: the settings' ``lessons_path``)."""
    clusters = list(session.scalars(
        select(Cluster).where(Cluster.scored_at.is_(None)).order_by(Cluster.created_at)))
    if not clusters:
        return 0
    system = _system_prompt_text() + "\n\n## Profile\n" + profile_text
    pos, neg = feedback_examples(session, profile_id=profile_id)
    if pos or neg:
        system += "\n\n## Recent reactions"
        if pos:
            system += "\nWorth it:\n" + "\n".join(f"- {h}" for h in pos)
        if neg:
            system += "\nSkipped:\n" + "\n".join(f"- {h}" for h in neg)
    system += lessons_block(lessons_path)
    scored = 0
    for start in range(0, len(clusters), batch):
        chunk = clusters[start:start + batch]
        items_by_cluster, sources_by_item = _load_batch_context(session, chunk)
        blocks = [render_cluster_for_classify(c, items_by_cluster[c.id], sources_by_item, now=now)
                  for c in chunk]
        user = (f"Score these {len(chunk)} clusters. Return one result per cluster_id.\n\n"
                + "\n\n".join(blocks))
        try:
            reply = backend.complete_json(system=system, user=user, schema=CLASSIFY_SCHEMA,
                                          model=model, effort=cheap_effort(model))
        except LLMError as e:
            log.warning("classify batch %d failed: %s", start // batch, e)
            continue
        by_id = {c.id: c for c in chunk}
        for r in reply.get("results", []) if isinstance(reply, dict) else []:
            c = by_id.get(r.get("cluster_id")) if isinstance(r, dict) else None
            if c is None:
                continue
            st = r.get("story_type")
            c.story_type = st if st in STORY_TYPES else "plain"
            c.importance = _clamp(r.get("importance"))
            c.early = _clamp(r.get("early"))
            topics = r.get("topics")
            if (isinstance(topics, list) and topics
                    and all(isinstance(t, str) and t in KNOWN_TOPICS for t in topics)):
                c.topics = list(topics)
            c.reason = str(r.get("reason", ""))[:300]
            c.breaking_eligible = bool(r.get("breaking_eligible", False))
            c.is_delta = bool(r.get("is_delta", True))
            tone = r.get("tone")
            c.tone = tone if isinstance(tone, str) and tone in TONES else None
            c.scored_at = now
            scored += 1
        session.flush()
    return scored
