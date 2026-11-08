import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from newshouse.enrich import enrich_clusters, extract_body, extract_image
from newshouse.models import Cluster, ClusterItem, Item, ItemSource, Source

HTML = (Path(__file__).parent / "fixtures" / "article.html").read_text()
NOW = datetime(2026, 10, 30, 8, 0, tzinfo=timezone.utc)


def _setup(session, specs, cluster_id="c1"):
    """specs: list of (item_id, [(tier, kind, paywall), ...], body, age_hours)."""
    session.add(Cluster(id=cluster_id, window_start=NOW, topics=["ai"]))
    for item_id, sources, body, age in specs:
        session.add(Item(id=item_id, title=item_id, url=f"https://ex.com/{item_id}",
                         canonical_url=f"https://ex.com/{item_id}", teaser="", body=body,
                         published_at=NOW - timedelta(hours=age), first_seen_at=NOW,
                         dated=True, topics=["ai"], raw={}))
        session.add(ClusterItem(cluster_id=cluster_id, item_id=item_id))
        for n, (tier, kind, paywall) in enumerate(sources):
            sid = f"{item_id}-s{n}"
            session.add(Source(id=sid, name=sid, topics=["ai"], tier=tier, kind=kind,
                               url=f"https://feeds/{sid}", paywall=paywall))
            session.add(ItemSource(item_id=item_id, source_id=sid))
    session.flush()


def _ok(url_id, html=HTML, **kw):
    return dict(url=f"https://ex.com/{url_id}", text=html,
                headers={"content-type": "text/html; charset=utf-8"}, **kw)


def test_extract_body_from_fixture():
    body = extract_body(HTML, "https://ex.com/a")
    assert body is not None
    assert "distinctive turning point" in body
    assert "Subscribe Today" not in body
    assert "Trending Now" not in body


def test_extract_body_none_when_short():
    assert extract_body("<html><body><p>Too short.</p></body></html>", "https://ex.com/a") is None


def test_enrich_skips_paywall_and_gnews(session, httpx_mock):
    _setup(session, [
        ("pay", [("mainstream", "rss", True)], None, 1),
        ("gn", [("mainstream", "gnews", False)], None, 2),
        ("ok", [("mainstream", "rss", False)], None, 3),
    ])
    httpx_mock.add_response(**_ok("ok"))
    with httpx.Client() as client:
        assert enrich_clusters(session, ["c1"], client=client) == 1
    assert len(httpx_mock.get_requests()) == 1
    assert "distinctive turning point" in session.get(Item, "ok").body
    assert session.get(Item, "pay").body is None and session.get(Item, "gn").body is None


def test_enrich_tolerates_fetch_failure(session, httpx_mock, caplog):
    _setup(session, [
        ("bad", [("primary", "rss", False)], None, 1),
        ("good", [("mainstream", "rss", False)], None, 2),
    ])
    httpx_mock.add_exception(httpx.ConnectError("boom"), url="https://ex.com/bad")
    httpx_mock.add_response(**_ok("good"))
    with caplog.at_level(logging.WARNING, logger="newshouse.enrich"):
        with httpx.Client() as client:
            assert enrich_clusters(session, ["c1"], client=client) == 1
    assert session.get(Item, "bad").body is None
    assert session.get(Item, "good").body
    assert any("bad" in r.getMessage() for r in caplog.records)


def test_enrich_skips_items_with_body(session, httpx_mock):
    _setup(session, [("has", [("primary", "rss", False)], "existing body", 1)])
    with httpx.Client() as client:
        assert enrich_clusters(session, ["c1"], client=client) == 0
    assert httpx_mock.get_requests() == []
    assert session.get(Item, "has").body == "existing body"


def test_enrich_requires_html_content_type(session, httpx_mock):
    _setup(session, [("pdf", [("primary", "rss", False)], None, 1)])
    httpx_mock.add_response(url="https://ex.com/pdf", content=b"%PDF-1.4",
                            headers={"content-type": "application/pdf"})
    with httpx.Client() as client:
        assert enrich_clusters(session, ["c1"], client=client) == 0
    assert session.get(Item, "pdf").body is None


def test_enrich_orders_by_tier_then_recency_and_caps(session, httpx_mock):
    _setup(session, [
        ("m-new", [("mainstream", "rss", False)], None, 1),
        ("e-old", [("early-signal", "rss", False)], None, 10),
        ("p-old", [("primary", "rss", False)], None, 20),
        ("p-new", [("primary", "rss", False)], None, 2),
    ])
    for i in ("p-new", "p-old", "e-old"):
        httpx_mock.add_response(**_ok(i))
    with httpx.Client() as client:
        assert enrich_clusters(session, ["c1"], client=client) == 3
    assert [r.url.path for r in httpx_mock.get_requests()] == ["/p-new", "/p-old", "/e-old"]
    assert session.get(Item, "m-new").body is None


def test_enrich_stops_at_max_bytes(session, httpx_mock):
    _setup(session, [("big", [("primary", "rss", False)], None, 1)])
    httpx_mock.add_response(**_ok("big", html=HTML + "<!--" + "x" * 50000 + "-->"))
    with httpx.Client() as client:
        assert enrich_clusters(session, ["c1"], client=client, max_bytes=len(HTML)) == 1


def test_extract_image_prefers_og_image():
    html = ('<html><head><meta name="twitter:image" content="https://t.example/tw.jpg">'
            '<meta property="og:image" content="https://o.example/og.jpg">'
            '<meta property="og:image:width" content="1200">'
            '<meta property="og:image:height" content="630"></head></html>')
    assert extract_image(html) == ("https://o.example/og.jpg", 1200, 630)


def test_extract_image_rejects_non_https():
    for bad in ["/a.jpg", "http://x/a.jpg", "data:image/png;base64,AA", "javascript:alert(1)"]:
        html = f'<head><meta property="og:image" content="{bad}"></head>'
        assert extract_image(html) == (None, None, None), bad
    html = ('<head><meta property="og:image" content="http://x/a.jpg">'
            '<meta name="twitter:image" content="https://ok.example/b.jpg"></head>')
    assert extract_image(html)[0] == "https://ok.example/b.jpg"


def test_enrich_stores_image_even_without_body(session, httpx_mock):
    _setup(session, [("a", [("mainstream", "rss", False)], None, 1)])
    page = ('<html><head><meta property="og:image" content="https://img.example/a.jpg">'
            '<meta property="og:image:width" content="800"></head>'
            '<body><p>Too short.</p></body></html>')
    httpx_mock.add_response(**_ok("a", html=page))
    with httpx.Client() as client:
        assert enrich_clusters(session, ["c1"], client=client) == 0
    it = session.get(Item, "a")
    assert it.body is None and it.image_url == "https://img.example/a.jpg"
    assert it.image_w == 800 and it.image_h is None
