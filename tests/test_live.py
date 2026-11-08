import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from newshouse.edition_config import EditionConfig
from newshouse.live import cpcb_aqi, cpcb_band, fetch_aqi, fetch_live, fetch_next_match

# a trimmed copy of ESPN's real schedule for team 83, fetched 2026-11-03
ESPN = json.loads((Path(__file__).parent / "fixtures" / "espn_schedule_83.json").read_text())
AIR = {"latitude": 28.5, "longitude": 77.0, "current_units": {"pm2_5": "μg/m³", "pm10": "μg/m³"},
       "current": {"time": "2026-11-03T14:00", "interval": 3600, "pm2_5": 45.0, "pm10": 60.0}}
CFG = EditionConfig(live={"aqi": {"provider": "open-meteo", "lat": 28.4595, "lon": 77.0266},
                          "fixtures": {"provider": "espn", "team": "barcelona", "team_id": 83}})
NOW = datetime(2026, 11, 3, 6, 0, tzinfo=timezone.utc)


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def ok_both(request):
    if request.url.host == "air-quality-api.open-meteo.com":
        return httpx.Response(200, json=AIR)
    if request.url.host == "site.api.espn.com":
        return httpx.Response(200, json=ESPN)
    return httpx.Response(404)


def test_cpcb_aqi_breakpoints():
    assert cpcb_aqi(45, None) == 75
    assert cpcb_aqi(None, 300) == 250
    assert 400 < cpcb_aqi(300, None) <= 500
    assert cpcb_aqi(2000, 2000) == 500
    assert cpcb_aqi(None, None) is None
    assert cpcb_aqi(0, 0) == 0
    assert cpcb_aqi(45, 300) == 250  # the higher sub-index wins
    assert cpcb_aqi(30, None) == 50 and cpcb_aqi(None, 100) == 100


def test_cpcb_band():
    assert cpcb_band(40) == ("Good", "good")
    assert cpcb_band(75) == ("Satisfactory", "good")
    assert cpcb_band(150) == ("Moderate", "butter")
    assert cpcb_band(250) == ("Poor", "tomato")
    assert cpcb_band(350) == ("Very poor", "tomato")
    assert cpcb_band(450) == ("Severe", "tomato")
    assert cpcb_band(100) == ("Satisfactory", "good") and cpcb_band(101) == ("Moderate", "butter")


def _hourly(pm25, pm10, *, start_hour=0):
    """Hourly series from 2026-11-02T00:00 local, one value per hour."""
    times = [f"2026-11-0{2 + (start_hour + h) // 24}T{(start_hour + h) % 24:02d}:00" for h in range(len(pm25))]
    return {"time": times, "pm2_5": pm25, "pm10": pm10}


def test_fetch_aqi_uses_24h_mean_up_to_now():
    # 48 hours: the first 16 at 200 (outside the window), hours 16..39 at 45, then future hours at 900
    pm25 = [200.0] * 16 + [45.0] * 24 + [900.0] * 8
    pm10 = [10.0] * 48
    body = {"current": {"time": "2026-11-03T15:30", "pm2_5": 999.0, "pm10": 999.0},
            "hourly": _hourly(pm25, pm10)}  # hour 39 is 2026-11-03T15:00, the last one up to now
    with client_for(lambda r: httpx.Response(200, json=body)) as c:
        got = fetch_aqi(c, lat=1, lon=2)
    assert got["aqi"] == 75 and got["at"] == "2026-11-03T15:30"


def test_fetch_aqi_ignores_nulls_in_the_mean():
    pm25 = [None] * 16 + [30.0, 60.0] * 12 + [None] * 8  # mean 45 over 24 valid hours
    body = {"current": {"time": "2026-11-03T15:30", "pm2_5": 999.0, "pm10": None},
            "hourly": _hourly(pm25, [None] * 48)}
    with client_for(lambda r: httpx.Response(200, json=body)) as c:
        got = fetch_aqi(c, lat=1, lon=2)
    assert got["aqi"] == 75  # pm10 has no valid hours and no current value: PM2.5 alone


def test_fetch_aqi_falls_back_to_current_under_12_hours():
    pm25 = [None] * 29 + [500.0] * 11 + [None] * 8  # 11 valid hours in the window
    pm10 = [None] * 16 + [300.0] * 24 + [None] * 8
    body = {"current": {"time": "2026-11-03T15:30", "pm2_5": 45.0, "pm10": 10.0},
            "hourly": _hourly(pm25, pm10)}
    with client_for(lambda r: httpx.Response(200, json=body)) as c:
        got = fetch_aqi(c, lat=1, lon=2)
    assert got["aqi"] == 250  # PM2.5 current 45 gives 75; PM10's 24-h mean 300 gives 250


def test_fetch_aqi_parses_current():
    seen = []

    def handler(request):
        seen.append(request.url)
        return httpx.Response(200, json=AIR)

    with client_for(handler) as c:
        got = fetch_aqi(c, lat=28.4595, lon=77.0266)
    assert got == {"aqi": 75, "band": "Satisfactory", "dot": "good", "at": "2026-11-03T14:00"}
    url = seen[0]
    assert str(url).startswith("https://air-quality-api.open-meteo.com/v1/air-quality")
    assert url.params["current"] == "pm2_5,pm10" and url.params["timezone"] == "Asia/Kolkata"
    assert url.params["hourly"] == "pm2_5,pm10" and url.params["past_days"] == "1"
    assert url.params["latitude"] == "28.4595" and url.params["longitude"] == "77.0266"


def test_fetch_next_match_picks_first_future_event_in_ist():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json=ESPN)

    with client_for(handler) as c:
        home = fetch_next_match(c, team_id=83, team_name="barcelona", now=NOW)
        # after the Villa kick-off: the away game at Atlético is next
        away = fetch_next_match(c, team_id=83, team_name="barcelona",
                                now=datetime(2026, 11, 3, 20, 1, tzinfo=timezone.utc))
        far = fetch_next_match(c, team_id=83, team_name="barcelona",
                               now=datetime(2026, 11, 9, tzinfo=timezone.utc))
        none = fetch_next_match(c, team_id=83, team_name="barcelona",
                                now=datetime(2027, 1, 1, tzinfo=timezone.utc))
    assert seen[0] == "https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/83/schedule?fixture=true"
    # 20:00 UTC on Tue 3 Nov is 1:30 am on Wed 4 Nov in IST
    assert home == {"text": "Barça v Aston Villa", "when": "Wed 1:30 am",
                    "iso": "2026-11-03T20:00:00+00:00", "competition": "UEFA Champions League"}
    assert away["text"] == "Atlético Madrid v Barça" and away["when"] == "Mon 1:30 am"
    assert away["competition"] == "Spanish LALIGA"
    # six days or more away carries the date too, so a weekday is not mistaken for this week's
    assert far["text"] == "Barça v Villarreal" and far["when"] == "Sun 22 Nov 6:30 pm"
    assert none is None


@pytest.mark.parametrize("mode", ["500", "timeout", "malformed", "wrong-shape"])
def test_live_fetch_failures_are_silent(mode, caplog):
    def handler(request):
        if mode == "500":
            return httpx.Response(500)
        if mode == "timeout":
            raise httpx.ReadTimeout("slow", request=request)
        if mode == "malformed":
            return httpx.Response(200, content=b"{not json")
        return httpx.Response(200, json={"current": "x", "events": [{"date": "soon"}]})

    with caplog.at_level(logging.WARNING, logger="newshouse.live"), client_for(handler) as c:
        assert fetch_live(c, CFG, now=NOW) == {}
        assert fetch_aqi(c, lat=1, lon=2) is None
        assert fetch_next_match(c, team_id=83, team_name="barcelona", now=NOW) is None
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_fetch_live_combines_and_omits_missing():
    with client_for(ok_both) as c:
        both = fetch_live(c, CFG, now=NOW)
    assert set(both) == {"aqi", "match"} and both["aqi"]["aqi"] == 75
    assert both["match"]["text"] == "Barça v Aston Villa"

    def air_only(request):
        return httpx.Response(200, json=AIR) if "open-meteo" in request.url.host else httpx.Response(503)

    with client_for(air_only) as c:
        assert set(fetch_live(c, CFG, now=NOW)) == {"aqi"}
    with client_for(ok_both) as c:
        assert fetch_live(c, EditionConfig(), now=NOW) == {}  # nothing configured, nothing fetched


# a trimmed copy of NSE's real allIndices reply (NIFTY 50 and NIFTY BANK), fetched 2026-11-05 13:39 IST
NSE = json.loads((Path(__file__).parent / "fixtures" / "nse_allindices.json").read_text())


def test_fetch_market_parses_nse():
    from newshouse.live import fetch_market
    seen = []

    def handler(request):
        seen.append((request.url.host, request.url.path, request.headers.get("user-agent", "")))
        return httpx.Response(200, json=NSE)

    snap = fetch_market(client_for(handler))
    assert [(h, p) for h, p, _ in seen] == [("www.nseindia.com", "/api/allIndices")]
    assert "Mozilla" in seen[0][2]
    (nifty,) = snap["indices"]
    row = next(r for r in NSE["data"] if r["index"] == "NIFTY 50")
    assert (nifty["name"], nifty["symbol"]) == ("Nifty 50", "NIFTY 50")
    assert nifty["level"] == row["last"] and nifty["prev_close"] == row["previousClose"]
    assert nifty["change_pct"] == round(row["percentChange"], 2)
    week = round((row["last"] - row["oneWeekAgoVal"]) / row["oneWeekAgoVal"] * 100, 2)
    month = round((row["last"] - row["oneMonthAgoVal"]) / row["oneMonthAgoVal"] * 100, 2)
    year = round((row["last"] - row["oneYearAgoVal"]) / row["oneYearAgoVal"] * 100, 2)
    assert nifty["trend"] == [{"label": "1 week", "pct": week}, {"label": "1 month", "pct": month},
                              {"label": "1 year", "pct": year}]
    assert snap["as_of"] == "2026-11-05T13:39:00+05:30"


def test_market_trend_skips_missing_values():
    from newshouse.live import index_from_nse
    row = {"index": "NIFTY 50", "last": 110.0, "previousClose": 100.0, "percentChange": 10.0,
           "oneWeekAgoVal": 100.0, "oneMonthAgoVal": None, "oneYearAgoVal": 0}
    idx = index_from_nse(row)
    assert idx["change_pct"] == 10.0 and idx["trend"] == [{"label": "1 week", "pct": 10.0}]


def test_fetch_market_failure_is_none(caplog):
    from newshouse.live import fetch_market
    with caplog.at_level(logging.WARNING):
        assert fetch_market(client_for(lambda r: httpx.Response(429))) is None
        assert fetch_market(client_for(lambda r: httpx.Response(200, json={"data": []}))) is None
        assert fetch_market(client_for(lambda r: httpx.Response(200, text="<html>"))) is None
    assert "market fetch failed" in caplog.text


def test_fetch_live_includes_market():
    def handler(request):
        if request.url.host == "www.nseindia.com":
            return httpx.Response(200, json=NSE)
        return ok_both(request)
    out = fetch_live(client_for(handler), CFG, now=NOW)
    assert set(out) == {"aqi", "match", "market"}
    out = fetch_live(client_for(ok_both), CFG, now=NOW)
    assert "market" not in out
