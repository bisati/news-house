"""Turn feedparser entries into normalised RawItem records."""
from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TEASER_MAX = 1500
_TRACKING = {"fbclid", "gclid", "igshid", "mc_cid", "mc_eid", "ref", "source"}


@dataclass
class RawItem:
    title: str
    url: str
    guid: str | None
    teaser: str
    author: str | None
    published_at: datetime | None
    raw: dict


class _Stripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag, attrs) -> None:
        self.parts.append(" ")

    def handle_endtag(self, tag) -> None:
        self.parts.append(" ")


def strip_html(text: str) -> str:
    p = _Stripper()
    p.feed(text or "")
    p.close()
    out = html.unescape("".join(p.parts)).replace("\xa0", " ")
    return re.sub(r"\s+", " ", out).strip()


def detect_lang(title: str | None) -> str:
    """Cheap script check: "hi" when >= 30% of the title's letters are Devanagari."""
    letters = [ch for ch in (title or "") if ch.isalpha() or "\u0900" <= ch <= "\u097f"]
    if not letters:
        return "en"
    deva = sum(1 for ch in letters if "\u0900" <= ch <= "\u097f")
    return "hi" if deva / len(letters) >= 0.30 else "en"


def canonical_url(url: str) -> str:
    if not url:
        return ""
    s = urlsplit(url.strip())
    query = [
        (k, v)
        for k, v in parse_qsl(s.query, keep_blank_values=True)
        if not k.startswith("utm_") and k not in _TRACKING
    ]
    path = s.path.rstrip("/")
    return urlunsplit((s.scheme.lower(), s.netloc.lower(), path, urlencode(query), ""))


def item_id(source_url: str, raw: RawItem) -> str:
    key = canonical_url(raw.url) or raw.guid or f"{source_url}|{raw.title}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def _dt(entry) -> datetime | None:
    for name in ("published_parsed", "updated_parsed"):
        t = dict.get(entry, name)  # bypass feedparser's deprecated alias
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except (ValueError, OverflowError, TypeError):
                continue
    return None


def normalize_entry(entry, kind: str) -> RawItem:
    title = (entry.get("title") or "").strip()
    url = (entry.get("link") or "").strip()
    body = entry.get("summary") or entry.get("description") or ""
    if kind == "youtube" and not body:
        body = entry.get("media_description") or ""
    teaser = strip_html(body)[:TEASER_MAX]
    raw: dict = {
        "title": title,
        "link": url,
        "id": entry.get("id"),
        "author": entry.get("author"),
        "published": dict.get(entry, "published") or dict.get(entry, "updated"),
        "tags": [t.get("term") for t in entry.get("tags", []) if t.get("term")],
    }
    if kind == "hn" and entry.get("comments"):
        raw["comments"] = entry["comments"]
    if kind == "gnews":
        src = entry.get("source")
        if src:
            if src.get("title"):
                raw["publisher"] = src["title"]
            if src.get("href"):
                raw["publisher_domain"] = urlsplit(src["href"]).netloc.lower()
    return RawItem(
        title=title,
        url=url,
        guid=entry.get("id") or None,
        teaser=teaser,
        author=entry.get("author") or None,
        published_at=_dt(entry),
        raw=raw,
    )
