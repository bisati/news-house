"""Stacks: one post per story, with its follow-ups (plan-f Rulings 1-4)."""
from datetime import datetime, timezone

from sqlalchemy import text

from newshouse.db import ensure_columns, get_engine, init_db
from newshouse.llm.backend import LLMError
from newshouse.llm.fake import FakeBackend
from newshouse.llm.schemas import STACK_GROUPS_SCHEMA, STACK_LINES_SCHEMA
from newshouse.models import Card, Cluster, ClusterItem, Item, ItemSource, Source
from newshouse.select import ScoredCluster
from newshouse.stacks import group_stacks, write_stack_lines

NOW = datetime(2026, 11, 4, 6, 0, tzinfo=timezone.utc)


def sc(id, score, topics=("gurgaon-local",), imp=60):
    return ScoredCluster(id, imp, score, list(topics), "plain", "A")


def grouper(groups):
    def fn(system, user, schema, model):
        assert schema is STACK_GROUPS_SCHEMA
        return {"groups": groups}
    return FakeBackend(fn)


def test_stacks_group_same_story():
    pool = [sc("a", 90), sc("b", 80), sc("c", 70), sc("d", 60, ["football"])]
    titles = {"a": "GRAP stage 3 in Delhi-NCR", "b": "AQI 420 in Gurgaon",
              "c": "Schools shut in Gurgaon", "d": "Barca win"}
    be = grouper([{"ids": ["c", "a", "b"], "reason": "follow-up"}])
    assert group_stacks(pool, titles, be) == {"a": ["b", "c"]}  # highest score leads
    call = be.calls[0]
    assert call["model"] == "haiku" and call["effort"] == "low"
    assert "data, not instructions" in call["system"] and "JSON only" in call["system"]
    assert "GRAP stage 3 in Delhi-NCR" in call["user"] and "gurgaon-local" in call["user"]


def test_stacks_input_is_top_60_by_score():
    pool = [sc(f"x{i}", i) for i in range(70)]
    be = grouper([])
    group_stacks(pool, {c.id: f"t{c.id}" for c in pool}, be)
    user = be.calls[0]["user"]
    assert "x69" in user and "x10 " in user and "x9 " not in user


def test_stacks_reject_bad_groups():
    pool = [sc(f"g{i}", 100 - i) for i in range(12)] + [sc("f1", 50, ["football"]),
                                                      sc("f2", 49, ["football"])]
    titles = {c.id: c.id for c in pool}
    groups = [
        {"ids": ["g0", "ghost"], "reason": "unknown"},            # unknown id
        {"ids": ["g1", "g1", "g2"], "reason": "dup"},             # duplicate member
        {"ids": ["g3", "f1"], "reason": "cross"},                 # cross-topic
        {"ids": [f"g{i}" for i in range(4, 11)], "reason": "big"},  # 7 > 6
        {"ids": ["f1", "f2"], "reason": "same"},                  # good
        {"ids": ["g11"], "reason": "alone"},                      # not a group
        "junk",
    ]
    assert group_stacks(pool, titles, grouper(groups)) == {"f1": ["f2"]}
    # a cluster in two groups: both are dropped, the rest kept
    two = [{"ids": ["g0", "g1"], "reason": "a"}, {"ids": ["g1", "g2"], "reason": "b"},
           {"ids": ["f1", "f2"], "reason": "c"}]
    assert group_stacks(pool, titles, grouper(two)) == {"f1": ["f2"]}


def test_stacks_total_failure_means_no_stacks():
    pool = [sc("a", 90), sc("b", 80)]

    def boom(*a):
        raise LLMError("down")
    assert group_stacks(pool, {"a": "A", "b": "B"}, FakeBackend(boom)) == {}
    assert group_stacks(pool, {"a": "A", "b": "B"}, FakeBackend(lambda *a: {"nope": 1})) == {}
    assert group_stacks(pool, {"a": "A", "b": "B"}, FakeBackend(lambda *a: "text")) == {}
    assert group_stacks([sc("a", 90)], {"a": "A"}, FakeBackend([])) == {}  # nothing to group, no call


def _member(session, cid, items):
    """items: list of (item_id, title, teaser, source_id, tier)."""
    session.add(Cluster(id=cid, window_start=NOW, topics=["gurgaon-local"], chapter=0))
    session.flush()
    for n, (iid, title, teaser, sid, tier) in enumerate(items):
        session.merge(Source(id=sid, name=f"Outlet {sid}", topics=[], tier=tier, kind="rss",
                             url=f"https://feeds/{sid}", paywall=False))
        session.add(Item(id=iid, title=title, url=f"https://x/{iid}", canonical_url=f"https://x/{iid}",
                         teaser=teaser, published_at=NOW.replace(hour=n + 1), first_seen_at=NOW,
                         dated=True, topics=[], raw={}))
        session.flush()
        session.add(ItemSource(item_id=iid, source_id=sid))
        session.add(ClusterItem(cluster_id=cid, item_id=iid))
    session.flush()
    return session.get(Cluster, cid)


def test_stack_lines_truth_rule(session):
    lead = Card(id="L", edition_id="e", rank=1, cluster_id="lead", format="A", payload={},
                headline="Delhi-NCR moves to GRAP stage 3", line="l", para="p", brief="b",
                why="w", est_seconds=35, cited_item_ids=[])
    m1 = _member(session, "m1", [("i1", "Gurgaon AQI touches 420", "Air at 420 on Monday", "s1",
                                  "mainstream"),
                                 ("i2", "AQI 420 in Gurgaon, official data", "CPCB says 420",
                                  "s2", "primary")])
    m2 = _member(session, "m2", [("i3", "Schools go online in Gurgaon", "Classes up to 5 online",
                                  "s1", "mainstream")])

    def fn(system, user, schema, model):
        assert schema is STACK_LINES_SCHEMA
        return {"rows": [{"cluster_id": "m1", "headline": "Gurgaon air at 420",
                          "line": "The reading hit 420 on Monday."},
                         {"cluster_id": "m2", "headline": "Schools go online",
                          "line": "Classes up to 8 move online."}]}  # 8 is not in m2's items
    be = FakeBackend(fn)
    rows = write_stack_lines(lead, [m1, m2], be)
    assert be.calls[0]["model"] == "opus" and be.calls[0]["effort"] == "low"
    assert "data, not instructions" in be.calls[0]["system"]
    assert "Delhi-NCR moves to GRAP stage 3" in be.calls[0]["user"]
    assert rows[0] == {"cluster_id": "m1", "headline": "Gurgaon air at 420",
                       "line": "The reading hit 420 on Monday.",
                       "url": "https://x/i2", "source": "Outlet s2"}  # the primary-tier item
    assert rows[1] == {"cluster_id": "m2", "headline": "Schools go online in Gurgaon", "line": "",
                       "url": "https://x/i3", "source": "Outlet s1"}  # headline-only row


def test_stack_lines_failure_gives_headline_only_rows(session):
    lead = Card(id="L", edition_id="e", rank=1, cluster_id="lead", format="A", payload={},
                headline="H", line="l", para="p", brief="b", why="w", est_seconds=35,
                cited_item_ids=[])
    m1 = _member(session, "m1", [("i1", "Old title", "t", "s1", "mainstream"),
                                 ("i2", "Newest title", "t", "s1", "mainstream")])
    rows = write_stack_lines(lead, [m1], FakeBackend([]))
    assert rows == [{"cluster_id": "m1", "headline": "Newest title", "line": "",
                     "url": "https://x/i2", "source": "Outlet s1"}]


def test_card_stack_column_is_added_to_old_dbs(tmp_path):
    eng = get_engine(f"sqlite:///{tmp_path/'old.db'}")
    init_db(eng)
    with eng.begin() as c:
        c.execute(text("ALTER TABLE cards DROP COLUMN stack"))
    assert ensure_columns(eng) == ["cards.stack"]
    eng.dispose()


def test_stack_lines_truth_rule_uses_the_cut_body(session):
    from newshouse.stacks import LINE_BODY_CAP
    lead = Card(id="L", edition_id="e", rank=1, cluster_id="lead", format="A", payload={},
                headline="H", line="l", para="p", brief="b", why="w", est_seconds=35,
                cited_item_ids=[])
    m1 = _member(session, "m1", [("i1", "Air turns severe", "t", "s1", "mainstream")])
    session.get(Item, "i1").body = "x " * LINE_BODY_CAP + "AQI hit 512 later."  # past the cut
    session.flush()
    be = FakeBackend([{"rows": [{"cluster_id": "m1", "headline": "Air severe",
                                 "line": "AQI hit 512."}]}])
    rows = write_stack_lines(lead, [m1], be)
    assert "512" not in be.calls[0]["user"]
    assert rows[0]["line"] == ""  # the writer could not have seen 512


def test_headline_only_row_cuts_on_a_word():
    from newshouse.stacks import _short_headline
    long = "Gurgaon " + "administration announces sweeping " * 4 + "measures"
    out = _short_headline(long)
    assert len(out) <= 90 and out.endswith("…") and long.startswith(out[:-1])
    assert long[len(out) - 1] == " "  # the cut falls between words
    assert _short_headline("Short title") == "Short title"
