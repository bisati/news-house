from datetime import datetime, timedelta, timezone

from newshouse.health import check_sources
from newshouse.models import Run, Source
from newshouse.sources import source_id

NOW = datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc)


def add_source(session, url, kind="rss", **kw):
    s = Source(id=source_id(url), name=url, topics=["ai-models"], tier="primary", kind=kind,
               url=url, home=url, paywall=False, **kw)
    session.add(s)
    session.flush()
    return s


def feed(*dates):
    body = "".join(
        f"<item><title>t{i}</title><link>https://x/{i}</link><guid>https://x/{i}</guid>"
        f"<pubDate>{d.strftime('%a, %d %b %Y %H:%M:%S GMT')}</pubDate></item>"
        for i, d in enumerate(dates))
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>{body}</channel></rss>'.encode()


def test_health_reports_dead_sources(session, httpx_mock, httpx_client):
    bad = add_source(session, "https://bad.example/feed")
    good = add_source(session, "https://good.example/feed", last7d=99)
    for _ in range(3):
        httpx_mock.add_response(url=bad.url, status_code=404)
    httpx_mock.add_response(url=good.url, content=feed(NOW - timedelta(days=1), NOW - timedelta(days=3),
                                                       NOW - timedelta(days=20)))
    reports = []
    for i in range(3):
        if i:
            httpx_mock.add_response(url=good.url, content=feed(NOW + timedelta(days=7 * i - 1)))
        reports.append(check_sources(session, client=httpx_client, now=NOW + timedelta(days=7 * i)))
    assert reports[0]["dead"] == [] and reports[1]["dead"] == []
    last = reports[2]
    assert last["dead"] == [bad.url] and bad.url in last["failed"] and last["checked"] == 2
    assert good.last7d == 1 and good.last_ok_at == NOW + timedelta(days=14)
    assert bad.enabled is True
    runs = session.query(Run).filter(Run.kind == "health").count()
    assert runs == 3


def test_health_marks_sources_with_nothing_in_30_days(session, httpx_mock, httpx_client):
    old = add_source(session, "https://old.example/feed")
    off = add_source(session, "https://off.example/feed", enabled=False)
    reddit = add_source(session, "https://reddit.example/r", kind="reddit")
    httpx_mock.add_response(url=old.url, content=feed(NOW - timedelta(days=40)))
    r = check_sources(session, client=httpx_client, now=NOW)
    assert r["stale30"] == [old.url] and r["dead"] == [old.url] and r["checked"] == 1
    assert old.last7d == 0 and old.last_ok_at == NOW and old.enabled is True
    assert off.last_ok_at is None and reddit.last_ok_at is None


def test_health_run_finishes_on_wall_clock(session, httpx_client):
    from freezegun import freeze_time
    later = NOW + timedelta(minutes=7)
    with freeze_time(later):
        check_sources(session, client=httpx_client, now=NOW)
    r = session.query(Run).filter(Run.kind == "health").one()
    assert r.started_at == NOW and r.finished_at == later
