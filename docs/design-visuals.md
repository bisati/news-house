# News House: visuals that say something

Status: spec, 2026-11-06. Owner: Mihir. Extends `docs/design-v2.md` sections 3.4 (visual catalogue) and 3.3 (post anatomy). Builds on the colour ladder (design-v2 3.6) and the photo fallback, both merged with this spec.

## 1. Why

In the first five editions (30 Oct to 6 Nov, 132 posts), about two-thirds of posts got a cover: a big number or two big words. Mihir: "just reading those big words does not do anything for the reader to understand what it actually is in the news." When we dropped the automatic cover, 13 of 29 posts on 5 Nov had no visual at all, which is worse. He wants most posts to have a visual again, but one that carries the story.

The stories repeat in a small number of shapes every day: launches, rules with dates, deals, injuries, matches, bug reports, court cases, numbers that only mean something next to another number. Each shape has a natural picture. This spec adds those pictures to the catalogue and makes the writer pick the one that fits.

Mihir also found that a visual above the headline sometimes makes no sense until you have read the headline (his example: the 5 Nov Form 6 versus card). So the order of headline and visual now depends on the visual.

## 2. Goals

- G1. Most posts carry a visual that tells the reader something the headline alone does not: target 80% or more of posts in an edition, counted by the validator.
- G2. Each visual is honest: every name, number and date in it appears in a cited item, as today.
- G3. Each format fits a post at phone width: at most 320px tall at 390px wide, like every visual today.
- G4. The headline leads when the visual explains it; the visual leads when it is a hook that stands on its own.

## 3. Non-goals and anti-goals

- Not maps, live trackers, video or model-drawn illustrations (design-v2 non-goals stand).
- Anti-goal: a format that becomes the new two-word cover, chosen for everything because it is easy. The validator warns when one format fills more than a third of an edition, and Key facts has its own cap (section 6).
- Anti-goal: invented structure. A Fact sheet with a guessed price, a Deal card with a made-up status, or a reliability label the sources do not support is worse than no visual. When a field is not in the sources, it is left out, or the writer picks a simpler format.
- No change to colours: every format draws from the post's world (label, ink, accent, panel, hi), so the ladder in design-v2 3.6 still decides how loud a post is. Tomato stays for urgent news only. No format uses red for "bad".

## 4. The formats

Each format is a new `visual` name with its own payload, written by the writer and checked by the validator. String limits keep each one inside 320px. "Truth" says what must appear in cited items (numbers by value through `catalogue._numbers`, names and phrases as a case-insensitive substring of the cited items' text).

Common rendering rules: the format sits on the post's inner panel (`--panel`), like a table or chart today. Small labels use the world's `--label`; the values that matter use `--hi` (the family ink); marks use `--accent`. Status tags are quiet pills: ink outline, or filled ink for the one state that matters. No new colours.

### 4.1 Key facts (the new default)
For any story. It replaces the two-word cover as the fallback a writer reaches for.
- Payload: `{"facts": [{"label": str, "value": str}]}`, 2 to 4 facts. `label` at most 14 characters (Who, What, When, Where, How much, Status, Next, Affects). `value` at most 32 characters.
- Truth: every number in a value, and every proper name, appears in a cited item.
- Renders: a 2×2 grid (one column when there are 2 facts), label in small caps over the value in Fraunces 20px. A value of 20 characters or more drops to DM Sans 16px semibold.
- Example (5 Nov, Raphinha renewal): Who: Raphinha · What: contract renewal · When: Thursday · With: president Laporta.
- Order: headline first.

### 4.2 Number in context (replaces the post-level cover)
For a story carried by one number that only means something next to another.
- Payload: `{"value": str, "what": str, "compare": {"label": str, "value": str} | null}`. `value` at most 12 characters; `what` (what the number measures) at most 48; `compare.label` at most 24, `compare.value` at most 12.
- Truth: both numbers appear in cited items. If both parse as numbers in the same unit (the renderer strips currency and unit words and compares the remaining figures, and a `crore`/`lakh`/`billion`/`million` word must match), the card draws two bars to scale; otherwise it prints "vs <label> <value>" under the number.
- Renders: the number large (Fraunces 64px, the family ink), `what` under it, then the comparison.
- Examples: $592M · "Indian tech funding in October" · vs "12-month high" (when the source gives one). ₹143.63 cr · "PhysicsWallah Q2 profit" · vs "a year ago ₹69.71 cr". $465M raised · vs "H1 revenue $174K".
- `cover` stays in the catalogue for a deck's slide 1 and for a two- or three-word phrase that is itself the story ("Raphinha stays"); the writer should reach for Number in context first.
- Order: visual first.

### 4.3 What changes for you
For a rule, curb, order or policy with effects and dates.
- Payload: `{"rows": [{"what": str, "change": str}], "from": "YYYY-MM-DD" | null, "to": "YYYY-MM-DD" | null, "where": str}`. 2 or 3 rows; `what` at most 22, `change` at most 32, `where` at most 32 (tightened from 4 rows and 40 so the longest card fits 320px).
- Truth: dates and numbers appear in cited items; `where` appears in a cited item.
- Renders: rows of "what" (small caps) and "change" (semibold). Under them, when `from` or `to` is set, a date bar: start date left, end date right, a filled stretch for the period, and a dot for the edition date with "today". Only `from` gives "from 5 Nov" with no bar end; only `to` gives "until 20 Nov".
- Example (5 Nov, CAQM): Offices: at most 50% in person · Construction: dust-raising work stopped · Parking: higher fees · 5 Nov ━━●━━ 20 Nov · Delhi-NCR.
- Order: headline first.

### 4.4 Fact sheet
For a product, model or feature launch.
- Payload: `{"has": [str], "lacks": [str], "price": str | null, "status": "available" | "preview" | "beta" | "waitlist" | "limited" | null, "where": str | null}`. `has` 1 to 3, `lacks` 0 to 2, each at most 26 characters (tightened from 4 for the 320px limit); `price` at most 28; `where` at most 24 (US only, paid users).
- Truth: each item in `has` and `lacks` is supported by a cited item (the validator checks only numbers and the price; the prompt carries the rest). `lacks` only for what the source says is missing ("no public API", "not in India").
- Renders: ✓ rows for `has`, ✗ rows in muted for `lacks`, then a footer line with the status pill, `where` and `price`.
- Example (6 Nov, Grok phone calls): ✓ sits on hold ✓ books appointments ✓ negotiates bills · ✗ outside the US · paid users.
- Order: headline first.

### 4.5 Deal
For an acquisition, stake, merger, funding round or listing.
- Payload: `{"kind": "acquisition" | "stake" | "merger" | "funding" | "listing", "from": str, "to": str, "amount": str | null, "terms": str | null, "to_does": str, "status": "announced" | "closed" | "needs approval" | "reported" | null}`. `from` (buyer or investors) at most 28, `to` at most 28, `amount` at most 16, `terms` at most 32 ("all-stock", "at $21.5B valuation"), `to_does` at most 48.
- Truth: names, amount and terms appear in cited items; `status` only when a cited item says it.
- Renders: two name blocks joined by an arrow (buyer → target, investors → company), the amount on the arrow, `to_does` under the target, `terms` and the status pill below.
- Examples: OpenAI → Pierre · "developer tools behind Codex" · needs approval. NBCUniversal, MIT Investment → (unnamed) is not a Deal card: the target is not in the sources, so Key facts.
- Order: headline first.

Photos and these formats (Mihir, 2026-11-06): Availability, Scoreline, Stakes and Rumour win over the photo rows for injuries, results, previews and reported transfers when the sources fill them; a photo steps in when they cannot.

### 4.6 Availability
For a player out, doubtful, suspended or back.
- Payload: `{"player": str, "status": "out" | "doubt" | "suspended" | "back", "reason": str | null, "return": str | null, "fixtures": [{"vs": str, "date": str, "plays": "miss" | "doubt" | "play"}]}`. `player` at most 32, `reason` at most 24 ("right hamstring"), `return` at most 24 ("about 3 weeks"), up to 3 fixtures (`vs` at most 18, `date` at most 8; cut from 4 for the 320px limit).
- Truth: the player, reason, return and each fixture appear in cited items. A fixture's `plays` comes from the sources, never inferred from the return estimate.
- Renders: the player name with a status pill (OUT filled ink, DOUBT outlined, BACK on mint), reason and return under it, then a row of fixture chips each with a miss, doubt or play mark. A configured team's kit colours mark the chips' dots (design-v2 3.6).
- Example (5 Nov): Rodri · OUT · right hamstring · about 3 weeks · Atlético (miss).
- Order: headline first.

### 4.7 Scoreline and Stakes
For a result, and for a preview with something on the line.
- Scoreline payload: `{"home": str, "away": str, "score": [int, int], "competition": str, "scorers": [{"name": str, "minute": str, "side": "home" | "away"}], "note": str | null}`; teams at most 20 characters, up to 4 scorers of at most 18, `note` at most 48 ("first clean sheet since April 2025"). The score must be written as a score ("3-0") in a cited item.
- Stakes payload: `{"fixture": str, "when": str, "outcomes": [{"if": "win" | "draw" | "loss", "then": str}]}`; `fixture` at most 32, 2 or 3 distinct outcomes, `then` at most 36.
- Truth: teams, score, scorers and each outcome appear in cited items.
- Renders: Scoreline as the two teams either side of a large score, scorers in two columns under it. Stakes as the fixture and time, then one row per outcome.
- Examples: Barça 3–0 Aston Villa · Raphinha 2, Yamal. Atlético v Barça, Sunday: win → five points clear; loss → Atlético one point ahead.
- Order: Scoreline visual first; Stakes headline first.

### 4.8 Incident
For a developer bug report, outage or security report.
- Payload: `{"symptom": str, "affects": [str], "reports": int | null, "vendor": "confirmed" | "fixed" | "no reply" | "disputed" | null, "since": str | null, "workaround": str | null}`. `symptom` at most 60, `affects` up to 3 items of at most 28 (model names, versions), `workaround` at most 60.
- Truth: everything appears in cited items; `reports` is the count of distinct cited reports and must not exceed the number of cited items unless a cited item gives a count.
- Renders: the symptom, the affected chips, then a "how sure" line built from `reports` and `vendor`: "1 forum post · no vendor reply" reads as weak, "7 threads · vendor confirmed" as strong (wording only, no colour scale). Workaround last, when there is one.
- Example (3 Nov): "high demand" 503 errors · gemini-3.1-flash-lite, gemini-3.8-flash · 2 forum posts · status page shows operational.
- Order: headline first.

### 4.9 Countdown
For a deadline: a shutdown, deprecation, end of a scheme, a closing window.
- Payload: `{"date": "YYYY-MM-DD", "what": str, "do": str | null}`. `what` at most 48 (what ends or changes), `do` at most 60 (what to do, only when the source says).
- Truth: the date and `what` appear in cited items.
- Renders: "N days" large (computed from the edition date at render time; "today" at 0; a date in the past is a validator problem), the date, `what`, then `do`.
- Example (5 Nov): 25 days · 1 Dec · gemini-2.5-flash calls move to 3.5-flash-lite · re-test on real recordings.
- Order: visual first.

### 4.10 Case
For a court case, petition or formal dispute that moves in steps.
- Payload: `{"court": str, "asked": str, "steps": [{"label": str, "date": str | null, "done": bool}], "next": str | null}`. `court` at most 40, `asked` at most 64; 3 or 4 steps, `label` at most 16, `date` at most 12; `next` at most 32 (the next hearing). Cut from 5 steps of 24 and an ask of 80 for the 320px limit.
- Truth: court, dates and each step appear in cited items. Steps are what the sources describe (filed, notice issued, hearing, referred to a larger bench, ruling), not a generic court process.
- Renders: the court and what was asked, then a horizontal stepper with done steps filled in the accent and the rest hollow, then "Next: <next>".
- Order: headline first.

### 4.11 Scale
For a story about a level on a known scale. Two scales only, defined in code with their bands: GRAP stages I to IV, and CPCB AQI bands (good, satisfactory, moderate, poor, very poor, severe).
- Payload: `{"scale": "grap" | "aqi", "level": int, "previous": int | null, "value": int | null}`. For GRAP `level` is the stage index (0 for Stage I to 3 for Stage IV; "Stage II", "GRAP II" and "GRAP 2" all name it); for AQI it is the band index (0 to 5) and `value` the reading, and the page takes the band from the reading. `previous` must be named in a source (an earlier stage, or an earlier reading written near "AQI").
- Truth: the stage or reading appears in a cited item.
- Renders: the scale's steps in a row, the current step filled in the accent with its name, the previous step marked "was". This is the one place a poor or worse AQI band may show in tomato, as the live tile does (design-v2 3.6: alarming status values).
- Order: headline first.

### 4.12 Rumour
For a transfer or signing that is reported, not done.
- Payload: `{"player": str, "from": str, "to": str, "fee": str | null, "source": str, "tier": "official" | "reporter" | "report"}`. `fee` at most 20.
- Truth: player, clubs, fee and source appear in cited items. `tier` follows the source: `official` for a club statement, `reporter` for a named journalist the item quotes, `report` for everything else. The writer never upgrades a tier.
- Renders: player, from → to, the fee, and "Per <source>" with a tier word (Official / Reported by a named journalist / Reported).
- Order: headline first.

### 4.13 Steps
For a how-to or engineering post whose point is a method.
- Payload: `{"steps": [str]}`, exactly 3 steps of at most 60 characters each.
- Truth: each step is supported by a cited item (prompt-checked).
- Renders: three numbered rows, the numbers in the accent.
- A post whose point is a speed-up or a cut keeps using `chart` (with its key point) or `before-after`.
- Order: headline first.

## 5. Headline first or visual first

The order is set by the visual, in code, never by the writer:

| Visual first (a hook that stands alone) | Headline first (the visual explains the headline) |
|---|---|
| photo, number, cover, quote, scoreline, countdown, a slide deck | key-facts, changes, factsheet, deal, availability, stakes, incident, case, scale, rumour, steps, chart, table, timeline, versus, before-after, pitch |

A headline-first post shows: header row, headline, the visual, the gist, the why line, the footer. A visual-first post keeps today's order. A stack's chip and the why line keep their place under the gist in both. Expanded posts keep the expanded layout in design-v2 3.7 (the visual or deck at the top).

## 6. How the writer chooses

The writer prompt gets one short table of story shape → format (section 4's "For" lines), and these rules:
- Pick the most specific format whose every required field the cited items fill. If a field would need a guess, drop to a simpler format: a specific format, then Number in context or Key facts, then `none`.
- Key facts is the fallback, not the first choice. The validator warns (`format-mix`) when Key facts fills more than a third of an edition's posts, or any one format more than a third.
- A deck (slides) can use the new formats as slides only after phase C; until then slides keep their current kinds.

Allowed visuals per story (extends `write.allowed_visuals`): Key facts, Number in context, cover, quote and `none` are always allowed (a teaser can fill them). Countdown and Deal are allowed whenever a cited item has text the payload can be checked against, teaser included; Availability, Scoreline, Stakes and Rumour too, for a football story. Fact sheet, What changes, Incident, Case, Steps and the existing rich visuals need a body (today's `_unlocks_rich`); Scale needs a body and the GRAP or AQI words in a cited item. Pitch needs a football topic and a body. A format slide is allowed only when its kind is an allowed visual for the story; it has an empty body, and on a slide Key facts holds at most 3 facts, Fact sheet 2 ticks and 1 cross, and a Deal's `to_does` 32 characters.

The longest legal payloads are kept inside 320px by these limits and by CSS line clamps on the longest fields (real text is shorter); worst-case cards in `scripts/sample_edition.py` prove it at four widths in light and dark.

Photos by story shape (Mihir, 2026-11-06): a story about a person (a death, an appointment or exit, a signing or transfer, an injury, a profile), a disaster, accident or attack, or an event (a match, race, ceremony, protest, rally, summit) gets the source's photo when a cited item has one, ahead of any fact format. Launches, rules and numbers keep their fact format and never take a photo. On the 6 Nov test, 27 of 29 posts had a usable publisher image but the writer picked a photo once, because the shape table had no photo row and a post has one visual slot; this rule gives photos their own rows.

When the writer still picks `none`, the photo fallback applies (a cited item's publisher image). The renderer never builds a visual on its own beyond that.

## 7. Validation

Each format's checks live in `catalogue.payload_problems`, with the same consequence as today: a failing payload costs the post its visual, never its text (one retry, then `none`). New edition-level warnings in `validate.py`:
- `visual-share`: fewer than 80% of posts have a visual (photo counts).
- `format-mix`: one format, or Key facts, above a third of the edition's posts (photos are not counted: they follow the story's shape and the photo fallback).
- `countdown-past`: a countdown date before the edition date.

## 8. Phases

Each phase ends with a test page from that day's paper, rewritten on a copy of the prod database (never published, never touching Neon), plus the shot checks at the four widths in light and dark.

- Phase A: the order rule (section 5), Key facts, Number in context, What changes for you, Fact sheet, the prompt table, `visual-share` and `format-mix`. These four cover most stories in the first five editions.
- Phase B: Deal, Availability, Scoreline and Stakes, Incident, Countdown.
- Phase C: Case, Scale, Rumour, Steps, and the new formats as slide kinds (Key facts, Number in context, Fact sheet, Deal and Steps; a slide's title is at most 4 words, and every number on it must be in the brief).

## 9. Rules for the builder (from the builder check, my calls)

1. **Key facts truth.** Numbers are checked by value, as everywhere. Every capitalised word of three letters or more in a value (a proper name: Raphinha, Laporta, CAQM) must appear in a cited item, case-insensitive; lowercase phrases ("contract renewal") are prompt-checked. The label list in 4.1 is examples, not an enum ("With" is fine); labels are free text of at most 14 characters.
2. **Dates.** A `YYYY-MM-DD` field passes when one cited item contains its day number and its month (name or three-letter abbreviation) in any order ("5 Nov", "November 5", "5 to 20 November" covers both 5 and 20). The year is the edition's year, or the next year when the month is more than six months before the edition month. A relative word ("Thursday") cannot fill a date field: the writer leaves the field null or picks a simpler format. `countdown-past` compares against the edition date.
3. **Colour ladder.** Number in context and cover are step 3 like the cover today: the family tint when the post has no deck, counted as tinted for the "never two tinted in a row" rule, the number on the inner panel. Every other new format is a step 4 white post with the format on the inner panel. Forest, breaking and mint win over both, as now.
4. **Order everywhere.** Section 5's order applies to every post, the lead included, collapsed and expanded alike (the expanded extras, brief and sources, come after the gist as now). It changes for all posts at once in phase A, existing visuals included.
5. **Counting visuals.** `visual-share` counts a post as having a visual when it has a deck, a visual other than `none`, or a `none` visual with a cited item whose image the page would show (the same `photo_eligible` and https rule as the photo fallback). Nothing new is stored.
6. **Cover cap.** Cover and Number in context count as one family for `format-mix` (together at most a third of the edition). The old "one in four" prompt line goes. Stored cards keep rendering as now: a cover with `big` renders as a cover, an empty one as the photo fallback or nothing.
7. **Bar mode for Number in context** is decided in `present.py` at render; the validator checks only truth. Both values parse to a currency (or none), a figure and a scale word or suffix (K, thousand, lakh, M, mn, million, crore, cr, B, bn, billion), normalised to an absolute figure. Bars draw only when the currencies match and both parse; otherwise the "vs" line. $465M against $174K draws two bars; ₹143.63 cr against $10M does not.
8. **Enums are code-checked** for allowed values (Deal `status`, Rumour `tier`, Fact sheet `status`, Availability `status`, fixture `plays`). Whether the value is true to the sources is prompt-checked, except that `status`/`tier` words the validator can see in the text ("approval", "official") are not required.
9. **Retries** stay as today: one retry per post carrying the specific problem lines, then `none` (and then the photo fallback).

## 10. Calls made in this spec (for Mihir to check)

- Key facts as the default fallback, not a renderer-built cover.
- The order is set per format in code, not chosen by the writer.
- The cover stays only for deck slides and short phrases; Number in context replaces it on posts.
- No new colours; statuses are quiet pills (BACK on mint, since it is good news).
- Phase A's four formats first, by how many stories they fit.
