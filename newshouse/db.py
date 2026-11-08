"""Engine, session and init helpers."""
import json
from contextlib import contextmanager
from typing import Iterator

import numpy as np
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.orm import Session

from newshouse.config import get_settings
from newshouse.models import Base

_engine: Engine | None = None


def get_engine(url: str | None = None) -> Engine:
    url = url or get_settings().database_url
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    return create_engine(url, **kwargs)


def _default_literal(col, dialect) -> str | None:
    """SQL literal for a column's Python-side default, so old rows get a value too."""
    d = col.default
    if d is None or not getattr(d, "is_scalar", False) and not getattr(d, "is_callable", False):
        return None
    if d.is_callable:
        value = d.arg(None)  # SQLAlchemy wraps callables to take a context argument
    else:
        value = d.arg
    if isinstance(value, bool):
        return ("1" if value else "0") if dialect.name == "sqlite" else str(value).lower()
    if isinstance(value, (list, dict)):
        return "'" + json.dumps(value).replace("'", "''") + "'"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return None


def ensure_columns(engine: Engine) -> list[str]:
    """Add columns the models have but an older database lacks (create_all never does).
    Returns "table.column" for each one added; idempotent."""
    added: list[str] = []
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in sorted(Base.metadata.tables.values(), key=lambda t: t.name):
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ddl = (f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" '
                       f"{col.type.compile(dialect=engine.dialect)}")
                lit = _default_literal(col, engine.dialect)
                if lit is not None:
                    ddl += f" DEFAULT {lit}"
                    if not col.nullable:
                        ddl += " NOT NULL"
                conn.execute(text(ddl))
                added.append(f"{table.name}.{col.name}")
    return added


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    ensure_columns(engine)


def default_engine() -> Engine:
    """The process-wide engine ``session_scope`` uses when given none."""
    global _engine
    if _engine is None:
        _engine = get_engine()
    return _engine


@contextmanager
def session_scope(engine: Engine | None = None) -> Iterator[Session]:
    """Commit on success, roll back on error. Uses the default engine if none given."""
    if engine is None:
        engine = default_engine()
    session = Session(engine, expire_on_commit=False)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def vec_to_bytes(v) -> bytes:
    return np.asarray(v, dtype=np.float32).tobytes()


def bytes_to_vec(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32)
