from datetime import datetime, timedelta, timezone

import pytest

from newshouse.feedback import Weights, compute_weights, record_feedback
from newshouse.models import Card, Cluster, ClusterItem, Edition, Item, ItemSource, Source

NOW = datetime(2026, 10, 30, 6, 0, tzinfo=timezone.utc)


def mk(session, cid="c1", topics=("ai-models",), source="s1"):
    if session.get(Source, source) is None:
        session.add(Source(id=source, name=source, topics=[], tier="mainstream", kind="rss",
                           url=f"http://{source}", paywall=False))
    session.add(Item(id=f"i-{cid}", url="http://x", canonical_url="http://x", title="t", teaser="",
                     published_at=NOW, first_seen_at=NOW, dated=True, topics=[], raw={}))
    session.add(Cluster(id=cid, window_start=NOW, topics=list(topics)))
    session.flush()
    session.add(ClusterItem(cluster_id=cid, item_id=f"i-{cid}"))
    session.add(ItemSource(item_id=f"i-{cid}", source_id=source))
    session.flush()


def mk_card(session, cid="c1"):
    session.add(Edition(id="e1", date=NOW.date(), budget_seconds=900))
    session.flush()
    session.add(Card(id="card1", edition_id="e1", rank=1, cluster_id=cid, format="A", payload={},
                     headline="h", line="", para="", brief="", why="", est_seconds=35,
                     cited_item_ids=[]))
    session.flush()


def test_ewma_weights_move_toward_reward(session):
    mk(session)
    mk_card(session)
    record_feedback(session, profile_id="mihir", action="worth", card_id="card1", at=NOW)
    w = compute_weights(session, profile_id="mihir")
    assert w.topic["ai-models"] == pytest.approx(0.2)
    assert w.source["s1"] == pytest.approx(0.2)
    record_feedback(session, profile_id="mihir", action="skip", card_id="card1",
                    at=NOW + timedelta(minutes=1))
    w = compute_weights(session, profile_id="mihir")
    assert w.topic["ai-models"] == pytest.approx(-0.04)


def test_weights_clamped(session):
    mk(session)
    for i in range(5):
        record_feedback(session, profile_id="mihir", action="should_have", cluster_id="c1",
                        at=NOW + timedelta(minutes=i))
    w = compute_weights(session, profile_id="mihir", alpha=2.0)
    assert w.topic["ai-models"] == 1.0
    record_feedback(session, profile_id="mihir", action="skip", cluster_id="c1",
                    at=NOW + timedelta(hours=1))
    assert compute_weights(session, profile_id="mihir", alpha=5.0).topic["ai-models"] == -1.0


def test_record_feedback_validation_and_unresolved_rows(session):
    with pytest.raises(ValueError):
        record_feedback(session, profile_id="mihir", action="love", cluster_id="c1", at=NOW)
    with pytest.raises(ValueError):
        record_feedback(session, profile_id="mihir", action="worth", at=NOW)
    fb = record_feedback(session, profile_id="mihir", action="worth", cluster_id="ghost", at=NOW)
    assert len(fb.id) == 32
    assert compute_weights(session, profile_id="mihir") == Weights(topic={}, source={})


def test_cli_feedback(tmp_path, monkeypatch, capsys):
    import newshouse.db as db
    from newshouse.cli import main
    engine = db.get_engine(f"sqlite:///{tmp_path / 'cli.db'}")
    db.init_db(engine)
    monkeypatch.setattr(db, "_engine", engine)
    try:
        assert main(["feedback", "--cluster", "c9", "should_have"]) == 0
        assert main(["feedback", "card9", "skip"]) == 0
    finally:
        engine.dispose()
    ids = capsys.readouterr().out.split()
    assert len(ids) == 2 and all(len(i) == 32 for i in ids)


def test_seen_and_read_are_valid_actions_and_ignored_by_weights(session):
    mk(session)
    mk_card(session)
    for a in ("seen", "read", "tune"):
        record_feedback(session, profile_id="mihir", action=a, card_id="card1", at=NOW,
                        payload={"budget": 1} if a == "tune" else None)
    w = compute_weights(session, profile_id="mihir")
    assert w.topic == {} and w.source == {}


def test_payload_round_trips(session):
    mk(session)
    mk_card(session)
    p = {"topic": "football", "dir": -1}
    fb = record_feedback(session, profile_id="mihir", action="tune", card_id="card1", at=NOW,
                         payload=p)
    session.expire_all()
    assert session.get(type(fb), fb.id).payload == p


def test_tune_feedback_payload_rules(session):
    a = record_feedback(session, profile_id="mihir", action="tune", at=NOW,
                        payload={"topic": "football", "dir": -1})
    b = record_feedback(session, profile_id="mihir", action="tune", at=NOW, payload={"budget": 1})
    for fb in (a, b):
        assert fb.card_id is None and fb.cluster_id is None
    for bad in (None, {}, {"topic": "football"}, {"topic": "football", "dir": 2},
                {"topic": "", "dir": 1}, {"topic": 5, "dir": 1}, {"budget": 0},
                {"budget": True}, {"budget": -1, "x": 1}, {"topic": "f", "dir": 1, "budget": 1},
                {"topic": "football", "dir": 1.0}, [1]):
        with pytest.raises(ValueError):
            record_feedback(session, profile_id="mihir", action="tune", at=NOW, payload=bad)
    with pytest.raises(ValueError):  # other actions still need an id
        record_feedback(session, profile_id="mihir", action="worth", at=NOW, payload={"budget": 1})
