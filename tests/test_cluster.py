from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import func, select

from newshouse.cluster import cluster_fresh_items, confirm_borderline, group_by_similarity
from newshouse.db import vec_to_bytes
from newshouse.llm.fake import FakeBackend
from newshouse.llm.schemas import SAME_EVENT_SCHEMA
from newshouse.models import Cluster, ClusterItem, Item


def _basis(k: int) -> np.ndarray:
    v = np.zeros(384, dtype=np.float32)
    v[k] = 1.0
    return v


def _at(base: np.ndarray, cos: float, k: int) -> np.ndarray:
    """Unit vector with cosine `cos` to `base` (orthogonal component on axis k)."""
    v = base * cos + _basis(k) * float(np.sqrt(1 - cos ** 2))
    return (v / np.linalg.norm(v)).astype(np.float32)


def _item(i: str, vec, now, title=None, topics=("ai",)) -> Item:
    return Item(id=i, title=title or f"title {i}", url=f"http://x/{i}", canonical_url=f"http://x/{i}",
                teaser="", published_at=now - timedelta(hours=1), first_seen_at=now, dated=True,
                topics=list(topics), stale=False, embedding=vec_to_bytes(vec), raw={})


def test_group_by_similarity_joins_near_duplicates():
    a = _basis(0)
    vecs = np.stack([a, _at(a, 0.95, 1), _at(a, 0.5, 2), _at(a, 0.75, 3)])
    groups, border = group_by_similarity(["a", "b", "c", "d"], vecs)
    assert sorted(map(sorted, groups)) == [["a", "b"], ["c"], ["d"]]
    assert ("a", "d") in border or ("d", "a") in border
    assert len(border) >= 1 and all("c" not in p for p in border)


def test_confirm_borderline_uses_backend_and_schema():
    pairs = [("a", "b"), ("c", "d")]
    titles = {"a": "T1", "b": "T2", "c": "T3", "d": "T4"}
    fb = FakeBackend([{"pairs": [{"a": "a", "b": "b", "same": True}, {"a": "c", "b": "d", "same": False}]}])
    assert confirm_borderline(pairs, titles, fb) == {("a", "b")}
    call = fb.calls[0]
    assert call["model"] == "haiku" and call["schema"] == SAME_EVENT_SCHEMA
    assert "1. A (a): T1 || B (b): T2" in call["user"]
    assert "real-world event" in call["system"]


def test_confirm_borderline_batches_and_missing_means_not_same():
    pairs = [(f"a{i}", f"b{i}") for i in range(120)]
    fb = FakeBackend([{"pairs": []}, {"pairs": []}, {"pairs": []}])
    assert confirm_borderline(pairs, {}, fb) == set()
    assert len(fb.calls) == 3


def test_cluster_fresh_items_creates_rows_and_merges(session):
    now = datetime.now(timezone.utc)
    a = _basis(0)
    session.add_all([_item("i1", a, now), _item("i2", _at(a, 0.95, 1), now, topics=("ai", "tech")),
                     _item("i3", _basis(5), now, topics=("sports",))])
    session.flush()
    fb = FakeBackend([])
    new = cluster_fresh_items(session, fb, now=now)
    assert len(new) == 2 and not fb.calls
    big = next(c for c in new if len(c.topics) == 2)
    assert big.topics == ["ai", "tech"]
    session.add(_item("i4", _at(a, 0.93, 2), now))
    session.flush()
    again = cluster_fresh_items(session, fb, now=now)
    assert again == []
    assert len(session.scalars(select(Cluster)).all()) == 2
    members = {r.item_id for r in session.scalars(select(ClusterItem).where(ClusterItem.cluster_id == big.id))}
    assert members == {"i1", "i2", "i4"}


def test_group_spanning_two_clusters_joins_larger_one(session):
    now = datetime.now(timezone.utc)
    a = _basis(0)
    b = _basis(10)
    big_items = [_item("a1", a, now), _item("a2", _at(a, 0.99, 1), now), _item("a3", _at(a, 0.99, 2), now)]
    small = _item("b1", b, now)
    session.add_all(big_items + [small])
    session.add_all([Cluster(id="big", window_start=now, topics=["ai"]), Cluster(id="small", window_start=now, topics=["ai"])])
    session.flush()
    session.add_all([ClusterItem(cluster_id="big", item_id=i.id) for i in big_items]
                    + [ClusterItem(cluster_id="small", item_id="b1")])
    # bridge item similar to a-cluster, and to b via confirmed borderline
    bridge = _item("n1", _at(a, 0.97, 3), now)
    session.add(bridge)
    session.flush()
    # make b1 near the a-cluster at high similarity so everything is one group
    small.embedding = vec_to_bytes(_at(a, 0.9, 11))
    session.flush()
    new = cluster_fresh_items(session, FakeBackend([]), now=now)
    assert new == []
    assert len(session.scalars(select(Cluster)).all()) == 2
    rows = session.scalars(select(ClusterItem).where(ClusterItem.item_id == "n1")).all()
    assert [r.cluster_id for r in rows] == ["big"]
    assert session.scalars(select(ClusterItem).where(ClusterItem.item_id == "b1")).one().cluster_id == "small"


def test_attach_updates_cluster_topics(session):
    now = datetime.now(timezone.utc)
    a = _basis(0)
    session.add_all([_item("i1", a, now), _item("i2", _at(a, 0.95, 1), now)])
    session.flush()
    fb = FakeBackend([])
    (cluster,) = cluster_fresh_items(session, fb, now=now)
    assert cluster.topics == ["ai"]
    session.add(_item("i3", _at(a, 0.93, 2), now, topics=("sports",)))
    session.flush()
    assert cluster_fresh_items(session, fb, now=now) == []
    session.expire_all()
    assert session.get(Cluster, cluster.id).topics == ["ai", "sports"]


def test_borderline_pairs_skip_two_already_clustered_items():
    a = _basis(0)
    vecs = np.stack([a, _at(a, 0.76, 1), _at(a, 0.76, 2)])
    _, border = group_by_similarity(["x", "y", "z"], vecs, clustered={"x", "y"})
    assert ("x", "y") not in border and ("y", "x") not in border
    assert ("x", "z") in border


def _clustered(session, cid, items, now):
    session.add_all(items)
    session.add(Cluster(id=cid, window_start=now, topics=["ai"]))
    session.flush()
    session.add_all([ClusterItem(cluster_id=cid, item_id=i.id) for i in items])
    session.flush()


def test_two_clustered_items_at_borderline_make_no_backend_call(session):
    now = datetime.now(timezone.utc)
    a = _basis(0)
    _clustered(session, "c1", [_item("x", a, now)], now)
    _clustered(session, "c2", [_item("y", _at(a, 0.76, 1), now)], now)
    fb = FakeBackend([])
    assert cluster_fresh_items(session, fb, now=now) == []
    assert fb.calls == []


def test_unclustered_item_at_borderline_to_clustered_one_is_asked(session):
    now = datetime.now(timezone.utc)
    a = _basis(0)
    _clustered(session, "c1", [_item("x", a, now)], now)
    session.add(_item("z", _at(a, 0.76, 2), now))
    session.flush()
    fb = FakeBackend([{"pairs": []}])
    cluster_fresh_items(session, fb, now=now)
    assert len(fb.calls) == 1 and "(x)" in fb.calls[0]["user"] and "(z)" in fb.calls[0]["user"]


def test_oversize_chain_splits_under_cap():
    # A chain: each vector is ~0.87 to its neighbour, so single linkage joins all 40,
    # but far-apart members are well below the join threshold.
    n = 40
    vecs = [_basis(0)]
    for k in range(1, n):
        vecs.append(_at(vecs[-1], 0.87, k))
    ids = [f"c{k:02d}" for k in range(n)]
    sims = np.stack(vecs) @ np.stack(vecs).T
    groups, _ = group_by_similarity(ids, np.stack(vecs))
    assert sum(len(g) for g in groups) == n
    assert max(len(g) for g in groups) <= 30
    pos = {i: k for k, i in enumerate(ids)}
    for g in groups:  # every split group is complete-linked at the join threshold
        for x in g:
            for y in g:
                assert x == y or sims[pos[x], pos[y]] >= 0.86


def test_dense_group_over_cap_is_capped():
    a = _basis(0)
    vecs = np.stack([_at(a, 0.99, k) for k in range(1, 46)])
    groups, _ = group_by_similarity([f"d{k}" for k in range(45)], vecs)
    assert sorted(len(g) for g in groups) == [15, 30]


def test_default_join_threshold_is_086():
    a = _basis(0)
    groups, border = group_by_similarity(["a", "b"], np.stack([a, _at(a, 0.84, 1)]))
    assert len(groups) == 2 and border == [("a", "b")]


def test_devanagari_title_is_hi_and_excluded_from_pool(session):
    from newshouse.fetch.normalize import detect_lang
    hindi = "प्रधानमंत्री ने नई योजना की घोषणा की"
    assert detect_lang(hindi) == "hi"
    assert detect_lang("PIB: प्रधानमंत्री ने योजना launched today for all") == "hi"
    assert detect_lang("Prime Minister announces new scheme") == "en"
    assert detect_lang("") == "en"
    now = datetime.now(timezone.utc)
    a = _basis(0)
    h1 = _item("h1", a, now, title=hindi)
    h1.lang = "hi"
    h2 = _item("h2", _at(a, 0.99, 1), now, title=hindi)  # lang unset: detected from title
    session.add_all([h1, h2, _item("e1", _basis(7), now)])
    session.flush()
    new = cluster_fresh_items(session, FakeBackend([]), now=now)
    members = {r.item_id for r in session.scalars(select(ClusterItem))}
    assert len(new) == 1 and members == {"e1"}


def test_ingest_sets_lang(session):
    from datetime import timedelta as td

    from newshouse.fetch.feeds import FetchResult
    from newshouse.fetch.normalize import RawItem
    from newshouse.ingest import RunStats, _ingest_source
    from newshouse.models import Source
    now = datetime.now(timezone.utc)
    src = Source(id="s1", name="PIB", topics=["india-news"], tier="primary", kind="rss",
                 url="http://pib/rss", paywall=False, enabled=True)
    session.add(src)
    session.flush()
    raws = [RawItem(title="प्रधानमंत्री ने नई योजना की घोषणा की", url="http://pib/1", guid=None,
                    teaser="", author=None, published_at=now, raw={}),
            RawItem(title="PM announces new scheme", url="http://pib/2", guid=None,
                    teaser="", author=None, published_at=now, raw={})]
    _ingest_source(session, src, FetchResult(ok=True, items=raws), now, td(hours=72), RunStats())
    langs = {i.url: i.lang for i in session.scalars(select(Item))}
    assert langs == {"http://pib/1": "hi", "http://pib/2": "en"}


def test_attach_never_grows_cluster_past_cap(session):
    now = datetime.now(timezone.utc)
    a = _basis(0)
    _clustered(session, "full", [_item(f"m{k:02d}", _at(a, 0.99, k + 1), now) for k in range(29)], now)
    session.add_all([_item(f"n{k}", _at(a, 0.99, 100 + k), now) for k in range(3)])
    session.flush()
    new = cluster_fresh_items(session, FakeBackend([]), now=now)
    sizes = {c: n for c, n in session.execute(
        select(ClusterItem.cluster_id, func.count()).group_by(ClusterItem.cluster_id))}
    assert sizes["full"] == 30 and len(new) == 1 and sizes[new[0].id] == 2
