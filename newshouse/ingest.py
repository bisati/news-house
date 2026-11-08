"""One ingest run: fetch every enabled source and upsert items."""
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from newshouse.config import get_settings
from newshouse.fetch.feeds import fetch_feed
from newshouse.fetch.normalize import canonical_url, detect_lang, item_id
from newshouse.fetch.reddit import RedditClient, parse_reddit_url
from newshouse.models import Item, ItemSource, Run, Source

DEFAULT_KINDS = frozenset({"rss", "atom", "youtube", "podcast", "hn", "gnews", "reddit"})


class RunStats(BaseModel):
    sources_tried: int = 0
    sources_ok: int = 0
    sources_failed: dict[str, str] = Field(default_factory=dict)
    items_new: int = 0
    items_dup: int = 0
    items_stale: int = 0


def _ingest_source(session: Session, source: Source, res, now: datetime,
                   stale_after: timedelta, stats: RunStats) -> None:
    source.etag = res.etag or source.etag
    source.last_modified = res.last_modified or source.last_modified
    source.last_ok_at = now
    for raw in res.items:
        iid = item_id(source.url, raw)
        item = session.get(Item, iid)
        if item is not None:
            stats.items_dup += 1
            item.topics = sorted(set(item.topics) | set(source.topics))
        else:
            published = raw.published_at or now
            dated = raw.published_at is not None
            stale = dated and (now - published) > stale_after
            item = Item(
                id=iid, title=raw.title, url=raw.url, canonical_url=canonical_url(raw.url),
                teaser=raw.teaser, author=raw.author, published_at=published,
                first_seen_at=now, dated=dated, topics=list(source.topics),
                stale=stale, lang=detect_lang(raw.title), raw=raw.raw)
            session.add(item)
            stats.items_new += 1
            stats.items_stale += int(stale)
        if session.get(ItemSource, (iid, source.id)) is None:
            session.add(ItemSource(item_id=iid, source_id=source.id))
        session.flush()


def ingest(session: Session, *, now: datetime, client: httpx.Client,
           kinds: set[str] | frozenset[str] = DEFAULT_KINDS,
           stale_hours: int | None = None,
           reddit: RedditClient | None = None) -> RunStats:
    stale_after = timedelta(hours=stale_hours if stale_hours is not None
                            else get_settings().stale_hours)
    stats = RunStats()
    sources = session.scalars(
        select(Source).where(Source.enabled.is_(True), Source.kind.in_(kinds)).order_by(Source.url)
    ).all()
    for source in sources:
        stats.sources_tried += 1
        # work on a copy so a rolled-back savepoint cannot leave partial counts
        local = RunStats()
        try:
            with session.begin_nested():
                if source.kind == "reddit":
                    if reddit is None:
                        reddit = RedditClient(get_settings(), client)
                    res = reddit.fetch_listing(parse_reddit_url(source.url))
                else:
                    res = fetch_feed(source.url, kind=source.kind, etag=source.etag,
                                     last_modified=source.last_modified, client=client)
                if not res.ok:
                    stats.sources_failed[source.url] = res.error or f"status {res.status}"
                    continue
                _ingest_source(session, source, res, now, stale_after, local)
        except Exception as exc:  # isolate per source
            session.expire(source)
            stats.sources_failed[source.url] = f"{type(exc).__name__}: {exc}"
            continue
        stats.sources_ok += 1
        stats.items_new += local.items_new
        stats.items_dup += local.items_dup
        stats.items_stale += local.items_stale
    session.add(Run(id=uuid.uuid4().hex, kind="ingest", started_at=now,
                    finished_at=datetime.now(timezone.utc), status="ok",
                    stats=stats.model_dump()))
    session.flush()
    return stats
