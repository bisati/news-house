import importlib.util
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import event
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Engine

from newshouse.db import get_engine, init_db, session_scope, vec_to_bytes
from newshouse.models import (Base, AlsoHappened, Card, Cluster, ClusterItem, Edition, Feedback,
                              Item, ItemSource, Profile, Run, Source, Thread)

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "migrate_sqlite_to_pg.py"
NOW = datetime(2026, 10, 30, 6, 0, tzinfo=timezone.utc)


def _load():
    spec = importlib.util.spec_from_file_location("migrate_sqlite_to_pg", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _seed(url):
    eng = get_engine(url)
    init_db(eng)
    with session_scope(eng) as s:
        s.add(Source(id="s1", name="N", topics=["tech"], tier="a", kind="rss",
                     url="http://x", paywall=False))
        s.add(Item(id="i1", title="t", url="u", canonical_url="u", teaser="x",
                   published_at=NOW, first_seen_at=NOW, dated=True, topics=["tech"],
                   embedding=vec_to_bytes(np.ones(3)), raw={"k": 1}))
        s.add(Thread(id="t1", title="T", summary="S", opened_at=NOW, last_chapter_at=NOW))
        s.flush()
        s.flush()
        s.add(Cluster(id="c1", window_start=NOW, topics=["tech"], thread_id="t1"))
        s.add(Edition(id="e1", date=date(2026, 10, 30), budget_seconds=900))
        s.flush()
        s.add(ItemSource(item_id="i1", source_id="s1"))
        s.add(ClusterItem(cluster_id="c1", item_id="i1"))
        s.add(Card(id="k1", edition_id="e1", rank=1, cluster_id="c1", format="para",
                   payload={"a": 1}, headline="h", line="l", para="p", brief="b",
                   why="w", est_seconds=30, cited_item_ids=["i1"]))
        s.add(AlsoHappened(edition_id="e1", cluster_id="c1", rank=1, line="l"))
        s.add(Feedback(id="f1", card_id="k1", cluster_id="c1", action="worth", at=NOW))
        s.add(Profile(id="p1", version=1, text="x"))
        s.add(Run(id="r1", kind="tick", started_at=NOW, status="ok", stats={}))
    eng.dispose()


@pytest.fixture
def sqlite_fk_on():
    def _on(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")
    event.listen(Engine, "connect", _on)
    yield
    event.remove(Engine, "connect", _on)


def test_migrate_copies_all_tables_sqlite_to_sqlite(tmp_path, sqlite_fk_on):
    mod = _load()
    src, dst = f"sqlite:///{tmp_path}/src.db", f"sqlite:///{tmp_path}/dst.db"
    _seed(src)
    counts = mod.migrate(src, dst)
    assert list(counts) == mod.TABLES and len(counts) == 12
    assert all(a == b == 1 for a, b in counts.values())
    assert mod.migrate(src, dst) == counts  # idempotent
    eng = get_engine(dst)
    with session_scope(eng) as s:
        it = s.get(Item, "i1")
        assert it.raw == {"k": 1} and it.published_at == NOW
    eng.dispose()


def test_table_order_satisfies_foreign_keys():
    mod = _load()
    pos = {n: i for i, n in enumerate(mod.TABLES)}
    assert set(pos) == set(Base.metadata.tables)
    for name in mod.TABLES:
        for fk in Base.metadata.tables[name].foreign_keys:
            parent = fk.column.table.name
            if parent != name:
                assert pos[parent] < pos[name], f"{parent} must precede {name}"


def test_postgres_insert_compiles():
    from types import SimpleNamespace
    mod = _load()
    eng = SimpleNamespace(dialect=postgresql.dialect())
    sql = str(mod._insert(eng, Base.metadata.tables["items"]).compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT DO NOTHING" in sql
