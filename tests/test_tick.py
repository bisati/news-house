import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect, select, text

import newshouse.tick as tk
from newshouse.config import Settings
from newshouse.ingest import RunStats
from newshouse.models import Edition, Item, Run, Source

IST_10AM = datetime(2026, 10, 31, 4, 45, tzinfo=timezone.utc)   # 10:15 IST
IST_5AM = datetime(2026, 10, 30, 23, 30, tzinfo=timezone.utc)   # 05:00 IST 31st


class Stub:
    def __init__(self):
        self.calls = []


@pytest.fixture
def env(session, tmp_path, monkeypatch):
    profile = tmp_path / "profile.md"
    profile.write_text("Mihir")
    src = tmp_path / "sources.yaml"
    src.write_text("- {name: A, url: 'https://a/feed', topic: ai, tier: mainstream, kind: rss}\n")
    settings = Settings(profile_path=profile, database_url="sqlite://", sources_path=src,
                        neon_database_url=None, publish_remote=None)  # never the real ~/.config env
    calls: list[str] = []

    def rec(name, ret):
        def fn(*a, **k):
            calls.append(name)
            return ret
        return fn

    monkeypatch.setattr(tk, "ingest", rec("ingest", RunStats()))
    monkeypatch.setattr(tk, "embed_new_items", rec("embed", 0))
    monkeypatch.setattr(tk, "cluster_fresh_items", rec("cluster", []))
    monkeypatch.setattr(tk, "classify_clusters", rec("classify", 0))
    monkeypatch.setattr(tk, "match_threads", rec("threads", 0))
    monkeypatch.setattr(tk, "close_quiet_threads", rec("close", 0))

    def fake_build(session, backend, *, settings, now, **k):
        calls.append("build")
        ed = Edition(id="ed1", profile_id="mihir", date=now.astimezone(__import__("zoneinfo").ZoneInfo(settings.tz)).date(),
                     built_at=now, budget_seconds=1)
        session.add(ed)
        session.flush()
        return ed

    def fake_render(session, ed, out_dir):
        calls.append("render")
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / f"{ed.date}.html"
        p.write_text("<html>x</html>")
        return p

    monkeypatch.setattr(tk, "build_edition", fake_build)
    monkeypatch.setattr(tk, "render_edition", fake_render)
    monkeypatch.setattr(tk, "run_breaking", lambda *a, **k: (calls.append("breaking") or []))
    monkeypatch.setattr(tk, "fetch_market", lambda client: None)  # no network in tests

    def go(now, out=tmp_path / "out"):
        return tk.tick(session, None, settings=settings, now=now, client=None, embedder=None,
                       out_dir=out)
    return go, calls, settings, tmp_path


def test_tick_builds_when_no_edition_and_after_6am(session, env):
    go, calls, _, tmp = env
    r = go(IST_10AM)
    assert "build" in calls and "render" in calls and "breaking" not in calls
    assert r["built"] == "ed1" and r["rendered"].endswith("2026-10-31.html")
    assert (tmp / "out" / "latest.html").read_text() == "<html>x</html>"
    assert calls.index("threads") < calls.index("build") < calls.index("close")


def test_tick_runs_breaking_when_edition_built(session, env):
    go, calls, _, _ = env
    go(IST_10AM)
    calls.clear()
    r = go(datetime(2026, 10, 31, 6, 45, tzinfo=timezone.utc))
    assert "breaking" in calls and "build" not in calls and r["built"] is None


def test_tick_does_not_build_before_6am(session, env):
    go, calls, _, _ = env
    go(IST_5AM)
    assert "breaking" in calls and "build" not in calls and "render" not in calls


def test_tick_syncs_sources_only_when_yaml_changed(session, env):
    go, calls, settings, _ = env
    assert go(IST_5AM)["sync"] == 1
    assert session.scalars(select(Source)).all()
    assert go(IST_5AM)["sync"] is None
    st = os.stat(settings.sources_path).st_mtime
    os.utime(settings.sources_path, (st + 10, st + 10))
    assert go(IST_5AM)["sync"] == 1
    assert len(session.scalars(select(Run).where(Run.kind == "sync")).all()) == 2


def test_tick_prunes_once_per_day(session, env):
    go, _, _, _ = env
    old = Item(id="old", url="http://o", canonical_url="http://o", title="t", teaser="",
               published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
               first_seen_at=datetime(2026, 1, 1, tzinfo=timezone.utc), dated=True, topics=[],
               raw={}, body="b")
    session.add(old)
    session.flush()
    assert go(IST_5AM)["pruned"] == 1 and old.body is None
    assert go(IST_5AM)["pruned"] is None
    assert go(datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc))["pruned"] == 0


SUN = datetime(2026, 11, 1, 4, 45, tzinfo=timezone.utc)   # Sunday 10:15 IST
MON = datetime(2026, 11, 1, 23, 30, tzinfo=timezone.utc)   # Monday 05:00 IST (before build hour)


def test_tick_runs_health_on_sunday_once(session, env, monkeypatch):
    go, calls, _, _ = env
    seen = []

    def fake_health(sess, *, client, now):
        seen.append(now)
        sess.add(Run(id=f"h{len(seen)}", kind="health", started_at=now, finished_at=now,
                     status="ok", stats={}))
        sess.commit()
        return {"checked": 0}

    monkeypatch.setattr(tk, "check_sources", fake_health)
    assert go(SUN)["health"] == {"checked": 0}
    assert go(SUN + timedelta(hours=1))["health"] is None
    assert go(MON)["health"] is None
    assert len(seen) == 1


def test_tick_records_per_stage_usage_in_tick_run(session, env, monkeypatch):
    from newshouse.llm.fake import FakeBackend
    go, _, settings, tmp = env
    fb = FakeBackend(lambda *a: {})

    def classify(sess, backend, **k):
        backend.complete_json(system="s", user="u", schema={}, model="haiku", effort="low")
        backend.complete_json(system="s", user="u", schema={}, model="haiku", effort="low")
        return 2
    monkeypatch.setattr(tk, "classify_clusters", classify)
    tk.tick(session, fb, settings=settings, now=IST_5AM, client=None, embedder=None,
            out_dir=tmp / "out")
    r = session.scalars(select(Run).where(Run.kind == "tick")).one()
    assert r.status == "ok" and r.stats["classify"] == 2
    assert list(r.stats["usage"]) == ["classify"]
    assert r.stats["usage"]["classify"]["haiku"]["calls"] == 2


def test_tick_commits_each_stage_so_a_later_failure_keeps_earlier_rows(session, env, monkeypatch):
    go, calls, _, _ = env

    def embed(sess, embedder):
        sess.add(Item(id="kept", url="http://k", canonical_url="http://k", title="t", teaser="",
                      published_at=IST_5AM, first_seen_at=IST_5AM, dated=True, topics=[], raw={}))
        sess.flush()
        return 1

    def boom(*a, **k):
        raise RuntimeError("classify exploded")
    monkeypatch.setattr(tk, "embed_new_items", embed)
    monkeypatch.setattr(tk, "classify_clusters", boom)
    with pytest.raises(RuntimeError, match="classify exploded"):
        go(IST_5AM)
    session.rollback()  # anything uncommitted is gone; committed stages remain
    assert session.get(Item, "kept") is not None
    r = session.scalars(select(Run).where(Run.kind == "tick")).one()
    assert r.status == "error" and "classify exploded" in r.error and r.finished_at is not None
    assert "build" not in calls and "breaking" not in calls


def test_tick_runs_finish_on_wall_clock(session, env):
    from freezegun import freeze_time
    go, _, _, _ = env
    later = IST_5AM + timedelta(minutes=40)
    with freeze_time(later):
        go(IST_5AM)
    for kind in ("tick", "sync", "prune"):
        r = session.scalars(select(Run).where(Run.kind == kind)).one()
        assert r.started_at == IST_5AM and r.finished_at == later, kind


def test_tick_adds_missing_columns_first(session, env):
    go, _, _, _ = env
    engine = session.get_bind()
    with engine.begin() as c:
        c.execute(text("ALTER TABLE cards DROP COLUMN visual"))
    assert "visual" not in {c["name"] for c in inspect(engine).get_columns("cards")}
    go(IST_5AM)
    assert "visual" in {c["name"] for c in inspect(engine).get_columns("cards")}


def test_tick_survives_sync_failure(session, env, monkeypatch, tmp_path):
    go, calls, settings, _ = env
    settings.neon_database_url = f"sqlite:///{tmp_path / 'inbox.db'}"

    def boom(*a, **k):
        raise RuntimeError("secret-host.neon.tech down")

    monkeypatch.setattr(tk, "sync_feedback", boom)
    r = go(IST_10AM)
    assert r["feedback_sync"] == {"error": "RuntimeError"}
    assert "build" in calls and r["built"] == "ed1"


def test_tick_skips_sync_without_neon_url(session, env, monkeypatch):
    go, calls, settings, _ = env
    monkeypatch.setattr(tk, "sync_feedback", lambda *a, **k: pytest.fail("called"))
    settings.neon_database_url = None
    assert go(IST_10AM)["feedback_sync"] is None


def test_tick_survives_publish_failure(session, env, monkeypatch):
    go, calls, settings, _ = env
    settings.publish_remote = "origin"

    def boom(*a, **k):
        raise RuntimeError("https://token@github.com push failed")

    monkeypatch.setattr(tk, "publish", boom)
    r = go(IST_10AM)
    assert r["publish"] == {"status": "error", "error": "RuntimeError"}
    assert "build" in calls and r["built"] == "ed1"


def test_tick_publishes_after_render(session, env, monkeypatch):
    go, calls, settings, tmp = env
    settings.publish_remote = "origin"
    seen = {}

    def fake(out_dir, **k):
        seen.update(k, out_dir=out_dir)
        assert (out_dir / "latest.html").exists()
        return {"status": "pushed", "commit": "abc", "files": 3}

    monkeypatch.setattr(tk, "publish", fake)
    r = go(IST_10AM)
    assert r["publish"] == {"status": "pushed", "commit": "abc", "files": 3}
    assert seen["remote"] == "origin" and seen["branch"] == settings.publish_branch
    assert seen["worktree"] == settings.publish_worktree and seen["now"] == IST_10AM


def test_tick_skips_publish_without_remote(session, env, monkeypatch):
    go, calls, settings, _ = env
    monkeypatch.setattr(tk, "publish", lambda *a, **k: pytest.fail("called"))
    assert go(IST_10AM)["publish"] is None  # remote unset
    assert go(IST_10AM + timedelta(minutes=15))["publish"] is None  # no build either


def test_tick_publishes_without_a_build(session, env, monkeypatch):
    """publish() skips unchanged content and retries a failed push, so every tick calls it."""
    go, calls, settings, _ = env
    settings.publish_remote = "origin"
    seen = []
    monkeypatch.setattr(tk, "publish", lambda out_dir, **k: seen.append(k["now"]) or
                        {"status": "unchanged", "commit": "abc", "files": 3})
    go(IST_10AM)
    later = IST_10AM + timedelta(minutes=15)
    r = go(later)
    assert r["built"] is None and "breaking" in calls
    assert r["publish"] == {"status": "unchanged", "commit": "abc", "files": 3}
    assert seen == [IST_10AM, later]


def test_tick_without_a_build_survives_publish_failure(session, env, monkeypatch):
    go, calls, settings, _ = env
    go(IST_10AM)
    settings.publish_remote = "origin"

    def boom(*a, **k):
        raise RuntimeError("https://token@github.com push failed")

    monkeypatch.setattr(tk, "publish", boom)
    r = go(IST_10AM + timedelta(minutes=15))
    assert r["publish"] == {"status": "error", "error": "RuntimeError"}
    assert r["built"] is None and r["health"] is None and r["threads_closed"] == 0
    run = session.scalars(select(Run).where(Run.kind == "tick")
                          .order_by(Run.started_at.desc())).first()
    assert run.status == "ok"


def test_tick_records_sync_and_publish_in_run_stats(session, env, monkeypatch, tmp_path):
    go, calls, settings, _ = env
    settings.neon_database_url = f"sqlite:///{tmp_path / 'inbox.db'}"
    settings.publish_remote = "origin"
    counts = {"fetched": 2, "recorded": 2, "duplicate": 0, "invalid": 0}
    monkeypatch.setattr(tk, "sync_feedback", lambda *a, **k: counts)
    monkeypatch.setattr(tk, "publish", lambda *a, **k: {"status": "pushed", "commit": "abc",
                                                        "files": 3})
    go(IST_10AM)
    run = session.scalars(select(Run).where(Run.kind == "tick")).one()
    assert run.stats["feedback_sync"] == counts
    assert run.stats["publish"] == {"status": "pushed", "commit": "abc", "files": 3}


def test_tick_passes_publish_identity_and_worktree(session, env, monkeypatch):
    go, calls, settings, _ = env
    settings.publish_remote = "origin"
    settings.publish_author_name, settings.publish_author_email = "N", "n@example.invalid"
    seen = {}
    monkeypatch.setattr(tk, "publish", lambda out_dir, **k: seen.update(k) or {"status": "x"})
    go(IST_10AM)
    assert seen["author_name"] == "N" and seen["author_email"] == "n@example.invalid"
    assert seen["worktree"] is None  # unset: publish picks the per-repo default


SNAP_A = {"as_of": "2026-10-31T10:00:00+05:30", "indices": [{"name": "Nifty 50", "level": 1.0}]}
SNAP_B = {"as_of": "2026-10-31T12:00:00+05:30", "indices": [{"name": "Nifty 50", "level": 2.0}]}
NOON = datetime(2026, 10, 31, 6, 45, tzinfo=timezone.utc)  # 12:15 IST


def _built_with(session, go, snap):
    go(IST_10AM)
    ed = session.get(Edition, "ed1")
    ed.live = {"aqi": {"x": 1}, "market": snap} if snap else {"aqi": {"x": 1}}
    session.commit()
    return ed


def test_tick_refreshes_market_on_a_later_tick(session, env, monkeypatch):
    go, calls, _, tmp = env
    ed = _built_with(session, go, SNAP_A)
    calls.clear()
    monkeypatch.setattr(tk, "fetch_market", lambda client: SNAP_B)
    r = go(NOON)
    assert r["market"] == "updated" and "render" in calls and "build" not in calls
    session.refresh(ed)
    assert ed.live == {"aqi": {"x": 1}, "market": SNAP_B}
    assert (tmp / "out" / "latest.html").read_text() == "<html>x</html>"


def test_tick_adds_market_when_the_build_had_none(session, env, monkeypatch):
    go, calls, _, _ = env
    ed = _built_with(session, go, None)
    monkeypatch.setattr(tk, "fetch_market", lambda client: SNAP_A)
    assert go(NOON)["market"] == "updated"
    session.refresh(ed)
    assert ed.live["market"] == SNAP_A


def test_tick_leaves_market_alone_when_unchanged_or_failed(session, env, monkeypatch):
    go, calls, _, _ = env
    ed = _built_with(session, go, SNAP_A)
    for snap, want in ((dict(SNAP_A), "unchanged"), (None, "failed")):
        calls.clear()
        monkeypatch.setattr(tk, "fetch_market", lambda client, snap=snap: snap)
        assert go(NOON)["market"] == want and "render" not in calls
        session.refresh(ed)
        assert ed.live["market"] == SNAP_A


def test_tick_survives_market_render_failure(session, env, monkeypatch):
    go, calls, _, _ = env
    _built_with(session, go, SNAP_A)
    monkeypatch.setattr(tk, "fetch_market", lambda client: SNAP_B)

    def boom(*a, **k):
        raise RuntimeError("render broke")
    monkeypatch.setattr(tk, "render_edition", boom)
    r = go(NOON)
    assert r["market"] == "error" and "close" in calls


def test_tick_does_not_refresh_market_before_the_build(session, env, monkeypatch):
    go, calls, _, _ = env
    monkeypatch.setattr(tk, "fetch_market", lambda client: pytest.fail("called"))
    assert go(IST_5AM)["market"] is None
