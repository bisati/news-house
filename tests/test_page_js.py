from importlib import resources

from newshouse.render_static import render_edition
from tests.helpers import seed_edition

MOTION = "@media (prefers-reduced-motion: no-preference)"


def test_js_inlined_with_named_behaviours(session, tmp_path):
    ed = seed_edition(session, [(1, "A", "Lead story", {}, {})])
    html = render_edition(session, ed, tmp_path / "out").read_text()
    script = html[html.rindex("<script>"):html.rindex("</script>")]
    for name in ("expand", "send", "flush", "retryable", "observeSeen", "restoreSeen", "saveSeen",
                 "reactions", "motion", "photoFallback", "decks", "liveTiles", "theme"):
        assert f"function {name}(" in script
    assert "prefers-reduced-motion" in script and "nh.queue" in script
    assert "QUEUE_MAX = 500" in script and '"nh.seen." +' in script


def _strip_block(css, opener):
    start = css.index(opener)
    depth, i = 0, css.index("{", start)
    while True:
        depth += {"{": 1, "}": -1}.get(css[i], 0)
        if depth == 0:
            return css[:start] + css[i + 1:], css[start:i + 1]
        i += 1


def test_css_motion_is_gated():
    css = resources.files("newshouse").joinpath("static/edition.css").read_text()
    assert css.count(MOTION) == 1
    outside, block = _strip_block(css, MOTION)
    assert outside.count("transition") == 0 and outside.count("animation") == 0
    assert "transition" in block and ".post.in" in block


def test_css_snaps_slides_outside_the_motion_block():
    css = resources.files("newshouse").joinpath("static/edition.css").read_text()
    outside, block = _strip_block(css, MOTION)
    assert "scroll-snap-type" in outside and "scroll-snap-type" not in block
    assert "max-height" not in css
    assert ".slide-dots" in block and "width" not in block.split(".slide-dots", 1)[1].split("}", 1)[0]


def test_expand_motion_and_chevron_rotation():
    css = resources.files("newshouse").joinpath("static/edition.css").read_text()
    outside, block = _strip_block(css, MOTION)
    assert "rotate(" in outside and "rotate(" not in block
    assert ".expand svg" in block and "transition: transform" in block.split(".expand svg", 1)[1].split("}", 1)[0]
    assert ".more" in block and "animation" in block
    assert "max-height" not in css


def test_head_keys_leave_inner_buttons_alone_and_collapse_refocuses():
    js = resources.files("newshouse").joinpath("static/edition.js").read_text()
    head = js.split('head.addEventListener("keydown"', 1)[1].split("});", 1)[0]
    assert "ev.target !== head" in head and head.index("ev.target !== head") < head.index("preventDefault")
    hc = js.split("headCollapse.addEventListener", 1)[1].split("});", 1)[0]
    assert "btn.focus()" in hc


def test_decks_hides_chevrons_at_the_ends():
    js = resources.files("newshouse").joinpath("static/edition.js").read_text()
    fn = js.split("function decks(", 1)[1].split("\n  flush();", 1)[0]
    assert "prev.hidden = i === 0" in fn and "next.hidden = i === n - 1" in fn
    assert ".disabled" not in fn


def test_chevrons_are_faded_and_boxless():
    css = resources.files("newshouse").joinpath("static/edition.css").read_text()
    rule = css.split(".slide-prev, .slide-next {", 1)[1].split("}", 1)[0]
    assert "opacity: 0.55" in rule and "position: absolute" in rule


def test_live_tiles_refresh_every_half_hour_while_visible():
    js = resources.files("newshouse").joinpath("static/edition.js").read_text()
    live = js.split("function liveTiles(", 1)[1]
    assert "30 * 60 * 1000" in live and "visibilityState" in live and "data-src" in live
    assert "Asia/Kolkata" in live and "data.hourly" in live and "< 12" in live and "liveTiles();" in js.split("function liveTiles(", 1)[1]


NIGHT_HEXES = ("#141A16", "#1C2620", "#F3EEE4", "#D7E4DB", "#2E3A33", "#9DB5A6")
DARK_MQ = "@media (prefers-color-scheme: dark)"
SYS = ':root:not([data-theme="light"])'
FORCED = ':root[data-theme="dark"]'


def _night_block(css):
    """The night rules (keyed on data-theme="dark")."""
    return css[css.index("/* night: forced */"):css.index("/* night: end */")]


def test_css_night_palette_is_opt_in():
    """Light by default (2026-11-06): no system media query, one night block keyed on the
    data-theme the masthead switch sets."""
    css = resources.files("newshouse").joinpath("static/edition.css").read_text()
    assert DARK_MQ not in css
    forced = _night_block(css)
    for hexv in NIGHT_HEXES:
        assert hexv in forced
    rule = forced.split(" .post {", 1)[1].split("}", 1)[0]
    for k in ("fill", "ink", "panel", "accent", "cover-fill", "hi-fill"):
        assert f"--{k}: var(--d-{k});" in rule
    assert "!important" not in forced
    # the one world rule by night: a good-news pitch goes back to the post's panel
    assert forced.count("data-world") == 1 and '.post[data-world="mint"] .visual[data-kind="pitch"]' in forced
    day = css[:css.index("/* night: forced */")]
    assert "--fill: var(--l-fill);" in day.split(".post {", 1)[1].split("}", 1)[0]


def test_theme_switch_and_head_script(session, tmp_path):
    import re
    ed = seed_edition(session, [(1, "A", "Lead story", {}, {})])
    html = render_edition(session, ed, tmp_path / "out").read_text()
    head = html[:html.index("</head>")]
    assert 'localStorage.getItem("nh.theme")' in head and 'setAttribute("data-theme", "dark")' in head
    sw = re.search(r'<button[^>]*class="theme-toggle"[^>]*>', html).group(0)
    assert 'role="switch"' in sw and 'aria-checked="false"' in sw and 'aria-label="Dark theme"' in sw
    js = resources.files("newshouse").joinpath("static/edition.js").read_text()
    fn = js.split("function theme(", 1)[1].split("\n  }\n", 1)[0]
    assert 'localStorage.setItem(THEME_KEY' in fn and 'removeAttribute("data-theme")' in fn


def test_theme_reads_the_url_override():
    js = resources.files("newshouse").joinpath("static/edition.js").read_text()
    fn = js.split("function theme(", 1)[1].split("\n  }\n", 1)[0]
    assert "URLSearchParams" in fn and '"theme"' in fn and 'setAttribute("data-theme"' in fn
    assert '"dark"' in fn and '"light"' in fn
    init = js.split("\n  flush();", 1)[0].rsplit("\n", 1)[0]
    assert js.index("  theme();") < js.index("\n  flush();")


def _deck_show():
    js = resources.files("newshouse").joinpath("static/edition.js").read_text()
    fn = js.split("function decks(", 1)[1].split("\n  flush();", 1)[0]
    return fn.split("function show(i) {", 1)[1].split("\n      }\n", 1)[0]


def test_deck_takes_the_current_slides_fill_not_its_style():
    show = _deck_show()
    assert 'deck.setAttribute("data-fill", slides[i].getAttribute("data-fill"))' in show
    assert 'setAttribute("style"' not in show


def test_chevron_ink_follows_the_deck_fill():
    css = resources.files("newshouse").joinpath("static/edition.css").read_text()
    rule = css.split(".slide-prev, .slide-next {", 1)[1].split("}", 1)[0]
    assert "color: var(--chev-ink)" in rule and "--slide-ink" not in rule
    assert "outline: 2px solid var(--chev-ink)" in css
    assert ".deck { position: relative; --chev-ink: var(--ink); }" in css
    assert '.deck[data-fill="hi"] { --chev-ink: var(--on-hi); }' in css


def test_chevron_glyphs_sit_in_the_gutter():
    css = resources.files("newshouse").joinpath("static/edition.css").read_text()
    assert ".slide-prev { left: -12px; }" in css and ".slide-next { right: -12px; }" in css
    rule = css.split(".slide-prev, .slide-next {", 1)[1].split("}", 1)[0]
    assert "width: 44px" in rule and "height: 44px" in rule


def test_chevron_hands_focus_on_before_hiding():
    show = _deck_show()
    assert "document.activeElement" in show and ".focus()" in show
    assert show.index(".focus()") < show.index("prev.hidden =")
    assert show.index(".focus()") < show.index("next.hidden =")


def test_should_have_shows_noted_and_restores():
    js = resources.files("newshouse").joinpath("static/edition.js").read_text()
    assert "function restoreShouldHave(" in js and "restoreShouldHave();" in js
    assert '"nh-should-have"' in js and "Noted \\u2713" in js
    handler = js.split("function reactions(", 1)[1].split('"button.should-have", function (btn) {', 1)[1].split("each(document", 1)[0]
    assert "markNoted(" in handler and "saveShouldHave(" in handler
    css = resources.files("newshouse").joinpath("static/edition.css").read_text()
    rule = css.split('.should-have[aria-pressed="true"] {', 1)[1].split("}", 1)[0]
    assert "text-decoration: none" in rule and "color: var(--forest)" in rule
