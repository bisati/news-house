"""Reddit via the official OAuth API (anonymous feed polling gets 429)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import parse_qsl, urlparse

import httpx

from newshouse.fetch.feeds import FetchResult
from newshouse.fetch.normalize import RawItem

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API = "https://oauth.reddit.com"
TOKEN_TTL = 55 * 60
DEFAULT_UA = "macos:news-house:0.1"


@dataclass
class RedditQuery:
    subreddit: str
    mode: Literal["top", "search"]
    params: dict[str, str] = field(default_factory=dict)


def parse_reddit_url(url: str) -> RedditQuery:
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2 or parts[0] != "r":
        raise ValueError(f"not a reddit subreddit url: {url}")
    params = dict(parse_qsl(parsed.query))
    mode = "search" if len(parts) > 2 and parts[2].startswith("search") else "top"
    return RedditQuery(parts[1], mode, params)


def subreddit_from_url(url: str) -> str:
    return parse_reddit_url(url).subreddit


def _post_to_item(p: dict) -> RawItem:
    selftext = p.get("selftext") or ""
    return RawItem(
        title=p["title"], url="https://www.reddit.com" + p["permalink"], guid=p["name"],
        teaser=selftext[:1500] if selftext else p.get("url"), author=p.get("author"),
        published_at=datetime.fromtimestamp(p["created_utc"], tz=timezone.utc),
        raw={"subreddit": p.get("subreddit"), "score": p.get("score"),
             "num_comments": p.get("num_comments"), "url": p.get("url"),
             "is_self": p.get("is_self"), "permalink": p["permalink"]})


class RedditClient:
    def __init__(self, settings, http: httpx.Client):
        self.s = settings
        self.http = http
        self._token: str | None = None
        self._expires = 0.0

    @property
    def _ua(self) -> str:
        return self.s.reddit_user_agent or DEFAULT_UA

    def has_credentials(self) -> bool:
        if not (self.s.reddit_client_id and self.s.reddit_client_secret):
            return False
        return bool(self.s.reddit_password or self.s.reddit_refresh_token)

    def token(self) -> str:
        if self._token and time.monotonic() < self._expires:
            return self._token
        if self.s.reddit_password:
            data = {"grant_type": "password", "username": self.s.reddit_username or "",
                    "password": self.s.reddit_password}
        else:
            data = {"grant_type": "refresh_token", "refresh_token": self.s.reddit_refresh_token}
        r = self.http.post(TOKEN_URL, data=data, headers={"User-Agent": self._ua},
                           auth=(self.s.reddit_client_id, self.s.reddit_client_secret))
        if r.status_code != 200:
            raise RuntimeError(f"reddit token request failed: http {r.status_code}")
        tok = r.json().get("access_token")
        if not tok:
            raise RuntimeError("reddit token response had no access_token")
        self._token, self._expires = tok, time.monotonic() + TOKEN_TTL
        return tok

    def fetch_listing(self, query: RedditQuery, *, limit: int = 25) -> FetchResult:
        if not self.has_credentials():
            return FetchResult(ok=False, error="reddit: no credentials")
        try:
            sub, p = query.subreddit, query.params
            if query.mode == "top":
                path, params = f"/r/{sub}/top", {"t": p.get("t", "day")}
            else:
                params = {"q": p.get("q", ""), "restrict_sr": "1", "sort": p.get("sort", "new")}
                if "t" in p:
                    params["t"] = p["t"]
                path = f"/r/{sub}/search"
            params |= {"limit": str(limit), "raw_json": "1"}
            r = self.http.get(API + path, params=params, headers={
                "Authorization": f"bearer {self.token()}", "User-Agent": self._ua})
            if r.status_code != 200:
                return FetchResult(ok=False, status=r.status_code,
                                   error=f"reddit: http {r.status_code}")
            children = r.json()["data"]["children"]
            items = [_post_to_item(c["data"]) for c in children if c.get("kind") == "t3"]
            return FetchResult(ok=True, items=items, status=200)
        except Exception as exc:  # never raise out of the adapter
            return FetchResult(ok=False, error=f"reddit: {type(exc).__name__}: {exc}")

    def fetch_top(self, subreddit: str, *, t: str = "day", limit: int = 25) -> FetchResult:
        return self.fetch_listing(RedditQuery(subreddit, "top", {"t": t}), limit=limit)
