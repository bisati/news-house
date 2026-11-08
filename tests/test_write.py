from datetime import datetime, timedelta, timezone

from newshouse.llm.backend import LLMError
from newshouse.llm.fake import FakeBackend
from newshouse.models import Card, Cluster, ClusterItem, Item, ItemSource, Source, Thread
from newshouse.write import allowed_formats, earlier_chapters, render_cluster_for_write, validate_card, write_card

NOW = datetime(2026, 10, 30, 6, 0, tzinfo=timezone.utc)


def mk(session, *, kind="rss", tier="mainstream", paywall=False, body="Body text. " * 40,
       chapter=None, thread=None):
    session.add(Source(id="s1", name="The Wire", topics=["ai"], tier=tier, kind=kind,
                       url="https://feeds/s1", paywall=paywall))
    for iid, age in (("i1", 2), ("i2", 0)):
        session.add(Item(id=iid, url=f"http://x/{iid}", canonical_url=f"http://x/{iid}",
                         title=f"Title {iid}", teaser=f"Teaser {iid} " * 30,
                         body=body if iid == "i1" else None,
                         published_at=NOW - timedelta(hours=age), first_seen_at=NOW,
                         dated=True, topics=[], raw={}))
    session.add(Cluster(id="c1", window_start=NOW, topics=["ai-models"], story_type="launch",
                        chapter=chapter, thread_id=thread))
    session.flush()
    for iid in ("i1", "i2"):
        session.add(ClusterItem(cluster_id="c1", item_id=iid))
        session.add(ItemSource(item_id=iid, source_id="s1"))
    session.flush()
    return session.get(Cluster, "c1")


def b_card(**kw):
    out = {"format": "B", "headline": "Model X beats Y on 3 benchmarks", "line": "One line.",
           "para": "A para.", "brief": "Brief.", "why": "You build on Y.",
           "cited_item_ids": ["i1"],
           "payload": {"columns": ["Model", "Score"],
                       "rows": [{"cells": ["X", "90"], "yours": False, "new": True},
                                {"cells": ["Y", "80"], "yours": True, "new": False}]}}
    out.update(kw)
    return out


def test_write_happy_path_stores_payload_and_citations(session):
    c = mk(session)
    backend = FakeBackend([b_card()])
    card = write_card(session, backend, c, profile_text="Mihir, PM in Gurgaon")
    assert card.format == "B" and len(card.payload["rows"]) == 2
    assert set(card.cited_item_ids) <= {"i1", "i2"}
    assert card.est_seconds == 50 and card.unverified is False
    assert card.cluster_id == "c1" and card.id
    assert "Mihir, PM in Gurgaon" in backend.calls[0]["system"]
    assert "Allowed visuals: none, key-facts, number, cover, quote, countdown, deal, changes, factsheet, incident, case, steps, chart, table, versus, before-after" in backend.calls[0]["user"]


def test_write_rejects_unknown_citations(session):
    c = mk(session)
    backend = FakeBackend([b_card(cited_item_ids=["nope"]), b_card()])
    card = write_card(session, backend, c, profile_text="p")
    assert len(backend.calls) == 2
    assert "Your previous reply had these problems:" in backend.calls[1]["user"]
    assert "nope" in backend.calls[1]["user"]
    assert card.format == "B" and card.unverified is False


def test_write_falls_back_to_unverified_A(session):
    c = mk(session)
    backend = FakeBackend([b_card(cited_item_ids=["nope"])] * 2)
    card = write_card(session, backend, c, profile_text="p")
    assert len(backend.calls) == 2
    assert card.format == "A" and card.unverified is True and card.payload == {}
    assert card.headline == "Title i2"  # most recent
    assert card.line == session.get(Item, "i2").teaser[:200]
    assert card.para == card.brief == card.why == ""
    assert card.cited_item_ids == ["i2"] and card.est_seconds == 35


def test_rich_format_not_allowed_for_gnews_only_cluster(session):
    c = mk(session, kind="gnews")
    items = [session.get(Item, i) for i in ("i1", "i2")]
    sbi = {i.id: [session.get(Source, "s1")] for i in items}
    assert allowed_formats(c, items, sbi) == ["A"]
    text = render_cluster_for_write(session, c, thread=None, read_chapters=frozenset())
    assert "Allowed visuals: none, key-facts, number, cover, quote, countdown, deal\n" in text
    backend = FakeBackend([b_card(), b_card()])
    notes: list[str] = []
    card = write_card(session, backend, c, profile_text="p", notes=notes)
    # a disallowed visual is a visual problem (Ruling 2): the text stays, the visual is a cover
    assert card.unverified is False and card.format == "A" and card.visual == "none"
    assert card.headline == "Model X beats Y on 3 benchmarks" and card.payload == {}
    assert "format" in backend.calls[1]["user"]
    assert len(notes) == 1 and "not allowed" in notes[0]


def test_primary_tier_gnews_only_cluster_is_format_a_only(session):
    c = mk(session, kind="gnews", tier="primary", body=None)
    items = [session.get(Item, i) for i in ("i1", "i2")]
    sbi = {i.id: [session.get(Source, "s1")] for i in items}
    assert allowed_formats(c, items, sbi) == ["A"]


def test_primary_tier_non_gnews_unlocks_rich(session):
    c = mk(session, kind="rss", tier="primary", body=None)
    items = [session.get(Item, i) for i in ("i1", "i2")]
    sbi = {i.id: [session.get(Source, "s1")] for i in items}
    assert allowed_formats(c, items, sbi) == ["A", "B", "C", "E", "F"]


def test_headline_over_90_is_problem():
    out = {"format": "A", "headline": "x" * 91, "line": "l", "para": "p", "brief": "b",
           "why": "", "cited_item_ids": ["i1"], "payload": {}}
    assert any("headline" in p for p in validate_card(out, {"i1"}, allowed=["A"]))
    out["headline"] = "x" * 90
    assert validate_card(out, {"i1"}, allowed=["A"]) == []
    out["headline"] = ""
    assert any("headline" in p for p in validate_card(out, {"i1"}, allowed=["A"]))


def test_chart_needs_three_points():
    pts = [{"label": "a", "value": 1, "item_id": "i1"}, {"label": "b", "value": 2.5, "item_id": "i1"}]
    out = {"format": "C", "headline": "h", "line": "l", "para": "p", "brief": "b", "why": "",
           "cited_item_ids": ["i1"], "payload": {"series": pts, "unit": "%", "caption": "c"}}
    assert any("series" in p for p in validate_card(out, {"i1"}, allowed=["A", "C"]))
    out["payload"]["series"] = pts + [{"label": "c", "value": 3, "item_id": "i1"}]
    assert validate_card(out, {"i1"}, allowed=["A", "C"]) == []
    out["payload"]["series"][2]["item_id"] = "i9"
    assert any("item_id" in p for p in validate_card(out, {"i1", "i9"}, allowed=["A", "C"]))
    out["payload"]["series"][2]["value"] = "3"
    assert any("value" in p for p in validate_card(out, {"i1"}, allowed=["A", "C"]))


def base(fmt, payload, **kw):
    out = {"format": fmt, "headline": "h", "line": "l", "para": "p", "brief": "b", "why": "",
           "cited_item_ids": ["i1"], "payload": payload}
    out.update(kw)
    return out


def test_validate_other_rules():
    ids = {"i1"}
    al = list("ABCDEF")
    assert validate_card(base("A", {}, cited_item_ids=[]), ids, allowed=al)
    assert validate_card(base("A", {}, line=""), ids, allowed=al)
    assert validate_card(base("A", {}, para=""), ids, allowed=al)
    assert validate_card(base("A", {"x": 1}), ids, allowed=al)
    assert validate_card(base("Z", {}), ids, allowed=al)
    # B
    good_row = {"cells": ["a", "b"], "yours": False, "new": True}
    assert validate_card(base("B", {"columns": ["a", "b"], "rows": [good_row]}), ids, allowed=al) == []
    assert validate_card(base("B", {"columns": [], "rows": [good_row]}), ids, allowed=al)
    assert validate_card(base("B", {"columns": ["a", "b"], "rows": []}), ids, allowed=al)
    assert validate_card(base("B", {"columns": ["a"], "rows": [good_row]}), ids, allowed=al)
    assert validate_card(base("B", {"columns": ["a", "b"], "rows": [{**good_row, "new": "y"}]}), ids, allowed=al)
    # D
    d = {"chapters": [{"title": "t", "date": "2026-10-01", "read": True}], "delta": "now"}
    assert validate_card(base("D", d), ids, allowed=al) == []
    assert validate_card(base("D", {**d, "delta": ""}), ids, allowed=al)
    assert validate_card(base("D", {**d, "chapters": []}), ids, allowed=al)
    assert validate_card(base("D", {**d, "chapters": [{"title": "t", "date": "d"}]}), ids, allowed=al)
    # E
    e = {"for": ["a"], "against": ["b"], "stands": "s"}
    assert validate_card(base("E", e), ids, allowed=al) == []
    assert validate_card(base("E", {**e, "against": []}), ids, allowed=al)
    assert validate_card(base("E", {**e, "stands": 3}), ids, allowed=al)
    # F
    f = {"before": "a", "after": "b", "effective": "c", "applies_to": "d"}
    assert validate_card(base("F", f), ids, allowed=al) == []
    assert validate_card(base("F", {**f, "effective": ""}), ids, allowed=al)


def test_write_sets_cluster_carded_and_returns_unsaved_card(session):
    c = mk(session)
    card = write_card(session, FakeBackend([b_card()]), c, profile_text="p")
    assert c.carded is True
    assert card not in session
    c2 = mk_second(session)
    write_card(session, FakeBackend([b_card(cited_item_ids=["nope"])] * 2), c2, profile_text="p")
    assert c2.carded is True


def mk_second(session):
    c = Cluster(id="c2", window_start=NOW, topics=[], story_type="plain")
    session.add(c)
    session.flush()
    session.add(ClusterItem(cluster_id="c2", item_id="i1"))
    session.flush()
    return c


def test_write_llm_error_falls_back(session):
    c = mk(session)
    def boom(system, user, schema, model):
        raise LLMError("down")
    backend = FakeBackend(boom)
    card = write_card(session, backend, c, profile_text="p")
    assert card.unverified is True and card.format == "A" and c.carded is True
    assert card.cited_item_ids == ["i2"]
    # error on second attempt only
    c2 = mk_second(session)
    seq = [b_card(cited_item_ids=["nope"])]
    def fn(system, user, schema, model):
        if seq:
            return seq.pop()
        raise LLMError("down")
    card2 = write_card(session, FakeBackend(fn), c2, profile_text="p")
    assert card2.unverified is True and card2.cited_item_ids == ["i1"]


def test_render_includes_blocks_thread_and_paywall(session):
    t = Thread(id="t1", title="Big saga", summary="Summary text", opened_at=NOW,
               last_chapter_at=NOW, chapters=3)
    session.add(t)
    session.flush()
    c = mk(session, paywall=True, body="z" * 7000, chapter=3, thread="t1")
    text = render_cluster_for_write(session, c, thread=t, read_chapters={1, 2})
    assert "#### item i1" in text and "source: The Wire (mainstream, paywall, rss)" in text
    assert "[truncated]" in text and "z" * 6001 not in text
    assert "body: (paywalled; teaser only)" in text  # i2 has no body
    assert '### Thread "Big saga" (3 chapters so far)' in text
    assert "Read chapters: 1, 2" in text and "Allowed visuals: none, key-facts, number, cover, quote, countdown, deal, timeline, changes, factsheet, incident, case, steps, chart, table, versus, before-after" in text


def _thread_with_cards(session):
    t = Thread(id="t1", title="Big saga", summary="Summary", opened_at=NOW,
               last_chapter_at=NOW, chapters=3)
    session.add(t)
    session.flush()
    c = mk(session, chapter=3, thread="t1")
    from newshouse.models import Edition
    from datetime import date
    session.add(Edition(id="e1", date=date(2026, 10, 29), budget_seconds=600))
    session.add(Cluster(id="old1", window_start=NOW, topics=[], thread_id="t1", chapter=1))
    session.add(Cluster(id="old2", window_start=NOW, topics=[], thread_id="t1", chapter=2))
    session.flush()
    for n in (1, 2):
        session.add(Card(id=f"card{n}", edition_id="e1", rank=n, cluster_id=f"old{n}",
                         thread_id="t1", chapter=n, format="A", payload={},
                         headline=f"Chapter {n} headline", line="l", para="p", brief="", why="",
                         est_seconds=35, cited_item_ids=["i1"],
                         created_at=datetime(2026, 10, 20 + n, 5, tzinfo=timezone.utc)))
    session.flush()
    return t, c


def test_render_includes_earlier_chapter_titles_and_dates(session):
    t, c = _thread_with_cards(session)
    text = render_cluster_for_write(session, c, thread=t, read_chapters={1})
    assert "- chapter 1 (2026-10-21, read): Chapter 1 headline" in text
    assert "- chapter 2 (2026-10-22, unread): Chapter 2 headline" in text
    ec = earlier_chapters(session, t, before_chapter=3, read_chapters={1})
    assert [e["read"] for e in ec] == [True, False]


def test_earlier_chapters_falls_back_to_cluster_and_skips_missing(session):
    t, c = _thread_with_cards(session)
    session.delete(session.get(Card, "card2"))
    session.add(ClusterItem(cluster_id="old2", item_id="i2"))
    session.flush()
    ec = earlier_chapters(session, t, before_chapter=6, read_chapters=set())
    assert [e["chapter"] for e in ec] == [1, 2, 3]  # chapters 4 and 5 have nothing: skipped
    assert ec[1]["title"] == "Title i2"


def test_validate_d_requires_matching_chapters():
    exp = [{"chapter": 1, "title": "a", "date": "2026-10-21", "read": True},
           {"chapter": 2, "title": "b", "date": "2026-10-22", "read": False}]
    def d(chs):
        return base("D", {"chapters": chs, "delta": "x"})
    ch = lambda r: {"title": "t", "date": "d", "read": r}
    ok = d([ch(True), ch(False)])
    assert validate_card(ok, {"i1"}, allowed=["A", "D"], expected_chapters=exp) == []
    assert validate_card(d([ch(True)]), {"i1"}, allowed=["A", "D"], expected_chapters=exp)
    assert validate_card(d([ch(False), ch(False)]), {"i1"}, allowed=["A", "D"], expected_chapters=exp)
    assert validate_card(d([ch(True), ch(False), ch(False)]), {"i1"}, allowed=["A", "D"], expected_chapters=exp)


def test_write_uses_opus_at_default_effort(session):
    c = mk(session)
    backend = FakeBackend([b_card()])
    write_card(session, backend, c, profile_text="p")
    assert backend.calls[0]["model"] == "opus" and backend.calls[0]["effort"] is None


def test_write_prompt_caps_items_at_12_bodies_first(session):
    import re as _re
    session.add_all([
        Source(id="sp", name="Lab blog", topics=["ai"], tier="primary", kind="rss",
               url="https://feeds/sp", paywall=False),
        Source(id="sm", name="Daily", topics=["ai"], tier="mainstream", kind="rss",
               url="https://feeds/sm", paywall=False)])
    session.add(Cluster(id="big", window_start=NOW, topics=["ai-models"], story_type="launch"))
    session.flush()
    for k in range(20):
        iid = f"n{k:02d}"
        session.add(Item(id=iid, url=f"http://x/{iid}", canonical_url=f"http://x/{iid}",
                         title=f"Title {iid}", teaser="t", body="Body." if k in (3, 17) else None,
                         published_at=NOW - timedelta(hours=k), first_seen_at=NOW, dated=True,
                         topics=[], raw={}))
        session.flush()
        session.add(ClusterItem(cluster_id="big", item_id=iid))
        session.add(ItemSource(item_id=iid, source_id="sp" if k in (10, 15) else "sm"))
    session.flush()
    c = session.get(Cluster, "big")
    text = render_cluster_for_write(session, c, thread=None, read_chapters=frozenset())
    shown = _re.findall(r"^#### item (\S+)", text, _re.M)
    assert len(shown) == 12
    assert shown[:2] == ["n03", "n17"]          # bodies first
    assert shown[2:4] == ["n10", "n15"]         # then primary tier
    assert shown[4:] == ["n00", "n01", "n02", "n04", "n05", "n06", "n07", "n08"]  # newest
    assert "[8 more items omitted]" in text
    backend = FakeBackend([{"format": "A", "headline": "H", "line": "l", "para": "p",
                            "brief": "b", "why": "", "cited_item_ids": ["n19"], "payload": {}}] * 2)
    card = write_card(session, backend, c, profile_text="p")
    assert card.unverified is True  # an item the writer was not shown cannot be cited


def test_write_card_with_problems_makes_one_attempt(session):
    c = mk(session)
    backend = FakeBackend([b_card(cited_item_ids=["nope"]), b_card()])
    card = write_card(session, backend, c, profile_text="p", problems=["headline is 14 words"])
    assert len(backend.calls) == 1
    user = backend.calls[0]["user"]
    assert "Your previous reply had these problems:\n- headline is 14 words" in user
    assert "Fix them and reply again with JSON only." in user
    assert card.unverified is True and c.carded  # the one bad reply falls back


# --- phase 2: the visual catalogue, slides and tone -------------------------------------

from newshouse.write import allowed_visuals, item_facts  # noqa: E402


def _items_sbi(session, kind="rss"):
    items = [session.get(Item, i) for i in ("i1", "i2")]
    src = Source(id=f"x-{kind}", name="X", topics=[], tier="mainstream", kind=kind,
                 url=f"https://feeds/{kind}", paywall=False)
    return items, {i.id: [src] for i in items}


def test_allowed_visuals(session):
    c = mk(session, body=None)
    items, sbi = _items_sbi(session)
    assert allowed_visuals(c, items, sbi) == ["none", "key-facts", "number", "cover", "quote", "countdown", "deal"]
    items[0].body = "Full body."
    assert allowed_visuals(c, items, sbi) == ["none", "key-facts", "number", "cover", "quote", "countdown", "deal", "changes", "factsheet", "incident", "case", "steps", "chart", "table", "versus",
                                              "before-after"]
    c.topics = ["football"]
    got = allowed_visuals(c, items, sbi)
    assert got[-1] == "pitch" and {"availability", "scoreline", "stakes", "rumour"} <= set(got)
    c.chapter = 2
    assert allowed_visuals(c, items, sbi)[:12] == ["none", "key-facts", "number", "cover", "quote", "countdown", "deal",
                                                   "availability", "scoreline", "stakes", "rumour", "timeline"]
    items[0].body = "Full body. GRAP stage 2 is in force."
    assert "scale" in allowed_visuals(c, items, sbi)
    c.topics = ["ai-models"]
    assert "rumour" not in allowed_visuals(c, items, sbi)
    c.topics = ["football"]
    items[1].image_url = "https://img/x.jpg"
    assert allowed_visuals(c, items, sbi)[-1] == "photo"
    g_items, g_sbi = _items_sbi(session, kind="gnews")
    assert "photo" not in allowed_visuals(c, g_items, g_sbi)
    facts = item_facts(items, sbi)
    assert facts["i2"].image_url == "https://img/x.jpg" and "Title i2" in facts["i2"].text
    assert item_facts(g_items, g_sbi)["i2"].image_url is None


def test_writer_input_lists_visuals_tone_and_images(session):
    c = mk(session, body=None)
    text = render_cluster_for_write(session, c, thread=None, read_chapters=frozenset())
    assert "Allowed visuals: none, key-facts, number, cover, quote, countdown, deal\n" in text and "tone (from classify)" not in text
    c.tone = "bad"
    session.get(Item, "i2").image_url = "https://img/i2.jpg"
    text = render_cluster_for_write(session, c, thread=None, read_chapters=frozenset())
    assert "tone (from classify): bad" in text
    assert "url: http://x/i2\nimage: https://img/i2.jpg\n" in text
    assert "Allowed visuals: none, key-facts, number, cover, quote, countdown, deal, photo" in text


def _v(**kw):
    out = {"visual": "none", "headline": "Alphabet misses on capex", "line": "One line.",
           "para": "A para.", "brief": "Capex reached $500 billion.\n\nShares fell.",
           "why": "", "cited_item_ids": ["i1"], "payload": {}, "slides": [], "tone": "bad"}
    out.update(kw)
    return out


DECK = [{"kind": "cover", "title": "Capex", "body": "", "payload": {"big": "$500B"}},
        {"kind": "text", "title": "Shares fell", "body": "Investors sold.", "payload": {}}]


def test_reply_with_deck_is_stored(session):
    c = mk(session)
    card = write_card(session, FakeBackend([_v(slides=DECK)]), c, profile_text="p")
    assert card.slides == DECK and card.visual == "none" and card.tone == "bad"
    assert card.format == "A" and card.est_seconds == 50 and card.unverified is False


def test_legacy_format_reply_still_works(session):
    c = mk(session)
    c.tone = "mixed"
    pts = [{"label": x, "value": n, "item_id": "i1"} for n, x in enumerate("abc")]
    reply = base("C", {"series": pts, "unit": "%", "caption": "c"})
    card = write_card(session, FakeBackend([reply]), c, profile_text="p")
    assert card.visual == "chart" and card.format == "C" and card.slides == []
    assert card.tone == "mixed" and card.unverified is False and card.est_seconds == 50


def test_bad_deck_keeps_text(session):
    c = mk(session)
    bad = [{**DECK[0], "payload": {"big": "$600B"}}, DECK[1]]
    notes: list[str] = []
    backend = FakeBackend([_v(slides=bad), _v(slides=bad)])
    card = write_card(session, backend, c, profile_text="p", notes=notes)
    assert len(backend.calls) == 2 and "slides[0]" in backend.calls[1]["user"]
    assert (card.headline, card.line, card.brief) == ("Alphabet misses on capex", "One line.",
                                                     _v()["brief"])
    assert card.visual == "none" and card.payload == {} and card.slides == []
    assert card.format == "A" and card.est_seconds == 35 and card.unverified is False
    assert len(notes) == 1 and notes[0].startswith("Alphabet misses on capex: ")
    assert "slides[0]" in notes[0]


def test_bad_text_still_falls_back_to_teaser(session):
    c = mk(session)
    card = write_card(session, FakeBackend([_v(headline="")] * 2), c, profile_text="p")
    assert card.unverified is True and card.headline == "Title i2" and card.format == "A"


def test_visual_not_allowed_is_a_problem(session):
    c = mk(session)
    photo = _v(visual="photo", payload={"item_id": "i1", "alt": "a", "credit": "c"})
    backend = FakeBackend([photo, _v()])
    card = write_card(session, backend, c, profile_text="p")
    assert len(backend.calls) == 2
    assert "photo" in backend.calls[1]["user"].split("Your previous reply had these problems:")[1]
    assert card.visual == "none" and card.unverified is False


def test_text_that_passed_on_attempt_one_survives_a_worse_retry(session):
    """Final review (deferred minor promoted): Ruling 2 keeps attempt 1's passing text."""
    c = mk(session)
    one_slide = [{"kind": "cover", "title": "", "body": "", "payload": {"big": "X"}}]
    first = b_card(headline="First headline", slides=one_slide)  # text fine, deck broken
    second = b_card(headline="Second headline", cited_item_ids=["nope"])  # text broken
    notes: list[str] = []
    card = write_card(session, FakeBackend([first, second]), c, profile_text="p", notes=notes)
    assert card.unverified is False and card.headline == "First headline"
    assert card.visual == "none" and card.slides == [] and card.payload == {}
    assert len(notes) == 1 and notes[0].startswith("First headline: ") and "two to four" in notes[0]
