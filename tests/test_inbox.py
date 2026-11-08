from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import insert, select

from newshouse.inbox import INBOX, init_inbox, inbox_engine, sync_feedback
from newshouse.models import Feedback
from tests.test_feedback import mk, mk_card

NOW = datetime(2026, 11, 3, 6, 0, tzinfo=timezone.utc)


@pytest.fixture
def inbox(tmp_path):
    eng = inbox_engine(f"sqlite:///{tmp_path / 'inbox.db'}")
    init_inbox(eng)
    yield eng
    eng.dispose()


def put(eng, id, body, at=NOW - timedelta(minutes=5)):
    with eng.begin() as c:
        c.execute(insert(INBOX).values(id=id, received_at=at, body=body))


def test_inbox_url_normalised():
    for u in ("postgres://u:p@h.neon.tech/db", "postgresql://u:p@h.neon.tech/db"):
        e = inbox_engine(u)
        assert e.url.drivername == "postgresql+psycopg"
        assert e.url.host == "h.neon.tech"
    assert inbox_engine("sqlite://").url.drivername == "sqlite"


def test_sync_records_rows(session, inbox):
    mk(session)
    mk_card(session)
    t1, t2 = NOW - timedelta(minutes=9), NOW - timedelta(minutes=3)
    put(inbox, "r1", {"action": "worth", "card_id": "card1"}, t1)
    put(inbox, "r2", {"action": "tune", "payload": {"topic": "ai-models", "dir": 1}}, t2)
    r = sync_feedback(session, inbox, profile_id="mihir", now=NOW)
    assert r == {"fetched": 2, "recorded": 2, "duplicate": 0, "invalid": 0}
    fbs = {f.id: f for f in session.scalars(select(Feedback))}
    assert fbs["r1"].card_id == "card1" and fbs["r1"].at == t1 and fbs["r1"].profile_id == "mihir"
    assert fbs["r2"].action == "tune" and fbs["r2"].at == t2
    with inbox.connect() as c:
        vals = c.execute(select(INBOX.c.synced_at)).scalars().all()
    assert len(vals) == 2 and all(v is not None for v in vals)


def test_sync_is_idempotent(session, inbox):
    mk(session)
    mk_card(session)
    put(inbox, "r1", {"action": "worth", "card_id": "card1"})
    sync_feedback(session, inbox, profile_id="mihir", now=NOW)
    # the same id arriving again (synced_at lost, e.g. a restored inbox) is recorded once
    with inbox.begin() as c:
        c.execute(INBOX.update().values(synced_at=None))
    r = sync_feedback(session, inbox, profile_id="mihir", now=NOW)
    assert r == {"fetched": 1, "recorded": 0, "duplicate": 1, "invalid": 0}
    assert len(session.scalars(select(Feedback)).all()) == 1
    assert sync_feedback(session, inbox, profile_id="mihir", now=NOW)["fetched"] == 0


def test_sync_drops_invalid_rows(session, inbox):
    mk(session)
    mk_card(session)
    put(inbox, "a", {"action": "worth", "card_id": "ghost"})
    put(inbox, "b", {"action": "love", "card_id": "card1"})
    put(inbox, "c", {"action": "tune", "payload": {"topic": "x", "dir": 5}})
    put(inbox, "d", {"action": "worth", "cluster_id": "nope"})
    put(inbox, "e", "not an object")
    put(inbox, "f", {"action": "worth", "card_id": 7})
    put(inbox, "g", {"action": "tune", "payload": "x"})
    put(inbox, "h", {"action": 5, "card_id": "card1"})
    put(inbox, "i", {"action": "worth", "card_id": "c" * 65})
    r = sync_feedback(session, inbox, profile_id="mihir", now=NOW)
    assert r == {"fetched": 9, "recorded": 0, "duplicate": 0, "invalid": 9}
    assert session.scalars(select(Feedback)).all() == []
    assert sync_feedback(session, inbox, profile_id="mihir", now=NOW)["fetched"] == 0


def test_sync_prunes_old_rows(session, inbox):
    mk(session)
    mk_card(session)
    put(inbox, "old", {"action": "worth", "card_id": "card1"}, NOW - timedelta(days=40))
    sync_feedback(session, inbox, profile_id="mihir", now=NOW - timedelta(days=35))
    put(inbox, "new", {"action": "skip", "card_id": "card1"})
    sync_feedback(session, inbox, profile_id="mihir", now=NOW)
    with inbox.connect() as c:
        assert c.execute(select(INBOX.c.id)).scalars().all() == ["new"]


def test_cli_requires_neon_url(monkeypatch, capsys, tmp_path):
    import newshouse.db as db
    from newshouse.cli import main
    from newshouse.config import get_settings
    monkeypatch.delenv("NEON_DATABASE_URL", raising=False)
    from newshouse.config import Settings  # explicit None beats any real neon.env
    monkeypatch.setattr("newshouse.cli.get_settings", lambda: Settings(neon_database_url=None))
    engine = db.get_engine(f"sqlite:///{tmp_path / 'cli.db'}")
    db.init_db(engine)
    monkeypatch.setattr(db, "_engine", engine)
    try:
        for cmd in ("inbox-init", "sync-feedback"):
            assert main([cmd]) == 2
            assert "NEON_DATABASE_URL" in capsys.readouterr().err
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_cli_sync_feedback_prints_counts(monkeypatch, capsys, tmp_path):
    import json
    import newshouse.db as db
    from newshouse.cli import main
    from newshouse.config import get_settings
    monkeypatch.setenv("NEON_DATABASE_URL", f"sqlite:///{tmp_path / 'inbox.db'}")
    get_settings.cache_clear()
    engine = db.get_engine(f"sqlite:///{tmp_path / 'cli.db'}")
    db.init_db(engine)
    monkeypatch.setattr(db, "_engine", engine)
    try:
        assert main(["inbox-init"]) == 0
        capsys.readouterr()
        assert main(["sync-feedback"]) == 0
    finally:
        engine.dispose()
        get_settings.cache_clear()
    assert json.loads(capsys.readouterr().out) == {"fetched": 0, "recorded": 0,
                                                    "duplicate": 0, "invalid": 0}


def test_sync_isolates_poison_row(session, inbox, monkeypatch):
    import newshouse.inbox as ib
    mk(session)
    mk_card(session)
    put(inbox, "p1", {"action": "worth", "card_id": "card1"}, NOW - timedelta(minutes=9))
    put(inbox, "p2", {"action": "skip", "card_id": "card1"}, NOW - timedelta(minutes=2))
    real = ib.record_feedback

    def flaky(sess, **kw):
        if kw["id"] == "p1":
            raise RuntimeError("boom")
        return real(sess, **kw)

    monkeypatch.setattr(ib, "record_feedback", flaky)
    r = sync_feedback(session, inbox, profile_id="mihir", now=NOW)
    assert r == {"fetched": 2, "recorded": 1, "duplicate": 0, "invalid": 1}
    assert [f.id for f in session.scalars(select(Feedback))] == ["p2"]
    assert sync_feedback(session, inbox, profile_id="mihir", now=NOW)["fetched"] == 0


def test_sync_works_in_batches_of_500(session, inbox, monkeypatch):
    import newshouse.inbox as ib
    from sqlalchemy import func
    mk(session)
    mk_card(session)
    with inbox.begin() as c:
        c.execute(insert(INBOX), [{"id": f"r{i:04d}", "received_at": NOW - timedelta(seconds=i),
                                   "body": {"action": "worth", "card_id": "card1"}}
                                  for i in range(1200)])
    fetches = []
    real = ib._fetch

    def spy(engine, limit):
        rows = real(engine, limit)
        fetches.append((limit, len(rows)))
        return rows

    monkeypatch.setattr(ib, "_fetch", spy)
    r = sync_feedback(session, inbox, profile_id="mihir", now=NOW)
    assert r == {"fetched": 1200, "recorded": 1200, "duplicate": 0, "invalid": 0}
    assert fetches == [(500, 500), (500, 500), (500, 200)]
    assert session.scalar(select(func.count()).select_from(Feedback)) == 1200
    with inbox.connect() as c:
        assert c.execute(select(func.count()).select_from(INBOX)
                         .where(INBOX.c.synced_at.is_(None))).scalar() == 0


def test_sync_stops_after_the_pass_cap(session, inbox, monkeypatch):
    import newshouse.inbox as ib
    from sqlalchemy import func
    mk(session)
    mk_card(session)
    monkeypatch.setattr(ib, "BATCH", 10)
    monkeypatch.setattr(ib, "MAX_PASSES", 3)
    with inbox.begin() as c:
        c.execute(insert(INBOX), [{"id": f"r{i:03d}", "received_at": NOW - timedelta(seconds=i),
                                   "body": {"action": "worth", "card_id": "card1"}}
                                  for i in range(45)])
    assert sync_feedback(session, inbox, profile_id="mihir", now=NOW)["fetched"] == 30
    with inbox.connect() as c:
        assert c.execute(select(func.count()).select_from(INBOX)
                         .where(INBOX.c.synced_at.is_(None))).scalar() == 15
    assert sync_feedback(session, inbox, profile_id="mihir", now=NOW)["fetched"] == 15


def test_sync_prunes_even_with_nothing_to_sync(session, inbox):
    put(inbox, "old", {"action": "worth", "card_id": "card1"}, NOW - timedelta(days=40))
    with inbox.begin() as c:
        c.execute(INBOX.update().values(synced_at=NOW - timedelta(days=31)))
    r = sync_feedback(session, inbox, profile_id="mihir", now=NOW)
    assert r["fetched"] == 0
    with inbox.connect() as c:
        assert c.execute(select(INBOX.c.id)).scalars().all() == []


def test_sync_rejects_a_row_with_both_card_and_cluster(session, inbox):
    from newshouse.models import Cluster
    mk(session)
    mk_card(session)
    cluster_id = session.scalars(select(Cluster.id)).first()
    assert cluster_id is not None
    put(inbox, "both", {"action": "worth", "card_id": "card1", "cluster_id": cluster_id})
    put(inbox, "tune-both", {"action": "tune", "card_id": "card1", "cluster_id": cluster_id,
                             "payload": {"budget": 1}})
    put(inbox, "tune", {"action": "tune", "payload": {"budget": 1}})
    r = sync_feedback(session, inbox, profile_id="mihir", now=NOW)
    assert r == {"fetched": 3, "recorded": 1, "duplicate": 0, "invalid": 2}
    assert [f.id for f in session.scalars(select(Feedback))] == ["tune"]


def test_inbox_engine_sets_postgres_timeouts(monkeypatch):
    import newshouse.inbox as ib
    from sqlalchemy import event
    seen = {}
    real = ib.create_engine

    def spy(url, **kw):
        seen["kw"] = kw
        return real(url, **kw)

    monkeypatch.setattr(ib, "create_engine", spy)
    eng = ib.inbox_engine("postgresql://u:p@h.neon.tech/db")  # no connection is made
    assert seen["kw"]["connect_args"] == {"connect_timeout": 10}
    assert event.contains(eng, "connect", ib._statement_timeout)
    ran = []

    class Cur:
        def execute(self, sql):
            ran.append(sql)

        def close(self):
            ran.append("closed")

    class DBAPIConn:
        def cursor(self):
            return Cur()

    ib._statement_timeout(DBAPIConn(), None)
    assert ran == ["SET statement_timeout = '30s'", "closed"]
    lite = ib.inbox_engine("sqlite://")  # SQLite gets neither
    assert "connect_args" not in seen["kw"]
    assert not event.contains(lite, "connect", ib._statement_timeout)
