"""HTTP feed fetcher. Never raises on network or parse errors."""
from __future__ import annotations

from dataclasses import dataclass, field

import feedparser
import httpx

from newshouse.fetch.normalize import RawItem, normalize_entry

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class FetchResult:
    ok: bool
    items: list[RawItem] = field(default_factory=list)
    etag: str | None = None
    last_modified: str | None = None
    status: int | None = None
    error: str | None = None


def _looks_like_html(data: bytes) -> bool:
    head = data[:400].lower().strip()
    return head.startswith(b"<!doctype html") or b"<html" in head


def fetch_feed(
    url: str,
    *,
    kind: str,
    etag: str | None = None,
    last_modified: str | None = None,
    client: httpx.Client,
    max_bytes: int = 3_000_000,
    timeout: float = 20.0,
) -> FetchResult:
    headers = {"User-Agent": USER_AGENT}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    status = None
    try:
        with client.stream("GET", url, headers=headers, timeout=timeout, follow_redirects=True) as resp:
            status = resp.status_code
            new_etag = resp.headers.get("etag") or etag
            new_lm = resp.headers.get("last-modified") or last_modified
            if status == 304:
                return FetchResult(True, [], etag, last_modified, 304, None)
            if not 200 <= status < 300:
                return FetchResult(False, [], etag, last_modified, status, f"http {status}")
            buf = bytearray()
            for chunk in resp.iter_bytes():
                buf.extend(chunk)
                if len(buf) >= max_bytes:
                    del buf[max_bytes:]
                    break
        data = bytes(buf)
        if _looks_like_html(data):
            return FetchResult(False, [], new_etag, new_lm, status, "html")
        parsed = feedparser.parse(data)
        if not parsed.entries and parsed.get("bozo"):
            return FetchResult(False, [], new_etag, new_lm, status, f"parse: {parsed.get('bozo_exception')}")
        items = [normalize_entry(e, kind) for e in parsed.entries]
        return FetchResult(True, items, new_etag, new_lm, status, None)
    except httpx.HTTPError as e:
        return FetchResult(False, [], etag, last_modified, status, f"{type(e).__name__}: {e}"[:200])
    except Exception as e:  # parse or unexpected
        return FetchResult(False, [], etag, last_modified, status, f"parse: {e}"[:200])
