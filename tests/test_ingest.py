from datetime import datetime, timedelta, timezone
from pathlib import Path

from newshouse.ingest import ingest
from newshouse.models import Item, ItemSource, Run, Source
from newshouse.sources import source_id

FIX = Path(__file__).parent / "fixtures" / "feeds"
NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


def add_source(session, url, topics=("ai-models",), kind="rss", **kw):
    s = Source(id=source_id(url), name=url, topics=list(topics), tier="primary",
               kind=kind, url=url, home=url, paywall=False, **kw)
    session.add(s)
    session.flush()
    return s


def feed(*items):
    body = "".join(
        f"<item><title>{t}</title><link>{u}</link><guid>{u}</guid><pubDate>{d}</pubDate></item>"
        for t, u, d in items)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>{body}</channel></rss>'.encode()


def rfc(dt):
    return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")


def test_ingest_stores_items_and_item_sources(session, httpx_mock, httpx_client):
    src = add_source(session, "https://one.example/feed.xml")
    httpx_mock.add_response(url=src.url, content=(FIX / "rss_dated.xml").read_bytes(),
                            headers={"ETag": '"e1"'})
    stats = ingest(session, now=NOW, client=httpx_client)
    session.flush()
    assert stats.sources_tried == 1 and stats.sources_ok == 1 and stats.sources_failed == {}
    assert stats.items_new == 3 and stats.items_dup == 0
    assert session.query(Item).count() == 3
    assert session.query(ItemSource).count() == 3
    item = session.query(Item).filter(Item.title == "First story").one()
    assert item.topics == ["ai-models"] and item.dated is True
    assert item.canonical_url == "https://example.com/a"
    assert item.first_seen_at == NOW
    assert src.etag == '"e1"' and src.last_ok_at == NOW
    run = session.query(Run).one()
    assert run.kind == "ingest" and run.status == "ok" and run.stats["items_new"] == 3


def test_ingest_continues_after_source_failure(session, httpx_mock, httpx_client):
    bad = add_source(session, "https://a-bad.example/feed.xml")
    good = add_source(session, "https://b-good.example/feed.xml")
    httpx_mock.add_response(url=bad.url, status_code=500)
    httpx_mock.add_response(url=good.url, content=(FIX / "rss_dated.xml").read_bytes())
    stats = ingest(session, now=NOW, client=httpx_client)
    assert stats.sources_tried == 2 and stats.sources_ok == 1
    assert stats.items_new == 3
    assert list(stats.sources_failed) == [bad.url]


def test_ingest_isolates_unexpected_exception(session, httpx_mock, httpx_client, monkeypatch):
    a = add_source(session, "https://a.example/feed.xml")
    b = add_source(session, "https://b.example/feed.xml")
    import newshouse.ingest as mod
    real = mod.fetch_feed

    def boom(url, **kw):
        if url == a.url:
            raise RuntimeError("kaboom")
        return real(url, **kw)

    monkeypatch.setattr(mod, "fetch_feed", boom)
    httpx_mock.add_response(url=b.url, content=(FIX / "rss_dated.xml").read_bytes())
    stats = ingest(session, now=NOW, client=httpx_client)
    assert "kaboom" in stats.sources_failed[a.url]
    assert stats.items_new == 3 and stats.sources_ok == 1


def test_ingest_skips_disabled_and_other_kinds(session, httpx_mock, httpx_client):
    add_source(session, "https://off.example/f", enabled=False)
    add_source(session, "https://x.example/f", kind="x")
    stats = ingest(session, now=NOW, client=httpx_client)
    assert stats.sources_tried == 0


def test_stale_marking_uses_72h(session, httpx_mock, httpx_client):
    src = add_source(session, "https://stale.example/feed.xml")
    httpx_mock.add_response(url=src.url, content=feed(
        ("old", "https://stale.example/old", rfc(NOW - timedelta(hours=80))),
        ("fresh", "https://stale.example/fresh", rfc(NOW - timedelta(hours=70)))))
    stats = ingest(session, now=NOW, client=httpx_client)
    assert stats.items_stale == 1
    assert session.query(Item).filter(Item.title == "old").one().stale is True
    assert session.query(Item).filter(Item.title == "fresh").one().stale is False


def test_undated_item_uses_now_and_is_not_stale(session, httpx_mock, httpx_client):
    src = add_source(session, "https://u.example/feed.xml")
    httpx_mock.add_response(url=src.url, content=(FIX / "rss_undated.xml").read_bytes())
    ingest(session, now=NOW, client=httpx_client)
    items = session.query(Item).all()
    assert items and all(i.dated is False and i.stale is False and i.published_at == NOW for i in items)


def test_same_url_from_two_sources_is_one_item(session, httpx_mock, httpx_client):
    a = add_source(session, "https://a.example/feed.xml", topics=["ai-models"])
    b = add_source(session, "https://b.example/feed.xml", topics=["markets"])
    xml = feed(("Shared", "https://shared.example/story", rfc(NOW - timedelta(hours=1))))
    httpx_mock.add_response(url=a.url, content=xml)
    httpx_mock.add_response(url=b.url, content=xml)
    stats = ingest(session, now=NOW, client=httpx_client)
    session.flush()
    assert session.query(Item).count() == 1
    assert session.query(ItemSource).count() == 2
    assert session.query(Item).one().topics == ["ai-models", "markets"]
    assert stats.items_new == 1 and stats.items_dup == 1
