from pathlib import Path

import yaml

from newshouse.models import Source
from newshouse.sources import load_sources, sync_sources

REAL = Path(__file__).parent.parent / "sources" / "sources.yaml"


def entry(topic, url="https://a.example/feed", **kw):
    d = {"topic": topic, "name": "A", "tier": "primary", "kind": "rss", "url": url,
         "home": "https://a.example", "verified": True, "last7d": 5, "latest": "x",
         "paywall": False, "why": "w", "note": None}
    d.update(kw)
    return d


def test_load_sources_merges_duplicate_urls(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text(yaml.safe_dump([entry("b"), entry("a"), entry("a", url="https://z.example/f", name="Z")]))
    specs = load_sources(p)
    assert len(specs) == 2
    by = {s["url"]: s for s in specs}
    assert by["https://a.example/feed"]["topics"] == ["a", "b"]
    assert by["https://a.example/feed"]["name"] == "A"
    assert by["https://a.example/feed"]["last7d"] == 5
    assert by["https://z.example/f"]["topics"] == ["a"]


def test_sync_sources_upserts(session):
    specs = load_sources(REAL)
    assert sync_sources(session, specs) == 274
    session.flush()
    assert session.query(Source).count() == 274
    s = session.query(Source).first()
    s.enabled = False
    s.etag = "keep"
    session.flush()
    assert sync_sources(session, specs) == 274
    session.flush()
    assert session.query(Source).count() == 274
    s2 = session.get(Source, s.id)
    assert s2.enabled is False and s2.etag == "keep"
    assert len(s.id) == 16


REQUIRED = {"topic", "name", "tier", "kind", "url", "verified", "last7d", "latest", "paywall", "why"}


def test_real_sources_cover_ai_tools_and_startups():
    raw = yaml.safe_load(REAL.read_text())
    for e in raw:
        assert REQUIRED <= set(e), (e.get("name"), REQUIRED - set(e))
    specs = load_sources(REAL)
    for topic in ("ai-tools", "startups"):
        assert sum(1 for s in specs if topic in s["topics"]) >= 4, topic
    by = {s["url"]: s for s in specs}
    assert {"ai-built", "ai-tools"} <= set(by["https://www.bensbites.com/feed"]["topics"])
