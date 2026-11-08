from datetime import date
from newshouse import catalogue
from newshouse.catalogue import (ItemFacts, effective_visual, payload_problems, visual_seconds, slide_problems)

ITEMS = {"i1": ItemFacts(text="Alphabet fell 13% on Thursday. 'We will spend more,' said Ashkenazi.\nBalde and Kounde start; Kounde out with an ankle knock.",
                         image_url="https://img.example.com/a.jpg"),
         "i2": ItemFacts(text="No image here.")}

def test_effective_visual_maps_legacy_formats():
    assert effective_visual("cover", "B") == "table"
    assert effective_visual(None, "C") == "chart"
    assert effective_visual("quote", "A") == "quote"
    assert effective_visual("cover", "A") == "cover"
    assert effective_visual("nonsense", "A") == "none"
    assert effective_visual("none", "A") == "none" and effective_visual(None, None) == "none"
    assert effective_visual("none", "B") == "table"


def test_none_visual_takes_no_payload():
    assert payload_problems("none", {}, cited={"i1"}, items=ITEMS) == []


def test_cover_payload_needs_big():
    assert payload_problems("cover", {}, cited={"i1"}, items=ITEMS)
    assert payload_problems("cover", {"big": " "}, cited={"i1"}, items=ITEMS)
    assert payload_problems("cover", {"big": "-13%", "label": "Thursday", "line": "Worst day."},
                            cited={"i1"}, items=ITEMS) == []
    assert payload_problems("cover", {"big": "x" * 15}, cited={"i1"}, items=ITEMS)

def test_cover_digits_must_be_in_a_cited_item():
    assert payload_problems("cover", {"big": "-14%"}, cited={"i1"}, items=ITEMS)

def test_quote_text_must_appear_in_its_item():
    ok = {"text": "We will spend   MORE", "who": "Anat Ashkenazi", "where": "earnings call", "item_id": "i1"}
    assert payload_problems("quote", ok, cited={"i1"}, items=ITEMS) == []
    bad = {**ok, "text": "We will spend less"}
    assert payload_problems("quote", bad, cited={"i1"}, items=ITEMS)
    assert payload_problems("quote", ok, cited={"i2"}, items=ITEMS)  # item not cited

def test_pitch_names_must_appear_in_cited_items():
    p = {"rows": [[{"pos": "LB", "name": "Balde"}]], "note": "Predicted, per a fan site",
         "out": [{"name": "Kounde", "why": "ankle"}]}
    assert payload_problems("pitch", p, cited={"i1"}, items=ITEMS) == []
    p2 = {**p, "rows": [[{"pos": "ST", "name": "Haaland"}]]}
    assert any("Haaland" in x for x in payload_problems("pitch", p2, cited={"i1"}, items=ITEMS))

def test_photo_item_must_be_cited_and_have_an_image():
    ok = {"item_id": "i1", "alt": "Sundar Pichai on stage", "credit": "Wire"}
    assert payload_problems("photo", ok, cited={"i1"}, items=ITEMS) == []
    assert payload_problems("photo", {**ok, "item_id": "i2"}, cited={"i2"}, items=ITEMS)

def test_v1_visuals_delegate_to_format_rules():
    assert payload_problems("chart", {"series": []}, cited=set(), items={})
    assert payload_problems("before-after", {"before": "a", "after": "b", "effective": "c",
                                             "applies_to": "d"}, cited=set(), items={}) == []

def test_unknown_visual_is_a_problem():
    assert payload_problems("hologram", {}, cited=set(), items={})

def test_visual_seconds():
    assert visual_seconds("cover", []) == 35
    assert visual_seconds("cover", [{}, {}]) == 50
    assert visual_seconds("chart", []) == 50


BRIEF = "Revenue was $127.58B against $127.97B expected.\n\nAbout $500 billion was wiped off.\n\nWhat to watch next: the Q4 call."
COVER = {"kind": "cover", "title": "", "body": "Worst day ever.", "payload": {"big": "$500B", "label": "The damage"}}
NEXT = {"kind": "what-next", "title": "What next", "body": "The Q4 call explains capex.", "payload": {}}

def test_empty_deck_is_fine():
    assert slide_problems([], brief=BRIEF, cited=set(), items={}) == []

def test_deck_needs_two_to_four_slides_and_cover_first():
    assert slide_problems([COVER], brief=BRIEF, cited=set(), items={})
    assert slide_problems([COVER] * 5, brief=BRIEF, cited=set(), items={})
    assert slide_problems([NEXT, COVER], brief=BRIEF, cited=set(), items={})
    assert slide_problems([COVER, NEXT], brief=BRIEF, cited=set(), items={}) == []

def test_slide_numbers_must_be_in_the_brief():
    bad = {**COVER, "payload": {"big": "$600B"}}
    probs = slide_problems([bad, NEXT], brief=BRIEF, cited=set(), items={})
    assert any("600" in p and p.startswith("slides[0]") for p in probs)

def test_cover_slide_keeps_the_14_character_rule():
    long = {**COVER, "payload": {"big": "$500 billion lost"}}
    assert any("14" in p for p in slide_problems([long, NEXT], brief=BRIEF, cited=set(), items={}))

def test_text_slide_limits():
    long_body = {"kind": "text", "title": "One two three four five", "body": "word " * 36, "payload": {}}
    probs = slide_problems([COVER, long_body], brief=BRIEF, cited=set(), items={})
    assert any("title" in p for p in probs) and any("35" in p for p in probs)

def test_what_next_is_last_when_brief_has_watch_line():
    text = {"kind": "text", "title": "The miss", "body": "Revenue missed.", "payload": {}}
    assert slide_problems([COVER, text], brief=BRIEF, cited=set(), items={})
    assert slide_problems([COVER, NEXT, text], brief=BRIEF, cited=set(), items={})

def test_what_next_word_limit_and_unknown_kind():
    wordy = {**NEXT, "body": "word " * 61}
    assert any("60" in p for p in slide_problems([COVER, wordy], brief=BRIEF, cited=set(), items={}))
    odd = {"kind": "gif", "title": "", "body": "", "payload": {}}
    assert slide_problems([COVER, odd], brief=BRIEF, cited=set(), items={})

def test_chart_and_table_slides_use_their_payload_rules():
    table = {"kind": "table", "title": "The miss", "body": "", "payload": {"columns": ["x"], "rows": []}}
    assert slide_problems([COVER, table], brief=BRIEF, cited=set(), items={})

def test_chart_slide_item_ids_do_not_count_as_numbers():
    chart = {"kind": "chart", "title": "Revenue", "body": "", "payload": {
        "series": [{"label": "A", "value": 127.58, "item_id": "i1"}, {"label": "B", "value": 127.97, "item_id": "i1"},
                   {"label": "C", "value": 500, "item_id": "i1"}], "unit": "$B", "caption": "Revenue"}}
    assert slide_problems([COVER, chart, NEXT], brief=BRIEF, cited={"i1"}, items=ITEMS) == []


def _table(n):
    return {"kind": "table", "title": "The miss", "body": "", "payload": {
        "columns": ["Metric", "Quarter"], "rows": [{"cells": [chr(97 + i), "x"], "yours": False, "new": False} for i in range(n)]}}


def _chart(n):
    return {"kind": "chart", "title": "Revenue", "body": "", "payload": {
        "series": [{"label": chr(97 + i), "value": 127.58, "item_id": "i1"} for i in range(n)], "unit": "$B", "caption": "Revenue"}}


def _row_problems(slide):
    return [p for p in slide_problems([COVER, slide, NEXT], brief=BRIEF, cited={"i1"}, items=ITEMS)
            if p.startswith("slides[1]")]


def test_table_slide_has_at_most_4_rows():
    assert _row_problems(_table(4)) == []
    assert any("4 rows" in p for p in _row_problems(_table(5)))


def test_chart_slide_has_at_most_6_points():
    assert _row_problems(_chart(6)) == []
    assert any("6 points" in p for p in _row_problems(_chart(7)))


# Final review, Important 1: numbers compare by value, not by digit runs.
def _chart_vals(vals, unit="$"):
    return {"kind": "chart", "title": "Price", "body": "", "payload": {
        "series": [{"label": chr(97 + i), "value": v, "item_id": "i1"} for i, v in enumerate(vals)],
        "unit": unit, "caption": "Price per million"}}


def _deck_probs(slide, brief):
    cover = {"kind": "cover", "title": "", "body": "", "payload": {"big": "Prices"}}
    return slide_problems([cover, slide], brief=brief, cited={"i1"}, items=ITEMS)


def test_decimal_chart_values_match_dollar_figures_in_the_brief():
    brief = "Input costs $0.10, cached $0.25 and output $0.40 per million."
    assert _deck_probs(_chart_vals([0.10, 0.25, 0.40]), brief) == []


def test_comma_thousands_match_plain_numbers_both_ways():
    assert _deck_probs(_chart_vals([1200, 300, 40]), "Rs 1,200 crore, 300 and 40.") == []
    cover = {"kind": "cover", "title": "", "body": "", "payload": {"big": "1,200 cr"}}
    text = {"kind": "text", "title": "The sum", "body": "Paid in full.", "payload": {}}
    assert slide_problems([cover, text], brief="A 1200 crore deal.", cited=set(), items={}) == []


def test_large_payload_number_is_not_split_by_float_formatting():
    assert _deck_probs(_chart_vals([1500000, 300, 40]), "1,500,000 users, 300 and 40.") == []


def test_absent_number_is_named_as_written():
    probs = _deck_probs(_chart_vals([0.10, 0.25, 0.55]), "Input $0.10, cached $0.25, output $0.40.")
    assert any("0.55" in p and p.startswith("slides[1]") for p in probs)
    text = {"kind": "text", "title": "The sum", "body": "Rs 1,350 crore.", "payload": {}}
    probs = _deck_probs(text, "Rs 1,200 crore.")
    assert any("1,350" in p for p in probs)


def test_cover_big_with_comma_matches_cited_item():
    items = {"i9": ItemFacts(text="The 1200 crore deal closed.")}
    assert payload_problems("cover", {"big": "1,200 cr"}, cited={"i9"}, items=items) == []
    assert payload_problems("cover", {"big": "1,300 cr"}, cited={"i9"}, items=items)


# Final review, Important 2: a deck's cover slide needs a big.
def test_slide_cover_needs_a_non_empty_big():
    for payload in ({}, {"big": "  "}, {"label": "The damage"}):
        blank = {**COVER, "payload": payload}
        probs = slide_problems([blank, NEXT], brief=BRIEF, cited=set(), items={})
        assert any(p.startswith("slides[0]") and "big" in p for p in probs), payload
    assert slide_problems([COVER, NEXT], brief=BRIEF, cited=set(), items={}) == []


# Final review, Important 3: the page shows at most 4 pitch rows and 3 out entries.
def test_pitch_rejects_more_than_4_rows_or_3_out():
    row = [{"pos": "LB", "name": "Balde"}]
    four = {"rows": [row] * 4, "note": "Predicted", "out": [{"name": "Kounde", "why": "ankle"}] * 3}
    assert payload_problems("pitch", four, cited={"i1"}, items=ITEMS) == []
    five = {**four, "rows": [row] * 5}
    assert any("4 rows" in p for p in payload_problems("pitch", five, cited={"i1"}, items=ITEMS))
    many_out = {**four, "out": [{"name": "Kounde", "why": "ankle"}] * 4}
    assert any("3 " in p and "out" in p for p in payload_problems("pitch", many_out, cited={"i1"}, items=ITEMS))


# Final review, Minor 1: accents fold on both sides.
def test_pitch_names_match_across_accents():
    p = {"rows": [[{"pos": "RB", "name": "Koundé"}]], "note": "Predicted", "out": []}
    assert payload_problems("pitch", p, cited={"i1"}, items=ITEMS) == []  # source says Kounde
    accented = {"i3": ItemFacts(text="Koundé starts at right back.")}
    plain = {**p, "rows": [[{"pos": "RB", "name": "Kounde"}]]}
    assert payload_problems("pitch", plain, cited={"i3"}, items=accented) == []


# Final review, Minor 2: a quote that keeps its own quote marks still matches.
def test_quote_text_with_its_own_quote_marks_matches():
    base = {"who": "Anat Ashkenazi", "where": "earnings call", "item_id": "i1"}
    for text in ("'We will spend more,'", "“We will spend more”", '"We will spend more"',
                 "‘We will spend more,’"):
        assert payload_problems("quote", {**base, "text": text}, cited={"i1"}, items=ITEMS) == [], text
    assert payload_problems("quote", {**base, "text": "'We will spend less'"}, cited={"i1"}, items=ITEMS)
    assert payload_problems("quote", {**base, "text": "\u201c\u201d"}, cited={"i1"}, items=ITEMS)


def test_long_table_value_rejected():
    ok = {"columns": ["Item", "Value"], "rows": [{"cells": ["Hours", "50 hours a year"], "yours": False, "new": False},
                                                 {"cells": ["Other", "x" * 28], "yours": False, "new": False}]}
    assert payload_problems("table", ok, cited={"i1"}, items=ITEMS) == []
    bad = {**ok, "rows": [{"cells": ["Maths", "Computational thinking inside Mathematics"], "yours": False, "new": False}]}
    probs = payload_problems("table", bad, cited={"i1"}, items=ITEMS)
    assert any("value over 28 characters" in p for p in probs)
    sentence = "x" * 60
    assert payload_problems("versus", {"for": [sentence], "against": [sentence], "stands": sentence},
                            cited={"i1"}, items=ITEMS) == []
    assert payload_problems("before-after", {"before": sentence, "after": sentence, "effective": "e",
                                             "applies_to": "all"}, cited={"i1"}, items=ITEMS) == []


# Test build 2026-11-04: a five-quote versus stood 623px tall at phone width.
def test_long_versus_rejected():
    ok = {"for": ["x" * 90, "y" * 90], "against": ["z" * 90], "stands": "s" * 140}
    assert payload_problems("versus", ok, cited={"i1"}, items=ITEMS) == []
    three = {**ok, "against": ["a", "b", "c"]}
    assert any("at most 2 points" in p for p in payload_problems("versus", three, cited={"i1"}, items=ITEMS))
    long_point = {**ok, "for": ["x" * 91]}
    assert any("point over 90 characters" in p
               for p in payload_problems("versus", long_point, cited={"i1"}, items=ITEMS))
    long_stands = {**ok, "stands": "s" * 141}
    assert any("stands over 140 characters" in p
               for p in payload_problems("versus", long_stands, cited={"i1"}, items=ITEMS))


TEXT = {"kind": "text", "title": "Why", "body": "Search is hurting.", "payload": {}}

def test_highlight_mistakes_never_cost_the_deck():
    """deck_for drops a mark on the cover and keeps the first other one (test_present)."""
    hi = {**TEXT, "highlight": True}
    for deck in ([COVER, hi, NEXT], [COVER, hi, {**NEXT, "highlight": True}],
                 [{**COVER, "highlight": True}, NEXT], [COVER, {**TEXT, "highlight": "yes"}, NEXT]):
        assert slide_problems(deck, brief=BRIEF, cited=set(), items={}) == []


def test_slide_cover_message_names_the_slide():
    probs = slide_problems([{**COVER, "payload": {}}, NEXT], brief=BRIEF, cited=set(), items={})
    assert "slides[0] a cover slide needs a non-empty payload.big" in probs


def test_chart_marks_at_most_one_key_point():
    pts = [{"label": x, "value": n, "item_id": "i1"} for n, x in enumerate("abc")]
    chart = {"series": pts, "unit": "%", "caption": "c"}
    assert payload_problems("chart", chart, cited={"i1"}, items=ITEMS) == []
    pts[0]["key"] = pts[1]["key"] = True
    assert "payload.series may mark at most one point key" in payload_problems(
        "chart", chart, cited={"i1"}, items=ITEMS)
    pts[1]["key"] = "no"
    assert "payload.series[1].key must be a boolean" in payload_problems(
        "chart", chart, cited={"i1"}, items=ITEMS)


# ---- phase A fact formats (docs/design-visuals.md 4.1-4.4, 9.1-9.2) ----

FACTS = {"f1": ItemFacts(text="Raphinha will sign a contract renewal with president Laporta on Thursday. "
                              "CAQM caps offices at 50% from 5 to 20 November across Delhi-NCR. "
                              "PhysicsWallah Q2 profit was ₹143.63 crore against ₹69.71 crore a year ago. "
                              "Grok can sit on hold for paid users in the US at $30 a month.")}


def _pp(visual, payload):
    return payload_problems(visual, payload, cited={"f1"}, items=FACTS)


def test_key_facts_rules():
    good = {"facts": [{"label": "Who", "value": "Raphinha"}, {"label": "What", "value": "Contract renewal"},
                      {"label": "When", "value": "Thursday"}]}
    assert _pp("key-facts", good) == []
    assert _pp("key-facts", {"facts": good["facts"][:1]})  # at least 2
    assert _pp("key-facts", {"facts": good["facts"] * 2})  # at most 4
    assert any("15" in p or "14" in p for p in _pp("key-facts", {"facts": [{"label": "x" * 15, "value": "a"},
                                                                          {"label": "b", "value": "c"}]}))
    assert any("32" in p for p in _pp("key-facts", {"facts": [{"label": "a", "value": "x" * 33},
                                                             {"label": "b", "value": "c"}]}))
    bad = {"facts": [{"label": "Who", "value": "Zubimendi"}, {"label": "When", "value": "Thursday"}]}
    assert "payload has the name 'Zubimendi', which no cited item contains" in _pp("key-facts", bad)
    bad = {"facts": [{"label": "Cap", "value": "60%"}, {"label": "When", "value": "Thursday"}]}
    assert "payload has the number 60, which no cited item contains" in _pp("key-facts", bad)


def test_number_rules():
    good = {"value": "₹143.63 cr", "what": "PhysicsWallah Q2 profit",
            "compare": {"label": "a year ago", "value": "₹69.71 cr"}}
    assert _pp("number", good) == []
    assert _pp("number", {**good, "compare": None}) == []
    assert _pp("number", {**good, "value": "₹999 cr"})  # untraced
    assert _pp("number", {**good, "value": "x" * 13})
    assert _pp("number", {**good, "what": "x" * 49})
    assert _pp("number", {**good, "compare": {"label": "x" * 25, "value": "₹69.71 cr"}})
    assert _pp("number", {**good, "value": "Big week"})  # a phrase is a cover, not a number


def test_changes_rules():
    good = {"rows": [{"what": "Offices", "change": "at most 50% in person"},
                     {"what": "Construction", "change": "dust-raising work stopped"}],
            "from": "2026-11-05", "to": "2026-11-20", "where": "Delhi-NCR"}
    assert _pp("changes", good) == []  # "5 to 20 November" traces both dates
    assert _pp("changes", {**good, "from": None, "to": None}) == []
    assert _pp("changes", {**good, "rows": good["rows"][:1]})
    assert any("after" in p for p in _pp("changes", {**good, "from": "2026-11-20", "to": "2026-11-05"}))
    assert any("2026-11-12" in p for p in _pp("changes", {**good, "to": "2026-11-12"}))
    assert any("where" in p for p in _pp("changes", {**good, "where": "Mumbai"}))
    assert any("32" in p for p in _pp("changes", {**good, "rows": [{"what": "a", "change": "x" * 33}] * 2}))
    assert _pp("changes", {**good, "rows": good["rows"] * 2})  # at most 3 rows
    assert _pp("changes", {**good, "rows": [{"what": "Payments above ₹9,999", "change": "at most 50% in person"}] * 2})
    assert _pp("changes", {**good, "rows": [{"what": "Offices", "change": "at most 60% in person"}] * 2})


def test_factsheet_rules():
    good = {"has": ["sits on hold", "books appointments"], "lacks": ["outside the US"],
            "price": "$30 a month", "status": "limited", "where": "paid users"}
    assert _pp("factsheet", good) == []
    assert _pp("factsheet", {**good, "lacks": [], "price": None, "status": None, "where": None}) == []
    assert _pp("factsheet", {**good, "has": []})
    assert _pp("factsheet", {**good, "has": ["a"] * 4})  # at most 3
    assert _pp("factsheet", {**good, "lacks": None}) == []
    assert _pp("factsheet", {**good, "lacks": ["a"] * 3})
    assert _pp("factsheet", {**good, "has": ["x" * 27]})
    assert _pp("factsheet", {**good, "status": "soon"})
    assert any("number 40" in p for p in _pp("factsheet", {**good, "price": "$40 a month"}))


def test_dates_need_day_and_month_together():
    t = {"d": ItemFacts(text="The mayor said 5 projects. Curbs run 5 to 20 November; Sept 3 review; "
                             "polls on November 12; 1st Dec start.")}
    ok = lambda iso: catalogue._date_in(iso, {"d"}, t, today=date(2026, 11, 6))
    assert ok("2026-11-05") and ok("2026-11-20") and ok("2026-11-12") and ok("2026-09-03") and ok("2026-12-01")
    assert not ok("2026-05-05")  # "mayor" and a stray 5 are not a date
    assert not ok("2026-11-07") and not ok("2019-11-05")


def test_names_need_whole_words_and_ignore_possessives():
    t = {"n": ItemFacts(text="PhysicsWallah IPO plans; Delhi NCR offices; a training programme.")}
    un = lambda v: catalogue._unnamed([v], {"n"}, t)
    assert un("PhysicsWallah's profit") == [] and un("Delhi-NCR") == []
    assert un("Ram") == ["Ram"] and un("Škoda deal") == ["Škoda"]
    assert un("contract renewal") == []


# ---- phases B and C (docs/design-visuals.md 4.5-4.13) ----

STORY = {"s1": ItemFacts(text=(
    "OpenAI agrees to buy Pierre, whose developer tools power Codex, for $400M in an all-stock deal; it needs approval. "
    "Rodri is out with a right hamstring injury for about 3 weeks and will miss Atlético on 9 November. "
    "Barcelona beat Aston Villa 3-0 in the Champions League: Raphinha scored in the 12th and 55th minute. "
    "On Sunday a win at Atlético puts Barça five points clear; a loss puts Atlético one point ahead. "
    "Two developers report 503 errors on gemini-3.1-flash-lite since 2 November; Google has not replied. "
    "gemini-2.5-flash calls move to 3.5-flash-lite on 1 December 2026; re-test on real recordings. "
    "The Supreme Court issued notice on 3 November and will hear the plea on 20 November. "
    "CAQM moved Delhi-NCR to GRAP stage II as AQI reached 324. "
    "Leipzig defender Castello Lukeba may join Barcelona for €65m, per Fabrizio Romano. "
    "Upload a sketch, ask Canvas to code it, then test it in the preview."))}


def _sp(visual, payload):
    return payload_problems(visual, payload, cited={"s1"}, items=STORY)


def test_deal_rules():
    good = {"kind": "acquisition", "from": "OpenAI", "to": "Pierre", "amount": "$400M", "terms": "all-stock",
            "to_does": "developer tools that power Codex", "status": "needs approval"}
    assert _sp("deal", good) == []
    assert _sp("deal", {**good, "amount": "$900M"}) and _sp("deal", {**good, "to": "Conductor"})
    assert _sp("deal", {**good, "kind": "buyout"}) and _sp("deal", {**good, "status": "done"})
    assert _sp("deal", {**good, "amount": None, "terms": None, "status": None}) == []


def test_availability_scoreline_stakes_rumour_rules():
    av = {"player": "Rodri", "status": "out", "reason": "right hamstring", "return": "about 3 weeks",
          "fixtures": [{"vs": "Atlético", "date": "9 Nov", "plays": "miss"}]}
    assert _sp("availability", av) == []
    assert _sp("availability", {**av, "status": "injured"})
    assert _sp("availability", {**av, "fixtures": [{"vs": "Getafe", "date": None, "plays": "miss"}]})
    sc = {"home": "Barcelona", "away": "Aston Villa", "score": [3, 0], "competition": "Champions League",
          "scorers": [{"name": "Raphinha", "minute": "12'", "side": "home"}], "note": None}
    assert _sp("scoreline", sc) == []
    assert _sp("scoreline", {**sc, "score": [4, 0]}) and _sp("scoreline", {**sc, "score": ["3", 0]})
    st = {"fixture": "Atlético v Barça", "when": "Sunday", "outcomes": [{"if": "win", "then": "five points clear"},
                                                                       {"if": "loss", "then": "Atlético one point ahead"}]}
    assert _sp("stakes", st) == []
    assert _sp("stakes", {**st, "outcomes": st["outcomes"][:1]})
    ru = {"player": "Castello Lukeba", "from": "Leipzig", "to": "Barcelona", "fee": "€65m",
          "source": "Fabrizio Romano", "tier": "reporter"}
    assert _sp("rumour", ru) == []
    assert _sp("rumour", {**ru, "tier": "confirmed"}) and _sp("rumour", {**ru, "fee": "€80m"})


def test_incident_countdown_rules():
    inc = {"symptom": "503 errors", "affects": ["gemini-3.1-flash-lite"], "reports": 2, "vendor": "no reply",
           "since": "2 November", "workaround": None}
    assert _sp("incident", inc) == []
    assert _sp("incident", {**inc, "reports": 7})  # more than the cited items and no item says 7
    assert _sp("incident", {**inc, "vendor": "silent"})
    cd = {"date": "2026-12-01", "what": "gemini-2.5-flash calls move to 3.5-flash-lite", "do": "re-test on real recordings"}
    assert _sp("countdown", cd) == []
    assert _sp("countdown", {**cd, "date": "2026-12-02"})


def test_case_scale_steps_rules():
    case = {"court": "Supreme Court", "asked": "a plea", "next": "20 November",
            "steps": [{"label": "notice issued", "date": "3 November", "done": True},
                      {"label": "hearing", "date": "20 November", "done": False},
                      {"label": "ruling", "date": None, "done": False}]}
    assert _sp("case", case) == []
    assert _sp("case", {**case, "steps": case["steps"][:2]})
    assert _sp("case", {**case, "steps": [{**case["steps"][0], "done": "yes"}] * 3})
    assert _sp("scale", {"scale": "grap", "level": 1, "previous": None, "value": None}) == []
    assert _sp("scale", {"scale": "grap", "level": 1, "previous": 0, "value": None})  # stage I not named
    assert _sp("scale", {"scale": "grap", "level": 2, "previous": None, "value": None})  # stage III not named
    assert _sp("scale", {"scale": "aqi", "level": 4, "previous": None, "value": 324}) == []
    assert _sp("scale", {"scale": "aqi", "level": 3, "previous": None, "value": 324})  # 324 is very poor
    assert _sp("steps", {"steps": ["Upload a sketch", "Ask Canvas to code it", "Test it in the preview"]}) == []
    assert _sp("steps", {"steps": ["Upload a sketch", "Test it"]})


def test_bc_review_fixes():
    t = {"r": ItemFacts(text="Barcelona beat Real Madrid 3-0 on 1 November. GRAP II is in force; AQI 412 today, 268 yesterday. "
                             "Thursday 9 November. Lukeba could cost 65 million euros. Two developers report 503s.")}
    pp = lambda v, p: payload_problems(v, p, cited={"r"}, items=t)
    sc = {"home": "Barcelona", "away": "Real Madrid", "score": [3, 0], "competition": "LaLiga", "scorers": [], "note": None}
    assert not [x for x in pp("scoreline", sc) if "score" in x]
    assert [x for x in pp("scoreline", {**sc, "score": [1, 3]}) if "payload.score" in x]  # digits from the date
    assert pp("scale", {"scale": ["aqi"], "level": 0}) and pp("scale", {"scale": {}, "level": 0})  # no crash
    assert pp("scale", {"scale": "grap", "level": 1, "previous": None, "value": None}) == []  # "GRAP II"
    assert pp("scale", {"scale": "grap", "level": 1, "previous": None, "value": 487})  # invented number
    assert pp("scale", {"scale": "aqi", "level": 5, "previous": 3, "value": 412}) == []  # 268 is poor
    assert pp("scale", {"scale": "aqi", "level": 5, "previous": 1, "value": 412})
    kf = lambda v: pp("key-facts", {"facts": [{"label": "When", "value": v}, {"label": "Who", "value": "Barcelona"}]})
    assert kf("Thursday 9 Nov") == [] and kf("Friday 9 March")
    assert pp("rumour", {"player": "Lukeba", "from": "Leipzig", "to": "Barcelona", "fee": "£65m",
                         "source": "Barcelona", "tier": "report"})
    st = {"fixture": "Barcelona v Real Madrid", "when": "Thursday",
          "outcomes": [{"if": "win", "then": "a"}, {"if": "win", "then": "b"}]}
    assert any("at most once" in x for x in pp("stakes", st))


def test_countdown_year_is_the_next_occurrence():
    t = {"c": ItemFacts(text="The scheme ends on 9 November.")}
    ok = lambda iso, today: catalogue._countdown_year_ok(iso, {"c"}, t, today=today)
    assert ok("2026-11-09", date(2026, 11, 6)) and not ok("2025-11-09", date(2026, 11, 6))
    assert not ok("2027-11-09", date(2026, 11, 6)) and ok("2027-11-09", date(2026, 11, 10))
