"""Weekly source health check: refresh activity numbers and report dead sources."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from newshouse.fetch.feeds import fetch_feed
from newshouse.models import Run, Source

HEALTH_KINDS = {"rss", "atom", "youtube", "podcast", "hn", "gnews"}
FAILED_RUNS = 3


def check_sources(session: Session, *, client: httpx.Client, now: datetime) -> dict:
    previous = list(session.scalars(select(Run).where(Run.kind == "health")
                                    .order_by(Run.started_at.desc()).limit(FAILED_RUNS - 1)))
    prior_failed = [set((r.stats or {}).get("failed", {})) for r in previous]
    sources = session.scalars(select(Source).where(Source.enabled.is_(True),
                                                   Source.kind.in_(HEALTH_KINDS))
                              .order_by(Source.url)).all()
    ok = 0
    failed: dict[str, str] = {}
    stale30: list[str] = []
    for src in sources:
        res = fetch_feed(src.url, kind=src.kind, client=client)
        if not res.ok:
            failed[src.url] = res.error or "failed"
            continue
        ok += 1
        dates = [i.published_at for i in res.items if i.published_at is not None]
        src.last7d = sum(1 for d in dates if d >= now - timedelta(days=7))
        src.last_ok_at = now
        if not dates or max(dates) < now - timedelta(days=30):
            stale30.append(src.url)
    streak = len(prior_failed) == FAILED_RUNS - 1
    dead = [u for u in failed if streak and all(u in p for p in prior_failed)]
    dead += [u for u in stale30 if u not in dead]
    report = {"checked": len(sources), "ok": ok, "failed": failed,
              "dead": dead, "stale30": stale30}
    session.add(Run(id=uuid.uuid4().hex, kind="health", started_at=now,
                    finished_at=datetime.now(timezone.utc),
                    status="ok", stats=report))
    session.commit()
    return report
