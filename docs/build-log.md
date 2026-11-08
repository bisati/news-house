# Build log

One entry per task, appended in the same commit as the task's code.

Entry format:

```
## Task N: <name> · <date>
Implementer: <what was built and tested>
Reviewer: <verdict>
Follow-ups: <or "none">
```

## Task 1: Repository and project skeleton · 2026-10-30
Implementer: Created the repo skeleton (pyproject, gitignore, package, env and profile templates), `newshouse.config.Settings` (pydantic-settings, loads `~/.config/news-house/*.env` then environment) with cached `get_settings()`, and copied the spec and plan into `docs/`. `tests/test_config.py` checks the spec defaults (1 passed). Installed on Python 3.14.3 including fastembed 0.9.1.
Reviewer: Spec compliant. One Important finding (blank values in .env.example broke Settings) fixed with env_ignore_empty=True and a covering test; re-review clean.
Follow-ups: none

## Task 2: Database models and init-db · 2026-10-30
Implementer: Added `newshouse/models.py` (12 SQLAlchemy 2 tables, JSON columns, UTC-aware datetimes, `created_at` default, unique `(profile_id, date)` on editions) and `newshouse/db.py` (`get_engine`, `session_scope`, `init_db`, float32 `vec_to_bytes`/`bytes_to_vec`).
`tests/test_models.py` covers table creation, the edition uniqueness constraint, vector round-trip, and defaults/JSON/embedding persistence.
Reviewer: Spec compliant, approved; minors deferred (JSON columns need whole-value reassignment, SQLite FK pragma off, read-only arrays from bytes_to_vec).
Follow-ups: none

## Task 3: Feed fetching and item normalisation · 2026-10-30
Implementer: Added `newshouse/fetch/normalize.py` (`RawItem`, `canonical_url`, `item_id`, `normalize_entry` with HTML-stripped 1,500-char teasers, UTC-aware dates, gnews publisher and HN comments link in `raw`) and `newshouse/fetch/feeds.py` (`FetchResult`, `fetch_feed`: streamed capped read, conditional GET, 304/non-2xx/HTML/parse handling, never raises).
`tests/test_feeds.py` (14 tests) parses five realistic fixture files via pytest-httpx and real feedparser.
Reviewer: Spec compliant. One Important finding (one unparseable date failed the whole feed) fixed with a guarded date parser and tests; re-review clean. Minors deferred.
Follow-ups: none

## Task 4: Source loading and the ingest run · 2026-10-30
Implementer: Added `newshouse/sources.py` (`load_sources` merges the 265 entries into 258 specs by url with unioned topics; `sync_sources` upserts by url with sha1 ids, preserving enabled/etag/last_modified/last_ok_at), `newshouse/ingest.py` (`RunStats`, `ingest` with per-source savepoint and try/except isolation, stale marking at `stale_hours`, ItemSource links, Run row) and `newshouse/cli.py` (`init-db`, `sync-sources`, `ingest --kinds`). 9 new tests with a `session` fixture; full suite 32 passed under `-W error`. Real smoke run: 207 sources tried, 206 ok, 1 failed (barcauniversal.com, http 520), 16,205 new items (13,488 stale), 717 dup.
Reviewer: Spec compliant, approved. Savepoint isolation, dedupe and etag logic verified; minor coverage gaps deferred.
Follow-ups: first run pulls full feed archives (83% of new items are stale); downstream stages should ignore `stale`.

## Task 5: Reddit adapter · 2026-10-30
Implementer: Added `newshouse/fetch/reddit.py` (`RedditClient` with cached password/refresh-token grants, `fetch_listing` for both the `top` and `search` URL shapes, `fetch_top` and `subreddit_from_url` wrappers, `parse_reddit_url`; never raises, returns `reddit: no credentials` / `reddit: http <status>`), the six `reddit_*` settings, `ingest` dispatch for `kind == "reddit"` (lazy client or injected `reddit=`, "reddit" added to default kinds), `scripts/reddit_auth_once.py` and a README "Reddit" section. 11 tests in `tests/test_reddit.py`, all via `httpx_mock`.
Reviewer: Spec compliant, approved. Both URL shapes, token handling and failure isolation verified; hardening minors deferred.
Follow-ups: live smoke run needs Mihir's credentials in `~/.config/news-house/reddit.env`; no etag/conditional fetch for Reddit.

## Task 6: Embeddings · 2026-10-30
Implementer: Added `newshouse/embed.py` (`Embedder` lazy-loading fastembed BAAI/bge-small-en-v1.5 with cache in `~/.cache/news-house/fastembed`, float32 L2-normalised `(n, 384)` output; `text_for_item`; `embed_new_items` batching fresh non-stale unembedded items, flushing per batch). 3 tests in `tests/test_embed.py` use the real model; full suite 46 passed under `-W error`. Real smoke DB: 2,717 items embedded in 53.4s.
Reviewer: Spec compliant, approved. Lazy load, guarded normalisation and SQL-side filtering verified; minors deferred.
Follow-ups: none

## Task 7: LLM backend protocol, fake backend, Claude Code backend · 2026-10-30
Implementer: Added `newshouse/llm/` with `LLMError`, `LLMBackend` protocol and `get_backend` (api raises NotImplementedError), `FakeBackend` (list or callable, records calls) and `ClaudeCodeBackend` (headless `claude -p` with the fixed flags, temp system-prompt file always removed, bare-cwd guard, one retry then `LLMError` with stderr tail, usage/cost logged at DEBUG). `tests/bin/claude` is a fake executable; 5 tests in `tests/test_llm_backend.py`.
Reviewer: Spec compliant, approved. Exact argv, single retry, temp-file cleanup and stderr capture verified; minors deferred.
Follow-ups: none

## Task 8: Clustering · 2026-10-30
Implementer: Added `newshouse/cluster.py` (`group_by_similarity` union-find at 0.80 with borderline pairs 0.72-0.80 capped at 200; `confirm_borderline` in batches of 50 via haiku; `cluster_fresh_items` attaching groups to the existing cluster with most members, never merging or deleting clusters, creating sha1-id clusters otherwise), `newshouse/llm/schemas.py` (`SAME_EVENT_SCHEMA`) and `same_event.system.md`. 5 tests in `tests/test_cluster.py`; full suite 56 passed under `-W error`.
Reviewer: Spec compliant after one fix (cluster topics now updated when items join); grouping, borderline confirmation and attach-to-largest verified; minors deferred.
Follow-ups: pair lines carry item ids in the user prompt (`n. A (id): title || B (id): title`) so the model can echo ids; prompt file is not declared as package data (fine for editable install).

## Task 9: Classify and score · 2026-10-30
Implementer: Added `newshouse/profile.py` (`load_profile` versions profile.md into `Profile` rows, FileNotFoundError if missing), `newshouse/classify.py` (`feedback_examples`, `render_cluster_for_classify`, `classify_clusters` batched via haiku with validation: unknown story_type becomes plain, scores clamped 0..100, topics accepted only if all in the 14 known slugs, reason cut to 300, LLMError skips the batch), `CLASSIFY_SCHEMA` and `classify.system.md`. 10 tests in `tests/test_classify.py`.
Reviewer: Spec compliant, approved. Validation, batch isolation, latest-action feedback and prompt content verified; hardening minors deferred.
Follow-ups: thread context is not yet passed to the classifier, so `is_delta` is true unless the model says otherwise; `classify_clusters` takes an extra `profile_id` kwarg (default "mihir") for feedback lookup.

## Task 10: Threads · 2026-10-30
Implementer: Added `newshouse/threads.py` (`cluster_centroid`, `candidate_threads` at cosine 0.60 capped at 5, `match_threads` batched via haiku with non-candidate thread ids rejected, running-mean unit-length thread embeddings, saga/importance>=85 clusters open new threads, others get chapter 0, no LLM call when no candidates, LLMError leaves the batch for the next run; `close_quiet_threads` after 30 days), `THREAD_MATCH_SCHEMA` and `thread_match.system.md`. 10 tests in `tests/test_threads.py`.
Reviewer: Spec compliant after one fix (threads opened earlier in a run are now visible to later clusters); id validation, running mean and LLMError isolation verified; minors deferred.
Follow-ups: thread context is still not fed back to the classifier; clusters are matched only once (a cluster that later gains items keeps its first assignment); thread summary cap (2000) keeps the oldest text and drops the newest; a reply that omits a cluster finalises it as standalone/new instead of retrying; the 3 item titles shown are not ordered (should be most recent first); within one LLM batch, a thread opened by an earlier member is not a candidate for later members.

## Task 11: Scoring formula, feedback weights, and edition selection · 2026-10-30
Implementer: Added `newshouse/feedback.py` (`Weights`, `record_feedback` with action/target validation, `compute_weights` EWMA alpha 0.2 clamped to [-1, 1] over topics and distinct sources, resolving via card or cluster and skipping unresolved rows) and `newshouse/select.py` (`freshness`, `tier_bonus`, `final_score`, `est_seconds`, `expected_format`, pure `select_edition` with guaranteed pass, budget/cap/per-topic fill, floor pass, `also` capped at 25; `score_and_select` persists `final_score` on in-window scored, uncarded clusters). CLI: `feedback <card_id> <action>` and `feedback --cluster <id> <action>`. 16 tests in `tests/test_feedback.py` and `tests/test_select.py`.
Reviewer: Spec compliant after one fix (guaranteed pass now takes the qualifying cluster); formula, EWMA, selection passes and CLI verified; minors deferred.
Follow-ups: the floor pass ignores the time budget but still respects `per_topic_cap` and `card_cap`; the guaranteed pass counts against the budget but is not blocked by it; `score_and_select` skips clusters with no items.

## Task 12: Enrichment · 2026-10-30
Implementer: Added `newshouse/enrich.py` (`extract_body` via trafilatura, precision mode, None under 300 chars; `enrich_clusters` skipping items with a body, all-paywall items and items whose sources are all gnews/reddit/youtube/podcast/x/scrape/api, ordering by tier primary > early-signal > mainstream then newest, streaming fetch capped at `max_bytes`, 2xx + text/html only, per-fetch failures logged at WARNING under `newshouse.enrich`, one flush per cluster). Fixture `tests/fixtures/article.html`; 8 tests in `tests/test_enrich.py`.
Reviewer: Spec compliant, approved. Skip rules, ordering, byte cap and charset handling verified; test minors deferred.
Follow-ups: none

## Task 13: Card writing · 2026-10-30
Implementer: Added `newshouse/write.py` (pure `allowed_formats` and `validate_card` with per-format payload checks, `render_cluster_for_write` with 6,000-char body cap and thread section, `write_card` with one retry listing problems then an unverified format-A fallback citing the newest item; `cluster.carded` set on every path, card returned unsaved), `WRITE_SCHEMA`, and `write.system.md` / `house_style.md` prompts. 10 tests in `tests/test_write.py`.
Reviewer: Spec compliant after one fix (thread cards now receive earlier chapter titles and dates); validation, retry, fallback and prompts verified; hardening minors deferred.
Follow-ups: `write_card` raises ValueError for a cluster with no items; `read_chapters` must be supplied by the caller (default empty); fallback card has no `why`/`brief`. Reviewer minors: a reply missing keys escapes the retry (KeyError path); unhashable citation ids are not guarded; a primary-tier gnews source unlocks rich formats; the source line shows only the first source. D cards now get `earlier_chapters` (title/date/read) rendered and checked against the payload.

## Task 14: The daily build · 2026-10-30
Implementer: Added `newshouse/build.py` (`get_or_create_edition`, `build_edition` running profile, embed, cluster, classify, threads, select, enrich, write and also-happened stages inside one committed `Run(kind="build")` with per-stage counts and seconds, per-card isolation storing unverified format-A fallbacks counted as `cards_fallback`, `read_chapters` from other built editions, `--force` reset keeping breaking cards, `prune_old`) and the `build [--date] [--force]` CLI command. 7 tests in `tests/test_build.py`; full suite passes under `-W error`.
Reviewer: Spec compliant, approved. Stage order, idempotence, force semantics, per-card isolation and error-path durability verified; minors deferred.
Follow-ups: `build_edition` takes extra `client`, `embedder` and `date` arguments; a failed build rolls back its work but keeps an error Run row; `prune_old` is not yet called (Task 16); `_fallback` is imported from `newshouse.write`.

## Task 15: Static preview render · 2026-10-30
Implementer: Added `newshouse/render_static.py` (`edition_view` JSON-serialisable view with breaking cards first, topics, cited sources and counts; `render_edition` writing `<date>.html` and `<date>.json`), the standalone `newshouse/templates/edition.html.j2` (CSS variables with dark mode, formats A to F from payloads, C as inline SVG bars, depth dial in vanilla JS, inert footer, end card G, autoescape on) and the `render [--date] [--out out/]` CLI command. 5 tests in `tests/test_render.py`; full suite passes under `-W error`.
Reviewer: Spec compliant after one fix (feed URLs are scheme-checked before becoming links); escaping, ordering and chart rendering verified; minors deferred.
Follow-ups: templates are not declared as package data (fine for editable installs); the footer buttons and "saved" count are inert placeholders until the app exists; `render` errors via argparse when no edition exists for the date.

## Task 16: Breaking lane and the tick entry point · 2026-10-30
Implementer: Added `newshouse/breaking.py` (`run_breaking`: eligible, uncarded clusters at or above the threshold scored since the last breaking run, by importance, up to the daily cap counting breaking cards already on today's edition; enrich, write with isolated unverified fallback, rank 0, one `Run(kind="breaking")` with candidates/written/fallback/cap_reached, error Run plus re-raise on failure) and `newshouse/tick.py` (`tick`: mtime-gated source sync, ingest, embed, cluster, classify, threads, then build + render + `latest.html` if today is unbuilt and local time >= 06:00, else breaking; then close quiet threads and prune once per local day). CLI `breaking` and `tick [--out out/]` print JSON. 11 tests in `tests/test_breaking.py` and `tests/test_tick.py`.
Reviewer: Spec compliant, approved. Breaking window, cap, 06:00 local rule, sync gating and prune-once-a-day verified; minors deferred.
Follow-ups: `tick` runs embed/cluster/classify/threads before `build_edition`, which repeats them (idempotent, but not cheap as first written here: the repeated cluster stage re-asked the same top-200 borderline same-event pairs every time, about 4 Haiku calls and 3 minutes per pass; fixed in the final-review wave, C2); the candidate window is `scored_at >= last breaking run start`, so a cluster scored mid-run by a concurrent tick could be missed; a failed stage aborts the tick with no per-stage isolation; sync mtime check raises if the YAML is missing.

## Task 17: Source health check · 2026-10-30
Implementer: Added `newshouse/health.py` (`check_sources`: re-fetches every enabled source of kind rss/atom/youtube/podcast/hn/gnews without an etag, sets `last7d` and `last_ok_at` on success, reports `{checked, ok, failed, dead, stale30}`; dead = failed in this and the two previous health runs, or nothing newer than 30 days; writes `Run(kind="health")`; never touches `enabled`). `tick` runs it on Sunday (local) once per local day under `"health"`; CLI `health` prints the JSON. 3 new tests (2 in `tests/test_health.py`, 1 in `tests/test_tick.py`).
Reviewer: Spec compliant, approved. Three-run dead rule, 30-day rule and Sunday-once scheduling verified; minors deferred.
Follow-ups: Reddit sources are not checked (credentials, no conditional-GET path); a source with zero dated items counts as stale30; the three-run rule needs two earlier health runs, so a source cannot be dead-by-failure before the third weekly run.

## Task 18: launchd scheduling on the Mac · 2026-10-30
Implementer: Added the plist template, `scripts/tick.sh` (fetch/checkout/ff-pull of `NEWSHOUSE_BRANCH`, default main, then `newshouse tick --out out`), `install_launchd.sh` (creates the production clone and venv, renders and bootstraps the agent) and `uninstall_launchd.sh`; README section "Running on the Mac". Agent deliberately not installed until Task 20.
Reviewer: Spec compliant after one fix (plist placeholder tokens and git step isolation); production-clone design, idempotent install and profile seeding verified; minors deferred.
Follow-ups: staging smoke ingested ~230 feeds (about 5 minutes, 8:43 total) then failed in `tick` with `FileNotFoundError: profile file not found: profile.md` (gitignored, per-clone; the install script now seeds it) after a first attempt failed with `no such table: runs` on a fresh DB (`newshouse init-db` needed; the install script runs it). `main` has no CLI until Task 20, so install is deferred.

## Task 19: Postgres on Neon · 2026-10-30
Implementer: Added `scripts/migrate_sqlite_to_pg.py` (`migrate(from_url, to_url)` copies the 12 tables in dependency order with SQLAlchemy Core in batches of 1,000, `OR IGNORE` on SQLite and `ON CONFLICT DO NOTHING` on Postgres, returns per-table source/target counts; CLI exits non-zero on any mismatch), `tests/test_migrate.py` (SQLite to SQLite, all tables seeded, idempotent re-run) and the README section "Database". No Postgres was contacted.
Reviewer: Spec compliant after one fix (table order now satisfies the clusters→threads foreign key, enforced in the test); live Postgres verification parked until the Neon project exists.
Follow-ups: live Postgres verification and launchd switch deferred until the owner creates the Neon project

## Task 20: First real edition and acceptance · 2026-10-30
Implementer: Ran `newshouse tick` by hand on staging (Step 0 merge to main left to the owner) via the new `scripts/tick_debug.py` (DEBUG log to `out/`). 83 minutes wall clock, exit 0: 228 sources tried, 206 ok, 22 failed (21 Reddit "no credentials", 1 http 520); 808 new items; 1,609 clusters classified; edition of 23 cards (A 17, C 3, D 1, E 1, F 1), 0 unverified, 0 breaking, 25 "Also happened", 20 cards with a `why`; 447 Claude Code calls (22 Opus card writes), list-price estimate $3.18. Wrote `docs/first-run-notes.md` with numbers, failures, page observations and an empty "Mihir's read" section. No pipeline fixes were needed.
Reviewer: pending
Follow-ups: merge `build/plan-a` to main after owner review; Reddit credentials; Neon project; call volume far above plan on a backlog day (watch days 2 and 3); log the model name in `newshouse.llm` lines; format C chart label overlap; possible duplicate GRAP card plus chapter card.

## Final review · 2026-10-30
Reviewer (whole branch): four Critical and six Important findings before merge to main.
- C1: thread matching flushed its batch whenever a cluster had no candidates, so it made 381 calls for 1,608 clusters; now one call per chunk of 50 (threads from earlier chunks visible; same-chunk visibility an accepted gap).
- C2: borderline same-event pairs between two already-clustered items were re-asked on every build and tick; now only pairs with at least one unclustered item are asked.
- C3: single linkage at 0.80 built a 100-item catch-all (templated BCCI pages, Devanagari PIB releases, empty teasers); join threshold raised to 0.86, groups and clusters capped at 30 (greedy complete-linkage split), `Item.lang` set at ingest by a Devanagari script check and non-English items kept out of the clustering pool. On the staging pool the largest group drops from 100 to 13.
- C4: a primary-tier gnews source unlocked rich formats for a gnews-only cluster; gnews sources no longer count.
- I1: 23 of 37 Haiku calls carried 76-84K cache-creation tokens in a second request inside one invocation; Haiku calls now pass `--effort low` (reproduction numbers in the fix-wave report).
- I2: no usage accounting; the Claude Code backend now accumulates per-model tokens, cost, turns and API time, logs one INFO line per call, and build/tick record per-stage usage in `Run.stats["usage"]` (tick writes its own `Run(kind="tick")`).
- I3: thread candidate threshold raised from 0.60 to 0.70.
- I4: `tick` now commits after every stage, so a crash loses at most one stage.
- I5: `finished_at` and `built_at` use the wall clock; the injected `now` still dates editions and drives windows.
- I6: the write prompt renders at most 12 items (bodies, then tier, then recency) and notes the omitted count; citations are checked against shown items.
- Minors: the Claude Code cwd must be completely empty; classify and same-event prompts mark item text as data; first-run notes corrected (the 91-character headline was rejected and a valid 76-character one stored).
