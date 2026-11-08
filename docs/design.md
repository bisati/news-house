# News House: Design

Date: 2026-10-30. Status: approved by Mihir on 2026-10-30 (directionally, with the answers in section 13); next step is the implementation plan.
Name: **News House** (repo `news-house`, named by Mihir on 2026-10-30).

Companion files:
- `news-house/sources/sources.yaml`: the topic-to-sources map (265 sources, 235 verified on 2026-10-30).
- `news-house/sources/checkfeed.py`: the feed verifier that produced the `verified`/`last7d` fields.
- `news-house/card-format-mockups.html`: the seven card formats as reviewed on 2026-10-30 (structure only; visual design deferred).

---

## 1. Intent and why

Mihir spends roughly two hours a day scrolling Instagram and gets ten to fifteen minutes of value out of it. The algorithm optimises for eyeballs, so the things that matter to him get buried under slop, and even when they surface they're served flatly. Twitter and the rest have the same shape.

This product replaces that habit with a **15-minute daily read ranked by importance to him, not virality**. It is built for one person first. Opening it to other people is a later phase, and nothing in v1 should preclude it, but nothing in v1 is built for it either.

The three jobs, in his framing:

1. **Don't miss what matters to him**, even when it never went viral. Instagram has no notion of importance-to-you.
2. **Hear things early**, including from circles he hasn't reached yet. A new Gemini model should reach him the hour it drops, not three days later when it's a meme.
3. **Fit in 15 minutes.** A daily "here's everything that moved in your world", skimmable, with depth on demand so he can go deep later on what's worth it.

The feed replaces the habit. The 15-minute digest is the promise.

### Why it isn't Inshorts

Inshorts is one template (60 words plus a stock photo) applied to everything, ranked for everyone. This product differs in six specific ways, ordered by how much they matter:

1. Every card says **why it matters to him**, written against a profile of who he is and what he works on.
2. **The feed ends.** It says "you're caught up" after the day's worth. A finite feed is the real anti-doom-scroll feature, and it is a decision no ad-funded product can make.
3. **Stories are threads, not items.** Ongoing stories show only the delta since he last read, with a one-tap recap.
4. **The story picks its format**, not a template. Launches get comparison tables, numbers get charts, sagas get timelines, debates get two sides, rule changes get before/after.
5. **Depth is a dial.** One line, a paragraph, a brief, the sources. The 15-minute budget is the top layer of everything, not the full read of a few things.
6. **His reactions train the ranker.** Worth it / skip / later on every card.

---

## 2. Goals, non-goals, anti-goals

### Goals (v1)

- G1. One edition a day, sized to about 15 minutes at the default depth, drawn from the 14-topic source map.
- G2. Every card carries a personalised "why it matters to you" line grounded in the profile file.
- G3. The feed has an end screen. Nothing loads past it.
- G4. Four-level depth dial on every card; the brief is grounded in fetched article text where available.
- G5. Worth-it / skip / later feedback, stored and fed back into ranking.
- G6. Threads: ongoing stories are detected, numbered, and shown as deltas.
- G7. Seven card formats (A to G in section 5.2), chosen per story from its content, never from a template default.
- G8. A breaking lane between editions for the rare thing that can't wait (capped at three a day).
- G9. Runs itself. On a normal day nothing requires a manual step. Failures are visible in a run log.
- G10. Every factual claim on a card is traceable to a source item. No invented numbers, no rich format without data from the sources.

### Non-goals (v1)

- Multi-user, accounts, onboarding, a topic registry. The data model keeps a `profile_id` column so this is additive later; nothing else is built for it.
- The newspaper view. It is phase 2 (section 5.5 describes it at concept level so v1 doesn't paint it into a corner).
- X / Twitter ingestion. Seven handles are recorded in the source map; they need the paid X API. Their owners are covered through newsletters and blogs where those exist.
- Native app or app-store presence. Phone-first PWA only.
- Push notifications. The edition is simply there at the edition time.
- Full text of paywalled sources. Headline plus teaser is what we get and what the writer may use.
- Scrape-only sources (12 in the map). Skipped in v1 unless the builder finds one trivial.
- Scores and match reports for sports. He watches the matches.

### Anti-goals (what would make this a failure even if it technically works)

- Anything that makes the feed infinite or sticky: autoplay, "more like this", recommendations past the end screen.
- Engagement mechanics: streaks, likes, comments, badges, share counts.
- Becoming a generic aggregator. The test: if a card could appear in Inshorts unchanged, it is wrong.
- Sensational or clickbait framing in headlines or "why it matters" lines.
- Hallucinated facts. A card with an invented number is worse than no card.
- A "why it matters" line that is generic ("as a PM you might find this useful"). It has to reference something specific from the profile or it's omitted.

---

## 3. Constraints

- One builder, part-time. Favour boring, hosted, free-tier infrastructure.
- Cost ceiling for LLM and hosting: tens of dollars a month, not hundreds. See section 7.6 for the estimate.
- Mihir's existing deploy habit is GitHub to Vercel (note from past deploys: commits need a GitHub noreply email or Vercel blocks the build).
- Source access constraints discovered on 2026-10-30, all recorded per source in `sources.yaml`:
  - Reddit returns 429 to unauthenticated feed polling unless requests are about 60 seconds apart with a browser user agent. Use the official Reddit API with a registered script app (OAuth, free, 100 requests a minute) instead.
  - Google News RSS query feeds work and are the stand-in for every official body that publishes nothing machine-readable (Barça, BCCI, AIFF, ATP, GMDA, ONDC, NPCI, MEA, ORF and others).
  - Twenty sources are paywalled; their feeds carry headline and teaser only.
  - Several feeds exceed 2 MB (some Substack and podcast feeds); the ingester must stream and cap reads, not fail.
  - Some feeds are undated (PIB, Google Developers Blog, a GitHub Trending mirror); dedupe by GUID and treat first-seen time as published time.
  - Movies consensus needs keyed APIs (TMDB, OMDb; both free) plus IMDb's nightly ratings dump; Rotten Tomatoes, Letterboxd and BookMyShow are scrape-only and are non-goals for v1.
  - AQI for Gurgaon is available keyless from Open-Meteo. Barça fixtures are available keyless from ESPN's schedule JSON; F1 from Jolpica/OpenF1.
- Daily intake is roughly 600 to 1,000 items (the 7-day verified count was about 4,100 and several feeds cap at 100 items). Weekends are quieter, launch days are louder. The edition budget is therefore time, not a fixed item count.

---

## 4. The user and the profile file

v1 has one user: Mihir. Everything the ranker and writer know about him lives in one plain-text file, `profile.md` (gitignored; `profile.example.md` is the committed template), that he edits by hand. It is versioned (every edit stored with a timestamp) so a change in ranking can be traced to a change in profile.

Sections, with a starting draft the builder should include and Mihir should correct:

- **Who I am.** Product Manager, Growth and AI, at Coding Ninjas (Indian edtech, upskilling courses, mobile-first consumer platform). Based in Gurgaon. Engineering background (BITS Pilani), ex-Samsung R&D.
- **What I work on now.** AI products in production: voice agents, LLM extraction pipelines, prompt A/B tests, growth analytics, plus a couple of side projects.
- **My stack.** Gemini and Claude APIs, SQL analytics, Vercel for deploys.
- **What I want to hear early.** Model and API releases I could use at work, pricing changes on models I run, new agent and voice capabilities, what edtech companies are doing and what students say about them.
- **Interests outside work.** Barça first, then La Liga, Champions League, Premier League; Indian football; cricket; tennis; F1. Watches the matches, so wants tactics, analysis and insider discussion, not scores. Movies: Hindi, English, the big South crossovers, streaming originals; wants "is it worth watching" by consensus.
- **Where I live.** Gurgaon: traffic, metro, AQI and GRAP stages, civic notices, Haryana decisions that touch property or commuting.
- **What I'm tired of.** Virality-ranked feeds, reaction content, listicles, "A beat B".
- **Register.** English with natural Hindi-English code-mixing acceptable in headlines; direct; no hype.

The profile is used in three places: the importance score (section 7.4), the "why it matters" line (7.5), and the breaking-lane gate (7.8). It is injected verbatim into those prompts and cached.

---

## 5. Product shape

### 5.1 Editions

- **One edition a day**, dated by calendar day (IST). It is built by the pipeline running on Mihir's Mac: the first run after 06:00 IST that finds the Mac awake builds that day's edition; if the Mac was asleep, the job runs on the next wake. He wakes around 10:00 and the laptop is open most of the day, so in practice the edition is ready before he looks (his call, 2026-10-30: the morning deadline does not matter to him). Breaking-lane runs happen on the two-hourly ingest while the Mac is awake.
- An edition is an **ordered list of cards** sized to the time budget: estimated read time at the default "para" depth, summed in rank order, cut at 15 minutes. Starting constants: 35 seconds per standard card, 50 for chart/comparison/thread cards; hard cap 25 cards, floor 8. These are tuning knobs, not product rules; his feedback should move them.
- Below the cards, an **"Also happened" list** of 10 to 25 one-liners that scored above noise but didn't make the cut. This is the recall check ("did it miss anything?") and the cheapest way to learn where the cut line should be: each one-liner has a tiny "should have been in" button.
- Then the **end card** (format G): "You're caught up", with the day's counts and the saved-for-later list.
- **Breaking lane.** Between editions, the hourly run may promote at most three clusters a day that clear a high bar (section 7.8). They appear as a "1 new" pill at the top of the current edition, never as a stream, and are folded into the next edition's thread history.
- **Weekly rhythm.** Movies are weekly by nature (Friday releases). The Saturday edition gets a "worth watching this week" card and more room for long reads. Nothing else changes by weekday.
- **Fixture card** (small, optional): when Barça, India (cricket), or an F1 race is on in the next 24 hours, a one-line card at the top with the IST kick-off. Cheap, keyless, high delight. Builder decides whether it lands in v1 or phase 2.

### 5.2 Cards

Every card shares a spine:

- Topic chip, time since the event, number of sources.
- Headline (the one-line depth).
- Body at the current depth.
- **"Why it matters to you"** strip, visually distinct, one to two sentences, specific to the profile. If the writer can't make it specific, the strip is omitted rather than filled with filler.
- Depth dial: `1 line | para | brief | sources`. Default `para`. All four depths are generated at build time; nothing is generated on tap.
- Footer: `Worth it | Skip | Later`. One tap, no confirmation. Later adds to the saved list. Skip records the reaction and dims the card; it does not remove it.
- Sources: the list of source items (title, outlet, link, published time) the card was written from.

Seven formats. The writer chooses one per card from the story's content and emits the structured data for it; the UI renders. If the data a rich format needs isn't present in the source items, the writer must fall back to A. Mockups of all seven were reviewed on 2026-10-30 and accepted as "fine for v1, design later".

| Format | When | Structured payload |
|---|---|---|
| A. So-what card | Default | headline, line, para, brief |
| B. Comparison | A launch or change with comparable attributes (price, context, speed, features) | table rows and columns, with the row that matches his stack flagged `yours` |
| C. Chart | A number or trend with at least three data points in the sources | series (label, value), unit, caption, source item per point |
| D. Thread | A cluster that matched an existing thread | thread id, chapter number, the earlier chapters (title, date, read/unread), the delta |
| E. Two sides | A debate, proposal, or open policy question | for[], against[], where-it-stands line |
| F. Before / after | A rule, policy, or pricing change | before, after, effective date, who it applies to |
| G. End | Always last | counts, saved list |

### 5.3 Threads

A thread is a storyline across days (a renegotiation, a regulation, a transfer saga, a product's rollout). The pipeline matches each new cluster to open threads (section 7.7). A thread card shows the chapter number, greys out chapters he has already read (he opened the card or marked it), and shows only the delta. Threads that go quiet for 30 days close.

### 5.4 The end screen

Format G. Shows: cards read, minutes, saved count, "nothing else moved in your world today", next edition time, a button into the saved list, and a close button. Nothing loads after it.

### 5.5 Views

**Scroll feed (v1).** Single column, phone-first, installable as a PWA, dark and light. Cards in rank order, then "Also happened", then the end card. The home screen is the current edition. A saved list holds the Later items.

**Archive.** Every edition is kept forever and is reachable from an archive page listing editions by date. A past edition opens exactly as it was: the same cards, the same "Also happened" list, with his reactions shown. Nothing about an edition is recomputed later. (Mihir asked for this explicitly on 2026-10-30.)

**Newspaper view (phase 2, concept only).** The same edition laid out as a front page: a lead story, columns, sections by topic, with motion (animated charts, looping visuals) and the Daily Prophet playfulness. It consumes the same edition data, which is why cards must carry structured payloads (chart series, timeline rows) and not just prose. It is not designed here. The one constraint it places on v1: don't flatten card data into HTML strings in the database.

---

## 6. Topics and sources

Fourteen topics, as Mihir listed them, with the slugs used in `sources.yaml`:

| Slug | Topic | Sources (verified) | Items / 7 days |
|---|---|---|---|
| ai-models | AI models and new capabilities from the labs | 31 (24) | 267 |
| ai-built | Interesting things being built with AI | 22 (17) | 121 |
| india-tech-biz | Indian tech, startups, business | 19 (17) | 357 |
| intl-biz-tech | International business and tech | 17 (17) | 484 |
| edtech-competitors | Edtech and Coding Ninjas' competitors | 23 (20) | 130 |
| product-design | Product management, UI/UX, product design | 15 (15) | 60 |
| solutions | Well-solved problems, India and abroad | 15 (12) | 111 |
| geopolitics | Geopolitics, with an India lens | 15 (15) | 392 |
| india-news | Important India news | 15 (15) | 562 |
| gurgaon-local | Gurgaon news applicable to a resident | 15 (10) | 251 |
| movies | Recent releases and whether they're worth watching | 15 (9) | 153 |
| football | Barça, La Liga, UCL, PL, tactics; Indian football | 24 (17) | 561 |
| cricket | Cricket | 17 (12) | 457 |
| tennis-f1 | Tennis and F1 | 22 (15) | 226 |

Each source has a tier: **primary** (where the thing is announced), **early-signal** (where people who care hear it first), **mainstream** (confirmation). Tier is a ranking input, not a filter.

Kinds and how the ingester handles each:

- `rss`, `atom`: poll with a browser user agent, conditional GET (ETag / Last-Modified), stream with a 3 MB cap.
- `reddit`: Reddit API via OAuth script app registered on Mihir's Reddit account (section 13); `top` of the day per subreddit; one call per subreddit per run. Without the app, the fallback is one combined multi-subreddit RSS fetch per day with a browser user agent, which loses the "hear early" property for Reddit sources.
- `youtube`: channel Atom feed; item is the video title and description; no transcript fetch in v1.
- `hn`: hnrss or Algolia; the points floor is in the URL.
- `gnews`: Google News RSS query feeds. **The item link does not resolve to the publisher** (verified 2026-10-30: it redirects to a Google News JS page; the only decoder is undocumented and breaks periodically). The feed gives title, publisher name and publisher domain. v1 policy (my call): treat gnews items as teaser-only; dedupe and cluster them by embedding and title similarity against items from publisher feeds already ingested (when a match exists, the cluster gets the publisher URL and can be enriched); gnews-only clusters are never enriched, use format A only, and link out to the Google News URL, which opens fine for a human. A decoder or scrape adapters for the official bodies are phase 2.
- `podcast`: RSS; item is the episode title and show notes; no audio processing.
- `api`: per-source adapter (Hugging Face trending, ESPN schedule, Open-Meteo AQI, TMDB, OMDb, IMDb dump). Builder writes a small adapter per kind of API; v1 ships the ones needed for G1 to G8 and treats TMDB/OMDb/IMDb as phase 2 if time is short.
- `x`, `scrape`: recorded, not ingested in v1.

Source health: a weekly job re-runs the checker over every `url`, records `last7d`, and flags any source with no items in 30 days in the run log. Adding a topic later means adding entries to the YAML and a line in the profile.

Seven URLs appear under two topics on purpose (for example Finshots, Money Stuff). Items are stored once and tagged with every topic their source belongs to.

---

## 7. Pipeline

Two schedules: **ingest** every two hours, **build** once a day. Both are idempotent and safe to re-run.

### 7.1 Ingest

For each source due: fetch, parse, normalise to an **Item**:

`id (hash of canonical url, else guid, else source+title), source_id, topics[], url, canonical_url, title, teaser (feed summary, stripped), body (null until enriched), author, published_at (feed date, else first_seen), first_seen_at, lang, raw_json`.

Exact-duplicate URLs across sources collapse to one item with multiple `item_sources` rows. Items older than 72 hours at first sight are stored but marked `stale` and excluded from editions (except for threads).

### 7.2 Enrich

Only for items that reach the shortlist (after 7.4), to keep fetch volume down: fetch the article page, extract main text (readability-style), store as `body`. Skip paywalled sources (keep the teaser). Compute an embedding of `title + teaser` for every fresh item at ingest time (cheap; needed for clustering).

### 7.3 Cluster

Within a rolling 48-hour window, group items into **clusters** (one cluster = one event or story candidate): embedding similarity above a threshold, plus a cheap-model confirmation pass for borderline pairs. A cluster records its items, its topics (union), source count, best tier present, earliest and latest published times. Multi-source clusters are a strong importance signal; single-source clusters from primary-tier sources are also legitimate (a changelog entry is one source and can still be the most important thing that day).

### 7.4 Classify and score

One cheap-model call per fresh cluster (batched), with the profile injected and cached. Output, as strict JSON:

- `story_type`: launch | number | saga | debate | rule_change | plain | fixture | noise
- `topics[]` (may refine the source-derived topics)
- `importance` 0 to 100, defined as: how much Mihir would regret not knowing this today, given the profile
- `early` 0 to 100: how far ahead of mainstream this is (primary or early-signal only, not yet in mainstream sources)
- `reason`: one line, stored in the edition log so he can see why something was in or out
- `breaking_eligible`: boolean (section 7.8)

Final score = importance, adjusted by: freshness decay, source-count bonus, tier bonus, topic weight and source weight learned from feedback (7.9), novelty against open threads (a thread's fourth chapter needs a real delta to score). The exact formula is the builder's; the inputs are fixed here.

### 7.5 Select the edition

Rank by final score. Apply diversity: no more than 5 cards from one topic, and any topic with a cluster scoring above a high threshold gets at least one card. Fill the time budget (5.1). Everything from the threshold down to the noise floor goes to "Also happened". Record the cut line and every decision in the edition log.

### 7.6 Write cards

One stronger-model call per selected cluster, with: the cluster's items (bodies where enriched, teasers otherwise), the profile, the thread history if any, and the house style. Output as strict JSON matching the format payloads in 5.2, plus the four depths and the "why it matters" line, plus `cited_item_ids[]` per depth. Rules the prompt must enforce:

- Every number, name, date and claim must appear in a cited item. If the sources only have a teaser, the card is honest about that ("The Ken reports..., paywalled").
- Choose a rich format (B to F) only when the payload can be filled entirely from cited items; otherwise A.
- "Why it matters to you" must reference a specific profile fact or be left empty.
- Headline: factual, specific, no hype, under 90 characters. Hindi-English code-mixing is allowed where natural, never forced.
- The brief is 3 to 6 short paragraphs and may include a "what to watch next" line.

Cost estimate (prices verified 2026-10-30 for Claude, 2026-09-26 for Gemini):

| Stage | Volume / day | Model | Approx. cost / month |
|---|---|---|---|
| Embeddings | ~800 items | Gemini embedding (free tier or $0.20 / 1M) | under $1 |
| Classify and score | ~500 clusters × ~700 tokens | Claude Haiku 5.5 ($0.10 / $0.50) | ~$2 |
| | | or Gemini 3.5 flash-lite ($0.30 / $2.50) | ~$7 |
| Write cards | ~20 cards × ~8K in, 1.5K out | Claude Opus 5.5 ($4 / $20) | ~$37 |
| | | or Claude Sonnet 5.5 ($2 / $10) | ~$19 |
| | | or Gemini 3.8 flash ($0.75 / $3.75) | ~$7 |
| Hosting | | Vercel hobby, Neon free tier, GitHub Actions free minutes | $0 |

Recommendation: Haiku 5.5 for classification (it runs 500 times a day and only needs to be consistent), Opus 5.5 for writing (it runs 20 times a day and is the entire reading experience). About $40 a month. Sonnet 5.5 halves that at some quality cost. Which pair to use, and which account pays, is Mihir's call (section 13). Note for the builder: Gemini reasoning models bill thinking tokens as output and they can be 85% of the charge; the flash-lite tier emits none. Prompt caching on the profile and house style should be on from day one.

### 7.7 Threads

After scoring, match each cluster to open threads by embedding similarity against the thread's summary and a cheap-model yes/no. Matched clusters inherit the thread and get a chapter number; the writer receives the earlier chapters' one-liners and must write the delta. Unmatched clusters that are `saga` or score high open a new thread. Threads close after 30 quiet days.

### 7.8 Breaking lane

After each ingest run, clusters flagged `breaking_eligible` with importance at or above a high threshold (start at 90) get a card written immediately and are pushed to the "new" slot of the current edition. Eligible types, by policy: a model or API release or pricing change in his stack; a Gurgaon disruption affecting the same day (GRAP stage change, major closure); major India news; a Barça transfer or managerial change. Maximum three a day. Everything else waits for the morning.

### 7.9 Feedback into ranking

Worth it / skip / later / "should have been in" are stored as events. v1 uses them two ways:

1. **Weights.** Exponentially weighted per-topic and per-source scores (worth it and later count up, skip counts down, "should have been in" counts up for the source and topic) feed into the final score in 7.4.
2. **Examples.** The last 20 worth-it and 20 skip headlines are injected into the classify prompt as "recent reactions" so the model can calibrate.

A learned model is a later phase, once there are a few thousand events.

### 7.10 Where the LLM calls run

Two ways to pay for the model calls. The pipeline is written with a backend switch (`LLM_BACKEND=api|claude-code`) so this is a configuration choice, not a rewrite.

**API (Anthropic SDK, metered).** Runs anywhere, including GitHub Actions. Structured outputs, prompt caching, the Batch API at half price for the daily build, Haiku pricing for the 500 classify calls. Realistic monthly cost with caching and batching: about $12 with Sonnet 5.5 writing, about $20 with Opus 5.5 writing (list price without those: $25 to $45).

**Claude Code headless on Mihir's Mac (subscription).** The pipeline shells out to `claude -p ... --output-format json` for each model step, batching about 50 clusters per call so it is roughly 30 to 40 invocations a day. No metered cost; it draws on his Claude plan's usage limits. Constraints: the Mac must be awake and online at build time (a scheduled wake via `pmset` works when plugged in; a closed-lid laptop is not reliable), so the phone may not have the edition at 07:30; each invocation carries Claude Code's system-prompt overhead; only Claude Code's models are available (no Haiku-priced classification); and this is a personal-use arrangement that must move to the API in the multi-user phase. The hosted database and app stay exactly as in section 8; only the model calls move.

**Hybrid.** Mac-first at 06:30 IST; if no edition exists by 07:00, GitHub Actions builds one on the API. Costs only on the days the Mac missed.

**Decision (Mihir, 2026-10-30): Claude Code headless on his Mac, under his Max plan, for v1.** The API backend stays in the code as the switch for the public phase. Phase 0 also runs on Claude Code. Overhead mitigation for the headless route, verified against Claude Code 2.1.314 on 2026-10-30: `--tools ""` (no tool definitions), `--system-prompt-file` (replaces the whole default prompt), `--setting-sources project,local` (no user settings, plugins, hooks, MCP or `~/.claude/CLAUDE.md`), `--no-session-persistence`, `--output-format json` with `--json-schema` (validated object comes back in `structured_output`). Measured cache-creation tokens per call: about 36,000 with defaults, about 550 with these flags. Do not `--resume` between batches (history grows); a fresh call with a byte-identical system prompt is a cache hit above the minimum prefix size. `--model haiku` is selectable under the subscription, so classification runs on Haiku and writing on Opus. Run the pipeline from a fixed working directory with no `CLAUDE.md`. For unattended runs set `CLAUDE_CODE_RETRY_WATCHDOG=1`. Policy note from the Claude Code legal page: Pro/Max OAuth is for the purchaser's own ordinary use; a personal pipeline on his own machine fits, serving other people does not, which is why the public phase moves to the API.

### 7.11 Run log and observability

Every run writes a row: started, finished, items fetched per source, failures per source, clusters formed, tokens spent per stage, edition size, cut line. The app has a plain `/log` page listing runs and, per edition, each cluster's score and reason. This is how the ranker gets debugged.

---

## 8. Platform and stack

These are my calls, made so the builder can start. Mihir can override any of them.

- **Repository.** New private repo `news-house` under Mihir's personal GitHub account (`bisati`), the same pattern as `cutlist-private`: Vercel Hobby, deploy on push to main, repo-level GitHub noreply commit email. The pipeline code lives in the same repo and is run from a local clone on the Mac.
- **GitHub is the source of truth (Mihir, 2026-10-30).** Everything is on GitHub from day one, including the spec, the plan, the card mockups, the LLM prompts, and a build log that records which agents did what, so the project can be shown on his profile and made replicable later. Production is only ever deployed from `main`: the Mac's scheduled job runs `git pull --ff-only origin main` before each tick, and the Vercel app deploys from `main`. Work happens on branches pushed after every task; merging to `main` is the deploy. Local runs on a branch with a SQLite database are staging.
- **App.** Next.js (App Router) in TypeScript with Tailwind. PWA manifest and service worker for installability and offline reading of the current edition. Hosted on Vercel. Server components read from the database; a small route handler records feedback.
- **Database.** Postgres on Neon (serverless, free tier, pgvector available for embeddings). Supabase is an acceptable swap if the builder prefers its dashboard.
- **Pipeline.** Python 3.12 (feedparser, httpx, pydantic, a readability extractor). Runs on Mihir's Mac as launchd jobs: ingest every two hours while awake, build once per calendar day on the first run after 06:00 IST (launchd runs a missed interval on wake). It writes to the hosted database, so the phone app is unaffected by where the pipeline runs. A `make run` target runs the same thing by hand. GitHub Actions with the API backend is the documented fallback for the public phase, not part of v1.
- **Secrets.** Database URL, Reddit app credentials and any API keys live in `~/.config/news-house/` (mode 600) on the Mac and in Vercel environment variables; never in the repo. `profile.md` is **gitignored** (it is personal); `profile.example.md` is committed so the repo is replicable. The live profile is also stored in the database on each build.
- **Access.** v1 has no login. The app is gated by a single long secret in the URL path or a cookie set once. Good enough for one user; replaced by real auth in the multi-user phase.
- **LLMs.** v1 backend is Claude Code headless (`claude -p`) on the Mac under Mihir's Max plan: Haiku (`--model haiku`, verified selectable) for classification and thread matching, Opus for card writing. Every model step asks for strict JSON and validates it against a schema; a failed validation retries once with the error shown. The `api` backend (Anthropic SDK, structured outputs, prompt caching, Batch API) is implemented behind the same interface for the public phase.
- **Embeddings.** A small local sentence-transformers model on the Mac (keyless, about 800 items a day on CPU is seconds). Gemini embeddings are the alternative if the pipeline ever moves off the Mac.

---

## 9. Data model

Tables, with the columns that matter to the design (the builder adds the rest):

- `sources`: loaded from `sources.yaml` on every build; `id, topic[], name, tier, kind, url, home, paywall, enabled, last_ok_at, last7d`.
- `items`: section 7.1. `embedding vector`.
- `item_sources`: item to source, for cross-source duplicates.
- `clusters`: `id, window_start, topics[], story_type, importance, early, reason, final_score, thread_id, breaking`.
- `cluster_items`.
- `threads`: `id, title, summary, opened_at, last_chapter_at, closed_at`.
- `editions`: `id, date, built_at, budget_seconds, cut_score, profile_version`.
- `cards`: `id, edition_id, rank, cluster_id, thread_id, chapter, format, payload jsonb, line, para, brief, why, est_seconds, cited_item_ids[]`.
- `also_happened`: `edition_id, cluster_id, line, rank`.
- `feedback`: `id, profile_id, card_id or cluster_id, action (worth|skip|later|should_have), at`.
- `profiles`: `id, version, text, created_at`. One row per edit.
- `runs`: section 7.10.

Every user-scoped table carries `profile_id` with a single value in v1.

**Retention.** `editions`, `cards`, `also_happened`, `feedback`, `threads` and `profiles` are never deleted. `items` keep their metadata forever; `body` and `embedding` are cleared after 90 days to stay inside the free Postgres tier (roughly 300K items a year; cards carry their own text, so an old edition never depends on an item body).

---

## 10. Phases

**Phase 0, spike (recommended, one to two days).** Run ingest once over the whole map, cluster, classify, write cards for one edition, and render it as a static page in the mockup style. No feedback, no threads, no scheduling. Purpose: see a real edition before polishing anything, because the ranker's quality is the product and this is the cheapest way to judge it. Throwaway code; what it teaches goes into the v1 plan.

**Phase 1, v1.** Everything in sections 5 to 9 marked v1: scheduled pipeline, PWA feed, feedback, threads, breaking lane, run log. Done when Mihir has read it every morning for two weeks and stopped opening Instagram for news.

**Phase 2.** Newspaper view. Saturday movie card with TMDB/OMDb/IMDb consensus. Fixture card if not already in. Scrape adapters for the two or three scrape-only sources that matter most.

**Phase 3, later and out of scope here.** Multi-user: accounts, a topic-to-sources registry with LLM-assisted source discovery, per-user profiles, onboarding.

---

## 11. Left to the builder

- Exact prompts for classify, write, and thread-match (write them with the `prompt-writing` skill), and the JSON schemas.
- Clustering thresholds and the borderline-confirmation pass.
- The final-score formula and the feedback weight decay.
- Reading-time constants and the diversity caps (starting values in 5.1 and 7.5).
- Readability extraction library and the enrichment fetch budget.
- Reddit app registration and the adapter.
- PWA specifics (manifest, service worker scope, offline strategy).
- UI polish. The mockups set the structure; visual design is explicitly deferred. Before applying any of the installed design skills, ask Mihir, per his standing rule.
- Which `api`-kind sources ship in v1 versus phase 2.
- Whether the fixture card is v1.

---

## 12. Risks and how the design handles them

- **The ranker is mediocre.** Mitigated by the "Also happened" list (recall check), the edition log with reasons (debuggability), feedback weights, and the spike in phase 0 that shows an edition before anything else is built.
- **Cards hallucinate.** Mitigated by citation per depth, the rule that rich formats need data from cited items, enrichment of article bodies for the shortlist, and honesty about paywalled teasers.
- **Volume swings.** Budget is time, not count; floor of 8 cards; "Also happened" absorbs the rest.
- **Source rot.** Weekly health check; `enabled` flag; the run log.
- **Reddit or Google News change their access rules.** Both are isolated behind adapters; the map records the human homepage for every source so an alternative can be found.
- **GitHub Actions minutes.** Two-hourly ingest fits; if it doesn't, the Fly.io fallback is a configuration change, not a redesign.
- **Scope creep toward the newspaper view.** Phase 2, and the only v1 concession is structured payloads.

---

## 13. Open questions for Mihir

From the builder check on 2026-10-30, answered by Mihir the same day.

1. **Model pair and billing account.** Answer: Claude Code under his Max plan; Opus for writing ("Opus is fine to start with"). No API billing in v1. Classification also on Claude Code (cheaper model if selectable).
2. **Reddit script app.** Answer: yes, he will register one. Steps are in the implementation plan; credentials go to `~/.config/news-house/reddit.env`.
3. **Where the model calls run.** Answer: his Mac, whenever it is awake; the morning deadline does not matter to him. API backend kept for the public phase.

Also decided: "first build for myself on my Claude Code, run it for a few days, then see how to release to the public."


Calls I made that he should check while reading: edition at 07:30 IST (5.1); gnews items are teaser-only in v1 (section 6); Gemini embeddings even if Claude does the rest (section 8); repo under his personal GitHub account on Vercel Hobby (section 8); fixture card left to the builder (5.1); the starting reading-time constants and diversity caps (5.1, 7.5).
