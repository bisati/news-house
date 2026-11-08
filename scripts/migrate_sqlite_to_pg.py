"""Copy every News House table from one database to another (default use: SQLite -> Postgres).

    python scripts/migrate_sqlite_to_pg.py --from sqlite:///./newshouse.db --to "$DATABASE_URL"

Idempotent: rows already present in the target are skipped. Exits non-zero if any
table's source and target row counts differ.
"""
import argparse
import os
import sys

from sqlalchemy import func, insert, select

from newshouse.db import get_engine, init_db
from newshouse.models import Base

# Parents before children. clusters.thread_id references threads.id, so threads comes first
# (Postgres enforces foreign keys immediately).
TABLES = ["sources", "items", "item_sources", "threads", "clusters", "cluster_items",
          "editions", "cards", "also_happened", "feedback", "profiles", "runs"]
BATCH = 1000


def _insert(engine, table):
    if engine.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        return pg_insert(table).on_conflict_do_nothing()
    return insert(table).prefix_with("OR IGNORE")


def _count(conn, table) -> int:
    return conn.execute(select(func.count()).select_from(table)).scalar_one()


def migrate(from_url: str, to_url: str) -> dict[str, tuple[int, int]]:
    src, dst = get_engine(from_url), get_engine(to_url)
    try:
        init_db(dst)
        result: dict[str, tuple[int, int]] = {}
        for name in TABLES:
            table = Base.metadata.tables[name]
            stmt = _insert(dst, table)
            with src.connect() as sc, dst.begin() as dc:
                rows = sc.execution_options(stream_results=True).execute(select(table))
                for chunk in rows.mappings().partitions(BATCH):
                    dc.execute(stmt, [dict(r) for r in chunk])
            with src.connect() as sc, dst.connect() as dc:
                result[name] = (_count(sc, table), _count(dc, table))
        return result
    finally:
        src.dispose()
        dst.dispose()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--from", dest="src", default="sqlite:///./newshouse.db")
    p.add_argument("--to", dest="dst", default=os.environ.get("DATABASE_URL"))
    args = p.parse_args(argv)
    if not args.dst:
        p.error("--to or env DATABASE_URL is required")
    counts = migrate(args.src, args.dst)
    bad = False
    for name, (a, b) in counts.items():
        flag = "" if a == b else "  MISMATCH"
        bad = bad or a != b
        print(f"{name:15} source={a:<8} target={b:<8}{flag}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
