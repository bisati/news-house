import re
from datetime import datetime, timedelta, timezone

import numpy as np

from newshouse.db import bytes_to_vec, vec_to_bytes
from newshouse.llm.backend import LLMError
from newshouse.llm.fake import FakeBackend
from newshouse.models import Cluster, ClusterItem, Item, Thread
from newshouse.threads import (candidate_threads, close_quiet_threads, cluster_centroid,
                               match_threads)

NOW = datetime(2026, 10, 30, 6, 0, tzinfo=timezone.utc)


def unit(*xs):
    v = np.array(xs, dtype=np.float32)
    return v / np.linalg.norm(v)


def mk_cluster(session, cid, vec, *, story_type="plain", importance=50, title=None, created=0):
    session.add(Item(id=f"i-{cid}", url=f"http://x/{cid}", canonical_url=f"http://x/{cid}",
                     title=title or f"title {cid}", teaser="", published_at=NOW,
                     first_seen_at=NOW, dated=True, topics=[], raw={},
                     embedding=None if vec is None else vec_to_bytes(vec)))
    session.add(Cluster(id=cid, window_start=NOW, topics=["ai-models"], story_type=story_type,
                        importance=importance, reason=f"reason {cid}", scored_at=NOW,
                        created_at=NOW + timedelta(seconds=created)))
    session.flush()
    session.add(ClusterItem(cluster_id=cid, item_id=f"i-{cid}"))
    session.flush()


def mk_thread(session, tid, vec, *, chapters=3, last=None, closed=None):
    t = Thread(id=tid, title=f"thread {tid}", summary="sum", opened_at=NOW - timedelta(days=5),
               last_chapter_at=last or NOW - timedelta(days=1), closed_at=closed,
               embedding=None if vec is None else vec_to_bytes(vec), chapters=chapters)
    session.add(t)
    session.flush()
    return t


def matcher(choose):
    def fn(system, user, schema, model):
        out = []
        for block in re.split(r"^### cluster ", user, flags=re.M)[1:]:
            cid = block.split()[0]
            tids = re.findall(r"^- thread (\S+):", block, re.M)
            out.append({"cluster_id": cid, "thread_id": choose(cid, tids)})
        return {"matches": out}
    return FakeBackend(fn)


def test_matched_cluster_gets_next_chapter(session):
    mk_thread(session, "t1", unit(1, 0, 0), chapters=3)
    mk_cluster(session, "c1", unit(1, 0.1, 0))
    b = matcher(lambda cid, tids: tids[0])
    assert match_threads(session, b, now=NOW) == 1
    c, t = session.get(Cluster, "c1"), session.get(Thread, "t1")
    assert c.thread_id == "t1" and c.chapter == 4 and t.chapters == 4
    assert t.last_chapter_at == NOW and t.summary.endswith("\n- reason c1")
    assert abs(np.linalg.norm(bytes_to_vec(t.embedding)) - 1) < 1e-5
    assert b.calls[0]["model"] == "haiku" and b.calls[0]["effort"] == "low"


def test_unmatched_saga_opens_thread(session):
    mk_cluster(session, "c1", unit(0, 1, 0), story_type="saga", importance=40, title="Big saga")
    b = matcher(lambda cid, tids: None)
    assert match_threads(session, b, now=NOW) == 1
    c = session.get(Cluster, "c1")
    t = session.get(Thread, c.thread_id)
    assert c.chapter == 1 and t.chapters == 1 and t.title == "Big saga"
    assert t.summary == "reason c1" and t.opened_at == NOW and t.last_chapter_at == NOW
    assert np.allclose(bytes_to_vec(t.embedding), unit(0, 1, 0), atol=1e-5)


def test_unmatched_plain_low_importance_is_standalone(session):
    mk_thread(session, "t1", unit(1, 0, 0))
    mk_cluster(session, "c1", unit(1, 0.1, 0), importance=50)
    assert match_threads(session, matcher(lambda cid, tids: None), now=NOW) == 1
    c = session.get(Cluster, "c1")
    assert c.chapter == 0 and c.thread_id is None
    assert session.query(Thread).count() == 1


def test_high_importance_unmatched_opens_thread(session):
    mk_cluster(session, "c1", unit(0, 1, 0), importance=85)
    match_threads(session, matcher(lambda cid, tids: None), now=NOW)
    assert session.get(Cluster, "c1").chapter == 1


def test_close_quiet_threads_after_30_days(session):
    mk_thread(session, "old", unit(1, 0, 0), last=NOW - timedelta(days=31))
    mk_thread(session, "new", unit(1, 0, 0), last=NOW - timedelta(days=29))
    assert close_quiet_threads(session, now=NOW) == 1
    assert session.get(Thread, "old").closed_at == NOW
    assert session.get(Thread, "new").closed_at is None


def test_reply_with_non_candidate_thread_is_ignored(session):
    mk_thread(session, "t1", unit(1, 0, 0), chapters=3)
    mk_cluster(session, "c1", unit(1, 0.1, 0))
    assert match_threads(session, matcher(lambda cid, tids: "bogus"), now=NOW) == 1
    c = session.get(Cluster, "c1")
    assert c.thread_id is None and c.chapter == 0
    assert session.get(Thread, "t1").chapters == 3


def test_no_candidates_low_importance_is_standalone_without_llm_call(session):
    mk_thread(session, "far", unit(0, 0, 1))
    mk_cluster(session, "c1", unit(1, 0, 0))
    b = matcher(lambda cid, tids: None)
    assert match_threads(session, b, now=NOW) == 1
    assert b.calls == [] and session.get(Cluster, "c1").chapter == 0


def test_llm_error_leaves_batch_unchanged(session):
    mk_thread(session, "t1", unit(1, 0, 0))
    mk_cluster(session, "c1", unit(1, 0.1, 0))

    def boom(system, user, schema, model):
        raise LLMError("down")
    assert match_threads(session, FakeBackend(boom), now=NOW) == 0
    c = session.get(Cluster, "c1")
    assert c.chapter is None and c.thread_id is None


def test_candidate_threads_filters_closed_far_and_caps_at_five(session):
    for i in range(7):
        mk_thread(session, f"t{i}", unit(1, 0.05 * i, 0))
    mk_thread(session, "closed", unit(1, 0, 0), closed=NOW)
    mk_thread(session, "noemb", None)
    mk_thread(session, "far", unit(0, 1, 0))
    got = candidate_threads(session, unit(1, 0, 0), now=NOW)
    assert [t.id for t in got] == ["t0", "t1", "t2", "t3", "t4"]


def test_no_embedding_cluster_is_standalone_and_centroid_none(session):
    mk_cluster(session, "c1", None, story_type="saga")
    assert cluster_centroid(session, session.get(Cluster, "c1")) is None
    assert match_threads(session, matcher(lambda c, t: None), now=NOW) == 1
    c = session.get(Cluster, "c1")
    assert c.chapter == 0 and c.thread_id is None


def test_thread_opened_earlier_in_run_is_candidate_for_later_cluster(session):
    mk_cluster(session, "c1", unit(0, 1, 0), story_type="saga", created=0)
    mk_cluster(session, "c2", unit(0, 1, 0.05), story_type="saga", created=1)
    b = matcher(lambda cid, tids: tids[0] if tids else None)
    assert match_threads(session, b, now=NOW, batch=1) == 2
    threads = session.query(Thread).all()
    assert len(threads) == 1 and threads[0].chapters == 2
    assert session.get(Cluster, "c1").chapter == 1 and session.get(Cluster, "c2").chapter == 2
    assert session.get(Cluster, "c2").thread_id == threads[0].id


def test_one_call_per_chunk_and_threads_from_earlier_chunk_are_candidates(session):
    # Chunk 1: 50 clusters; the even ones sit near t1 (have candidates), the odd ones
    # are far away. The last one (a49) is a far saga that opens a new thread.
    mk_thread(session, "t1", unit(1, 0, 0), chapters=1)
    for n in range(50):
        if n == 49:
            mk_cluster(session, "a49", unit(0, 1, 0), story_type="saga", created=n)
        elif n % 2 == 0:
            mk_cluster(session, f"a{n:02d}", unit(1, 0.05, 0), created=n)
        else:
            mk_cluster(session, f"a{n:02d}", unit(0, 0, 1), created=n)
    # Chunk 2: one cluster close to the saga thread opened in chunk 1.
    mk_cluster(session, "b00", unit(0, 1, 0.05), created=100)
    b = matcher(lambda cid, tids: None)
    assert match_threads(session, b, now=NOW) == 51
    assert len(b.calls) == 2
    first = re.findall(r"^### cluster (\S+)", b.calls[0]["user"], re.M)
    assert len(first) == 25 and all(int(c[1:]) % 2 == 0 for c in first)
    saga = session.get(Cluster, "a49")
    assert saga.chapter == 1 and saga.thread_id is not None
    second = b.calls[1]["user"]
    assert "### cluster b00" in second and f"- thread {saga.thread_id}:" in second


def test_candidate_threshold_is_070(session):
    mk_thread(session, "near", unit(1, 0.9, 0))    # cos ~0.74 to (1,0,0)
    mk_thread(session, "mid", unit(1, 1.2, 0))     # cos ~0.64: candidate at 0.60, not at 0.70
    got = candidate_threads(session, unit(1, 0, 0), now=NOW)
    assert [t.id for t in got] == ["near"]
