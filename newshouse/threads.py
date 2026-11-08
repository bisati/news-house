"""Link story clusters into ongoing storylines (threads) with chapter numbers."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from importlib import resources

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from newshouse.db import bytes_to_vec, vec_to_bytes
from newshouse.llm.backend import LLMError, cheap_effort
from newshouse.llm.schemas import THREAD_MATCH_SCHEMA
from newshouse.models import Cluster, ClusterItem, Item, Thread

log = logging.getLogger(__name__)


def _system_prompt_text() -> str:
    return resources.files("newshouse.llm").joinpath("prompts/thread_match.system.md").read_text()


def _normalize(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def _cluster_items(session: Session, cluster: Cluster) -> list[Item]:
    return list(session.scalars(
        select(Item).join(ClusterItem, ClusterItem.item_id == Item.id)
        .where(ClusterItem.cluster_id == cluster.id)))


def cluster_centroid(session: Session, cluster: Cluster) -> np.ndarray | None:
    vecs = [bytes_to_vec(i.embedding).copy() for i in _cluster_items(session, cluster)
            if i.embedding is not None]
    if not vecs:
        return None
    return _normalize(np.mean(vecs, axis=0)).astype(np.float32)


def candidate_threads(session: Session, centroid: np.ndarray, *, now: datetime,
                      min_cos: float = 0.70) -> list[Thread]:
    scored: list[tuple[float, Thread]] = []
    for t in session.scalars(select(Thread).where(Thread.closed_at.is_(None),
                                                  Thread.embedding.is_not(None))):
        cos = float(np.dot(_normalize(bytes_to_vec(t.embedding)), centroid))
        if cos >= min_cos:
            scored.append((cos, t))
    scored.sort(key=lambda p: p[0], reverse=True)
    return [t for _, t in scored[:5]]


def _title_of_latest(items: list[Item]) -> str:
    return max(items, key=lambda i: i.published_at).title if items else ""


def match_threads(session: Session, backend, *, now: datetime, model: str = "haiku",
                  batch: int = 50) -> int:
    clusters = list(session.scalars(
        select(Cluster).where(Cluster.scored_at.is_not(None), Cluster.thread_id.is_(None),
                              Cluster.chapter.is_(None)).order_by(Cluster.created_at)))
    processed = 0
    centroids: dict[str, np.ndarray] = {}
    cands: dict[str, list[Thread]] = {}
    items_by: dict[str, list[Item]] = {}
    system = _system_prompt_text()

    def finish_unmatched(c: Cluster) -> None:
        if c.story_type == "saga" or (c.importance or 0) >= 85:
            title = _title_of_latest(items_by[c.id])
            t = Thread(id=uuid.uuid4().hex[:16], title=title, summary=c.reason or title,
                       opened_at=now, last_chapter_at=now,
                       embedding=vec_to_bytes(centroids[c.id]), chapters=1)
            session.add(t)
            c.thread_id = t.id
            c.chapter = 1
        else:
            c.chapter = 0

    def attach(c: Cluster, t: Thread) -> None:
        old = _normalize(bytes_to_vec(t.embedding).copy()) * t.chapters
        c.thread_id = t.id
        c.chapter = t.chapters + 1
        t.chapters += 1
        t.last_chapter_at = now
        t.summary = (t.summary + "\n- " + (c.reason or ""))[:2000]
        t.embedding = vec_to_bytes(_normalize(old + centroids[c.id]))

    def decide_pending(pending: list[Cluster]) -> int:
        if not pending:
            return 0
        blocks = []
        for c in pending:
            lines = [f"### cluster {c.id}"]
            lines += [f"- {i.title}" for i in items_by[c.id][:3]]
            lines.append("candidates:")
            lines += [f"- thread {t.id}: {t.title} — {(t.summary or '')[:300]}"
                      for t in cands[c.id]]
            blocks.append("\n".join(lines))
        user = (f"Match these {len(pending)} clusters. Return one match per cluster_id.\n\n"
                + "\n\n".join(blocks))
        try:
            reply = backend.complete_json(system=system, user=user,
                                          schema=THREAD_MATCH_SCHEMA, model=model,
                                          effort=cheap_effort(model))
        except LLMError as e:
            log.warning("thread match batch failed: %s", e)
            return 0
        chosen: dict[str, str | None] = {}
        for m in reply.get("matches", []) if isinstance(reply, dict) else []:
            if isinstance(m, dict) and isinstance(m.get("cluster_id"), str):
                chosen[m["cluster_id"]] = m.get("thread_id")
        for c in pending:
            tid = chosen.get(c.id)
            t = next((x for x in cands[c.id] if x.id == tid), None) if isinstance(tid, str) else None
            if t is not None:
                attach(c, t)
            else:
                finish_unmatched(c)
        return len(pending)

    # One model call per chunk of `batch` clusters (created_at order). Candidates are
    # computed at the start of each chunk, so threads opened or extended in earlier
    # chunks are visible; threads opened within the same chunk are not (accepted gap).
    for start in range(0, len(clusters), batch):
        chunk = clusters[start:start + batch]
        with_cands: list[Cluster] = []
        without: list[Cluster] = []
        for c in chunk:
            items_by[c.id] = _cluster_items(session, c)
            cen = cluster_centroid(session, c)
            if cen is None:
                c.chapter = 0
                processed += 1
                continue
            centroids[c.id] = cen
            cands[c.id] = candidate_threads(session, cen, now=now)
            (with_cands if cands[c.id] else without).append(c)
        processed += decide_pending(with_cands)
        for c in without:
            finish_unmatched(c)
            processed += 1
        session.flush()
    session.flush()
    return processed


def close_quiet_threads(session: Session, *, now: datetime, days: int = 30) -> int:
    cutoff = now - timedelta(days=days)
    n = 0
    for t in session.scalars(select(Thread).where(Thread.closed_at.is_(None),
                                                  Thread.last_chapter_at < cutoff)):
        t.closed_at = now
        n += 1
    session.flush()
    return n
