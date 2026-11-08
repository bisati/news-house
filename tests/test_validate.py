from datetime import date

from newshouse.edition_config import EditionConfig, TopicRule
from newshouse.models import Card, Edition
from newshouse.validate import (Banned, card_problems, load_banned, profile_tokens,
                                validate_edition)
from tests.helpers import NOW, seed_edition

CFG = EditionConfig()
BANNED = load_banned()


def _check(session, ed, cfg=CFG, profile_text=""):
    return validate_edition(session, ed, cfg=cfg, profile_text=profile_text, banned=BANNED)


def _rules(problems):
    return [p.rule for p in problems]


def _cards(n, extra=None):
    return [(i + 1, "A", f"Story {i}", {}, dict(extra or {})) for i in range(n)]


def _card(**kw):
    base = {"id": "x", "format": "A", "payload": {}, "headline": "Short head", "line": "Line",
            "para": "Para", "brief": "Brief", "why": "", "cited_item_ids": ["i0"], "chapter": None}
    base.update(kw)
    return base


def _card_check(card, profile=frozenset()):
    return card_problems(card, profile=set(profile), banned=BANNED, previous_headline=None,
                         cluster_item_ids={"i0"})


def test_validate_empty_edition_warns(session):
    ed = seed_edition(session, [])
    problems = _check(session, ed)
    assert _rules(problems) == ["count"]


def test_count_rule_on_minutes(session):
    ed = seed_edition(session, _cards(8, {"est_seconds": 300}))
    counts = [p for p in _check(session, ed) if p.rule == "count"]
    assert len(counts) == 1 and "minutes" in counts[0].text


def test_floor_rule(session):
    cfg = EditionConfig(topics={"movies": TopicRule(min=1, max=2)})
    ed = seed_edition(session, _cards(8))
    floors = [p for p in _check(session, ed, cfg=cfg) if p.rule == "floor"]
    assert len(floors) == 1 and "movies" in floors[0].text


def test_top_unexplained(session):
    ed = seed_edition(session, _cards(1))
    ed.top_ids = ["c9"]
    session.flush()
    tops = [p for p in _check(session, ed) if p.rule == "top-unexplained"]
    assert len(tops) == 1 and "c9" in tops[0].text


def test_top_explained_by_cut_reason(session):
    ed = seed_edition(session, _cards(2),
                      also=[{"cluster_id": "c1", "rank": 1, "line": "Cut", "cut_reason": "topic cap"}])
    ed.top_ids = ["c0", "c1"]
    session.flush()
    assert "top-unexplained" not in _rules(_check(session, ed))


def test_thread_home(session):
    ed = seed_edition(session, _cards(2, {"thread_id": "t1"}))
    homes = [p for p in _check(session, ed) if p.rule == "thread-home"]
    assert len(homes) == 1 and "t1" in homes[0].text


def test_chapter_repeats(session):
    ed = seed_edition(session, [(1, "A", "Delhi announces new vehicle curbs under revised GRAP", {},
                                 {"thread_id": "t1", "chapter": 2})])
    session.add(Edition(id="e0", date=date(2026, 10, 29), built_at=NOW, budget_seconds=900))
    session.flush()
    session.add(Card(id="old", edition_id="e0", rank=1, cluster_id="c0", thread_id="t1", chapter=1,
                     format="A", payload={}, headline="Delhi announces new vehicle curbs under GRAP",
                     line="l", para="p", brief="b", why="w", est_seconds=60, cited_item_ids=["i0"]))
    session.flush()
    repeats = [p for p in _check(session, ed) if p.rule == "chapter-repeats"]
    assert len(repeats) == 1 and repeats[0].card_id == "card0"


def test_headline_long_is_soft(session):
    head = " ".join(f"word{i}" for i in range(14))
    ed = seed_edition(session, [(1, "A", head, {}, {})])
    longs = [p for p in _check(session, ed) if p.rule == "headline-long"]
    assert len(longs) == 1


def test_why_generic_vs_specific():
    profile = profile_tokens("Gemini Gurgaon")
    assert profile == {"gemini", "gurgaon"}
    generic = _card_check(_card(why="This matters to anyone in tech"), profile)
    assert _rules(generic) == ["why-generic"]
    assert _card_check(_card(why="You run Gemini flash-lite"), profile) == []


def test_banned_word_and_pattern():
    problems = _card_check(_card(para="A pivotal moment — experts say"))
    assert sorted(_rules(problems)) == ["banned-pattern", "banned-word"]
    assert isinstance(BANNED, Banned)


def test_citation_outside_cluster(session):
    ed = seed_edition(session, [(1, "A", "Head", {}, {"cited_item_ids": ["i0", "zz"]})])
    cites = [p for p in _check(session, ed) if p.rule == "citation"]
    assert len(cites) == 1 and "zz" in cites[0].text and cites[0].card_id == "card0"


def test_slide_problems_reported(session):
    deck = [{"kind": "cover", "title": "", "body": "", "payload": {}}]
    ed = seed_edition(session, [(1, "A", "Head", {}, {"slides": deck})])
    slides = [p for p in _check(session, ed) if p.rule == "slides"]
    assert len(slides) == 1 and slides[0].card_id == "card0" and "two to four" in slides[0].text


def test_legacy_card_payload_rule_unchanged(session):
    table = {"columns": ["Model"], "rows": [{"cells": ["x"], "yours": False, "new": True}]}
    ed = seed_edition(session, [(1, "B", "Head", table, {"visual": "cover"})])
    assert "payload" not in _rules(_check(session, ed))


def test_new_visual_payload_checked_against_cited_items(session):
    # a cover with a non-empty payload is valid (v1's format-A rule would flag it) ...
    ed = seed_edition(session, [(1, "A", "Head", {"big": "Title 0", "label": "", "line": ""},
                                 {"visual": "cover"}),
                                (2, "A", "Head", {"big": "77"}, {"visual": "cover"})])
    payload = [p for p in _check(session, ed) if p.rule == "payload"]
    # ... but its digits must still appear in a cited item ("Source title 1" has no 77)
    assert [p.card_id for p in payload] == ["card1"] and "77" in payload[0].text


def test_cited_items_and_previous_headline_public(session):
    from newshouse.validate import _previous_headline, cited_items, previous_headline
    ed = seed_edition(session, [(1, "A", "Head", {}, {})])
    facts = cited_items(session, {"cited_item_ids": ["i0", "zz"]})
    assert list(facts) == ["i0"] and "Source title 0" in facts["i0"].text
    assert _previous_headline is previous_headline


def test_folded_top_story_is_explained(session):
    from newshouse.models import Cluster
    session.add(Cluster(id="g1", window_start=NOW, topics=["gurgaon-local"], chapter=0))
    ed = seed_edition(session, _cards(1),
                      also=[{"cluster_id": "g1", "rank": 1, "line": "Cut", "folded": True,
                             "cut_reason": "topic cap gurgaon-local (3)", "is_top": True}])
    ed.top_ids = ["c0", "g1"]
    session.flush()
    assert "top-unexplained" not in _rules(_check(session, ed))


def _owed_setup(session, *, printed=False, explained=False, importance=60, topic="cricket"):
    from newshouse.lessons import Lesson
    from newshouse.models import Cluster
    session.add(Cluster(id="o1", window_start=NOW, topics=[topic, "india-news"], importance=importance,
                        scored_at=NOW, chapter=0))
    also = [{"cluster_id": "o1", "rank": 1, "line": "IPL", "cut_reason": "budget"}] if explained else []
    ed = seed_edition(session, _cards(1), also=also)
    if printed:
        session.get(Card, "card0").cluster_id = "o1"
    session.flush()
    lessons = [Lesson(id="L1", date="2026-10-29", miss="Missed IPL", owed={"topic": "cricket"}),
               Lesson(id="L2", date="2026-10-29", miss="Done one", owed={"topic": "cricket"},
                      status="done")]
    return ed, lessons


def _owed(session, ed, lessons):
    return [p for p in validate_edition(session, ed, cfg=CFG, profile_text="", banned=BANNED,
                                        lessons=lessons, noise_floor=30, window_hours=48)
            if p.rule == "owed"]


def test_owed_rule(session):
    ed, lessons = _owed_setup(session)
    owed = _owed(session, ed, lessons)
    assert len(owed) == 1 and "L1" in owed[0].text and "o1" in owed[0].text


def test_owed_rule_printed_or_explained_or_quiet(session):
    ed, lessons = _owed_setup(session, printed=True)
    assert _owed(session, ed, lessons) == []


def test_owed_rule_one_warning_per_lesson(session):
    from newshouse.models import Cluster
    ed, lessons = _owed_setup(session)
    for k in range(4):
        session.add(Cluster(id=f"o9{k}", window_start=NOW, topics=["cricket"], importance=50 + k,
                            scored_at=NOW, chapter=0))
    session.flush()
    owed = _owed(session, ed, lessons)
    assert len(owed) == 1
    assert "5 cluster(s)" in owed[0].text and "o1, o93, o92, ..." in owed[0].text
    assert "o91" not in owed[0].text


def test_owed_rule_uses_now_over_built_at(session):
    from datetime import timedelta
    ed, lessons = _owed_setup(session)
    ed.built_at = NOW - timedelta(hours=1)  # a stale built_at (a --force rebuild) misses o1
    session.flush()
    assert _owed(session, ed, lessons) == []
    owed = [p for p in validate_edition(session, ed, cfg=CFG, profile_text="", banned=BANNED,
                                        lessons=lessons, noise_floor=30, window_hours=48, now=NOW)
            if p.rule == "owed"]
    assert len(owed) == 1


def test_owed_rule_skips_cluster_printed_elsewhere(session):
    from newshouse.models import Cluster
    ed, lessons = _owed_setup(session)
    session.get(Cluster, "o1").carded = True
    session.flush()
    assert _owed(session, ed, lessons) == []


def test_owed_rule_explained(session):
    ed, lessons = _owed_setup(session, explained=True)
    assert _owed(session, ed, lessons) == []


def test_owed_rule_below_noise_and_secondary_topic(session):
    ed, lessons = _owed_setup(session, importance=20)
    assert _owed(session, ed, lessons) == []


def test_owed_rule_thread(session):
    from newshouse.lessons import Lesson
    from newshouse.models import Cluster, Thread
    session.add(Thread(id="t1", title="T", summary="", opened_at=NOW, last_chapter_at=NOW))
    session.add(Cluster(id="o2", window_start=NOW, topics=["football"], importance=50,
                        scored_at=NOW, thread_id="t1"))
    ed = seed_edition(session, _cards(1))
    lessons = [Lesson(id="L3", date="2026-10-29", miss="Barca", owed={"thread_id": "t1"})]
    assert ["L3" in p.text for p in _owed(session, ed, lessons)] == [True]
    lessons = [Lesson(id="L3", date="2026-10-29", miss="Barca", owed={"topic": "india-news"})]
    assert _owed(session, ed, lessons) == []  # primary topic only


def test_owed_rule_tolerates_missing_ledger(session, lessons_path):
    assert not lessons_path.exists()  # the autouse fixture's ledger, never written here
    ed = seed_edition(session, _cards(1))
    assert "owed" not in _rules(_check(session, ed))


def test_count_rule_minutes_band_fits_a_20_minute_edition(session):
    # the edition is about 20 minutes (1200 s budget, up to 36 posts): 12 to 24 is in band
    for n, secs, warned in ((10, 120, False), (11, 120, False), (10, 150, True)):  # 20, 22, 25 min
        session.rollback()
        ed = seed_edition(session, _cards(n, {"est_seconds": secs}))
        counts = [p for p in _check(session, ed) if p.rule == "count"]
        assert bool(counts) is warned, (n, secs, counts)
        if warned:
            assert "outside 12 to 24" in counts[0].text


def test_stored_automatic_cover_is_not_a_payload_problem(session):
    ed = seed_edition(session, [(1, "A", "Old plain card", {}, {"visual": "cover"})])
    probs = validate_edition(session, ed, cfg=EditionConfig(), profile_text="", banned=Banned(),
                             lessons=[], noise_floor=0, window_hours=48)
    assert not [p for p in probs if p.rule == "payload"]


def test_visual_share_and_format_mix(session):
    from newshouse.validate import _visual_problems
    kf = {"visual": "key-facts", "payload": {"facts": [{"label": "a", "value": "b"}] * 2}, "slides": []}
    plain = {"visual": "none", "payload": {}, "slides": [], "sources": []}
    rules = lambda cards: [p.rule for p in _visual_problems({"cards": cards})]
    assert rules([kf] * 2 + [plain] * 3) == ["visual-share"]  # 5 posts: no format-mix
    assert rules([kf] * 6) == ["format-mix"]
    cover = {"visual": "cover", "payload": {"big": "9"}, "slides": []}
    number = {"visual": "number", "payload": {"value": "9", "what": "x"}, "slides": []}
    deck = {"visual": "none", "payload": {}, "slides": [{"kind": "cover"}, {"kind": "text"}]}
    mixed = [cover, number, cover, kf, kf, deck, deck]
    assert rules(mixed) == ["format-mix"]  # cover and number counted together: 3 of 7
    photo = {**plain, "sources": [{"item_id": "i", "image_url": "https://x/a.jpg", "outlet": "W"}]}
    assert rules([photo] * 4 + [plain]) == []  # the photo fallback counts as a visual
    assert rules([photo] * 6) == []  # photos are not capped by format-mix
