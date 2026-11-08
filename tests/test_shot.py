import importlib.util
from pathlib import Path

import pytest

from newshouse.render_static import render_edition
from tests.helpers import seed_edition

_spec = importlib.util.spec_from_file_location("shot", Path(__file__).resolve().parent.parent / "scripts" / "shot.py")
shot = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shot)

B = {"columns": ["Model", "Price", "Was"],
     "rows": [{"cells": ["Mine", "$1", "$2"], "yours": True, "new": False},
              {"cells": ["Shiny", "$2", "$3"], "yours": False, "new": True}]}
C = {"series": [{"label": "Q1", "value": 10, "item_id": "i1"}, {"label": "Q2", "value": 20, "item_id": "i1"},
                {"label": "Q3", "value": 15, "item_id": "i1"}], "unit": "$M", "caption": "Raised"}


def test_inject_and_parse_round_trip():
    out = shot.inject_checks("<html><body><p>x</p></body></html>")
    assert "NHCHECK:" in out and out.endswith("</script></body></html>")
    bare = shot.inject_checks("<p>x</p>")
    assert bare.startswith("<p>x</p><script>") and "NHCHECK:" in bare
    dom = ('<html><head><title>NHCHECK:{&quot;overflow&quot;:false,&quot;min_font&quot;:15,'
           '&quot;empty_visual&quot;:0,&quot;tallest_post&quot;:0.9}</title></head></html>')
    assert shot.parse_report(dom) == {"overflow": False, "min_font": 15, "empty_visual": 0, "tallest_post": 0.9}
    with pytest.raises(ValueError):
        shot.parse_report("<html><head><title>News House</title></head></html>")


@pytest.mark.skipif(shot.chrome_path() is None, reason="no Chrome")
def test_shoot_real_page(session, tmp_path):
    ed = seed_edition(session, [(1, "A", "Lead story", {}, {}), (2, "C", "Chart story", C, {}),
                                (3, "B", "Table story", B, {})])
    page = render_edition(session, ed, tmp_path / "out")
    shots = tmp_path / "shots"
    reports = shot.shoot(page, shots, chrome=shot.chrome_path(), sizes=[(390, 844), (1280, 800)])
    assert set(reports) == {"390x844", "1280x800"}
    for r in reports.values():
        assert r["overflow"] is False and r["min_font"] >= 11
        assert r["empty_visual"] == 0 and r["posts"] == 3
    for name in ("390x844.png", "1280x800.png"):
        assert (shots / name).stat().st_size > 10_000
    assert not list(page.parent.glob("_check-*")) and not list(page.parent.glob("_wrap-*"))


GOOD = {"overflow": False, "min_font": 12, "empty_visual": 0, "tallest_post": 0.9,
        "deck_slides": [4, 2], "slide_overflow": 0, "broken_photo": 0}


def test_failures_pass_a_clean_report():
    assert shot.failures(GOOD) == []


def test_failures_report_a_deck_outside_two_to_four():
    assert shot.failures({**GOOD, "deck_slides": [4, 1]}) == ["deck_slides"]
    assert shot.failures({**GOOD, "deck_slides": [5]}) == ["deck_slides"]


def test_failures_report_an_overflowing_slide():
    assert shot.failures({**GOOD, "slide_overflow": 1}) == ["slide_overflow"]


def test_failures_report_a_broken_visible_photo():
    assert shot.failures({**GOOD, "broken_photo": 1}) == ["broken_photo"]


def test_check_script_measures_decks_slides_and_photos():
    for needle in (".deck", ".slide", "scrollHeight", "clientHeight + 1", "img.photo", "naturalWidth === 0",
                   "deck_slides", "slide_overflow", "broken_photo"):
        assert needle in shot.CHECK_JS


def test_failures_report_a_visual_over_320px_at_phone_width():
    assert shot.failures({**GOOD, "viewport_w": 390, "tallest_visual": 321}) == ["tallest_visual"]
    assert shot.failures({**GOOD, "viewport_w": 430, "tallest_visual": 339.6}) == ["tallest_visual"]
    assert shot.failures({**GOOD, "viewport_w": 430, "tallest_visual": 320}) == []
    assert shot.failures({**GOOD, "viewport_w": 768, "tallest_visual": 400}) == []
    assert "tallest_visual" in shot.CHECK_JS and "viewport_w" in shot.CHECK_JS


def test_empty_visual_check_skips_unrendered_visuals():
    start = shot.CHECK_JS.index("var emptyVisual")
    block = shot.CHECK_JS[start:shot.CHECK_JS.index("emptyVisual++", start)]
    assert 'closest("[hidden]")' in block and "getClientRects().length === 0" in block


def test_parse_args_accepts_a_theme():
    a = shot.parse_args(["page.html", "out", "--theme", "dark"])
    assert (a.page, a.out_dir, a.theme, a.keep) == ("page.html", "out", "dark", False)
    assert shot.parse_args(["page.html", "out"]).theme is None
    with pytest.raises(SystemExit):
        shot.parse_args(["page.html", "out", "--theme", "sepia"])


def test_theme_goes_into_the_iframe_src_and_the_png_name():
    assert shot.frame_src("_check-390x844.html", "dark") == "_check-390x844.html?theme=dark"
    assert shot.frame_src("_check-390x844.html", None) == "_check-390x844.html"
    assert shot.png_name("390x844", "dark") == "390x844-dark.png"
    assert shot.png_name("390x844", "light") == "390x844-light.png"
    assert shot.png_name("390x844", None) == "390x844.png"
    assert "ground" in shot.CHECK_JS


@pytest.mark.skipif(shot.chrome_path() is None, reason="no Chrome")
def test_shoot_dark_paints_the_night_ground(session, tmp_path):
    ed = seed_edition(session, [(1, "A", "Lead story", {}, {}), (2, "C", "Chart story", C, {})])
    page = render_edition(session, ed, tmp_path / "out")
    shots = tmp_path / "shots"
    dark = shot.shoot(page, shots, chrome=shot.chrome_path(), sizes=[(390, 844)], theme="dark")
    light = shot.shoot(page, shots, chrome=shot.chrome_path(), sizes=[(390, 844)], theme="light")
    assert dark["390x844"]["ground"] == "rgb(20, 26, 22)"
    assert light["390x844"]["ground"] == "rgb(243, 238, 228)"
    assert (shots / "390x844-dark.png").stat().st_size > 10_000
    assert (shots / "390x844-light.png").stat().st_size > 10_000


def test_failures_report_a_stack_strip_over_320px_at_phone_width():
    assert shot.failures({**GOOD, "viewport_w": 390, "tallest_stack": 321}) == ["tallest_stack"]
    assert shot.failures({**GOOD, "viewport_w": 390, "tallest_stack": 320}) == []
    assert shot.failures({**GOOD, "viewport_w": 768, "tallest_stack": 400}) == []


def test_check_script_measures_the_stack_strip():
    for needle in (".stack", "tallest_stack", "more.hidden = false"):
        assert needle in shot.CHECK_JS
