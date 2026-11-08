import re
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from newshouse.breaking import run_breaking
from newshouse.build import get_or_create_edition
from newshouse.config import Settings
from newshouse.llm.fake import FakeBackend
from newshouse.models import Card, Cluster, ClusterItem, Item, ItemSource, Run, Source

NOW = datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def settings(tmp_path):
    p = tmp_path / "profile.md"
    p.write_text("Mihir, PM")
    return Settings(profile_path=p, database_url="sqlite://")


def mk(session, cid, *, importance=95, eligible=True, carded=False, scored_at=NOW):
    session.merge(Source(id="s1", name="Wire", topics=["ai"], tier="mainstream", kind="rss",
                         url="https://feeds/s1", paywall=False))
    session.add(Item(id=f"i-{cid}", url=f"http://x/{cid}", canonical_url=f"http://x/{cid}",
                     title=f"Story {cid}", teaser="T", published_at=NOW, first_seen_at=NOW,
                     dated=True, topics=[], raw={}))
    session.add(Cluster(id=cid, window_start=NOW, topics=["ai-models"], story_type="plain",
                        importance=importance, early=10, reason="r", scored_at=scored_at,
                        chapter=0, created_at=NOW, breaking_eligible=eligible, carded=carded))
    session.flush()
    session.add(ClusterItem(cluster_id=cid, item_id=f"i-{cid}"))
    session.add(ItemSource(item_id=f"i-{cid}", source_id="s1"))
    session.flush()


def backend(fail=()):
    def fn(system, user, schema, model):
        iid = re.search(r"i-c\d+", user).group(0)
        if iid[2:] in fail:
            raise ValueError("malformed")
        return {"format": "A", "headline": f"Head {iid}", "line": "Line.", "para": "Para.",
                "brief": "Brief.", "why": "Why.", "cited_item_ids": [iid], "payload": {}}
    return FakeBackend(fn)


def go(session, settings, be=None, now=NOW):
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    with client:
        return run_breaking(session, be or backend(), settings=settings, now=now, client=client)


def test_breaking_respects_threshold_and_daily_cap(session, settings):
    for k, imp in enumerate([99, 98, 97, 96, 95]):
        mk(session, f"c{k}", importance=imp)
    mk(session, "low", importance=89)
    cards = go(session, settings)
    assert [c.cluster_id for c in cards] == ["c0", "c1", "c2"]
    assert all(c.rank == 0 and c.breaking for c in cards)
    assert session.get(Cluster, "c0").breaking and session.get(Cluster, "c0").carded
    assert not session.get(Cluster, "c3").carded and not session.get(Cluster, "low").carded
    run = session.scalars(select(Run).where(Run.kind == "breaking")).one()
    assert run.status == "ok"
    assert run.stats == {"candidates": 5, "written": 3, "fallback": 0, "cap_reached": True,
                         "same_story": 0}


def test_breaking_cap_counts_cards_already_today(session, settings):
    for k in range(3):
        mk(session, f"c{k}")
    go(session, settings, now=NOW)
    mk(session, "c9", scored_at=NOW + timedelta(hours=1))
    assert go(session, settings, now=NOW + timedelta(hours=2)) == []
    assert not session.get(Cluster, "c9").carded


def test_breaking_ignores_already_carded_and_ineligible(session, settings):
    mk(session, "c0", carded=True)
    mk(session, "c1", eligible=False)
    assert go(session, settings) == []
    assert session.scalars(select(Card)).all() == []


def test_breaking_only_considers_clusters_scored_since_last_run(session, settings):
    mk(session, "old", scored_at=NOW - timedelta(hours=5))
    session.add(Run(id="r0", kind="breaking", started_at=NOW - timedelta(hours=2),
                    finished_at=NOW - timedelta(hours=2), status="ok", stats={}))
    mk(session, "new", scored_at=NOW - timedelta(hours=1))
    cards = go(session, settings)
    assert [c.cluster_id for c in cards] == ["new"]


def test_breaking_failed_write_stores_unverified_fallback(session, settings):
    mk(session, "c0")
    cards = go(session, settings, backend(fail={"c0"}))
    assert len(cards) == 1 and cards[0].unverified and cards[0].breaking and cards[0].rank == 0
    run = session.scalars(select(Run).where(Run.kind == "breaking")).one()
    assert run.stats["fallback"] == 1
    assert session.get(Cluster, "c0").carded


def test_breaking_attaches_to_today_edition_in_local_tz(session, settings):
    mk(session, "c0")
    late = datetime(2026, 10, 30, 20, 0, tzinfo=timezone.utc)  # already 31st in IST
    (card,) = go(session, settings, now=late)
    ed = get_or_create_edition(session, profile_id="mihir", date=date(2026, 10, 31), budget_seconds=1)
    assert card.edition_id == ed.id and ed.built_at is None


def test_breaking_finished_at_is_wall_clock(session, settings):
    from freezegun import freeze_time
    mk(session, "c0")
    later = NOW + timedelta(minutes=3)
    with freeze_time(later):
        go(session, settings)
    run = session.scalars(select(Run).where(Run.kind == "breaking")).one()
    assert run.started_at == NOW and run.finished_at == later


def test_breaking_skips_same_story(session, settings):
    from newshouse.llm.schemas import STACK_GROUPS_SCHEMA
    mk(session, "c0", importance=99)
    mk(session, "c1", importance=98)
    write = backend()._responses
    seen = []

    def fn(system, user, schema, model):
        if schema is STACK_GROUPS_SCHEMA:
            seen.append(user)
            ids = [line.split(" ")[0] for line in user.splitlines() if line.strip()]
            return {"groups": [{"ids": ids, "reason": "same"}]}
        return write(system, user, schema, model)
    cards = go(session, settings, FakeBackend(fn))
    assert [c.cluster_id for c in cards] == ["c0"]
    assert not session.get(Cluster, "c1").carded
    assert len(seen) == 1 and "Story c0" in seen[0] and "Story c1" in seen[0]
    run = session.scalars(select(Run).where(Run.kind == "breaking")).one()
    assert run.stats["same_story"] == 1


def _cfg_settings(settings, tmp_path, *, cap=36):
    p = tmp_path / "edition.yaml"
    p.write_text(f"budget_seconds: 1200\ncards: {{floor: 1, cap: {cap}}}\n")
    return settings.model_copy(update={"edition_config_path": p})


def test_breaking_edition_takes_the_edition_config_budget(session, settings, tmp_path):
    mk(session, "c0")
    (card,) = go(session, _cfg_settings(settings, tmp_path))
    from newshouse.models import Edition
    assert session.get(Edition, card.edition_id).budget_seconds == 1200


def test_breaking_respects_the_edition_card_cap(session, settings, tmp_path):
    s = _cfg_settings(settings, tmp_path, cap=2)
    ed = get_or_create_edition(session, profile_id="mihir", date=date(2026, 10, 30),
                               budget_seconds=1200)
    for n in range(2):
        session.add(Card(id=f"r{n}", edition_id=ed.id, rank=n + 1, cluster_id=f"x{n}", format="A",
                         payload={}, headline="H", line="l", para="p", brief="b", why="w",
                         est_seconds=35, cited_item_ids=[]))
    session.flush()
    mk(session, "c0")
    assert go(session, s) == []
    assert not session.get(Cluster, "c0").carded
    run = session.scalars(select(Run).where(Run.kind == "breaking")).one()
    assert run.stats["cap_reached"] is True and run.stats["written"] == 0


def test_breaking_cap_reached_only_when_a_candidate_was_stopped(session, settings):
    from newshouse.llm.schemas import STACK_GROUPS_SCHEMA
    for k, imp in enumerate([99, 98, 97]):
        mk(session, f"c{k}", importance=imp)
    write = backend()._responses

    def fn(system, user, schema, model):
        if schema is STACK_GROUPS_SCHEMA:  # only c1 is the same story as c0
            ids = [line.split(" ")[0] for line in user.splitlines() if line.strip()]
            return {"groups": [{"ids": ids, "reason": "same"}]} if "Story c1" in user else {"groups": []}
        return write(system, user, schema, model)
    s = settings.model_copy(update={"breaking_daily_cap": 2})
    cards = go(session, s, FakeBackend(fn))
    assert [c.cluster_id for c in cards] == ["c0", "c2"]  # the cap filled, nothing left over
    run = session.scalars(select(Run).where(Run.kind == "breaking")).one()
    assert run.stats["cap_reached"] is False and run.stats["same_story"] == 1
