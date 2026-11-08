import re
from datetime import date, datetime, timedelta, timezone

import httpx
import numpy as np
import pytest
from freezegun import freeze_time
from sqlalchemy import func, select

from newshouse.build import _read_chapters, apply_validation, build_edition, get_or_create_edition, prune_old
from newshouse.config import Settings
from newshouse.db import vec_to_bytes
from newshouse.edition_config import EditionConfig, TopicRule
from newshouse.llm.backend import LLMError
from newshouse.llm.fake import FakeBackend
from newshouse.models import (AlsoHappened, Card, Cluster, ClusterItem, Edition, Item,
                              ItemSource, Run, Source, Thread)
from newshouse.render_static import render_edition
from newshouse.validate import load_banned
from tests.helpers import seed_edition


NOW = datetime(2026, 10, 30, 6, 0, tzinfo=timezone.utc)


@pytest.fixture
def settings(tmp_path):
    p = tmp_path / "profile.md"
    p.write_text("Mihir, PM")
    return Settings(profile_path=p, database_url="sqlite://")


def mk_clusters(session, n=12, *, start=0):
    session.merge(Source(id="s1", name="Wire", topics=["ai"], tier="mainstream", kind="rss",
                         url="https://feeds/s1", paywall=False))
    for k in range(start, start + n):
        cid = f"c{k}"
        session.add(Item(id=f"i-{cid}", url=f"http://x/{cid}", canonical_url=f"http://x/{cid}",
                         title=f"Story {cid}", teaser=f"Teaser {cid}", published_at=NOW,
                         first_seen_at=NOW, dated=True, topics=[], raw={},
                         embedding=vec_to_bytes(np.ones(4, dtype=np.float32))))
        session.add(Cluster(id=cid, window_start=NOW, topics=[["ai-models", "markets", "india"][k % 3]],
                            story_type="plain", importance=95 - 3 * k, early=10,
                            reason=f"reason {cid}", scored_at=NOW, chapter=0, created_at=NOW))
        session.flush()
        session.add(ClusterItem(cluster_id=cid, item_id=f"i-{cid}"))
        session.add(ItemSource(item_id=f"i-{cid}", source_id="s1"))
    session.flush()


def writer(fail=()):
    def fn(system, user, schema, model):
        iid = re.search(r"i-c\d+", user).group(0)
        if iid[2:] in fail:
            raise ValueError("malformed")
        return {"format": "A", "headline": f"Head {iid}", "line": "Line.", "para": "Para.",
                "brief": "Brief.", "why": "Why Mihir.", "cited_item_ids": [iid], "payload": {}}
    return FakeBackend(fn)


def run(session, backend, settings, **kw):
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    with freeze_time(NOW), client:
        return build_edition(session, backend, settings=settings, now=NOW, client=client,
                             embedder=None, **kw)


def test_build_creates_edition_with_ranked_cards(session, settings):
    mk_clusters(session, 40)
    ed = run(session, writer(), settings)
    cards = session.scalars(select(Card).where(Card.edition_id == ed.id).order_by(Card.rank)).all()
    also = session.scalars(select(AlsoHappened).where(AlsoHappened.edition_id == ed.id)
                           .order_by(AlsoHappened.rank)).all()
    assert ed.built_at == NOW and ed.date == date(2026, 10, 30) and ed.profile_version == 1
    assert cards and [c.rank for c in cards] == list(range(1, len(cards) + 1))
    assert also and len(cards) + len(also) <= 40
    assert [a.rank for a in also] == list(range(1, len(also) + 1))
    assert also[0].line.startswith("Story c")
    assert ed.cut_score is not None
    assert all(session.get(Cluster, c.cluster_id).carded for c in cards)


def test_build_also_line_is_title_and_reason_goes_to_stats(session, settings):
    mk_clusters(session, 40)
    for it in session.scalars(select(Item)):
        it.title = f"{it.title} broke today - Hindustan Times"
    session.get(Source, "s1").kind = "gnews"  # only Google News titles carry an outlet suffix
    session.flush()
    ed = run(session, writer(), settings)
    also = session.scalars(select(AlsoHappened).where(AlsoHappened.edition_id == ed.id)
                           .order_by(AlsoHappened.rank)).all()
    assert also
    for a in also:
        assert a.line == f"Story {a.cluster_id} broke today"
    reasons = session.scalars(select(Run)).one().stats["also_reasons"]
    assert reasons == {a.cluster_id: f"reason {a.cluster_id}" for a in also}


def test_build_is_idempotent_per_date(session, settings):
    mk_clusters(session)
    ed = run(session, writer(), settings)
    n = session.scalar(select(func.count()).select_from(Card))
    again = run(session, writer(), settings)
    assert again.id == ed.id and session.scalar(select(func.count()).select_from(Card)) == n
    assert session.scalar(select(func.count()).select_from(Run)) == 1


def test_build_force_rebuilds_but_keeps_breaking_cards(session, settings):
    mk_clusters(session, 13)
    ed = get_or_create_edition(session, profile_id="mihir", date=date(2026, 10, 30),
                               budget_seconds=900)
    session.add(Card(id="brk", edition_id=ed.id, rank=0, cluster_id="c12", format="A", payload={},
                     headline="Breaking", line="l", para="p", brief="b", why="w", est_seconds=35,
                     cited_item_ids=["i-c12"], breaking=True))
    session.get(Cluster, "c12").carded = True
    session.flush()
    first = run(session, writer(), settings)
    ids1 = {c.id for c in session.scalars(select(Card).where(Card.edition_id == ed.id,
                                                              Card.breaking == False))}  # noqa: E712
    run(session, writer(), settings, force=True)
    cards = session.scalars(select(Card).where(Card.edition_id == ed.id)).all()
    assert first.id == ed.id
    brk = [c for c in cards if c.breaking]
    assert [(c.id, c.rank) for c in brk] == [("brk", 0)]
    normal = [c for c in cards if not c.breaking]
    assert normal and {c.id for c in normal} == ids1  # Ruling 10: ids are stable per cluster
    assert sorted(c.rank for c in normal) == list(range(1, len(normal) + 1))
    assert session.scalar(select(func.count()).select_from(Edition)) == 1


def test_build_records_run_stats(session, settings):
    mk_clusters(session)
    run(session, writer(), settings)
    r = session.scalars(select(Run)).one()
    assert r.kind == "build" and r.status == "ok" and r.finished_at is not None
    for k in ("cards", "also", "clusters_scored", "selected", "cards_fallback", "profile_version"):
        assert k in r.stats
    assert r.stats["cards"] == r.stats["selected"] and r.stats["cards_fallback"] == 0
    assert "classify" in r.stats["seconds"]
    u = r.stats["usage"]
    assert list(u) == ["select", "write"] and u["write"]["opus"]["calls"] == r.stats["cards"]
    assert u["select"] == {"haiku": {**u["select"]["haiku"], "calls": 1}}  # the stack grouping
    assert set(u["write"]["opus"]) == {"calls", "input", "cache_read", "cache_create", "output",
                                       "cost", "turns", "api_ms"}


def test_build_isolates_write_failures(session, settings):
    mk_clusters(session)
    ed = run(session, writer(fail={"c0"}), settings)
    cards = session.scalars(select(Card).where(Card.edition_id == ed.id)).all()
    bad = [c for c in cards if c.cluster_id == "c0"]
    assert len(bad) == 1 and bad[0].unverified and bad[0].format == "A"
    assert bad[0].headline == "Story c0" and bad[0].est_seconds == 35
    assert all(not c.unverified for c in cards if c.cluster_id != "c0")
    assert session.get(Cluster, "c0").carded
    assert session.scalars(select(Run)).one().stats["cards_fallback"] == 1


def test_build_error_marks_run_and_reraises(session, settings):
    settings.profile_path = settings.profile_path.parent / "missing.md"
    with pytest.raises(FileNotFoundError):
        run(session, writer(), settings)
    r = session.scalars(select(Run)).one()
    assert r.status == "error" and "missing.md" in r.error


def test_prune_old_clears_bodies_after_90_days(session):
    mk_clusters(session, 2)
    old = session.get(Item, "i-c0")
    old.first_seen_at = NOW - timedelta(days=91)
    old.body = "text"
    session.get(Item, "i-c1").body = "keep"
    session.flush()
    assert prune_old(session, now=NOW) == 1
    assert old.body is None and old.embedding is None
    assert session.get(Item, "i-c1").body == "keep" and session.get(Item, "i-c1").embedding


def test_build_stamps_wall_clock_not_injected_now(session, settings):
    mk_clusters(session)
    later = NOW + timedelta(minutes=42)  # the stages "took" 42 minutes
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    with freeze_time(later), client:
        ed = build_edition(session, writer(), settings=settings, now=NOW, client=client,
                           embedder=None)
    r = session.scalars(select(Run)).one()
    assert r.started_at == NOW and r.finished_at == later and r.finished_at >= r.started_at
    assert ed.built_at == later and ed.built_at != NOW
    assert ed.date == date(2026, 10, 30)  # dating still follows the injected now


def test_build_error_finished_at_is_wall_clock(session, settings):
    settings.profile_path = settings.profile_path.parent / "missing.md"
    later = NOW + timedelta(minutes=5)
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    with freeze_time(later), client, pytest.raises(FileNotFoundError):
        build_edition(session, writer(), settings=settings, now=NOW, client=client, embedder=None)
    r = session.scalars(select(Run)).one()
    assert r.status == "error" and r.finished_at == later


def test_build_stores_top_ids_and_cut_reasons(session, settings):
    mk_clusters(session, 2)
    for c in session.scalars(select(Cluster)):
        c.topics = ["ai-models"]
    # c0: most important but 30h old (90 * 0.8 = 72); c1: fresher (80 * 1.0 = 80) wins the cap
    session.get(Cluster, "c0").importance = 90
    session.get(Cluster, "c1").importance = 80
    session.get(Item, "i-c0").published_at = NOW - timedelta(hours=30)
    session.flush()
    cfg = EditionConfig(top_n=1, cards_floor=1, topics={"ai-models": {"min": 0, "max": 1}})
    ed = run(session, writer(), settings, cfg=cfg)
    row = session.scalars(select(AlsoHappened).where(AlsoHappened.edition_id == ed.id)).one()
    assert ed.top_ids == ["c0"] and ed.budget_seconds == cfg.budget_seconds
    assert row.cluster_id == "c0" and row.is_top is True
    assert row.cut_reason.startswith("topic cap")
    stats = session.scalars(select(Run)).one().stats
    assert stats["cuts"] == {"c0": row.cut_reason} and stats["unmet_floors"] == {}


def scripted(dirty):
    """Replies per cluster: dirty[cid] is how many leading replies say "pivotal"."""
    seen: dict[str, int] = {}

    def fn(system, user, schema, model):
        iid = re.search(r"i-c\d+", user).group(0)
        n = seen[iid] = seen.get(iid, 0) + 1
        para = "A pivotal week." if n <= dirty.get(iid[2:], 0) else "A plain week."
        return {"format": "A", "headline": f"Head {iid}", "line": "Line.", "para": para,
                "brief": "Brief.", "why": "Why Mihir.", "cited_item_ids": [iid], "payload": {}}
    return FakeBackend(fn)


def _wide_cfg():  # 22 A cards print (c22+ fall under the noise floor): 13 minutes, no topic cap, no floor in the way
    return EditionConfig(cards_floor=8, cards_cap=25, topic_default=TopicRule(max=10))


def test_validator_retries_then_warns(session, settings):
    mk_clusters(session, 22)
    backend = scripted({"c0": 1})
    ed = run(session, backend, settings, cfg=_wide_cfg())
    cards = session.scalars(select(Card).where(Card.edition_id == ed.id)).all()
    assert len(cards) == 22
    c0 = next(c for c in cards if c.cluster_id == "c0")
    assert "pivotal" not in c0.para and c0.unverified is False
    assert [w for w in ed.warnings if w["rule"] != "visual-share"] == []
    assert len(backend.calls) == 24  # 22 cards, 1 retry, 1 stack grouping
    assert session.scalars(select(Run)).one().stats["validator"] == {
        "problems": 2, "retried": 1, "warnings": 1, "fallbacks": 0}  # + visual-share (plain fakes)

    backend = scripted({"c1": 99})
    ed = run(session, backend, settings, cfg=_wide_cfg(), force=True)
    c1 = session.scalars(select(Card).where(Card.edition_id == ed.id,
                                            Card.cluster_id == "c1")).one()
    assert "pivotal" in c1.para
    assert [w for w in ed.warnings if w["rule"] != "visual-share"] == [{"rule": "banned-word", "text": "para uses banned words: pivotal",
                            "card_id": c1.id}]
    assert len(backend.calls) == 24  # 22 cards, 1 retry, 1 stack grouping


def test_count_warning_is_not_retried(session, settings):
    mk_clusters(session, 3)
    backend = writer()
    ed = run(session, backend, settings, cfg=EditionConfig(cards_floor=8))
    assert len(backend.calls) == 4  # 3 cards and the stack grouping
    assert {w["rule"] for w in ed.warnings} - {"visual-share"} == {"count"}
    assert [w["text"] for w in ed.warnings if "floor" in w["text"]] == [
        "3 cards, below the floor of 8"]
    assert all(w["card_id"] is None for w in ed.warnings)


BAD_B = {"columns": ["Model"], "rows": []}


def _validate(session, ed, backend):
    stats: dict = {}
    out = apply_validation(session, backend, ed, cfg=EditionConfig(cards_floor=0),
                           profile_text="mihir", banned=load_banned(), stats=stats)
    return out, stats["validator"]


def _reply(**kw):
    out = {"format": "A", "headline": "Short head", "line": "Line.", "para": "Para.",
           "brief": "Brief.", "why": "Why mihir.", "cited_item_ids": ["i0"], "payload": {}}
    out.update(kw)
    return out


def _snapshot(card):
    return (card.format, card.payload, card.headline, card.line, card.para, card.brief, card.why,
            card.est_seconds, list(card.cited_item_ids), card.unverified)


def test_fallback_to_no_visual_warns(session, tmp_path):
    ed = seed_edition(session, [(1, "B", "Short head", BAD_B, {"why": "Why mihir", "visual": "table"}),
                                (2, "A", "Fine head", {}, {"why": "Why mihir", "est_seconds": 35})])
    backend = FakeBackend([_reply(format="B", payload=BAD_B)])  # the retry is still broken
    _, stats = _validate(session, ed, backend)
    card = session.get(Card, "card0")
    assert len(backend.calls) == 1
    assert (card.format, card.payload, card.visual, card.est_seconds) == ("A", {}, "none", 35)
    fb = [w for w in ed.warnings if w["rule"] == "payload-fallback"]
    assert fb == [{"rule": "payload-fallback", "card_id": "card0",
                   "text": "Short head: payload.rows must be a non-empty list"}]
    assert [w["rule"] for w in ed.warnings if w["rule"] not in ("payload-fallback", "visual-share")] == ["count"]
    # 60 + 35 seconds before the fallback (2 minutes), 35 + 35 after (1 minute)
    assert "1 minutes" in next(w["text"] for w in ed.warnings if w["rule"] == "count")
    assert stats["fallbacks"] == 1 and stats["warnings"] == len(ed.warnings)
    render_edition(session, ed, tmp_path, validate=True, cfg=EditionConfig(cards_floor=0),
                   profile_text="mihir", banned=load_banned())
    assert [w for w in ed.warnings if w["rule"] == "payload-fallback"] == fb


def _pivotal_edition(session):
    ed = seed_edition(session, [(1, "A", "Short head", {}, {"why": "Why mihir", "para": "A pivotal week."})])
    return ed, _snapshot(session.get(Card, "card0"))


def test_retry_unverified_keeps_card(session):
    ed, before = _pivotal_edition(session)
    backend = FakeBackend([_reply(cited_item_ids=["nope"])])  # write_card falls back
    _, stats = _validate(session, ed, backend)
    assert len(backend.calls) == 1 and stats["retried"] == 1
    assert _snapshot(session.get(Card, "card0")) == before
    assert [w["rule"] for w in ed.warnings if w["card_id"]] == ["banned-word"]


def test_retry_raises_keeps_card(session):
    ed, before = _pivotal_edition(session)

    def boom(system, user, schema, model):
        raise ValueError("malformed")
    _, stats = _validate(session, ed, FakeBackend(boom))
    assert stats["retried"] == 1
    assert _snapshot(session.get(Card, "card0")) == before
    assert [w["rule"] for w in ed.warnings if w["card_id"]] == ["banned-word"]


def test_retry_worse_keeps_card(session):
    ed, before = _pivotal_edition(session)
    equal = FakeBackend([_reply(para="Another pivotal week.")])
    _validate(session, ed, equal)
    assert _snapshot(session.get(Card, "card0")) == before
    worse = FakeBackend([_reply(para="A crucial week.", line="A pivotal line.")])
    _validate(session, ed, worse)
    assert len(worse.calls) == 1
    assert _snapshot(session.get(Card, "card0")) == before


def test_read_chapters_uses_seen_events(session):
    from newshouse.feedback import record_feedback
    session.add(Thread(id="t1", title="T", summary="S", opened_at=NOW, last_chapter_at=NOW, chapters=2))
    session.add(Edition(id="old", date=date(2026, 10, 29), built_at=NOW, budget_seconds=900))
    cur = Edition(id="cur", date=date(2026, 10, 30), budget_seconds=900)
    session.add(cur)
    session.add(Cluster(id="c-old", window_start=NOW, topics=[], thread_id="t1", chapter=1))
    cl = Cluster(id="c-new", window_start=NOW, topics=[], thread_id="t1", chapter=2)
    session.add(cl)
    session.flush()
    session.add(Card(id="card-old", edition_id="old", rank=1, cluster_id="c-old", format="A",
                     payload={}, headline="h", line="", para="", brief="", why="", est_seconds=35,
                     cited_item_ids=[], thread_id="t1", chapter=1))
    session.flush()
    assert _read_chapters(session, cl, cur) == frozenset()
    record_feedback(session, profile_id="mihir", action="seen", card_id="card-old", at=NOW)
    assert _read_chapters(session, cl, cur) == frozenset({1})


# --- phase 2: stable ids, catalogue validation, write fallbacks --------------

ONE_SLIDE = [{"kind": "cover", "title": "", "body": "", "payload": {}}]


def _replies(**per_cluster):
    """Like writer(), with per-cluster overrides: per_cluster["c0"] = {...reply keys...}."""
    def fn(system, user, schema, model):
        iid = re.search(r"i-c\d+", user).group(0)
        out = {"format": "A", "headline": f"Head {iid}", "line": "Line.", "para": "Para.",
               "brief": "Brief.", "why": "Why Mihir.", "cited_item_ids": [iid], "payload": {}}
        out.update(per_cluster.get(iid[2:], {}))
        return out
    return FakeBackend(fn)


def test_card_id_for_is_stable():
    from newshouse.build import card_id_for
    import hashlib
    assert card_id_for("e1", "c0") == hashlib.sha1(b"e1:c0").hexdigest()[:32]
    assert card_id_for("e1", "c0") == card_id_for("e1", "c0") != card_id_for("e1", "c1")


def test_force_rebuild_keeps_card_ids(session, settings):
    from newshouse.build import card_id_for
    from newshouse.feedback import record_feedback
    from newshouse.models import Feedback
    mk_clusters(session)
    ed = run(session, writer(), settings)
    ids1 = {c.id for c in session.scalars(select(Card).where(Card.edition_id == ed.id))}
    first = session.scalars(select(Card).where(Card.edition_id == ed.id, Card.rank == 1)).one()
    assert first.id == card_id_for(ed.id, first.cluster_id)
    record_feedback(session, profile_id="mihir", action="worth", card_id=first.id, at=NOW)
    session.commit()
    ed = run(session, writer(), settings, force=True)
    ids2 = {c.id for c in session.scalars(select(Card).where(Card.edition_id == ed.id))}
    assert ids2 == ids1
    assert session.scalars(select(Feedback)).one().card_id in ids2


def test_write_fallback_notes_become_warnings(session, settings):
    from newshouse.build import card_id_for
    mk_clusters(session)
    backend = _replies(c0={"slides": ONE_SLIDE})
    ed = run(session, backend, settings)
    cid = card_id_for(ed.id, "c0")
    card = session.get(Card, cid)
    assert card.slides == [] and card.visual == "none" and not card.unverified
    fb = [w for w in ed.warnings if w["rule"] == "payload-fallback"]
    assert len(fb) == 1 and fb[0]["card_id"] == cid
    assert fb[0]["text"].startswith("Head i-c0: ") and "two to four" in fb[0]["text"]
    assert session.scalars(select(Run)).one().stats["write_fallbacks"] == {cid: fb[0]["text"]}


def test_headline_long_does_not_retry(session, settings):
    from newshouse.build import card_id_for
    mk_clusters(session, 22)
    long_head = "Head " + " ".join(["word"] * 12)  # 13 words, well under 90 characters
    backend = _replies(c0={"headline": long_head})
    ed = run(session, backend, settings, cfg=_wide_cfg())
    c0_calls = [c for c in backend.calls if re.search(r"i-c0\b", c["user"])]
    assert len(c0_calls) == 1
    assert [w["rule"] for w in ed.warnings if w["rule"] != "visual-share"] == ["headline-long"]
    assert [w for w in ed.warnings if w["rule"] == "headline-long"][0]["card_id"] == card_id_for(ed.id, "c0")
    assert session.scalars(select(Run)).one().stats["validator"]["retried"] == 0


def test_tone_changes_logged(session, settings):
    from newshouse.build import card_id_for
    mk_clusters(session)
    session.get(Cluster, "c0").tone = "bad"
    session.get(Cluster, "c1").tone = "good"
    session.flush()
    ed = run(session, _replies(c0={"tone": "good"}, c1={"tone": "good"}, c2={"tone": "mixed"}),
             settings)
    stats = session.scalars(select(Run)).one().stats
    assert stats["tone_changes"] == {card_id_for(ed.id, "c0"): ["bad", "good"]}


def test_validator_fallback_clears_slides(session):
    table = {"columns": ["Model"], "rows": [{"cells": ["x"], "yours": False, "new": True}]}
    ed = seed_edition(session, [(1, "B", "Short head", table,
                                 {"why": "Why mihir", "visual": "table", "slides": ONE_SLIDE})])
    backend = FakeBackend([_reply(cited_item_ids=["nope"])])  # the retry falls back: kept as is
    _, stats = _validate(session, ed, backend)
    card = session.get(Card, "card0")
    assert len(backend.calls) == 1
    assert (card.visual, card.payload, card.slides, card.format, card.est_seconds) == (
        "none", {}, [], "A", 35)
    fb = [w for w in ed.warnings if w["rule"] == "payload-fallback"]
    assert len(fb) == 1 and fb[0]["card_id"] == "card0" and "two to four" in fb[0]["text"]
    assert not [w for w in ed.warnings if w["rule"] == "slides"]
    assert stats["fallbacks"] == 1


def test_breaking_card_holding_the_stable_id_keeps_writer_uuid(session, settings):
    from newshouse.build import card_id_for
    mk_clusters(session, 13)
    ed = get_or_create_edition(session, profile_id="mihir", date=date(2026, 10, 30),
                               budget_seconds=900)
    taken = card_id_for(ed.id, "c0")
    session.add(Card(id=taken, edition_id=ed.id, rank=0, cluster_id="c12", format="A", payload={},
                     headline="Breaking", line="l", para="p", brief="b", why="w", est_seconds=35,
                     cited_item_ids=["i-c12"], breaking=True))
    session.get(Cluster, "c12").carded = True
    session.flush()
    run(session, writer(), settings)
    c0 = session.scalars(select(Card).where(Card.cluster_id == "c0")).one()
    assert c0.id != taken and len(c0.id) == 32
    assert session.get(Card, taken).breaking


GOOD_DECK = [{"kind": "cover", "title": "", "body": "", "payload": {"big": "Big week"}},
             {"kind": "text", "title": "The week", "body": "It happened.", "payload": {}}]


def test_text_retry_that_loses_a_working_deck_is_not_kept(session):
    """Final review, Important 4: fixing one banned word must not cost a valid deck."""
    ed = seed_edition(session, [(1, "A", "Short head", {},
                                 {"why": "Why mihir", "para": "A pivotal week.", "slides": GOOD_DECK})])
    backend = FakeBackend([_reply(slides=ONE_SLIDE)])  # text fixed, deck now broken -> cover
    _validate(session, ed, backend)
    card = session.get(Card, "card0")
    assert len(backend.calls) == 1
    assert card.slides == GOOD_DECK and "pivotal" in card.para
    assert [w["rule"] for w in ed.warnings if w["card_id"]] == ["banned-word"]


def test_folded_rows_stored(session, settings):
    mk_clusters(session, 10)
    for c in session.scalars(select(Cluster)):
        c.topics = ["ai-models"]
    session.flush()
    cfg = EditionConfig(top_n=6, cards_floor=1, also_per_topic=1,
                        topics={"ai-models": {"min": 0, "max": 1}})
    ed = run(session, writer(), settings, cfg=cfg)
    rows = session.scalars(select(AlsoHappened).where(AlsoHappened.edition_id == ed.id)
                           .order_by(AlsoHappened.rank)).all()
    assert [(r.cluster_id, r.folded) for r in rows] == [
        ("c1", False), ("c2", True), ("c3", True), ("c4", True), ("c5", True)]
    assert [r.rank for r in rows] == [1, 2, 3, 4, 5]
    for r in rows:
        assert r.is_top is True and r.cut_reason == "topic cap ai-models (1)"
    assert all(w["rule"] != "top-unexplained" for w in ed.warnings or [])


def test_build_stores_live(session, settings):
    from tests.test_live import ok_both
    mk_clusters(session, 12)
    client = httpx.Client(transport=httpx.MockTransport(ok_both))
    cfg = EditionConfig(live={"aqi": {"provider": "open-meteo", "lat": 28.4595, "lon": 77.0266},
                              "fixtures": {"provider": "espn", "team": "barcelona", "team_id": 83}})
    with freeze_time(NOW), client:
        ed = build_edition(session, writer(), settings=settings, now=NOW, client=client,
                           embedder=None, cfg=cfg)
    assert ed.live["aqi"] == {"aqi": 75, "band": "Satisfactory", "dot": "good", "at": "2026-11-03T14:00"}
    assert ed.live["match"]["text"] == "Barça v Aston Villa"
    run_row = session.scalars(select(Run).order_by(Run.started_at.desc())).first()
    assert "live" in run_row.stats["seconds"] and run_row.status == "ok"


def test_build_survives_live_failure(session, settings):
    mk_clusters(session, 12)
    cfg = EditionConfig(live={"aqi": {"provider": "open-meteo", "lat": 1, "lon": 2},
                              "fixtures": {"provider": "espn", "team": "barcelona", "team_id": 83}})
    ed = run(session, writer(), settings, cfg=cfg)  # the run client answers 404 to everything
    assert ed.built_at is not None and ed.live == {}


def test_build_stores_empty_live_when_fetch_live_raises(session, settings, caplog):
    import logging
    mk_clusters(session, 12)
    cfg = EditionConfig(live={"aqi": 5, "fixtures": {"team_id": 83}})  # `"lat" in 5` raises
    with caplog.at_level(logging.WARNING, logger="newshouse.build"):
        ed = run(session, writer(), settings, cfg=cfg)
    assert ed.built_at is not None and ed.live == {}
    assert any("live" in r.getMessage() for r in caplog.records if r.name == "newshouse.build")


def test_build_makes_lesson_stubs(session, settings, lessons_path):
    from pathlib import Path
    from newshouse.lessons import load_lessons
    from newshouse.models import Feedback
    repo_ledger = Path(__file__).resolve().parents[1] / "ledger" / "lessons.json"
    before = repo_ledger.read_bytes()
    path = lessons_path  # the autouse fixture's tmp ledger, reached through LESSONS_PATH
    assert settings.lessons_path == path
    session.add(Edition(id="old", date=date(2026, 10, 29), built_at=NOW - timedelta(days=1),
                        budget_seconds=900))
    session.add(Cluster(id="cut1", window_start=NOW, topics=["cricket"], final_score=55.0,
                        scored_at=NOW - timedelta(days=1)))
    session.flush()
    session.add(AlsoHappened(edition_id="old", cluster_id="cut1", rank=1, line="IPL auction",
                             cut_reason="budget", is_top=True))
    session.add(Feedback(id="fbx", cluster_id="cut1", action="should_have", at=NOW))
    session.flush()
    mk_clusters(session, 12)
    run_obj = run(session, writer(), settings)
    lessons = load_lessons(path)
    assert [l.feedback_id for l in lessons] == ["fbx"]
    assert lessons[0].miss == "Should have been in: IPL auction" and lessons[0].run_id is None
    build_run = session.scalars(select(Run).where(Run.kind == "build")).first()
    assert build_run.stats["lesson_stubs"] == 1
    assert run_obj is not None
    assert repo_ledger.read_bytes() == before


def test_forced_rebuild_owed_window_uses_build_clock(session, settings, lessons_path):
    from newshouse.lessons import Lesson, save_lessons
    save_lessons(lessons_path, [Lesson(id="L1", date="2026-10-29", miss="Missed IPL",
                                       owed={"topic": "cricket"})])
    mk_clusters(session, 12)
    run(session, writer(), settings)  # built_at = NOW
    later = NOW + timedelta(hours=30)
    # scored by this rebuild's clock, after the first build; no items, so never printed
    session.add(Cluster(id="ipl", window_start=later, topics=["cricket"], importance=60,
                        story_type="plain", scored_at=later, created_at=later, chapter=0))
    session.flush()
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    with freeze_time(NOW + timedelta(hours=31)), client:  # built_at is wall clock, after now
        ed = build_edition(session, writer(), settings=settings, now=later, client=client,
                           embedder=None, force=True, date=NOW.date())
    owed = [w for w in ed.warnings if w["rule"] == "owed"]
    assert len(owed) == 1 and "L1" in owed[0]["text"] and "ipl" in owed[0]["text"]


def test_forced_rebuild_stubs_todays_cut_top_before_reset(session, settings, lessons_path):
    """A should_have tap on today's cut top line is stubbed even when the rebuild drops it."""
    from newshouse.lessons import load_lessons
    from newshouse.models import Feedback
    mk_clusters(session, 12)
    ed = run(session, writer(), settings)
    # a top line cut today, for a cluster the rebuild will not see again (no items)
    session.add(Cluster(id="gone", window_start=NOW, topics=["cricket"], final_score=50.0,
                        scored_at=NOW - timedelta(days=3)))
    session.flush()
    session.add(AlsoHappened(edition_id=ed.id, cluster_id="gone", rank=99, line="IPL auction",
                             cut_reason="budget", is_top=True))
    session.add(Feedback(id="fbt", cluster_id="gone", action="should_have", at=NOW))
    session.flush()
    run(session, writer(), settings, force=True)
    lessons = load_lessons(lessons_path)
    assert [l.feedback_id for l in lessons] == ["fbt"]
    assert lessons[0].miss == "Should have been in: IPL auction"
    assert lessons[0].cut_reason == "budget"
    runs = session.scalars(select(Run).where(Run.kind == "build").order_by(Run.started_at)).all()
    assert runs[-1].stats["lesson_stubs"] == 1 and "lessons" in runs[-1].stats["seconds"]


def stacked(groups, rows=None):
    """The build's writer plus a grouping call (``groups``) and a stack-lines call."""
    from newshouse.llm.schemas import STACK_GROUPS_SCHEMA, STACK_LINES_SCHEMA
    write = writer()._responses

    def fn(system, user, schema, model):
        if schema is STACK_GROUPS_SCHEMA:
            return {"groups": groups}
        if schema is STACK_LINES_SCHEMA:
            if rows is None:
                raise LLMError("down")
            return {"rows": rows}
        return write(system, user, schema, model)
    return FakeBackend(fn)


def test_stack_joins_breaking_lead(session, settings):
    mk_clusters(session, 13)
    ed = get_or_create_edition(session, profile_id="mihir", date=date(2026, 10, 30),
                               budget_seconds=900)
    session.add(Card(id="brk", edition_id=ed.id, rank=0, cluster_id="c12", format="A", payload={},
                     headline="Breaking", line="l", para="p", brief="b", why="w", est_seconds=35,
                     cited_item_ids=["i-c12"], breaking=True))
    session.get(Cluster, "c12").carded = True
    session.flush()
    # c3 scores higher than the breaking c12, but the breaking card keeps the lead
    be = stacked([{"ids": ["c3", "c12"], "reason": "follow-up"}],
                 rows=[{"cluster_id": "c3", "headline": "Follow-up", "line": "It moved on."}])
    run(session, be, settings)
    brk = session.get(Card, "brk")
    assert brk.rank == 0 and brk.breaking
    assert brk.stack == [{"cluster_id": "c3", "headline": "Follow-up", "line": "It moved on.",
                          "url": "http://x/c3", "source": "Wire"}]
    assert brk.est_seconds == 45
    assert session.scalars(select(Card).where(Card.cluster_id == "c3")).first() is None
    assert session.scalars(select(AlsoHappened).where(AlsoHappened.cluster_id == "c3")).first() is None
    assert session.get(Cluster, "c3").carded
    stats = session.scalars(select(Run)).one().stats
    assert stats["stacks"] == {"groups": 1, "members": 1, "lines_failed": 0, "capped": 0}
    # a forced rebuild rewrites the breaking card's stack rather than doubling it
    run(session, stacked([{"ids": ["c3", "c12"], "reason": "follow-up"}]), settings, force=True)
    brk = session.get(Card, "brk")
    assert [r["headline"] for r in brk.stack] == ["Story c3"] and brk.est_seconds == 45


def test_build_stack_on_a_written_lead(session, settings):
    mk_clusters(session, 13)
    be = stacked([{"ids": ["c0", "c3", "c6"], "reason": "same"}])  # lines fail: headline-only
    run(session, be, settings)
    c0 = session.scalars(select(Card).where(Card.cluster_id == "c0")).one()
    assert [r["cluster_id"] for r in c0.stack] == ["c3", "c6"]
    stacked_secs = c0.est_seconds
    assert all(r["line"] == "" for r in c0.stack)
    assert not session.scalars(select(Card).where(Card.cluster_id.in_(["c3", "c6"]))).all()
    stats = session.scalars(select(Run)).one().stats
    assert stats["stacks"] == {"groups": 1, "members": 2, "lines_failed": 2, "capped": 0}
    run(session, stacked([]), settings, force=True)  # no stacks now: members print again
    assert session.scalars(select(Card).where(Card.cluster_id == "c3")).first() is not None
    c0 = session.scalars(select(Card).where(Card.cluster_id == "c0")).one()
    assert c0.stack == [] and c0.est_seconds == stacked_secs - 20  # 10 s per member, gone


def test_build_survives_grouping_failure(session, settings):
    mk_clusters(session, 13)
    ed = run(session, writer(), settings)  # the writer's reply is junk to the grouping call
    assert session.scalars(select(Card).where(Card.edition_id == ed.id)).all()
    stats = session.scalars(select(Run)).one().stats
    assert stats["stacks"] == {"groups": 0, "members": 0, "lines_failed": 0, "capped": 0}


def _lead_cards(session, leads):
    ed = get_or_create_edition(session, profile_id="mihir", date=date(2026, 10, 30),
                               budget_seconds=1200)
    for n, cid in enumerate(leads, start=1):
        session.add(Card(id=f"card-{cid}", edition_id=ed.id, rank=n, cluster_id=cid, format="A",
                         payload={}, headline=f"Head {cid}", line="l", para="p", brief="b",
                         why="w", est_seconds=35, cited_item_ids=[f"i-{cid}"]))
    session.flush()
    return ed


def test_write_stacks_never_fails_the_build(session):
    from newshouse.build import _write_stacks
    mk_clusters(session, 3)
    session.add(Cluster(id="empty", window_start=NOW, topics=["ai-models"], chapter=0,
                        created_at=NOW))  # a member with no items: its facts raise
    ed = _lead_cards(session, ["c0"])
    stats: dict = {}
    _write_stacks(session, stacked([]), ed, {"c0": ["c1", "empty", "c2"]}, stats=stats)
    card = session.get(Card, "card-c0")
    assert [r["cluster_id"] for r in card.stack] == ["c1", "c2"]
    assert all(r["line"] == "" for r in card.stack) and card.est_seconds == 55
    assert session.get(Cluster, "c1").carded and not session.get(Cluster, "empty").carded
    assert stats["stacks"] == {"groups": 1, "members": 2, "lines_failed": 2, "capped": 0}


def test_write_stacks_caps_writer_calls_at_max_stacks(session):
    from newshouse.build import _write_stacks
    from newshouse.llm.schemas import STACK_LINES_SCHEMA
    from newshouse.stacks import MAX_STACKS
    assert MAX_STACKS == 10
    mk_clusters(session, 24)
    leads = [f"c{k}" for k in range(12)]
    ed = _lead_cards(session, leads)
    be = stacked([], rows=[])
    _write_stacks(session, be, ed, {lead: [f"c{k + 12}"] for k, lead in enumerate(leads)},
                  stats=(stats := {}))
    assert sum(1 for c in be.calls if c["schema"] is STACK_LINES_SCHEMA) == 10
    last = session.get(Card, "card-c11")  # beyond the cap: headline-only, no call
    assert last.stack == [{"cluster_id": "c23", "headline": "Story c23", "line": "",
                           "url": "http://x/c23", "source": "Wire"}] and last.est_seconds == 45
    assert session.get(Cluster, "c23").carded
    assert stats["stacks"]["groups"] == 12 and stats["stacks"]["capped"] == 2
