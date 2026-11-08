"""Story clustering: embedding similarity plus a cheap model check for borderline pairs."""
from __future__ import annotations

import hashlib
from collections import Counter
from datetime import datetime, timedelta
from importlib import resources

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from newshouse.db import bytes_to_vec
from newshouse.fetch.normalize import detect_lang
from newshouse.llm.backend import cheap_effort
from newshouse.llm.schemas import SAME_EVENT_SCHEMA
from newshouse.models import Cluster, ClusterItem, Item

MAX_BORDERLINE = 200
BATCH = 50
HI = 0.86   # join threshold (single linkage); bge-small chains badly at 0.80
LO = 0.72   # borderline band is [LO, HI): asked to the cheap model
MAX_GROUP = 30  # no group or cluster ever exceeds this many items


def _split_oversize(members: list[int], sims: np.ndarray, hi: float,
                    cap: int) -> list[list[int]]:
    """Greedy complete-linkage: each member joins the first subgroup where it is >= hi
    to every member and there is room; otherwise it starts a new subgroup."""
    subs: list[list[int]] = []
    for m in members:
        for sub in subs:
            if len(sub) < cap and all(sims[m, o] >= hi for o in sub):
                sub.append(m)
                break
        else:
            subs.append([m])
    return subs


def group_by_similarity(ids: list[str], vecs: np.ndarray, *, hi: float = HI,
                        lo: float = LO, cap: int = MAX_GROUP, clustered: set[str] | frozenset[str] = frozenset(),
                        ) -> tuple[list[set[str]], list[tuple[str, str]]]:
    """Union-find over >= hi edges; borderline pairs are lo <= cos < hi.

    A union-find group larger than ``cap`` (single-linkage chaining) is split by greedy
    complete linkage at ``hi``, so no group exceeds ``cap``.
    Pairs whose items are both in ``clustered`` (already in stored clusters) are never
    borderline: clusters are never merged, so asking about them is wasted work.
    """
    n = len(ids)
    if n == 0:
        return [], []
    sims = vecs @ vecs.T
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    iu, ju = np.triu_indices(n, k=1)
    s = sims[iu, ju]
    for i, j in zip(iu[s >= hi], ju[s >= hi]):
        ri, rj = find(int(i)), find(int(j))
        if ri != rj:
            parent[ri] = rj
    mask = (s >= lo) & (s < hi)
    cand = sorted(zip(iu[mask].tolist(), ju[mask].tolist(), s[mask].tolist()), key=lambda t: -t[2])
    borderline = [(ids[i], ids[j]) for i, j, _ in cand
                  if find(i) != find(j) and not (ids[i] in clustered and ids[j] in clustered)
                  ][:MAX_BORDERLINE]
    roots: dict[int, list[int]] = {}
    for i in range(n):
        roots.setdefault(find(i), []).append(i)
    groups: list[set[str]] = []
    for members in roots.values():
        if len(members) > cap:
            groups += [{ids[m] for m in sub} for sub in _split_oversize(members, sims, hi, cap)]
        else:
            groups.append({ids[m] for m in members})
    return groups, borderline


def _system_prompt() -> str:
    return resources.files("newshouse.llm").joinpath("prompts/same_event.system.md").read_text()


def confirm_borderline(pairs: list[tuple[str, str]], titles: dict[str, str], backend,
                       *, model: str = "haiku") -> set[tuple[str, str]]:
    system = _system_prompt()
    same: set[tuple[str, str]] = set()
    for start in range(0, len(pairs), BATCH):
        batch = pairs[start:start + BATCH]
        user = "\n".join(f"{n}. A ({a}): {titles.get(a, '')} || B ({b}): {titles.get(b, '')}"
                         for n, (a, b) in enumerate(batch, 1))
        reply = backend.complete_json(system=system, user=user, schema=SAME_EVENT_SCHEMA, model=model,
                                     effort=cheap_effort(model))
        asked = {frozenset(p): p for p in batch}
        for entry in reply.get("pairs", []):
            if entry.get("same") is True:
                key = frozenset((entry.get("a"), entry.get("b")))
                if key in asked:
                    same.add(asked[key])
    return same


def _is_en(item: Item) -> bool:
    return (item.lang or detect_lang(item.title)) == "en"


def cluster_fresh_items(session: Session, backend, *, now: datetime,
                        window_hours: int = 48) -> list[Cluster]:
    window = timedelta(hours=window_hours)
    cutoff = now - window
    clustered = {r[0] for r in session.execute(select(ClusterItem.item_id))}
    item_cluster: dict[str, list[str]] = {}
    recent = select(Cluster.id).where(Cluster.created_at >= cutoff)
    for cid, iid in session.execute(select(ClusterItem.cluster_id, ClusterItem.item_id)
                                    .where(ClusterItem.cluster_id.in_(recent))):
        item_cluster.setdefault(iid, []).append(cid)
    fresh = session.scalars(select(Item).where(
        Item.stale.is_(False), Item.embedding.is_not(None), Item.published_at >= cutoff)).all()
    # bge-small-en is English-only: non-English items stay stored but are not clustered.
    pool = {i.id: i for i in fresh if i.id not in clustered and _is_en(i)}
    if item_cluster:
        for it in session.scalars(select(Item).where(Item.id.in_(list(item_cluster)))):
            if it.embedding is not None and _is_en(it):
                pool[it.id] = it
    if not pool:
        return []
    ids = sorted(pool)
    vecs = np.stack([bytes_to_vec(pool[i].embedding) for i in ids])
    groups, borderline = group_by_similarity(ids, vecs, clustered=set(item_cluster))
    if borderline:
        titles = {i: pool[i].title for i in ids}
        confirmed = confirm_borderline(borderline, titles, backend)
        index = {}
        for gi, g in enumerate(groups):
            for i in g:
                index[i] = gi
        merged = list(range(len(groups)))
        size = [len(g) for g in groups]

        def find(x: int) -> int:
            while merged[x] != x:
                merged[x] = merged[merged[x]]
                x = merged[x]
            return x

        for a, b in confirmed:
            ra, rb = find(index[a]), find(index[b])
            if ra != rb and size[ra] + size[rb] <= MAX_GROUP:
                merged[ra] = rb
                size[rb] += size[ra]
        combined: dict[int, set[str]] = {}
        for gi, g in enumerate(groups):
            combined.setdefault(find(gi), set()).update(g)
        groups = list(combined.values())

    created: list[Cluster] = []
    for g in groups:
        existing = [i for i in g if i in item_cluster]
        if existing:
            counts = Counter(c for i in existing for c in item_cluster[i])
            target = max(sorted(counts), key=lambda c: counts[c])
            added = sorted(g - set(existing))
            have = session.scalar(select(func.count()).select_from(ClusterItem)
                                  .where(ClusterItem.cluster_id == target)) or 0
            room = max(0, MAX_GROUP - have)
            if len(added) > room:  # overflow becomes its own cluster below
                groups.append(set(added[room:]))
                added = added[:room]
            if not added:
                continue
            for i in added:
                session.add(ClusterItem(cluster_id=target, item_id=i))
            cluster = session.get(Cluster, target)
            union = sorted(set(cluster.topics) | {t for i in added for t in pool[i].topics})
            if union != list(cluster.topics):
                cluster.topics = union
            continue
        sorted_ids = sorted(g)
        cid = hashlib.sha1("|".join(sorted_ids).encode()).hexdigest()[:16]
        topics = sorted({t for i in sorted_ids for t in pool[i].topics})
        session.add(Cluster(id=cid, window_start=cutoff, topics=topics))
        session.flush()
        for i in sorted_ids:
            session.add(ClusterItem(cluster_id=cid, item_id=i))
        created.append(session.get(Cluster, cid))
    session.flush()
    return created
