"""Fetch article bodies for shortlisted clusters. Failures are logged, never raised."""
from __future__ import annotations

import logging
from html.parser import HTMLParser
from urllib.parse import urlsplit

import httpx
import trafilatura
from sqlalchemy import select

from newshouse.fetch.feeds import USER_AGENT
from newshouse.models import ClusterItem, Item, ItemSource, Source

log = logging.getLogger("newshouse.enrich")

MIN_BODY_CHARS = 300
SKIP_KINDS = {"gnews", "reddit", "youtube", "podcast", "x", "scrape", "api"}
TIER_ORDER = {"primary": 0, "early-signal": 1, "mainstream": 2}


def extract_body(html: str, url: str) -> str | None:
    text = trafilatura.extract(html, url=url, include_comments=False,
                               include_tables=False, favor_precision=True)
    if not text or len(text) < MIN_BODY_CHARS:
        return None
    return text


class _ImageMeta(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.og: list[str] = []
        self.twitter: list[str] = []
        self.link: list[str] = []
        self.width: int | None = None
        self.height: int | None = None

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "").strip() for k, v in attrs if k}
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            val = a.get("content", "")
            if key in ("og:image", "og:image:secure_url"):
                self.og.append(val)
            elif key == "twitter:image":
                self.twitter.append(val)
            elif key in ("og:image:width", "og:image:height"):
                try:
                    n = int(val)
                except ValueError:
                    return
                if key.endswith("width") and self.width is None:
                    self.width = n
                elif key.endswith("height") and self.height is None:
                    self.height = n
        elif tag == "link" and a.get("rel", "").lower() == "image_src":
            self.link.append(a.get("href", ""))


def _https_url(u: str) -> bool:
    try:
        parts = urlsplit(u)
    except ValueError:
        return False
    return parts.scheme.lower() == "https" and bool(parts.netloc)


def extract_image(html: str) -> tuple[str | None, int | None, int | None]:
    """First absolute https preview image: og:image, twitter:image, link image_src."""
    parser = _ImageMeta()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - malformed markup must not abort enrichment
        pass
    for url in parser.og + parser.twitter + parser.link:
        if _https_url(url):
            if url in parser.og:
                return url, parser.width, parser.height
            return url, None, None
    return None, None, None


def _best_tier(sources: list[Source]) -> int:
    return min(TIER_ORDER.get(s.tier, len(TIER_ORDER)) for s in sources)


def _fetch_html(client: httpx.Client, url: str, max_bytes: int) -> str | None:
    with client.stream("GET", url, headers={"User-Agent": USER_AGENT},
                       follow_redirects=True, timeout=15.0) as resp:
        if not resp.is_success:
            return None
        if "text/html" not in resp.headers.get("content-type", "").lower():
            return None
        buf = bytearray()
        for chunk in resp.iter_bytes():
            buf.extend(chunk)
            if len(buf) >= max_bytes:
                break
        encoding = resp.charset_encoding or "utf-8"
    try:
        return bytes(buf[:max_bytes]).decode(encoding, errors="replace")
    except LookupError:
        return bytes(buf[:max_bytes]).decode("utf-8", errors="replace")


def enrich_clusters(session, cluster_ids: list[str], *, client: httpx.Client,
                    max_items_per_cluster: int = 3, max_bytes: int = 2_000_000) -> int:
    stored = 0
    for cid in cluster_ids:
        rows = session.execute(
            select(Item, Source).join(ClusterItem, ClusterItem.item_id == Item.id)
            .join(ItemSource, ItemSource.item_id == Item.id)
            .join(Source, Source.id == ItemSource.source_id)
            .where(ClusterItem.cluster_id == cid)).all()
        items: dict[str, tuple[Item, list[Source]]] = {}
        for item, source in rows:
            items.setdefault(item.id, (item, []))[1].append(source)

        candidates = []
        for item, sources in items.values():
            if item.body:
                continue
            if all(s.paywall for s in sources):
                continue
            if all(s.kind in SKIP_KINDS for s in sources):
                continue
            candidates.append((item, sources))
        candidates.sort(key=lambda t: -t[0].published_at.timestamp())
        candidates.sort(key=lambda t: _best_tier(t[1]))

        for item, sources in candidates[:max_items_per_cluster]:
            try:
                html = _fetch_html(client, item.url, max_bytes)
                if html and any(s.kind != "gnews" for s in sources):
                    item.image_url, item.image_w, item.image_h = extract_image(html)
                body = extract_body(html, item.url) if html else None
            except Exception as exc:  # noqa: BLE001 - enrichment must never abort a run
                log.warning("enrich failed for %s: %s", item.url, exc)
                continue
            if body:
                item.body = body
                stored += 1
        session.flush()
    return stored
