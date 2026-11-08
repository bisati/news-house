from datetime import date, datetime, timezone

import numpy as np
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from newshouse.db import bytes_to_vec, ensure_columns, get_engine, init_db, session_scope, vec_to_bytes
from newshouse.models import AlsoHappened, Card, Cluster, Edition, Item, Run, Source

@pytest.fixture
def engine(tmp_path):
    eng = get_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(eng)
    yield eng
    eng.dispose()


TABLES = {"sources", "items", "item_sources", "clusters", "cluster_items", "threads",
          "editions", "cards", "also_happened", "feedback", "profiles", "runs"}


def test_init_db_creates_all_tables(engine):
    eng = engine
    assert TABLES <= set(inspect(eng).get_table_names())


def test_edition_unique_per_profile_date(engine):
    eng = engine
    d = date(2026, 10, 30)
    with pytest.raises(IntegrityError):
        with session_scope(eng) as s:
            s.add(Edition(id="a", profile_id="mihir", date=d, budget_seconds=900))
            s.add(Edition(id="b", profile_id="mihir", date=d, budget_seconds=900))


def test_vector_roundtrip():
    v = np.array([0.5, -1.25, 3.0], dtype=np.float32)
    assert np.array_equal(bytes_to_vec(vec_to_bytes(v)), v)


def test_defaults_and_json_and_embedding_roundtrip(engine):
    eng = engine
    now = datetime(2026, 10, 30, tzinfo=timezone.utc)
    with session_scope(eng) as s:
        s.add(Source(id="s1", name="N", topics=["tech"], tier="a", kind="rss",
                     url="http://x", paywall=False))
        s.add(Item(id="i1", title="t", url="u", canonical_url="u", teaser="x",
                   published_at=now, first_seen_at=now, dated=True, topics=["tech"],
                   embedding=vec_to_bytes(np.ones(3)), raw={"k": 1}))
    with session_scope(eng) as s:
        src = s.get(Source, "s1")
        assert src.enabled is True and src.created_at is not None
        it = s.get(Item, "i1")
        assert it.stale is False and it.topics == ["tech"] and it.raw == {"k": 1}
        assert bytes_to_vec(it.embedding).tolist() == [1.0, 1.0, 1.0]


def test_datetimes_round_trip_aware(engine):
    orig = datetime(2026, 10, 30, 6, 0, tzinfo=timezone.utc)
    with session_scope(engine) as s:
        s.add(Run(id="r1", kind="ingest", started_at=orig, status="ok", stats={}))
    with session_scope(engine) as s:
        r = s.get(Run, "r1")
        assert r.started_at.tzinfo is not None
        assert r.started_at == orig
        assert r.created_at.tzinfo is not None


def test_naive_datetime_rejected(engine):
    with pytest.raises(Exception, match="naive datetime"):
        with session_scope(engine) as s:
            s.add(Run(id="r2", kind="ingest", started_at=datetime(2026, 10, 30, 6, 0),
                      status="ok", stats={}))


def test_new_columns_have_defaults(session):
    now = datetime(2026, 10, 30, 6, 0, tzinfo=timezone.utc)
    session.add(Edition(id="e1", date=date(2026, 10, 30), built_at=now, budget_seconds=900))
    session.add(Cluster(id="c0", window_start=now, topics=["ai-models"]))
    session.flush()
    session.add(Card(id="card0", edition_id="e1", rank=1, cluster_id="c0", format="A", payload={},
                     headline="h", line="l", para="p", brief="b", why="w", est_seconds=60,
                     cited_item_ids=[]))
    session.add(AlsoHappened(edition_id="e1", cluster_id="c0", rank=1, line="x"))
    session.flush()
    card = session.get(Card, "card0")
    assert card.visual == "none" and card.slides == [] and card.tone is None
    ed = session.get(Edition, "e1")
    assert ed.top_ids == [] and ed.warnings == []
    ah = session.get(AlsoHappened, ("e1", "c0"))
    assert ah.is_top is False and ah.cut_reason is None


def test_ensure_columns_adds_missing(tmp_path):
    eng = get_engine(f"sqlite:///{tmp_path/'old.db'}")
    init_db(eng)
    with eng.begin() as c:
        c.execute(text("ALTER TABLE cards DROP COLUMN visual"))
        c.execute(text("ALTER TABLE editions DROP COLUMN warnings"))
    added = ensure_columns(eng)
    assert added == ["cards.visual", "editions.warnings"]
    assert ensure_columns(eng) == []
    eng.dispose()


def test_ensure_columns_backfills_defaults_for_existing_rows(tmp_path):
    eng = get_engine(f"sqlite:///{tmp_path/'old.db'}")
    init_db(eng)
    with eng.begin() as c:
        c.execute(text("ALTER TABLE editions DROP COLUMN top_ids"))
        c.execute(text("ALTER TABLE editions DROP COLUMN warnings"))
        c.execute(text("ALTER TABLE editions DROP COLUMN live"))  # phase 3: an older db lacks it too
        c.execute(text("INSERT INTO editions (id, profile_id, date, budget_seconds, created_at) "
                       "VALUES ('e1', 'mihir', '2026-10-30', 900, '2026-10-30 00:00:00')"))
    ensure_columns(eng)
    from sqlalchemy.orm import Session
    with Session(eng) as s:
        ed = s.get(Edition, "e1")
        assert ed.top_ids == [] and ed.warnings == [] and ed.live == {}
    eng.dispose()


def test_phase2_columns_exist(tmp_path):
    from datetime import datetime, timezone
    from sqlalchemy.orm import Session
    eng = get_engine(f"sqlite:///{tmp_path/'p2.db'}")
    init_db(eng)
    now = datetime(2026, 11, 3, tzinfo=timezone.utc)
    with Session(eng) as s:
        s.add(Item(id="i1", title="t", url="u", canonical_url="u", teaser="x", published_at=now,
                   first_seen_at=now, dated=True, topics=[], raw={},
                   image_url="https://a/b.jpg", image_w=800, image_h=450))
        s.add(Cluster(id="c1", window_start=now, topics=[], tone="bad"))
        s.commit()
    with Session(eng) as s:
        it = s.get(Item, "i1")
        assert (it.image_url, it.image_w, it.image_h) == ("https://a/b.jpg", 800, 450)
        assert s.get(Cluster, "c1").tone == "bad"
    with eng.begin() as c:
        for col in ("image_url", "image_w", "image_h"):
            c.execute(text(f"ALTER TABLE items DROP COLUMN {col}"))
        c.execute(text("ALTER TABLE clusters DROP COLUMN tone"))
    added = ensure_columns(eng)
    assert set(added) == {"items.image_url", "items.image_w", "items.image_h", "clusters.tone"}
    assert ensure_columns(eng) == []
    eng.dispose()


def test_cli_upgrades_a_v1_database_before_any_command(tmp_path, monkeypatch, capsys):
    """A v1-era database (no phase 2 columns) re-renders the 30 October edition."""
    import newshouse.db as db
    from sqlalchemy.orm import Session
    from newshouse.cli import main
    from tests.helpers import seed_edition
    eng = get_engine(f"sqlite:///{tmp_path/'v1.db'}")
    init_db(eng)
    with Session(eng) as s:
        seed_edition(s, [(1, "A", "Short head", {}, {})])
        s.commit()
    with eng.begin() as c:
        for col in ("image_url", "image_w", "image_h"):
            c.execute(text(f"ALTER TABLE items DROP COLUMN {col}"))
        c.execute(text("ALTER TABLE clusters DROP COLUMN tone"))
    (tmp_path / "profile.md").write_text("Mihir, PM")
    monkeypatch.setenv("PROFILE_PATH", str(tmp_path / "profile.md"))
    monkeypatch.setattr(db, "_engine", eng)
    try:
        assert main(["render", "--date", "2026-10-30", "--out", str(tmp_path / "out"),
                     "--validate"]) == 0
        cols = {t: {c["name"] for c in inspect(eng).get_columns(t)} for t in ("items", "clusters")}
    finally:
        eng.dispose()
    assert {"image_url", "image_w", "image_h"} <= cols["items"] and "tone" in cols["clusters"]
    assert (tmp_path / "out").exists() and capsys.readouterr().out.strip()


def _render_cli(tmp_path, monkeypatch, date_arg):
    import newshouse.db as db
    from newshouse.cli import main
    assert main(["render", "--date", date_arg, "--out", str(tmp_path / "out")]) == 0


def test_render_refreshes_latest(tmp_path, monkeypatch):
    import newshouse.db as db
    from sqlalchemy.orm import Session
    from tests.helpers import seed_edition, NOW
    eng = get_engine(f"sqlite:///{tmp_path/'r.db'}")
    init_db(eng)
    with Session(eng) as s:
        seed_edition(s, [(1, "A", "Old head", {}, {})])
        s.add(Edition(id="e2", date=date(2026, 11, 3), built_at=NOW, budget_seconds=900, cut_score=40.0))
        s.commit()
    (tmp_path / "profile.md").write_text("Mihir, PM")
    monkeypatch.setenv("PROFILE_PATH", str(tmp_path / "profile.md"))
    monkeypatch.setattr(db, "_engine", eng)
    out = tmp_path / "out"
    try:
        _render_cli(tmp_path, monkeypatch, "2026-11-03")
        assert (out / "latest.html").read_text() == (out / "2026-11-03.html").read_text()
        before = (out / "latest.html").read_text()
        _render_cli(tmp_path, monkeypatch, "2026-10-30")
        assert (out / "2026-10-30.html").exists()
        assert (out / "latest.html").read_text() == before
    finally:
        eng.dispose()
