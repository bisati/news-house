"""SQLAlchemy table definitions for News House."""
from datetime import date as date_, datetime, timezone

from sqlalchemy import (JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer,
                        LargeBinary, String, Text, UniqueConstraint)
from sqlalchemy.types import TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes on every backend (SQLite drops tzinfo)."""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime not allowed; use timezone-aware UTC")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dt(nullable: bool = False):
    return mapped_column(UTCDateTime, nullable=nullable)


class Base(DeclarativeBase):
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    topics: Mapped[list] = mapped_column(JSON)
    tier: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    url: Mapped[str] = mapped_column(String, unique=True)
    home: Mapped[str | None] = mapped_column(String, nullable=True)
    paywall: Mapped[bool] = mapped_column(Boolean)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_ok_at: Mapped[datetime | None] = _dt(True)
    last7d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    etag: Mapped[str | None] = mapped_column(String, nullable=True)
    last_modified: Mapped[str | None] = mapped_column(String, nullable=True)


class Item(Base):
    __tablename__ = "items"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String)
    url: Mapped[str] = mapped_column(String)
    canonical_url: Mapped[str] = mapped_column(String)
    teaser: Mapped[str] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(String, nullable=True)
    published_at: Mapped[datetime] = _dt()
    first_seen_at: Mapped[datetime] = _dt()
    dated: Mapped[bool] = mapped_column(Boolean)
    lang: Mapped[str | None] = mapped_column(String, nullable=True)
    topics: Mapped[list] = mapped_column(JSON)
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    raw: Mapped[dict] = mapped_column(JSON)
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    image_w: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_h: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ItemSource(Base):
    __tablename__ = "item_sources"
    item_id: Mapped[str] = mapped_column(ForeignKey("items.id"), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), primary_key=True)


class Thread(Base):
    __tablename__ = "threads"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String)
    summary: Mapped[str] = mapped_column(Text)
    opened_at: Mapped[datetime] = _dt()
    last_chapter_at: Mapped[datetime] = _dt()
    closed_at: Mapped[datetime | None] = _dt(True)
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    chapters: Mapped[int] = mapped_column(Integer, default=0)


class Cluster(Base):
    __tablename__ = "clusters"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    window_start: Mapped[datetime] = _dt()
    topics: Mapped[list] = mapped_column(JSON)
    story_type: Mapped[str | None] = mapped_column(String, nullable=True)
    importance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    early: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    breaking_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    is_delta: Mapped[bool] = mapped_column(Boolean, default=True)
    final_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    thread_id: Mapped[str | None] = mapped_column(ForeignKey("threads.id"), nullable=True)
    chapter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    breaking: Mapped[bool] = mapped_column(Boolean, default=False)
    scored_at: Mapped[datetime | None] = _dt(True)
    carded: Mapped[bool] = mapped_column(Boolean, default=False)
    tone: Mapped[str | None] = mapped_column(String, nullable=True)


class ClusterItem(Base):
    __tablename__ = "cluster_items"
    cluster_id: Mapped[str] = mapped_column(ForeignKey("clusters.id"), primary_key=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("items.id"), primary_key=True)


class Edition(Base):
    __tablename__ = "editions"
    __table_args__ = (UniqueConstraint("profile_id", "date"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    profile_id: Mapped[str] = mapped_column(String, default="mihir")
    date: Mapped[date_] = mapped_column(Date)
    built_at: Mapped[datetime | None] = _dt(True)
    budget_seconds: Mapped[int] = mapped_column(Integer)
    cut_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    profile_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    top_ids: Mapped[list] = mapped_column(JSON, default=list)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    live: Mapped[dict] = mapped_column(JSON, default=dict)


class Card(Base):
    __tablename__ = "cards"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    edition_id: Mapped[str] = mapped_column(ForeignKey("editions.id"))
    rank: Mapped[int] = mapped_column(Integer)
    cluster_id: Mapped[str] = mapped_column(ForeignKey("clusters.id"))
    thread_id: Mapped[str | None] = mapped_column(String, nullable=True)
    chapter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    format: Mapped[str] = mapped_column(String)
    visual: Mapped[str] = mapped_column(String, default="none")
    slides: Mapped[list] = mapped_column(JSON, default=list)
    tone: Mapped[str | None] = mapped_column(String, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)
    headline: Mapped[str] = mapped_column(String)
    line: Mapped[str] = mapped_column(Text)
    para: Mapped[str] = mapped_column(Text)
    brief: Mapped[str] = mapped_column(Text)
    why: Mapped[str] = mapped_column(Text)
    est_seconds: Mapped[int] = mapped_column(Integer)
    cited_item_ids: Mapped[list] = mapped_column(JSON)
    breaking: Mapped[bool] = mapped_column(Boolean, default=False)
    unverified: Mapped[bool] = mapped_column(Boolean, default=False)
    # the story's follow-ups, read by swiping: [{cluster_id, headline, line, url, source}]
    stack: Mapped[list] = mapped_column(JSON, default=list)


class AlsoHappened(Base):
    __tablename__ = "also_happened"
    edition_id: Mapped[str] = mapped_column(ForeignKey("editions.id"), primary_key=True)
    cluster_id: Mapped[str] = mapped_column(ForeignKey("clusters.id"), primary_key=True)
    rank: Mapped[int] = mapped_column(Integer)
    line: Mapped[str] = mapped_column(Text)
    cut_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    is_top: Mapped[bool] = mapped_column(Boolean, default=False)
    folded: Mapped[bool] = mapped_column(Boolean, default=False)  # kept only to explain a cut top story


class Feedback(Base):
    __tablename__ = "feedback"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    profile_id: Mapped[str] = mapped_column(String, default="mihir")
    card_id: Mapped[str | None] = mapped_column(String, nullable=True)
    cluster_id: Mapped[str | None] = mapped_column(String, nullable=True)
    action: Mapped[str] = mapped_column(String)  # see feedback.ACTIONS
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    at: Mapped[datetime] = _dt()


class Profile(Base):
    __tablename__ = "profiles"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    profile_id: Mapped[str] = mapped_column(String, default="mihir")
    version: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String)
    started_at: Mapped[datetime] = _dt()
    finished_at: Mapped[datetime | None] = _dt(True)
    status: Mapped[str] = mapped_column(String)
    stats: Mapped[dict] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
