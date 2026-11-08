# Running News House

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

Secrets live only in `~/.config/news-house/*.env` (mode 600), never in the repo. See `.env.example` for the variable names. Copy `profile.example.md` to `profile.md` and edit it (it is gitignored).

```bash
newshouse init-db
newshouse sync-sources
newshouse tick
```

## Reddit

Reddit returns 429 to anonymous feed polling, so the 22 Reddit sources use the official OAuth API (a "script" app). One-time setup:

1. Log in to Reddit, open https://www.reddit.com/prefs/apps, click "create another app...".
2. Name `news-house`, type **script**, redirect URI `http://localhost:8080`, create.
3. Copy the client id (the string under the app name) and the secret into `~/.config/news-house/reddit.env` as `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, plus `REDDIT_USERNAME` and `REDDIT_PASSWORD` (no 2FA) or `REDDIT_REFRESH_TOKEN` (2FA, obtained with `python scripts/reddit_auth_once.py`), and `REDDIT_USER_AGENT="macos:news-house:0.1 (by /u/<username>)"`. Then `chmod 600` the file.

Without credentials, Reddit sources fail with `reddit: no credentials` and the rest of the run continues.

## Running on the Mac

A launchd agent runs `newshouse tick` every two hours from a separate production clone at `~/mihir_ai/news-house-prod`, always on `main` from GitHub. The development clone is never touched by the scheduler. launchd's two-hour clock stops while the Mac sleeps, so a second agent checks every 10 awake minutes and starts a tick when one is owed: two hours since the last, or none yet since 06:00 IST. Each tick runs under `caffeinate -i`, so an idle Mac does not sleep mid-build; a closed lid still sleeps it.

```
bash scripts/install_launchd.sh     # clones main if needed, builds the venv, installs the agent
bash scripts/uninstall_launchd.sh   # removes the agents
```

Where to look:

- Log: `~/Library/Logs/news-house/tick.log`
- Latest edition: `~/mihir_ai/news-house-prod/out/latest.html`
- Agent state: `launchctl print gui/$(id -u)/com.bisati.news-house.tick | grep -E 'state|last exit'`

Cadence: a tick every two hours (a missed interval runs at the next wake). The first tick at or after 06:00 local builds the day's edition; every other tick scans for breaking stories.

Staging rule: develop on a branch in the dev clone with SQLite (`DATABASE_URL=sqlite:///...`); `main` is production and the only deploy path. Do not install the agent until the branch is merged into `main`.

## Reading it on the phone

`newshouse serve` serves `out/` and accepts the page's reactions (`POST /feedback`: worth, skip, later, should have, seen, read) so they reach the database:

```
.venv/bin/newshouse serve --out out          # http://0.0.0.0:8787/, GET / redirects to /latest.html
```

`bash scripts/install_launchd.sh` installs both agents (tick and serve), so the server starts at login and restarts if it dies; `uninstall_launchd.sh` removes both. On the home network open `http://<mac-name>.local:8787/latest.html` on the phone; `index.html` beside it lists every past edition. When the Mac is unreachable, reactions queue in the browser and drain on the next page load.

The server binds all interfaces, so the page is reachable from any network the Mac joins, including public Wi-Fi, and the edition JSON contains profile-derived lines. Run it on the home network, or pass `--host 127.0.0.1` to keep it local.

Log: `~/Library/Logs/news-house/serve.log`.

## Hosting

The paper is readable on the phone anywhere at a Vercel address, and taps made there reach the Mac.

The flow:

1. The Mac builds and renders as before (`newshouse tick`).
2. On every tick (when `PUBLISH_REMOTE` is set), `newshouse publish` copies the rendered pages, fonts and the `site/` bundle into an orphan `site` branch of the private GitHub repo and pushes it. A publish with no changes makes no commit and no push; a push that failed earlier is retried. Commits carry the identity `bisati <81610063+bisati@users.noreply.github.com>` (the GitHub no-reply address Vercel accepts).
3. Vercel deploys the `site` branch only: the `ignoreCommand` in both `vercel.json` files (the repo root's on `main`, `site/vercel.json` on the `site` branch) skips a build for any other branch. `/` redirects to `/latest.html`; the archive stays at `/index.html`.
4. A tap on the page posts to `/feedback`, which Vercel rewrites to a Python function (`site/api/feedback.py`). The function stores the tap, lightly checked, as one row in a one-table Neon inbox (`feedback_inbox`).
5. Before each build the Mac runs the sync: it records new inbox rows through the same check as the local server, marks them synced, and deletes rows synced more than 30 days ago. A row synced twice is recorded once.

Neon holds only the inbox. The main database stays local SQLite. A Neon or GitHub outage never stops a build: the tick logs a warning and records `feedback_sync` or `publish` as an error in its stats (the tick Run row's `stats` always carries both results), and the local page is unaffected.

**One clone runs the real paper.** Every clone on the Mac reads the same `~/.config/news-house/*.env`, so only the clone that builds the real paper (the one whose `newshouse.db` holds the editions; until the launchd agent is installed, that is the dev clone `~/mihir_ai/news-house`) should run `tick`, `sync-feedback` or `publish`; a second clone would sync the inbox into its own database and publish its own pages. Each clone gets its own publish worktree (`~/.cache/news-house/site-<8 hex of the repo path's sha1>`), so a second clone cannot take over or break the first one's. When the launchd agent is installed, the production clone `~/mihir_ai/news-house-prod` needs the dev clone's `newshouse.db` moved into it (`install_launchd.sh` does not copy the database).

Settings, all outside the repo in `~/.config/news-house/*.env` (mode 600):

- `neon.env`: `NEON_DATABASE_URL=postgresql://...` (the Neon connection string; a secret, never printed or logged).
- `publish.env`: `PUBLISH_REMOTE=origin` (a remote name or URL; unset means never publish). Optional: `PUBLISH_BRANCH` (default `site`), `PUBLISH_WORKTREE` (default `~/.cache/news-house/site-<repo hash>`, one per clone), `PUBLISH_AUTHOR_NAME` (default `bisati`) and `PUBLISH_AUTHOR_EMAIL` (default `81610063+bisati@users.noreply.github.com`).
- Vercel project settings: the same `NEON_DATABASE_URL` as an environment variable, for the function.

Commands:

```
.venv/bin/newshouse inbox-init       # create the feedback_inbox table in Neon (once; safe to repeat)
.venv/bin/newshouse sync-feedback    # record new inbox rows now (500 per pass, up to 20 passes); the tick does this before each build
.venv/bin/newshouse publish          # push the rendered pages to the site branch; exit 2 if PUBLISH_REMOTE is unset
```

`newshouse publish` reads `--out` (default `out`). The launchd tick needs git push to work without a prompt: the credential helper for github.com is the GitHub CLI's `gh auth git-credential`, set in the global git config (`gh auth setup-git`), not the macOS keychain. A push that cannot authenticate fails fast and is logged, not hung. Neon calls time out too: the sync connects within 10 s and each statement gets 30 s; the function connects within 5 s and each statement gets 5 s.

**The endpoint is public.** There is no access control, by Mihir's choice: anyone with the address can read the paper and post a tap. The function accepts only small, well-formed bodies (at most 4 KB, a known action, ids as short strings, a payload object) and answers 400 or 413 otherwise. A forged tap that passes is one junk inbox row; the sync drops it if it names a card or cluster the Mac does not have, or fails the normal feedback check, and counts it as invalid.

One-time Vercel setup:

1. Import the repo (`bisati/news-house`) as a new project.
2. Set the production branch to `site` and the root directory to the repo root. Framework preset: "Other".
3. Add `NEON_DATABASE_URL` as an environment variable (production).
4. Run `inbox-init`, then `publish` once, so the `site` branch exists to deploy.

## The edition config

`config/edition.yaml` is committed (no secrets) and shapes every edition:

- `budget_seconds`: the reading budget, 1200 seconds (about 20 minutes). This file is the only place the budget is set: an edition first made by the breaking lane takes it from here too. The budget is a ceiling, not a target: a quiet day stays short rather than reaching down below the noise floor.
- `cards: {floor, cap}`: an edition has at least 8 and at most 36 cards. The floor is filled even past the budget. Breaking cards written earlier in the day count toward the cap (and lower the floor), since the validator counts every card. At the average card length the budget fits about 34 cards; 36 is reachable only on a day with stacks or shorter cards. The breaking lane also stops at the cap: it writes no breaking card once today's edition has 36 cards, and records `cap_reached` in its run stats (set only when a cap, this one or `BREAKING_DAILY_CAP`, actually stopped a candidate).
- `topics`: per topic, `min` is a floor (that many cards are taken first, before the budget, if the topic has stories) and `max` is a cap. `default` covers any topic not listed. Since phase 4 the floors favour what Mihir reads for: `startups` 1-4, `ai-tools` 1-4, `product-design` 2-4 (labelled "Product"; PM craft, PM careers and product news, as well as design), `edtech-competitors` 1-3, and `gurgaon-local` 0-2, so one local story (a GRAP stage change, a closure) cannot fill the paper. Breaking cards count toward these caps too.
- `top_n`: the 10 most important stories of the day must either get a card or appear in the also-happened list with the reason they were cut (budget, topic cap, card cap).
- `also: {max, per_topic}`: the "Also today" list. At most `max` (25) unfolded lines, at most `per_topic` (2) per primary topic, and no line for a story whose thread already has a printed card or an earlier line. A line over a topic's cap is left out so other topics fill the slots; a top-10 story over the cap is kept as a folded row with its cut reason (the page shows them as one line per topic, for example "+7 more Gurgaon stories cut as duplicates", which expands). An unknown key under `also` is an error.
- `colours` and `live`: which colour family (world, ai, business, sport, city, screen; `newshouse/present.py`) a topic belongs to, the team kit colours, and the live data behind the tiles under the masthead (`live.aqi` has the coordinates, `live.fixtures` the team and its ESPN `team_id`, 83 for Barcelona).

Edit it, commit it, merge to `main`; the next build reads it.

## Stacks

One story told five times is one post. After scoring, a single Haiku call (`newshouse/stacks.py`) reads the headlines and primary topics of the top 60 pool clusters and groups the ones that are *the same event or a direct follow-up of it*. It does not use embeddings for this: they cannot tell two different Barca stories (0.84) from duplicate pollution reports (0.77). Bad groups are dropped and the rest kept (an unknown id, a cluster in two groups, a group across topics, or more than 6 members); if the call fails there are no stacks and the build carries on.

- The highest-scored member leads. The others are removed from the pool before selection and get no card of their own and no "Also today" line. If the lead itself is cut (budget, cap, thread), its members go back to the pool as normal clusters for "Also today", each carrying the lead's cut reason, so they are explained (and an owed lesson does not warn about them).
- A stack counts as **one post** against its lead's topic cap and the card cap. Its reading time is the lead's plus 10 seconds per extra member.
- One Opus call per stack (`--effort low`), for at most `MAX_STACKS` (10) stacks per build, best lead score first, writes a headline and a short line for each extra member from that member's own items. The truth rule is the same as for cards: a number in the line must appear in the member's brief, otherwise that member gets a headline-only row. Stacks past the tenth get headline-only rows with no call. A stack that fails for any other reason (a member with no items, a database error) falls back to headline-only rows, skipping a member it cannot read; stacks never fail the build.
- On the page a collapsed post shows a quiet chip, "+N more on this story". Expanded, a "More on this story" strip follows the body: swipe through the follow-ups (source, headline, line, "Read at <source>"), with dots underneath.
- The breaking lane uses the same grouping call on today's breaking headlines only, and skips a candidate that is the same story as a breaking card already written today. A stack whose lead is a breaking card keeps its pinned slot and gains the members.
- The build records `stats["stacks"]` as groups, members, lines failed and `capped` (stacks past `MAX_STACKS`).

Editions built before phase 4 have no stacks and render as they were.

## Live tiles

Three white tiles sit under the masthead: "Gurgaon air now", "Next match" and the market. `newshouse build` fetches them once, in a stage after Select, and stores them on the edition (`Edition.live`); the page then refetches them every 30 minutes while it is visible.

- Air: Open-Meteo's air-quality API (PM2.5 and PM10 for the Gurgaon coordinates in `config/edition.yaml`), turned into India's CPCB AQI. The basis is the mean of the last 24 hourly values, because CPCB defines its PM sub-indices on 24-hour averages (with fewer than 12 valid hours it falls back to the current value). The tile says "24-h avg · model estimate". It is a model, not a station: on 3 November it read 302 against an official 246, so expect it to sit about one band above the CPCB figure.
- Match: ESPN's public team schedule (`site.api.espn.com`, no key); the first fixture after now, with the kickoff in IST.
- Market: Nifty 50 from NSE's `www.nseindia.com/api/allIndices` (no key; it wants a browser User-Agent), fetched at build time and again on every later tick of the day: when the numbers differ from the tile's, the tick saves them on the edition, re-renders the page and publishes it, so during market hours the tile is at most two hours old. The row shows the level and NSE's day change with an arrow (a rise in the page ink, a fall in tomato-ink), "as of HH:MM IST" (with the weekday when the numbers are from an earlier day), and Trend opens the change over 1 week, 1 month and 1 year. Sensex is not shown: Yahoo rate-limits both the Mac and Vercel (429/502 on 2026-11-04 and 05) and BSE refuses scripts.
- Failure: a fetch that errors, times out, returns non-2xx or lacks the expected keys is logged at warning and that tile is simply not stored or drawn. The row hides when all are missing. A build never fails because of a tile, and a failed refresh in the page leaves the tile as it was.

## Tune tomorrow

After the end card the page has a "Tune tomorrow" post with four chips: "Less <the topic with the most posts>", "More <the topic with the best-scored cut story>", "More <the next such topic>", and "Shorter edition" (or "Longer edition" when the edition ran under 12 minutes). They are generated by a fixed rule, not a model.

A tap is sent to the server like the other reactions and counts for the **next built edition only**: a topic weight moves by 0.3 (clamped to -1 to 1) or the reading budget by 120 seconds. Each chip is one step; tapping the same chip again does not stack, and for a given topic or for the budget the last tap wins. A tapped chip shows as selected and is disabled, and so is its opposite on the same topic. Taps made before the previous edition was built are ignored, and the applied adjustment is recorded in the build's stats under `tune`.

## Lessons ledger

`ledger/lessons.json` (committed, no secrets; path overridable with `LESSONS_PATH`) records stories the paper missed, why, and the fix. The ten newest go into the classify prompt under `## Lessons`.

- A "Should have been in" tap shows "Noted ✓" and the button stays disabled, also after a reload (the pressed state is kept in the browser by cluster id, like "seen"). A tap on a cut top-10 line becomes a stub lesson **at the next build** (never by the page server, which writes no repo files). Stubs are idempotent by feedback id and carry the story's score, cut reason and the cutting run's id.
- An open lesson with `owed` (`{"thread_id": ...}` or `{"topic": ...}`) is checked by the validator: when a story scored in the edition's selection window matches, is above the noise floor, and is neither printed nor explained in "Also today", the edition gets a warning naming the lesson.

```
.venv/bin/newshouse lesson add --text "Missed the IPL auction"      # prints the new lesson id
.venv/bin/newshouse lesson add --from-feedback <feedback-id>        # make a stub by hand; exit 1 if none applies
.venv/bin/newshouse lesson list                                     # open lessons: id, date, miss
```

Fill in `why`, `fix` and `owed` by editing the JSON, then commit it.

## Night palette

The page follows the system light/dark setting. `?theme=dark` or `?theme=light` on the URL overrides it, which is what the screenshot script uses. Paint colours (mint, sky, tomato, butter fills) stay in the dark theme, as the design specifies; white posts take the dark post colour. `scripts/shot.py` takes the same choice:

```
.venv/bin/python scripts/shot.py out/latest.html out/shots --theme dark    # PNGs named 390x844-dark.png and so on
```

## Rendering

`newshouse render --date D` also copies the page to `out/latest.html` when D is the newest built edition (as `tick` already did); rendering an older edition leaves `latest.html` alone.

## The validator

Every build checks the written edition before it is saved: headline and gist length, banned words and patterns (`config/banned.yaml`), generic "why it matters" lines, visual payloads, card count and minutes (12 to 24 minutes: the edition is about 20 minutes, up to 36 posts), topic floors, the top-10 rule, and one card per thread. A card with a text problem gets one rewrite; a card whose visual or slides are still broken after the retry keeps its text, gets an automatic cover and no slides, and the edition carries a `payload-fallback` warning. Whatever remains is stored as the edition's `warnings`, written into the edition JSON and listed in small type under the end card.

To check an existing edition without any model call (report only: the warnings are stored and shown, no card is rewritten):

```
.venv/bin/newshouse render --date 2026-10-30 --validate --out out
```

## Visuals and slides

Each post carries one visual, chosen by the writer from a fixed catalogue (`newshouse/catalogue.py`):

- `cover`: one big figure or two words, a small label and a line (the default).
- `chart`: three or more bars, each value traced to a cited item, with a unit and a caption.
- `table`: rows of label, figure and comparison, with `yours` and `new` tags. Table values are at most 28 characters and must read on their own (no test ids, ticket numbers or sentences); `catalogue.check_visual` rejects longer ones and the post falls back to the cover. Values of 17 to 28 characters are set in the 17px sans body face, not the large serif.
- `timeline`: today's development on top, the thread's earlier chapters below.
- `versus`: the case for, the case against, and where it stands.
- `before-after`: a rule or price before and after, with when it takes effect and who it applies to.
- `pitch`: a football line-up on a pitch, rows from the back line forward, in the team's kit colours (`config/edition.yaml` under `colours.teams`).
- `photo`: the source's own image, hotlinked over https, never from Google News; a broken image shows the cover instead.
- `quote`: one line, word for word from its item, with who said it.

`versus` and `before-after` are small body text, so the 28-character limit does not apply to them. A post may instead carry a deck of two to four slides: a cover first, then `chart`, `table`, `text` (35 words or fewer) or `what-next` (60 words or fewer, always last). Slide colours run butter, sand, tomato, forest; the writer never picks them. Every number on a slide must appear in the brief. The writer also sets a tone (`good`, `bad`, `mixed`, `neutral`) that tints the post's colour world.

To see every kind on one page without a model call or a database:

```
.venv/bin/python scripts/sample_edition.py --out out/sample          # prints out/sample/<today>.html
.venv/bin/python scripts/shot.py out/sample/<today>.html out/sample/shots
```

The sample's photo card points at `https://invalid.example/missing.jpg` on purpose, so it shows the fallback cover.

## Screenshots

`scripts/shot.py` screenshots a rendered page with headless Chrome at 390x844, 430x932, 768x1024 and 1280x800 and fails on layout defects: horizontal overflow, any text under 11px, an empty visual, a post taller than 1.4 screens, a deck with fewer than two or more than four slides, a slide whose content overflows it, a visible photo that did not load, or (at 430px wide or less) a visual or deck taller than 320px.

```
.venv/bin/python scripts/shot.py out/2026-10-30.html out/shots     # one line per size; exit 0 = all pass
```

It needs Google Chrome (or `$CHROME`). At phone sizes the PNG shows a grey margin on the right: headless Chrome will not open a window narrower than 500px, so the page sits in an iframe of the exact size.

## Database

SQLite is the default (`sqlite:///./newshouse.db`, one file per clone). Production uses Postgres on Neon so the phone app can read the same data. Embeddings are stored as bytes and similarity is computed in Python, so `pgvector` is not needed.

One-time steps for the owner:

1. Create a free Neon project named `news-house`.
2. Copy the pooled connection string into `~/.config/news-house/db.env` as `DATABASE_URL=postgresql+psycopg://...`.
3. `chmod 600 ~/.config/news-house/db.env`.

Then create the tables, copy the existing data and verify:

```bash
newshouse init-db
python scripts/migrate_sqlite_to_pg.py --from sqlite:///./newshouse.db --to "$DATABASE_URL"
psql "$DATABASE_URL" -c '\dt'     # should list 12 tables
```

The migration copies the tables in dependency order (parents before children, so `threads` before `clusters`) in batches of 1,000, skips rows that already exist (safe to re-run), prints source and target row counts per table, and exits non-zero if any differ. `--to` defaults to the `DATABASE_URL` environment variable.

## Staging vs production

GitHub is the source of truth. `main` is production. Work happens on `build/plan-a`; running locally on that branch with SQLite is staging.

See `docs/design.md` for the design and `docs/how-this-was-built.md` for the build process.
