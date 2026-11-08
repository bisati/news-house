from newshouse.edition_config import EditionConfig
from newshouse.select import ScoredCluster, primary_topic, select_edition_v2

def sc(id, imp, score, topics, st="plain", fmt="A", thread=None):
    return ScoredCluster(id, imp, score, topics, st, fmt, thread_id=thread)

CFG = EditionConfig(top_n=2, cards_floor=1, cards_cap=25, budget_seconds=900,
                    topics={"ai-models": {"min": 1, "max": 2}, "gurgaon-local": {"min": 1, "max": 3},
                            "movies": {"min": 1, "max": 2}})

def test_primary_topic_of_untopiced_cluster():
    assert primary_topic([]) == "other" and primary_topic(None) == "other"
    assert primary_topic(["football", "india-news"]) == "football"

def test_floor_pulls_in_a_lower_scored_topic():
    sel = select_edition_v2([sc("a", 80, 90, ["ai-models"]), sc("b", 70, 80, ["ai-models"]),
                             sc("g", 35, 40, ["gurgaon-local"])], cfg=CFG)
    assert "g" in sel.selected

def test_cap_counts_primary_topic_only_and_explains_top_cuts():
    scored = [sc(f"a{i}", 90 - i, 90 - i, ["ai-models", "ai-built"]) for i in range(4)]
    sel = select_edition_v2(scored, cfg=CFG)
    assert sel.selected == ["a0", "a1"]
    assert sel.top_ids == ["a0", "a1"] and sel.cuts == {}
    sel = select_edition_v2(scored, cfg=EditionConfig(top_n=3, cards_floor=1,
                                                      topics={"ai-models": {"min": 0, "max": 2}}))
    assert sel.cuts == {"a2": "topic cap ai-models (2)"}

def test_budget_cut_is_explained():
    cfg = EditionConfig(top_n=2, cards_floor=1, budget_seconds=35)
    sel = select_edition_v2([sc("a", 90, 90, ["movies"]), sc("b", 85, 85, ["cricket"])], cfg=cfg)
    assert sel.selected == ["a"] and sel.cuts == {"b": "budget"}

def test_one_home_per_thread():
    sel = select_edition_v2([sc("a", 90, 90, ["india-news"], thread="t1"),
                             sc("b", 88, 80, ["india-news"], thread="t1")],
                            cfg=EditionConfig(top_n=2, cards_floor=1))
    assert sel.selected == ["a"] and sel.cuts["b"] == "duplicate thread home"

def test_unmet_floor_is_recorded_not_forced():
    sel = select_edition_v2([sc("a", 90, 90, ["ai-models"])], cfg=CFG)
    assert sel.unmet_floors == {"gurgaon-local": 1, "movies": 1}

def test_cut_top_ids_always_in_also():
    scored = [sc(f"x{i}", 60, 60 - i * 0.1, ["cricket"]) for i in range(40)]
    scored.append(sc("top", 99, 1, ["cricket"]))  # high importance, low score, cut by topic cap
    sel = select_edition_v2(scored, cfg=EditionConfig(top_n=1, cards_floor=1, also_per_topic=99,
                                                      topics={"cricket": {"min": 0, "max": 2}}))
    assert "top" in sel.also and len(sel.also) == 26

def test_floor_beats_budget():
    cfg = EditionConfig(top_n=2, cards_floor=1, budget_seconds=70,
                        topics={"ai-models": {"min": 0, "max": 2}, "gurgaon-local": {"min": 1, "max": 3}})
    sel = select_edition_v2([sc("a", 90, 90, ["ai-models"]), sc("b", 70, 80, ["ai-models"]),
                             sc("g", 35, 40, ["gurgaon-local"])], cfg=cfg)
    assert sel.selected == ["a", "g"] and sel.cuts["b"] == "budget"

def test_also_one_topic_flood_is_capped():
    cfg = EditionConfig(top_n=6, cards_floor=1, cards_cap=3,  # only g0-g2 print
                        topics={"gurgaon-local": {"min": 0, "max": 3}})
    scored = [sc(f"g{i}", 90 - i, 90 - i, ["gurgaon-local"]) for i in range(30)]
    others = ["movies", "cricket", "football", "tennis-f1", "geopolitics"]
    scored += [sc(f"o{i}", 40, 50 - i, [t]) for i, t in enumerate(others)]
    sel = select_edition_v2(scored, cfg=cfg)
    cut_tops = [cid for cid in sel.top_ids if cid in sel.cuts]
    assert len(cut_tops) == 3 and all(sel.cuts[c].startswith("topic cap") for c in cut_tops)
    assert len([c for c in sel.also if c.startswith("g")]) <= 2
    assert all(c in sel.also or c in sel.folded for c in cut_tops)
    assert sel.folded and not set(sel.folded) & set(sel.also)
    assert {f"o{i}" for i in range(5)} <= set(sel.also)

def test_also_skips_printed_threads():
    cfg_kw = dict(cards_floor=1, topics={"movies": {"min": 0, "max": 1}})
    scored = [sc("a", 90, 90, ["movies"], thread="t1"),   # printed
              sc("b", 85, 80, ["movies"], thread="t1"),   # same thread as a printed card
              sc("c", 50, 70, ["movies"], thread="t2"),   # cut by the cap, listed
              sc("d", 80, 60, ["movies"], thread="t2")]   # same thread as an earlier line
    sel = select_edition_v2(scored, cfg=EditionConfig(top_n=1, **cfg_kw))
    assert sel.selected == ["a"] and sel.also == ["c"] and sel.folded == []
    sel = select_edition_v2(scored, cfg=EditionConfig(top_n=3, **cfg_kw))  # a, b, d are top
    assert sel.also == ["c"] and sel.folded == ["b", "d"]
    assert sel.cuts["b"] == sel.cuts["d"] == "duplicate thread home"

def test_also_stops_at_max_unfolded_lines():
    scored = [sc(f"x{i}", 60, 60 - i, [f"t{i}"]) for i in range(10)]
    sel = select_edition_v2(scored, cfg=EditionConfig(top_n=1, cards_floor=1, cards_cap=1,
                                                      also_max=4))
    assert sel.also == ["x1", "x2", "x3", "x4"] and sel.folded == []


def _tune(session, at, payload):
    from newshouse.feedback import record_feedback
    record_feedback(session, profile_id="mihir", action="tune", at=at, payload=payload)


def test_tune_applies_to_next_edition_only(session):
    from datetime import timedelta
    import pytest
    from newshouse.config import Settings
    from newshouse.feedback import tune_adjustments
    from newshouse.models import Cluster, Edition
    from newshouse.select import final_score, score_and_select
    from tests.test_select import NOW, _mk
    _mk(session, "cr", topics=("cricket",))
    a = Edition(id="A", date=NOW.date() - timedelta(days=2), budget_seconds=900,
                built_at=NOW - timedelta(days=1))
    session.add(a)
    _tune(session, a.built_at - timedelta(hours=1), {"topic": "football", "dir": 1})
    _tune(session, a.built_at + timedelta(hours=1), {"topic": "cricket", "dir": 1})
    _tune(session, a.built_at + timedelta(hours=2), {"topic": "cricket", "dir": 1})
    _tune(session, a.built_at + timedelta(hours=3), {"budget": 1})
    b = Edition(id="B", date=NOW.date() - timedelta(days=1), budget_seconds=900)
    session.add(b)
    session.flush()
    assert tune_adjustments(session, profile_id="mihir", since=None) == (
        {"football": pytest.approx(0.3), "cricket": pytest.approx(0.3)}, 120)
    sel = score_and_select(session, now=NOW, settings=Settings(), cfg=EditionConfig(), edition=b)
    assert sel.tune == {"topics": {"cricket": 0.3}, "budget": 120} and sel.budget_seconds == 1020
    assert session.get(Cluster, "cr").final_score == pytest.approx(final_score(
        importance=60, age_hours=1, n_sources=1, best_tier="primary", topic_w=0.3, source_w=0,
        chapter=None, is_delta=False))
    b.built_at = a.built_at + timedelta(hours=4)
    c = Edition(id="C", date=NOW.date(), budget_seconds=900)
    session.add(c)
    session.flush()
    sel = score_and_select(session, now=NOW, settings=Settings(), cfg=EditionConfig(), edition=c)
    assert sel.tune == {"topics": {}, "budget": 0}


def test_tune_topic_weight_is_clamped(session, monkeypatch):
    from datetime import timedelta
    import newshouse.select as sel_mod
    from newshouse.config import Settings
    from newshouse.feedback import Weights
    from newshouse.models import Cluster
    from newshouse.select import final_score, score_and_select
    from tests.test_select import NOW, _mk
    _mk(session, "cr", topics=("cricket",))
    monkeypatch.setattr(sel_mod, "compute_weights", lambda s, **k: Weights(topic={"cricket": 0.9}))
    _tune(session, NOW - timedelta(hours=1), {"topic": "cricket", "dir": 1})
    score_and_select(session, now=NOW, settings=Settings(), cfg=EditionConfig())
    assert session.get(Cluster, "cr").final_score == final_score(
        importance=60, age_hours=1, n_sources=1, best_tier="primary", topic_w=1.0, source_w=0,
        chapter=None, is_delta=False)


def test_tune_budget_moves_selection(session, monkeypatch):
    from datetime import timedelta
    import newshouse.select as sel_mod
    from newshouse.config import Settings
    from tests.test_select import NOW
    _tune(session, NOW - timedelta(hours=1), {"budget": -1})
    seen = {}
    real = sel_mod.select_edition_v2

    def spy(scored, *, cfg, **kw):
        seen["budget"] = cfg.budget_seconds
        return real(scored, cfg=cfg, **kw)
    monkeypatch.setattr(sel_mod, "select_edition_v2", spy)
    cfg = EditionConfig()
    sel = sel_mod.score_and_select(session, now=NOW, settings=Settings(), cfg=cfg)
    assert seen["budget"] == 780 and cfg.budget_seconds == 900
    assert sel.tune == {"topics": {}, "budget": -120} and sel.budget_seconds == 780


def test_tune_counts_one_step_per_chip(session):
    """A reload, second tab or second device can tap a chip again: the last tap wins."""
    from datetime import timedelta
    import pytest
    from newshouse.feedback import tune_adjustments
    from tests.test_select import NOW

    def adj(*payloads):
        from newshouse.models import Feedback
        session.query(Feedback).delete()
        for n, p in enumerate(payloads):
            _tune(session, NOW + timedelta(minutes=n), p)
        return tune_adjustments(session, profile_id="mihir", since=None)
    more, less = {"topic": "cricket", "dir": 1}, {"topic": "cricket", "dir": -1}
    assert adj(more, more) == ({"cricket": pytest.approx(0.3)}, 0)
    assert adj(less, more) == ({"cricket": pytest.approx(0.3)}, 0)
    assert adj(more, less) == ({"cricket": pytest.approx(-0.3)}, 0)
    assert adj({"budget": -1}, {"budget": -1}) == ({}, -120)
    assert adj({"budget": -1}, {"budget": 1}) == ({}, 120)


def test_tune_stats_round_topics(session):
    from datetime import timedelta
    from newshouse.config import Settings
    from newshouse.select import score_and_select
    from tests.test_select import NOW
    _tune(session, NOW - timedelta(hours=1), {"topic": "cricket", "dir": 1})
    sel = score_and_select(session, now=NOW, settings=Settings(), cfg=EditionConfig())
    assert sel.tune == {"topics": {"cricket": 0.3}, "budget": 0} and sel.budget_seconds == 900


def test_folded_row_claims_its_thread():
    """A folded top row still owns its thread: a later cluster on it gets no line."""
    scored = [sc("a", 90, 90, ["movies"], thread="t1"),   # printed
              sc("b", 85, 80, ["movies"], thread="t2"),   # top, cut, listed
              sc("c", 84, 70, ["movies"], thread="t3"),   # top, over the per-topic cap: folded
              sc("d", 40, 60, ["cricket"], thread="t3")]  # same thread as the folded row
    sel = select_edition_v2(scored, cfg=EditionConfig(
        top_n=3, cards_floor=1, cards_cap=1, also_per_topic=1,
        topics={"movies": {"min": 0, "max": 1}}))
    assert sel.selected == ["a"] and sel.folded == ["c"]
    assert sel.also == ["b"]


def test_less_tune_lowers_a_cluster_with_a_heavier_second_topic(session, monkeypatch):
    from datetime import timedelta
    import pytest
    import newshouse.select as sel_mod
    from newshouse.config import Settings
    from newshouse.feedback import Weights
    from newshouse.models import Cluster
    from newshouse.select import final_score, score_and_select
    from tests.test_select import NOW, _mk
    _mk(session, "fc", topics=("football", "cricket"))
    monkeypatch.setattr(sel_mod, "compute_weights", lambda s, **k: Weights(topic={"cricket": 0.2}))
    _tune(session, NOW - timedelta(hours=1), {"topic": "football", "dir": -1})
    score_and_select(session, now=NOW, settings=Settings(), cfg=EditionConfig())
    assert session.get(Cluster, "fc").final_score == pytest.approx(final_score(
        importance=60, age_hours=1, n_sources=1, best_tier="primary", topic_w=-0.1, source_w=0,
        chapter=None, is_delta=False))


def _real_cfg(**kw):
    from pathlib import Path
    from newshouse.edition_config import load_edition_config
    cfg = load_edition_config(Path("config/edition.yaml"))
    return cfg.model_copy(update=kw) if kw else cfg

def test_quiet_day_stays_short():
    topics = ["ai-models", "startups", "ai-tools", "product-design", "football", "india-news"]
    scored = [sc(f"q{i}", 60, 60 - i, [topics[i % 6]]) for i in range(12)]
    sel = select_edition_v2(scored, cfg=_real_cfg())
    assert len(sel.selected) == 12

def test_cap_36_fills_on_a_busy_day():
    topics = ["ai-models", "ai-built", "startups", "ai-tools", "product-design", "football",
              "india-news", "india-tech-biz", "intl-biz-tech", "edtech-competitors"]
    scored = [sc(f"b{i}", 80, 80 - i * 0.1, [topics[i % 10]]) for i in range(60)]
    # shipped config: budget 1200 s / 35 s per A card limits the edition to 34 cards
    sel = select_edition_v2(scored, cfg=_real_cfg())
    assert len(sel.selected) == 1200 // 35
    # a larger budget proves the cap of 36 is what stops it
    sel = select_edition_v2(scored, cfg=_real_cfg(budget_seconds=2000))
    assert len(sel.selected) == 36


def test_stack_counts_as_one_post():
    cfg = EditionConfig(top_n=1, cards_floor=1, budget_seconds=90,
                        topics={"ai-models": {"min": 0, "max": 2}})
    scored = [sc("a", 90, 90, ["ai-models"]), sc("b", 80, 80, ["ai-models"]),
              sc("c", 70, 70, ["ai-models"]), sc("d", 60, 60, ["ai-models"])]
    assert select_edition_v2(scored, cfg=cfg).selected == ["a", "b"]
    sel = select_edition_v2(scored, cfg=cfg, stacks={"a": ["b", "c"]})
    assert sel.selected == ["a", "d"]  # one cap slot for the stack; 35 + 2 * 10 + 35 = 90
    assert sel.stacks == {"a": ["b", "c"]}
    tight = cfg.model_copy(update={"budget_seconds": 89})
    sel = select_edition_v2(scored, cfg=tight, stacks={"a": ["b", "c"]})
    assert sel.selected == ["a"]


def test_stack_members_get_no_also_line():
    cfg = EditionConfig(top_n=1, cards_floor=1, cards_cap=1, also_per_topic=9)
    scored = [sc("a", 90, 90, ["movies"]), sc("b", 95, 80, ["movies"]),
              sc("c", 70, 70, ["movies"]), sc("x", 50, 50, ["movies"])]
    sel = select_edition_v2(scored, cfg=cfg, stacks={"a": ["b", "c"]})
    assert sel.selected == ["a"] and sel.also == ["x"] and sel.folded == []
    assert sel.top_ids == ["a"]  # a member is never a top id; the lead stands for it
    # a lead that is not chosen has no stack; its member is a normal Also candidate again
    sel = select_edition_v2(scored, cfg=cfg, stacks={"x": ["c"]})
    assert sel.stacks == {} and "c" in sel.also and "c" not in sel.selected
    assert sel.cuts["c"] == "card cap"  # explained by its lead's cut reason


def test_breaking_cards_count_toward_caps():
    cfg = EditionConfig(top_n=1, cards_floor=1,
                        topics={"gurgaon-local": {"min": 1, "max": 2}})
    brk = [sc("brk", 95, 95, ["gurgaon-local"])]
    scored = [sc("g1", 80, 80, ["gurgaon-local"]), sc("g2", 70, 70, ["gurgaon-local"])]
    assert select_edition_v2(scored, cfg=cfg).selected == ["g1", "g2"]
    sel = select_edition_v2(scored, cfg=cfg, breaking=brk)
    assert sel.selected == ["g1"] and sel.unmet_floors == {}
    assert "brk" not in sel.selected and "brk" not in sel.also
    sel = select_edition_v2(scored, cfg=cfg, breaking=brk, stacks={"brk": ["g2"]})
    assert sel.selected == ["g1"] and sel.stacks == {"brk": ["g2"]}


def test_stack_lead_owns_its_members_threads():
    cfg = EditionConfig(top_n=1, cards_floor=1, also_per_topic=9)
    scored = [sc("a", 90, 90, ["movies"]),                       # lead, no thread of its own
              sc("b", 60, 80, ["movies"], thread="t1"),          # member, thread t1
              sc("x", 50, 70, ["cricket"], thread="t1"),         # another chapter of t1
              sc("y", 40, 60, ["cricket"], thread="t2")]
    assert select_edition_v2(scored, cfg=cfg).cuts["x"] == "duplicate thread home"  # b is home
    sel = select_edition_v2(scored, cfg=cfg, stacks={"a": ["b"]})
    assert "x" not in sel.selected and "x" not in sel.also and "x" not in sel.folded
    assert sel.cuts["x"] == "duplicate thread home" and "y" in sel.selected
    # a cut that would otherwise get an Also line: t1 belongs to the printed stack
    tight = EditionConfig(top_n=1, cards_floor=1, cards_cap=1, also_per_topic=9)
    sel = select_edition_v2(scored, cfg=tight, stacks={"a": ["b"]})
    assert sel.selected == ["a"] and sel.also == ["y"]
    # a breaking lead owns its members' threads too
    sel = select_edition_v2([s for s in scored if s.id != "a"], cfg=cfg,
                            breaking=[sc("brk", 95, 95, ["movies"])], stacks={"brk": ["b"]})
    assert "x" not in sel.selected and "x" not in sel.also


def test_breaking_cards_use_up_the_card_cap():
    cfg = EditionConfig(top_n=1, cards_floor=1, cards_cap=3, budget_seconds=900)
    scored = [sc(f"m{i}", 80 - i, 80 - i, [t]) for i, t in
              enumerate(["movies", "cricket", "football", "tennis-f1"])]
    assert len(select_edition_v2(scored, cfg=cfg).selected) == 3
    brk = [sc("b1", 95, 95, ["geopolitics"]), sc("b2", 94, 94, ["india-news"])]
    sel = select_edition_v2(scored, cfg=cfg, breaking=brk)
    assert sel.selected == ["m0"]  # 2 breaking + 1 = the cap of 3
    assert sel.cuts == {} and "m1" in sel.also


def test_breaking_card_claims_its_own_thread():
    # GRAP: today's breaking card and a regular cluster on the same thread print once
    cfg = EditionConfig(top_n=2, cards_floor=1, also_per_topic=9)
    brk = [sc("brk", 95, 95, ["gurgaon-local"], thread="T1")]
    scored = [sc("mate", 80, 80, ["gurgaon-local"], thread="T1"),
              sc("other", 70, 70, ["movies"])]
    sel = select_edition_v2(scored, cfg=cfg, breaking=brk)
    assert "mate" not in sel.selected and sel.cuts["mate"] == "duplicate thread home"
    assert sel.selected == ["other"]
    # the cut thread-mate gets no Also line of its own: the breaking card owns T1
    assert "mate" not in sel.also and "mate" in sel.folded


def test_cut_lead_members_return_to_the_also_pool():
    cfg = EditionConfig(top_n=1, cards_floor=1, cards_cap=1, also_per_topic=9)
    scored = [sc("a", 90, 90, ["movies"]), sc("x", 50, 50, ["cricket"]),
              sc("c", 70, 70, ["football"]), sc("lo", 20, 65, ["football"])]
    sel = select_edition_v2(scored, cfg=cfg, stacks={"x": ["c", "lo"]})
    assert sel.selected == ["a"] and sel.stacks == {}
    # the cut lead's member is a normal Also candidate, explained by its lead's cut reason;
    # a member under the noise floor stays out, as it would without the stack
    assert sel.also == ["c", "x"] and "lo" not in sel.also
    assert sel.cuts["c"] == "card cap"


def test_stacks_come_best_lead_first():
    # the writer caps stacks by order (MAX_STACKS), so the best-scored leads come first
    cfg = EditionConfig(top_n=1, cards_floor=1, also_per_topic=9)
    scored = [sc("lo", 60, 60, ["movies"]), sc("hi", 90, 90, ["cricket"]),
              sc("m1", 50, 50, ["movies"]), sc("m2", 50, 49, ["cricket"])]
    brk = [sc("brk", 95, 70, ["football"]), ]
    sel = select_edition_v2([*scored, sc("m3", 50, 48, ["football"])], cfg=cfg, breaking=brk,
                            stacks={"lo": ["m1"], "brk": ["m3"], "hi": ["m2"]})
    assert list(sel.stacks) == ["hi", "brk", "lo"]
