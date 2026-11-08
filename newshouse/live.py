"""Live tiles: Gurgaon air quality now and Barça's next match (spec 3.8).

Both sources are keyless and allow cross-origin reads, so the page refreshes them too
(``liveTiles`` in ``edition.js`` uses the same URLs). Air quality is India's CPCB AQI
estimated from Open-Meteo's PM2.5 and PM10 (Ruling 5); fixtures come from ESPN's public
team schedule (Ruling 6). A fetch never raises: failures log at warning and give None.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from newshouse.edition_config import EditionConfig

log = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
AQI_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
SCHEDULE_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/{team_id}/schedule?fixture=true"
SHORT_NAMES = {"barcelona": "Barça"}
NSE_URL = "https://www.nseindia.com/api/allIndices"  # no key; refuses requests without a browser UA
NSE_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                             "(KHTML, like Gecko) Chrome/130.0 Safari/537.36", "Accept": "application/json"}
INDICES = (("Nifty 50", "NIFTY 50"),)  # NSE has no Sensex; BSE refuses scripts (2026-11-05)
TREND = (("1 week", "oneWeekAgoVal"), ("1 month", "oneMonthAgoVal"), ("1 year", "oneYearAgoVal"))

# CPCB breakpoints: (concentration low, high) per AQI band (low, high)
_AQI_BANDS = ((0, 50), (51, 100), (101, 200), (201, 300), (301, 400), (401, 500))
_PM25 = ((0, 30), (31, 60), (61, 90), (91, 120), (121, 250), (251, 380))
_PM10 = ((0, 50), (51, 100), (101, 250), (251, 350), (351, 430), (431, 510))
_LABELS = ("Good", "Satisfactory", "Moderate", "Poor", "Very poor", "Severe")
_DOTS = ("good", "good", "butter", "tomato", "tomato", "tomato")


def _sub_index(conc: float | None, table) -> float | None:
    if conc is None:
        return None
    conc = max(0.0, float(conc))
    for (b_lo, b_hi), (i_lo, i_hi) in zip(table, _AQI_BANDS):
        if conc <= b_hi:
            return i_lo + (i_hi - i_lo) * (conc - b_lo) / (b_hi - b_lo)
    return 500.0  # above the last breakpoint


def cpcb_aqi(pm25: float | None, pm10: float | None) -> int | None:
    """CPCB AQI from PM2.5 and PM10 (µg/m³): the higher sub-index, capped at 500."""
    subs = [s for s in (_sub_index(pm25, _PM25), _sub_index(pm10, _PM10)) if s is not None]
    if not subs:
        return None
    return int(min(500, max(0, round(max(subs)))))


def cpcb_band(aqi: int) -> tuple[str, str]:
    """``(label, dot)`` for an AQI: Good and Satisfactory are good, Moderate butter, worse tomato."""
    for n, (_, hi) in enumerate(_AQI_BANDS):
        if aqi <= hi:
            return _LABELS[n], _DOTS[n]
    return _LABELS[-1], _DOTS[-1]


def aqi_url(*, lat: float, lon: float) -> str:
    return AQI_URL + "?" + urlencode({"latitude": lat, "longitude": lon, "current": "pm2_5,pm10",
                                      "hourly": "pm2_5,pm10", "past_days": 1,
                                      "timezone": "Asia/Kolkata"}, safe=",/")


MIN_HOURS = 12  # fewer valid hours than this in the 24-h window: use the current value


def _avg_24h(hourly: dict, key: str, upto: str | None, current: float | None) -> float | None:
    """Mean of the last 24 hourly values at or before ``upto`` (local ISO, as Open-Meteo
    sends it), ignoring nulls; ``current`` when fewer than MIN_HOURS are valid."""
    times, values = hourly.get("time") or [], hourly.get(key) or []
    window = [v for t, v in zip(times, values) if upto is None or str(t) <= upto][-24:]
    valid = [float(v) for v in window if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if len(valid) < MIN_HOURS:
        return current
    return sum(valid) / len(valid)


def schedule_url(team_id: int) -> str:
    return SCHEDULE_URL.format(team_id=int(team_id))


def _get_json(client, url: str):
    resp = client.get(url, timeout=10.0)
    resp.raise_for_status()
    return resp.json()


def fetch_aqi(client, *, lat: float, lon: float) -> dict | None:
    """``{"aqi", "band", "dot", "at"}`` from Open-Meteo's PM2.5/PM10, or None. CPCB sub-indices
    are defined on 24-hour averages, so each pollutant is the mean of the last 24 hourly
    values up to now, falling back to the current value when too few hours are valid."""
    try:
        data = _get_json(client, aqi_url(lat=lat, lon=lon))
        cur, hourly = data["current"], data.get("hourly") or {}
        upto = cur.get("time")
        aqi = cpcb_aqi(_avg_24h(hourly, "pm2_5", upto, cur.get("pm2_5")),
                       _avg_24h(hourly, "pm10", upto, cur.get("pm10")))
        if aqi is None:
            log.warning("air quality: no PM2.5 or PM10 in the reply")
            return None
        band, dot = cpcb_band(aqi)
        return {"aqi": aqi, "band": band, "dot": dot, "at": cur.get("time")}
    except Exception as e:  # a tile never fails a build
        log.warning("air quality fetch failed: %r", e)
        return None


def _clock(dt: datetime) -> str:
    hour = dt.hour % 12 or 12
    mins = f":{dt.minute:02d}" if dt.minute else ""
    return f"{hour}{mins} {'am' if dt.hour < 12 else 'pm'}"


def match_when(kickoff: datetime, now: datetime) -> str:
    """``Wed 1:30 am`` in IST; six days or more ahead also gives the date (``Sun 22 Nov 6:30 pm``)."""
    local = kickoff.astimezone(IST)
    day = f"{local:%a}" if kickoff - now < timedelta(days=6) else f"{local:%a} {local.day} {local:%b}"
    return f"{day} {_clock(local)}"


def _parse_date(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def fetch_next_match(client, *, team_id: int, team_name: str, now: datetime) -> dict | None:
    """The first ESPN schedule event after ``now``: ``{"text", "when", "iso", "competition"}``."""
    try:
        events = _get_json(client, schedule_url(team_id)).get("events") or []
        upcoming = sorted(((_parse_date(e["date"]), e) for e in events), key=lambda p: p[0])
        upcoming = [(k, e) for k, e in upcoming if k > now]
        if not upcoming:
            return None
        kickoff, ev = upcoming[0]
        ours = SHORT_NAMES.get(team_name.lower(), team_name)
        names = {}
        for comp in ev["competitions"][0]["competitors"]:
            team = comp.get("team") or {}
            mine = str(team.get("id")) == str(team_id) or \
                (team.get("displayName") or "").lower() == team_name.lower()
            names[comp["homeAway"]] = ours if mine else team.get("displayName", "")
        league = ev.get("league") or ev["competitions"][0].get("league") or {}
        return {"text": f"{names['home']} v {names['away']}", "when": match_when(kickoff, now),
                "iso": kickoff.isoformat(), "competition": league.get("name", "")}
    except Exception as e:  # a tile never fails a build
        log.warning("next match fetch failed: %r", e)
        return None


def index_from_nse(row: dict, name: str = "Nifty 50") -> dict:
    """One index from a row of NSE's allIndices reply. ``change_pct`` is NSE's day change
    (``last`` against ``previousClose``); ``trend`` is ``last`` against the value a week, a
    month and a year ago, leaving out any NSE does not give."""
    level = float(row["last"])
    trend = []
    for label, key in TREND:
        then = row.get(key)
        if isinstance(then, (int, float)) and not isinstance(then, bool) and then > 0:
            trend.append({"label": label, "pct": round((level - then) / then * 100, 2)})
    return {"name": name, "symbol": row["index"], "level": level,
            "prev_close": float(row["previousClose"]),
            "change_pct": round(float(row["percentChange"]), 2), "trend": trend}


def fetch_market(client) -> dict | None:
    """``{"as_of", "indices": [Nifty 50]}`` from NSE's allIndices, or None on any failure."""
    try:
        resp = client.get(NSE_URL, headers=NSE_HEADERS, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
        rows = {r.get("index"): r for r in data["data"]}
        indices = [index_from_nse(rows[symbol], name) for name, symbol in INDICES]
        when = datetime.strptime(data["timestamp"], "%d-%b-%Y %H:%M").replace(tzinfo=IST)
        return {"as_of": when.isoformat(timespec="seconds"), "indices": indices}
    except Exception as e:  # a tile never fails a build
        log.warning("market fetch failed: %r", e)
        return None


def fetch_live(client, cfg: EditionConfig, *, now: datetime) -> dict:
    """The tiles under ``aqi``, ``match`` and ``market``; a key is left out when its fetch gave None."""
    out: dict = {}
    live = cfg.live or {}
    aqi_cfg, fx = live.get("aqi") or {}, live.get("fixtures") or {}
    if "lat" in aqi_cfg and "lon" in aqi_cfg:
        aqi = fetch_aqi(client, lat=aqi_cfg["lat"], lon=aqi_cfg["lon"])
        if aqi is not None:
            out["aqi"] = aqi
    if "team_id" in fx:
        match = fetch_next_match(client, team_id=fx["team_id"], team_name=fx.get("team", ""), now=now)
        if match is not None:
            out["match"] = match
    if (live.get("market") or {}).get("enabled", True):
        market = fetch_market(client)
        if market is not None:
            out["market"] = market
    return out
