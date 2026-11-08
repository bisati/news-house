# News House Pipeline Implementation Plan (Plan A of 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Python pipeline on Mihir's Mac that turns the 265-source map into one daily edition of ranked, personalised, cited news cards, persisted in a database and viewable as a static HTML preview, using Claude Code headless as the model backend.

**Architecture:** A `newshouse` CLI with one scheduled entry point (`tick`) that ingests feeds into Postgres/SQLite via SQLAlchemy, embeds and clusters fresh items locally, scores clusters with Haiku and writes cards with Opus through `claude -p`, selects an edition against a 15-minute budget, and renders it. The phone app (Plan B, Next.js on Vercel) reads the same tables; nothing in this plan depends on it.

**Tech Stack:** Python 3.12+ (3.14.3 installed), SQLAlchemy 2 (SQLite for tests and local, Postgres on Neon for prod via `DATABASE_URL`), feedparser, httpx, pydantic 2, fastembed (`BAAI/bge-small-en-v1.5`, 384-dim, ONNX, no torch), numpy, trafilatura, PyYAML, Jinja2, pytest. Claude Code CLI 2.1.314 as the LLM backend. launchd for scheduling.

**Spec:** `docs/superpowers/specs/2026-10-30-news-house-design.md` (copied into the repo as `docs/design.md` in Task 1; section numbers below refer to it).

**Scope split:** Plan A (this) = pipeline + static preview. Plan B (written after Plan A ships its first real edition) = the PWA: feed UI, feedback buttons, archive, saved list, `/log` page. The `feedback` table and the `newshouse feedback` command exist in Plan A so ranking can be trained from the terminal before the app exists.

## Global Constraints

- Repo: new private git repo at `~/news-house/`, remote `github.com/bisati/news-house`, commit email `81610063+bisati@users.noreply.github.com` (set at repo level).
- Secrets only in `~/.config/news-house/*.env` (mode 600) and Vercel env; never in the repo. `profile.md` is gitignored; `profile.example.md` is committed.
- GitHub is the source of truth. Work on branch `build/plan-a`; push after every task's commit. `main` is production: the Mac's tick pulls `main` before running; nothing is deployed any other way. Local runs on the branch with SQLite are staging.
- The build is documented in the repo: `docs/how-this-was-built.md` (the workflow and the agent roles) and `docs/build-log.md` (one entry per task: implementer summary, reviewer verdict, follow-ups). The executor appends to the build log at the end of every task, in the same commit as the task's code.
- LLM calls go through `newshouse/llm/backend.py`'s `LLMBackend` protocol; nothing else imports subprocess or an SDK.
- Claude Code invocation flags are exactly: `--model <haiku|opus> --tools "" --system-prompt-file <path> --setting-sources project,local --no-session-persistence --output-format json --json-schema <json>`, run from a fixed cwd that contains no `CLAUDE.md`, with `CLAUDE_CODE_RETRY_WATCHDOG=1`. Never `--resume`.
- Models: classification and thread matching on `haiku`; card writing on `opus`.
- Spec constants (section 5.1, 7.5, 7.8): budget 900 s; 35 s per A/E/F card, 50 s per B/C/D; cap 25 cards, floor 8; max 5 per topic; guaranteed-topic threshold importance ≥ 85; noise floor importance < 30; breaking threshold importance ≥ 90, max 3 per day; classify batch size 50; feedback examples 20 worth + 20 skip; cluster window 48 h; stale at first sight > 72 h; thread closes after 30 quiet days; bodies and embeddings cleared after 90 days.
- Every number, name, date on a card must come from a cited item (section 7.6, G10); a rich format (B to F) falls back to A when its payload can't be filled from cited items.
- Headline ≤ 90 characters. "Why it matters" is empty rather than generic.
- Google News (`gnews`) items are teaser-only; never enriched; format A only unless the cluster also contains a non-gnews item.
- Default `profile_id` is `"mihir"` everywhere.
- Python: `python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"`. If `fastembed`/`onnxruntime` has no wheel for the installed Python, `brew install python@3.12` and recreate the venv with it.

## Review Focus

1. A feed that returns HTML, a 5 MB body, or a 429 must not abort the run; the source is logged as failed and the rest continue (Task 4 test `test_ingest_continues_after_source_failure`).
2. An undated feed item (PIB, GitHub trending) must get `published_at = first_seen_at` and must not be marked stale (Task 3 test `test_undated_item_uses_first_seen`).
3. A day with fewer than 8 clusters above the noise floor must still build an edition with whatever exists, not fail (Task 11 test `test_select_below_floor_returns_all`).
4. A writer response whose cited item ids don't exist in the cluster must be rejected and retried once, then the card falls back to format A with only the headline and one line marked unverified (Task 13 test `test_write_rejects_unknown_citations`).
5. Running `build` twice on the same date must not create a second edition or duplicate cards (Task 14 test `test_build_is_idempotent_per_date`).

---

### Task 1: Repository and project skeleton

**Files:**
- Create: `pyproject.toml`, `README.md`, `.gitignore`, `newshouse/__init__.py`, `newshouse/config.py`, `tests/__init__.py`, `tests/test_config.py`, `docs/design.md` (copy of the spec), `docs/plan-a.md` (copy of this plan), `docs/how-this-was-built.md`, `docs/build-log.md`, `profile.md` (gitignored), `profile.example.md`, `.env.example`
- Move (already in folder): `sources/sources.yaml`, `sources/checkfeed.py`, `card-format-mockups.html` → `docs/card-format-mockups.html`

**Interfaces:**
- Produces: `newshouse.config.Settings` (pydantic-settings) with fields `database_url: str = "sqlite:///./newshouse.db"`, `profile_id: str = "mihir"`, `profile_path: Path = Path("profile.md")`, `sources_path: Path = Path("sources/sources.yaml")`, `claude_bin: str = "claude"`, `claude_cwd: Path = Path("~/.cache/news-house/claude-cwd").expanduser()`, `llm_backend: Literal["claude-code","api","fake"] = "claude-code"`, `tz: str = "Asia/Kolkata"`, `budget_seconds: int = 900`, `card_cap: int = 25`, `card_floor: int = 8`, `per_topic_cap: int = 5`, `guaranteed_threshold: int = 85`, `noise_floor: int = 30`, `breaking_threshold: int = 90`, `breaking_daily_cap: int = 3`, `classify_batch: int = 50`, `cluster_window_hours: int = 48`, `stale_hours: int = 72`. Loads `~/.config/news-house/*.env` then environment. `get_settings() -> Settings` cached.

- [ ] **Step 1: Initialise the repo and set identity**

Run in `~/news-house`: `git init -b main && git config user.email 81610063+bisati@users.noreply.github.com && git config user.name bisati`. Create `.gitignore` with `.venv/`, `*.db`, `__pycache__/`, `.env`, `out/`, `.pytest_cache/`, `profile.md`.

- [ ] **Step 2: Write `pyproject.toml`**

Project name `news-house`, package `newshouse`, `requires-python = ">=3.12"`, deps: `sqlalchemy>=2.0`, `pydantic>=2`, `pydantic-settings>=2`, `feedparser>=6`, `httpx>=0.27`, `pyyaml>=6`, `numpy>=1.26`, `fastembed>=0.3`, `trafilatura>=1.9`, `jinja2>=3.1`, `psycopg[binary]>=3.1`. Dev extra: `pytest>=8`, `pytest-httpx`, `freezegun`. Script entry: `newshouse = "newshouse.cli:main"`.

- [ ] **Step 3: Write the failing test** in `tests/test_config.py`

```python
def test_defaults_match_spec(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from newshouse.config import Settings
    s = Settings(_env_file=None)
    assert (s.budget_seconds, s.card_cap, s.card_floor, s.per_topic_cap) == (900, 25, 8, 5)
    assert (s.guaranteed_threshold, s.noise_floor, s.breaking_threshold, s.breaking_daily_cap) == (85, 30, 90, 3)
    assert s.classify_batch == 50 and s.cluster_window_hours == 48 and s.stale_hours == 72
    assert s.profile_id == "mihir"
```

- [ ] **Step 4: Create the venv, install, run the test to see it fail**

Run: `python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]" && pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: newshouse.config`

- [ ] **Step 5: Implement `newshouse/config.py`** as specified in Interfaces, then `pytest tests/test_config.py -v` → PASS

- [ ] **Step 6: Add docs and profile**

Copy the spec to `docs/design.md` and this plan to `docs/plan-a.md`; move `card-format-mockups.html` to `docs/`. Write `profile.md` from spec section 4's draft, verbatim, with a top line "Edit freely. Every edit is versioned on the next build."; write `profile.example.md` with the same section headings and placeholder text. Write `.env.example` listing every variable from `Settings` and the Reddit fields with blank values. Write `docs/how-this-was-built.md`: a short account of the process (brainstorm in conversation → design spec → builder check by a fresh agent → implementation plan → subagent-driven development, where each task is implemented by a fresh implementer agent and checked by a fresh reviewer agent before the next starts, then a whole-branch review), the LLM roles inside the product (same-event confirmer, classifier, thread matcher, card writer, each with its prompt file path), and a pointer to `docs/build-log.md`. Create `docs/build-log.md` with a header and the entry format: `## Task N: <name> · <date>` / `Implementer:` / `Reviewer:` / `Follow-ups:`. Write `README.md` with: what News House is (two paragraphs from the spec's intent), setup steps (venv, env files, `newshouse init-db`, `newshouse sync-sources`, `newshouse tick`), and the staging-vs-production rule.

- [ ] **Step 7: Commit, create the remote, start the working branch**

```bash
git add -A && git commit -m "chore: project skeleton, config, spec, source map"
gh repo create bisati/news-house --private --source=. --push
git checkout -b build/plan-a && git push -u origin build/plan-a
```

Every later task ends with `git push` after its commit.

---

### Task 2: Database models and `init-db`

**Files:**
- Create: `newshouse/models.py`, `newshouse/db.py`, `tests/test_models.py`

**Interfaces:**
- Produces: SQLAlchemy 2 declarative models in `newshouse/models.py` with these columns (types in parentheses; all tables also get `created_at` default now):
  - `Source(id: str pk, name: str, topics: JSON list[str], tier: str, kind: str, url: str unique, home: str|None, paywall: bool, enabled: bool=True, last_ok_at: datetime|None, last7d: int|None, etag: str|None, last_modified: str|None)`
  - `Item(id: str pk, title: str, url: str, canonical_url: str, teaser: str, body: str|None, author: str|None, published_at: datetime, first_seen_at: datetime, dated: bool, lang: str|None, topics: JSON list[str], stale: bool=False, embedding: LargeBinary|None, raw: JSON)`
  - `ItemSource(item_id fk, source_id fk)` composite pk
  - `Cluster(id: str pk, window_start: datetime, topics: JSON, story_type: str|None, importance: int|None, early: int|None, reason: str|None, breaking_eligible: bool=False, is_delta: bool=True, final_score: float|None, thread_id: str|None fk, chapter: int|None, breaking: bool=False, scored_at: datetime|None, carded: bool=False)`
  - `ClusterItem(cluster_id fk, item_id fk)` composite pk
  - `Thread(id: str pk, title: str, summary: str, opened_at: datetime, last_chapter_at: datetime, closed_at: datetime|None, embedding: LargeBinary|None, chapters: int=0)`
  - `Edition(id: str pk, profile_id: str, date: date, built_at: datetime|None, budget_seconds: int, cut_score: float|None, profile_version: int|None)` unique `(profile_id, date)`
  - `Card(id: str pk, edition_id fk, rank: int, cluster_id fk, thread_id: str|None, chapter: int|None, format: str, payload: JSON, headline: str, line: str, para: str, brief: str, why: str, est_seconds: int, cited_item_ids: JSON list[str], breaking: bool=False, unverified: bool=False)`
  - `AlsoHappened(edition_id fk, cluster_id fk, rank: int, line: str)` composite pk
  - `Feedback(id: str pk, profile_id: str, card_id: str|None, cluster_id: str|None, action: str, at: datetime)` where action ∈ `worth|skip|later|should_have`
  - `Profile(id: str pk, profile_id: str, version: int, text: str)`
  - `Run(id: str pk, kind: str, started_at: datetime, finished_at: datetime|None, status: str, stats: JSON, error: str|None)`
- `newshouse/db.py`: `get_engine(url: str | None = None)`, `session_scope()` context manager yielding a `Session`, `init_db(engine) -> None` (create_all). Embeddings are stored as `np.float32.tobytes()`; helpers `vec_to_bytes(np.ndarray) -> bytes` and `bytes_to_vec(bytes) -> np.ndarray` live in `newshouse/db.py`.

- [ ] **Step 1: Write the failing test** in `tests/test_models.py`

```python
def test_init_db_creates_all_tables(tmp_path):
    from newshouse.db import get_engine, init_db
    from sqlalchemy import inspect
    eng = get_engine(f"sqlite:///{tmp_path}/t.db"); init_db(eng)
    names = set(inspect(eng).get_table_names())
    assert {"sources","items","item_sources","clusters","cluster_items","threads","editions","cards","also_happened","feedback","profiles","runs"} <= names

def test_edition_unique_per_profile_date(tmp_path):
    # inserting two Edition rows with profile_id="mihir", date=2026-10-30 raises IntegrityError
```

- [ ] **Step 2: Run** `pytest tests/test_models.py -v` → FAIL (`newshouse.db` missing)
- [ ] **Step 3: Implement `newshouse/models.py` and `newshouse/db.py`** per Interfaces
- [ ] **Step 4: Run** `pytest tests/test_models.py -v` → PASS
- [ ] **Step 5: Commit** `git commit -am "feat(db): models and init_db"`

---

### Task 3: Feed fetching and item normalisation

**Files:**
- Create: `newshouse/fetch/__init__.py`, `newshouse/fetch/feeds.py`, `newshouse/fetch/normalize.py`, `tests/fixtures/feeds/{rss_dated.xml,atom_youtube.xml,rss_undated.xml,gnews.xml,html_not_feed.html}`, `tests/test_feeds.py`

**Interfaces:**
- Produces in `newshouse/fetch/normalize.py`: `@dataclass RawItem(title: str, url: str, guid: str|None, teaser: str, author: str|None, published_at: datetime|None, raw: dict)`; `canonical_url(url: str) -> str` (lowercase host, strip `utm_*`, `fbclid`, fragments, trailing slash); `item_id(source_url: str, raw: RawItem) -> str` = sha1 of canonical url, else guid, else `source_url + "|" + title`; `normalize_entry(entry: dict, kind: str) -> RawItem` (handles feedparser entries for rss/atom/youtube/podcast/hn/gnews; strips HTML from teaser; caps teaser at 1,500 chars).
- Produces in `newshouse/fetch/feeds.py`: `@dataclass FetchResult(ok: bool, items: list[RawItem], etag: str|None, last_modified: str|None, status: int|None, error: str|None)`; `fetch_feed(url: str, *, kind: str, etag: str|None=None, last_modified: str|None=None, client: httpx.Client, max_bytes: int = 3_000_000, timeout: float = 20.0) -> FetchResult`. Browser user agent. Conditional GET (304 → `ok=True, items=[]`). Streams and stops at `max_bytes` (parses what it has). HTML body → `ok=False, error="html"`. Never raises on network/parse errors.

- [ ] **Step 1: Write the failing tests** in `tests/test_feeds.py` (use `pytest-httpx` to serve fixtures)

```python
def test_rss_dated_items_parsed(httpx_mock): ...  # 3 items, published_at set, teaser html-stripped
def test_undated_item_uses_first_seen(httpx_mock): ...  # rss_undated.xml → published_at is None in RawItem (caller sets first_seen)
def test_conditional_get_304_returns_ok_empty(httpx_mock): ...
def test_html_response_is_failure_not_exception(httpx_mock): ...  # html_not_feed.html → ok False, error "html"
def test_oversize_body_is_capped(httpx_mock): ...  # 4 MB body, max_bytes=100_000 → returns without raising
def test_canonical_url_strips_tracking(): assert canonical_url("https://X.com/a/?utm_source=t#frag") == "https://x.com/a"
def test_gnews_entry_keeps_publisher(): ...  # raw["publisher"] set from <source>
```

- [ ] **Step 2: Run** `pytest tests/test_feeds.py -v` → FAIL
- [ ] **Step 3: Implement `normalize.py` then `feeds.py`** per Interfaces (feedparser on the fetched bytes; youtube entries use `media_description` as teaser; gnews `<source>` element → `raw["publisher"]`, `raw["publisher_domain"]`)
- [ ] **Step 4: Run** `pytest tests/test_feeds.py -v` → PASS
- [ ] **Step 5: Commit** `git commit -am "feat(fetch): feed fetcher and item normalisation"`

---

### Task 4: Source loading and the ingest run

**Files:**
- Create: `newshouse/sources.py`, `newshouse/ingest.py`, `newshouse/cli.py`, `tests/test_sources.py`, `tests/test_ingest.py`

**Interfaces:**
- `newshouse/sources.py`: `load_sources(path: Path) -> list[dict]` (parses YAML; merges entries sharing a `url` into one with the union of `topic`s, so the 7 cross-topic duplicates become one source with two topics); `sync_sources(session, specs: list[dict]) -> int` (upsert by url; `id` = sha1(url)[:16]; `enabled` stays as in DB if row exists; returns count).
- `newshouse/ingest.py`: `ingest(session, *, now: datetime, client: httpx.Client, kinds: set[str] = {"rss","atom","youtube","podcast","hn","gnews"}) -> RunStats` where `RunStats` is a pydantic model `{sources_tried: int, sources_ok: int, sources_failed: dict[str,str], items_new: int, items_dup: int, items_stale: int}`. For each enabled source of an ingested kind: `fetch_feed`, upsert items (existing id → add `ItemSource` row only), set `published_at = raw.published_at or now`, `dated = raw.published_at is not None`, `stale = dated and (now - published_at) > stale_hours`, `topics = source.topics`, update `etag/last_modified/last_ok_at`. Wrap each source in try/except; failures go to `sources_failed`. Writes a `Run(kind="ingest")` row with `stats`.
- `newshouse/cli.py`: argparse `newshouse` with subcommands added task by task; this task adds `init-db`, `sync-sources`, `ingest [--kinds ...]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sources.py
def test_load_sources_merges_duplicate_urls(tmp_path): ...  # two entries same url, topics a and b → one spec with topics ["a","b"]
def test_sync_sources_upserts(session): ...  # second sync doesn't duplicate; 265 real entries → 258 rows
# tests/test_ingest.py
def test_ingest_stores_items_and_item_sources(session, httpx_mock): ...
def test_ingest_continues_after_source_failure(session, httpx_mock): ...  # one source 500, one ok → items_new from the ok one, sources_failed has the url
def test_stale_marking_uses_72h(session, httpx_mock): ...  # item dated 80h ago → stale True; 70h → False
def test_same_url_from_two_sources_is_one_item(session, httpx_mock): ...  # 1 item, 2 item_sources
```

Add `tests/conftest.py` with a `session` fixture (SQLite in `tmp_path`, `init_db`).

- [ ] **Step 2: Run** `pytest tests/test_sources.py tests/test_ingest.py -v` → FAIL
- [ ] **Step 3: Implement `sources.py`, `ingest.py`, `cli.py`** per Interfaces
- [ ] **Step 4: Run** → PASS. Then a real smoke: `newshouse init-db && newshouse sync-sources && newshouse ingest` against `sqlite:///./newshouse.db`; expected: `items_new` in the hundreds, `sources_failed` listing only reddit/api/x/scrape kinds (not ingested) and a handful of dead feeds.
- [ ] **Step 5: Commit** `git commit -am "feat(ingest): source sync and ingest run"`

---

### Task 5: Reddit adapter

**Files:**
- Create: `newshouse/fetch/reddit.py`, `tests/test_reddit.py`, `scripts/reddit_auth_once.py`
- Modify: `newshouse/ingest.py` (dispatch `kind == "reddit"` to the adapter), `newshouse/config.py` (fields `reddit_client_id`, `reddit_client_secret`, `reddit_username`, `reddit_password`, `reddit_refresh_token`, `reddit_user_agent`, all `str|None`)

**Interfaces:**
- `newshouse/fetch/reddit.py`: `class RedditClient(settings, http: httpx.Client)` with `token() -> str` (password grant if `reddit_password` set, else refresh-token grant; cached until 55 min), and `fetch_top(subreddit: str, *, t: str = "day", limit: int = 25) -> FetchResult` calling `https://oauth.reddit.com/r/{sub}/top?t={t}&limit={limit}&raw_json=1` with `Authorization: bearer` and the configured user agent, mapping each post to `RawItem(title, url=permalink, guid=name, teaser=selftext[:1500] or link url, author, published_at=created_utc)`; `subreddit_from_url(url: str) -> str` parses `/r/<sub>/` from the YAML `url`. If no credentials are configured, `fetch_top` returns `ok=False, error="reddit: no credentials"`.
- `scripts/reddit_auth_once.py`: one-time browser flow for accounts with 2FA; prints a refresh token to paste into `~/.config/news-house/reddit.env`.

**Mihir's one-time steps (recorded here so the implementer can put them in README):**
1. Log in to Reddit, open `https://www.reddit.com/prefs/apps`, click "create another app…".
2. Name `news-house`, type **script**, redirect URI `http://localhost:8080`, create.
3. Copy the client id (the string under the app name) and the secret into `~/.config/news-house/reddit.env` as `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, plus `REDDIT_USERNAME`, `REDDIT_PASSWORD` (no 2FA) or `REDDIT_REFRESH_TOKEN` (2FA, via `scripts/reddit_auth_once.py`), and `REDDIT_USER_AGENT="macos:news-house:0.1 (by /u/<username>)"`. `chmod 600` the file.

- [ ] **Step 1: Write the failing tests** (`httpx_mock` for token and listing endpoints)

```python
def test_password_grant_token_cached(httpx_mock, settings_with_reddit): ...  # two fetch_top calls → one token request
def test_fetch_top_maps_posts(httpx_mock, settings_with_reddit): ...  # 2 posts → 2 RawItems, url is permalink, published_at from created_utc
def test_no_credentials_is_failure_not_exception(settings_without_reddit): ...
def test_ingest_dispatches_reddit_kind(session, httpx_mock, settings_with_reddit): ...  # a reddit source in DB → items stored
```

- [ ] **Step 2: Run** `pytest tests/test_reddit.py -v` → FAIL
- [ ] **Step 3: Implement** `reddit.py`, the ingest dispatch, the config fields, and `scripts/reddit_auth_once.py` (authorization-code flow with `duration=permanent`, scope `read`, local HTTP listener on 8080)
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `git commit -am "feat(fetch): reddit adapter via OAuth script app"`

---

### Task 6: Embeddings

**Files:**
- Create: `newshouse/embed.py`, `tests/test_embed.py`

**Interfaces:**
- `newshouse/embed.py`: `class Embedder` with `__init__(model: str = "BAAI/bge-small-en-v1.5")`, `embed(texts: list[str]) -> np.ndarray` (shape `(n, 384)`, L2-normalised, float32); `embed_new_items(session, embedder: Embedder, *, batch: int = 128) -> int` embeds every `Item` with `embedding IS NULL AND stale = False` using `title + "\n" + teaser[:500]`, stores via `vec_to_bytes`, returns count. `text_for_item(item) -> str` is the single place that defines the embedded text.

- [ ] **Step 1: Write the failing tests**

```python
def test_embed_shape_and_norm(): ...  # 3 texts → (3, 384); each row norm ≈ 1.0
def test_similar_titles_closer_than_different(): ...  # cos("Google ships Gemini 3 Flash", "Gemini 3 Flash released by Google") > cos(first, "Barcelona beat Girona 2-1")
def test_embed_new_items_skips_stale_and_done(session): ...
```

- [ ] **Step 2: Run** → FAIL. (If fastembed fails to import on Python 3.14, follow the Global Constraints fallback before continuing.)
- [ ] **Step 3: Implement `embed.py`** per Interfaces
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `git commit -am "feat(embed): local fastembed embeddings"`

---

### Task 7: LLM backend protocol, fake backend, Claude Code backend

**Files:**
- Create: `newshouse/llm/__init__.py`, `newshouse/llm/backend.py`, `newshouse/llm/fake.py`, `newshouse/llm/claude_code.py`, `tests/bin/claude` (fake executable), `tests/test_llm_backend.py`

**Interfaces:**
- `newshouse/llm/backend.py`: `class LLMError(Exception)`; `class LLMBackend(Protocol): def complete_json(self, *, system: str, user: str, schema: dict, model: str) -> dict: ...`; `get_backend(settings) -> LLMBackend` (by `settings.llm_backend`).
- `newshouse/llm/fake.py`: `class FakeBackend(responses: list[dict] | Callable[[str, str, dict, str], dict])` returning canned dicts in order and recording `calls: list[dict(system, user, schema, model)]`.
- `newshouse/llm/claude_code.py`: `class ClaudeCodeBackend(bin: str, cwd: Path, timeout_s: int = 600)` implementing the protocol: writes `system` to a temp file; runs `[bin, "-p", "--model", model, "--tools", "", "--system-prompt-file", f, "--setting-sources", "project,local", "--no-session-persistence", "--output-format", "json", "--json-schema", json.dumps(schema)]` with `input=user`, `cwd=cwd` (created if missing, must contain no `CLAUDE.md`), `env={**os.environ, "CLAUDE_CODE_RETRY_WATCHDOG": "1"}`; parses stdout JSON; returns `structured_output`. If `is_error` or `structured_output` missing, retries once with `user + "\n\nYour previous reply was not valid: <reason>. Reply with JSON matching the schema only."`; then raises `LLMError`. Logs `usage` and `total_cost_usd` from the envelope at debug level.

- [ ] **Step 1: Write the fake executable** `tests/bin/claude` (shell script): reads stdin, prints the JSON file named by `$FAKE_CLAUDE_REPLY` (or `{"is_error":true,"result":"boom"}` if `$FAKE_CLAUDE_FAIL=1`), and appends its argv to `$FAKE_CLAUDE_LOG`. `chmod +x`.

- [ ] **Step 2: Write the failing tests**

```python
def test_claude_code_passes_exact_flags(tmp_path, monkeypatch): ...  # argv log contains the flags from Global Constraints in order; "--resume" absent
def test_claude_code_returns_structured_output(tmp_path, monkeypatch): ...
def test_claude_code_retries_once_then_raises(tmp_path, monkeypatch): ...  # FAKE_CLAUDE_FAIL=1 → 2 invocations, LLMError
def test_fake_backend_records_calls(): ...
```

- [ ] **Step 3: Run** `pytest tests/test_llm_backend.py -v` → FAIL
- [ ] **Step 4: Implement** `backend.py`, `fake.py`, `claude_code.py` per Interfaces
- [ ] **Step 5: Run** → PASS. Then one live smoke (counts against the Max plan, a few hundred tokens): `python -c "from newshouse.llm.claude_code import ClaudeCodeBackend as B; print(B('claude', __import__('pathlib').Path('~/.cache/news-house/claude-cwd').expanduser()).complete_json(system='Reply in JSON.', user='Return {\"ok\": true}', schema={'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok']}, model='haiku'))"` → prints `{'ok': True}`.
- [ ] **Step 6: Commit** `git commit -am "feat(llm): backend protocol, fake and claude-code backends"`

---

### Task 8: Clustering

**Files:**
- Create: `newshouse/cluster.py`, `newshouse/llm/schemas.py` (starts here, grows in later tasks), `newshouse/llm/prompts/same_event.system.md`, `tests/test_cluster.py`

**Interfaces:**
- `newshouse/llm/schemas.py`: `SAME_EVENT_SCHEMA = {"type":"object","properties":{"pairs":{"type":"array","items":{"type":"object","properties":{"a":{"type":"string"},"b":{"type":"string"},"same":{"type":"boolean"}},"required":["a","b","same"]}}},"required":["pairs"]}`.
- `newshouse/cluster.py`: `group_by_similarity(ids: list[str], vecs: np.ndarray, *, hi: float = 0.80, lo: float = 0.72) -> tuple[list[set[str]], list[tuple[str,str]]]` returns union-find groups for pairs with cosine ≥ hi, and the borderline pairs in `[lo, hi)` not already joined; `confirm_borderline(pairs, titles: dict[str,str], backend, model="haiku") -> set[tuple[str,str]]` asks the model (batches of 50 pairs, prompt file `same_event.system.md`) and returns the pairs marked same; `cluster_fresh_items(session, backend, *, now: datetime, window_hours: int = 48) -> list[Cluster]`: takes non-stale embedded items with `published_at ≥ now − window` that are not yet in any cluster, groups them (merging into existing clusters in the window when an item joins one), creates `Cluster` rows (`id` = sha1 of sorted item ids [:16], `topics` = union of item topics, `window_start = now − window`) and `ClusterItem` rows; returns the new clusters.

- [ ] **Step 1: Write the failing tests**

```python
def test_group_by_similarity_joins_near_duplicates(): ...  # 4 synthetic unit vectors: two at cos 0.95 join; one at 0.5 alone; borderline pair at 0.75 returned
def test_confirm_borderline_uses_backend_and_schema(): ...  # FakeBackend returns same=True for one pair → that pair in result; call used model "haiku" and SAME_EVENT_SCHEMA
def test_cluster_fresh_items_creates_rows_and_merges(session): ...  # 3 items, two similar → 2 clusters; re-run with a 4th similar item → joins existing cluster, no new cluster for it
```

- [ ] **Step 2: Run** → FAIL
- [ ] **Step 3: Implement** per Interfaces. Write `same_event.system.md` with the `prompt-writing` skill: input is a numbered list of title pairs; output JSON only; "same" means the same real-world event, not the same topic.
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `git commit -am "feat(cluster): similarity clustering with borderline confirmation"`

---

### Task 9: Classify and score

**Files:**
- Create: `newshouse/classify.py`, `newshouse/llm/prompts/classify.system.md`, `newshouse/profile.py`, `tests/test_classify.py`
- Modify: `newshouse/llm/schemas.py` (add `CLASSIFY_SCHEMA`)

**Interfaces:**
- `newshouse/profile.py`: `load_profile(session, settings) -> Profile` reads `profile.md`; if its text differs from the latest `Profile` row for `profile_id`, inserts a new row with `version + 1`; returns the current row.
- `CLASSIFY_SCHEMA`: `{"results": [{"cluster_id": str, "story_type": enum["launch","number","saga","debate","rule_change","plain","fixture","noise"], "topics": [str], "importance": int 0..100, "early": int 0..100, "reason": str, "breaking_eligible": bool, "is_delta": bool}]}` with `required` on every field.
- `newshouse/classify.py`: `feedback_examples(session, *, n: int = 20) -> tuple[list[str], list[str]]` (last n worth-or-later headlines, last n skip headlines, from `Feedback` joined to `Card`); `render_cluster_for_classify(cluster, items) -> str` (cluster id, topics, source names and tiers, up to 5 titles with teasers truncated to 300 chars, published times); `classify_clusters(session, backend, *, profile_text: str, batch: int = 50, model: str = "haiku") -> int` scores every cluster with `scored_at IS NULL`, writes `story_type, topics, importance, early, reason, breaking_eligible, is_delta, scored_at`; the system prompt is `classify.system.md` + the profile + the feedback examples; returns count scored. Clusters whose id is missing from a response are left unscored (retried next run).

- [ ] **Step 1: Write the failing tests**

```python
def test_classify_batches_of_50_and_writes_scores(session): ...  # 120 unscored clusters + FakeBackend → 3 calls; all rows scored with the fake values
def test_classify_system_prompt_contains_profile_and_examples(session): ...  # FakeBackend.calls[0]["system"] contains a profile sentence and a worth-it headline
def test_profile_versioning(session, tmp_path): ...  # same text twice → one row; changed text → version 2
def test_missing_cluster_in_response_stays_unscored(session): ...
```

- [ ] **Step 2: Run** → FAIL
- [ ] **Step 3: Implement** per Interfaces. Write `classify.system.md` with the `prompt-writing` skill; it must define `importance` as "how much Mihir would regret not knowing this today, given the profile", `early` as "primary or early-signal only, not yet in mainstream", require a one-line `reason`, list the breaking-eligible types from spec 7.8, and define `is_delta` as "new information versus what the thread already covered" (true when no thread context is given).
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `git commit -am "feat(classify): cluster scoring against the profile"`

---

### Task 10: Threads

**Files:**
- Create: `newshouse/threads.py`, `newshouse/llm/prompts/thread_match.system.md`, `tests/test_threads.py`
- Modify: `newshouse/llm/schemas.py` (add `THREAD_MATCH_SCHEMA = {"matches":[{"cluster_id": str, "thread_id": str|null}]}`)

**Interfaces:**
- `newshouse/threads.py`: `cluster_centroid(session, cluster) -> np.ndarray`; `candidate_threads(session, centroid, *, now, min_cos: float = 0.60) -> list[Thread]` over threads with `closed_at IS NULL`; `match_threads(session, backend, *, now: datetime, model: str = "haiku") -> int` for scored clusters with `thread_id IS NULL and chapter IS NULL`: if candidates exist, ask the model (batch of 50, titles of cluster vs each candidate's title and summary) and set `thread_id`, `chapter = thread.chapters + 1`, bump `thread.chapters`, `last_chapter_at`; if none matched and (`story_type == "saga"` or `importance >= 85`), open a new `Thread(title = best item title, summary = reason, embedding = centroid, chapters = 1)` and set `chapter = 1`; otherwise set `chapter = 0` (standalone). Returns clusters processed. `close_quiet_threads(session, *, now, days: int = 30) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
def test_matched_cluster_gets_next_chapter(session): ...  # thread with chapters=3 and close centroid; FakeBackend says match → chapter 4, thread.chapters 4
def test_unmatched_saga_opens_thread(session): ...
def test_unmatched_plain_low_importance_is_standalone(session): ...  # chapter 0, no thread
def test_close_quiet_threads_after_30_days(session): ...
```

- [ ] **Step 2: Run** → FAIL
- [ ] **Step 3: Implement** per Interfaces; write `thread_match.system.md` with the `prompt-writing` skill.
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `git commit -am "feat(threads): storyline matching and chapters"`

---

### Task 11: Scoring formula, feedback weights, and edition selection

**Files:**
- Create: `newshouse/feedback.py`, `newshouse/select.py`, `tests/test_feedback.py`, `tests/test_select.py`
- Modify: `newshouse/cli.py` (add `feedback <card_id> <worth|skip|later|should_have>` and `feedback --cluster <cluster_id> should_have`)

**Interfaces:**
- `newshouse/feedback.py`: `@dataclass Weights(topic: dict[str,float], source: dict[str,float])`; `compute_weights(session, *, profile_id: str, alpha: float = 0.2) -> Weights`: iterate `Feedback` in `at` order; reward `r = +1` for worth/later/should_have, `−1` for skip; for each topic of the card's cluster and each source of its items: `w = clamp(w + alpha*(r − w), −1, 1)`; `record_feedback(session, *, profile_id, action, card_id=None, cluster_id=None, at) -> Feedback`.
- `newshouse/select.py`: `freshness(age_hours: float) -> float` = 1.0 if ≤ 24, 0.8 if ≤ 48, else 0.5; `tier_bonus(best_tier: str) -> int` = 5 primary, 3 early-signal, 0 mainstream; `final_score(*, importance: int, age_hours: float, n_sources: int, best_tier: str, topic_w: float, source_w: float, chapter: int|None, is_delta: bool) -> float` = `min(importance, 40 if (chapter and chapter >= 2 and not is_delta) else 100) * freshness + 5*min(n_sources−1, 4) + tier_bonus + 10*topic_w + 5*source_w`; `est_seconds(format: str) -> int` = 50 for B/C/D else 35; `@dataclass Selection(selected: list[str], also: list[str], cut_score: float|None)`; `select_edition(scored: list[ScoredCluster], *, budget_seconds=900, cap=25, floor=8, per_topic_cap=5, guaranteed_threshold=85, noise_floor=30) -> Selection` where `ScoredCluster` is a dataclass `(id, importance, final_score, topics: list[str], story_type, expected_format: str)`; algorithm: drop `importance < noise_floor` and `story_type == "noise"`; sort by `final_score` desc; first pass takes the top cluster of every topic that has one with `importance ≥ guaranteed_threshold`; second pass fills in score order respecting `per_topic_cap`, the running `est_seconds` sum ≤ budget, and `cap`; if fewer than `floor` were selected, keep taking in score order ignoring the budget until `floor` or the list ends; everything remaining above the noise floor becomes `also` (max 25); `cut_score` = lowest selected score. `expected_format` is a cheap guess from `story_type` (launch→B, number→C, chapter≥2→D, debate→E, rule_change→F, else A) used only for the time estimate before writing. `score_and_select(session, *, now, settings) -> Selection` glues `compute_weights`, `final_score` (persisting `final_score` on each cluster) and `select_edition` over clusters scored in the window and not yet carded.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_feedback.py
def test_ewma_weights_move_toward_reward(session): ...  # one worth on topic ai-models → 0.2; then a skip → 0.2 + 0.2*(-1-0.2) = -0.04
def test_weights_clamped(session): ...
# tests/test_select.py
def test_final_score_formula_values(): assert final_score(importance=80, age_hours=10, n_sources=3, best_tier="primary", topic_w=0.5, source_w=0, chapter=None, is_delta=True) == 80*1.0 + 10 + 5 + 5
def test_thread_without_delta_capped_at_40(): ...
def test_select_respects_budget_and_cap(): ...  # 40 clusters × 35s → 25 selected (900/35 = 25.7, cap 25)
def test_select_per_topic_cap(): ...  # 10 high clusters same topic → 5 selected from it
def test_guaranteed_topic_gets_a_card(): ...  # low-scoring topic with one importance-90 cluster → included
def test_select_below_floor_returns_all(): ...  # 5 clusters above noise → all 5 selected, also empty
def test_noise_floor_excluded(): ...
```

- [ ] **Step 2: Run** → FAIL
- [ ] **Step 3: Implement** per Interfaces, plus the CLI subcommand
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `git commit -am "feat(select): scoring formula, feedback weights, edition selection"`

---

### Task 12: Enrichment

**Files:**
- Create: `newshouse/enrich.py`, `tests/fixtures/article.html`, `tests/test_enrich.py`

**Interfaces:**
- `newshouse/enrich.py`: `extract_body(html: str, url: str) -> str|None` (trafilatura, `include_comments=False`, returns None under 300 chars); `enrich_clusters(session, cluster_ids: list[str], *, client: httpx.Client, max_items_per_cluster: int = 3, max_bytes: int = 2_000_000) -> int`: for each cluster, pick up to 3 items preferring primary/early-signal sources, skipping items whose every source is `paywall` or `kind == "gnews"`, and items that already have a body; fetch with a 15 s timeout; store `body`; failures are skipped silently (logged); returns bodies stored.

- [ ] **Step 1: Write the failing tests**

```python
def test_extract_body_from_fixture(): ...  # article.html → body contains a known sentence, no nav text
def test_enrich_skips_paywall_and_gnews(session, httpx_mock): ...  # 3 items: paywalled, gnews, normal → 1 fetch, 1 body
def test_enrich_tolerates_fetch_failure(session, httpx_mock): ...
```

- [ ] **Step 2: Run** → FAIL
- [ ] **Step 3: Implement** per Interfaces
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `git commit -am "feat(enrich): article body extraction for shortlisted clusters"`

---

### Task 13: Card writing

**Files:**
- Create: `newshouse/write.py`, `newshouse/llm/prompts/write.system.md`, `newshouse/llm/prompts/house_style.md`, `tests/test_write.py`
- Modify: `newshouse/llm/schemas.py` (add `WRITE_SCHEMA`), `newshouse/select.py` (nothing; `est_seconds` reused)

**Interfaces:**
- `WRITE_SCHEMA` (strict JSON): `{"format": enum["A","B","C","D","E","F"], "headline": str, "line": str, "para": str, "brief": str, "why": str, "cited_item_ids": [str], "payload": object}` where `payload` by format is: B `{"columns":[str],"rows":[{"cells":[str],"yours":bool,"new":bool}]}`; C `{"series":[{"label":str,"value":number,"item_id":str}],"unit":str,"caption":str}`; D `{"chapters":[{"title":str,"date":str,"read":bool}],"delta":str}`; E `{"for":[str],"against":[str],"stands":str}`; F `{"before":str,"after":str,"effective":str,"applies_to":str}`; A `{}`.
- `newshouse/write.py`: `render_cluster_for_write(session, cluster, *, thread: Thread|None, read_chapters: set[int]) -> str` (every item: id, source name, tier, paywall flag, published time, title, teaser, body if present; thread chapters if any; the allowed formats given the data: `A` always, `D` only if `cluster.chapter >= 2`, `B/C/E/F` only if at least one non-gnews item with a body or a primary-tier teaser exists); `validate_card(out: dict, item_ids: set[str], *, allow_rich: bool) -> list[str]` returns problems: unknown citation ids, empty `cited_item_ids`, headline > 90 chars, rich format with empty payload, `C` with fewer than 3 series points, payload `item_id` not in citations; `write_card(session, backend, cluster, *, profile_text: str, model: str = "opus") -> Card`: builds the prompt (`write.system.md` + `house_style.md` + profile), calls the backend, validates; on problems retries once with the problems listed; if still invalid, stores a format-A card with `headline = best item title`, `line = teaser[:200]`, `para = brief = ""`, `why = ""`, `unverified = True`; sets `est_seconds = est_seconds(format)`, `cluster.carded = True`; returns the unsaved `Card` (caller assigns `edition_id` and `rank`).

- [ ] **Step 1: Write the failing tests**

```python
def test_write_happy_path_stores_payload_and_citations(session): ...  # FakeBackend returns a valid B card → Card.format "B", payload rows, cited ids subset of cluster items
def test_write_rejects_unknown_citations(session): ...  # first reply cites "nope", second reply valid → 2 calls, valid stored
def test_write_falls_back_to_unverified_A(session): ...  # both replies invalid → format A, unverified True, headline = item title
def test_rich_format_not_allowed_for_gnews_only_cluster(session): ...  # prompt's allowed formats = ["A"]; a "B" reply is a problem
def test_headline_over_90_is_problem(): ...
def test_chart_needs_three_points(): ...
```

- [ ] **Step 2: Run** → FAIL
- [ ] **Step 3: Implement** per Interfaces. Write `write.system.md` and `house_style.md` with the `prompt-writing` skill, encoding spec 7.6 verbatim: citations for every claim; rich format only when fillable from cited items; "why" must reference a specific profile fact or be empty; headline factual, ≤ 90 chars, Hinglish allowed where natural; brief 3 to 6 short paragraphs with an optional "what to watch next"; paywalled sources are named as such.
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `git commit -am "feat(write): card generation with citation validation"`

---

### Task 14: The daily build

**Files:**
- Create: `newshouse/build.py`, `tests/test_build.py`
- Modify: `newshouse/cli.py` (add `build [--date YYYY-MM-DD] [--force]`)

**Interfaces:**
- `newshouse/build.py`: `get_or_create_edition(session, *, profile_id: str, date: date, budget_seconds: int) -> Edition`; `build_edition(session, backend, *, settings, now: datetime, force: bool = False) -> Edition | None`: date = `now` in `settings.tz`; if the edition exists with `built_at` set and not `force` → return it unchanged; otherwise, inside one `Run(kind="build")`: `load_profile`, `embed_new_items`, `cluster_fresh_items`, `classify_clusters`, `match_threads`, `score_and_select`, `enrich_clusters(selected)`, `write_card` for each selected cluster in order (rank 1..n; breaking cards already attached to this edition keep rank 0 and are excluded from the budget), insert `AlsoHappened` rows with `line = cluster.reason or best title`, set `edition.built_at`, `cut_score`, `profile_version`; `Run.stats` records counts and total seconds per stage. On `force`, existing non-breaking cards and also-happened rows of that edition are deleted first.

- [ ] **Step 1: Write the failing tests** (all with `FakeBackend` and `freezegun`)

```python
def test_build_creates_edition_with_ranked_cards(session): ...  # 12 scored clusters → edition with cards rank 1..n, also_happened for the rest, built_at set
def test_build_is_idempotent_per_date(session): ...  # second call returns same edition id, same card count, no new Run
def test_build_force_rebuilds_but_keeps_breaking_cards(session): ...
def test_build_records_run_stats(session): ...  # Run.kind == "build", stats has "cards", "also", "clusters_scored"
```

- [ ] **Step 2: Run** → FAIL
- [ ] **Step 3: Implement** per Interfaces and the CLI subcommand
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `git commit -am "feat(build): daily edition build"`

---

### Task 15: Static preview render

**Files:**
- Create: `newshouse/render_static.py`, `newshouse/templates/edition.html.j2`, `tests/test_render.py`
- Modify: `newshouse/cli.py` (add `render [--date] [--out out/]`)

**Interfaces:**
- `newshouse/render_static.py`: `edition_view(session, edition) -> dict` (serialisable: edition date, cards in rank order with all fields and payload, also-happened lines, counts: cards, est_minutes, saved=0); `render_edition(session, edition, out_dir: Path) -> Path` writes `out/<date>.html` and `out/<date>.json`. The template reuses the structure and CSS of `docs/card-format-mockups.html`: one phone-width column; formats A to F rendered from `payload` (B as a table, C as an inline SVG bar chart, D as the timeline, E as two columns, F as before/after); the depth dial is four tabs switching among `line/para/brief/sources` with a few lines of vanilla JS; the footer buttons are inert in the static preview; the end card (G) shows the counts. Unverified cards show an "unverified" tag.

- [ ] **Step 1: Write the failing tests**

```python
def test_render_writes_html_and_json(session, tmp_path): ...  # 3 cards (A, B, C) → file exists; html contains the B headline and an <svg>; json has 3 cards
def test_render_marks_unverified(session, tmp_path): ...
```

- [ ] **Step 2: Run** → FAIL
- [ ] **Step 3: Implement** per Interfaces
- [ ] **Step 4: Run** → PASS; open `out/<date>.html` in a browser once to eyeball
- [ ] **Step 5: Commit** `git commit -am "feat(render): static edition preview"`

---

### Task 16: Breaking lane and the `tick` entry point

**Files:**
- Create: `newshouse/breaking.py`, `newshouse/tick.py`, `tests/test_breaking.py`, `tests/test_tick.py`
- Modify: `newshouse/cli.py` (add `breaking`, `tick`)

**Interfaces:**
- `newshouse/breaking.py`: `run_breaking(session, backend, *, settings, now: datetime) -> list[Card]`: among clusters scored since the last breaking run (tracked by the latest `Run(kind="breaking")`), take those with `breaking_eligible and importance >= settings.breaking_threshold and not carded`, ordered by importance, until today's breaking count (cards with `breaking=True` on today's edition) reaches `settings.breaking_daily_cap`; `enrich_clusters` then `write_card`; attach to `get_or_create_edition(today)` with `rank = 0`, `breaking = True`; one `Run(kind="breaking")`.
- `newshouse/tick.py`: `tick(session, backend, *, settings, now: datetime, client) -> dict`: `sync_sources` (if the YAML changed since the last sync, by mtime) → `ingest` → `embed_new_items` → `cluster_fresh_items` → `classify_clusters` → `match_threads` → then: if today's edition is not built and local time ≥ 06:00 → `build_edition` + `render_edition`; else → `run_breaking`. Also `close_quiet_threads` and, once a day, `prune_old(session, now, days=90)` which nulls `body` and `embedding` on items older than 90 days (define `prune_old` in `newshouse/build.py`). Returns a dict of what ran.

- [ ] **Step 1: Write the failing tests**

```python
def test_breaking_respects_threshold_and_daily_cap(session): ...  # 5 eligible clusters ≥ 90 → 3 cards today, rank 0, breaking True
def test_breaking_ignores_already_carded(session): ...
def test_tick_builds_when_no_edition_and_after_6am(session): ...  # freezegun 2026-10-31 10:15 IST → build ran, breaking did not
def test_tick_runs_breaking_when_edition_built(session): ...
def test_tick_does_not_build_before_6am(session): ...
def test_prune_old_clears_bodies_after_90_days(session): ...
```

- [ ] **Step 2: Run** → FAIL
- [ ] **Step 3: Implement** per Interfaces and the CLI subcommands
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `git commit -am "feat(tick): scheduled entry point and breaking lane"`

---

### Task 17: Source health check

**Files:**
- Create: `newshouse/health.py`, `tests/test_health.py`
- Modify: `newshouse/cli.py` (add `health`), `newshouse/tick.py` (run `health` on Sundays once)

**Interfaces:**
- `newshouse/health.py`: `check_sources(session, *, client: httpx.Client, now: datetime) -> dict[str, dict]`: for every source of a fetchable kind, `fetch_feed` and update `last7d` (items with `published_at` within 7 days) and `last_ok_at`; a source with `ok=False` three health runs in a row, or no item newer than 30 days, is reported under `"dead"`; a `Run(kind="health")` stores the report. Does not change `enabled` (Mihir decides).

- [ ] **Step 1: Write the failing test** `test_health_reports_dead_sources(session, httpx_mock)` (one feed 404 three times → in dead; one healthy → last7d updated)
- [ ] **Step 2: Run** → FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `git commit -am "feat(health): weekly source health report"`

---

### Task 18: launchd scheduling on the Mac

**Files:**
- Create: `launchd/com.bisati.news-house.tick.plist.template`, `scripts/tick.sh`, `scripts/install_launchd.sh`, `scripts/uninstall_launchd.sh`, `README.md` section "Running on the Mac"

**Interfaces:**
- The plist runs `/bin/zsh -lc '<repo>/scripts/tick.sh >> ~/Library/Logs/news-house/tick.log 2>&1'` with `StartInterval` 7200, `RunAtLoad` true, `EnvironmentVariables` `CLAUDE_CODE_RETRY_WATCHDOG=1`, `ProcessType` Background. launchd runs a missed interval at the next wake, which is what section 5.1 relies on.
- `scripts/tick.sh`: `cd <repo> && git checkout -q main && git pull -q --ff-only origin main && . .venv/bin/activate && pip install -q -e . && newshouse tick`. This is the only production path: what runs is always `main` on GitHub. (During Plan A development, before the first merge, `main` holds only the skeleton; the acceptance run in Task 20 happens after merging `build/plan-a` into `main` via a pull request.)
- `install_launchd.sh` substitutes the repo path, copies to `~/Library/LaunchAgents/`, runs `launchctl bootstrap gui/$(id -u) <plist>`, and prints how to check: `launchctl print gui/$(id -u)/com.bisati.news-house.tick | grep -E 'state|last exit'`.

- [ ] **Step 1: Write the template, scripts and README section**
- [ ] **Step 2: Verify** `bash scripts/install_launchd.sh` then `launchctl kickstart -k gui/$(id -u)/com.bisati.news-house.tick`; expected: `tick.log` gains a run within a minute and `newshouse` exits 0
- [ ] **Step 3: Commit** `git commit -am "feat(ops): launchd agent for tick"`

---

### Task 19: Postgres on Neon

**Files:**
- Modify: `README.md` (section "Database"), `newshouse/db.py` (no code change expected; verify JSON/LargeBinary/date types create cleanly on Postgres)
- Create: `scripts/migrate_sqlite_to_pg.py`

**Mihir's one-time steps:** create a free Neon project named `news-house`, copy the pooled connection string into `~/.config/news-house/db.env` as `DATABASE_URL=postgresql+psycopg://...`, `chmod 600`.

- [ ] **Step 1: Verify create_all on Postgres**: with `DATABASE_URL` set, `newshouse init-db` then `psql "$DATABASE_URL" -c '\dt'` lists the 12 tables
- [ ] **Step 2: Write and run `scripts/migrate_sqlite_to_pg.py`** copying every table from `./newshouse.db` to Postgres in dependency order (sources, items, item_sources, clusters, cluster_items, threads, editions, cards, also_happened, feedback, profiles, runs); verify row counts match
- [ ] **Step 3: Switch the launchd agent to Postgres** (it reads the same env file) and `launchctl kickstart`; expected: next tick writes a `Run` row in Postgres
- [ ] **Step 4: Commit** `git commit -am "feat(db): postgres on neon, sqlite migration script"`

---

### Task 20: First real edition and acceptance

**Files:**
- Create: `docs/first-run-notes.md`

- [ ] **Step 0: Merge to main** — open a PR from `build/plan-a` to `main` on GitHub, merge it, and confirm `scripts/tick.sh` pulls it
- [ ] **Step 1: Full run** `newshouse tick` by hand around midday; expected: `Run(kind="build")` succeeded, 8 to 25 cards, `out/<date>.html` renders
- [ ] **Step 2: Mihir reads it** and records in `docs/first-run-notes.md`: cards that were worth it, cards that shouldn't be there, items in "Also happened" that should have been in, and any card whose facts are wrong against its sources; file `newshouse feedback` for each
- [ ] **Step 3: Check the numbers**: `Run.stats` per stage; Claude Code calls per day (expect roughly 10 to 15 classify, 20 to 25 write, a handful of thread/same-event); cost estimate from the envelope's `total_cost_usd` summed; note in the file
- [ ] **Step 4: Fix anything the first run breaks** as ordinary commits; run for three days unattended before starting Plan B
- [ ] **Step 5: Commit** `git commit -am "docs: first run notes"`

---

## Self-review notes

- Spec coverage: 5.1 editions (14, 16), 5.2 cards and formats (13, 15), 5.3 threads (10), 5.4 end screen (15, static only; interactive in Plan B), 5.5 archive and retention (2 keeps everything; 16 prunes bodies), 6 sources and kinds (3, 4, 5; `api` kind adapters for HF trending/ESPN/Open-Meteo/TMDB deferred to Plan B or phase 2 as the spec allows), 7.1 to 7.9 (4, 12, 8, 9, 11, 13, 10, 16, 11), 7.10 headless flags (7), 7.11 run log (every task writes `Run` rows; the `/log` page is Plan B), 8 platform (1, 18, 19), 9 data model (2), section 13 decisions (Haiku/Opus in Global Constraints, Reddit in 5, Mac in 18).
- Not in Plan A, by design: the PWA, feedback buttons, archive UI, `/log` page, fixture card, movies consensus APIs, `api` LLM backend (interface exists; implementation is phase 3).
- Type consistency checked: `FetchResult`/`RawItem` (3) used by 4, 5, 17; `LLMBackend.complete_json` (7) used by 8, 9, 10, 13; `Selection`/`ScoredCluster` (11) used by 14; `est_seconds` (11) used by 13; `get_or_create_edition` (14) used by 16; `Weights` (11) internal.
