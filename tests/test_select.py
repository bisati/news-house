from datetime import datetime, timedelta, timezone

import pytest

from newshouse.config import Settings
from newshouse.edition_config import EditionConfig
from newshouse.models import Cluster, ClusterItem, Item, ItemSource, Source
from newshouse.select import (ScoredCluster, expected_format, est_seconds, final_score, freshness,
                              score_and_select, tier_bonus)

NOW = datetime(2026, 10, 30, 6, 0, tzinfo=timezone.utc)


def sc(i, score, topic="t", imp=60, st="plain", fmt="A"):
    return ScoredCluster(id=f"c{i}", importance=imp, final_score=score, topics=[topic],
                         story_type=st, expected_format=fmt)


def test_final_score_formula_values():
    assert final_score(importance=80, age_hours=10, n_sources=3, best_tier="primary", topic_w=0.5,
                       source_w=0, chapter=None, is_delta=True) == 80 * 1.0 + 10 + 5 + 5
    assert freshness(24) == 1.0 and freshness(48) == 0.8 and freshness(49) == 0.5
    assert tier_bonus("primary") == 5 and tier_bonus("early-signal") == 3
    assert tier_bonus("mainstream") == 0
    assert est_seconds("B") == est_seconds("C") == est_seconds("D") == 50
    assert est_seconds("A") == 35


def test_thread_without_delta_capped_at_40():
    kw = dict(importance=90, age_hours=1, n_sources=1, best_tier="mainstream", topic_w=0,
              source_w=0, chapter=2)
    assert final_score(**kw, is_delta=False) == 40
    assert final_score(**kw, is_delta=True) == 90
    assert final_score(**{**kw, "chapter": 1}, is_delta=False) == 90


def test_expected_format():
    assert expected_format("launch", None) == "B"
    assert expected_format("number", 0) == "C"
    assert expected_format("debate", 2) == "D"
    assert expected_format("debate", 1) == "E"
    assert expected_format("rule_change", None) == "F"
    assert expected_format("plain", None) == "A"


def _mk(session, cid, *, age_h=1, created=NOW, importance=60, scored=NOW, carded=False,
        topics=("ai-models",), sources=(("s1", "primary"),)):
    for sid, tier in sources:
        if session.get(Source, sid) is None:
            session.add(Source(id=sid, name=sid, topics=[], tier=tier, kind="rss",
                               url=f"http://{sid}", paywall=False))
    session.add(Item(id=f"i-{cid}", url="http://x", canonical_url="http://x", title="t", teaser="",
                     published_at=NOW - timedelta(hours=age_h), first_seen_at=NOW, dated=True,
                     topics=[], raw={}))
    session.add(Cluster(id=cid, window_start=NOW, topics=list(topics), story_type="plain",
                        importance=importance, scored_at=scored, carded=carded, created_at=created))
    session.flush()
    session.add(ClusterItem(cluster_id=cid, item_id=f"i-{cid}"))
    for sid, _ in sources:
        session.add(ItemSource(item_id=f"i-{cid}", source_id=sid))
    session.flush()


def test_score_and_select_persists_final_score_and_uses_window(session):
    _mk(session, "in", sources=(("s1", "primary"), ("s2", "mainstream")))
    _mk(session, "old", created=NOW - timedelta(hours=49))
    _mk(session, "carded", carded=True)
    _mk(session, "unscored", scored=None)
    _mk(session, "noimp", importance=None)
    sel = score_and_select(session, now=NOW, settings=Settings(), cfg=EditionConfig())
    assert sel.selected == ["in"]
    c = session.get(Cluster, "in")
    assert c.final_score == pytest.approx(60 * 1.0 + 5 * 1 + 5)
    assert session.get(Cluster, "old").final_score is None
