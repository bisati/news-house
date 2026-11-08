from datetime import date, datetime, timedelta, timezone

import pytest

from newshouse.lessons import (Lesson, add_text, load_lessons, pending_should_have, recent,
                               save_lessons, stub_from_feedback)
from newshouse.models import AlsoHappened, Cluster, Edition, Feedback, Run

NOW = datetime(2026, 10, 30, 6, 0, tzinfo=timezone.utc)
TODAY = date(2026, 10, 31)


def seed_cut(session, *, is_top=True, cid="c1"):
    session.add(Run(id="run1", kind="build", started_at=NOW - timedelta(minutes=5),
                    finished_at=NOW + timedelta(minutes=1), status="ok", stats={}))
    session.add(Run(id="other", kind="tick", started_at=NOW - timedelta(minutes=5),
                    finished_at=NOW + timedelta(minutes=1), status="ok", stats={}))
    session.add(Edition(id="e1", date=NOW.date(), built_at=NOW, budget_seconds=900))
    session.add(Cluster(id=cid, window_start=NOW, topics=["cricket"], final_score=71.5))
    session.flush()
    session.add(AlsoHappened(edition_id="e1", cluster_id=cid, rank=1, line="IPL auction opens",
                             cut_reason="topic cap cricket (2)", is_top=is_top))
    session.add(Feedback(id="fb1", cluster_id=cid, action="should_have", at=NOW))
    session.flush()


def test_lessons_round_trip(tmp_path):
    path = tmp_path / "lessons.json"
    assert load_lessons(path) == []
    lessons = [Lesson(id="b", date="2026-10-31", miss="Two"),
               Lesson(id="a", date="2026-10-30", miss="One", owed={"topic": "cricket"})]
    save_lessons(path, lessons)
    assert path.read_text().endswith("\n")
    loaded = load_lessons(path)
    assert loaded == sorted(lessons, key=lambda l: (l.date, l.id))
    assert [l.id for l in recent(loaded, n=1)] == ["b"]


def test_add_text_and_cli(tmp_path, monkeypatch, capsys):
    import newshouse.db as db
    from newshouse.cli import main
    from newshouse.config import get_settings
    path = tmp_path / "ledger" / "lessons.json"
    monkeypatch.setenv("LESSONS_PATH", str(path))
    get_settings.cache_clear()
    engine = db.get_engine(f"sqlite:///{tmp_path / 'cli.db'}")
    db.init_db(engine)
    monkeypatch.setattr(db, "_engine", engine)
    try:
        assert main(["lesson", "add", "--text", "Missed the IPL auction"]) == 0
        new_id = capsys.readouterr().out.strip()
        lessons = load_lessons(path)
        assert len(lessons) == 1
        assert lessons[0].id == new_id and lessons[0].status == "open"
        assert lessons[0].miss == "Missed the IPL auction"
        assert main(["lesson", "list"]) == 0
        out = capsys.readouterr().out.strip().splitlines()
        assert len(out) == 1 and new_id in out[0] and "IPL auction" in out[0]
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_add_text_ids_unique_and_sort_in_order(tmp_path):
    path = tmp_path / "l.json"
    made = [add_text(path, f"miss {n}", today=TODAY) for n in range(1, 12)]
    assert made[0].id == "2026-10-31-001" and made[-1].id == "2026-10-31-011"
    assert len({l.id for l in made}) == 11 and made[0].date == "2026-10-31"
    loaded = load_lessons(path)
    assert [l.miss for l in loaded] == [f"miss {n}" for n in range(1, 12)]
    assert recent(loaded, n=1)[0].miss == "miss 11"


def test_settings_ledger_is_isolated(tmp_path, lessons_path):
    from newshouse.config import Settings, get_settings
    assert lessons_path.parent == tmp_path
    assert get_settings().lessons_path == lessons_path
    assert Settings(database_url="sqlite://").lessons_path == lessons_path


def test_lesson_stub_is_idempotent(session, tmp_path):
    path = tmp_path / "l.json"
    seed_cut(session)
    assert pending_should_have(session, path, profile_id="mihir") == ["fb1"]
    stub = stub_from_feedback(session, path, "fb1", today=TODAY)
    assert stub.miss == "Should have been in: IPL auction opens"
    assert stub.score == 71.5 and stub.cut_reason == "topic cap cricket (2)"
    assert stub.run_id == "run1" and stub.cluster_id == "c1" and stub.feedback_id == "fb1"
    assert stub.status == "open"
    assert pending_should_have(session, path, profile_id="mihir") == []
    assert stub_from_feedback(session, path, "fb1", today=TODAY) is None
    assert len(load_lessons(path)) == 1


def test_non_top_should_have_makes_no_stub(session, tmp_path):
    path = tmp_path / "l.json"
    seed_cut(session, is_top=False)
    assert pending_should_have(session, path, profile_id="mihir") == []
    session.add(Feedback(id="fb2", cluster_id="c1", action="skip", at=NOW))
    session.flush()
    assert stub_from_feedback(session, path, "fb2", today=TODAY) is None
    assert stub_from_feedback(session, path, "missing", today=TODAY) is None
    assert not path.exists()


def test_cli_from_feedback(tmp_path, monkeypatch, capsys):
    import newshouse.db as db
    from newshouse.cli import main
    from newshouse.config import get_settings
    path = tmp_path / "lessons.json"
    monkeypatch.setenv("LESSONS_PATH", str(path))
    get_settings.cache_clear()
    engine = db.get_engine(f"sqlite:///{tmp_path / 'cli.db'}")
    db.init_db(engine)
    monkeypatch.setattr(db, "_engine", engine)
    try:
        with db.session_scope(engine) as s:
            seed_cut(s)
        assert main(["lesson", "add", "--from-feedback", "fb1"]) == 0
        new_id = capsys.readouterr().out.strip()
        assert [l.id for l in load_lessons(path)] == [new_id]
        assert main(["lesson", "add", "--from-feedback", "fb1"]) != 0  # already has a lesson
        assert len(load_lessons(path)) == 1
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_repo_ledger_is_valid():
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "ledger" / "lessons.json"
    assert path.read_text().endswith("\n")
    load_lessons(path)
