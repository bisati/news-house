"""The lessons ledger (spec 4.7): stories the paper missed, why, and the fix.

``ledger/lessons.json`` is the source of truth, committed with the repo. Stubs come
from "Should have been in" taps on cut top lines, made at the next build (never by the
page server). The last ten lessons go into the classify prompt; an ``owed`` lesson is
checked by the validator.
"""
from __future__ import annotations

import json
import logging
from datetime import date as date_
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from newshouse.models import AlsoHappened, Cluster, Edition, Feedback, Run

log = logging.getLogger(__name__)


class Lesson(BaseModel):
    id: str
    date: str  # ISO date
    miss: str
    why: str = ""
    fix: str = ""
    owed: dict | None = None  # {"thread_id": ...} or {"topic": ...}
    status: Literal["open", "done"] = "open"
    feedback_id: str | None = None
    cluster_id: str | None = None
    score: float | None = None
    cut_reason: str | None = None
    run_id: str | None = None


_LIST = TypeAdapter(list[Lesson])


def load_lessons(path: Path) -> list[Lesson]:
    """The ledger; a missing file is an empty ledger. A malformed file raises."""
    path = Path(path)
    if not path.exists():
        return []
    return _LIST.validate_json(path.read_text(encoding="utf-8") or "[]")


def read_lessons(path: Path | None) -> list[Lesson]:
    """Like ``load_lessons`` but never raises: for readers (classify, validator)."""
    if path is None:
        return []
    try:
        return load_lessons(path)
    except Exception as e:  # a hand-edited ledger with a typo must not stop a build
        log.warning("lessons ledger %s unreadable: %r", path, e)
        return []


def _order(lessons: list[Lesson]) -> list[Lesson]:
    return sorted(lessons, key=lambda l: (l.date, l.id))


def save_lessons(path: Path, lessons: list[Lesson]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [l.model_dump() for l in _order(lessons)]
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def recent(lessons: list[Lesson], n: int = 10) -> list[Lesson]:
    """The ``n`` newest lessons, oldest first."""
    return _order(lessons)[-n:] if n > 0 else []


def _next_id(lessons: list[Lesson], today: date_) -> str:
    taken = {l.id for l in lessons}
    n = 1
    while f"{today.isoformat()}-{n:03d}" in taken:
        n += 1
    return f"{today.isoformat()}-{n:03d}"  # zero-padded so ids sort in order


def _append(path: Path, lesson_kw: dict, *, today: date_) -> Lesson:
    lessons = load_lessons(path)
    lesson = Lesson(id=_next_id(lessons, today), date=today.isoformat(), **lesson_kw)
    save_lessons(path, lessons + [lesson])
    return lesson


def add_text(path: Path, text: str, *, today: date_) -> Lesson:
    return _append(path, {"miss": text}, today=today)


def _cut_row(session: Session, cluster_id: str):
    """The newest also row holding the cluster (and its edition), top rows first."""
    rows = session.execute(
        select(AlsoHappened, Edition).join(Edition, Edition.id == AlsoHappened.edition_id)
        .where(AlsoHappened.cluster_id == cluster_id)).all()
    if not rows:
        return None
    return max(rows, key=lambda r: (bool(r[0].is_top), r[1].built_at is not None,
                                    r[1].built_at or r[1].created_at, r[1].date))


def _cutting_run(session: Session, edition: Edition) -> str | None:
    """The build run whose span holds the edition's ``built_at``; None when there is
    no such run or more than one."""
    if edition.built_at is None:
        return None
    ids = [r.id for r in session.scalars(select(Run).where(
        Run.kind == "build", Run.started_at <= edition.built_at))
        if r.finished_at is None or r.finished_at >= edition.built_at]
    return ids[0] if len(ids) == 1 else None


def stub_from_feedback(session: Session, path: Path, feedback_id: str, *,
                       today: date_) -> Lesson | None:
    """A stub lesson for a ``should_have`` tap; None when the tap already has a lesson,
    is missing, or is not a ``should_have`` on a cluster."""
    fb = session.get(Feedback, feedback_id)
    if fb is None or fb.action != "should_have" or not fb.cluster_id:
        return None
    if any(l.feedback_id == feedback_id for l in load_lessons(path)):
        return None
    cluster = session.get(Cluster, fb.cluster_id)
    found = _cut_row(session, fb.cluster_id)
    line, cut_reason, run_id = fb.cluster_id, None, None
    if found is not None:
        row, edition = found
        line, cut_reason, run_id = row.line or fb.cluster_id, row.cut_reason, _cutting_run(session, edition)
    return _append(path, {"miss": f"Should have been in: {line}", "feedback_id": feedback_id,
                          "cluster_id": fb.cluster_id,
                          "score": cluster.final_score if cluster else None,
                          "cut_reason": cut_reason, "run_id": run_id}, today=today)


def pending_should_have(session: Session, path: Path, *, profile_id: str) -> list[str]:
    """Feedback ids of ``should_have`` taps on cut top lines that have no lesson yet."""
    have = {l.feedback_id for l in load_lessons(path) if l.feedback_id}
    rows = session.execute(
        select(Feedback.id, Feedback.cluster_id).where(
            Feedback.profile_id == profile_id, Feedback.action == "should_have",
            Feedback.cluster_id.is_not(None)).order_by(Feedback.at, Feedback.id)).all()
    if not rows:
        return []
    tops = set(session.scalars(select(AlsoHappened.cluster_id).where(
        AlsoHappened.is_top == True,  # noqa: E712
        AlsoHappened.cluster_id.in_({cid for _, cid in rows}))))
    return [fid for fid, cid in rows if cid in tops and fid not in have]


def make_stubs(session: Session, path: Path, *, profile_id: str, today: date_) -> int:
    """Stub every pending tap; the build calls this at its start."""
    made = 0
    for fid in pending_should_have(session, path, profile_id=profile_id):
        if stub_from_feedback(session, path, fid, today=today) is not None:
            made += 1
    return made
