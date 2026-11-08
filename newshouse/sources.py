"""Load the source map from YAML and sync it into the database."""
import hashlib
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from newshouse.models import Source

_FIELDS = ("name", "tier", "kind", "home", "paywall", "last7d")


def load_sources(path: Path) -> list[dict]:
    """Parse the YAML list; entries sharing a url merge (first wins, topics unioned)."""
    entries = yaml.safe_load(Path(path).read_text()) or []
    by_url: dict[str, dict] = {}
    for e in entries:
        url = e["url"]
        if url in by_url:
            by_url[url]["topics"] = sorted(set(by_url[url]["topics"]) | {e["topic"]})
            continue
        spec = {k: e.get(k) for k in _FIELDS}
        spec["paywall"] = bool(spec["paywall"])
        spec["url"] = url
        spec["topics"] = [e["topic"]]
        by_url[url] = spec
    return list(by_url.values())


def source_id(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:16]


def sync_sources(session: Session, specs: list[dict]) -> int:
    """Upsert by url. Existing rows keep enabled/etag/last_modified/last_ok_at."""
    existing = {s.url: s for s in session.scalars(select(Source))}
    for spec in specs:
        row = existing.get(spec["url"])
        if row is None:
            row = Source(id=source_id(spec["url"]), url=spec["url"], enabled=True)
            session.add(row)
            existing[spec["url"]] = row
        for k in ("name", "tier", "kind", "home", "paywall", "last7d"):
            setattr(row, k, spec[k])
        row.topics = list(spec["topics"])
    return len(specs)
