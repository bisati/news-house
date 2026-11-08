"""Pure rules for the visual catalogue: names, format mapping, payload truth checks."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

VISUALS = ("none", "cover", "number", "key-facts", "changes", "factsheet",
           "deal", "availability", "scoreline", "stakes", "incident", "countdown",
           "case", "scale", "rumour", "steps", "chart", "table", "timeline", "versus", "before-after", "pitch", "photo", "quote")
SLIDE_KINDS = ("cover", "chart", "table", "text", "what-next",
               "key-facts", "number", "factsheet", "deal", "steps")  # phase C: formats as slides
SLIDE_FORMATS = ("key-facts", "number", "factsheet", "deal", "steps")
TONES = ("good", "bad", "mixed", "neutral")

VISUAL_FORMAT = {"chart": "C", "table": "B", "timeline": "D", "versus": "E", "before-after": "F",
                 "none": "A", "cover": "A", "number": "A", "key-facts": "A", "changes": "A", "factsheet": "A",
                 "deal": "A", "availability": "A", "scoreline": "A", "stakes": "A", "incident": "A",
                 "countdown": "A", "case": "A", "scale": "A", "rumour": "A", "steps": "A", "pitch": "A", "photo": "A", "quote": "A"}
FORMAT_VISUAL = {"B": "table", "C": "chart", "D": "timeline", "E": "versus", "F": "before-after"}


@dataclass(frozen=True)
class ItemFacts:
    text: str  # title, teaser and body joined by newlines
    image_url: str | None = None


def photo_eligible(source_kinds) -> bool:
    """An item's image may be shown only when it came from a publisher: the item has at
    least one source that is not Google News. The writer and the page share this rule."""
    return any(k != "gnews" for k in source_kinds)


def effective_visual(visual: str | None, format: str | None) -> str:
    """The visual to show. A cover or ``none`` (also the column defaults) gives way to a
    v1 format letter's visual; with no such letter it stays as it is (no visual: none)."""
    if visual in VISUALS and visual not in ("cover", "none"):
        return visual
    return FORMAT_VISUAL.get(format, "cover" if visual == "cover" else "none")


def _strs(v) -> bool:
    return isinstance(v, list) and bool(v) and all(isinstance(x, str) for x in v)


def _nonempty_str(v) -> bool:
    return isinstance(v, str) and bool(v.strip())


MAX_VALUE_CHARS = 28
VERSUS_MAX_POINTS, VERSUS_POINT_CHARS, VERSUS_STANDS_CHARS = 2, 90, 140  # fits 320px at phone width


def _long_values(cells) -> bool:
    return any(isinstance(c, str) and len(c) > MAX_VALUE_CHARS for c in cells)


def format_payload_problems(fmt: str, p, cited: set[str],
                            expected_chapters: list[dict] | None = None) -> list[str]:
    if not isinstance(p, dict):
        return ["payload must be an object"]
    out: list[str] = []
    if fmt == "A":
        if p:
            out.append("payload for format A must be empty {}")
    elif fmt == "B":
        cols, rows = p.get("columns"), p.get("rows")
        if not _strs(cols):
            out.append("payload.columns must be a non-empty list of strings")
        if not isinstance(rows, list) or not rows:
            out.append("payload.rows must be a non-empty list")
        else:
            for n, r in enumerate(rows):
                if (not isinstance(r, dict) or not isinstance(r.get("cells"), list)
                        or (_strs(cols) and len(r["cells"]) != len(cols))
                        or not isinstance(r.get("yours"), bool) or not isinstance(r.get("new"), bool)):
                    out.append(f"payload.rows[{n}] needs cells matching columns plus boolean yours and new")
                elif _long_values(r["cells"][1:]):
                    out.append(f"table value over {MAX_VALUE_CHARS} characters (payload.rows[{n}])")
    elif fmt == "C":
        series = p.get("series")
        if not isinstance(series, list) or len(series) < 3:
            out.append("payload.series needs at least 3 points")
        else:
            for n, pt in enumerate(series):
                if not isinstance(pt, dict) or not _nonempty_str(pt.get("label")):
                    out.append(f"payload.series[{n}] needs a label")
                    continue
                v = pt.get("value")
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    out.append(f"payload.series[{n}].value must be a number")
                if pt.get("item_id") not in cited:
                    out.append(f"payload.series[{n}].item_id must be one of cited_item_ids")
                if "key" in pt and not isinstance(pt["key"], bool):
                    out.append(f"payload.series[{n}].key must be a boolean")
            if sum(1 for pt in series if isinstance(pt, dict) and pt.get("key") is True) > 1:
                out.append("payload.series may mark at most one point key")
        for k in ("unit", "caption"):
            if not _nonempty_str(p.get(k)):
                out.append(f"payload.{k} must be a non-empty string")
    elif fmt == "D":
        ch = p.get("chapters")
        if not isinstance(ch, list) or not ch:
            out.append("payload.chapters must be a non-empty list")
        else:
            for n, c in enumerate(ch):
                if (not isinstance(c, dict) or not _nonempty_str(c.get("title"))
                        or not isinstance(c.get("date"), str) or not isinstance(c.get("read"), bool)):
                    out.append(f"payload.chapters[{n}] needs title, date and boolean read")
            if expected_chapters is not None:
                if len(ch) != len(expected_chapters):
                    out.append(f"payload.chapters must list exactly {len(expected_chapters)} "
                               f"earlier chapters, got {len(ch)}")
                else:
                    for n, (c, e) in enumerate(zip(ch, expected_chapters)):
                        if isinstance(c, dict) and c.get("read") is not e["read"]:
                            out.append(f"payload.chapters[{n}].read must be "
                                       f"{str(e['read']).lower()} (chapter {e['chapter']})")
        if not _nonempty_str(p.get("delta")):
            out.append("payload.delta must be non-empty")
    elif fmt == "E":
        for k in ("for", "against"):
            if not _strs(p.get(k)):
                out.append(f"payload.{k} must be a non-empty list of strings")
            elif len(p[k]) > VERSUS_MAX_POINTS:
                out.append(f"payload.{k} has at most {VERSUS_MAX_POINTS} points")
            elif any(len(x) > VERSUS_POINT_CHARS for x in p[k]):
                out.append(f"payload.{k} has a point over {VERSUS_POINT_CHARS} characters")
        if not _nonempty_str(p.get("stands")):
            out.append("payload.stands must be a non-empty string")
        elif len(p["stands"]) > VERSUS_STANDS_CHARS:
            out.append(f"payload.stands over {VERSUS_STANDS_CHARS} characters")
    elif fmt == "F":
        for k in ("before", "after", "effective", "applies_to"):
            if not _nonempty_str(p.get(k)):
                out.append(f"payload.{k} must be a non-empty string")
    return out


def _norm(s: str) -> str:
    """Lower case, single spaces, straight quote marks, no accents ("Koundé" is "kounde")."""
    s = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))
    s = (s.replace("\u2018", "'").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"'))
    return " ".join(s.lower().split())


def _unquoted(s: str) -> str:
    """The normalised text without the quote marks a quote may keep around itself."""
    return _norm(s).strip().strip("'\"").strip()


_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(s: str) -> dict[float, str]:
    """Each number in the text by value (commas dropped, so "1,200" is 1200 and "$0.10"
    is 0.1), mapped to how it was first written."""
    out: dict[float, str] = {}
    for m in _NUMBER_RE.finditer(s):
        written = m.group(0).rstrip(",")
        out.setdefault(float(written.replace(",", "")), written)
    return out


def _written(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else repr(float(v))


def _cited_text(cited: set[str], items: dict[str, ItemFacts]) -> str:
    return _norm("\n".join(items[i].text for i in cited if i in items))


def payload_problems(visual: str, payload, *, cited: set[str], items: dict[str, ItemFacts],
                     expected_chapters: list[dict] | None = None,
                     check_cover_digits: bool = True) -> list[str]:
    if visual not in VISUALS:
        return [f"visual {visual!r} is not in the catalogue"]
    if visual == "none":
        return []
    if visual in ("chart", "table", "timeline", "versus", "before-after"):
        return format_payload_problems(VISUAL_FORMAT[visual], payload, cited, expected_chapters)
    if not isinstance(payload, dict):
        return ["payload must be an object"]
    p = payload
    out: list[str] = []
    if visual == "cover":
        big = p.get("big")
        for k in ("big", "label", "line"):
            if k in p and not isinstance(p[k], str):
                out.append(f"payload.{k} must be a string")
        if not _nonempty_str(big):
            out.append("a cover slide needs a non-empty payload.big" if not check_cover_digits else
                       "payload.big must be filled in (choose visual none when nothing carries the story)")
        elif isinstance(big, str):
            if len(big) > 14:
                out.append("payload.big must be 14 characters or fewer")
            if check_cover_digits:
                have = set().union(*(_numbers(items[i].text) for i in cited if i in items))
                for v, w in sorted(_numbers(big).items()):
                    if v not in have:
                        out.append(f"payload.big has the number {w}, which no cited item contains")
    elif visual == "quote":
        for k in ("text", "who", "item_id"):
            if not _nonempty_str(p.get(k)):
                out.append(f"payload.{k} must be a non-empty string")
        if not isinstance(p.get("where"), str):
            out.append("payload.where must be a string")
        iid = p.get("item_id")
        if _nonempty_str(iid):
            if iid not in cited or iid not in items:
                out.append("payload.item_id must be one of cited_item_ids")
            elif _nonempty_str(p.get("text")) and (not _unquoted(p["text"])
                                                   or _unquoted(p["text"]) not in _norm(items[iid].text)):
                out.append("payload.text does not appear in its item")
    elif visual == "pitch":
        names: list[str] = []
        rows = p.get("rows")
        if not isinstance(rows, list) or not rows:
            out.append("payload.rows must be a non-empty list of rows")
        else:
            if len(rows) > 4:
                out.append(f"payload.rows may have at most 4 rows (the page shows no more), got {len(rows)}")
            for n, r in enumerate(rows):
                if not isinstance(r, list) or not r:
                    out.append(f"payload.rows[{n}] must be a non-empty list")
                    continue
                for m, pl in enumerate(r):
                    if (not isinstance(pl, dict) or not _nonempty_str(pl.get("pos"))
                            or not _nonempty_str(pl.get("name"))):
                        out.append(f"payload.rows[{n}][{m}] needs string pos and name")
                    else:
                        names.append(pl["name"])
        if not _nonempty_str(p.get("note")):
            out.append("payload.note must be a non-empty string")
        o = p.get("out", [])
        if not isinstance(o, list):
            out.append("payload.out must be a list")
        else:
            if len(o) > 3:
                out.append(f"payload.out may have at most 3 entries (the page shows no more), got {len(o)}")
            for n, x in enumerate(o):
                if (not isinstance(x, dict) or not _nonempty_str(x.get("name"))
                        or not isinstance(x.get("why"), str)):
                    out.append(f"payload.out[{n}] needs string name and why")
                else:
                    names.append(x["name"])
        text = _cited_text(cited, items)
        for nm in names:
            if _norm(nm) not in text:
                out.append(f"payload name {nm!r} does not appear in any cited item")
    elif visual in FACT_FORMATS:
        out += _fact_format_problems(visual, p, cited, items)
    elif visual in STORY_FORMATS:
        out += _story_format_problems(visual, p, cited, items)
    elif visual == "photo":
        for k in ("item_id", "alt"):
            if not _nonempty_str(p.get(k)):
                out.append(f"payload.{k} must be a non-empty string")
        if not isinstance(p.get("credit"), str):
            out.append("payload.credit must be a string")
        iid = p.get("item_id")
        if _nonempty_str(iid):
            if iid not in cited or iid not in items:
                out.append("payload.item_id must be one of cited_item_ids")
            elif not items[iid].image_url:
                out.append("payload.item_id names an item with no image")
    return out


# ---- the fact formats (docs/design-visuals.md 4.1-4.4, rules 9.1-9.2) ----------------------

FACT_FORMATS = ("number", "key-facts", "changes", "factsheet")
STORY_FORMATS = ("deal", "availability", "scoreline", "stakes", "incident", "countdown",
                 "case", "scale", "rumour", "steps")  # docs/design-visuals.md 4.5-4.13
DEAL_KINDS = ("acquisition", "stake", "merger", "funding", "listing")
DEAL_STATUS = ("announced", "closed", "needs approval", "reported")
AVAILABILITY_STATUS = ("out", "doubt", "suspended", "back")
PLAYS = ("miss", "doubt", "play")
OUTCOMES = ("win", "draw", "loss")
VENDOR = ("confirmed", "fixed", "no reply", "disputed")
RUMOUR_TIERS = ("official", "reporter", "report")
SCALES = {"grap": ("Stage I", "Stage II", "Stage III", "Stage IV"),
          "aqi": ("Good", "Satisfactory", "Moderate", "Poor", "Very poor", "Severe")}
AQI_BANDS = (50, 100, 200, 300, 400)  # CPCB upper bounds of the first five bands


def aqi_band(value: int) -> int:
    """The CPCB band index (0 good to 5 severe) of an AQI reading."""
    return next((n for n, top in enumerate(AQI_BANDS) if value <= top), 5)
FACTSHEET_STATUS = ("available", "preview", "beta", "waitlist", "limited")
_WORD_RE = re.compile(r"[^\W\d_][\w'’.&-]*")
_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december")
# a day joined to its month: "5 Nov", "5th November", "November 5", "5 to 20 November", "5-20 Nov"
_RANGE_JOIN = r"(?:\s*(?:-|–|to|and|&)\s*)"


def _untraced(strings, cited: set[str], items: dict[str, ItemFacts]) -> list[str]:
    """Numbers in ``strings`` (as written) that no cited item contains, by value."""
    have = set().union(*(_numbers(items[i].text) for i in cited if i in items)) if cited else set()
    found: dict[float, str] = {}
    for x in strings:
        if isinstance(x, str):
            for v, w in _numbers(x).items():
                found.setdefault(v, w)
    return [w for v, w in sorted(found.items()) if v not in have]


# a month or weekday in a value matches any of its forms in the sources ("9 Nov" against
# "9 November"), but must still be there ("Friday" fails against a source saying "Thursday")
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_CALENDAR_FORMS: dict[str, str] = {}
for _w in (*_MONTHS, *_WEEKDAYS):
    _forms = f"{_w}|{_w[:3]}" + ("|sept" if _w == "september" else "")
    for _f in _forms.split("|"):
        _CALENDAR_FORMS[_f] = _forms


def _name_parts(word: str) -> list[str]:
    """A capitalised token as the name parts to look up: no possessive, split on hyphens."""
    word = re.sub(r"['’]s$", "", word.rstrip(".'’-&"))
    return [p for p in word.split("-") if len(p) >= 3]


def _unnamed(strings, cited: set[str], items: dict[str, ItemFacts]) -> list[str]:
    """Capitalised words of 3+ letters (names) that no cited item contains as a whole word,
    case-insensitive and accent-blind ("PhysicsWallah's" looks up PhysicsWallah)."""
    text = _cited_text(cited, items)
    out: list[str] = []
    for x in strings:
        for tok in _WORD_RE.findall(x if isinstance(x, str) else ""):
            if not tok[0].isupper():
                continue
            cal = _CALENDAR_FORMS.get(_norm(tok).rstrip("."))
            if cal is not None:  # a month or weekday: any of its forms must be in the sources
                if not re.search(rf"(?<!\w)(?:{cal})(?!\w)", text) and tok not in out:
                    out.append(tok)
                continue
            for w in _name_parts(tok):
                if not re.search(rf"(?<!\w){re.escape(_norm(w))}(?!\w)", text) and w not in out:
                    out.append(w)
    return out


def _month_forms(m: int) -> str:
    name = _MONTHS[m - 1]
    forms = {name, name[:3]} | ({"sept"} if m == 9 else set())
    return "(?:" + "|".join(sorted(forms, key=len, reverse=True)) + r")\.?"


def _date_in(iso: str, cited: set[str], items: dict[str, ItemFacts], *,
             today: date | None = None) -> bool:
    """One cited item writes the date's day joined to its month ("5 Nov", "November 5",
    "5 to 20 November"); the year is this year or the next (spec 9.2)."""
    try:
        d = date.fromisoformat(iso)
    except (TypeError, ValueError):
        return False
    ref = today or date.today()
    if d.year not in (ref.year - 1, ref.year, ref.year + 1):  # -1: an edition built just after New Year
        return False
    mon, day = _month_forms(d.month), rf"0?{d.day}(?:st|nd|rd|th)?"
    pats = (rf"(?<!\d){day}(?:{_RANGE_JOIN}\d{{1,2}}(?:st|nd|rd|th)?)?\s+(?:of\s+)?{mon}\b",
            rf"(?<!\d)\d{{1,2}}(?:st|nd|rd|th)?{_RANGE_JOIN}{day}\s+(?:of\s+)?{mon}\b",
            rf"\b{mon}\s+{day}(?!\d)",
            rf"\b{mon}\s+\d{{1,2}}{_RANGE_JOIN}{day}(?!\d)")
    for i in cited:
        if i in items:
            t = _norm(items[i].text)
            if any(re.search(p, t) for p in pats):
                return True
    return False


def _cap(out: list[str], where: str, v, n: int, *, required: bool = True) -> None:
    if v is None and not required:
        return
    if not isinstance(v, str) or (required and not v.strip()):
        out.append(f"{where} must be a non-empty string")
    elif len(v) > n:
        out.append(f"{where} must be {n} characters or fewer")


def _fact_format_problems(visual: str, p: dict, cited: set[str], items: dict[str, ItemFacts]) -> list[str]:
    out: list[str] = []
    strings: list = []
    if visual == "key-facts":
        facts = p.get("facts")
        if not isinstance(facts, list) or not 2 <= len(facts) <= 4:
            return ["payload.facts must hold 2 to 4 facts"]
        for n, f in enumerate(facts):
            if not isinstance(f, dict):
                out.append(f"payload.facts[{n}] must be an object")
                continue
            _cap(out, f"payload.facts[{n}].label", f.get("label"), 14)
            _cap(out, f"payload.facts[{n}].value", f.get("value"), 32)
            strings.append(f.get("value"))
        for w in _unnamed(strings, cited, items):
            out.append(f"payload has the name {w!r}, which no cited item contains")
    elif visual == "number":
        _cap(out, "payload.value", p.get("value"), 12)
        _cap(out, "payload.what", p.get("what"), 48)
        strings += [p.get("value"), p.get("what")]
        cmp = p.get("compare")
        if cmp is not None:
            if not isinstance(cmp, dict):
                out.append("payload.compare must be an object or null")
            else:
                _cap(out, "payload.compare.label", cmp.get("label"), 24)
                _cap(out, "payload.compare.value", cmp.get("value"), 12)
                strings += [cmp.get("value"), cmp.get("label")]
        if isinstance(p.get("value"), str) and not _numbers(p["value"]):
            out.append("payload.value must be a number (choose key-facts or cover for a phrase)")
    elif visual == "changes":
        rows = p.get("rows")
        if not isinstance(rows, list) or not 2 <= len(rows) <= 3:
            out.append("payload.rows must hold 2 or 3 rows")
            rows = []
        for n, r in enumerate(rows):
            if not isinstance(r, dict):
                out.append(f"payload.rows[{n}] must be an object")
                continue
            _cap(out, f"payload.rows[{n}].what", r.get("what"), 22)
            _cap(out, f"payload.rows[{n}].change", r.get("change"), 32)
            strings += [r.get("what"), r.get("change")]
        _cap(out, "payload.where", p.get("where"), 32)
        where = p.get("where")
        if _nonempty_str(where) and _norm(where) not in _cited_text(cited, items):
            out.append("payload.where does not appear in any cited item")
        for k in ("from", "to"):
            v = p.get(k)
            if v is None:
                continue
            if not isinstance(v, str):
                out.append(f"payload.{k} must be a YYYY-MM-DD date or null")
            elif not _date_in(v, cited, items):
                out.append(f"payload.{k} {v} is not a date any cited item gives (day and month)")
        if isinstance(p.get("from"), str) and isinstance(p.get("to"), str) and p["from"] > p["to"]:
            out.append("payload.from is after payload.to")
    elif visual == "factsheet":
        has, lacks = p.get("has"), p.get("lacks") or []
        if not isinstance(has, list) or not 1 <= len(has) <= 3:
            out.append("payload.has must hold 1 to 3 items")
            has = []
        if not isinstance(lacks, list) or len(lacks) > 2:
            out.append("payload.lacks must hold at most 2 items")
            lacks = []
        for k, xs in (("has", has), ("lacks", lacks)):
            for n, x in enumerate(xs):
                _cap(out, f"payload.{k}[{n}]", x, 26)
            strings += xs
        _cap(out, "payload.price", p.get("price"), 28, required=False)
        _cap(out, "payload.where", p.get("where"), 24, required=False)
        strings += [p.get("price"), p.get("where")]
        if p.get("status") is not None and p.get("status") not in FACTSHEET_STATUS:
            out.append(f"payload.status must be one of {', '.join(FACTSHEET_STATUS)} or null")
    for w in _untraced(strings, cited, items):
        out.append(f"payload has the number {w}, which no cited item contains")
    return out


def _enum(out: list[str], where: str, v, allowed, *, required: bool = True) -> None:
    if v is None and not required:
        return
    if v not in allowed:
        out.append(f"{where} must be one of {', '.join(allowed)}" + ("" if required else " or null"))


def _objs(out: list[str], where: str, v, lo: int, hi: int) -> list[dict]:
    """``v`` as a list of objects of lo..hi entries; a problem (and []) otherwise."""
    if not isinstance(v, list) or not lo <= len(v) <= hi or not all(isinstance(x, dict) for x in v):
        out.append(f"{where} must hold {lo} to {hi} objects" if lo != hi else f"{where} must hold {lo} objects")
        return []
    return v


def _story_format_problems(visual: str, p: dict, cited: set[str], items: dict[str, ItemFacts]) -> list[str]:
    """Phases B and C (docs/design-visuals.md 4.5-4.13). Numbers and capitalised names in
    every text field must appear in a cited item; enums are checked; dates need day and month."""
    out: list[str] = []
    strings: list = []
    g = p.get
    if visual == "deal":
        _enum(out, "payload.kind", g("kind"), DEAL_KINDS)
        _cap(out, "payload.from", g("from"), 28)
        _cap(out, "payload.to", g("to"), 28)
        _cap(out, "payload.amount", g("amount"), 16, required=False)
        _cap(out, "payload.terms", g("terms"), 32, required=False)
        _cap(out, "payload.to_does", g("to_does"), 48)
        _enum(out, "payload.status", g("status"), DEAL_STATUS, required=False)
        strings += [g("from"), g("to"), g("amount"), g("terms"), g("to_does")]
    elif visual == "availability":
        _cap(out, "payload.player", g("player"), 32)
        _enum(out, "payload.status", g("status"), AVAILABILITY_STATUS)
        _cap(out, "payload.reason", g("reason"), 24, required=False)
        _cap(out, "payload.return", g("return"), 24, required=False)
        strings += [g("player"), g("reason"), g("return")]
        for n, f in enumerate(_objs(out, "payload.fixtures", g("fixtures") or [], 0, 3)):
            _cap(out, f"payload.fixtures[{n}].vs", f.get("vs"), 18)
            _cap(out, f"payload.fixtures[{n}].date", f.get("date"), 8, required=False)
            _enum(out, f"payload.fixtures[{n}].plays", f.get("plays"), PLAYS)
            strings += [f.get("vs"), f.get("date")]
    elif visual == "scoreline":
        _cap(out, "payload.home", g("home"), 20)
        _cap(out, "payload.away", g("away"), 20)
        _cap(out, "payload.competition", g("competition"), 32)
        _cap(out, "payload.note", g("note"), 48, required=False)
        score = g("score")
        if (not isinstance(score, list) or len(score) != 2
                or not all(isinstance(x, int) and not isinstance(x, bool) and 0 <= x <= 99 for x in score)):
            out.append("payload.score must be two whole numbers, home then away")
        else:
            a, b = score
            text = _cited_text(cited, items)
            if not re.search(rf"(?<!\d)(?:{a}\s*[-–:]\s*{b}|{b}\s*[-–:]\s*{a})(?!\d)", text):
                out.append(f"payload.score {a}-{b} is not a score any cited item gives")
        strings += [g("home"), g("away"), g("competition"), g("note")]
        for n, sc in enumerate(_objs(out, "payload.scorers", g("scorers") or [], 0, 4)):
            _cap(out, f"payload.scorers[{n}].name", sc.get("name"), 18)
            _cap(out, f"payload.scorers[{n}].minute", sc.get("minute"), 8, required=False)
            _enum(out, f"payload.scorers[{n}].side", sc.get("side"), ("home", "away"))
            strings += [sc.get("name"), sc.get("minute")]
    elif visual == "stakes":
        _cap(out, "payload.fixture", g("fixture"), 32)
        _cap(out, "payload.when", g("when"), 24)
        strings += [g("fixture"), g("when")]
        outcomes = _objs(out, "payload.outcomes", g("outcomes"), 2, 3)
        for n, o in enumerate(outcomes):
            _enum(out, f"payload.outcomes[{n}].if", o.get("if"), OUTCOMES)
            _cap(out, f"payload.outcomes[{n}].then", o.get("then"), 36)
            strings.append(o.get("then"))
        if len({o.get("if") for o in outcomes}) < len(outcomes):
            out.append("payload.outcomes: each of win, draw and loss at most once")
    elif visual == "incident":
        _cap(out, "payload.symptom", g("symptom"), 60)
        affects = g("affects") or []
        if not isinstance(affects, list) or len(affects) > 3:
            out.append("payload.affects must hold at most 3 items")
            affects = []
        for n, a in enumerate(affects):
            _cap(out, f"payload.affects[{n}]", a, 28)
        reports = g("reports")
        if reports is not None and (not isinstance(reports, int) or isinstance(reports, bool) or reports < 1):
            out.append("payload.reports must be a whole number of at least 1, or null")
        elif isinstance(reports, int) and reports > max(1, len(cited)) and not re.search(
                rf"(?<!\d)(?:{reports}|{_NUMBER_WORDS.get(reports, '-')})\s+(?:\w+\s+)?"
                r"(?:reports?|developers?|threads?|posts?|users?|people|complaints?)\b",
                _cited_text(cited, items)):
            out.append(f"payload.reports is {reports}, more than the cited items, and no cited item gives that count")
        _enum(out, "payload.vendor", g("vendor"), VENDOR, required=False)
        _cap(out, "payload.since", g("since"), 24, required=False)
        _cap(out, "payload.workaround", g("workaround"), 60, required=False)
        strings += [g("symptom"), *affects, g("since"), g("workaround")]
    elif visual == "countdown":
        _cap(out, "payload.what", g("what"), 48)
        _cap(out, "payload.do", g("do"), 60, required=False)
        d = g("date")
        if not isinstance(d, str) or not _date_in(d, cited, items):
            out.append(f"payload.date {d} is not a date any cited item gives (day and month)")
        elif not _countdown_year_ok(d, cited, items):
            out.append(f"payload.date {d}: with no year in the sources, use the next time that day comes round")
        strings += [g("what"), g("do")]
    elif visual == "case":
        _cap(out, "payload.court", g("court"), 40)
        _cap(out, "payload.asked", g("asked"), 64)
        _cap(out, "payload.next", g("next"), 32, required=False)
        strings += [g("court"), g("asked"), g("next")]
        for n, st in enumerate(_objs(out, "payload.steps", g("steps"), 3, 4)):
            _cap(out, f"payload.steps[{n}].label", st.get("label"), 16)
            _cap(out, f"payload.steps[{n}].date", st.get("date"), 12, required=False)
            if not isinstance(st.get("done"), bool):
                out.append(f"payload.steps[{n}].done must be true or false")
            strings += [st.get("label"), st.get("date")]
    elif visual == "scale":
        kind, level, value = g("scale"), g("level"), g("value")
        kind = kind if isinstance(kind, str) else None  # a list or object here must not crash
        _enum(out, "payload.scale", kind, tuple(SCALES))
        steps = SCALES.get(kind, ()) if kind else ()
        for k in ("level", "previous"):
            v = g(k)
            if v is None and k == "previous":
                continue
            if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v < max(1, len(steps)):
                out.append(f"payload.{k} must be a step index from 0 to {max(0, len(steps) - 1)}")
        text = _cited_text(cited, items)
        if kind == "grap" and "grap" not in text:
            out.append("payload.scale is grap but no cited item mentions GRAP")
        if value is not None:
            if not isinstance(value, int) or isinstance(value, bool):
                out.append("payload.value must be a whole number or null")
            else:
                strings.append(str(value))  # traced for both scales
        if kind == "aqi":
            if not isinstance(value, int) or isinstance(value, bool):
                out.append("payload.value must be the AQI reading")
            elif isinstance(level, int) and level != aqi_band(value):
                out.append(f"payload.level does not match the band of AQI {value}")
            prev = g("previous")
            if isinstance(prev, int) and not isinstance(prev, bool) and isinstance(value, int):
                # readings are numbers written within a few words after "AQI", not any number at all
                near = " ".join(m.group(0) for m in re.finditer(r"\baqi\b.{0,60}", _cited_text(cited, items)))
                readings = [v for v in _numbers(near) if float(v).is_integer() and 0 <= v <= 999 and v != value]
                if not any(aqi_band(int(v)) == prev for v in readings):
                    out.append("payload.previous: no other AQI reading in the sources falls in that band")
        if kind == "grap":
            for k in ("level", "previous"):
                v = g(k)
                if isinstance(v, int) and not isinstance(v, bool) and 0 <= v < 4:
                    roman = ("i", "ii", "iii", "iv")[v]
                    if not re.search(rf"\b(?:stage|grap)[\s-]*(?:{roman}|{v + 1})\b", text):
                        out.append(f"payload.{k}: no cited item names GRAP stage {v + 1}")
    elif visual == "rumour":
        _cap(out, "payload.player", g("player"), 32)
        _cap(out, "payload.from", g("from"), 24)
        _cap(out, "payload.to", g("to"), 24)
        _cap(out, "payload.fee", g("fee"), 20, required=False)
        _cap(out, "payload.source", g("source"), 32)
        fee = g("fee")
        if _nonempty_str(fee):
            text = _cited_text(cited, items)
            for sym, words in (("€", "€|euro"), ("£", "£|pound"), ("$", "\\$|dollar|usd"), ("₹", "₹|rs|inr|rupee|crore|lakh")):
                if sym in fee and not re.search(rf"(?:{words})", text):
                    out.append(f"payload.fee is in {sym}, which no cited item uses")
        _enum(out, "payload.tier", g("tier"), RUMOUR_TIERS)
        strings += [g("player"), g("from"), g("to"), g("fee"), g("source")]
    elif visual == "steps":
        steps = g("steps")
        if not isinstance(steps, list) or len(steps) != 3:
            out.append("payload.steps must hold exactly 3 steps")
            steps = []
        for n, st in enumerate(steps):
            _cap(out, f"payload.steps[{n}]", st, 60)
        strings += steps
    for w in _unnamed(strings, cited, items):
        out.append(f"payload has the name {w!r}, which no cited item contains")
    for w in _untraced(strings, cited, items):
        out.append(f"payload has the number {w}, which no cited item contains")
    return out


_NUMBER_WORDS = dict(enumerate(("zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
                                  "nine", "ten", "eleven", "twelve")))


def _slide_format_caps(kind: str, p: dict) -> list[str]:
    """A format on a 320px slide holds less than on a post (docs/design-visuals.md 8, phase C)."""
    n = lambda k: len(p.get(k)) if isinstance(p.get(k), list) else 0
    if kind == "key-facts" and n("facts") > 3:
        return ["a key-facts slide holds at most 3 facts"]
    if kind == "factsheet" and (n("has") > 2 or n("lacks") > 1):
        return ["a factsheet slide holds at most 2 ticks and 1 cross"]
    if kind == "deal" and isinstance(p.get("to_does"), str) and len(p["to_does"]) > 32:
        return ["a deal slide's to_does is at most 32 characters"]
    return []


def _countdown_year_ok(iso: str, cited: set[str], items: dict[str, ItemFacts], *,
                       today: date | None = None) -> bool:
    """A Countdown's year: written in a cited item, or else the next time that day and month
    comes round (today included), so "9 November" never becomes last year or next."""
    d = date.fromisoformat(iso)
    if re.search(rf"\b{d.year}\b", _cited_text(cited, items)):
        return True
    ref = today or date.today()
    try:
        nxt = d.replace(year=ref.year)
    except ValueError:  # 29 February
        return False
    if nxt < ref:
        nxt = nxt.replace(year=ref.year + 1)
    return d == nxt


def visual_seconds(visual: str, slides: list) -> int:
    return 50 if slides or visual in ("chart", "table", "timeline", "pitch") else 35


def _payload_numbers(v, key: str | None = None) -> dict[float, str]:
    """Numbers in every string or number inside a payload, by value (ids are labels,
    not claims). A number value is used as is, never re-formatted into digit runs."""
    if key == "item_id" or isinstance(v, bool):
        return {}
    if isinstance(v, str):
        return _numbers(v)
    if isinstance(v, (int, float)):
        return {abs(float(v)): _written(abs(v))}
    out: dict[float, str] = {}
    if isinstance(v, dict):
        for k, x in v.items():
            for n, w in _payload_numbers(x, k).items():
                out.setdefault(n, w)
    elif isinstance(v, list):
        for x in v:
            for n, w in _payload_numbers(x).items():
                out.setdefault(n, w)
    return out


def slide_problems(slides: list, *, brief: str, cited: set[str],
                   items: dict[str, ItemFacts]) -> list[str]:
    if not slides:
        return []
    out: list[str] = []
    if not 2 <= len(slides) <= 4:
        out.append(f"slides must number two to four, got {len(slides)}")
    first = slides[0].get("kind") if isinstance(slides[0], dict) else None
    if first != "cover":
        out.append("slides[0] must be a cover")
    in_brief = set(_numbers(brief))
    watch = "What to watch next:" in brief
    for n, s in enumerate(slides):
        tag = f"slides[{n}]"
        if not isinstance(s, dict):
            out.append(f"{tag} must be an object")
            continue
        kind, title, body, payload = s.get("kind"), s.get("title", ""), s.get("body", ""), s.get("payload", {})
        if kind not in SLIDE_KINDS:
            out.append(f"{tag}.kind {kind!r} is not one of {', '.join(SLIDE_KINDS)}")
            continue
        if not isinstance(title, str) or not isinstance(body, str):
            out.append(f"{tag} title and body must be strings")
            continue
        if kind == "cover":
            sub = payload_problems("cover", payload, cited=cited, items=items, check_cover_digits=False)
        elif kind in ("chart", "table"):
            sub = format_payload_problems("C" if kind == "chart" else "B", payload, cited)
        elif kind in SLIDE_FORMATS:
            sub = payload_problems(kind, payload, cited=cited, items=items)
            if len(title.split()) > 4:
                sub.append("title must be 4 words or fewer")
            if body.strip():
                sub.append("a format slide has no body (its payload is the slide)")
            sub += _slide_format_caps(kind, payload if isinstance(payload, dict) else {})
        else:
            sub = []
        out += [f"{tag} {p}" for p in sub]
        if kind == "table" and isinstance(payload, dict) and isinstance(payload.get("rows"), list) \
                and len(payload["rows"]) > 4:
            out.append(f"{tag} a table slide may have at most 4 rows, got {len(payload['rows'])}")
        if kind == "chart" and isinstance(payload, dict) and isinstance(payload.get("series"), list) \
                and len(payload["series"]) > 6:
            out.append(f"{tag} a chart slide may have at most 6 points, got {len(payload['series'])}")
        if kind == "text":
            if len(title.split()) > 4:
                out.append(f"{tag}.title must be 4 words or fewer")
            if len(body.split()) > 35:
                out.append(f"{tag}.body must be 35 words or fewer")
        if kind == "what-next":
            if len(body.split()) > 60:
                out.append(f"{tag}.body must be 60 words or fewer")
            if n != len(slides) - 1:
                out.append(f"{tag} what-next must be the last slide")
        nums = {**_payload_numbers(payload), **_numbers(body), **_numbers(title)}
        for v, w in sorted(nums.items()):
            if v not in in_brief:
                out.append(f"{tag} has the number {w}, which the brief does not contain")
    # highlight mistakes are not problems: present.deck_for ignores a mark on the cover and
    # keeps only the first other one, so a good deck is never lost over its colour
    if watch and not (isinstance(slides[-1], dict) and slides[-1].get("kind") == "what-next"):
        out.append("the brief has a 'What to watch next:' line, so the last slide must be a what-next")
    return out
