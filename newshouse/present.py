"""Presentation logic for the edition page: colour worlds and visuals.

Pure functions, no I/O. The template calls these to decide each post's
colour world (spec 3.6) and its one visual (spec 3.4).
"""
import re
from dataclasses import dataclass
from datetime import date
from urllib.parse import urlsplit

from newshouse.catalogue import (AQI_BANDS, FACT_FORMATS, SCALES, SLIDE_FORMATS, STORY_FORMATS, aqi_band,  # noqa: F401
                                 effective_visual)

from newshouse.edition_config import EditionConfig
from newshouse.select import primary_topic

PALETTE: dict[str, str] = {
    "sand": "#F3EEE4",
    "white": "#FFFFFF",
    "forest": "#12372A",
    "forest-deep": "#1E4A3A",
    "ink-body": "#2C3A32",
    "muted": "#5B6A61",
    "hairline": "#E4DDCD",
    "track": "#DDD5C4",
    "tomato": "#F25C3B",
    "tomato-ink": "#B23A1C",
    "butter": "#F6C945",
    "mint": "#A8F0C6",
    "mint-light": "#D9F5E3",
    "mint-night": "#143A2B",
    "good": "#3CC77A",
    # night page (spec 3.1)
    "night-ground": "#141A16",
    "night-post": "#1C2620",
    "night-ink": "#F3EEE4",
    "night-body": "#D7E4DB",
    "night-muted": "#9DB5A6",
    "night-hairline": "#2E3A33",
}

TEAM_ALIASES: dict[str, tuple[str, ...]] = {"barcelona": ("barça", "barcelona", "barca")}


@dataclass(frozen=True)
class Family:
    """A topic's colour family (spec 3.6): ``accent`` marks the dot, the story's bar and
    today's timeline dot; ``tint`` fills a tinted post; ``ink`` is text on the tint and
    on white; ``night`` and ``night_accent`` are the dark-mode tint and accent."""
    name: str
    accent: str
    tint: str
    ink: str
    night: str
    night_accent: str
    secondary: str | None = None  # a team's second kit colour (the disc ring)


FAMILIES: dict[str, Family] = {f.name: f for f in (
    Family("world", "#4C7BE0", "#E3ECFF", "#1F3A6B", "#16233D", "#8FB4FF"),
    Family("ai", "#7C6CF0", "#ECE7FF", "#3B2C7A", "#221C3D", "#B9AEFF"),
    Family("business", "#A87F00", "#FBEFC4", "#5A4300", "#2B2412", "#F6C945"),
    Family("sport", "#C4672F", "#F9E3D3", "#6B3216", "#33200F", "#F2A36B"),
    Family("city", "#D6456B", "#F9DEE5", "#6B1E33", "#331620", "#F28BA8"),
    Family("screen", "#1F8F83", "#D6F1EE", "#0F4A45", "#0F2A28", "#7FDCCF"),
)}
# a topic with no family: muted marks, and never a tinted post
NEUTRAL = Family("neutral", "#5B6A61", "#FFFFFF", "#12372A", "#1C2620", "#9DB5A6")


def _mix(a: str, b: str, t: float) -> str:
    """``a`` moved ``t`` of the way to ``b`` (0 is a, 1 is b)."""
    pa = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    pb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(pa, pb))


def team_family(team: str, primary: str, secondary: str) -> Family:
    """A team's family from its two kit colours: the kit colour is the accent, the
    rest are mixes of it toward white, black and the night ground."""
    return Family(f"team-{team}", primary, _mix(primary, "#FFFFFF", 0.88),
                  _mix(primary, "#000000", 0.25), _mix(primary, PALETTE["night-ground"], 0.8),
                  _mix(primary, "#FFFFFF", 0.5), secondary)


def _luminance(h: str) -> float:
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(a: str, b: str) -> float:
    """The WCAG contrast ratio of two hex colours."""
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _on(colour: str) -> str:
    """Forest or white, whichever reads better on ``colour`` (disc letters)."""
    f, w = PALETTE["forest"], PALETTE["white"]
    return f if contrast(f, colour) >= contrast(w, colour) else w


# The CSS variables a world sets, in day and night pairs (edition.css reads --l-* by day
# and --d-* by night). hi: the big number and cover phrase. why: the "Why it matters"
# label. cover-fill / plain-fill / hi-fill: deck slides by role (spec 3.5).
WORLD_VARS = ("fill", "ink", "body", "muted", "accent", "label", "panel", "track", "hi", "why",
              "on-accent", "cover-fill", "plain-fill", "hi-fill", "on-hi", "hi-label")


@dataclass(frozen=True)
class World:
    """A post's colour world: its ladder step (``name``), its family, and the CSS
    values by day (``light``) and by night (``night``)."""
    name: str
    family: Family
    light: dict
    night: dict

    def style(self) -> str:
        parts = [f"--l-{k}:{self.light[k]};--d-{k}:{self.night[k]}" for k in WORLD_VARS]
        if self.family.secondary:  # a team: the pitch discs keep the kit by day and night
            parts.append(f"--secondary:{self.family.secondary};--kit:{self.family.accent};"
                         f"--on-kit:{_on(self.family.accent)}")
        return ";".join(parts)


def _white_post(f: Family) -> tuple[dict, dict]:
    p = _P
    light = {"fill": p["white"], "ink": p["forest"], "body": p["ink-body"], "muted": p["muted"],
             "accent": f.accent, "label": f.ink, "panel": p["sand"], "track": p["track"],
             "hi": f.ink, "why": p["forest"], "on-accent": _on(f.accent),
             "cover-fill": f.tint if f is not NEUTRAL else p["sand"], "plain-fill": p["sand"],
             "hi-fill": f.ink, "on-hi": p["white"], "hi-label": f.tint}
    night = {"fill": p["night-post"], "ink": p["night-ink"], "body": p["night-body"],
             "muted": p["night-muted"], "accent": f.night_accent, "label": f.night_accent,
             "panel": p["night-ground"], "track": p["night-hairline"], "hi": f.night_accent,
             "why": p["mint"], "on-accent": _on(f.night_accent),
             "cover-fill": f.night if f is not NEUTRAL else p["night-ground"],
             "plain-fill": p["night-ground"], "hi-fill": f.night_accent,
             "on-hi": p["night-ground"], "hi-label": p["night-ground"]}
    return light, night


def _world(name: str, f: Family) -> World:
    p = _P
    light, night = _white_post(f)
    if name == "forest":
        # the lead: forest fill, mint marks; by night forest-deep with forest panels
        light.update(fill=p["forest"], ink=p["white"], body="#D7E4DB", muted="#9DB5A6",
                     accent=p["mint"], label=p["mint"], panel=p["forest-deep"], track="#9DB5A6",
                     hi=p["mint"], why=p["mint"], **{"on-accent": p["forest"],
                     "cover-fill": p["forest-deep"], "plain-fill": p["forest-deep"],
                     "hi-fill": p["mint"], "on-hi": p["forest"], "hi-label": p["forest"]})
        night.update(fill=p["forest-deep"], ink=p["white"], body="#D7E4DB", muted="#9DB5A6",
                     accent=p["mint"], label=p["mint"], panel=p["forest"], track="#9DB5A6",
                     hi=p["mint"], why=p["mint"], **{"on-accent": p["forest"],
                     "cover-fill": p["forest"], "plain-fill": p["forest"],
                     "hi-fill": p["mint"], "on-hi": p["forest"], "hi-label": p["forest"]})
    elif name == "mint":
        # good news: mint-light by day, mint-night by night; marks stay the topic's
        light.update(fill=p["mint-light"], muted="#3F5A4B", label=p["forest"], panel=p["white"],
                     hi=p["forest"], **{"cover-fill": p["white"], "plain-fill": p["white"],
                     "hi-fill": p["forest"], "on-hi": p["white"], "hi-label": p["mint"]})
        night.update(fill=p["mint-night"], label=p["mint"], hi=p["mint"],
                     **{"hi-fill": p["mint"], "on-hi": p["forest"], "hi-label": p["forest"]})
    elif name == "tint":
        # a cover or quote post: the family's tint, its ink on the big text
        light.update(fill=f.tint, panel=p["white"])
        night.update(fill=f.night)
    return World(name, f, light, night)


_P = PALETTE
TINTED = ("mint", "tint")


def team_for(card: dict, cfg: EditionConfig) -> str | None:
    """The first configured team named in a football card's headline or line."""
    if "football" not in (card.get("topics") or []):
        return None
    text = f"{card.get('headline') or ''} {card.get('line') or ''}".lower()
    for team in cfg.teams:
        names = (team, *TEAM_ALIASES.get(team, ()))
        if any(name.lower() in text for name in names):
            return team
    return None


def family_for(card: dict, cfg: EditionConfig) -> Family:
    """The card's colour family: a named team's kit, else its primary topic's family."""
    team = team_for(card, cfg)
    if team is not None:
        kit = cfg.teams[team]
        return team_family(team, kit.primary, kit.secondary)
    return topic_family(primary_topic(card.get("topics")), cfg)


def topic_family(topic: str | None, cfg: EditionConfig) -> Family:
    return FAMILIES.get(cfg.colours_topic.get(topic or ""), NEUTRAL)


def colour_world(card: dict, *, position: int, previous: list[str],
                 cfg: EditionConfig, visual: str | None = None) -> World:
    """The post's step on the colour ladder (spec 3.6), loudest first:

    1. ``forest``: the lead (position 0, never a breaking card).
    2. ``breaking``: an urgent card (``urgent``, else ``breaking``): white with the tomato bar.
    3. ``mint`` for good news; ``tint`` for a cover, number or quote post without a deck whose
       family has a tint.
    4. ``white``: everything else, the topic colour on its marks.

    Rhythm: never two tinted posts in a row (the second drops to white)."""
    family = family_for(card, cfg)
    urgent = card.get("urgent", card.get("breaking"))
    if urgent:
        name = "breaking"
    elif position == 0 and not card.get("breaking"):
        name = "forest"
    elif card.get("tone") == "good":
        name = "mint"
    elif visual in ("cover", "number", "quote") and not card.get("slides") and family is not NEUTRAL:
        name = "tint"
    else:
        name = "white"
    if name in TINTED and previous[-1:] and previous[-1] in TINTED:
        name = "white"
    return _world(name, family)


_TRAIL = ",.;:"
_NUM = r"\d[\d,]*(?:\.\d+)?"
# (i) a figure with a currency prefix, optionally with a unit after it
_CURRENCY_RE = re.compile(
    r"(?<![\w])(?:[$₹€£]|Rs\.?|INR)\s?-?" + _NUM
    + r"(?:\s?(?:billion|million|crore|lakh|bn|mn)\b)?",
    re.IGNORECASE,
)
# (ii) a figure with a unit suffix
_UNIT_RE = re.compile(
    r"(?<![\w.,])-?" + _NUM
    + r"(?:\s?%|°C|\s?(?:billion|million|crore|lakh|bn|mn|points|pts|km|kg)\b)",
    re.IGNORECASE,
)
# (iii) a score between two words: "Barça 3-1 Alavés"
_SCORE_RE = re.compile(r"(?<=[^\W\d_]\s)(\d+[-–]\d+)(?=\s[^\W\d_])")
_OUTLET_PREFIX_RE = re.compile(r"^[^:]{2,25}:\s")
_ARTICLES = {"the", "a", "an"}
_FUNCTION_WORDS = {"with", "of", "in", "on", "at", "to", "for", "and", "as", "by", "from",
                   "after", "before", "over", "under"}


def _figure(headline: str) -> str | None:
    """The first currency, unit or score figure in the headline, by position."""
    found = [m for m in (p.search(headline) for p in (_CURRENCY_RE, _UNIT_RE, _SCORE_RE)) if m]
    if not found:
        return None
    first = min(found, key=lambda m: (m.start(), -len(m.group(0))))
    return first.group(0).rstrip(_TRAIL).strip() or None


def _two_words(headline: str) -> str:
    """Two words from the headline: no "Outlet:" prefix, no leading article,
    no trailing function word (one word is fine when the second is dropped)."""
    text = _OUTLET_PREFIX_RE.sub("", headline.strip(), count=1)
    words = text.split()
    while len(words) > 1 and words[0].lower().strip(_TRAIL) in _ARTICLES:
        words = words[1:]
    pick = [w.rstrip(_TRAIL) for w in words[:2]]
    if len(pick) == 2 and pick[1].lower() in _FUNCTION_WORDS:
        pick = pick[:1]
    return " ".join(w for w in pick if w)


def cover_big(headline: str) -> str:
    """The big cover text: a currency, unit or score figure, else two words (spec 3.4)."""
    return _figure(headline) or _two_words(headline) or headline.strip() or "·"


def safe_image_url(url) -> str | None:
    """The URL only when its scheme is https, else None."""
    try:
        return url.strip() if urlsplit(str(url).strip()).scheme.lower() == "https" else None
    except (ValueError, AttributeError):
        return None


def _auto_cover(card: dict) -> dict:
    return {"big": cover_big(card["headline"]), "label": "", "line": card["line"]}


def _strs(v, n: int) -> list[str]:
    return [x for x in v if isinstance(x, str) and x.strip()][:n] if isinstance(v, list) else []


def _str(v) -> str:
    return v if isinstance(v, str) else ""


def _fact_payload(kind: str, p) -> dict | None:
    """A fact-format payload with only the fields the page draws, in the shapes it expects;
    None when nothing drawable is left (the post then shows no visual)."""
    p = p if isinstance(p, dict) else {}
    if kind == "key-facts":
        facts = [{"label": _str(f.get("label")), "value": _str(f.get("value"))}
                 for f in p.get("facts") or [] if isinstance(f, dict) and _str(f.get("value"))][:4]
        return {"facts": facts} if facts else None
    if kind == "number":
        cmp = p.get("compare")
        cmp = ({"label": _str(cmp.get("label")), "value": _str(cmp.get("value"))}
               if isinstance(cmp, dict) and _str(cmp.get("value")) else None)
        return {"value": _str(p.get("value")), "what": _str(p.get("what")), "compare": cmp} if _str(p.get("value")) else None
    if kind == "changes":
        rows = [{"what": _str(r.get("what")), "change": _str(r.get("change"))}
                for r in p.get("rows") or [] if isinstance(r, dict) and _str(r.get("change"))][:3]
        return ({"rows": rows, "from": p.get("from"), "to": p.get("to"), "where": _str(p.get("where"))}
                if rows else None)
    has = _strs(p.get("has"), 3)  # factsheet
    return ({"has": has, "lacks": _strs(p.get("lacks"), 2), "price": _str(p.get("price")),
             "status": _str(p.get("status")), "where": _str(p.get("where"))} if has else None)


def _int(v) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _objs(v, n: int, keys: tuple[str, ...], need: str) -> list[dict]:
    return [{k: (x.get(k) if k in ("done",) else _str(x.get(k))) for k in keys}
            for x in (v if isinstance(v, list) else []) if isinstance(x, dict) and _str(x.get(need))][:n]


def _story_payload(kind: str, p) -> dict | None:
    """Phase B/C payloads cleaned for the page, as ``_fact_payload``; None when nothing is drawable."""
    p = p if isinstance(p, dict) else {}
    g = lambda k: _str(p.get(k))
    if kind == "deal":
        return ({"kind": g("kind"), "from": g("from"), "to": g("to"), "amount": g("amount"), "terms": g("terms"),
                 "to_does": g("to_does"), "status": g("status")} if g("from") and g("to") else None)
    if kind == "availability":
        fixtures = [{**f, "plays": f["plays"] if f["plays"] in ("miss", "doubt", "play") else "doubt"}
                    for f in _objs(p.get("fixtures"), 3, ("vs", "date", "plays"), "vs")]
        status = g("status") if g("status") in ("out", "doubt", "suspended", "back") else ""
        return ({"player": g("player"), "status": status, "reason": g("reason"), "return": g("return"),
                 "fixtures": fixtures} if g("player") else None)
    if kind == "scoreline":
        score = p.get("score")
        ok = isinstance(score, list) and len(score) == 2 and all(_int(x) is not None for x in score)
        return ({"home": g("home"), "away": g("away"), "score": score, "competition": g("competition"),
                 "note": g("note"), "scorers": _objs(p.get("scorers"), 4, ("name", "minute", "side"), "name")}
                if ok and g("home") and g("away") else None)
    if kind == "stakes":
        rows = [o for o in _objs(p.get("outcomes"), 3, ("if", "then"), "then") if o["if"] in ("win", "draw", "loss")]
        return {"fixture": g("fixture"), "when": g("when"), "outcomes": rows} if rows else None
    if kind == "incident":
        return ({"symptom": g("symptom"), "affects": _strs(p.get("affects"), 3), "since": g("since"),
                 "workaround": g("workaround"), "sure": incident_sure(_int(p.get("reports")), g("vendor"))}
                if g("symptom") else None)
    if kind == "countdown":
        try:
            date.fromisoformat(g("date"))
        except ValueError:
            return None
        return {"date": g("date"), "what": g("what"), "do": g("do")} if g("what") else None
    if kind == "case":
        steps = _objs(p.get("steps"), 4, ("label", "date", "done"), "label")
        return ({"court": g("court"), "asked": g("asked"), "next": g("next"), "steps": steps} if steps else None)
    if kind == "scale":
        return scale_view(p)
    if kind == "rumour":
        return ({"player": g("player"), "from": g("from"), "to": g("to"), "fee": g("fee"), "source": g("source"),
                 "tier": RUMOUR_WORDS.get(g("tier"), "Reported")} if g("player") and g("from") and g("to") else None)
    steps = _strs(p.get("steps"), 3)  # steps
    return {"steps": steps} if steps else None


VENDOR_WORDS = {"confirmed": "vendor confirmed", "fixed": "vendor says it is fixed",
                "no reply": "no vendor reply yet", "disputed": "vendor disputes it"}
RUMOUR_WORDS = {"official": "Official", "reporter": "Reported by a named journalist", "report": "Reported"}


def incident_sure(reports: int | None, vendor: str) -> str:
    """The Incident card's "how sure" line, in words (no colour scale)."""
    parts = []
    if reports:
        parts.append(f"{reports} report" + ("" if reports == 1 else "s"))
    if vendor in VENDOR_WORDS:
        parts.append(VENDOR_WORDS[vendor])
    return " · ".join(parts)


SCALE_SHORT = {"grap": ("I", "II", "III", "IV"),
               "aqi": ("Good", "Satisf.", "Moderate", "Poor", "V. poor", "Severe")}  # CPCB names, shortened


def scale_view(p: dict) -> dict | None:
    """The Scale card's steps: each with its name and whether it is the current or the previous
    level. An AQI card's level comes from its reading; poor or worse is ``alarm`` (tomato)."""
    kind = p.get("scale")
    names = SCALES.get(kind) if isinstance(kind, str) else None
    if not names:
        return None
    value = _int(p.get("value"))
    level = aqi_band(value) if kind == "aqi" and value is not None else _int(p.get("level"))
    if level is None or not 0 <= level < len(names):
        return None
    prev = _int(p.get("previous"))
    short = SCALE_SHORT.get(kind, names)  # the step labels fit a phone; the big line names it in full
    steps = [{"name": short[i], "now": i == level, "was": i == prev and i != level} for i in range(len(names))]
    return {"scale": kind, "steps": steps, "value": value, "name": names[level],
            "alarm": kind == "aqi" and level >= 3}


def countdown_days(iso: str, today: date) -> dict:
    """Days left for a Countdown: ``{"n": int | None, "label": "25 days" | "Tomorrow" | "Today" | "Ended",
    "date": "1 Dec"}``."""
    try:
        d = date.fromisoformat(iso)
    except (TypeError, ValueError):
        return {"n": None, "label": "", "date": ""}
    n = (d - today).days
    label = "Ended" if n < 0 else "Today" if n == 0 else "Tomorrow" if n == 1 else f"{n} days"
    return {"n": n, "label": label, "date": _day_month(d)}


def visual_for(card: dict) -> dict:
    """The post's one visual (spec 3.4): the catalogue kind, a cover only when the
    writer filled its ``big``, else ``none`` (a post with no visual)."""
    kind = effective_visual(card.get("visual"), card.get("format"))
    payload = card.get("payload")
    if kind == "cover":
        if (card.get("visual") or "cover") == "cover" and isinstance(payload, dict) \
                and str(payload.get("big") or "").strip():
            return {"kind": "cover", "payload": payload}
        kind = "none"
    if kind in FACT_FORMATS or kind in STORY_FORMATS:
        clean = _fact_payload(kind, payload) if kind in FACT_FORMATS else _story_payload(kind, payload)
        if clean is not None:
            return {"kind": kind, "payload": clean}
        kind = "none"
    if kind == "none":
        return _source_photo(card) or {"kind": "none", "payload": {}}
    if kind == "photo":
        p = payload if isinstance(payload, dict) else {}
        src = None
        for s in card.get("sources") or []:
            # image_url is set only for a photo-eligible item (catalogue.photo_eligible)
            if s.get("item_id") == p.get("item_id"):
                src = safe_image_url(s.get("image_url"))
                break
        if src is None:
            return {"kind": "none", "payload": {}}
        # a broken hotlink still swaps to a cover in place (edition.js photoFallback)
        return {"kind": "photo", "payload": {**p, "src": src, "fallback": _auto_cover(card)}}
    return {"kind": kind, "payload": payload}


def _source_photo(card: dict) -> dict | None:
    """The photo fallback (2026-11-06): a post with no visual shows the first cited
    article's publisher image (``image_url`` is set only for a photo-eligible item), with
    the outlet as credit. A load error hides it (edition.js photoFallback)."""
    for s in card.get("sources") or []:
        src = safe_image_url(s.get("image_url"))
        if src:
            return {"kind": "photo", "payload": {"item_id": s.get("item_id"), "src": src, "alt": "",
                                                 "credit": s.get("outlet") or "", "auto": True}}
    return None


# ---- phase A render helpers (docs/design-visuals.md 4.2, 4.3, 5) --------------------------

# the visual explains the headline, so the headline leads; every other visual is a hook
HEADLINE_FIRST = frozenset({"key-facts", "changes", "factsheet", "chart", "table", "timeline",
                            "versus", "before-after", "pitch", "deal", "availability", "stakes",
                            "incident", "case", "scale", "rumour", "steps"})

_SCALES = {"k": 1e3, "thousand": 1e3, "lakh": 1e5, "lakhs": 1e5, "m": 1e6, "mn": 1e6,
           "million": 1e6, "cr": 1e7, "crore": 1e7, "crores": 1e7, "b": 1e9, "bn": 1e9,
           "billion": 1e9}
_AMOUNT_RE = re.compile(r"^\s*(\$|₹|rs\.?|inr|€|£)?\s*(\d[\d,]*(?:\.\d+)?)\s*(%|[a-z]+)?(?:\s+([a-z]+))?\s*$",
                        re.IGNORECASE)


def amount(s) -> tuple[str, float] | None:
    """(unit, absolute value) of a short amount ("$465M", "₹143.63 cr", "Rs 69.71 crore",
    "₹1.2 lakh crore", "12%"), else None. Rupee spellings are one unit and a percentage is
    its own (``%``). Ranges, negatives and words that are not scales give None, so the
    page prints the comparison instead of drawing bars to a wrong scale."""
    m = _AMOUNT_RE.match(str(s or ""))
    if not m:
        return None
    cur = (m.group(1) or "").lower().rstrip(".")
    cur = "₹" if cur in ("₹", "rs", "inr") else cur
    value = float(m.group(2).replace(",", ""))
    words = [w.lower() for w in (m.group(3), m.group(4)) if w]
    if words and words[0] == "%":
        return (None if cur or len(words) > 1 else ("%", value))
    for w in words:  # "lakh crore" stacks: 1e5 * 1e7
        if w not in _SCALES:
            return None
        value *= _SCALES[w]
    return cur, value


def number_bars(payload: dict) -> list[dict] | None:
    """Two bars to scale for Number in context, only when both values parse with one currency."""
    cmp = payload.get("compare") if isinstance(payload, dict) else None
    if not isinstance(cmp, dict):
        return None
    a, b = amount(payload.get("value")), amount(cmp.get("value"))
    if not a or not b or a[0] != b[0] or max(a[1], b[1]) == 0:
        return None
    top = max(a[1], b[1])
    return [{"label": "", "value": payload.get("value"), "w": round(100 * a[1] / top), "key": True},
            {"label": cmp.get("label") or "", "value": cmp.get("value"), "w": round(100 * b[1] / top), "key": False}]


def _day_month(d: date) -> str:
    return f"{d.day} {d:%b}"


def date_bar(frm, to, today: date) -> dict | None:
    """The What-changes date bar: start and end labels, and the edition date's position as a
    percentage when it falls inside a two-ended period."""
    def parse(v):
        try:
            return date.fromisoformat(v) if isinstance(v, str) else None
        except ValueError:
            return None
    a, b = parse(frm), parse(to)
    if not a and not b:
        return None
    pct = None
    if a and b and a <= today <= b:
        pct = 50 if a == b else round(100 * (today - a).days / (b - a).days)
    return {"from": _day_month(a) if a else None, "to": _day_month(b) if b else None, "today": pct}


def _chart(payload: dict) -> dict:
    """Bar rows for a C chart: widths relative to the largest absolute value, which is the key bar."""
    series = payload.get("series") or []
    top = max((abs(float(p["value"])) for p in series), default=0) or 1.0
    # the writer's key point (the value the story is about), else the largest
    marked = [i for i, p in enumerate(series) if p.get("key") is True]
    key = marked[0] if marked else max(range(len(series)), key=lambda i: abs(float(series[i]["value"])),
                                         default=-1)
    rows = [{"label": p["label"], "value": p["value"], "key": i == key,
             "w": round(100 * abs(float(p["value"])) / top)} for i, p in enumerate(series)]
    return {**payload, "bars": rows}


def value_class(text) -> str:
    """CSS class for a table value: 17 to 28 characters is set in the small sans face."""
    return "v-long" if 17 <= len(str(text or "")) <= 28 else ""


def _table(payload: dict) -> dict:
    """B rows as label / big figure / small comparison."""
    rows = []
    for r in payload.get("rows") or []:
        cells = [str(x) for x in r.get("cells") or []]
        rows.append({"label": cells[0] if cells else "", "big": cells[1] if len(cells) > 1 else "",
                     "small": " · ".join(cells[2:]), "yours": bool(r.get("yours")),
                     "new": bool(r.get("new"))})
    return {**payload, "table_rows": rows}


def deck_for(card: dict, world) -> list[dict]:
    """One dict per slide: kind, title, body paragraphs, payload and its fill role
    (spec 3.5): ``cover`` for slide 1, ``hi`` for the one slide the writer marked
    ``highlight`` (never slide 1), ``plain`` for the rest. The roles' colours come from
    the post's world."""
    out = []
    highlighted = False
    for i, s in enumerate(card.get("slides") or []):
        kind = s.get("kind")
        payload = s.get("payload") if isinstance(s.get("payload"), dict) else {}
        if kind == "cover" and not str(payload.get("big") or "").strip():
            # a blank slide cover would open the deck on an empty frame
            payload = {**_auto_cover(card), **{k: v for k, v in payload.items()
                                               if k in ("label", "line") and str(v or "").strip()}}
        elif kind == "chart":
            payload = _chart(payload)
        elif kind == "table":
            payload = _table(payload)
        elif kind in SLIDE_FORMATS:
            payload = (_fact_payload(kind, payload) if kind in FACT_FORMATS else _story_payload(kind, payload)) or {}
            if kind == "number" and payload:
                payload = {**payload, "bars": number_bars(payload)}
        if i == 0:
            fill = "cover"
        elif s.get("highlight") is True and not highlighted:
            fill, highlighted = "hi", True
        else:
            fill = "plain"
        out.append({"kind": kind, "title": s.get("title") or "",
                    "body_paras": [p.strip() for p in re.split(r"\n\s*\n", s.get("body") or "") if p.strip()],
                    "payload": payload, "fill": fill})
    return out


TOPIC_NAMES = {"ai-models": "AI", "ai-built": "AI tooling", "india-tech-biz": "India business",
               "intl-biz-tech": "Business", "edtech-competitors": "Edtech", "product-design": "Product",
               "solutions": "Solutions", "geopolitics": "World", "india-news": "India",
               "gurgaon-local": "Gurgaon", "startups": "Startups", "ai-tools": "AI tools", "movies": "Movies", "football": "Football",
               "cricket": "Cricket", "tennis-f1": "Tennis & F1"}


def topic_name(topics: list[str]) -> str:
    """The display name of the card's first topic, else the slug itself."""
    slug = topics[0] if topics else ""
    return TOPIC_NAMES.get(slug, slug)


TUNE_LONGER_UNDER_MINUTES = 12


def tune_chips(view: dict, per_topic: int | None = None) -> list[dict]:
    """The four "Tune tomorrow" chips (Ruling 7): Less <the topic with the most posts>,
    More <the topic of the best-scored cut story>, More <the next such topic> (never a
    topic with folded rows or more lines than ``per_topic``), then
    Shorter edition, or Longer edition when the edition ran under 12 minutes. No topic
    gets two chips; an edition with fewer topics gets fewer topic chips."""
    chips: list[dict] = []
    used: set[str] = set()
    counts: dict[str, int] = {}
    for c in sorted(view.get("cards") or [], key=lambda c: c.get("rank") or 0):
        t = primary_topic(c.get("topics"))
        if t != "other":
            counts[t] = counts.get(t, 0) + 1
    if counts:
        most = max(counts, key=lambda t: counts[t])  # ties: the first in rank order
        chips.append({"label": f"Less {topic_name([most])}", "payload": {"topic": most, "dir": -1}})
        used.add(most)
    # a topic that flooded the cut list needs no "More": it has folded rows, or (an edition
    # built before folding) more plain lines than the per-topic cap
    lines: dict[str, int] = {}
    flooded: set[str] = set()
    for a in view.get("also") or []:
        t = a.get("topic") or "other"
        if a.get("folded"):
            flooded.add(t)
        else:
            lines[t] = lines.get(t, 0) + 1
    if per_topic is not None:
        flooded |= {t for t, k in lines.items() if k > per_topic}
    more = 0
    for a in sorted(view.get("also") or [], key=lambda a: a.get("rank") or 0):
        t = a.get("topic") or "other"
        if more == 2:
            break
        if t == "other" or t in used or t in flooded:
            continue
        chips.append({"label": f"More {topic_name([t])}", "payload": {"topic": t, "dir": 1}})
        used.add(t)
        more += 1
    if (view.get("counts") or {}).get("est_minutes", 0) < TUNE_LONGER_UNDER_MINUTES:
        chips.append({"label": "Longer edition", "payload": {"budget": 1}})
    else:
        chips.append({"label": "Shorter edition", "payload": {"budget": -1}})
    return chips
