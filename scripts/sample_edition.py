#!/usr/bin/env python3
"""Render a sample edition that shows every visual kind, with no model call.

Usage: .venv/bin/python scripts/sample_edition.py --out out/sample

Builds an in-memory SQLite database holding one card of every visual kind (cover, chart,
table, timeline, versus, before-after, pitch, photo, quote), a four-slide deck (cover,
table, text, what-next) and a two-slide deck, renders it with ``render_edition`` and prints
the HTML path. All text is sample text that says what its card demonstrates; the masthead
date is the run date. The photo card's image URL is ``https://invalid.example/missing.jpg``,
so the page shows the photo's cover fallback. Check the layout with
``scripts/shot.py <printed path> <shots dir>``.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from newshouse.catalogue import VISUAL_FORMAT, visual_seconds  # noqa: E402
from newshouse.db import get_engine, init_db, session_scope  # noqa: E402
from newshouse.edition_config import load_edition_config  # noqa: E402
from newshouse.models import (AlsoHappened, Card, Cluster, ClusterItem, Edition, Item,  # noqa: E402
                              ItemSource, Source)
from newshouse.render_static import render_edition  # noqa: E402

MISSING_IMAGE = "https://invalid.example/missing.jpg"

PITCH_NAMES = ("Szczęsny", "Koundé", "Cubarsí", "Martínez", "Balde", "Pedri", "De Jong", "Gavi",
               "Yamal", "Lewandowski", "Raphinha")

# One dict per card: item text (what the truth checks read), cluster topics and the card fields.
CARDS: list[dict] = [
    {"topics": ["intl-biz-tech"],
     "item": {"title": "Sample: worst-case deal", "body": "Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww  3-0 on 2026 and 9 November 2026 for €999m euros. 12' 55' 80' 90'. Mmm Www Ww Mm"},
     "visual": "deal", "payload": {"kind": "acquisition", "from": 'Mmmm Wwww Mmmm Wwww Mmmm Www', "to": 'Mmmm Wwww Mmmm Wwww Mmmm Www', "amount": "€999m",
                                   "terms": 'Mmmm Wwww Mmmm Wwww Mmmm Wwww Mm', "to_does": 'Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Www', "status": "needs approval"},
     "headline": "Sample worst-case deal: long names on both sides",
     "line": "Worst case for the Deal card."},
    {"topics": ["football"],
     "item": {"title": "Sample: worst-case scoreline", "body": "Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww  3-0 on 2026 and 9 November 2026 for €999m euros. 12' 55' 80' 90'. Mmm Www Ww Mm"},
     "visual": "scoreline", "payload": {"home": 'Mmmm Wwww Mmmm Wwww', "away": 'Mmmm Wwww Mmmm Wwww', "score": [3, 0], "competition": 'Mmmm Wwww Mmmm Wwww Mmmm Wwww Mm',
                                        "scorers": [{"name": 'Mmmm Wwww Mmmm Www', "minute": m, "side": "home"} for m in ("12'", "55'", "80'", "90'")],
                                        "note": 'Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Www'},
     "headline": "Sample worst-case scoreline: four scorers on one side",
     "line": "Worst case for the Scoreline."},
    {"topics": ["football"],
     "item": {"title": "Sample: worst-case stakes", "body": "Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww  3-0 on 2026 and 9 November 2026 for €999m euros. 12' 55' 80' 90'. Mmm Www Ww Mm"},
     "visual": "stakes", "payload": {"fixture": 'Mmmm Wwww Mmmm Wwww Mmmm Wwww Mm', "when": 'Mmmm Wwww Mmmm Wwww Mmmm',
                                     "outcomes": [{"if": k, "then": 'Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm W'} for k in ("win", "draw", "loss")]},
     "headline": "Sample worst-case stakes: three long outcomes",
     "line": "Worst case for Stakes."},
    {"topics": ["football"],
     "item": {"title": "Sample: worst-case rumour", "body": "Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww  3-0 on 2026 and 9 November 2026 for €999m euros. 12' 55' 80' 90'. Mmm Www Ww Mm"},
     "visual": "rumour", "payload": {"player": 'Mmmm Wwww Mmmm Wwww Mmmm Wwww Mm', "from": 'Mmmm Wwww Mmmm Wwww Mmmm', "to": 'Mmmm Wwww Mmmm Wwww Mmmm', "fee": "€999m",
                                     "source": 'Mmmm Wwww Mmmm Wwww Mmmm Wwww Mm', "tier": "reporter"},
     "headline": "Sample worst-case rumour: every field at its longest",
     "line": "Worst case for the Rumour card."},
    {"topics": ["ai-models"],
     "item": {"title": "Sample: worst-case countdown", "body": "Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww  3-0 on 2026 and 9 November 2026 for €999m euros. 12' 55' 80' 90'. Mmm Www Ww Mm"},
     "visual": "countdown", "payload": {"date": "2026-11-09", "what": 'Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Www', "do": 'Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww'},
     "headline": "Sample worst-case countdown: long what and do",
     "line": "Worst case for the Countdown."},
    {"topics": ["ai-tools"],
     "item": {"title": "Sample: worst-case steps", "body": "Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww  3-0 on 2026 and 9 November 2026 for €999m euros. 12' 55' 80' 90'. Mmm Www Ww Mm"},
     "visual": "steps", "payload": {"steps": ['Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww'] * 3},
     "headline": "Sample worst-case steps: three long steps",
     "line": "Worst case for Steps."},
    {"topics": ["intl-biz-tech"],
     "item": {"title": "Sample: worst-case format slides", "body": "Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww  3-0 on 2026 and 9 November 2026 for €999m euros. 12' 55' 80' 90'. Mmm Www Ww Mm"},
     "visual": "none", "payload": {},
     "slides": [
         {"kind": "cover", "title": "", "body": "", "payload": {"big": "€999m", "label": "Sample deck", "line": "Worst-case format slides."}},
         {"kind": "key-facts", "title": "Mmmm Wwww Mmmm Wwww", "body": "",
          "payload": {"facts": [{"label": "Mmmmmmmmmmmmmm", "value": 'Mmmm Wwww Mmmm Wwww Mmmm Wwww Mm'}] * 3}},
         {"kind": "factsheet", "title": "Mmmm Wwww Mmmm Wwww", "body": "",
          "payload": {"has": ['Mmmm Wwww Mmmm Wwww Mmmm W'] * 2, "lacks": ['Mmmm Wwww Mmmm Wwww Mmmm W'], "price": "€999m", "status": "waitlist", "where": 'Mmmm Wwww Mmmm Wwww Mmmm'}},
         {"kind": "deal", "title": "Mmmm Wwww Mmmm Wwww", "body": "",
          "payload": {"kind": "acquisition", "from": 'Mmmm Wwww Mmmm Wwww Mmmm Www', "to": 'Mmmm Wwww Mmmm Wwww Mmmm Www', "amount": "€999m", "terms": 'Mmmm Wwww Mmmm Wwww Mmmm Wwww Mm',
                      "to_does": 'Mmmm Wwww Mmmm Wwww Mmmm Wwww Mm', "status": "needs approval"}}],
     "brief": "Worst-case format slides for €999m.",
     "headline": "Sample worst-case format slides: each at its slide limit",
     "line": "Worst case for formats as slides."},
    {"topics": ["intl-biz-tech"],
     "item": {"title": "Sample: a deal post", "body": "OpenAI agrees to buy Pierre, whose developer tools power Codex, for $400M in an all-stock deal that needs approval."},
     "visual": "deal", "payload": {"kind": "acquisition", "from": "OpenAI", "to": "Pierre", "amount": "$400M",
                                   "terms": "all-stock", "to_does": "developer tools that power Codex", "status": "needs approval"},
     "headline": "Sample deal post: buyer, target and the price on the arrow",
     "line": "This card demonstrates the Deal card."},
    {"topics": ["football"],
     "item": {"title": "Sample: an availability post",
              "body": "Rodri is out with a right hamstring injury for about 3 weeks and will miss Atletico on 9 Nov and Getafe on 15 Nov; he could be back for Betis on 29 Nov."},
     "visual": "availability", "payload": {"player": "Rodri", "status": "out", "reason": "right hamstring", "return": "about 3 weeks",
                                           "fixtures": [{"vs": "Atletico", "date": "9 Nov", "plays": "miss"},
                                                        {"vs": "Getafe", "date": "15 Nov", "plays": "miss"},
                                                        {"vs": "Betis", "date": "29 Nov", "plays": "doubt"}]},
     "headline": "Sample availability post: a player out and the games he misses",
     "line": "This card demonstrates Availability."},
    {"topics": ["football"],
     "item": {"title": "Sample: a scoreline post",
              "body": "Barcelona beat Aston Villa 3-0 in the Champions League: Raphinha scored in the 12th and 55th minute and Yamal in the 80th, their first clean sheet since April 2025."},
     "visual": "scoreline", "payload": {"home": "Barcelona", "away": "Aston Villa", "score": [3, 0], "competition": "Champions League",
                                        "scorers": [{"name": "Raphinha", "minute": "12'", "side": "home"},
                                                    {"name": "Raphinha", "minute": "55'", "side": "home"},
                                                    {"name": "Yamal", "minute": "80'", "side": "home"}],
                                        "note": "first clean sheet since April 2025"},
     "headline": "Sample scoreline post: a result with its scorers",
     "line": "This card demonstrates the Scoreline."},
    {"topics": ["football"],
     "item": {"title": "Sample: a stakes post", "body": "Atletico v Barcelona on Sunday: a Barcelona win puts them five points clear; a loss puts Atletico one point ahead."},
     "visual": "stakes", "payload": {"fixture": "Atletico v Barcelona", "when": "Sunday",
                                     "outcomes": [{"if": "win", "then": "Barcelona five points clear"},
                                                  {"if": "loss", "then": "Atletico one point ahead"}]},
     "headline": "Sample stakes post: what each result would mean",
     "line": "This card demonstrates Stakes."},
    {"topics": ["ai-built"],
     "item": {"title": "Sample: an incident post",
              "body": "Two developers report 503 high demand errors on gemini-3.1-flash-lite and gemini-3.8-flash since 2 November; Google has not replied. Retrying with backoff helps."},
     "visual": "incident", "payload": {"symptom": "503 high demand errors", "affects": ["gemini-3.1-flash-lite", "gemini-3.8-flash"],
                                       "reports": 2, "vendor": "no reply", "since": "2 November", "workaround": "retrying with backoff helps"},
     "headline": "Sample incident post: a bug report and how sure we are",
     "line": "This card demonstrates the Incident card."},
    {"topics": ["ai-models"],
     "item": {"title": "Sample: a countdown post", "body": "gemini-2.5-flash calls move to 3.5-flash-lite on 1 December 2026; re-test on real recordings."},
     "visual": "countdown", "payload": {"date": "2026-12-01", "what": "gemini-2.5-flash calls move to 3.5-flash-lite",
                                        "do": "re-test on real recordings"},
     "headline": "Sample countdown post: days left to a deadline",
     "line": "This card demonstrates the Countdown."},
    {"topics": ["india-news"],
     "item": {"title": "Sample: a case post",
              "body": "The Supreme Court issued notice on the SFLC plea against facial surveillance on 3 November and will hear it on 20 November."},
     "visual": "case", "payload": {"court": "Supreme Court", "asked": "stop facial surveillance at protest sites",
                                   "next": "hearing on 20 November",
                                   "steps": [{"label": "plea filed", "date": None, "done": True},
                                             {"label": "notice issued", "date": "3 November", "done": True},
                                             {"label": "hearing", "date": "20 November", "done": False},
                                             {"label": "ruling", "date": None, "done": False}]},
     "headline": "Sample case post: where a court case stands",
     "line": "This card demonstrates the Case stepper."},
    {"topics": ["gurgaon-local"],
     "item": {"title": "Sample: a scale post", "body": "Gurugram AQI reached 324 (very poor), up from 268 a day earlier, as CAQM kept GRAP stage II."},
     "visual": "scale", "payload": {"scale": "aqi", "level": 4, "previous": 3, "value": 324},
     "headline": "Sample scale post: the AQI band, with yesterday marked",
     "line": "This card demonstrates the Scale."},
    {"topics": ["football"],
     "item": {"title": "Sample: a rumour post", "body": "Leipzig defender Castello Lukeba may join Barcelona for 65m euros, per Fabrizio Romano."},
     "visual": "rumour", "payload": {"player": "Castello Lukeba", "from": "Leipzig", "to": "Barcelona", "fee": "€65m",
                                     "source": "Fabrizio Romano", "tier": "reporter"},
     "headline": "Sample rumour post: a reported move and how sure the source is",
     "line": "This card demonstrates the Rumour card."},
    {"topics": ["ai-tools"],
     "item": {"title": "Sample: a steps post", "body": "Upload a photo of a sketch, ask Canvas to code it, then test and adjust it in the preview."},
     "visual": "steps", "payload": {"steps": ["Upload a photo of a sketch", "Ask Canvas to code it", "Test and adjust it in the preview"]},
     "headline": "Sample steps post: a method in three steps",
     "line": "This card demonstrates Steps."},
    {"topics": ["startups"],
     "item": {"title": "Sample: a deck of formats", "body": "Zipline raised $1.5B at a $21.5B valuation from Fidelity; it adds 300 Walmart sites to 21."},
     "visual": "none", "payload": {},
     "slides": [
         {"kind": "cover", "title": "", "body": "", "payload": {"big": "$1.5B", "label": "Sample deck", "line": "A deck whose slides are formats."}},
         {"kind": "deal", "title": "The round", "body": "", "highlight": True,
          "payload": {"kind": "funding", "from": "Fidelity", "to": "Zipline", "amount": "$1.5B", "terms": "at $21.5B valuation",
                      "to_does": "drone delivery", "status": None}},
         {"kind": "number", "title": "Walmart sites", "body": "",
          "payload": {"value": "300", "what": "new Walmart sites", "compare": {"label": "today", "value": "21"}}}],
     "brief": "Zipline raised $1.5B at a $21.5B valuation from Fidelity.\n\nIt adds 300 Walmart sites to the 21 it runs today.",
     "headline": "Sample format deck: a deal slide and a number slide",
     "line": "This card demonstrates the new formats as slides."},
    {"topics": ["india-news"],
     "item": {"title": "Sample: worst-case case", "body": "Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Www and 12 November, 13 November, 14 November, 15 November, 16 November."},
     "visual": "case", "payload": {"court": "Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww"[:40],
                                   "asked": ("Mmmm Wwww Mmmm Wwww " * 4)[:64], "next": "Mmmm Wwww Mmmm Wwww Mmmm Wwww Mm"[:32],
                                   "steps": [{"label": "Mmmm Wwww Mmmm Wwww Mmmm"[:16], "date": f"{d} November", "done": d < 14} for d in (12, 13, 14, 15)]},
     "headline": "Sample worst-case case: four long steps",
     "line": "Worst case for the Case stepper."},
    {"topics": ["football"],
     "item": {"title": "Sample: worst-case availability", "body": "Mmmm Wwww Mmmm Wwww Mmmm Wwww Mm misses Mmmm Wwww Mmmm Wwww and Mmmm Wwww Mmmm Www on 10 Nov 11 Nov 12 Nov 13 Nov."},
     "visual": "availability", "payload": {"player": "Mmmm Wwww Mmmm Wwww Mmmm Wwww Mm"[:32], "status": "doubt",
                                           "reason": "Mmmm Wwww Mmmm Wwww Mmmm"[:24], "return": "Mmmm Wwww Mmmm Wwww Mmmm"[:24],
                                           "fixtures": [{"vs": "Mmmm Wwww Mmmm Wwww"[:18], "date": f"{d} Nov", "plays": "miss"} for d in (10, 11, 12)]},
     "headline": "Sample worst-case availability: long names and three fixtures",
     "line": "Worst case for Availability."},
    {"topics": ["ai-built"],
     "item": {"title": "Sample: worst-case incident", "body": "Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww since Mmmm Wwww Mmmm Wwww Mmmm Www."},
     "visual": "incident", "payload": {"symptom": ("Mmmm Wwww " * 6)[:60], "affects": ["Mmmm Wwww Mmmm Wwww Mmmm Www"[:28]] * 3,
                                       "reports": 1, "vendor": "disputed", "since": "Mmmm Wwww Mmmm Wwww Mmmm"[:24],
                                       "workaround": ("Mmmm Wwww " * 6)[:60]},
     "headline": "Sample worst-case incident: every field at its longest",
     "line": "Worst case for the Incident card."},
    {"topics": ["ai-tools"],
     "item": {"title": "Sample: worst-case fact formats", "body": 'Wide Mmmm Wwww Mmmm Wwwwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mm Mmmm Wwww Mmmm Wwww Mm Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Www Mmmm Wwww Mmmm Wwww Mmmm $888,888.88 and $777,777.77, $99.99 a month.'},
     "visual": "factsheet", "payload": {"has": ['Wide Mmmm Wwww Mmmm Wwwwww'] * 3, "lacks": ['Wide Mmmm Wwww Mmmm Wwwwww'] * 2,
                                        "price": "$99.99 a month Mmmm Wwww Mm"[:28], "status": "waitlist", "where": 'Mmmm Wwww Mmmm Wwww Mmmm'},
     "headline": "Sample worst-case fact sheet: every line at its longest",
     "line": "Worst case for the fact sheet: three long ticks, two long crosses, a long footer."},
    {"topics": ["gurgaon-local"],
     "item": {"title": "Sample: worst-case what changes", "body": 'Wide Mmmm Wwww Mmmm Wwwwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mm Mmmm Wwww Mmmm Wwww Mm Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Www Mmmm Wwww Mmmm Wwww Mmmm $888,888.88 and $777,777.77, $99.99 a month. Delhi-NCR from 1 to 30 November.'},
     "visual": "changes", "payload": {"rows": [{"what": 'Mmmm Wwww Mmmm Wwww Mm', "change": 'Mmmm Wwww Mmmm Wwww Mmmm Wwww Mm'}] * 3,
                                      "from": "2026-11-01", "to": "2026-11-30", "where": 'Mmmm Wwww Mmmm Wwww Mmmm'},
     "headline": "Sample worst-case what changes: three long rows and a date bar",
     "line": "Worst case for What changes for you: every row at its longest."},
    {"topics": ["intl-biz-tech"],
     "item": {"title": "Sample: worst-case number", "body": 'Wide Mmmm Wwww Mmmm Wwwwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mm Mmmm Wwww Mmmm Wwww Mm Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Www Mmmm Wwww Mmmm Wwww Mmmm $888,888.88 and $777,777.77, $99.99 a month.'},
     "visual": "number", "payload": {"value": "$888,888.88", "what": 'Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Www',
                                     "compare": {"label": 'Mmmm Wwww Mmmm Wwww Mmmm', "value": "$777,777.77"}},
     "headline": "Sample worst-case number: a long figure with the vs line",
     "line": "Worst case for Number in context: the longest value, what and comparison."},
    {"topics": ["football"],
     "item": {"title": "Sample: worst-case key facts", "body": 'Wide Mmmm Wwww Mmmm Wwwwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mm Mmmm Wwww Mmmm Wwww Mm Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Wwww Mmmm Www Mmmm Wwww Mmmm Wwww Mmmm $888,888.88 and $777,777.77, $99.99 a month.'},
     "visual": "key-facts", "payload": {"facts": [{"label": "Mmmmmmmmmmmmmm", "value": 'Mmmm Wwww Mmmm Wwww Mmmm Wwww Mm'}] * 4},
     "headline": "Sample worst-case key facts: four long values",
     "line": "Worst case for Key facts: four values at their longest."},
    {"topics": ["startups"],
     "item": {"title": "Sample: a number post", "body": "Sample Robotics raised $465M at listing against H1 revenue of $174K."},
     "visual": "number", "payload": {"value": "$465M", "what": "raised at listing",
                                     "compare": {"label": "H1 revenue", "value": "$174K"}},
     "headline": "Sample number post: a figure shown next to the one it is measured against",
     "line": "This card demonstrates Number in context: two amounts in one currency draw as bars."},
    {"topics": ["football"],
     "item": {"title": "Sample: a key facts post", "body": "Raphinha signs a contract renewal with president Laporta on Thursday."},
     "visual": "key-facts", "payload": {"facts": [{"label": "Who", "value": "Raphinha"},
                                                  {"label": "What", "value": "contract renewal"},
                                                  {"label": "When", "value": "Thursday"},
                                                  {"label": "With", "value": "president Laporta"}]},
     "headline": "Sample key facts post: four facts under the headline",
     "line": "This card demonstrates Key facts, the fallback for a story with a few hard facts."},
    {"topics": ["gurgaon-local"],
     "item": {"title": "Sample: a what-changes post",
              "body": "Offices at most 50% in person and dust-raising construction stopped from 1 to 30 November across Delhi-NCR. Parking fees go up."},
     "visual": "changes", "payload": {"rows": [{"what": "Offices", "change": "at most 50% in person"},
                                               {"what": "Construction", "change": "dust-raising work stopped"},
                                               {"what": "Parking", "change": "fees go up"}],
                                      "from": "2026-11-01", "to": "2026-11-30", "where": "Delhi-NCR"},
     "headline": "Sample what-changes post: a rule's effects and its dates",
     "line": "This card demonstrates What changes for you: rows of effects and the period with today on it."},
    {"topics": ["ai-tools"],
     "item": {"title": "Sample: a fact sheet post",
              "body": "The sample agent sits on hold, books appointments and negotiates bills for paid users at $30 a month. It does not work outside the US."},
     "visual": "factsheet", "payload": {"has": ["sits on hold", "books appointments", "negotiates bills"],
                                        "lacks": ["outside the US"], "price": "$30 a month",
                                        "status": "limited", "where": "paid users"},
     "headline": "Sample fact sheet post: what a launch does and does not do",
     "line": "This card demonstrates the Fact sheet: ticks, crosses, status, where and price."},
    {"topics": ["ai-models"],
     "item": {"title": "Sample: a cover post", "body": "The cover shows one big figure: 42 pages."},
     "visual": "cover", "payload": {"big": "42", "label": "Sample cover", "line": "A big figure, a label, a line."},
     "headline": "Sample cover post: one big figure leads the edition",
     "line": "This card demonstrates the cover visual, the default for any story without a structure."},
    {"topics": ["india-tech-biz"],
     "item": {"title": "Sample: a chart post", "body": "Sample bars of 12, 30 and 18."},
     "visual": "chart",
     "payload": {"series": [{"label": "Mon", "value": 12, "item_id": "{i}"},
                            {"label": "Tue", "value": 30, "item_id": "{i}"},
                            {"label": "Wed", "value": 18, "item_id": "{i}"}],
                 "unit": "units", "caption": "Sample numbers, not real data"},
     "headline": "Sample chart post: three bars, the biggest in the accent",
     "line": "This card demonstrates the chart visual: bars with a unit and a caption."},
    {"topics": ["ai-built"],
     "item": {"title": "Sample: a table post", "body": "Plan A costs $10, Plan B $20."},
     "visual": "table",
     "payload": {"columns": ["Plan", "Price", "Was"],
                 "rows": [{"cells": ["Plan A", "$10", "$12"], "yours": True, "new": False},
                          {"cells": ["Plan B", "$20", "$20"], "yours": False, "new": True}]},
     "headline": "Sample table post: your plan against the new one",
     "line": "This card demonstrates the table visual, with yours and new tags."},
    {"topics": ["geopolitics"], "thread": ("sample-thread", 3),
     "item": {"title": "Sample: a timeline post", "body": "Third chapter of a sample thread."},
     "visual": "timeline",
     "payload": {"chapters": [{"title": "Sample chapter one", "date": "2026-10-28", "read": True},
                              {"title": "Sample chapter two", "date": "2026-10-30", "read": False}],
                 "delta": "Today's chapter adds one new fact to the thread."},
     "headline": "Sample timeline post: chapter three of a running story",
     "line": "This card demonstrates the timeline visual: today on top, earlier chapters below."},
    {"topics": ["india-news"],
     "item": {"title": "Sample: a versus post", "body": "Two sides of a sample argument."},
     "visual": "versus",
     "payload": {"for": ["Supporters say it saves time", "It is cheaper to run"],
                 "against": ["Critics say it was rushed"],
                 "stands": "Still under debate in this sample."},
     "headline": "Sample versus post: the case for and against",
     "line": "This card demonstrates the versus visual: two sides and where it stands."},
    {"topics": ["gurgaon-local"],
     "item": {"title": "Sample: a before-after post", "body": "A sample rule change."},
     "visual": "before-after",
     "payload": {"before": "Parking was free on weekends.", "after": "Parking is charged every day.",
                 "effective": "from Monday", "applies_to": "sample city lots"},
     "headline": "Sample before-after post: a rule that changed",
     "line": "This card demonstrates the before-after visual for a change in rules."},
    {"topics": ["football"],
     "item": {"title": "Sample: a pitch post",
              "body": "Sample line-up, back line forward: " + ", ".join(PITCH_NAMES[:11])
                      + ". Out: Ter Stegen (knee injury), Fermín López (suspended), Christensen (illness)."},
     "visual": "pitch",
     "payload": {"rows": [[{"pos": "GK", "name": "Szczęsny"}],
                          [{"pos": "RB", "name": "Koundé"}, {"pos": "CB", "name": "Cubarsí"},
                           {"pos": "CB", "name": "Martínez"}, {"pos": "LB", "name": "Balde"}],
                          [{"pos": "CM", "name": "Pedri"}, {"pos": "CM", "name": "De Jong"},
                           {"pos": "CM", "name": "Gavi"}],
                          [{"pos": "RW", "name": "Yamal"}, {"pos": "ST", "name": "Lewandowski"},
                           {"pos": "LW", "name": "Raphinha"}]],
                 "note": "Worst case: four rows, three out. Sample names.",
                 "out": [{"name": "Ter Stegen", "why": "knee injury"}, {"name": "Fermín López", "why": "suspended"},
                         {"name": "Christensen", "why": "illness"}]},
     "headline": "Sample pitch post: a Barça line-up in kit colours",
     "line": "This card demonstrates the pitch visual, coloured by the configured team kit."},
    {"topics": ["movies"], "image": MISSING_IMAGE,
     "item": {"title": "Sample: a photo post", "body": "A sample photo whose image does not load."},
     "visual": "photo",
     "payload": {"item_id": "{i}", "alt": "A sample photo that is meant to fail", "credit": "Sample credit"},
     "headline": "Sample photo post: fallback cover when the image fails",
     "line": "This card demonstrates the photo visual; its image fails, so the cover fallback shows."},
    {"topics": ["product-design"], "tone": "good",
     "item": {"title": "Sample: a quote post",
              "body": "The designer said: “Make the first screen do one job well.”"},
     "visual": "quote",
     "payload": {"text": "Make the first screen do one job well.", "who": "A sample designer",
                 "where": "in a sample interview", "item_id": "{i}"},
     "headline": "Sample quote post: one line, said by someone",
     "line": "This card demonstrates the quote visual; the quote text appears in its item."},
    {"topics": ["edtech-competitors"],
     "item": {"title": "Sample: a four-slide deck", "body": "Course prices of 1299 and 999."},
     "visual": "none", "payload": {},
     "slides": [
         {"kind": "cover", "title": "", "body": "",
          "payload": {"big": "₹1,299", "label": "Sample deck", "line": "Four slides: cover, table, text, what next."}},
         {"kind": "table", "title": "Prices compared", "body": "Sample prices.",
          "payload": {"columns": ["Course", "Price", "Was"],
                      "rows": [{"cells": ["Course A", "₹1,299", "₹999"], "yours": True, "new": False},
                               {"cells": ["Course B", "₹999", "₹999"], "yours": False, "new": False},
                               {"cells": ["Course C", "₹1,299", "₹1,299"], "yours": False, "new": True}]}},
         {"kind": "text", "title": "What it means", "body": "A text slide holds one short paragraph "
          "of 35 words or fewer, so it reads at a glance on a phone without scrolling.", "payload": {},
          "highlight": True},
         {"kind": "what-next", "title": "What to watch", "body": "The what-next slide closes the deck "
          "with what happens next.\n\nIt holds at most 60 words and points to the full brief below.",
          "payload": {}}],
     "brief": "This sample deck compares course prices of ₹1,299 and ₹999 across three sample courses.\n\n"
              "A text slide holds 35 words or fewer; a what-next slide holds 60 words or fewer.\n\n"
              "What to watch next: whether the sample prices change.",
     "headline": "Sample deck: four slides on course prices",
     "line": "This card demonstrates a four-slide deck: cover, table, text and what-next."},
    {"topics": ["intl-biz-tech"], "tone": "bad",
     "item": {"title": "Sample: a two-slide deck", "body": "Sample figures of 8, 5 and 3."},
     "visual": "none", "payload": {},
     "slides": [
         {"kind": "cover", "title": "", "body": "",
          "payload": {"big": "8 to 3", "label": "Sample deck", "line": "Two slides: a cover and a chart."}},
         {"kind": "chart", "title": "Falling count", "body": "Sample numbers.",
          "payload": {"series": [{"label": "2024", "value": 8, "item_id": "{i}"},
                                 {"label": "2025", "value": 5, "item_id": "{i}"},
                                 {"label": "2026", "value": 3, "item_id": "{i}", "key": True}],
                      "unit": "count", "caption": "Sample numbers, not real data"}}],
     "brief": "This sample deck shows a count falling from 8 in 2024 to 5 in 2025 and 3 in 2026.",
     "headline": "Sample deck: two slides, a cover and a chart",
     "line": "This card demonstrates the shortest deck: two slides."},
    {"topics": ["geopolitics"], "thread": ("sample-long-thread", 6),
     "item": {"title": "Sample: a long timeline post", "body": "Sixth chapter of a sample thread."},
     "visual": "timeline",
     "payload": {"chapters": [{"title": "Sample earlier chapter %d with a deliberately long title that wraps over several lines on a phone screen" % k,
                               "date": "2026-10-%02d" % (10 + k), "read": k < 3} for k in range(1, 6)],
                 "delta": "Today's chapter adds a long delta that keeps going for a while so that it wraps over many lines on a narrow phone, to prove the collapsed visual clamps it instead of growing past the height cap."},
     "headline": "Sample long timeline post: five long earlier chapters",
     "line": "Worst case for the timeline visual: five long chapters and a long delta."},
    {"topics": ["edtech-competitors"],
     "item": {"title": "Sample: a long-table deck", "body": "Course prices of 1299 and 999."},
     "visual": "none", "payload": {},
     "slides": [
         {"kind": "cover", "title": "", "body": "",
          "payload": {"big": "₹1,299", "label": "Sample deck", "line": "Worst case: a table slide of long cells."}},
         {"kind": "table", "title": "Prices compared, long cells", "body": "Sample prices.",
          "payload": {"columns": ["Course", "Price", "Was"],
                      "rows": [{"cells": ["Course %s with a very long label that wraps over several lines on a phone" % n,
                                          "₹1,299 a year, paid monthly", "₹999 before the price change"],
                                "yours": n == "A", "new": n == "D"} for n in "ABCD"]}}],
     "brief": "This sample deck compares course prices of ₹1,299 and ₹999 across four sample courses.",
     "headline": "Sample long-table deck: four rows of long cell text",
     "line": "Worst case for a table slide: four rows of long cell text."},
    {"topics": ["intl-biz-tech"],
     "item": {"title": "Sample: a stacked post", "body": "3 outlets cover the same sample story."},
     "visual": "cover", "payload": {"big": "3 outlets", "label": "Sample stack", "line": "One story, three articles."},
     "stack": [
         {"cluster_id": "sample-stack-m1", "headline": "Sample second outlet reports the same story with a longer headline that wraps",
          "line": "A sample line from the second outlet, one or two sentences about what its article adds to the story.",
          "url": "https://sample.invalid/stack-1", "source": "Sample Daily"},
         {"cluster_id": "sample-stack-m2", "headline": "Sample third outlet: headline only",
          "line": "", "url": "https://sample.invalid/stack-2", "source": "Sample Wire"},
         {"cluster_id": "sample-stack-m3", "headline": "Sample fourth outlet adds a detail",
          "line": "A sample line from the fourth outlet.", "url": "https://sample.invalid/stack-3", "source": "Sample Times"}],
     "headline": "Sample stacked post: three more articles on one story",
     "line": "This card demonstrates a stack: the chip below, and a swipe strip when expanded."},
]

ALSO = ["Sample also-happened line: a story below the cut, shown as one sentence.",
        "Another sample line, cut for the time budget."]


def _fill(v, iid: str):
    """Replace the ``{i}`` placeholder with the card's item id anywhere in a payload."""
    if isinstance(v, str):
        return v.replace("{i}", iid)
    if isinstance(v, list):
        return [_fill(x, iid) for x in v]
    if isinstance(v, dict):
        return {k: _fill(x, iid) for k, x in v.items()}
    return v


def seed(session, *, today: date | None = None) -> Edition:
    """Add the sample source, items, clusters and cards; return the edition."""
    now = datetime.now(timezone.utc).replace(microsecond=0)
    today = today or date.today()
    session.add(Source(id="sample", name="Sample Wire", topics=[], tier="mainstream", kind="rss",
                       url="https://sample.invalid/feed", paywall=False))
    ed = Edition(id="sample", date=today, built_at=now, budget_seconds=900, cut_score=40.0)
    ed.live = {
        "aqi": {"aqi": 168, "band": "Moderate", "dot": "butter", "at": "2026-11-04T11:00"},
        "match": {"text": "Barça v Aston Villa", "when": "Wed 1:30 am", "iso": "2026-11-11T20:00:00+00:00",
                  "competition": "UEFA Champions League"},
        "market": {"as_of": "2026-11-04T15:30:00+05:30", "indices": [
            {"name": "Nifty 50", "symbol": "NIFTY 50", "level": 23960.6, "prev_close": 23810.85,
             "change_pct": 0.63, "trend": [{"label": "1 week", "pct": 1.84}, {"label": "1 month", "pct": -0.42},
                                           {"label": "1 year", "pct": -6.4}]}]},
    }
    session.add(ed)
    session.flush()
    for n, spec in enumerate(CARDS, start=1):
        iid, cid = f"sample-i{n}", f"sample-c{n}"
        it = spec["item"]
        session.add(Item(id=iid, title=it["title"], url=f"https://sample.invalid/{n}",
                         canonical_url=f"https://sample.invalid/{n}", teaser=it["title"], body=it["body"],
                         published_at=now, first_seen_at=now, dated=True, topics=[], raw={},
                         image_url=spec.get("image")))
        session.add(Cluster(id=cid, window_start=now, topics=spec["topics"], tone=spec.get("tone")))
        session.flush()
        session.add(ItemSource(item_id=iid, source_id="sample"))
        session.add(ClusterItem(cluster_id=cid, item_id=iid))
        slides = _fill(spec.get("slides", []), iid)
        thread_id, chapter = spec.get("thread", (None, None))
        session.add(Card(
            id=f"sample-{n}", edition_id=ed.id, rank=n, cluster_id=cid, thread_id=thread_id, chapter=chapter,
            visual=spec["visual"], format=VISUAL_FORMAT[spec["visual"]], slides=slides, tone=spec.get("tone"), stack=spec.get("stack", []),
            payload=_fill(spec["payload"], iid), headline=spec["headline"], line=spec["line"],
            para="Sample paragraph.",
            brief=spec.get("brief", f"Sample brief for the {spec['visual']} post. {spec['line']}"),
            why="Sample: shows how this kind of post looks before a real edition uses it.",
            est_seconds=visual_seconds(spec["visual"], slides), cited_item_ids=[iid]))
    for k, line in enumerate(ALSO, start=1):
        cid = f"sample-also{k}"
        session.add(Cluster(id=cid, window_start=now, topics=["solutions"]))
        session.flush()
        session.add(AlsoHappened(edition_id=ed.id, cluster_id=cid, rank=k, line=line,
                                 cut_reason="budget" if k == 2 else None))
    session.flush()
    return ed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="out/sample", help="output directory (default out/sample)")
    args = ap.parse_args(argv)
    engine = get_engine("sqlite://")
    try:
        init_db(engine)
        with session_scope(engine) as session:
            ed = seed(session)
            cfg = load_edition_config(ROOT / "config" / "edition.yaml")
            page = render_edition(session, ed, Path(args.out), cfg=cfg)
    finally:
        engine.dispose()
    print(page)
    return 0


if __name__ == "__main__":
    sys.exit(main())
