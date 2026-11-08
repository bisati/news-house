# News House v2, Phase 4 (content) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The paper matches what Mihir reads for: less Gurgaon, more startups, new technology, AI tools and product management. One story told five times becomes one post you can swipe through. Visuals that don't help go. A market tile is added, and the paper grows to up to 36 posts within about 20 minutes.

**Architecture:** Most of this is configuration and prompts: the profile, topic floors and caps, new topic slugs, new sources. There is one new pipeline stage, **stacks**, which runs at build time after scoring. It makes one cheap Haiku call that groups same-story clusters, and the writer fills a short line for each extra story. Selection treats a stack as one post. The page shows a stack's extra stories as a swipe strip inside the expanded post, reusing the deck carousel. The market tile follows the live-tile pattern: a snapshot at build time, a Vercel function for refreshes, and a 1-month sparkline on tap.

**Tech Stack:** Python 3.12+, SQLAlchemy 2, pydantic 2, Jinja2, httpx, pytest; Vercel Python function; headless Chrome (dev only).

**Spec:** Mihir's notes on the 4 November edition (below) and his answers on 2026-11-04. Where they differ from `docs/design-v2.md`, his notes win.

## Mihir's notes this plan implements (2026-11-04)

1. Too much Gurgaon and Delhi: 7 of 27 posts. 5 were one GRAP/AQI story, and 3 of those came in as separate breaking cards.
2. More on startups, new technology and technical advances, product management skills, and what is new in product management. It helps him in his work.
3. Many stories on one subject: take the important ones and put them in one post that swipes. Answer: **same story plus close follow-ups**, not a whole theme.
4. "AI" also means AI tools and capabilities (image, text, video), in the style of @evolving.ai. Answer: find web and newsletter sources that carry the same updates.
5. The Vertex AI bug post's table (test ids such as "Test B #10, #18") told him nothing.
6. The CBSE post's table had long sentences set in the large serif, which "looks jarring and scary".
7. "Should have been in" seemed to do nothing. The taps did arrive; the button shows no change after a tap.
8. Stories he marked "should have been in": How Figma's PMs use AI every day; Coursera revenue up 94% after the Udemy merger; upcoming Netflix Spanish series (Money Heist spin-offs); LinkedIn swapped out OpenAI models to keep server costs flat; ChatGPT catching up to Google in search.
9. More posts: up to 36 when there are good stories. Answer: **up to 36, about 20 minutes, only above the quality bar**.
10. A market tile: is the Indian market up or down; tap for the trend. Answer: **Nifty 50 and Sensex**, with a 1-month trend on tap.

## Rulings made in this plan

1. **Stacks are grouped by a model, not by embeddings.** Plan-d measured embeddings and found they can't tell two different Barça stories (0.84) from duplicate pollution reports (0.77). One Haiku call gets the headlines of the top 60 pool clusters with their primary topics. It returns groups whose members are *the same event or a direct follow-up of it*, plus a one-word reason. Each group must share a primary topic and has at most 6 members. The member with the highest score leads.
2. **A stack counts as one post**, against its lead's topic cap and the budget. Its reading time is the lead's plus 10 seconds per extra member. Its extra members get no card of their own and no "Also today" line.
3. **Breaking cards count toward topic caps** at build time. The breaking lane skips a candidate that is the same story as a breaking card already written today, using the same grouping call on those headlines only. Classify's breaking case 2 becomes "a GRAP stage *change* or a major closure", not each new AQI reading.
4. **A stack's extra stories are written briefly.** One writer call per stack, on Opus at `--effort low`, returns `{cluster_id, headline, line}` per extra member, using only that member's items. The same truth rule as cards applies: numbers in the line must appear in the member's brief. A failed or invalid call leaves the stack with headline-only rows, using the cluster's latest title.
5. **New topic slugs: `startups` and `ai-tools`.** `product-design` stays, relabelled "Product", and its meaning widens to PM craft, PM careers and product news. New floors and caps in `config/edition.yaml`:
   - `gurgaon-local`: min 0, max 2
   - `product-design`: min 2, max 4
   - `startups`: min 1, max 4
   - `ai-tools`: min 1, max 4
   - `edtech-competitors`: min 1, max 3
   - `cards.cap` 36, `budget_seconds` 1200
   - The rest stay as they are.
6. **The profile is edited, not replaced.** "Where I live" keeps Gurgaon but narrows it to same-day disruptions: GRAP stage changes, closures, metro. "What I want to hear early" adds startups and funding, new technology, AI tools and capabilities, PM craft and careers, and the five should-have examples as a short "stories I want" list. `profile.md` is gitignored, so the edit is applied to both clones' copies and to `profile.example.md` in a neutral form.
7. **Visual rules.**
   - A table, versus or before-after visual is allowed only when every value is at most 28 characters and reads on its own: no internal ids, test labels or ticket numbers. The writer prompt says so, and `catalogue.check_visual` rejects values over 28 characters, which falls back to the cover.
   - The table renderer sets values of 17 to 28 characters in the 17px sans body face, not the large serif.
   - The Vertex example and the CBSE example go into the writer prompt as "don't" cases, paraphrased.
8. **"Should have been in" shows "Noted ✓"** and stays disabled after a tap, including after a reload. The pressed state is kept in `localStorage` by cluster id, as "seen" is.
9. **Market tile.**
   - The Mac fetches Yahoo Finance's chart API (`query1.finance.yahoo.com/v8/finance/chart/%5ENSEI` and `%5EBSESN`, `range=1mo&interval=1d`) at build time and stores it in `Edition.live["market"]`. It was checked from the Mac on 2026-11-04 and needs no key.
   - The page refreshes it every 30 minutes through a new Vercel function, `site/api/market.py`. The function proxies the two symbols with a 5-minute cache header, so the browser never calls Yahoo directly (CORS).
   - `newshouse serve` gains the same `/api/market` route.
   - When a refresh fails, the tile keeps its build-time numbers and says "as of <time>".
   - The tile shows each index's level and day change in tomato or forest with an arrow; tapping it opens a 1-month SVG sparkline. Whether Yahoo answers requests from Vercel's servers is checked at go-live. If it doesn't, the function is dropped and the tile updates only with each 2-hourly publish.
10. **New sources** come from a verified research pass (done 2026-11-04, results in Task 3). Each is fetched and parsed before it is added, as `sources.yaml` already requires.

## Global Constraints

- Work on branch `v2/content` off `main` (`8022287`). One commit per task; messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- No new runtime dependencies. Never commit `newshouse.db`, `out/` or `profile.md`. Secrets only in `~/.config/news-house/*.env`.
- No model call in `render` or in any test, and no network call in tests (use httpx `MockTransport` or the existing fake backends).
- Claude Code headless flags are unchanged (`--tools ""`, `--system-prompt-file`, `--setting-sources project,local`, `--no-session-persistence`, `--output-format json`, `--json-schema`, optional `--effort low`).
- Design rules from plan-d stay:
  - colour tokens only; no shadows, gradients or emoji
  - tap targets of at least 44px; no text under 11px
  - a visual is at most 320px tall at widths of 430 or less
  - motion only in the reduced-motion block
- Schema changes are additive through `ensure_columns`; old editions re-render without a rebuild.
- The 519 existing tests keep passing.

## Review Focus

- **The grouping call returns junk:** unknown ids, a cluster in two groups, a group across topics, or a group over 6. Bad groups are dropped and the rest kept; a total failure means no stacks and the build carries on. Test `test_stacks_reject_bad_groups` (Task 4).
- **A stack whose lead is a breaking card written overnight:** the card keeps its rank-0 slot and gains the members. Test `test_stack_joins_breaking_lead` (Task 4).
- **A quiet day:** the higher cap and budget must not pull in stories below the noise floor; the card count can stay under 27. Test `test_quiet_day_stays_short` (Task 2).
- **Old editions (30 Oct, 3 Nov, 4 Nov) render** with no stacks and no market tile. Test `test_old_editions_render` (Task 5).
- **A failed market fetch** never fails a build, and a failed refresh keeps the build-time numbers. Tests in Task 7.

---

### Task 1: "Should have been in" shows it was noted

**Files:** `newshouse/static/edition.js`, `newshouse/static/edition.css`, `tests/test_page_js.py` (or the existing JS-text test file)

- [ ] On tap: the label becomes "Noted ✓", `aria-pressed="true"`, disabled. The cluster id is stored under `nh-should-have` in `localStorage` (try/catch), and the pressed state is restored on load.
- [ ] CSS for `.should-have[aria-pressed="true"]`: no underline, colour `var(--forest)`.
- [ ] Test: the JS contains the restore call and the label text; existing tests pass. Commit `fix(page): show that a should-have tap was noted`.

### Task 2: Profile, topics, floors and budget

**Files:** `config/edition.yaml`, `newshouse/classify.py` (`KNOWN_TOPICS`), `newshouse/llm/prompts/classify.system.md` (slugs, breaking case 2, topic meanings), `newshouse/present.py` (labels: `startups` "Startups", `ai-tools` "AI tools", `product-design` "Product"; colours: `startups` butter, `ai-tools` forest), `profile.example.md`, `tests/test_select.py`, `tests/test_classify.py`

- [ ] The yaml values are as in Ruling 5. The classify prompt defines `ai-tools` ("new AI tools, apps and capabilities a person can try: image, video, voice, text, agents; not model or API releases, which are ai-models") and `startups` ("startup launches, funding, shutdowns and founders, India and global"). It widens `product-design` to "product management craft, PM careers and hiring, product teams' practices, design".
- [ ] Breaking case 2 is reworded as in Ruling 3.
- [ ] Tests: `test_known_topics_include_new_slugs`, `test_quiet_day_stays_short` (12 clusters above the floor give 12 cards, not 36), `test_cap_36_fills_on_a_busy_day`.
- [ ] Commit `feat(topics): startups and ai-tools; less Gurgaon; up to 36 posts in 20 minutes`.
- [ ] **Controller, after merge:** apply the Ruling 6 profile edit to `~/mihir_ai/news-house/profile.md` and `~/mihir_ai/news-house-prod/profile.md`. The text is shown to Mihir first.

### Task 3: New sources

**Files:** `sources/sources.yaml`, `tests/test_sources.py` (if a sources lint test exists; otherwise one that loads the yaml and checks each new entry's keys)

- [ ] Add the verified feeds listed in the controller's dispatch (from the 2026-11-04 research). Each entry follows the file's keys (`topic`, `tier`, `kind`, `url`, `verified`, `last7d`, `latest`, `why`), uses topic `ai-tools`, `startups` or `product-design`, and is fetched and parsed by the implementer before it is added. Skip any that fail and report them.
- [ ] Commit `feat(sources): AI tools, startups and product feeds`.

### Task 4: Stacks in the pipeline

**Files:**
- Create: `newshouse/stacks.py`, `newshouse/llm/prompts/stacks.system.md`, `newshouse/llm/prompts/stack_lines.system.md`
- Modify: `newshouse/llm/schemas.py` (`STACK_GROUPS_SCHEMA`, `STACK_LINES_SCHEMA`), `newshouse/models.py` (`Card.stack` JSON, default `[]`), `newshouse/select.py`, `newshouse/build.py`, `newshouse/breaking.py`
- Test: `tests/test_stacks.py`, `tests/test_select.py`, `tests/test_build.py`, `tests/test_breaking.py`

**Interfaces:**
- `group_stacks(pool: list[ScoredCluster], titles: dict[str, str], backend, *, limit: int = 60) -> dict[str, list[str]]` returns lead id → member ids (members exclude the lead, in score order). It validates as Ruling 1 and returns `{}` on any call failure.
- `select_edition_v2(..., stacks: dict[str, list[str]] | None = None)`:
  - members are removed from the pool before step 3;
  - `est_seconds` for a lead adds 10 per member;
  - `Selection.stacks` holds the chosen leads' stacks.
- `write_stack_lines(lead_card, members: list[Cluster], backend) -> list[dict]`. `Card.stack` stores `[{cluster_id, headline, line, url, source}]`, where `url` and `source` come from the member's best item.
- In the breaking lane: `same_story(candidate_title, today_breaking_titles, backend) -> bool`, built on `group_stacks`.

- [ ] Tests:
  - `test_stacks_group_same_story` (fake backend)
  - `test_stacks_reject_bad_groups` (unknown id, duplicate member, cross-topic group, more than 6 members)
  - `test_stack_counts_as_one_post`
  - `test_stack_members_get_no_also_line`
  - `test_stack_joins_breaking_lead`
  - `test_breaking_cards_count_toward_caps`
  - `test_breaking_skips_same_story`
  - `test_stack_lines_truth_rule` (a number not in the brief gives a headline-only row)
- [ ] The build records `stats["stacks"] = {"groups": n, "members": m, "lines_failed": k}`.
- [ ] Commit `feat(stacks): one post per story, with follow-ups to swipe`.

### Task 5: Stacks on the page

**Files:** `newshouse/present.py`, `newshouse/templates/edition.html.j2`, `newshouse/static/edition.css`, `newshouse/static/edition.js`, `scripts/shot.py`, `scripts/sample_edition.py`, `tests/test_render.py`

- [ ] A collapsed post with a stack shows a quiet chip under the line: "+N more on this story".
- [ ] The expanded post adds a section, "More on this story", after the body. It is a swipe strip built from the deck carousel (scroll-snap, faded chevrons, dots under the strip). Each slide shows the source name, headline and line, plus "Read at <source>" linking out.
- [ ] Slides use the post's fill and ink. No visual on member slides.
- [ ] The sample edition gains one stacked post, and `shot.py` checks that the strip fits 320px at a width of 390.
- [ ] Tests: `test_stack_chip_and_strip_render`, `test_old_editions_render` (the 30 Oct, 3 Nov and 4 Nov fixtures, or their JSON, render with no stack markup).
- [ ] Commit `feat(page): stacked posts swipe through the rest of the story`.

### Task 6: Visuals that earn their place

**Files:** `newshouse/catalogue.py`, `newshouse/llm/prompts/write.system.md`, `newshouse/present.py` (a `value_class` helper), `newshouse/templates/edition.html.j2`, `newshouse/static/edition.css`, `tests/test_catalogue.py`, `tests/test_render.py`

- [ ] `check_visual` rejects table, versus and before-after values over 28 characters, with the message `"<visual> value over 28 characters"`.
- [ ] The prompt adds the readability rule and the two paraphrased "don't" examples (Ruling 7).
- [ ] Values of 17 to 28 characters render with class `v-long`: the 17px sans body face, weight 600.
- [ ] Tests: `test_long_table_value_rejected`, `test_mid_length_value_renders_small`.
- [ ] Commit `fix(visuals): no tables of long sentences or internal ids`.

### Task 7: Market tile

**Files:**
- Modify: `newshouse/live.py` (`fetch_market(client) -> dict | None`), `newshouse/build.py` (store it in `Edition.live["market"]`), `newshouse/serve.py` (`GET /api/market`), `newshouse/present.py`, the template, CSS and JS
- Create: `site/api/market.py` (self-contained, like `feedback.py`; GET only; `Cache-Control: public, s-maxage=300`), with `site/vercel.json` unchanged unless a rewrite is needed
- Test: `tests/test_live.py`, `tests/test_site_function.py`, `tests/test_render.py`

- [ ] The snapshot is `{"as_of": iso, "indices": [{"name": "Nifty 50", "symbol": "^NSEI", "level": float, "prev_close": float, "change_pct": float, "closes": [float, ...] (last 22), "dates": [iso, ...]}, …]}`.
- [ ] The tile shows two rows, name, level and ▲/▼ % change, with tomato for a fall and forest for a rise. Tapping it toggles the sparkline, an inline SVG with a min/max label, 280×64 at a width of 390.
- [ ] Refresh every 30 minutes from `data-src="/api/market"`. A failure keeps the numbers and shows "as of HH:MM".
- [ ] Tests:
  - `test_fetch_market_parses_yahoo` (MockTransport, using a trimmed real reply saved as a fixture)
  - `test_fetch_market_failure_is_none`
  - `test_market_function_proxies_and_caches` (fake upstream)
  - `test_market_tile_renders`
  - `test_market_tile_absent_without_data`
- [ ] Commit `feat(live): Nifty 50 and Sensex tile with a 1-month trend`.

### Task 8: Docs, then a real build (controller)

- [ ] A subagent updates the README (stacks, topics, market tile), `docs/flow.html` (the stacks stage, plus a change-log line) and `docs/first-run-notes.md` (these rulings). Commit `docs: phase 4 content`.
- [ ] **Controller:**
  - Rebuild today's edition in the dev clone against a copy of the prod database, then check: the stack count, Gurgaon posts at most 2, product, startup and AI-tools posts present, the card count, and `shot.py` clean at four widths, day and night.
  - Show Mihir the screenshots and the counts. Merge only on his word.
