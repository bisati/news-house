from datetime import timezone
from pathlib import Path

import feedparser
import httpx

from newshouse.fetch.feeds import USER_AGENT, fetch_feed
from newshouse.fetch.normalize import RawItem, canonical_url, item_id, normalize_entry

FIX = Path(__file__).parent / "fixtures" / "feeds"
URL = "https://example.com/feed.xml"


def body(name: str) -> bytes:
    return (FIX / name).read_bytes()


def fetch(url=URL, kind="rss", **kw):
    with httpx.Client() as client:
        return fetch_feed(url, kind=kind, client=client, **kw)


def test_rss_dated_items_parsed(httpx_mock):
    httpx_mock.add_response(url=URL, content=body("rss_dated.xml"),
                            headers={"ETag": '"e1"', "Last-Modified": "Wed, 29 Oct 2026 11:00:00 GMT"})
    r = fetch()
    assert r.ok and r.status == 200 and r.error is None
    assert r.etag == '"e1"' and r.last_modified == "Wed, 29 Oct 2026 11:00:00 GMT"
    assert len(r.items) == 3
    first = r.items[0]
    assert first.title == "First story"
    assert first.guid == "g-1" and first.author == "Jane Roe"
    assert first.published_at.tzinfo is not None
    assert first.published_at.utcoffset().total_seconds() == 0
    assert first.published_at.isoformat() == "2026-10-29T10:30:00+00:00"
    assert r.items[1].published_at.isoformat() == "2026-10-28T02:30:00+00:00"
    assert first.teaser == "Hello world & friends. Second para"
    assert "<" not in first.teaser
    assert first.raw["tags"] == ["ai"]
    assert httpx_mock.get_request().headers["user-agent"] == USER_AGENT


def test_undated_item_uses_first_seen(httpx_mock):
    httpx_mock.add_response(url=URL, content=body("rss_undated.xml"))
    r = fetch()
    assert r.ok and len(r.items) == 2
    assert all(i.published_at is None for i in r.items)


def test_conditional_get_304_returns_ok_empty(httpx_mock):
    httpx_mock.add_response(url=URL, status_code=304)
    r = fetch(etag='"e1"', last_modified="Wed, 29 Oct 2026 11:00:00 GMT")
    req = httpx_mock.get_request()
    assert req.headers["if-none-match"] == '"e1"'
    assert req.headers["if-modified-since"] == "Wed, 29 Oct 2026 11:00:00 GMT"
    assert r.ok and r.items == [] and r.status == 304
    assert r.etag == '"e1"' and r.last_modified == "Wed, 29 Oct 2026 11:00:00 GMT"


def test_html_response_is_failure_not_exception(httpx_mock):
    httpx_mock.add_response(url=URL, content=body("html_not_feed.html"))
    r = fetch()
    assert not r.ok and r.error == "html" and r.items == []


def test_http_error_status(httpx_mock):
    httpx_mock.add_response(url=URL, status_code=503)
    r = fetch()
    assert not r.ok and r.error == "http 503" and r.status == 503


def test_network_error_does_not_raise(httpx_mock):
    httpx_mock.add_exception(httpx.ConnectError("boom"))
    r = fetch()
    assert not r.ok and r.error


def test_garbage_body_is_parse_failure(httpx_mock):
    httpx_mock.add_response(url=URL, content=b"this is not xml at all <<<")
    r = fetch()
    assert not r.ok and r.error.startswith("parse:")


def test_oversize_body_is_capped(httpx_mock):
    head = body("rss_dated.xml").decode().replace("</channel></rss>", "")
    filler = "<!-- " + "x" * 4_000_000 + " -->"
    httpx_mock.add_response(url=URL, content=(head + filler + "</channel></rss>").encode())
    r = fetch(max_bytes=100_000)
    assert r.ok and len(r.items) == 3


def test_canonical_url_strips_tracking():
    assert canonical_url("https://X.com/a/?utm_source=t#frag") == "https://x.com/a"
    assert canonical_url("HTTP://X.com/?fbclid=1&b=2&a=1&ref=x") == "http://x.com?b=2&a=1"
    assert canonical_url("https://x.com/") == "https://x.com"
    assert canonical_url("") == ""


def test_item_id_fallbacks():
    mk = lambda url, guid: RawItem("T", url, guid, "", None, None, {})
    import hashlib
    sha = lambda s: hashlib.sha1(s.encode()).hexdigest()
    assert item_id("s", mk("https://X.com/a/?utm_x=1", "g")) == sha("https://x.com/a")
    assert item_id("s", mk("", "g")) == sha("g")
    assert item_id("s", mk("", None)) == sha("s|T")


def test_gnews_entry_keeps_publisher(httpx_mock):
    httpx_mock.add_response(url=URL, content=body("gnews.xml"))
    r = fetch(kind="gnews")
    assert r.items[0].raw["publisher"] == "Hindustan Times"
    assert r.items[0].raw["publisher_domain"] == "www.hindustantimes.com"
    assert "publisher" not in r.items[1].raw
    assert "<" not in r.items[0].teaser and "&nbsp;" not in r.items[0].teaser


def test_youtube_uses_media_description(httpx_mock):
    httpx_mock.add_response(url=URL, content=body("atom_youtube.xml"))
    r = fetch(kind="youtube")
    it = r.items[0]
    assert it.url == "https://www.youtube.com/watch?v=abc123XYZ"
    assert it.teaser == "Line one of the description."
    assert it.published_at.isoformat() == "2026-10-29T12:00:00+00:00"
    assert it.author == "Some Channel"


def test_hn_keeps_comments_link():
    xml = ('<rss version="2.0"><channel><title>HN</title><item><title>Story</title>'
           '<link>https://story.example/x</link><comments>https://news.ycombinator.com/item?id=1</comments>'
           '<description>d</description></item></channel></rss>')
    entry = feedparser.parse(xml).entries[0]
    it = normalize_entry(entry, "hn")
    assert it.url == "https://story.example/x"
    assert it.raw["comments"] == "https://news.ycombinator.com/item?id=1"


def test_teaser_capped_at_1500():
    xml = ('<rss version="2.0"><channel><title>T</title><item><title>S</title><link>https://a.example/1</link>'
           f'<description>{"w " * 2000}</description></item></channel></rss>')
    it = normalize_entry(feedparser.parse(xml).entries[0], "rss")
    assert len(it.teaser) <= 1500


def test_bad_date_on_one_entry_does_not_fail_feed(httpx_mock):
    good = (4, 2026, 10, 29, 10, 0, 0)
    e = {"title": "T", "link": "https://a.example/1",
         "published_parsed": (2026, 10, 29, 23, 59, 60, 0, 0, 0)}
    assert normalize_entry(e, "rss").published_at is None
    e["published_parsed"] = (0, 1, 1, 0, 0, 0, 0, 0, 0)
    e["updated_parsed"] = (2026, 10, 29, 10, 0, 0, 0, 0, 0)
    assert normalize_entry(e, "rss").published_at.isoformat() == "2026-10-29T10:00:00+00:00"
    e["updated_parsed"] = (0, 1, 1, 0, 0, 0, 0, 0, 0)
    assert normalize_entry(e, "rss").published_at is None

    xml = body("rss_dated.xml").decode().replace(
        "</channel>",
        "<item><title>Leap</title><link>https://example.com/leap</link>"
        "<pubDate>Wed, 29 Oct 2026 23:59:60 GMT</pubDate></item></channel>")
    httpx_mock.add_response(url=URL, content=xml.encode())
    r = fetch()
    assert r.ok and len(r.items) == 4
