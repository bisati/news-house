from datetime import datetime, timezone

import pytest

from newshouse.config import Settings
from newshouse.fetch.reddit import RedditClient, parse_reddit_url, subreddit_from_url
from newshouse.ingest import ingest
from newshouse.models import Item, Source
from newshouse.sources import source_id

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
SEARCH_URL = ("https://www.reddit.com/r/developersIndia/search.rss?q=%22Coding+Ninjas%22+OR+"
              "%22Scaler%22&restrict_sr=on&sort=new")


@pytest.fixture
def settings_with_reddit():
    return Settings(_env_file=None, reddit_client_id="cid", reddit_client_secret="sec",
                    reddit_username="u", reddit_password="pw",
                    reddit_user_agent="macos:news-house:0.1 (by /u/u)")


@pytest.fixture
def settings_without_reddit():
    return Settings(_env_file=None)


def listing(*posts):
    return {"data": {"children": [{"kind": "t3", "data": p} for p in posts]}}


def post(n, **kw):
    d = {"name": f"t3_{n}", "title": f"Post {n}", "permalink": f"/r/LocalLLaMA/comments/{n}/x/",
         "selftext": "", "url": f"https://example.com/{n}", "author": "bob",
         "created_utc": 1761825600.0, "score": 10, "num_comments": 3, "is_self": False,
         "subreddit": "LocalLLaMA"}
    d.update(kw)
    return d


def test_password_grant_token_cached(httpx_mock, httpx_client, settings_with_reddit):
    httpx_mock.add_response(url=TOKEN_URL, method="POST",
                            json={"access_token": "tok", "expires_in": 86400})
    httpx_mock.add_response(json=listing(post(1)), is_reusable=True,
                            url="https://oauth.reddit.com/r/LocalLLaMA/top?t=day&limit=25&raw_json=1")
    rc = RedditClient(settings_with_reddit, httpx_client)
    assert rc.fetch_top("LocalLLaMA").ok and rc.fetch_top("LocalLLaMA").ok
    reqs = httpx_mock.get_requests()
    tokens = [r for r in reqs if str(r.url) == TOKEN_URL]
    assert len(tokens) == 1
    assert b"grant_type=password" in tokens[0].content
    assert tokens[0].headers["authorization"].startswith("Basic ")
    assert tokens[0].headers["user-agent"] == "macos:news-house:0.1 (by /u/u)"
    lst = [r for r in reqs if r.url.host == "oauth.reddit.com"][0]
    assert lst.headers["authorization"] == "bearer tok"


def test_refresh_token_grant(httpx_mock, httpx_client):
    s = Settings(_env_file=None, reddit_client_id="c", reddit_client_secret="s",
                 reddit_refresh_token="rt")
    httpx_mock.add_response(url=TOKEN_URL, method="POST", json={"access_token": "t2"})
    assert RedditClient(s, httpx_client).token() == "t2"
    assert b"grant_type=refresh_token" in httpx_mock.get_requests()[0].content


def test_fetch_top_maps_posts(httpx_mock, httpx_client, settings_with_reddit):
    httpx_mock.add_response(url=TOKEN_URL, method="POST", json={"access_token": "tok"})
    httpx_mock.add_response(json=listing(
        post(1, selftext="body text"), post(2)))
    res = RedditClient(settings_with_reddit, httpx_client).fetch_top("LocalLLaMA")
    assert res.ok and len(res.items) == 2
    a, b = res.items
    assert a.url == "https://www.reddit.com/r/LocalLLaMA/comments/1/x/"
    assert a.guid == "t3_1" and a.teaser == "body text" and a.author == "bob"
    assert a.published_at == datetime(2025, 10, 30, 12, 0, tzinfo=timezone.utc)
    assert b.teaser == "https://example.com/2"
    assert a.raw["subreddit"] == "LocalLLaMA" and a.raw["score"] == 10
    assert a.raw["url"] == "https://example.com/1" and a.raw["is_self"] is False


def test_no_credentials_is_failure_not_exception(settings_without_reddit, httpx_client):
    res = RedditClient(settings_without_reddit, httpx_client).fetch_top("x")
    assert not res.ok and res.error == "reddit: no credentials"


def test_listing_http_error(httpx_mock, httpx_client, settings_with_reddit):
    httpx_mock.add_response(url=TOKEN_URL, method="POST", json={"access_token": "tok"})
    httpx_mock.add_response(status_code=403)
    res = RedditClient(settings_with_reddit, httpx_client).fetch_top("x")
    assert not res.ok and res.error == "reddit: http 403" and res.status == 403


def test_token_failure_does_not_raise(httpx_mock, httpx_client, settings_with_reddit):
    httpx_mock.add_response(url=TOKEN_URL, method="POST", status_code=401)
    res = RedditClient(settings_with_reddit, httpx_client).fetch_top("x")
    assert not res.ok and "401" in res.error


def test_parse_search_url():
    q = parse_reddit_url(SEARCH_URL)
    assert q.mode == "search" and q.subreddit == "developersIndia"
    assert q.params["q"] == '"Coding Ninjas" OR "Scaler"'
    assert q.params["sort"] == "new"


def test_parse_top_url_and_subreddit_from_url():
    u = "https://www.reddit.com/r/LocalLLaMA/top/.rss?t=day"
    q = parse_reddit_url(u)
    assert (q.mode, q.subreddit, q.params) == ("top", "LocalLLaMA", {"t": "day"})
    assert subreddit_from_url(u) == "LocalLLaMA"


def test_search_listing_request(httpx_mock, httpx_client, settings_with_reddit):
    httpx_mock.add_response(url=TOKEN_URL, method="POST", json={"access_token": "tok"})
    httpx_mock.add_response(json=listing())
    res = RedditClient(settings_with_reddit, httpx_client).fetch_listing(parse_reddit_url(SEARCH_URL))
    assert res.ok and res.items == []
    url = httpx_mock.get_requests()[-1].url
    assert url.path == "/r/developersIndia/search"
    p = dict(url.params)
    assert p["q"] == '"Coding Ninjas" OR "Scaler"' and p["restrict_sr"] == "1"
    assert p["sort"] == "new" and p["limit"] == "25" and p["raw_json"] == "1"


def test_ingest_dispatches_reddit_kind(session, httpx_mock, httpx_client, settings_with_reddit):
    url = "https://www.reddit.com/r/LocalLLaMA/top/.rss?t=day"
    session.add(Source(id=source_id(url), name="r", topics=["ai-models"], tier="primary",
                       kind="reddit", url=url, home=url, paywall=False))
    session.flush()
    httpx_mock.add_response(url=TOKEN_URL, method="POST", json={"access_token": "tok"})
    httpx_mock.add_response(json=listing(post(1), post(2)))
    stats = ingest(session, now=NOW, client=httpx_client,
                   reddit=RedditClient(settings_with_reddit, httpx_client))
    assert stats.sources_ok == 1 and stats.items_new == 2
    assert session.query(Item).count() == 2


def test_ingest_reddit_without_credentials_records_failure(session, httpx_client,
                                                            settings_without_reddit):
    url = "https://www.reddit.com/r/LocalLLaMA/top/.rss?t=day"
    session.add(Source(id=source_id(url), name="r", topics=["ai-models"], tier="primary",
                       kind="reddit", url=url, home=url, paywall=False))
    session.flush()
    stats = ingest(session, now=NOW, client=httpx_client,
                   reddit=RedditClient(settings_without_reddit, httpx_client))
    assert stats.sources_failed == {url: "reddit: no credentials"}
