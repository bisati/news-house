import json
import re
from importlib import resources

from newshouse.render_static import render_edition
from newshouse.models import Cluster
from tests.helpers import NOW, seed_edition

B = {"columns": ["Model", "Price", "Was"],
     "rows": [{"cells": ["Mine", "$1", "$2"], "yours": True, "new": False},
              {"cells": ["Shiny", "$2", "$3"], "yours": False, "new": True}]}
C = {"series": [{"label": "Q1", "value": 10, "item_id": "i1"}, {"label": "Q2", "value": 20, "item_id": "i1"},
                {"label": "Q3", "value": 15, "item_id": "i1"}], "unit": "$M", "caption": "Raised"}
D = {"chapters": [{"title": "Ch one", "date": "Mar 2024", "read": True}], "delta": "Fines land"}
E = {"for": ["Pro point"], "against": ["Con point"], "stands": "Draft out"}


def _render(session, tmp_path, specs, **kw):
    ed = seed_edition(session, specs, **kw)
    out = tmp_path / "out"
    return render_edition(session, ed, out).read_text(), out


def test_render_posts_and_worlds(session, tmp_path):
    html, out = _render(session, tmp_path, [(1, "A", "Lead story", {}, {}), (2, "C", "Chart story", C, {}),
                                            (3, "B", "Table story", B, {}), (4, "D", "Thread story", D, {"chapter": 2}),
                                            (5, "E", "Split story", E, {})])
    assert html.count('class="post"') == 5
    first = html.index('class="post"')
    assert 'data-world="forest"' in html[first:html.index(">", first)]
    for kind in ("cover", "chart", "table", "timeline", "versus"):
        assert f'data-kind="{kind}"' in html
    assert html.count('class="bar-row"') == 3 * 2  # collapsed chart plus the structured copy
    assert 'style="--w: 100%"' in html and 'style="--w: 50%"' in html
    assert "fonts.googleapis" not in html and '<link rel="stylesheet"' not in html
    assert "@font-face" in html and "--forest: #12372A" in html and html.count("<script>") == 2  # the head theme script and the page script
    assert (out / "fonts" / "fraunces-latin.woff2").exists()


def test_why_block_only_when_present(session, tmp_path):
    html, _ = _render(session, tmp_path, [(1, "A", "No why", {}, {"why": ""}),
                                          (2, "A", "With why", {}, {"why": "You run Gemini"})])
    assert html.count('class="why"') == 1 and "You run Gemini" in html


def test_plain_card_has_no_visual(session, tmp_path):
    html, _ = _render(session, tmp_path, [(1, "A", "Alphabet loses $500 billion in a day", {}, {})])
    assert 'class="visual"' not in html.split("<body", 1)[1]
    assert "Alphabet loses $500 billion in a day" in html


def test_also_shows_cut_reason_and_hidden_rest(session, tmp_path):
    session.add_all([Cluster(id=f"x{n}", window_start=NOW, topics=["ai-models"], chapter=0) for n in range(1, 7)])
    also = [{"cluster_id": f"x{n}", "rank": n, "line": f"Also line {n}",
             "cut_reason": "cap ai-models" if n == 2 else None} for n in range(1, 7)]
    html, _ = _render(session, tmp_path, [(1, "A", "Only story", {}, {})], also=also)
    section = html[html.index('<section class="also"'):html.index("</section>", html.index('<section class="also"'))]
    assert section.count("<li") == 6 and len(re.findall(r"<li[^>]* hidden>", section)) == 2
    assert section.count("--l-accent:#3B2C7A") == 6  # each line's number in its topic's ink
    assert section.count('class="cut"') == 1 and "cut: cap ai-models" in section
    assert section.count('class="should-have"') == 6 and 'data-cluster-id="x3"' in section
    assert 'class="also-more"' in section and "Show 2 more" in section


def test_render_empty_edition(session, tmp_path):
    html, _ = _render(session, tmp_path, [])
    assert "0 posts · 0 min" in html and 'class="post"' not in html
    assert '<section class="end"' in html and "That's today" in html
    assert "Saturday morning, 31 October" in html
    assert '<section class="also"' not in html and 'class="warnings"' not in html


def test_json_has_no_template_extras(session, tmp_path):
    _, out = _render(session, tmp_path, [(1, "C", "Chart story", C, {"tone": "good"})])
    card = json.loads((out / "2026-10-30.json").read_text())["cards"][0]
    assert "world" not in card and "vis" not in card and "read_time" not in card
    assert card["tone"] == "good" and card["visual"] == "none" and card["slides"] == []


def test_lead_marker_survives_breaking_first(session, tmp_path):
    html, _ = _render(session, tmp_path, [(0, "A", "Breaking story", {}, {"breaking": True}),
                                          (1, "A", "Lead story", {}, {})])
    lead = html.index('data-card-id="card1"')
    head = html[html.rindex("<article", 0, lead):html.index("</article>", lead)]
    assert 'data-world="forest"' in head and "Lead · 1 min" in head
    assert html.count("Lead ·") == 1


def test_only_two_breaking_cards_get_the_tomato_bar(session, tmp_path):
    specs = [(n, "A", f"Breaking {n}", {}, {"breaking": True}) for n in range(3)] + [(3, "A", "Lead", {}, {})]
    html, _ = _render(session, tmp_path, specs)
    body = html.split("<body", 1)[1]
    assert body.count('data-breaking="true"') == 2
    third = _post(html, "card2")
    assert 'data-breaking' not in third.split(">", 1)[0] and ">Update</span>" in third
    assert "Lead ·" in _post(html, "card3")


def test_react_unselected_and_caption_below_bars(session, tmp_path):
    D2 = {"chapters": [{"title": "Ch one", "date": "2026-10-28", "read": True}], "delta": "Fines land"}
    html, _ = _render(session, tmp_path, [(1, "C", "Chart story", C, {}), (2, "D", "Thread", D2, {"chapter": 2})])
    assert "filled" not in html and 'class="panel-title"' not in html
    bars_end = html.rindex('class="bar-row"', 0, html.index('class="more"'))
    assert html.index('<p class="caption">Raised</p>', bars_end) < html.index('class="more"')
    assert ">28 Oct<" in html and "2026-10-28" not in html


def test_body_carries_feedback_hooks(session, tmp_path):
    html, _ = _render(session, tmp_path, [(1, "A", "Lead story", {}, {})])
    body = html[html.index("<body"):html.index(">", html.index("<body"))]
    assert 'data-feedback-url="/feedback"' in body and 'data-edition-id="e1"' in body


def test_index_lists_built_editions_newest_first(session, tmp_path):
    from datetime import date
    from newshouse.models import Card, Edition
    ed = seed_edition(session, [(1, "A", "Lead story", {}, {})])  # 2026-10-30, built
    older = Edition(id="e0", date=date(2026, 10, 29), built_at=NOW, budget_seconds=900, cut_score=40.0)
    unbuilt = Edition(id="e2", date=date(2026, 10, 31), built_at=None, budget_seconds=900, cut_score=40.0)
    session.add_all([older, unbuilt])
    session.flush()
    session.add(Card(id="old1", edition_id="e0", rank=1, cluster_id="c0", format="A", payload={},
                     headline="Old", line="l", para="p", brief="b", why="w", est_seconds=120,
                     cited_item_ids=["i0"]))
    session.flush()
    out = tmp_path / "out"
    render_edition(session, ed, out)
    html = (out / "index.html").read_text()
    assert html.index("2026-10-30.html") < html.index("2026-10-29.html")
    assert "2026-10-31.html" not in html
    assert "Friday 30 October 2026" in html
    assert "1 post · 1 min" in html and "1 post · 2 min" in html


def test_index_follows_the_night_palette(session, tmp_path):
    ed = seed_edition(session, [(1, "A", "Lead story", {}, {})])
    out = tmp_path / "out"
    render_edition(session, ed, out)
    html = (out / "index.html").read_text()
    assert '@media (prefers-color-scheme: dark)' not in html and ':root[data-theme="dark"]' in html
    style = html.split("</style>", 1)[0].rsplit(".archive a", 1)[1].split("}", 1)[0]
    assert "background: var(--post)" in style and "#fff" not in style
    assert 'URLSearchParams' in html and 'setAttribute("data-theme"' in html and '"nh.theme"' in html


def test_breaking_post_is_marked_for_its_tomato_header(session, tmp_path):
    html, _ = _render(session, tmp_path, [(0, "A", "Breaking story", {}, {"breaking": True}),
                                          (1, "A", "Lead story", {}, {})])
    brk = html.index('data-card-id="card0"')
    lead = html.index('data-card-id="card1"')
    assert 'data-breaking="true"' in html[brk:html.index(">", brk)]
    assert 'data-breaking' not in html[lead:html.index(">", lead)]
    assert len(re.findall(r"<article[^>]*data-breaking=\"true\"", html)) == 1
    assert '.post[data-breaking="true"] .post-head' in html


def test_masthead_links_to_archive(session, tmp_path):
    html, _ = _render(session, tmp_path, [(1, "A", "Lead story", {}, {})])
    mast = html[html.index('<header class="masthead"'):html.index("</header>")]
    assert 'href="index.html"' in mast and ">Archive<" in mast


def test_legacy_formats_render_as_before(session, tmp_path):
    specs = [(1, "A", "Plain story", {}, {"visual": "cover"}), (2, "B", "Table story", B, {"visual": "cover"}),
             (3, "C", "Chart story", C, {"visual": "cover"}), (4, "D", "Thread story", D, {"visual": "cover", "chapter": 2}),
             (5, "E", "Versus story", E, {"visual": "cover"}),
             (6, "F", "Before story", {"before": {"label": "Was", "text": "a"}, "after": {"label": "Now", "text": "b"}},
              {"visual": "cover"})]
    html, _ = _render(session, tmp_path, specs)
    assert re.findall(r'class="visual" data-kind="([\w-]+)"', html.split("<body", 1)[1])[:5] == [
        "table", "chart", "timeline", "versus", "before-after"]  # the plain A card has no visual


def test_json_has_visual_and_slides(session, tmp_path):
    slides = [{"kind": "cover", "title": "", "body": "", "payload": {"big": "5%", "label": "x", "line": "y"}},
              {"kind": "text", "title": "Why", "body": "Because.", "payload": {}}]
    _, out = _render(session, tmp_path, [(1, "A", "Deck story", {}, {"visual": "quote", "slides": slides})])
    card = json.loads((out / "2026-10-30.json").read_text())["cards"][0]
    assert card["visual"] == "quote" and card["slides"] == slides
    assert "deck" not in card and "style" not in card


def test_quote_renders(session, tmp_path):
    p = {"text": "We will build it here.", "who": "Jane Roe", "where": "Reuters interview", "item_id": "i0"}
    html, _ = _render(session, tmp_path, [(1, "A", "Quote story", p, {"visual": "quote"})])
    vis = html[html.index('<div class="visual" data-kind="quote"'):html.index('<h2 class="headline">')]
    assert "<blockquote" in vis and "We will build it here." in vis
    assert 'class="who"' in vis and "Jane Roe" in vis and "Reuters interview" in vis


def test_photo_renders_with_hidden_cover_fallback(session, tmp_path):
    from newshouse.models import Item
    p = {"item_id": "i0", "alt": "A stadium", "credit": "Reuters"}
    ed = seed_edition(session, [(1, "A", "Photo story", p, {"visual": "photo"})])
    session.get(Item, "i0").image_url = "https://img.example/a.jpg"
    session.flush()
    html = render_edition(session, ed, tmp_path / "out").read_text()
    vis = html[html.index('<div class="visual" data-kind="photo"'):html.index('<h2 class="headline">')]
    assert re.search(r'<img[^>]*class="photo"[^>]*src="https://img.example/a.jpg"', vis) or \
        re.search(r'<img[^>]*src="https://img.example/a.jpg"[^>]*class="photo"', vis)
    assert 'referrerpolicy="no-referrer"' in vis and 'alt="A stadium"' in vis
    assert "Reuters" in vis and 'class="credit"' in vis
    assert re.search(r'data-kind="cover"[^>]*\bhidden\b', vis)
    assert "<h2" not in vis  # the headline sits below the visual (the hidden cover only echoes it)


def test_pitch_renders_rows_back_to_front(session, tmp_path):
    p = {"rows": [[{"pos": "LB", "name": "Balde"}, {"pos": "CB", "name": "Cubarsi"}],
                  [{"pos": "ST", "name": "Lewandowski"}]],
         "note": "4-3-3 at home", "out": [{"name": "Kounde", "why": "ankle"}]}
    ed = seed_edition(session, [(0, "A", "Lead story", {}, {}), (1, "A", "Barcelona line-up", p, {"visual": "pitch"})])
    session.get(Cluster, "c1").topics = ["football"]
    session.flush()
    html = render_edition(session, ed, tmp_path / "out").read_text()
    start = html.index('<div class="visual" data-kind="pitch"')
    vis = html[start:html.index('class="gist"', start)]  # a pitch is headline first: the gist follows it
    assert vis.index("Lewandowski") < vis.index("Balde") < vis.index("Cubarsi")
    assert vis.count('class="pitch-row"') == 2
    assert 'Kounde</span><span class="out-why">&nbsp;· ankle' in vis and "4-3-3 at home" in vis
    style = html[html.index('data-card-id="card1"'):]
    style = style[:style.index(">")]
    assert "--l-accent:#A50044" in style and "--secondary:#004D98" in style


def _card_style(html, cid):
    tag = html[html.index(f'data-card-id="{cid}"'):]
    return tag[:tag.index(">")]


def test_pitch_disc_text_colour_follows_world(session, tmp_path):
    p = {"rows": [[{"pos": "CB", "name": "Cubarsi"}]], "note": "", "out": []}
    specs = [(0, "A", "Lead story", {}, {}), (1, "A", "Plain line-up", p, {"visual": "pitch"}),
             (2, "A", "Barcelona line-up", p, {"visual": "pitch"})]
    ed = seed_edition(session, specs)
    session.get(Cluster, "c1").topics = ["misc"]
    session.get(Cluster, "c2").topics = ["football"]
    session.flush()
    html = render_edition(session, ed, tmp_path / "out").read_text()
    # a topic with no family gets neutral marks with white letters; Barça gets its kit
    assert "--l-accent:#5B6A61" in _card_style(html, "card1") and "--l-on-accent:#FFFFFF" in _card_style(html, "card1")
    assert "--l-accent:#A50044" in _card_style(html, "card2") and "--l-on-accent:#FFFFFF" in _card_style(html, "card2")


def test_pitch_is_bounded(session, tmp_path):
    rows = [[{"pos": "P", "name": f"Player{i}"}] for i in range(6)]
    p = {"rows": rows, "note": "n", "out": [{"name": f"Out{i}", "why": "x"} for i in range(5)]}
    ed = seed_edition(session, [(1, "A", "Big line-up", p, {"visual": "pitch"})])
    html = render_edition(session, ed, tmp_path / "out").read_text()
    start = html.index('<div class="visual" data-kind="pitch"')
    vis = html[start:html.index('class="gist"', start)]  # a pitch is headline first: the gist follows it
    assert vis.count('class="pitch-row"') == 4 and vis.count("<li>") == 3
    assert "Player3" in vis and "Player4" not in vis


DECK_COVER = {"kind": "cover", "title": "", "body": "", "payload": {"big": "-13%", "label": "Q3 2026", "line": "Worst day."}}


def _post(html, cid):
    start = html.index(f'data-card-id="{cid}"')
    return html[html.rindex("<article", 0, start):html.index("</article>", start)]


def test_deck_renders_slides_and_controls(session, tmp_path):
    slides = [DECK_COVER,
              {"kind": "table", "title": "The miss", "body": "", "payload": B},
              {"kind": "text", "title": "The damage", "body": "Half a trillion gone.", "payload": {}}]
    html, _ = _render(session, tmp_path, [(1, "A", "Deck story", {}, {"slides": slides})])
    post = _post(html, "card0")
    assert post.count('<section class="slide"') == 3
    track = post[post.index('class="slides"'):]
    track = track[:track.index(">")]
    assert 'role="group"' in track and 'aria-roledescription="carousel"' in track
    assert 'aria-label="Deck story"' in track
    assert re.findall(r'<section class="slide"[^>]*data-fill="(\w+)"', post) == ["cover", "plain", "plain"]
    assert re.findall(r'<section class="slide"[^>]*data-slide-kind="([\w-]+)"', post) == ["cover", "table", "text"]
    assert 'aria-label="1 of 3"' in post and 'aria-label="3 of 3"' in post
    assert re.search(r'<button[^>]*class="slide-prev"[^>]*aria-label="Previous slide"', post)
    assert re.search(r'<button[^>]*class="slide-next"[^>]*aria-label="Next slide"', post)
    dots = post[post.index('class="slide-dots"'):]
    dots = dots[:dots.index("</span></span>") + 7]
    assert dots.count("<span") == 3 and dots.count('class="on"') == 1
    assert '<span class="slide-count" aria-live="polite">1 / 3</span>' in post
    assert 'class="visual"' not in post[:post.index('<h2 class="headline">')]
    assert "-13%" in post and "The miss" in post and "$1" in post
    assert '<p class="gist">Line 0</p>' in post  # a deck post keeps its gist


def test_deck_chevrons_and_dots_markup(session, tmp_path):
    slides = [DECK_COVER,
              {"kind": "table", "title": "The miss", "body": "", "payload": B},
              {"kind": "text", "title": "The damage", "body": "Half a trillion gone.", "payload": {}}]
    html, _ = _render(session, tmp_path, [(1, "A", "Deck story", {}, {"slides": slides})])
    post = _post(html, "card0")
    deck = post[post.index('<div class="deck">'):]
    after = deck[deck.index("</div>", deck.index('class="slides"')):]
    # prev/next sit after .slides inside the deck, then .slide-meta is the deck's last child
    assert after.index("slide-prev") < after.index("slide-next") < after.index('class="slide-meta"')
    meta = post[post.index('<div class="slide-meta">'):]
    meta = meta[:meta.index("</div>") + 6]
    assert meta.count('class="on"') == 1 and meta.count("<span") == 5
    assert '<span class="slide-count" aria-live="polite">1 / 3</span>' in meta
    assert post.index("</div>", post.index('class="slide-meta"')) < post.index('class="post-foot"')
    assert meta.strip().endswith("</div>")
    foot = post[post.index('class="post-foot"'):]
    for needle in ("slide-prev", "slide-next", "slide-dots", "slide-count"):
        assert needle not in foot
    prev = re.search(r'<button[^>]*class="slide-prev"[^>]*>', post).group(0)
    nxt = re.search(r'<button[^>]*class="slide-next"[^>]*>', post).group(0)
    assert re.search(r"\bhidden\b", prev) and not re.search(r"\bhidden\b", nxt)
    assert "disabled" not in prev
    css = resources.files("newshouse").joinpath("static/edition.css").read_text()
    for m in re.finditer(r"([^{}]*\.slide-(?:prev|next)[^{}]*)\{([^}]*)\}", css):
        for prop in re.findall(r"(?:^|[;\s])(border|background)\s*:\s*([^;]+)", m.group(2)):
            assert prop[1].strip() in ("none", "transparent", "0"), (m.group(1), prop)


def test_photo_loads_eagerly(session, tmp_path):
    from newshouse.models import Item
    p = {"item_id": "i0", "alt": "A stadium", "credit": "Reuters"}
    ed = seed_edition(session, [(1, "A", "Photo story", p, {"visual": "photo"})])
    session.get(Item, "i0").image_url = "https://img.example/a.jpg"
    session.flush()
    html = render_edition(session, ed, tmp_path / "out").read_text()
    img = re.search(r'<img[^>]*class="photo"[^>]*>', html).group(0)
    assert "lazy" not in img


def test_deck_text_and_what_next_slides(session, tmp_path):
    slides = [DECK_COVER,
              {"kind": "text", "title": "Why it fell", "body": "Search is hurting.", "payload": {}},
              {"kind": "what-next", "title": "What next", "body": "Capex rises.\n\nThe Q4 call explains.", "payload": {}}]
    html, _ = _render(session, tmp_path, [(1, "A", "Deck story", {}, {"slides": slides})])
    post = _post(html, "card0")
    text = post[post.index('data-slide-kind="text"'):post.index('data-slide-kind="what-next"')]
    assert "Why it fell" in text and "<p>Search is hurting.</p>" in text
    nxt = post[post.index('data-slide-kind="what-next"'):]
    nxt = nxt[:nxt.index("</section>")]
    assert "What next" in nxt and nxt.count("<p>") == 2
    assert "<p>Capex rises.</p>" in nxt and "<p>The Q4 call explains.</p>" in nxt
    assert "Expand for the full brief" in nxt


def test_post_without_slides_has_no_deck_controls(session, tmp_path):
    html, _ = _render(session, tmp_path, [(1, "A", "Plain story", {}, {})])
    post = _post(html, "card0")
    for cls in ('class="deck"', 'class="slides"', 'class="slide"', "slide-prev", "slide-next",
                "slide-dots", "slide-count"):
        assert cls not in post


def test_head_collapse_button(session, tmp_path):
    html, _ = _render(session, tmp_path, [(1, "A", "Lead story", {}, {}), (2, "B", "Second", {}, {})])
    posts = re.findall(r'<article class="post".*?</article>', html, re.S)
    assert posts
    for p in posts:
        head = p.split('<div class="post-head">', 1)[1].split("</div>", 1)[0]
        m = re.search(r'<button[^>]*class="head-collapse"[^>]*>', head)
        assert m and " hidden" in m.group(0)
        assert 'aria-label="Collapse"' in m.group(0)
        cid = re.search(r'id="more-([^"]+)"', p).group(1)
        assert f'aria-controls="more-{cid}"' in m.group(0)


def test_deck_slide_count_is_live(session, tmp_path):
    slides = [DECK_COVER, {"kind": "text", "title": "T", "body": "b", "payload": {}}]
    html, _ = _render(session, tmp_path, [(1, "A", "Deck story", {}, {"slides": slides})])
    found = re.findall(r'<span class="slide-count"[^>]*>', html)
    assert found
    for m in found:
        assert 'aria-live="polite"' in m


def test_deck_keys_ignore_modifiers():
    from importlib import resources
    js = resources.files("newshouse").joinpath("static/edition.js").read_text()
    seg = js.split('ev.key !== "ArrowLeft"', 1)[0].rsplit("addEventListener", 1)[1]
    assert "altKey" in seg and "metaKey" in seg and "ctrlKey" in seg


def _css():
    from importlib import resources
    return resources.files("newshouse").joinpath("static/edition.css").read_text()


def test_pitch_sits_on_the_post_panel():
    css = _css()
    assert '.visual[data-kind="pitch"] { --pitch-panel: var(--panel);' in css
    # labels sit on the panel colour, so the centre circle never runs through a name
    assert "background: var(--pitch-panel)" in css[css.index(".pname {"):]


def test_out_chips_stay_on_one_line_and_big_words_keep_apart():
    css = _css()
    out = css[css.index(".out {"):]
    assert "flex-wrap: nowrap" in out[:out.index("}")]
    assert ".out-name { flex: none; }" in css  # the name always shows; the reason takes the ellipsis
    big = css[css.index("\n.big {"):]
    assert "word-spacing:" in big[:big.index("}")]


def test_photo_shows_when_any_source_is_not_google_news(session, tmp_path):
    """Final review, Minor 3: the page and the writer use one photo rule (any non-gnews source)."""
    from sqlalchemy import select
    from newshouse.models import Item, ItemSource, Source
    from newshouse.write import _image
    p = {"item_id": "i0", "alt": "A stadium", "credit": "Reuters"}
    ed = seed_edition(session, [(1, "A", "Photo story", p, {"visual": "photo"})])
    session.get(Source, "s1").kind = "gnews"  # s1 sorts first
    session.add(Source(id="s2", name="Reuters", topics=["ai"], tier="mainstream", kind="rss",
                       url="https://feeds/s2", paywall=False))
    session.flush()
    session.add(ItemSource(item_id="i0", source_id="s2"))
    item = session.get(Item, "i0")
    item.image_url = "https://img.example/a.jpg"
    session.flush()
    sbi = {"i0": [session.get(Source, "s1"), session.get(Source, "s2")]}
    assert _image(item, sbi) == "https://img.example/a.jpg"  # the writer is offered the photo
    html = render_edition(session, ed, tmp_path / "out").read_text()
    assert '<div class="visual" data-kind="photo"' in html  # and the page shows it

    session.delete(session.scalars(select(ItemSource).where(
        ItemSource.item_id == "i0", ItemSource.source_id == "s2")).one())
    session.flush()
    assert _image(item, {"i0": [session.get(Source, "s1")]}) is None
    html = render_edition(session, ed, tmp_path / "out2").read_text()
    assert '<div class="visual" data-kind="photo"' not in html


def _table(n):
    return {"columns": ["Year", "Revenue"],
            "rows": [{"cells": [f"FY{i}", f"₹{i}Cr"], "yours": False, "new": False} for i in range(n)]}


def _row_count(fragment):
    return len(re.findall(r'<div class="row[ "]', fragment))


def test_table_visual_caps_collapsed_rows_at_three(session, tmp_path):
    html, _ = _render(session, tmp_path, [(1, "B", "Six row table", _table(6), {})])
    start = html.index('<div class="visual" data-kind="table">')
    split = html.index('<div class="more"', start)
    visual, more = html[start:split], html[split:]
    assert _row_count(visual) == 3
    assert visual.count("+3 more rows in Expand") == 1 and 'class="rows-more"' in visual
    assert _row_count(more) == 6 and "more rows in Expand" not in more


def test_table_visual_with_three_rows_has_no_more_line(session, tmp_path):
    html, _ = _render(session, tmp_path, [(1, "B", "Three row table", _table(3), {})])
    assert "more rows in Expand" not in html and 'class="rows-more"' not in html
    assert _row_count(html) == 6


def test_long_quote_gets_the_smaller_size(session, tmp_path):
    long_text = "We will build it here and nowhere else. " * 4
    p = {"text": long_text.strip(), "who": "A. Person", "where": "", "item_id": "i1"}
    html, _ = _render(session, tmp_path, [(1, "A", "Long quote", p, {"visual": "quote"})])
    assert '<blockquote class="long">' in html


def test_short_quote_keeps_the_default_size(session, tmp_path):
    p = {"text": "We will build it here.", "who": "Jane Roe", "where": "", "item_id": "i0"}
    html, _ = _render(session, tmp_path, [(1, "A", "Short quote", p, {"visual": "quote"})])
    assert "<blockquote>" in html and 'blockquote class="long"' not in html


def test_folded_rows_render_as_one_line_per_topic(session, tmp_path):
    session.add_all([Cluster(id="y1", window_start=NOW, topics=["ai-models"], chapter=0),
                     Cluster(id="y2", window_start=NOW, topics=["movies"], chapter=0)]
                    + [Cluster(id=f"g{n}", window_start=NOW, topics=["gurgaon-local", "india-news"],
                               chapter=0) for n in range(1, 4)])
    also = [{"cluster_id": "y1", "rank": 1, "line": "Plain one", "cut_reason": None},
            {"cluster_id": "y2", "rank": 2, "line": "Plain two", "cut_reason": "budget"}]
    also += [{"cluster_id": f"g{n}", "rank": 2 + n, "line": f"Smog report {n}", "folded": True,
              "is_top": True, "cut_reason": "topic cap gurgaon-local (3)"} for n in range(1, 4)]
    html, out = _render(session, tmp_path, [(1, "A", "Only story", {}, {})], also=also)
    start = html.index('<section class="also"')
    section = html[start:html.index("</section>", start)]
    assert section.count("+3 more Gurgaon stories cut by the topic cap") == 1
    assert section.count('class="also-n"') == 2 and "Show" not in section  # unfolded as today
    assert "cut: budget" in section
    fold = section[section.index('class="also-fold"'):]
    assert re.search(r'<ol class="also-folded-list"[^>]*hidden', fold)
    for n in range(1, 4):
        assert f"Smog report {n}" in fold and f'data-cluster-id="g{n}"' in fold
    assert section.index("Plain two") < section.index("Smog report 1")
    end = html[html.index('<section class="end"'):]
    assert re.search(r'<span class="stat-n">2</span><span class="stat-label">below the cut', end)
    rows = {a["cluster_id"]: a for a in json.loads((out / "2026-10-30.json").read_text())["also"]}
    assert rows["g1"]["folded"] is True and rows["g1"]["topic"] == "gurgaon-local"
    assert rows["y1"]["folded"] is False and rows["y1"]["topic"] == "ai-models"


LIVE = {"aqi": {"aqi": 168, "band": "Moderate", "dot": "butter", "at": "2026-10-30T11:00"},
        "match": {"text": "Barça v Aston Villa", "when": "Wed 1:30 am", "iso": "2026-11-03T20:00:00+00:00",
                  "competition": "UEFA Champions League"}}


def _live_html(session, tmp_path, live):
    ed = seed_edition(session, [(1, "A", "Lead story", {}, {})])
    ed.live = live
    session.flush()
    out = tmp_path / "out"
    return render_edition(session, ed, out).read_text(), out


def _tiles(html):
    if '<section class="live"' not in html:
        return None
    start = html.index('<section class="live"')
    return html[start:html.index("</section>", start)]


def test_tiles_render_and_hide(session, tmp_path):
    html, out = _live_html(session, tmp_path, LIVE)
    tiles = _tiles(html)
    assert tiles is not None and html.index("</header>") < html.index('<section class="live"') < html.index('class="progress"')
    assert "Gurgaon air now" in tiles and ">168<" in tiles and "Moderate" in tiles
    assert 'data-dot="butter"' in tiles and "24-h avg · model estimate" in tiles
    assert "Next match" in tiles and "Barça v Aston Villa" in tiles and "Wed 1:30 am" in tiles
    assert 'data-src="https://air-quality-api.open-meteo.com/v1/air-quality?' in tiles
    assert "current=pm2_5,pm10" in tiles and "timezone=Asia/Kolkata" in tiles
    assert "hourly=pm2_5,pm10" in tiles and "past_days=1" in tiles
    assert 'data-src="https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/83/schedule?fixture=true"' in tiles
    assert 'data-team-id="83"' in tiles
    assert json.loads((out / "2026-10-30.json").read_text())["live"] == LIVE


def test_tiles_one_only(session, tmp_path):
    html, _ = _live_html(session, tmp_path, {"match": LIVE["match"]})
    tiles = _tiles(html)
    assert "Next match" in tiles and "Gurgaon air now" not in tiles


def test_tiles_none(session, tmp_path):
    html, _ = _live_html(session, tmp_path, {})
    assert _tiles(html) is None and "Gurgaon air now" not in html


def test_tiles_css_tokens():
    css = _css()
    block = css.split(".live-tile {", 1)[1].split("}", 1)[0]
    # the tile is the page's post colour: white by day, the night post at night (task 6)
    assert "border-radius: 14px" in block and "background: var(--post)" in block
    assert "--post: var(--white);" in css.split("}", 1)[0]
    assert '[data-dot="good"]' in css and '[data-dot="butter"]' in css and '[data-dot="tomato"]' in css


def test_tune_card_renders(session, tmp_path):
    session.add_all([Cluster(id="m1", window_start=NOW, topics=["movies"], chapter=0),
                     Cluster(id="k1", window_start=NOW, topics=["cricket"], chapter=0)])
    also = [{"cluster_id": "m1", "rank": 1, "line": "A film", "cut_reason": None},
            {"cluster_id": "k1", "rank": 2, "line": "A match", "cut_reason": "budget"}]
    html, out = _render(session, tmp_path, [(1, "A", "Lead story", {}, {})], also=also)
    end = html[html.index('<section class="end"'):]
    tune = end[end.index('<div class="tune"'):end.index('<div class="next"')]
    assert end.index("That's today") < end.index('class="tune"')
    assert '<h2 class="tune-title">Tune tomorrow</h2>' in tune
    assert "A tap nudges tomorrow&#39;s edition only." in tune or \
        "A tap nudges tomorrow's edition only." in tune
    chips = re.findall(r'<button class="tune-chip" type="button" aria-pressed="false" '
                       r"data-payload='([^']*)'>([^<]*)</button>", tune)
    assert [(json.loads(p), label) for p, label in chips] == [
        ({"topic": "ai-models", "dir": -1}, "Less AI"), ({"topic": "movies", "dir": 1}, "More Movies"),
        ({"topic": "cricket", "dir": 1}, "More Cricket"), ({"budget": 1}, "Longer edition")]
    assert "tune" not in json.loads((out / "2026-10-30.json").read_text())


def test_tune_css_and_js():
    css = resources.files("newshouse").joinpath("static/edition.css").read_text()
    rule = css[css.index(".tune {"):].split("}", 1)[0]
    assert "background: var(--butter)" in rule and "border-radius: 14px" in rule
    chip = css[css.index(".tune-chip {"):].split("}", 1)[0]
    assert "border-radius: 8px" in chip and "min-height: 44px" in chip and "color: var(--forest)" in chip
    js = resources.files("newshouse").joinpath("static/edition.js").read_text()
    assert "function tune(" in js and 'send("tune", null, payload)' in js and "tune();" in js


def test_render_gives_no_more_chip_to_a_flooded_topic(session, tmp_path):
    """3 Nov was built before folding: 25 plain Gurgaon lines must not earn "More Gurgaon"."""
    from newshouse.models import Cluster
    for n, t in enumerate(["gurgaon-local"] * 3 + ["movies"], start=1):
        session.add(Cluster(id=f"x{n}", window_start=NOW, topics=[t], chapter=0))
    session.flush()
    also = [dict(cluster_id=f"x{n}", rank=n, line=f"Line x{n}", cut_reason="budget")
            for n in range(1, 5)]
    ed = seed_edition(session, [(1, "A", "Lead story", {}, {})], also=also)
    html = render_edition(session, ed, tmp_path / "out").read_text()
    tune = html[html.index('<div class="tune"'):html.index('<div class="next"')]
    assert "More Movies" in tune and "More Gurgaon" not in tune


def test_collapsed_timeline_shows_today_and_two_latest_chapters(session, tmp_path):
    d = {"chapters": [{"title": f"Chapter {k}", "date": f"Mar {k}", "read": True} for k in range(1, 6)],
         "delta": "Fines land"}
    html, _ = _render(session, tmp_path, [(1, "D", "Thread story", d, {"chapter": 6})])
    assert html.count('class="tl-entry') == 6  # Today plus all five earlier, so an open post keeps them
    for k in range(1, 6):
        assert f"Chapter {k}" in html
    css = (resources.files("newshouse") / "static" / "edition.css").read_text()
    assert '.post:not(.open) .visual[data-kind="timeline"] .tl-entry:nth-child(n+4) { display: none; }' in css


def test_timeline_clamps_apply_only_while_collapsed():
    css = re.sub(r"/\*.*?\*/", "", (resources.files("newshouse") / "static" / "edition.css").read_text(), flags=re.S)
    for sel, body in re.findall(r"([^{}]+)\{([^}]*)\}", css):
        if "line-clamp" in body and ".tl-" in sel:
            assert all(x.strip().startswith(".post:not(.open)") for x in sel.split(",")), sel


def test_css_clamps_timeline_and_slide_table_text_without_max_height():
    css = (resources.files("newshouse") / "static" / "edition.css").read_text()
    assert "max-height" not in css
    for sel in (".post:not(.open) .tl-entry.today p", ".post:not(.open) .tl-text p", ".slide-row-label", ".slide-row-big", ".slide-row-small"):
        rule = next((m for m in re.findall(r"([^{}]+)\{([^}]*)\}", re.sub(r"/\*.*?\*/", "", css, flags=re.S)) if sel in [s.strip() for s in m[0].split(",")]
                     and "line-clamp" in m[1]), None)
        assert rule is not None, sel


STACK = [{"cluster_id": "m1", "headline": "Second outlet says X", "line": "A short line about X.",
          "url": "https://a.example/x", "source": "Alpha News"},
         {"cluster_id": "m2", "headline": "Third outlet on X", "line": "",
          "url": "https://b.example/x", "source": "Beta Wire"}]


def test_stack_chip_and_strip_render(session, tmp_path):
    html, _ = _render(session, tmp_path, [(1, "A", "Stack lead", {}, {"stack": STACK})])
    post = _post(html, "card0")
    assert re.search(r'<button[^>]*class="stack-chip"[^>]*>\+2 more on this story</button>', post)
    assert post.index("stack-chip") < post.index('class="more"')
    more = post[post.index('class="more"'):]
    assert "More on this story" in more and 'class="stack"' in more
    assert more.index("The brief") < more.index('class="stack"')
    assert more.count('<section class="slide stack-slide"') == 2
    assert 'aria-label="1 of 2"' in more and 'aria-label="2 of 2"' in more
    assert "Alpha News" in more and "Second outlet says X" in more and "A short line about X." in more
    assert more.count('class="stack-line"') == 1  # the headline-only row omits its line
    assert re.search(r'<a[^>]*href="https://a.example/x"[^>]*target="_blank"[^>]*rel="noopener"[^>]*>Read at Alpha News</a>', more)
    assert 'class="slide-prev"' in more and 'class="slide-next"' in more and '1 / 2' in more
    assert 'class="visual"' not in more.split('class="stack"')[1]


def test_old_editions_render(session, tmp_path):
    html, _ = _render(session, tmp_path, [(1, "A", "No stack key", {}, {}), (2, "A", "Empty stack", {}, {"stack": []})])
    body = html[html.index("<main"):html.index("</main>")]
    assert "stack-chip" not in body and 'class="stack' not in body and "More on this story" not in body
    from newshouse.models import Edition
    from newshouse.render_static import edition_view
    cards = edition_view(session, session.get(Edition, "e1"))["cards"]
    assert [c["stack"] for c in cards] == [[], []]


def test_mid_length_value_renders_small(session, tmp_path):
    payload = {"columns": ["Item", "Value"],
               "rows": [{"cells": ["Short", "₹5Cr"], "yours": False, "new": False},
                        {"cells": ["Mid", "About 50 hours a year"], "yours": False, "new": False},
                        {"cells": ["Edge", "x" * 16], "yours": False, "new": False}]}
    html, _ = _render(session, tmp_path, [(1, "B", "Mid value table", payload, {})])
    assert 'class="row-big v-long">About 50 hours a year' in html
    assert re.search(r'class="row-big ">₹5Cr', html) and 'class="row-big ">' + "x" * 16 in html
    assert ".row-big.v-long" in html


MARKET = {"as_of": "2026-11-05T13:39:00+05:30", "indices": [
    {"name": "Nifty 50", "symbol": "NIFTY 50", "level": 24530.65, "prev_close": 23960.6, "change_pct": 2.38,
     "trend": [{"label": "1 week", "pct": 6.95}, {"label": "1 month", "pct": -0.4}]}]}


def test_market_tile_renders(session, tmp_path):
    html, out = _live_html(session, tmp_path, {"market": MARKET})
    tiles = _tiles(html)
    assert tiles is not None and 'data-tile="market"' in tiles and "data-src" not in tiles.split('data-tile="market"')[1].split(">")[0]
    assert 'data-as-of="2026-11-05T13:39:00+05:30"' in tiles
    assert "Nifty 50" in tiles and "24,530.65" in tiles and "Sensex" not in tiles
    assert "▲</span> 2.38%" in tiles
    assert '<button type="button" class="mk-toggle" aria-expanded="false" aria-controls="mk-trend">Trend</button>' in tiles
    trend = tiles.split('<div class="mk-trend" id="mk-trend" hidden>', 1)[1].split("</div>", 1)[0]
    assert "1 week" in trend and "▲</span> 6.95%" in trend and "1 month" in trend and "▼</span> 0.40%" in trend
    assert json.loads((out / "2026-10-30.json").read_text())["live"] == {"market": MARKET}
    css = _css()
    assert ".mk-toggle" in css and "min-height: 44px" in css.split(".mk-toggle {", 1)[1].split("}", 1)[0]
    assert '.mk-chg[data-dir="down"] { color: var(--tomato-ink)' in css


def test_market_tile_without_trend_has_no_toggle(session, tmp_path):
    old = {"as_of": "2026-11-04T15:30:00+05:30", "indices": [
        {"name": "Nifty 50", "symbol": "^NSEI", "level": 23960.6, "prev_close": 23810.85, "change_pct": 0.63,
         "closes": [23810.85, 23960.6]}]}  # the Yahoo-era snapshot of 4 Nov
    html, _ = _live_html(session, tmp_path, {"market": old})
    tiles = _tiles(html)
    assert "23,960.60" in tiles and 'class="mk-toggle"' not in tiles and 'class="mk-trend"' not in tiles


def test_market_tile_absent_without_data(session, tmp_path):
    html, _ = _live_html(session, tmp_path, {"aqi": LIVE["aqi"]})
    assert 'data-tile="market"' not in _tiles(html) and 'class="mk-toggle"' not in html


def test_market_tile_absent_with_no_live_data(session, tmp_path):
    html, _ = _live_html(session, tmp_path, {})
    assert _tiles(html) is None and 'class="mk-toggle"' not in html


def test_stack_links_are_safe_and_named(session, tmp_path):
    rows = [{"cluster_id": "m1", "headline": "Unsafe link", "line": "", "url": "javascript:alert(1)",
             "source": "Alpha News"},
            {"cluster_id": "m2", "headline": "No source", "line": "", "url": "https://b.example/y",
             "source": ""}]
    html, _ = _render(session, tmp_path, [(1, "A", "Stack lead", {}, {"stack": rows})])
    more = _post(html, "card0")
    more = more[more.index('class="stack"'):]
    assert "javascript:" not in more
    assert more.count('class="stack-link"') == 1  # the unsafe row keeps its headline, no link
    assert "Unsafe link" in more
    assert re.search(r'<a[^>]*href="https://b.example/y"[^>]*>Read the article</a>', more)
    assert "Read at </a>" not in more and "Read at <" not in more


def test_phase_a_formats_render_and_order(session, tmp_path):
    kf = {"facts": [{"label": "Who", "value": "Raphinha"}, {"label": "When", "value": "Thursday"}]}
    num = {"value": "$465M", "what": "raised at listing", "compare": {"label": "H1 revenue", "value": "$174K"}}
    ch = {"rows": [{"what": "Offices", "change": "at most 50% in person"}, {"what": "Construction", "change": "stopped"}],
          "from": "2026-10-25", "to": "2026-11-05", "where": "Delhi-NCR"}
    fs = {"has": ["sits on hold"], "lacks": ["outside the US"], "price": "$30 a month", "status": "limited", "where": "paid users"}
    html, _ = _render(session, tmp_path, [(1, "A", "Facts story", kf, {"visual": "key-facts"}),
                                          (2, "A", "Number story", num, {"visual": "number"}),
                                          (3, "A", "Changes story", ch, {"visual": "changes"}),
                                          (4, "A", "Sheet story", fs, {"visual": "factsheet"})])
    facts, number, changes, sheet = (_post(html, f"card{n}") for n in range(4))
    assert facts.count('class="kf-item"') == 2 and "kf-2" in facts
    assert 'class="nc-value">$465M' in number and number.count('class="bar-row"') == 2
    assert changes.count('class="ch-row"') == 2 and ">25 Oct<" in changes and ">20 Nov<" not in changes
    assert 'class="ch-today" style="--at: ' in changes  # 30 Oct, the seeded edition date, is inside
    assert "✓</span>sits on hold" in sheet and "✗" in sheet and 'class="pill">limited' in sheet
    # order: headline first for the explaining formats, visual first for the number hook
    for post in (facts, changes, sheet):
        assert post.index('class="headline"') < post.index('class="visual"')
    assert number.index('class="visual"') < number.index('class="headline"')


def test_story_formats_render_and_order(session, tmp_path):
    specs = [(1, "A", "Deal story", {"kind": "acquisition", "from": "OpenAI", "to": "Pierre", "amount": "$400M",
                                     "terms": None, "to_does": "developer tools", "status": "needs approval"}, {"visual": "deal"}),
             (2, "A", "Score story", {"home": "Barcelona", "away": "Aston Villa", "score": [3, 0], "competition": "UCL",
                                      "scorers": [{"name": "Raphinha", "minute": "12'", "side": "home"}], "note": None},
              {"visual": "scoreline"}),
             (3, "A", "Deadline story", {"date": "2026-11-29", "what": "the API shuts", "do": None}, {"visual": "countdown"}),
             (4, "A", "Scale story", {"scale": "aqi", "level": 0, "previous": 3, "value": 324}, {"visual": "scale"}),
             (5, "A", "Odd story", {"symptom": None}, {"visual": "incident"})]
    html, _ = _render(session, tmp_path, specs)
    deal, score, cd, scale, odd = (_post(html, f"card{n}") for n in range(5))
    assert 'class="dl-name">OpenAI' in deal and 'class="dl-amount">$400M' in deal and 'class="pill">needs approval' in deal
    assert deal.index('class="headline"') < deal.index('class="visual"')
    assert "3<span class=\"sl-dash\">–</span>0" in score and score.index('class="visual"') < score.index('class="headline"')
    assert 'class="cd-days">30 days' in cd and ">29 Nov<" in cd  # the seeded edition is 30 Oct
    assert "324 · Very poor" in scale and 'class="sc-now alarm"' in scale and ">was<" in scale  # level from the reading
    assert 'class="visual"' not in odd  # an undrawable payload shows no visual, never a crash
