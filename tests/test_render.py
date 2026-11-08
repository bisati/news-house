import json

from newshouse.edition_config import EditionConfig
from newshouse.models import Cluster, Item, Source
from newshouse.render_static import edition_view, render_edition, latest_title, strip_outlet
from newshouse.validate import load_banned
from tests.helpers import seed_edition


ALSO = [{"cluster_id": "c0", "rank": 1, "line": "Minor thing happened"}]


B = {"columns": ["Model", "Price"], "rows": [{"cells": ["Mine", "1"], "yours": True, "new": False},
                                              {"cells": ["Shiny", "2"], "yours": False, "new": True}]}
C = {"series": [{"label": "Q1", "value": 10, "item_id": "i2"}, {"label": "Q2", "value": 20, "item_id": "i2"},
                {"label": "Q3", "value": 15, "item_id": "i2"}], "unit": "$M", "caption": "Raised"}


def test_render_writes_html_and_json(session, tmp_path):
    ed = seed_edition(session, [(1, "A", "Alpha head", {}, {}), (2, "B", "Beta table head", B, {}),
                        (3, "C", "Gamma chart head", C, {})])
    out = tmp_path / "out"
    path = render_edition(session, ed, out)
    assert path == out / "2026-10-30.html" and path.exists()
    html = path.read_text()
    assert "Beta table head" in html and 'class="bar-row"' in html and 'class="rows"' in html
    data = json.loads((out / "2026-10-30.json").read_text())
    assert len(data["cards"]) == 3 and data["date"] == "2026-10-30"
    assert data["counts"] == {"cards": 3, "est_minutes": 3, "saved": 0, "breaking": 0}


def test_render_marks_unverified(session, tmp_path):
    ed = seed_edition(session, [(1, "A", "Shaky", {}, {"unverified": True}), (2, "A", "Solid", {}, {})])
    html = render_edition(session, ed, tmp_path).read_text()
    assert html.count('class="unverified"') == 1


def test_edition_view_orders_breaking_first_and_includes_sources(session):
    ed = seed_edition(session, [(1, "A", "Normal", {}, {}), (0, "A", "Breaking", {}, {"breaking": True})],
                      also=ALSO)
    v = edition_view(session, ed)
    assert [c["headline"] for c in v["cards"]] == ["Breaking", "Normal"]
    assert v["counts"]["breaking"] == 1
    src = v["cards"][0]["sources"][0]
    assert src["outlet"] == "Wire" and src["title"] == "Source title 1" and src["url"] == "http://x/1"
    assert v["cards"][0]["topics"] == ["ai-models"] and v["cards"][0]["n_sources"] == 1
    assert v["also"] == [{"rank": 1, "line": "Minor thing happened", "cluster_id": "c0",
                          "cut_reason": None, "is_top": False, "folded": False,
                          "topic": "ai-models"}]
    assert v["top_ids"] == [] and v["warnings"] == []
    json.dumps(v)


def test_render_escapes_model_text(session, tmp_path):
    ed = seed_edition(session, [(1, "A", "<script>alert(1)</script>", {}, {"why": "<img src=x>"})])
    html = render_edition(session, ed, tmp_path).read_text()
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;alert(1)" in html
    assert "<img src=x>" not in html


def test_render_all_formats(session, tmp_path):
    D = {"chapters": [{"title": "Ch one", "date": "Mar 2024", "read": True}], "delta": "Fines land"}
    E = {"for": ["Pro point"], "against": ["Con point"], "stands": "Draft out"}
    F = {"before": "Old rule", "after": "New rule", "effective": "1 Dec", "applies_to": "Cards only"}
    ed = seed_edition(session, [(1, "D", "Dee", D, {"chapter": 2}), (2, "E", "Eee", E, {}), (3, "F", "Eff", F, {})])
    html = render_edition(session, ed, tmp_path).read_text()
    for s in ("Ch one", "Fines land", "Pro point", "Con point", "Draft out",
              "Old rule", "New rule", "1 Dec", "Cards only", "Next edition", "Saturday morning, 31 October"):
        assert s in html
    assert html.count("</span>Update</span>") == 1  # the chapter-2 card carries the Update marker


def test_render_drops_unsafe_source_urls(session, tmp_path):
    ed = seed_edition(session, [(1, "A", "One", {}, {}), (2, "A", "Two", {}, {})])
    session.get(Item, "i0").url = "javascript:alert(1)"
    session.get(Item, "i1").url = "https://example.com/ok"
    session.flush()
    html = render_edition(session, ed, tmp_path).read_text()
    assert "href=\"javascript:" not in html and "Source title 0" in html
    assert 'href="https://example.com/ok"' in html
    v = edition_view(session, ed)
    assert v["cards"][0]["sources"][0]["url"] is None


def test_chart_bars_all_negative_stay_in_bounds():
    from newshouse.render_static import _chart
    bars = _chart({"series": [{"label": l, "value": v} for l, v in (("a", -5), ("b", -20), ("c", -1))]})["bars"]
    assert [b["w"] for b in bars] == [25, 100, 5] and all(0 <= b["w"] <= 100 for b in bars)
    assert [b["key"] for b in bars] == [False, True, False]


def test_render_validate_report_mode(session, tmp_path):
    long = "One two three four five six seven eight nine ten eleven twelve thirteen fourteen"
    ed = seed_edition(session, [(1, "A", long, {}, {})])
    render_edition(session, ed, tmp_path, validate=True, cfg=EditionConfig(), profile_text="",
                   banned=load_banned())
    longs = [w for w in ed.warnings if w["rule"] == "headline-long"]
    assert longs == [{"rule": "headline-long", "text": "headline has 14 words (max 12)",
                      "card_id": "card0"}]
    data = json.loads((tmp_path / "2026-10-30.json").read_text())
    assert data["warnings"] == ed.warnings
    assert edition_view(session, ed)["cards"][0]["headline"] == long  # report only: nothing rewritten


def test_edition_view_swaps_a_stored_reason_for_the_latest_title(session):
    ed = seed_edition(session, [(1, "A", "Normal", {}, {}), (2, "A", "Other", {}, {})],
                      also=[{"cluster_id": "c0", "rank": 1, "line": "Matters to Mihir's commute"},
                            {"cluster_id": "c1", "rank": 2, "line": "A written fact"}])
    session.get(Cluster, "c0").reason = "Matters to Mihir's commute"
    session.get(Cluster, "c1").reason = "other reason"
    session.get(Item, "i0").title = "Metro Line 2 extension opens - Hindustan Times"
    session.get(Source, "s1").kind = "gnews"
    session.flush()
    lines = [a["line"] for a in edition_view(session, ed)["also"]]
    assert lines == ["Metro Line 2 extension opens", "A written fact"]


def test_strip_outlet_only_for_gnews():
    assert strip_outlet("Kohli - the final chapter", gnews=False) == "Kohli - the final chapter"
    assert strip_outlet("RBI holds rates - Mint", gnews=True) == "RBI holds rates"
    assert strip_outlet("Metro opens - Hindustan Times", gnews=True) == "Metro opens"
    assert strip_outlet("Alphabet - Google split - Reuters", gnews=True) == "Alphabet - Google split"
    assert strip_outlet("No suffix here", gnews=True) == "No suffix here"
    long = "Story - " + "x" * 45
    assert strip_outlet(long, gnews=True) == long


def test_latest_title_keeps_the_dash_for_a_non_gnews_source(session):
    seed_edition(session, [(1, "A", "Normal", {}, {})])
    session.get(Item, "i0").title = "Kohli - the final chapter"
    session.flush()
    assert latest_title(session, "c0") == "Kohli - the final chapter"
