import pytest
from newshouse.edition_config import EditionConfig
from newshouse.present import (FAMILIES, NEUTRAL, PALETTE, WORLD_VARS, _chart, colour_world, contrast,
                               cover_big, team_family, team_for, visual_for)

CFG = EditionConfig(colours_topic={"gurgaon-local": "city", "ai-models": "ai", "football": "sport"},
                    teams={"barcelona": {"primary": "#A50044", "secondary": "#004D98"}})

def card(**kw):
    base = dict(headline="H", line="L", topics=["ai-models"], tone=None, breaking=False,
                format="A", payload={}, chapter=0, slides=[])
    base.update(kw); return base

def test_lead_is_forest_by_day_and_forest_deep_by_night():
    w0 = colour_world(card(), position=0, previous=[], cfg=CFG)
    assert w0.name == "forest" and w0.light["fill"] == "#12372A" and w0.light["label"] == "#A8F0C6"
    assert w0.night["fill"] == "#1E4A3A"
    w1 = colour_world(card(topics=["ai-models"]), position=1, previous=["forest"], cfg=CFG)
    assert w1.name != "forest"

def test_urgent_card_gets_the_breaking_step_and_a_capped_one_does_not():
    assert colour_world(card(breaking=True), position=0, previous=[], cfg=CFG).name == "breaking"
    w = colour_world(card(breaking=True, urgent=False), position=2, previous=["forest"], cfg=CFG)
    assert w.name == "white"

def test_good_news_is_mint_with_its_own_night_surface():
    w = colour_world(card(tone="good"), position=3, previous=["white"], cfg=CFG)
    assert w.name == "mint" and w.light["fill"] == "#D9F5E3" and w.night["fill"] == "#143A2B"

def test_cover_and_quote_posts_take_the_topic_tint():
    w = colour_world(card(topics=["gurgaon-local"]), position=2, previous=["white"], cfg=CFG, visual="cover")
    assert w.name == "tint" and w.light["fill"] == FAMILIES["city"].tint
    assert w.night["fill"] == FAMILIES["city"].night and w.light["hi"] == FAMILIES["city"].ink
    assert colour_world(card(), position=2, previous=["white"], cfg=CFG, visual="quote").name == "tint"

def test_no_tint_for_a_deck_a_chart_or_a_neutral_topic():
    deck = card(slides=[{"kind": "cover"}, {"kind": "text"}])
    assert colour_world(deck, position=2, previous=["white"], cfg=CFG, visual="cover").name == "white"
    assert colour_world(card(), position=2, previous=["white"], cfg=CFG, visual="chart").name == "white"
    plain = card(topics=["solutions"])
    assert colour_world(plain, position=2, previous=["white"], cfg=CFG, visual="cover").name == "white"

def test_never_two_tinted_posts_in_a_row():
    for prev in ("mint", "tint"):
        w = colour_world(card(tone="good"), position=4, previous=["white", prev], cfg=CFG)
        assert w.name == "white"
        w = colour_world(card(), position=4, previous=["white", prev], cfg=CFG, visual="cover")
        assert w.name == "white"

def test_topic_family_marks_the_white_post():
    w = colour_world(card(topics=["ai-models"]), position=3, previous=["white"], cfg=CFG)
    assert w.name == "white" and w.light["fill"] == "#FFFFFF"
    assert w.light["accent"] == "#7C6CF0" and w.light["label"] == "#3B2C7A"
    assert w.night["fill"] == "#1C2620" and w.night["accent"] == "#B9AEFF"

def test_team_colours_on_barca():
    c = card(topics=["football"], headline="Koundé out vs Alavés; Barça short at the back")
    assert team_for(c, CFG) == "barcelona"
    w = colour_world(c, position=2, previous=["white"], cfg=CFG)
    assert w.light["accent"] == "#A50044" and "--secondary:#004D98" in w.style()
    other = card(topics=["football"], headline="Arsenal win at home")
    assert colour_world(other, position=2, previous=["white"], cfg=CFG).light["accent"] == "#C4672F"

def test_style_carries_day_and_night_values():
    style = colour_world(card(), position=3, previous=["white"], cfg=CFG).style()
    for k in WORLD_VARS:
        assert f"--l-{k}:" in style and f"--d-{k}:" in style

def _all_worlds():
    fams = [*FAMILIES.values(), NEUTRAL, team_family("barcelona", "#A50044", "#004D98")]
    for f in fams:
        topic = next((t for t, n in CFG.colours_topic.items() if n == f.name), "solutions")
        for kw in (dict(position=0), dict(position=2, visual="cover"), dict(position=2),
                   dict(position=2, tone="good"), dict(position=0, breaking=True)):
            c = card(topics=[topic], tone=kw.pop("tone", None), breaking=kw.pop("breaking", False))
            if f.name.startswith("team"):
                c.update(topics=["football"], headline="Barça news")
            yield f, colour_world(c, previous=["white"], cfg=CFG, **kw)

def test_config_family_names_match_the_families():
    from newshouse.edition_config import FAMILY_NAMES
    assert set(FAMILY_NAMES) == set(FAMILIES)


def test_also_numbers_pass_as_text():
    for f in FAMILIES.values():
        assert contrast(f.ink, "#FFFFFF") >= 4.5 and contrast(f.night_accent, PALETTE["night-post"]) >= 4.5


def test_tomato_is_no_world_colour():
    for _, w in _all_worlds():
        assert PALETTE["tomato"] not in (*w.light.values(), *w.night.values())

def test_every_world_passes_contrast_by_day_and_night():
    for f, w in _all_worlds():
        for mode in (w.light, w.night):
            tag = (f.name, w.name, mode is w.night)
            for fg, bg, need in (("ink", "fill", 7), ("body", "fill", 4.5), ("muted", "fill", 4.5),
                                 ("label", "fill", 4.5), ("hi", "fill", 4.5), ("why", "fill", 4.5),
                                 ("accent", "fill", 3), ("on-hi", "hi-fill", 4.5),
                                 ("hi-label", "hi-fill", 4.5), ("ink", "cover-fill", 4.5),
                                 ("hi", "cover-fill", 4.5), ("label", "cover-fill", 4.5),
                                 ("ink", "plain-fill", 4.5), ("ink", "panel", 4.5),
                                 ("label", "panel", 4.5), ("muted", "panel", 4.5), ("hi", "panel", 4.5),
                                 ("label", "plain-fill", 4.5), ("muted", "plain-fill", 4.5),
                                 ("on-accent", "accent", 3)):
                assert contrast(mode[fg], mode[bg]) >= need, (tag, fg, bg, mode[fg], mode[bg])

def test_cover_big():
    assert cover_big("Alphabet loses over $500 billion in market value after Q3 miss") == "$500 billion"
    assert cover_big("Gemini 4 Carbon tops Artificial Analysis index at 59, access limited") == "Gemini 4"
    assert cover_big("Gurugram AQI drops to 125 after rain, a day after a reading of 242") == "Gurugram AQI"
    assert cover_big("Koundé out vs Alavés; Cubarsí and Martín are the only fit centre-backs") == "Koundé out"

@pytest.mark.parametrize("headline, big", [
    ("Verstappen wins by 14.4s at Interlagos", "Verstappen wins"),
    ("Sector 43 road shut for repairs", "Sector 43"),
    ("Polls on May 23 decide the mayor", "Polls"),
    ("Barça 3-1 Alavés: Lewandowski double", "3-1"),
    ("Barça 2–0 Getafe at Montjuïc", "2–0"),
    ("Gemini 2.5 Pro gets cheaper", "Gemini 2.5"),
    ("Govt clears Rs 1,200 crore metro plan", "Rs 1,200 crore"),
    ("Fine of Rs. 500 for idling", "Rs. 500"),
    ("INR 50 lakh penalty on builder", "INR 50 lakh"),
    ("In 2026 the rules change", "In 2026"),
    ("Helicopter with 6 on board missing in Uttarakhand", "Helicopter"),
    ("The Athletic: Flick's Barcelona regroup after defeat", "Flick's Barcelona"),
    ("Breaking: 3 killed in Chamoli crash", "3 killed"),
    ("Sensex falls 2.3% on Fed worries", "2.3%"),
    ("Delhi hits 41°C in November", "41°C"),
    ("A 12 km tunnel opens on NH-48", "12 km"),
    ("The new rules for e-rickshaws", "new rules"),
])
def test_cover_big_refined_rule(headline, big):
    assert cover_big(headline) == big


def test_cover_big_single_word():
    assert cover_big("Rain") == "Rain"

def test_visual_for_maps_formats():
    assert visual_for(card(format="C", payload={"series": []}))["kind"] == "chart"
    assert visual_for(card(headline="Delhi lifts curbs")) == {"kind": "none", "payload": {}}
    assert visual_for(card(visual="cover", payload={})) == {"kind": "none", "payload": {}}


def test_chart_key_is_the_writers_point_else_the_largest():
    pts = [{"label": "a", "value": 9}, {"label": "b", "value": 2, "key": True}, {"label": "c", "value": 4}]
    assert [b["key"] for b in _chart({"series": pts})["bars"]] == [False, True, False]
    pts[1]["key"] = False
    assert [b["key"] for b in _chart({"series": pts})["bars"]] == [True, False, False]


from newshouse.present import deck_for


def _src(url):
    return [{"item_id": "i0", "title": "t", "outlet": "Wire", "url": "https://x/1",
             "published_at": None, "paywall": False, "gnews": False, "image_url": url}]


def test_writer_cover_payload_wins():
    p = {"big": "-13%", "label": "Q3", "line": "Worst day."}
    assert visual_for(card(visual="cover", payload=p)) == {"kind": "cover", "payload": p}


def test_photo_with_unsafe_url_shows_no_visual():
    v = visual_for(card(visual="photo", payload={"item_id": "i0", "credit": "AP"},
                        sources=_src("http://x/a.jpg")))
    assert v["kind"] == "none"


def test_post_with_no_visual_shows_its_sources_photo():
    v = visual_for(card(visual="none", sources=_src("https://x/a.jpg")))
    assert v["kind"] == "photo" and v["payload"]["src"] == "https://x/a.jpg"
    assert v["payload"]["credit"] == "Wire" and "fallback" not in v["payload"]
    assert visual_for(card(visual="none", sources=_src(None))) == {"kind": "none", "payload": {}}
    assert visual_for(card(visual="cover", payload={}, sources=_src("https://x/a.jpg")))["kind"] == "photo"
    # a chosen visual never gives way to the photo
    assert visual_for(card(format="C", payload={"series": []}, sources=_src("https://x/a.jpg")))["kind"] == "chart"


def test_photo_has_src_and_fallback():
    v = visual_for(card(visual="photo", payload={"item_id": "i0", "credit": "AP"},
                        sources=_src("https://x/a.jpg")))
    assert v["kind"] == "photo" and v["payload"]["src"] == "https://x/a.jpg"
    assert v["payload"]["fallback"]["big"]


def test_deck_fills_by_role():
    slides = [{"kind": "cover", "title": "", "body": "", "payload": {"big": "9"}}] + \
             [{"kind": "text", "title": f"T{i}", "body": "One.\n\nTwo.", "payload": {}} for i in range(3)]
    deck = deck_for(card(slides=slides), None)
    assert [s["fill"] for s in deck] == ["cover", "plain", "plain", "plain"]
    assert deck[1]["body_paras"] == ["One.", "Two."]
    slides[2]["highlight"] = True
    assert [s["fill"] for s in deck_for(card(slides=slides), None)] == ["cover", "plain", "hi", "plain"]


def test_deck_highlight_is_one_slide_never_the_cover():
    slides = [{"kind": "cover", "title": "", "body": "", "payload": {"big": "9"}, "highlight": True}] + \
             [{"kind": "text", "title": "T", "body": "One.", "payload": {}, "highlight": True} for _ in range(2)]
    assert [s["fill"] for s in deck_for(card(slides=slides), None)] == ["cover", "hi", "plain"]


def test_blank_slide_cover_gets_the_automatic_cover():
    slides = [{"kind": "cover", "title": "", "body": "", "payload": {}},
              {"kind": "cover", "title": "", "body": "", "payload": {"big": "  ", "label": "Q3"}},
              {"kind": "text", "title": "T", "body": "One.", "payload": {}}]
    c = card(headline="Alphabet loses $500 billion in a day", line="Worst day ever.", slides=slides)
    deck = deck_for(c, None)
    assert deck[0]["payload"]["big"] == "$500 billion" and deck[0]["payload"]["line"] == "Worst day ever."
    assert deck[1]["payload"]["big"] == "$500 billion"
    kept = [{"kind": "cover", "title": "", "body": "", "payload": {"big": "-13%", "label": "Q3"}}]
    assert deck_for(card(slides=kept), None)[0]["payload"] == {"big": "-13%", "label": "Q3"}


def _tune_view(post_topics, also_topics, est_minutes=14):
    cards = [{"topics": [t], "rank": n} for n, t in enumerate(post_topics, start=1)]
    also = [{"cluster_id": f"a{n}", "cut_reason": None, "is_top": False, "folded": False,
             "topic": t, "rank": n} for n, t in enumerate(also_topics, start=1)]
    return {"cards": cards, "also": also, "counts": {"est_minutes": est_minutes}}


def test_tune_chips_rule():
    from newshouse.present import tune_chips
    view = _tune_view(["football"] * 6 + ["ai-models", "cricket"],
                      ["football", "movies", "movies", "cricket", "ai-models"])
    chips = tune_chips(view)
    assert [c["label"] for c in chips] == ["Less Football", "More Movies", "More Cricket",
                                           "Shorter edition"]
    assert [c["payload"] for c in chips] == [{"topic": "football", "dir": -1},
                                             {"topic": "movies", "dir": 1},
                                             {"topic": "cricket", "dir": 1}, {"budget": -1}]
    short = tune_chips(_tune_view(["football"] * 6, ["movies", "cricket"], est_minutes=11))
    assert short[-1] == {"label": "Longer edition", "payload": {"budget": 1}}
    # a topic with folded rows already flooded the cut list: no "More" for it; an untopiced
    # row is skipped
    view = _tune_view(["football"], ["other", "gurgaon-local", "movies"])
    view["also"].append({"cluster_id": "f", "cut_reason": "topic cap", "is_top": True,
                         "folded": True, "topic": "gurgaon-local", "rank": 4})
    assert [c["label"] for c in tune_chips(view)] == ["Less Football", "More Movies",
                                                      "Shorter edition"]
    assert [c["label"] for c in tune_chips(_tune_view([], [], est_minutes=0))] == ["Longer edition"]


def test_tune_chips_skip_a_topic_over_the_line_cap():
    """An edition built before folding (3 Nov) lists a flood as plain lines: a topic with more
    lines than the per-topic cap is flooded too, so it gets no "More" chip."""
    from newshouse.present import tune_chips
    view = _tune_view(["india-news"] * 3, ["gurgaon-local"] * 3 + ["movies"])
    labels = [c["label"] for c in tune_chips(view, per_topic=2)]
    assert labels == ["Less India", "More Movies", "Shorter edition"]
    assert "More Gurgaon" in [c["label"] for c in tune_chips(view)]  # no cap given: no check
    view = _tune_view(["india-news"], ["gurgaon-local"] * 2 + ["movies"])
    assert [c["label"] for c in tune_chips(view, per_topic=2)][1] == "More Gurgaon"  # at the cap


# ---- phase A render helpers ----
from datetime import date as _date
from newshouse.present import HEADLINE_FIRST, amount, date_bar, number_bars


def test_amount_parses_scales_and_currencies():
    assert amount("$465M") == ("$", 4.65e8)
    assert amount("₹143.63 cr") == ("₹", 143.63e7)
    assert amount("Rs 69.71 crore")[0] == "₹" and amount("INR 5 lakh") == ("₹", 5e5)
    assert amount("$174K") == ("$", 174e3) and amount("12%") == ("%", 12.0)
    assert amount("about half") is None and amount("5 people") is None
    assert amount("₹1.2 lakh crore") == ("₹", 1.2e12)
    assert amount("-13%") is None and amount("₹5-7 lakh") is None and amount("5 to 7%") is None


def test_number_bars_never_mix_percent_and_amounts():
    assert number_bars({"value": "40%", "compare": {"label": "x", "value": "1.2M"}}) is None
    assert number_bars({"value": "₹1.2 lakh crore", "compare": {"label": "x", "value": "₹90,000 crore"}})[0]["w"] == 100


def test_odd_stored_fact_payloads_never_crash():
    for kind, p in (("number", ["x"]), ("changes", "str"), ("changes", {"rows": None}),
                    ("key-facts", {"facts": None}), ("key-facts", {"facts": [{"label": "a", "value": None}]}),
                    ("factsheet", {"has": None}), ("factsheet", {"has": 5})):
        assert visual_for(card(visual=kind, payload=p)) == {"kind": "none", "payload": {}}, (kind, p)


def test_number_bars_only_for_matching_currencies():
    bars = number_bars({"value": "$465M", "compare": {"label": "H1 revenue", "value": "$174K"}})
    assert [b["w"] for b in bars] == [100, 0] and bars[0]["key"] and bars[1]["label"] == "H1 revenue"
    assert number_bars({"value": "₹143.63 cr", "compare": {"label": "x", "value": "$10M"}}) is None
    assert number_bars({"value": "$5M", "compare": {"label": "x", "value": "a lot"}}) is None
    assert number_bars({"value": "$5M", "compare": None}) is None


def test_date_bar_today_dot_only_inside():
    today = _date(2026, 11, 6)
    assert date_bar("2026-11-05", "2026-11-20", today) == {"from": "5 Nov", "to": "20 Nov", "today": 7}
    assert date_bar("2026-11-08", "2026-11-20", today)["today"] is None
    assert date_bar("2026-10-01", "2026-11-02", today)["today"] is None
    assert date_bar("2026-11-05", None, today) == {"from": "5 Nov", "to": None, "today": None}
    assert date_bar(None, None, today) is None and date_bar("soon", None, today) is None


def test_number_is_tinted_like_cover():
    w = colour_world(card(topics=["gurgaon-local"]), position=2, previous=["white"], cfg=CFG, visual="number")
    assert w.name == "tint"


def test_headline_first_set():
    assert {"key-facts", "changes", "factsheet", "versus", "chart", "table", "pitch"} <= HEADLINE_FIRST
    assert not {"photo", "number", "cover", "quote"} & HEADLINE_FIRST


def test_odd_stored_story_payloads_never_crash():
    for kind, p in (("scale", {"scale": ["aqi"], "level": 0}), ("scale", {"scale": {}}), ("countdown", {"date": "soon", "what": "x"}),
                    ("stakes", {"outcomes": [{"if": None, "then": "x"}]}), ("rumour", {"player": "X"}),
                    ("deal", {"from": None}), ("scoreline", {"home": "a", "away": "b", "score": ["3", 0]}),
                    ("case", {"steps": "x"}), ("incident", {"symptom": 5}), ("steps", {"steps": [None]})):
        assert visual_for(card(visual=kind, payload=p)) == {"kind": "none", "payload": {}}, (kind, p)
    av = visual_for(card(visual="availability", payload={"player": "Rodri", "status": "bogus",
                                                        "fixtures": [{"vs": "Atl", "plays": "bogus"}]}))
    assert av["payload"]["status"] == "" and av["payload"]["fixtures"][0]["plays"] == "doubt"
