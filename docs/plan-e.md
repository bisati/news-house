# News House, Hosting Implementation Plan (phase 3, Task 8)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The paper is readable on Mihir's phone anywhere, at a Vercel address, and his taps there (reactions, seen, read, tune, should-have) reach the Mac's pipeline.

**Architecture:** The Mac keeps building and rendering locally, as today. After each render, `newshouse publish` copies the rendered pages and a small site bundle into a separate `site` branch of the private GitHub repo and pushes it; Vercel deploys that branch. The page posts feedback to `/feedback`, which Vercel rewrites to a Python function that stores each tap, lightly checked, in a one-table Neon inbox. Before each build the Mac's `newshouse sync-feedback` pulls new inbox rows and records them through the existing `record_feedback`, which does the full check. Neon holds only the inbox; the main database stays local SQLite.

**Tech Stack:** Python 3.12+, SQLAlchemy 2 Core, psycopg 3 (already a dependency), git worktrees, Vercel Python functions; pytest.

**Spec:** `docs/design-v2.md` section 4.8 and section 10 answer 1 (Vercel plus Neon in phase 3). Mihir's choices on 2026-11-03: no privacy protection, a `site` branch deployed by Vercel, Neon for feedback only.

## Rulings made in this plan

1. **No access control, by Mihir's choice.** Because the feedback endpoint is public, the function accepts only small, well-formed bodies (at most 4 KB, a known action, ids as short strings, a payload object). The Mac's sync then rejects anything `record_feedback` rejects or that names a card or cluster it doesn't have. A junk row costs one inbox row and is dropped at sync.
2. **Vercel deploys the `site` branch, not `main`.** This deviates from D-007 ("Vercel deploys from main"). It keeps daily rendered pages out of `main`'s history. The branch is an orphan whose history is one commit per publish.
3. **The page keeps posting to `/feedback`.** `vercel.json` rewrites `/feedback` to `/api/feedback`, so the same page works with the Mac's `newshouse serve` and on Vercel. `/` redirects to `/latest.html`; the archive stays at `/index.html`.
4. **Sync is idempotent.** The inbox row id becomes the `Feedback.id`, so a row synced twice is recorded once. Synced rows are kept in Neon (marked with `synced_at`) for 30 days, then deleted by the sync.
5. **Publishing never fails a build.** A missing remote, a push failure or a missing Neon URL logs a warning in the tick's stats; the local page is unaffected.

## Global Constraints

- Work on branch `v2/hosting` off `main` (`f8cbc33`). One commit per task; messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Secrets only in `~/.config/news-house/*.env` (mode 600) and in Vercel's project settings. The Neon URL is `NEON_DATABASE_URL`. Never commit it, print it, or log it; logs name the host at most.
- Never commit `newshouse.db`, `profile.md` or `out/` to `main`. The `site` branch carries only rendered pages, fonts and the site bundle.
- No network and no model calls in tests. Tests use a temp SQLite file in place of Neon (the inbox code is SQLAlchemy Core, so it runs on both) and a temp bare git repo in place of GitHub.
- The 445 existing tests keep passing.

## Review Focus

- A Neon or GitHub outage at tick time: the build and local render still happen, and the tick records `publish: error` or `sync: error`. Test in Task 1 (`test_tick_survives_sync_failure`) and Task 3 (`test_tick_survives_publish_failure`).
- A forged tap (unknown action, unknown card id, 100 KB body, a tune with a bad payload): the function answers 400 or 413 for malformed bodies; anything it stores that the Mac can't record is dropped at sync and counted. Tests in Task 2 (`test_function_rejects_bad_bodies`) and Task 1 (`test_sync_drops_invalid_rows`).
- The same inbox row synced twice: one `Feedback` row. Test in Task 1 (`test_sync_is_idempotent`).
- A publish when nothing changed: no new commit and no push. Test in Task 3 (`test_publish_skips_when_unchanged`).

---

### Task 1: Neon inbox and sync

**Files:**
- Create: `newshouse/inbox.py`
- Modify: `newshouse/config.py` (`neon_database_url: str | None = None`), `newshouse/cli.py` (`inbox-init`, `sync-feedback`), `newshouse/tick.py` (sync before the build step)
- Test: `tests/test_inbox.py`, `tests/test_tick.py`

**Interfaces:**
- Produces in `newshouse/inbox.py`: `INBOX` (SQLAlchemy Core `Table("feedback_inbox", id text primary key, received_at timestamptz, body json/jsonb, synced_at timestamptz null)`), `inbox_engine(url: str) -> Engine` (accepts `postgres://` and `postgresql://`, normalises to `postgresql+psycopg://`), `init_inbox(engine) -> None` (create if missing), `sync_feedback(session, inbox_engine, *, profile_id: str, now: datetime, keep_days: int = 30) -> dict` returning `{"fetched", "recorded", "duplicate", "invalid"}`. It reads rows with `synced_at IS NULL` oldest first, records each through `record_feedback` with `Feedback.id` set to the inbox id and `at` set to `received_at`, drops a row whose card or cluster id is unknown or whose fields `record_feedback` rejects, sets `synced_at` on every fetched row, and deletes rows synced more than `keep_days` ago.
- `record_feedback` gains an optional `id: str | None = None`.
- CLI: `newshouse inbox-init` and `newshouse sync-feedback` (prints the counts as JSON); both exit 2 with a clear message when `NEON_DATABASE_URL` is unset.
- Tick: when `settings.neon_database_url` is set, run `sync_feedback` before deciding to build; any exception is logged, recorded as `out["sync"] = {"error": "<type>"}`, and the tick continues.

- [ ] **Step 1: Write the failing tests:** `test_inbox_url_normalised`, `test_sync_records_rows` (a worth on a known card and a tune with no ids become Feedback rows with the inbox ids and received times), `test_sync_is_idempotent`, `test_sync_drops_invalid_rows` (unknown card, unknown action, bad tune payload: counted invalid, marked synced, not recorded), `test_sync_prunes_old_rows`, `test_cli_requires_neon_url`, `test_tick_survives_sync_failure`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** as in Interfaces.
- [ ] **Step 4: Run** the full suite. Expected: all pass.
- [ ] **Step 5: Commit** `feat(inbox): Neon feedback inbox and sync into the local database`.

---

### Task 2: The site bundle and the Vercel function

**Files:**
- Create: `site/vercel.json`, `site/api/feedback.py`, `site/requirements.txt` (`psycopg[binary]>=3.1`), `site/README.md` (one paragraph: what deploys from this folder)
- Test: `tests/test_site_function.py`

**Interfaces:**
- `site/api/feedback.py` is self-contained (it does not import `newshouse`, since Vercel installs only `site/requirements.txt`). It defines `ACTIONS` (the seven actions, kept equal to `newshouse.feedback.ACTIONS` by a test), `check_body(raw: bytes) -> tuple[int, dict | None, str | None]` (status, parsed body or None, error), `store(conn, body: dict, *, now) -> str` (inserts into `feedback_inbox`, returns the id, a uuid4 hex), and a `handler(BaseHTTPRequestHandler)` class for Vercel's Python runtime: POST only (405 otherwise), `Content-Length` required and at most 4096 (413 above), JSON object with `action` in `ACTIONS`, `card_id` and `cluster_id` optional strings of at most 64 characters, `payload` an optional object; 204 on success, JSON errors otherwise. It connects with `os.environ["NEON_DATABASE_URL"]` per request and closes the connection; a database error answers 503 and stores nothing.
- `site/vercel.json`: rewrite `/feedback` to `/api/feedback`; redirect `/` to `/latest.html`; `Cache-Control: no-cache` on `*.html`; long cache on `/fonts/*`.

- [ ] **Step 1: Write the failing tests:** `test_function_actions_match_pipeline`, `test_function_accepts_good_bodies` (worth with card id; tune with payload and no ids), `test_function_rejects_bad_bodies` (no length, 5 KB, not JSON, a list, unknown action, an id of 65 characters, payload not an object), `test_function_stores_row` (with a fake connection object recording the SQL parameters), `test_vercel_json_rules`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.** Import the function module in tests by path (`importlib.util.spec_from_file_location`).
- [ ] **Step 4: Run** the full suite. Expected: all pass.
- [ ] **Step 5: Commit** `feat(site): Vercel bundle with the feedback function`.

---

### Task 3: Publish to the site branch

**Files:**
- Create: `newshouse/publish.py`
- Modify: `newshouse/config.py` (`publish_remote: str | None = None`, default unset; `publish_branch: str = "site"`; `publish_worktree: Path = ~/.cache/news-house/site`), `newshouse/cli.py` (`publish`), `newshouse/tick.py` (publish after a render)
- Test: `tests/test_publish.py`, `tests/test_tick.py`

**Interfaces:**
- `publish(out_dir: Path, *, repo: Path, remote: str, branch: str, worktree: Path, now: datetime) -> dict` returning `{"status": "pushed" | "unchanged" | "error", "commit": sha | None, "files": n}`. It creates or reuses a git worktree of `branch` at `worktree` (an orphan branch on first use), replaces its contents with: every `out/*.html` except files starting with `_`, `out/*.json`, `out/fonts/`, and the `site/` bundle copied to the worktree root; commits `publish: <edition date> <HH:MM IST>` with the repo's configured author when there are changes, and pushes `branch` to `remote`. Git runs through `subprocess` with explicit arguments; no shell strings.
- CLI: `newshouse publish` (uses `--out`, default `out`); exits 2 when `publish_remote` is unset.
- Tick: after a render, when `settings.publish_remote` is set, run `publish`; errors are logged and recorded as `out["publish"] = {"status": "error", "error": "<type>"}`.

- [ ] **Step 1: Write the failing tests** (temp repo with a temp bare remote): `test_publish_creates_orphan_site_branch` (the remote's `site` branch has `latest.html`, `fonts/`, `api/feedback.py`, `vercel.json`, and no `newshouse/` or `profile.md`), `test_publish_skips_when_unchanged`, `test_publish_excludes_underscore_files`, `test_cli_publish_requires_remote`, `test_tick_survives_publish_failure`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** as in Interfaces.
- [ ] **Step 4: Run** the full suite. Expected: all pass.
- [ ] **Step 5: Commit** `feat(publish): push rendered pages to the site branch`.

---

### Task 4: Docs, then go-live with Mihir (controller)

- [ ] **Step 1:** A subagent updates `README.md` ("Hosting": the flow, the three env settings, the commands, the public-endpoint note), `docs/flow.html` (Publish and Sync stages, change-log line) and `docs/first-run-notes.md` (this plan's rulings). Commit `docs: hosting`.
- [ ] **Step 2 (Mihir):** create a free Neon project and save its connection string to `~/.config/news-house/neon.env` as `NEON_DATABASE_URL=...` (mode 600).
- [ ] **Step 3 (controller):** `newshouse inbox-init`; set `PUBLISH_REMOTE=origin` in `~/.config/news-house/publish.env`; `newshouse publish`.
- [ ] **Step 4 (Mihir):** in Vercel, import `bisati/news-house`, set the production branch to `site`, the root directory to the repo root, and add `NEON_DATABASE_URL` as an environment variable.
- [ ] **Step 5 (controller):** open the Vercel address, post one tap from the page (or `curl` a `seen` for a real card id), run `newshouse sync-feedback`, and confirm the Feedback row exists locally. Report the address and the result.
