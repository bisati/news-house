"""The feedback inbox: a one-table Postgres (Neon) that the hosted page's endpoint writes taps
into, and the Mac-side sync that records them into the local database.

SQLAlchemy Core only, so it runs on SQLite too (tests use a temp file in place of Neon).
The connection URL is a secret: nothing here prints or logs it.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import (JSON, Column, MetaData, String, Table, create_engine, delete, event,
                        select, update)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from newshouse.feedback import record_feedback
from newshouse.models import Card, Cluster, Feedback, UTCDateTime

log = logging.getLogger(__name__)

MAX_LEN = 64
BATCH = 500        # unsynced rows fetched per pass
MAX_PASSES = 20    # per sync; anything left waits for the next tick
_meta = MetaData()
INBOX = Table(
    "feedback_inbox", _meta,
    Column("id", String, primary_key=True),
    Column("received_at", UTCDateTime, nullable=False),
    Column("body", JSON().with_variant(JSON(none_as_null=True), "sqlite"), nullable=False),
    Column("synced_at", UTCDateTime, nullable=True),
)


def _statement_timeout(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    try:
        cur.execute("SET statement_timeout = '30s'")
    finally:
        cur.close()


def inbox_engine(url: str) -> Engine:
    """Engine for the inbox; ``postgres://`` and ``postgresql://`` become psycopg 3. On
    Postgres a connect takes at most 10 s and a statement at most 30 s, so a slow Neon
    cannot stall the tick."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = "postgresql+psycopg://" + url[len(prefix):]
            break
    if not url.startswith("postgresql"):
        return create_engine(url, pool_pre_ping=True)
    engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 10})
    event.listen(engine, "connect", _statement_timeout)
    return engine


def init_inbox(engine: Engine) -> None:
    _meta.create_all(engine, checkfirst=True)


def _fetch(engine: Engine, limit: int) -> list:
    with engine.connect() as c:
        return c.execute(select(INBOX.c.id, INBOX.c.received_at, INBOX.c.body)
                         .where(INBOX.c.synced_at.is_(None))
                         .order_by(INBOX.c.received_at, INBOX.c.id).limit(limit)).all()


def sync_feedback(session: Session, engine: Engine, *, profile_id: str, now: datetime,
                  keep_days: int = 30) -> dict:
    """Record unsynced inbox rows as Feedback (id = inbox id, at = received_at) in passes of
    at most ``BATCH`` rows (at most ``MAX_PASSES`` passes), mark every fetched row synced
    after its pass, and delete rows synced more than ``keep_days`` ago."""
    counts = {"fetched": 0, "recorded": 0, "duplicate": 0, "invalid": 0}
    for _ in range(MAX_PASSES):
        rows = _fetch(engine, BATCH)
        if not rows:
            break
        counts["fetched"] += len(rows)
        for rid, received_at, body in rows:
            if session.get(Feedback, rid) is not None:
                counts["duplicate"] += 1
                continue
            try:
                with session.begin_nested():  # a savepoint per row: one bad row cannot sink the rest
                    _record(session, rid, received_at, body, profile_id)
                counts["recorded"] += 1
            except Exception as e:  # public input: never let a poison row block the inbox
                log.warning("dropped inbox row: %s", type(e).__name__)
                counts["invalid"] += 1
        session.commit()  # the feedback is durable before the inbox is told it was synced
        with engine.begin() as c:
            c.execute(update(INBOX).where(INBOX.c.id.in_([r.id for r in rows]))
                      .values(synced_at=now))
        if len(rows) < BATCH:
            break
    with engine.begin() as c:  # its own statement, every sync
        c.execute(delete(INBOX).where(INBOX.c.synced_at < now - timedelta(days=keep_days)))
    return counts


def _record(session: Session, rid: str, received_at: datetime, body, profile_id: str) -> None:
    if not isinstance(body, dict):
        raise ValueError("body is not an object")
    card_id, cluster_id = body.get("card_id"), body.get("cluster_id")
    if card_id is not None and cluster_id is not None:  # as serve.py: one target at most
        raise ValueError("both card_id and cluster_id")
    for v in (card_id, cluster_id):
        if v is not None and (not isinstance(v, str) or len(v) > MAX_LEN):
            raise ValueError("bad id")
    if card_id is not None and session.get(Card, card_id) is None:
        raise ValueError("unknown card")
    if cluster_id is not None and session.get(Cluster, cluster_id) is None:
        raise ValueError("unknown cluster")
    payload = body.get("payload")
    if payload is not None and not isinstance(payload, dict):
        raise ValueError("payload is not an object")
    action = body.get("action")
    if not isinstance(action, str) or len(action) > MAX_LEN:
        raise ValueError("action is not a string")
    record_feedback(session, id=rid, profile_id=profile_id, action=action, card_id=card_id,
                    cluster_id=cluster_id, at=received_at, payload=payload)
