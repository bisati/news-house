# First real edition: run notes

Run date: 2026-10-30, started 15:53 IST, finished 17:16 IST (about 83 minutes wall clock, `exit 0`). Staging clone on `build/plan-a` (HEAD `adbed28` plus the debug wrapper), existing `newshouse.db`, real Claude Code calls on the Max subscription. Launched with `scripts/tick_debug.py` (DEBUG log in `out/tick-debug.log`).

## Outputs

- `out/2026-10-30.html`
- `out/latest.html` (same file)
- `out/2026-10-30.json`

(`out/` is gitignored.)

## Numbers

| Item | Value |
|---|---|
| Wall clock | about 83 min (ingest 2m18s; the rest is clustering/classify/write model calls) |
| Ingest | 228 tried, 206 ok, 22 failed; 808 new items, 9,735 duplicates, 616 stale |
| Sync | 258 sources |
| Tick-level embed / cluster / classify / threads | 192 / 1,609 / 1,608 / 1,608 |
| Build stage seconds | profile 0.0, embed 0.2, cluster 181.1, classify 5.1, threads 0.0, select 0.5, enrich 21.9, write 382.1, also 0.0 |
| Cards | 23 (budget 900 s, est. 14 min, cut score 60.0) |
| Format mix | A 17, C 3, D 1, E 1, F 1 (no B) |
| Unverified | 0 (`cards_fallback` 0) |
| Breaking | 0 |
| "Also happened" lines | 25 |
| Cards with non-empty `why` | 20 of 23 (E has none; two more empty) |
| Claude Code calls | 447 total (the log line does not carry the model) |
| Calls, inferred by size/timing | about 37 large (80 to 90K cached input, up to 14K output, about 60 s each, 15:57 to 16:40); about 386 small (about 3K input, 1 to 5 s each, 16:40 to 17:15); 24 in the final window of which 22 were over $0.05 (the card writes, Opus) |
| List-price cost estimate (summed `total_cost_usd`) | $3.18 (about $1.98 from the 22 big write calls, $1.21 from the other 425); actual cost under the subscription is zero |

Calls were far above the expected "10 to 15 classify, 20 to 25 write, a handful of thread/same-event": about 420 non-write calls, because this run was against a database with 1,609 clusters needing classification and same-event confirmation (first run, 13.5K stale items, backlog). Expect a normal day to be much lower; check the second and third unattended days. Two things to look at: the ~37 big early calls carry roughly 90K tokens each (which stage they belong to is not logged), and the log has no model field, so adding the model name to the `newshouse.llm` DEBUG line would make this split exact.

The `build` Run row's own stats show `clusters_new 0`, `clusters_scored 1`, because the tick had already clustered and classified before `build_edition` repeated those stages (idempotent). The big cluster/classify work is therefore not in the build row; it is in the tick output above.

## Failed sources (from `sources_failed`)

- `reddit: no credentials` (21 of the 22): AI_Agents, Barca, ClaudeAI, Cricket, FootballTactics, IndianFootball, IndianStartups, LocalLLaMA, MachineLearning, ProductManagement, StartUpIndia, bollywood, formula1, gurgaon, movies, soccer, tennis, and Btechtards/developersIndia search feeds (4). Expected, not fixed.
- `http 520` (1): `https://barcauniversal.com/feed/` (upstream error; likely transient, retry on the next tick or the Sunday health check).

Note: the brief expected 22 Reddit failures; the actual split is 21 Reddit plus 1 HTTP 520 (22 failed in total).

## Warnings

- One write warning: `headline is 91 characters; maximum is 90` for cluster `adb0a82b9cce9058`. Validation rejected the 91-character headline; the retry returned a valid 76-character headline ("Gemini 4 Carbon tops Artificial Analysis index at 59, access limited for now"), which is what was stored. The card is verified (`unverified = 0`), not a fallback.

## What the page looked like

Opened `out/latest.html` and took a 500 px wide headless screenshot. It renders as a dark card stack ("News House · 2026-10-30", "23 stories · 14 min") with a topic chip, source count, headline, depth dial (1 line / para / brief / sources), an amber "Why it matters to you" block and Worth it / Skip / Later buttons; the format D card shows a dated chapter timeline with a NEW tag. Things that looked wrong: on the first card (format C bar chart) the x-axis labels overlap each other and are cut off ("nch Pro (finding vulnerabilities)" running into "CWE-Bench (patching)"), and the chart title is clipped on the right. The first four cards include two on the same Delhi GRAP story (an A card and a D chapter card whose headline says curbs removed): worth checking whether that is intended thread behaviour. The "Also happened" list includes one odd line, "Mixed 100-item catch-all; visible items are government releases...", which looks like a catch-all cluster that should not be summarised as an event. Nothing was redesigned.

## Mihir's read

- Worth it:
- Shouldn't be there:
- Should have been in (from "Also happened"):
- Facts wrong against sources:

## v2 phase 1: what differs from the mockup and why

Re-rendered on 2026-11-03 from the real `newshouse.db`, with no model call: `newshouse init-db` (adds the v2 columns with their defaults), then `newshouse render --date 2026-10-30 --validate --out out`, then `out/2026-10-30.html` copied to `out/latest.html`. The validator, in report mode, stored 14 warnings: 12 `headline-long` (13 to 17 words against a 12-word limit; v1 allowed 90 characters), 1 `gist-long` (46 words against 40), 1 `thread-home` (the GRAP thread has two cards in this edition). `scripts/shot.py out/2026-10-30.html out/shots` passed at all four sizes (no overflow, smallest text 11px, no empty visual, tallest post 1.32 screens at 390x844). No CSS or template change was needed.

Compared against the approved mockup boards (Main, Expanded, Done).

Expected, because they belong to phases 2 and 3:

- No slides or carousel: the Alphabet story is a big-type cover, not the mockup's four slides (-13%, the miss, the damage, what next).
- No pitch graphic: the Koundé story is a two-word cover ("Koundé out"), not the predicted back four.
- No photos.
- No live tiles under the masthead (Gurgaon AQI now, next Barça match).
- No tune-tomorrow chips on the end card.
- The "why it matters to you" line still shows on most cards; this edition was written under the v1 prompt. The mockup has none.

Also seen, worth a line each:

- Cover big type picks poor figures from v1 headlines. "14" from "14.4s to 1.2s" (the number regex stops at the decimal point before a unit letter), "43" from "Sector 43", "23" from "since May 23", "2029" from a contract year. With no figure it falls back to the headline's first two words, which gives "Helicopter with", "The Athletic", "Delhi announces", "Zverev beats". The mockup's covers carry a chosen figure with a label ("-13%", "$500B wiped off its value in one day"). Phase 2's writer should supply `big` and `label` itself; this is Python logic (`present.cover_big`), so it was left alone.
- Topic line: the mockup reads "AI · Google · 6 sources" and "Football · Barça · 7 sources" (topic, then subject). The page shows only the topic ("AI tooling · 6 sources"), because there is no subject field yet.
- Lead chart: the mockup has a chart title ("Carbon's security scores, per Google") and short row labels ("Patching"). The page shows the v1 payload: no title, a bare "%" unit header, and long labels that wrap to three lines on the phone ("SEC-bench Pro (finding vulnerabilities)").
- GRAP timeline: the mockup labels the chapters "Today · Stage IV lifted" and "Yesterday · new vehicle curbs". The page shows "Today" and "30 Oct", and the earlier chapter is itself a card in this same edition (the `thread-home` warning). Selection v2 prevents this on new builds.
- Versus: the mockup has named sides ("Sell · Sitharaman", "Keep · Rahul Gandhi") with one short paragraph each. The page shows "For" and "Against" columns with long, attributed bullets from the v1 payload. It reads, but it is about twice as tall.
- Also today: the mockup lines open with a bold name ("**Mistral** released open weights..."). The page lines are the classifier's reasons, written about the reader in the third person ("...not in the reader's Gemini stack, so it is worth knowing rather than acting on"). The also-happened line comes from `cluster.reason`; phase 2 should give it a plain fact line.
- Progress line: the mockup says "23 of 23 read"; the page says "seen" and counts posts scrolled past. Correct for phase 1 (read is a separate event); just worded differently.
- The end card lists the 14 validator warnings in small type beneath "Next edition". That is by design for now and not in the mockup.
- At 768 and 1280 wide the page stays a single phone-width column, centred. Same as the mockup, which only drew the phone.
- Fraunces's 4 at display size looks odd in "43" and "14": the flag of the 4 rises above the cap height. That is the typeface, not a rendering fault.

Screenshot note: the count-up animation on cover figures starts at 0 on the first frame. A headless screenshot taken without the shot.py wrapper (window 500x9000, all posts on screen at once) caught it mid-run and showed "$0 billion" and "0%". With `--force-prefers-reduced-motion`, or through shot.py, the real figures show. In a real browser the animation completes in 0.7 s.

For phase 2: the edition JSON's per-card `visual` field reads `"cover"` for all 23 cards (the column default), while the page shows the mapped visual (charts, a timeline, a before-after, a versus, covers). The writer does not fill the column until phase 2. Anything reading the JSON should use the format until then.

## v2 phase 2: what differs from the spec and why

Phase 2 added the visual catalogue (cover, chart, table, timeline, versus, before-after, pitch, photo, quote), two-to-four-slide decks and a tone per post. Where the spec was silent, unclear or in conflict with a project rule, a ruling was made. Mihir can overturn any of them.

Made in the plan:

1. The writer's reply names a `visual` instead of a `format`. The format is still stored, worked out from the visual (chart is C, table B, timeline D, versus E, before-after F, everything else A), so v1 code and the 30 October edition keep working. An old-style reply with only a format is mapped the same way and is not an error.
2. A bad visual never costs a story its text. If the text passes but the visual or slides still fail after one retry, the post keeps its text, gets no visual (an automatic cover until 2026-11-05) and no slides, and the edition gets a `payload-fallback` warning. The v1 teaser fallback is now only for a reply whose text fails.
3. Photo posts carry no text on the image. The spec's table says the kicker sits on the photo; its rules say kicker and headline stay below it. The rules win: only a small credit sits on the image, bottom right.
4. Pitch rows run from the back line forward and are drawn bottom to top, so the goalkeeper sits nearest the bottom edge.
5. Truth checks on the new visuals: a cover's big text is at most 14 characters and any number in it must appear in a cited item; a quote must appear word for word in its item (case, spacing and quote marks ignored); every name on a pitch must appear in a cited item; a photo's item must be cited and must have an image.
6. A what-next slide holds at most 60 words. The spec says "two short paragraphs" without a number.
7. Expanding a post fades and lifts the extra content slightly instead of growing its height. The spec asks for height growth, but the project rule allows only transform and opacity motion. The chevron rotates.
8. A headline over 12 words no longer asks the model for a rewrite. It is a soft rule and each retry is an Opus call, so it stays a warning only.
9. When the classifier's tone and the writer's tone differ, the run log records both, without asking the writer why. The reason would cost tokens and the reader would never see it.
10. Card ids are fixed per edition and story, so a reaction survives `build --force`.

Made while building it:

- Inside a deck, the cover slide keeps the 14-character limit but its numbers are checked against the brief, not against the cited items. Spec 3.5 says every number on a slide must appear in the brief, and the plan's own test expected this. The brief's own numbers are held to the writer prompt's first rule.
- A reply with no tone at all is fine (the post takes the story's tone from classify, which may be empty). Only a tone outside good, bad, mixed and neutral counts as a problem. Old replies and the test fakes have no tone.
- The slide dots animate by stretching sideways (a transform), not by changing width, for the same transform-and-opacity rule.
- An expanded deck post shows only its cover slide and the full brief, not its table or chart slides. Every number on a slide must already be in the brief, so no fact is lost; only the table's layout is.
- A table slide holds at most 4 rows and a chart slide at most 6 bars, so a 320px slide never cuts content off silently. A reply over the cap gets a retry, then no visual.
- Deck arrow keys are ignored while Alt, Cmd or Ctrl is held, and the slide counter is announced politely to screen readers (two review suggestions carried into the slide-controls work).
- The chevron's open-state rotation applies even with reduced motion on, so the open state still shows; only its transition sits inside the motion block.

Made in the sample-edition task (layout, smallest change each):

- When a photo fails to load, its credit is hidden with it. Before, the credit sat on top of the fallback cover's text.
- The pitch is 216px tall instead of 200px, so four rows of players no longer touch, and a player's name may use a quarter of the row instead of a fifth, so "Lewandowski" is no longer cut to "Lewandow...". The out-of-squad chips stay on one line: names always show, reasons shorten with an ellipsis. The worst case (four rows, three out, a one-line note) measures 298px, under the 320px limit for a visual at phone width (spec 3.3).
- The pitch sits on the post's inner panel (sand on a white post). Player names sit on the panel colour, so the centre circle never runs through a name.
- Cover big text keeps a word gap ("8 to 3" no longer reads "8to3"): the tight display letter-spacing had closed it.

`scripts/sample_edition.py` renders one post of every kind plus a four-slide and a two-slide deck with no model call; `scripts/shot.py` now also fails on a deck outside two to four slides, a slide whose content overflows it, a visible photo that did not load, and (at 430px wide or less) a visual or deck taller than 320px. On 3 November 2026 the sample passed at 390x844, 430x932, 768x1024 and 1280x800.

## v2 phase 3: what differs from the spec and why

Phase 3 added the clearer carousel, a rewritten "Also today", live tiles, "Tune tomorrow" chips, the lessons ledger and the night palette. Mihir's feedback on the first phase 2 edition (2026-11-03) wins where it differs from `docs/design-v2.md`. Mihir can overturn any ruling below.

Made in the plan (`docs/plan-d.md`):

1. "Also today" holds at most 2 lines per primary topic (`also.per_topic`) and no line for a story whose thread already has a printed card or an earlier line. A non-top story over the cap is left out so other topics fill the 25 slots; a top story over the cap is kept as a folded row with its cut reason, shown as one line per topic that expands. Matching duplicates by embedding similarity was measured and rejected: two different Barca stories scored 0.84, higher than the median pair of duplicate pollution reports (0.77).
2. Carousel dots and the `n / N` counter sit directly under the slides; the boxed previous and next buttons are replaced by box-less chevrons on the slide (44px tap area, 18px glyph at 55% opacity), each shown only on the side with another slide. Arrows and swipe stay. In an expanded post the chevrons and dots hide.
3. Post photos load eagerly (no `loading="lazy"`), so the broken-image check at page start works in iOS Safari. An edition has one to three photos.
4. `newshouse render` refreshes `out/latest.html` when it renders the newest built edition.
5. Air quality is India's CPCB AQI computed from Open-Meteo's PM2.5 and PM10, because Open-Meteo gives only US and European AQI. It is an estimate and says so.
6. The fixture tile uses ESPN's public team schedule (`site.api.espn.com`, Barcelona is team 83). Both sources need no key and allow cross-origin reads, so the page can refresh them.
7. Tune chips come from a fixed rule (less of the biggest topic, more of the two topics with the best-scored cut stories, shorter or longer edition). A tap counts for the next built edition only: a topic weight moves by 0.3 (clamped to -1 to 1), the budget by 120 seconds.
8. Lesson stubs from "Should have been in" taps are made at the next build, never by the page server, so the server writes no repo files. Stubs are idempotent by feedback id.
9. The night palette follows the system setting, with a `?theme=dark` or `?theme=light` override (used by `shot.py --theme`). Since 2026-11-05 every post carries its own night values, so mint and tinted posts get night fills too; dark muted text is `#9DB5A6`.
10. Not in this phase: spec 3.10's motion list is already met. Selection budgeting with the old reading times stays, because the visual is unknown at selection time. The clustering stage's failure to merge 25 reports of one event is a phase 4 item; this phase fixes what the reader sees.

Rulings made by the controller while building it:

- The AQI tile uses the 24-hour mean of Open-Meteo's hourly PM values (CPCB defines PM sub-indices on 24-hour averages) and says "24-h avg · model estimate". The reviewer measured 302 (24-h) against 301 (current hour) and an official 246, so the gap is the model source. If this is wrong the tile still reads about one band above the official CPCB figure; switching to a station source is a later decision.
- Also rows rank unfolded lines (in score order) before folded rows, and the tune "More" chips read that order, so folded top rows (already a capped topic) come last. A "More" chip for a flooded topic would be wrong anyway. Cost if wrong: none.
- A tune tap is validated strictly even when it carries an id (the implementer's reading; one test each in `test_serve` and `test_feedback` changed). Cost if wrong: none, the page never sends ids with tune.
- "This edition's window" for the owed check is the selection window (`cluster_window_hours` before the edition's reference time), the window the edition actually considered. Cost if wrong: an owed story scored just outside the window gives no warning.
- The folded-row label follows the most common cut reason of the group ("cut as duplicates", "cut by the topic cap", else "cut: <reason>") rather than the plan's example wording. On the 3 November data this gave 25 lines across 13 topics, one pollution line, and "+7 more Gurgaon stories cut as duplicates".
- Duplicate tune taps do not stack: the last tap wins per topic and for the budget.

Known and left for later: the tile label reads "Gurgaon air now" though the value is a 24-hour average (consider "Gurgaon air, last 24 h"); a forced same-day rebuild applies taps meant for tomorrow; live tile refresh and the fold toggle are not browser-tested.

## Hosting: what differs and why

Mihir's choices on 2026-11-03: no privacy protection, a `site` branch deployed by Vercel, Neon for feedback only. Rulings made in the plan (`docs/plan-e.md`):

1. No access control, by Mihir's choice. The public feedback endpoint accepts only small, well-formed bodies (at most 4 KB, a known action, short string ids, a payload object). The Mac's sync rejects anything `record_feedback` rejects or that names a card or cluster it does not have. A junk row costs one inbox row and is dropped at sync.
2. Vercel deploys the `site` branch, not `main`. This deviates from D-007 ("Vercel deploys from main"). It keeps daily rendered pages out of `main`'s history. The branch is an orphan whose history is one commit per publish.
3. The page keeps posting to `/feedback`. `vercel.json` rewrites it to `/api/feedback`, so the same page works with `newshouse serve` and on Vercel. `/` redirects to `/latest.html`; the archive stays at `/index.html`.
4. Sync is idempotent. The inbox row id becomes the `Feedback.id`, so a row synced twice is recorded once. Synced rows stay in Neon (marked `synced_at`) for 30 days, then the sync deletes them.
5. Publishing never fails a build. A missing remote, a push failure or a missing Neon URL logs a warning in the tick's stats; the local page is unaffected.

Rulings made by the controller while building it:

- The tick records the feedback sync as `out["feedback_sync"]`, because `out["sync"]` already holds the sources sync. Cost if wrong: none.
- The inbox table is created by `newshouse inbox-init`, run once at go-live, not by the function (which only inserts).
- The tick commits after every stage, so a failed sync or publish cannot roll back earlier stages.
- A poison inbox row (any exception while recording) is dropped and counted, never allowed to block the rest of the sync.
- Git for publish runs with a timeout, no terminal prompts and a scrubbed environment, and only tracked files of the `site/` bundle are copied (symlinks skipped). Push credentials for the launchd tick come from the global github.com credential helper `gh auth git-credential` (the GitHub CLI), not the macOS keychain; verify at the first live publish.

Known and left for later: the live Postgres smoke test and the `/(.*)\.html` cache header are checked at go-live; a half-built publish worktree needs manual removal; HEAD on the function gets a body and no `Allow` header; CLI connection errors to Neon show a traceback.

Not done until go-live: the Neon project, the Vercel import and the first publish (plan `docs/plan-e.md`, Task 4). Every publish is outward-facing and needs Mihir's go.

## Phase 4 (2026-11-04): what differs and why

Mihir's notes on the 4 November edition (too much Gurgaon, nothing on startups or product, five posts for one story, unreadable tables, a "should have" button that seemed dead, up to 36 posts, a market tile). Rulings made in the plan (`docs/plan-f.md`) and amended during the build:

1. Stacks are grouped by one Haiku call, not embeddings (plan-d measured 0.84 for two different Barca stories against 0.77 for duplicate pollution reports). Same event or a direct follow-up only; at most 6 members, one primary topic; bad groups dropped, a failed call means no stacks. A stack is one post: it counts once against the topic cap and card cap, and its reading time is the lead's plus 10 seconds per member.
2. Breaking cards now count toward topic caps. Amendment: because the validator counts every card, breaking cards also reduce the card cap and the floor at build time. The breaking lane skips a story that is the same as a breaking card already written today, and classify's breaking case 2 is a GRAP stage change or a major closure, not each AQI reading.
3. New slugs `startups` and `ai-tools`; `product-design` is labelled "Product" and widened to PM craft, careers and product news. Floors and caps: gurgaon-local 0-2, product-design 2-4, startups 1-4, ai-tools 1-4, edtech-competitors 1-3, cards cap 36, budget 1200 s. New sources were added from a verified research pass. Note: the 1200 s budget fits about 34 average cards, so 36 is reachable only with stacks or shorter cards; a quiet day still stays short.
4. Visuals: table values over 28 characters are rejected (fallback to the cover) and 17 to 28 characters render in the 17px sans face. Amendment: the limit applies to table values only; versus and before-after are small body text. The writer prompt carries the Vertex ids and CBSE sentences as paraphrased "don't" cases.
5. "Should have been in" shows "Noted ✓", is disabled after a tap and stays so after a reload (`localStorage`, by cluster id).
6. Market tile: Nifty 50 from NSE's allIndices at build time and refreshed by each later tick (re-render and publish when the numbers change), "as of HH:MM IST", and a Trend toggle with the 1-week, 1-month and 1-year change. Amendments at go-live (2026-11-05): Yahoo answered 429 to the Mac and 502 through Vercel, so the source moved to NSE, the Vercel refresh function was dropped, Sensex was dropped (BSE refuses scripts), and the 1-month sparkline became the Trend row (NSE gives no daily closes). A rise is shown in the page ink, not forest green, which disappears in the dark theme; a fall is tomato (tomato-ink, #B23A1C, on the light page since 2026-11-05).
7. The profile is edited, not replaced (Gurgaon narrowed to same-day disruptions; startups, new technology, AI tools and PM craft added); `profile.md` is gitignored, so the edit is applied by hand to both clones and in neutral form to `profile.example.md`.

8. Final review fixes: the validator's minutes band is 12 to 24 (the edition is about 20 minutes, up to 36 posts; the old 12 to 18 warned on every busy day). Members of a cut stack lead become normal "Also today" candidates with the lead's cut reason, so they are explained and raise no false owed-lesson warning. At most `MAX_STACKS` (10) stacks per build get an Opus line call, best lead first; the rest get headline-only rows, and a stack that fails falls back to headline-only rows rather than failing the build. The breaking lane writes no card once today's edition has `cards_cap` (36) cards and reads the budget from `config/edition.yaml` (the 900 s settings default is gone); `cap_reached` is now set only when a cap stopped a candidate. A breaking card's own thread is claimed, so no regular card or Also line repeats it. Stack "Read at" links go through `safe_url` and read "Read the article" when the member has no source name.

Open at go-live: whether Yahoo answers requests from Vercel's servers (if not, the function is dropped and the tile updates only with each publish).
