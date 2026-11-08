# News House v2, Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The edition renders as posts in the Calm Forest look on existing data, selection applies per-topic floors and the "top stories are printed or explained" rule, an edition-level validator warns, and reactions work from the page through a local server.

**Architecture:** The pipeline stays as built (ingest, cluster, classify, threads, select, write, render, tick). Phase 1 adds a committed `config/edition.yaml`, a new selection function that uses it, a validator module that runs after write and in report mode on render, pure presentation functions (`present.py`) that decide a post's colour world and visual from the card, a rewritten Jinja template with inlined CSS and JS and self-hosted fonts, an archive index, a stdlib HTTP server for feedback, and a screenshot script. Schema changes are additive columns applied by an `ensure_columns` helper. No new dependencies.

**Tech Stack:** Python 3.12+, SQLAlchemy 2, pydantic 2, PyYAML, Jinja2, httpx, stdlib `http.server`; pytest, freezegun; headless Chrome (dev only, for screenshots).

**Spec:** `docs/design-v2.md` (sections 3.1 to 3.4, 3.6, 3.7, 3.9, 3.10, 3.11, 4.1, 4.2, 4.3 why rule, 4.5, 4.6, 4.8, 4.9, 5, 6, phase 1 in 7). Where this plan and the spec disagree, the spec wins.

## Global Constraints

- Work on branch `v2/phase-1` off `main` (main is at the squash of Plan A, commit `6952b99`). One commit per task; commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- No new runtime dependencies. `config/edition.yaml` and `config/banned.yaml` are committed and hold no secrets. Never commit `newshouse.db`, `out/`, `profile.md`.
- No model call in `render`, in the validator's report mode, or in any test (tests use the fake backend from `newshouse/llm/fake.py` and the existing fixtures).
- Colour tokens exactly as spec 3.1 (sand `#F3EEE4`, white, forest `#12372A`, forest-deep `#1E4A3A`, ink-body `#2C3A32`, muted `#5B6A61`, hairline `#E4DDCD`, track `#DDD5C4`, tomato `#F25C3B`, butter `#F6C945`, mint `#A8F0C6`, mint-light `#D9F5E3`, sky `#DCE9FF`, good `#3CC77A`). Text on tomato is forest, never white.
- Fonts self-hosted under `newshouse/static/fonts/`; the rendered page makes no request to `fonts.googleapis.com` or `fonts.gstatic.com`. CSS and JS are inlined; the page is one file plus `out/fonts/`.
- Radii: post 14px, inner panel 10px, buttons 8px, bars 4px. No shadows, no gradients, no emoji anywhere.
- All motion is `transform`/`opacity` only, under `@media (prefers-reduced-motion: no-preference)`.
- Schema changes are additive with defaults; the 30 October 2026 edition (`newshouse.db`, edition date `2026-10-30`) must re-render without a rebuild.
- The validator never blocks a build; it writes `Edition.warnings`.
- Existing 178 tests keep passing.
- Headline: 12 words is a soft rule (a validator warning), 90 characters stays hard (`HEADLINE_MAX`).

## Review Focus

- An edition where no cluster clears the noise floor: selection returns no cards, the validator records a count warning, and `render_edition` still writes the page with a progress line of `0 posts` (no division by zero). Test in Task 7 (`test_validate_empty_edition_warns`) and Task 11 (`test_render_empty_edition`).
- A cluster whose `topics` is `[]` or `None`: primary topic is `"other"`, the default rule applies, no `KeyError` in selection or presentation. Test in Task 3 (`test_primary_topic_of_untopiced_cluster`).
- A headline with no number and one word: `cover_big` returns that word, never an empty string. Test in Task 9 (`test_cover_big_single_word`).
- `POST /feedback` with an unknown card id or an unknown action returns 400 with a JSON error, never 500, and writes nothing. Test in Task 14 (`test_serve_rejects_bad_feedback`).
- A database created by v1 (no new columns): `ensure_columns` adds them at `init-db` and at the start of `tick`, so a build on the old file does not crash. Test in Task 2 (`test_ensure_columns_adds_missing`) and Task 2's tick test.

---

### Task 1: Edition configuration file and loader

**Files:**
- Create: `config/edition.yaml`
- Create: `newshouse/edition_config.py`
- Modify: `newshouse/config.py` (add `edition_config_path`)
- Test: `tests/test_edition_config.py`

**Interfaces:**
- Produces: `class TopicRule(BaseModel)` with `min: int = 0`, `max: int = 4`; `class TeamColours(BaseModel)` with `primary: str`, `secondary: str`; `class EditionConfig(BaseModel)` with `budget_seconds: int = 900`, `cards_floor: int = 8`, `cards_cap: int = 25`, `top_n: int = 10`, `topics: dict[str, TopicRule] = {}`, `topic_default: TopicRule = TopicRule()`, `colours_topic: dict[str, str] = {}`, `teams: dict[str, TeamColours] = {}`; `def load_edition_config(path: Path | None = None) -> EditionConfig` (missing file returns defaults; `min > max` anywhere raises `ValueError`); `def rule_for(cfg: EditionConfig, topic: str | None) -> TopicRule`; `Settings.edition_config_path: Path = Path("config/edition.yaml")`.

- [ ] **Step 1: Write the failing tests**

```python
from pathlib import Path
import pytest
from newshouse.edition_config import EditionConfig, load_edition_config, rule_for

def test_loads_committed_file():
    cfg = load_edition_config(Path("config/edition.yaml"))
    assert cfg.budget_seconds == 900 and cfg.cards_floor == 8 and cfg.cards_cap == 25
    assert cfg.top_n == 10
    assert cfg.topics["ai-models"].min == 1 and cfg.topics["ai-models"].max == 4
    assert cfg.topics["gurgaon-local"].max == 3
    assert cfg.colours_topic["gurgaon-local"] == "sky"
    assert cfg.teams["barcelona"].primary == "#A50044"

def test_missing_file_gives_defaults(tmp_path):
    cfg = load_edition_config(tmp_path / "nope.yaml")
    assert cfg == EditionConfig()

def test_rule_for_unknown_topic_is_default():
    cfg = EditionConfig(topic_default={"min": 0, "max": 2})
    assert rule_for(cfg, "zzz").max == 2 and rule_for(cfg, None).max == 2

def test_min_above_max_rejected(tmp_path):
    p = tmp_path / "e.yaml"
    p.write_text("topics:\n  football: {min: 5, max: 2}\n")
    with pytest.raises(ValueError):
        load_edition_config(p)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_edition_config.py -v`
Expected: FAIL with `ModuleNotFoundError: newshouse.edition_config`

- [ ] **Step 3: Write `config/edition.yaml`**

Exactly the block in spec section 6, with the YAML keys mapped as: `cards: {floor, cap}` becomes `cards_floor`/`cards_cap` in the loader; `topics.default` becomes `topic_default`; `colours.topic` becomes `colours_topic`; `colours.teams` becomes `teams`; `live` is read into an extra `live: dict = {}` field for phase 3.

- [ ] **Step 4: Implement `newshouse/edition_config.py` and the Settings field**

The loader reads YAML with `yaml.safe_load`, reshapes the keys above, validates with pydantic, and checks `min <= max` for every rule.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_edition_config.py tests/test_config.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add config/edition.yaml newshouse/edition_config.py newshouse/config.py tests/test_edition_config.py
git commit -m "feat(config): committed edition.yaml with floors, caps, top_n, colours"
```

---

### Task 2: Additive schema columns and `ensure_columns`

**Files:**
- Modify: `newshouse/models.py`
- Modify: `newshouse/db.py`
- Modify: `newshouse/tick.py` (call `ensure_columns` first)
- Modify: `newshouse/feedback.py` (`ACTIONS`)
- Test: `tests/test_models.py`, `tests/test_tick.py`

**Interfaces:**
- Produces: columns `Card.visual: str` (default `"cover"`), `Card.slides: list` (JSON, default `[]`), `Card.tone: str | None`, `Edition.top_ids: list` (default `[]`), `Edition.warnings: list` (default `[]`), `AlsoHappened.cut_reason: str | None`, `AlsoHappened.is_top: bool` (default `False`), `Feedback.payload: dict | None`; `def ensure_columns(engine) -> list[str]` in `db.py` returning `"table.column"` for each column it added (idempotent; `init_db` calls it after `create_all`); `feedback.ACTIONS == ("worth", "skip", "later", "should_have", "tune", "seen", "read")`.

- [ ] **Step 1: Write the failing tests**

```python
from sqlalchemy import text
from newshouse.db import ensure_columns, get_engine, init_db, session_scope
from newshouse.models import AlsoHappened, Card, Edition

def test_new_columns_have_defaults(session):
    # seed one edition + card as in tests/test_render.py::seed, then:
    card = session.get(Card, "card0")
    assert card.visual == "cover" and card.slides == [] and card.tone is None
    ed = session.get(Edition, "e1")
    assert ed.top_ids == [] and ed.warnings == []

def test_ensure_columns_adds_missing(tmp_path):
    eng = get_engine(f"sqlite:///{tmp_path/'old.db'}")
    init_db(eng)
    with eng.begin() as c:
        c.execute(text("ALTER TABLE cards DROP COLUMN visual"))
        c.execute(text("ALTER TABLE editions DROP COLUMN warnings"))
    added = ensure_columns(eng)
    assert added == ["cards.visual", "editions.warnings"]
    assert ensure_columns(eng) == []
```

And in `tests/test_tick.py`, a test that drops `cards.visual` from the test database, runs `tick` with the fake backend once, and asserts no exception and that `cards.visual` exists afterwards.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_models.py tests/test_tick.py -v`
Expected: FAIL (`AttributeError: visual`, `ImportError: ensure_columns`)

- [ ] **Step 3: Add the columns, `ensure_columns`, the tick call, and the new actions**

`ensure_columns` uses `sqlalchemy.inspect(engine)` to list existing columns per table in `Base.metadata.tables`, and for each missing column runs `ALTER TABLE <t> ADD COLUMN <name> <type> [DEFAULT <literal>]` compiled for the engine's dialect (JSON columns default to `'[]'` or `NULL` as the model says; booleans default `0`/`false`). Order of the returned list: table order of `Base.metadata.sorted_tables`, then column order.

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass (178 + new)

- [ ] **Step 5: Commit**

```bash
git add newshouse/models.py newshouse/db.py newshouse/tick.py newshouse/feedback.py tests/test_models.py tests/test_tick.py
git commit -m "feat(db): v2 columns with defaults and ensure_columns for old databases"
```

---

### Task 3: Selection v2: primary-topic floors and caps, top rule, one home per thread

**Files:**
- Modify: `newshouse/select.py`
- Test: `tests/test_select_v2.py`

**Interfaces:**
- Consumes: `EditionConfig`, `rule_for` (Task 1).
- Produces: `ScoredCluster` gains `thread_id: str | None = None`; `def primary_topic(topics: list[str] | None) -> str` (first slug, else `"other"`); `Selection` gains `top_ids: list[str]`, `cuts: dict[str, str]`, `unmet_floors: dict[str, int]`; `def select_edition_v2(scored: list[ScoredCluster], *, cfg: EditionConfig, noise_floor: int = 30) -> Selection`; `score_and_select(session, *, now, settings, cfg: EditionConfig)` calls it. The v1 `select_edition` stays untouched for its existing tests and is removed in phase 2.

Algorithm, in this order:
1. `pool`: `importance >= noise_floor` and `story_type != "noise"`, sorted by `final_score` descending.
2. `top_ids`: the first `cfg.top_n` of `pool` sorted by `(importance, final_score)` descending.
3. Thread homes: among pool clusters sharing a `thread_id`, only the highest `final_score` stays eligible; the others get `cuts[id] = "duplicate thread home"`.
4. Floors: for each topic with `min > 0`, take eligible clusters of that primary topic by score until `min`, ignoring the budget, never above the topic `max` or `cards_cap`. A floor that cannot be met goes in `unmet_floors[topic] = min - taken`.
5. Budget: by score, take an eligible cluster when its primary topic count is below `max`, `spent + est_seconds <= cfg.budget_seconds` and `len(chosen) < cfg.cards_cap`. The first reason a cluster is passed over is remembered: `"topic cap <topic> (<max>)"`, `"budget"`, `"card cap"`.
6. Global floor: while `len(chosen) < cfg.cards_floor`, take the next eligible cluster within topic caps, ignoring the budget.
7. `cuts`: for every cluster in `top_ids` not chosen, its remembered reason (or `"noise floor"` when it was never in `pool`, which cannot happen for top ids but the code handles it).
8. `also`: pool minus chosen, by score, the first `ALSO_MAX`, plus every cut top id even past the limit.
9. `selected` in `final_score` order; `cut_score` as before.

- [ ] **Step 1: Write the failing tests**

```python
from newshouse.edition_config import EditionConfig
from newshouse.select import ScoredCluster, primary_topic, select_edition_v2

def sc(id, imp, score, topics, st="plain", fmt="A", thread=None):
    return ScoredCluster(id, imp, score, topics, st, fmt, thread_id=thread)

CFG = EditionConfig(top_n=2, cards_floor=1, cards_cap=25, budget_seconds=900,
                    topics={"ai-models": {"min": 1, "max": 2}, "gurgaon-local": {"min": 1, "max": 3},
                            "movies": {"min": 1, "max": 2}})

def test_primary_topic_of_untopiced_cluster():
    assert primary_topic([]) == "other" and primary_topic(None) == "other"
    assert primary_topic(["football", "india-news"]) == "football"

def test_floor_pulls_in_a_lower_scored_topic():
    sel = select_edition_v2([sc("a", 80, 90, ["ai-models"]), sc("b", 70, 80, ["ai-models"]),
                             sc("g", 35, 40, ["gurgaon-local"])], cfg=CFG)
    assert "g" in sel.selected

def test_cap_counts_primary_topic_only_and_explains_top_cuts():
    scored = [sc(f"a{i}", 90 - i, 90 - i, ["ai-models", "ai-built"]) for i in range(4)]
    sel = select_edition_v2(scored, cfg=CFG)
    assert sel.selected == ["a0", "a1"]
    assert sel.top_ids == ["a0", "a1"] and sel.cuts == {}
    sel = select_edition_v2(scored, cfg=EditionConfig(top_n=3, cards_floor=1,
                                                      topics={"ai-models": {"min": 0, "max": 2}}))
    assert sel.cuts == {"a2": "topic cap ai-models (2)"}

def test_budget_cut_is_explained():
    cfg = EditionConfig(top_n=2, cards_floor=1, budget_seconds=35)
    sel = select_edition_v2([sc("a", 90, 90, ["movies"]), sc("b", 85, 85, ["cricket"])], cfg=cfg)
    assert sel.selected == ["a"] and sel.cuts == {"b": "budget"}

def test_one_home_per_thread():
    sel = select_edition_v2([sc("a", 90, 90, ["india-news"], thread="t1"),
                             sc("b", 88, 80, ["india-news"], thread="t1")],
                            cfg=EditionConfig(top_n=2, cards_floor=1))
    assert sel.selected == ["a"] and sel.cuts["b"] == "duplicate thread home"

def test_unmet_floor_is_recorded_not_forced():
    sel = select_edition_v2([sc("a", 90, 90, ["ai-models"])], cfg=CFG)
    assert sel.unmet_floors == {"gurgaon-local": 1, "movies": 1}

def test_cut_top_ids_always_in_also():
    scored = [sc(f"x{i}", 60, 60 - i * 0.1, ["cricket"]) for i in range(40)]
    scored.append(sc("top", 99, 1, ["cricket"]))  # high importance, low score, cut by topic cap
    sel = select_edition_v2(scored, cfg=EditionConfig(top_n=1, cards_floor=1,
                                                      topics={"cricket": {"min": 0, "max": 2}}))
    assert "top" in sel.also and len(sel.also) == 26
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_select_v2.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `primary_topic`, `select_edition_v2`, extend `ScoredCluster` and `Selection`, switch `score_and_select` to v2 with a `cfg` parameter**

`score_and_select` populates `thread_id` from `Cluster.thread_id`. Callers in `build.py` and `breaking.py` pass `cfg=load_edition_config(settings.edition_config_path)`.

- [ ] **Step 4: Run the suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add newshouse/select.py newshouse/build.py newshouse/breaking.py tests/test_select_v2.py
git commit -m "feat(select): per-topic floors and caps, top stories printed or explained, one home per thread"
```

---

### Task 4: Build stores the top rule's outcome; the edition view exposes it

**Files:**
- Modify: `newshouse/build.py` (`_run_stages`)
- Modify: `newshouse/render_static.py` (`edition_view`)
- Test: `tests/test_build.py`, `tests/test_render.py`

**Interfaces:**
- Consumes: `Selection.top_ids`, `cuts`, `unmet_floors` (Task 3).
- Produces: `Edition.top_ids` set after select; each `AlsoHappened` row gets `cut_reason=sel.cuts.get(cid)` and `is_top=cid in sel.top_ids`; `stats["cuts"]`, `stats["unmet_floors"]`; `edition_view()` returns `top_ids`, `warnings`, and each `also` entry as `{"rank", "line", "cluster_id", "cut_reason", "is_top"}`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_build.py`, using the existing fake-backend build fixture: configure `EditionConfig(top_n=1, ...)` so one top cluster is cut by a topic cap, build, then assert `edition.top_ids` has one id and the matching `AlsoHappened` row has `is_top is True` and `cut_reason.startswith("topic cap")`. In `tests/test_render.py::test_edition_view_orders_breaking_first_and_includes_sources`, update the `also` assertion to the new shape and add `assert v["top_ids"] == [] and v["warnings"] == []`.

- [ ] **Step 2: Run to verify failure, implement, run the suite, commit**

```bash
git add newshouse/build.py newshouse/render_static.py tests/test_build.py tests/test_render.py
git commit -m "feat(build): store top ids and cut reasons; expose them in the edition view"
```

---

### Task 5: Prompt changes: the three tests, the why rule, the headline target

**Files:**
- Modify: `newshouse/llm/prompts/classify.system.md`
- Modify: `newshouse/llm/prompts/write.system.md`
- Test: `tests/test_prompts.py`

**Interfaces:** none beyond text. The validator (Task 6) enforces the why rule mechanically.

- [ ] **Step 1: Write the failing test**

```python
from importlib import resources

def _p(name):
    return resources.files("newshouse.llm").joinpath(f"prompts/{name}").read_text()

def test_classify_prompt_carries_the_three_tests():
    t = _p("classify.system.md")
    assert "annoyed tomorrow" in t and "well-informed person in India" in t
    assert "what they pay, earn, save or decide" in t

def test_write_prompt_why_rule_and_headline_target():
    t = _p("write.system.md")
    assert "this week or this month" in t
    assert "12 words" in t and "90 characters" in t
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_prompts.py -v`
Expected: FAIL on the assertions

- [ ] **Step 3: Edit the prompts**

In `classify.system.md`, under `importance`, add three bullet questions the scorer asks before choosing a band: "Would the reader be annoyed tomorrow to have missed it?", "Would a well-informed person in India be caught out not knowing it?", "Does it change what they pay, earn, save or decide?" A yes to the first or third lifts the story into 60 and above; a yes to the second alone is 60 to 75 (national news he does not follow but should know).

In `write.system.md`, replace the `why` bullet with: `why` is one sentence that names a specific fact from the reader profile and says what changes for the reader this week or this month: a cost, a decision, a commute, a match he will watch. If the sentence would only say that the topic is one he follows, set `why` to "". Most cards have no `why`. Replace the headline bullet with: at most 12 words as a target and 90 characters as the limit; name the actor and the fact.

- [ ] **Step 4: Run the suite, commit**

```bash
git add newshouse/llm/prompts/classify.system.md newshouse/llm/prompts/write.system.md tests/test_prompts.py
git commit -m "feat(prompts): three editorial tests in classify; stricter why rule and 12-word headline target"
```

---

### Task 6: The edition validator

**Files:**
- Create: `newshouse/validate.py`
- Create: `config/banned.yaml`
- Test: `tests/test_validate.py`

**Interfaces:**
- Consumes: `EditionConfig`, `primary_topic` (Task 3), `_payload_problems` from `newshouse/write.py`, `edition_view` (Task 4).
- Produces: `@dataclass class Problem: rule: str; text: str; card_id: str | None = None`; `class Banned(BaseModel)` with `words: list[str]`, `patterns: list[str]`; `def load_banned(path: Path = Path("config/banned.yaml")) -> Banned`; `def profile_tokens(profile_text: str) -> set[str]` (lowercase alphabetic tokens of 4+ letters, minus a small stopword set); `def card_problems(card: dict, *, profile: set[str], banned: Banned, previous_headline: str | None, cluster_item_ids: set[str]) -> list[Problem]`; `def validate_edition(session, edition, *, cfg: EditionConfig, profile_text: str, banned: Banned) -> list[Problem]`; `def is_text_problem(p: Problem) -> bool` (rules `headline-long`, `gist-long`, `why-generic`, `banned-word`, `banned-pattern`, `chapter-repeats`).

Rules and their `rule` names:
- `count`: cards below `cards_floor` or above `cards_cap`; `est_minutes` outside 12 to 18.
- `floor`: a topic with `min > 0` whose primary-topic card count is below `min`.
- `top-unexplained`: an id in `edition.top_ids` that is neither a card's `cluster_id` nor an `also` entry with a non-empty `cut_reason`.
- `thread-home`: two cards with the same `thread_id`.
- `chapter-repeats`: a card with `chapter >= 2` whose headline shares 60% or more of its lowercase word tokens with `previous_headline` (the chapter-1 card's headline from any earlier edition, queried by `thread_id` and `chapter - 1`).
- `headline-long`: more than 12 words. `gist-long`: `line` over 40 words.
- `why-generic`: `why` non-empty and sharing no token with `profile`.
- `banned-word`: any word in `Banned.words` found with word boundaries, case-insensitive, in headline, line, para, brief or why. `banned-pattern`: any regex in `Banned.patterns` matching those fields (the committed list: `—`, `(?i)\bexperts say\b`, `(?i)\bsources say\b`, `(?i)\bnot just \w+ but\b`).
- `payload`: `_payload_problems(format, payload, cited, None)` non-empty.
- `citation`: a cited item id not in the card's cluster.

`config/banned.yaml` words: pivotal, crucial, landmark, testament, underscores, highlights, showcases, delve, landscape, navigate, robust, seamless, notably, quietly, amid, game-changer, game-changing, elevate, unleash.

- [ ] **Step 1: Write the failing tests**

One test per rule, seeding with a helper modelled on `tests/test_render.py::seed` (copy it into `tests/helpers.py` as `seed_edition(session, specs, *, also=())` and import it from both files). Names and the assertion each makes:

```python
def test_validate_empty_edition_warns(session): ...  # no cards -> one Problem with rule "count"
def test_count_rule_on_minutes(session): ...  # 8 cards of 300 seconds -> "count" mentions minutes
def test_floor_rule(session): ...  # cfg movies min 1, no movies card -> rule "floor", text contains "movies"
def test_top_unexplained(session): ...  # edition.top_ids=["c9"], no card, no also row -> "top-unexplained"
def test_top_explained_by_cut_reason(session): ...  # also row with cut_reason -> no problem
def test_thread_home(session): ...  # two cards thread_id "t1" -> "thread-home"
def test_chapter_repeats(session): ...  # previous headline "Delhi announces new vehicle curbs under GRAP", card chapter 2 headline "Delhi announces new vehicle curbs under revised GRAP" -> "chapter-repeats"
def test_headline_long_is_soft(session): ...  # 14-word headline -> rule "headline-long"; is_text_problem True
def test_why_generic_vs_specific(): ...  # profile tokens {"gemini","gurgaon"}; why "This matters to anyone in tech" -> problem; why "You run Gemini flash-lite" -> none
def test_banned_word_and_pattern(): ...  # para "A pivotal moment — experts say" -> two problems, rules banned-word and banned-pattern
def test_citation_outside_cluster(session): ...  # cited id "zz" -> "citation"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_validate.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `validate.py` and `banned.yaml`**

`validate_edition` builds the view with `edition_view`, loads cluster item ids per card in one query, finds each chapter's previous headline with one query per thread card, and concatenates `card_problems` with the edition-level rules.

- [ ] **Step 4: Run the suite, commit**

```bash
git add newshouse/validate.py config/banned.yaml tests/test_validate.py tests/helpers.py tests/test_render.py
git commit -m "feat(validate): edition-level validator with count, floor, top, thread, language and citation rules"
```

---

### Task 7: Validator in the build (retry once, fall back, warn) and report mode on render

**Files:**
- Modify: `newshouse/write.py` (`write_card` gains `problems`)
- Modify: `newshouse/build.py` (`_run_stages`, after write)
- Modify: `newshouse/render_static.py`, `newshouse/cli.py` (`render --validate`)
- Test: `tests/test_build.py`, `tests/test_write.py`, `tests/test_render.py`

**Interfaces:**
- Produces: `write_card(session, backend, cluster, *, profile_text, model="opus", read_chapters=frozenset(), problems: list[str] | None = None) -> Card`: when `problems` is given, the first prompt already carries the "Your previous reply had these problems" block, and only one attempt is made. `def apply_validation(session, backend, edition, *, cfg, profile_text, banned, stats) -> list[Problem]` in `build.py`: runs `validate_edition`; for each card with problems, calls `write_card` once with the problem texts, replaces the card's fields if the new reply validates with `validate_card` and has fewer validator problems, else keeps the old card; a card still carrying a `payload` problem gets `format="A"`, `payload={}`, `visual="cover"`; every remaining problem is stored on `edition.warnings` as `{"rule", "text", "card_id"}`; `stats["validator"] = {"problems": n_before, "retried": n, "warnings": n_after}`. `render_edition(session, edition, out_dir, *, validate: bool = False, cfg=None, profile_text="", banned=None)`: with `validate=True` runs `validate_edition` in report mode and stores the warnings before rendering. CLI: `newshouse render --validate`.

- [ ] **Step 1: Write the failing tests**

- `tests/test_write.py::test_write_card_with_problems_makes_one_attempt`: fake backend records calls; `write_card(..., problems=["headline is 14 words"])` makes exactly one call whose user prompt contains the problem text.
- `tests/test_build.py::test_validator_retries_then_warns`: fake backend returns, for one cluster, a reply with `para` containing "pivotal" on the first call and a clean reply on the second; after build, that card's para has no "pivotal" and `edition.warnings == []`; a second cluster whose replies always contain "pivotal" ends with the word still there and one warning with `rule == "banned-word"`.
- `tests/test_build.py::test_count_warning_is_not_retried`: three selectable clusters, `cards_floor=8`: one warning with rule `count`, no extra backend calls beyond the three writes.
- `tests/test_render.py::test_render_validate_report_mode`: a seeded edition with a 14-word headline, `render_edition(..., validate=True, cfg=EditionConfig(), profile_text="", banned=load_banned())` stores one `headline-long` warning and the JSON has it under `warnings`.

- [ ] **Step 2: Run to verify failure, implement, run the suite, commit**

```bash
git add newshouse/write.py newshouse/build.py newshouse/render_static.py newshouse/cli.py tests/test_write.py tests/test_build.py tests/test_render.py
git commit -m "feat(build): validate after write, retry once, fall back and warn; render --validate report mode"
```

---

### Task 8: Feedback: seen, read and tune events; read chapters from seen

**Files:**
- Modify: `newshouse/feedback.py`, `newshouse/build.py` (`_read_chapters`), `newshouse/cli.py`
- Test: `tests/test_feedback.py`, `tests/test_build.py`

**Interfaces:**
- Produces: `record_feedback(session, *, profile_id, action, card_id=None, cluster_id=None, at, payload: dict | None = None)`; `compute_weights` ignores actions outside `("worth", "skip", "later", "should_have")`; `_read_chapters(session, cluster, edition)` returns the chapters of this thread whose card has a `seen` or `read` feedback for the profile (any edition except the current one); CLI `feedback <card_id> <action> [--payload JSON]`.

- [ ] **Step 1: Write the failing tests**

```python
def test_seen_and_read_are_valid_actions_and_ignored_by_weights(session): ...
    # record seen, read, tune on a card; compute_weights().topic == {}
def test_payload_round_trips(session): ...  # tune with {"topic": "football", "dir": -1}
def test_read_chapters_uses_seen_events(session): ...
    # chapter-1 card in an earlier edition without seen -> frozenset(); with seen -> {1}
```

- [ ] **Step 2: Run to verify failure, implement, run the suite, commit**

```bash
git add newshouse/feedback.py newshouse/build.py newshouse/cli.py tests/test_feedback.py tests/test_build.py
git commit -m "feat(feedback): seen, read and tune events with payload; thread chapters read only when seen"
```

---

### Task 9: Presentation logic: colour worlds and visuals

**Files:**
- Create: `newshouse/present.py`
- Test: `tests/test_present.py`

**Interfaces:**
- Consumes: `EditionConfig.colours_topic`, `teams` (Task 1); card view dicts from `edition_view`.
- Produces: `PALETTE: dict[str, str]` (the 14 tokens of spec 3.1 by name); `@dataclass class World: fill: str; ink: str; body: str; muted: str; accent: str; label: str; panel: str; name: str` (`name` is one of `forest`, `white`, `mint`, `sky`, `tomato-accent`, `butter-accent`, `team`); `def colour_world(card: dict, *, position: int, previous: list[str], cfg: EditionConfig) -> World` applying spec 3.6 in order (breaking, lead at position 0, team, tone, topic default, rhythm: never two `forest` in a row, never three `white` in a row); `def team_for(card: dict, cfg: EditionConfig) -> str | None` (a team key whose name or an alias in `TEAM_ALIASES = {"barcelona": ("barça", "barcelona", "barca")}` appears lowercase in the headline or line, only when `"football" in card["topics"]`); `def cover_big(headline: str) -> str`; `def visual_for(card: dict) -> dict` returning `{"kind": ..., "payload": ...}` with `format` mapped C→`chart`, B→`table`, D→`timeline`, E→`versus`, F→`before-after`, else `cover` with `{"big": cover_big(headline), "label": "", "line": card["line"]}`; `SLIDE_FILLS = ["butter", "sand", "tomato", "forest"]`.

`cover_big` rule: prefer the first match of a number with a currency prefix or a unit (`(?:[$₹€£]\s?)?-?\d[\d,.]*\s?(?:%|billion|million|crore|lakh|bn|mn|points|pts)` and `[$₹€£]\s?-?\d[\d,.]*`); else the first standalone number of two or more digits; else the first two words of the headline with trailing punctuation stripped. Never empty.

- [ ] **Step 1: Write the failing tests**

```python
from newshouse.edition_config import EditionConfig
from newshouse.present import colour_world, cover_big, team_for, visual_for

CFG = EditionConfig(colours_topic={"gurgaon-local": "sky", "ai-models": "forest"},
                    teams={"barcelona": {"primary": "#A50044", "secondary": "#004D98"}})

def card(**kw):
    base = dict(headline="H", line="L", topics=["ai-models"], tone=None, breaking=False,
                format="A", payload={}, chapter=0)
    base.update(kw); return base

def test_lead_is_forest_and_second_cannot_be():
    w0 = colour_world(card(), position=0, previous=[], cfg=CFG)
    assert w0.name == "forest" and w0.fill == "#12372A" and w0.label == "#A8F0C6"
    w1 = colour_world(card(topics=["ai-models"]), position=1, previous=["forest"], cfg=CFG)
    assert w1.name != "forest"

def test_tone_good_is_mint_light():
    assert colour_world(card(tone="good"), position=3, previous=["white"], cfg=CFG).fill == "#D9F5E3"

def test_team_colours_on_barca():
    c = card(topics=["football"], headline="Koundé out vs Alavés; Barça short at the back")
    assert team_for(c, CFG) == "barcelona"
    assert colour_world(c, position=2, previous=["white"], cfg=CFG).accent == "#A50044"

def test_rhythm_tints_third_white():
    w = colour_world(card(topics=["gurgaon-local"]), position=4, previous=["white", "white"], cfg=CFG)
    assert w.name == "sky"

def test_cover_big():
    assert cover_big("Alphabet loses over $500 billion in market value after Q3 miss") == "$500 billion"
    assert cover_big("Gemini 4 Carbon tops Artificial Analysis index at 59, access limited") == "59"
    assert cover_big("Gurugram AQI drops to 125 after rain, a day after a reading of 242") == "125"
    assert cover_big("Koundé out vs Alavés; Cubarsí and Martín are the only fit centre-backs") == "Koundé out"

def test_cover_big_single_word():
    assert cover_big("Rain") == "Rain"

def test_visual_for_maps_formats():
    assert visual_for(card(format="C", payload={"series": []}))["kind"] == "chart"
    v = visual_for(card(headline="Delhi lifts curbs"))
    assert v == {"kind": "cover", "payload": {"big": "Delhi lifts", "label": "", "line": "L"}}
```

- [ ] **Step 2: Run to verify failure, implement, run the suite, commit**

```bash
git add newshouse/present.py tests/test_present.py
git commit -m "feat(present): colour worlds, team detection, cover text and visual mapping"
```

---

### Task 10: Self-hosted fonts and the static asset scaffold

**Files:**
- Create: `scripts/fetch_fonts.py`
- Create: `newshouse/static/fonts/` (woff2 files, OFL licence text), `newshouse/static/fonts.css`, `newshouse/static/edition.css` (empty scaffold with the token custom properties), `newshouse/static/edition.js` (empty scaffold)
- Modify: `pyproject.toml` (package data)
- Test: `tests/test_fonts.py`

**Interfaces:**
- Produces: `def parse_font_faces(css: str) -> list[dict]` in `scripts/fetch_fonts.py` returning `{"family", "style", "weight", "url", "unicode_range"}` per `@font-face` block; `def fetch(out_dir: Path) -> list[Path]` downloads the `latin` subset woff2 of Fraunces (`ital,opsz,wght@0,9..144,400..700;1,9..144,400..700`) and DM Sans (`opsz,wght@9..40,400..700`) using a Chrome user agent, saves `fraunces-latin.woff2`, `fraunces-italic-latin.woff2`, `dmsans-latin.woff2`, and writes `fonts.css` with `@font-face` rules using `url(fonts/<file>)`, `font-display: swap`, weight and optical-size ranges; `pyproject.toml` gets `[tool.setuptools.package-data] newshouse = ["static/*", "static/fonts/*", "templates/*", "llm/prompts/*"]`.

- [ ] **Step 1: Write the failing tests**

```python
from pathlib import Path
from importlib import resources
import importlib.util

FONTS = resources.files("newshouse").joinpath("static/fonts")

def test_parse_font_faces_reads_google_css():
    spec = importlib.util.spec_from_file_location("ff", Path("scripts/fetch_fonts.py"))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    css = "/* latin */\n@font-face {\n  font-family: 'DM Sans';\n  font-style: normal;\n  font-weight: 400 700;\n  src: url(https://fonts.gstatic.com/s/x.woff2) format('woff2');\n  unicode-range: U+0000-00FF;\n}\n"
    faces = mod.parse_font_faces(css)
    assert faces == [{"family": "DM Sans", "style": "normal", "weight": "400 700",
                      "url": "https://fonts.gstatic.com/s/x.woff2", "unicode_range": "U+0000-00FF"}]

def test_font_files_are_committed():
    for name in ("fraunces-latin.woff2", "fraunces-italic-latin.woff2", "dmsans-latin.woff2"):
        assert FONTS.joinpath(name).stat().st_size > 10_000
    css = resources.files("newshouse").joinpath("static/fonts.css").read_text()
    assert "font-family: 'Fraunces'" in css and "font-family: 'DM Sans'" in css
    assert "gstatic" not in css
```

- [ ] **Step 2: Run to verify failure, implement, run `scripts/fetch_fonts.py` once, run the suite, commit**

```bash
git add scripts/fetch_fonts.py newshouse/static pyproject.toml tests/test_fonts.py
git commit -m "feat(static): self-hosted Fraunces and DM Sans, asset scaffold, package data"
```

---

### Task 11: The template rewrite: posts, visuals, Also today, end card

**Files:**
- Modify: `newshouse/templates/edition.html.j2` (rewrite)
- Modify: `newshouse/static/edition.css` (the full stylesheet)
- Modify: `newshouse/render_static.py` (`_card_view`, `render_edition`)
- Test: `tests/test_render_v2.py`, `tests/test_render.py` (adjust old assertions that name v1 classes)

**Interfaces:**
- Consumes: `colour_world`, `visual_for` (Task 9); `edition_view` with `top_ids`, `warnings`, `also[].cut_reason` (Task 4); fonts and CSS (Task 10).
- Produces: `_card_view` adds `visual` (name), `slides`, `tone`; `render_edition` adds to each template card `world: World` and `vis: dict` (from `visual_for`), inlines `fonts.css` + `edition.css` into one `<style>` and `edition.js` into one `<script>` read with `importlib.resources`, copies `static/fonts/*.woff2` to `out/fonts/`, and keeps the JSON free of template-only extras. Template structure and class names (the JS in Task 12 and the checks in Task 15 depend on them):
  - `header.masthead` with `.wordmark` and `.date`; `.progress` (sticky) with `.progress-text` and `.progress-bar > .fill`.
  - `article.post` per card with `data-card-id`, `data-world="<World.name>"`, `data-rank`; children `.post-head` (`.dot`, `.topic`, `.sub`, `.meta`), `.visual` with a `data-kind` of `cover|chart|table|timeline|versus|before-after`, `h2.headline`, `p.gist`, `.why` only when `why` is non-empty, `.post-foot` with `button.expand`.
  - The expanded parts, present in the markup but hidden: `.more` holding `.structured` (the chart or table again, sand panel), `.brief` (paragraphs; the first with `span.dropcap`), `ol.sources`, `.react` with three `button[data-action]`, `button.collapse`.
  - `section.also` with `ol.also-list` (first four `li` visible, the rest `hidden`, `button.also-more`), each `li` with `button.should-have[data-cluster-id]` and, when `cut_reason`, `span.cut`.
  - `section.end` with `.end-card` (forest), `.stats`, `.next`, `.warnings` (only when any).
  - Visual markup: `cover` is `.big` + `.label` + `.line`; `chart` is rows `.bar-row` (`.bar-label`, `.bar > .bar-fill` with inline `style="--w: 88%"`, `.bar-value`), widths relative to the largest absolute value, the largest value's bar in the post accent and the others in `track` (on a forest post: mint and forest-deep); `table` is `.rows > .row` (`.row-label`, `.row-big`, `.row-small`) from B's `columns`/`rows` (first column as label, second as big, the rest joined as small; `yours` rows get `.yours`); `timeline` from D's chapters plus `delta` as the `Today` entry; `versus` from E as `.versus > .side.for` (forest) and `.side.against` (butter) with `stands` below; `before-after` from F.
  - Colours are applied with inline custom properties on each post: `style="--fill:…;--ink:…;--body:…;--muted:…;--accent:…;--label:…;--panel:…"`.

- [ ] **Step 1: Write the failing tests**

```python
def test_render_posts_and_worlds(session, tmp_path): ...
    # seed 5 cards (A, C, B, D, E); html has 5 'class="post"'; first post data-world="forest"; no "fonts.googleapis"; '<link rel="stylesheet"' absent; (tmp_path/"out"/"fonts"/"fraunces-latin.woff2").exists()
def test_why_block_only_when_present(session, tmp_path): ...  # why "" -> no 'class="why"'; why "You run Gemini" -> one
def test_cover_fallback_for_plain_card(session, tmp_path): ...  # format A -> data-kind="cover" and the cover_big text
def test_also_shows_cut_reason_and_hidden_rest(session, tmp_path): ...  # 6 also rows, one with cut_reason -> 'class="cut"' once, two li hidden
def test_render_empty_edition(session, tmp_path): ...  # no cards -> page renders, progress text "0 posts", end card present
def test_json_has_no_template_extras(session, tmp_path): ...  # JSON card keys exclude "world" and "vis"
```

- [ ] **Step 2: Run to verify failure, implement, run the suite, commit**

```bash
git add newshouse/templates/edition.html.j2 newshouse/static/edition.css newshouse/render_static.py tests/test_render_v2.py tests/test_render.py
git commit -m "feat(render): posts in the Calm Forest look with visuals, Also today, end card"
```

---

### Task 12: Page behaviour: expand in place, reactions with a queue, seen and read, motion

**Files:**
- Modify: `newshouse/static/edition.js`
- Modify: `newshouse/static/edition.css` (motion rules)
- Modify: `newshouse/templates/edition.html.j2` (`<body data-feedback-url="/feedback" data-edition-id="…">`)
- Test: `tests/test_render_v2.py` (markup hooks), `tests/test_page_js.py`

**Interfaces:**
- Produces: `edition.js` as an IIFE with these behaviours, each a named function so the smoke test can grep for them: `expand(post)` toggles `.open` on the post, sets `aria-expanded`, pushes `#card-<id>` with `history.replaceState`, and sends `read`; on load, a matching hash opens that post and scrolls to it. `send(action, ids, payload)` posts JSON to `data-feedback-url`, and on any failure appends to a `localStorage` queue `nh.queue` that `flush()` retries on load; the queue entry is removed only on a 2xx response. `observeSeen()` uses `IntersectionObserver` with threshold 1.0 and a 1500 ms timer per post to send `seen` once, and updates `.progress-text` to `<n> of <total> seen` and the `.fill` width. `reactions()` wires `.react button[data-action]`, `.should-have` (action `should_have` with `cluster_id`), `.also-more`. `motion()` adds `.in` to posts as they enter the viewport (CSS does the transition) and starts the count-up on `.big` elements whose text is numeric (digits with optional sign, currency and unit kept as prefix/suffix text) over 700 ms; it does nothing when `matchMedia('(prefers-reduced-motion: reduce)')` matches. Keyboard: Enter or Space on a focused `.post-head` expands.

- [ ] **Step 1: Write the failing tests**

```python
def test_body_carries_feedback_hooks(session, tmp_path): ...  # 'data-feedback-url="/feedback"' and data-edition-id in html
def test_js_inlined_with_named_behaviours(session, tmp_path): ...
    # html contains "function expand(", "function send(", "function flush(", "function observeSeen(", "function motion(", and "prefers-reduced-motion"
def test_css_motion_is_gated(): ...  # edition.css: every "transition" or "animation" line sits inside "@media (prefers-reduced-motion: no-preference)"
```

- [ ] **Step 2: Run to verify failure, implement, run the suite, commit**

```bash
git add newshouse/static/edition.js newshouse/static/edition.css newshouse/templates/edition.html.j2 tests/test_render_v2.py tests/test_page_js.py
git commit -m "feat(page): expand in place, reactions with an offline queue, seen and read events, gated motion"
```

---

### Task 13: Archive index

**Files:**
- Modify: `newshouse/render_static.py`
- Create: `newshouse/templates/index.html.j2`
- Test: `tests/test_render_v2.py`

**Interfaces:**
- Produces: `def render_index(session, out_dir: Path) -> Path` writing `out/index.html`: every edition with `built_at` set, newest first, as a list of `a[href="<date>.html"]` with the date, card count and est minutes, in the same look (sand page, white rows). `render_edition` calls `render_index` after writing the page. `tick` keeps copying `latest.html`.

- [ ] **Step 1: Write the failing test**

```python
def test_index_lists_editions_newest_first(session, tmp_path): ...
    # two built editions 2026-10-29 and 2026-10-30 -> index.html exists, "2026-10-30.html" appears before "2026-10-29.html"
```

- [ ] **Step 2: Run to verify failure, implement, run the suite, commit**

```bash
git add newshouse/render_static.py newshouse/templates/index.html.j2 tests/test_render_v2.py
git commit -m "feat(render): archive index of editions"
```

---

### Task 14: `newshouse serve`: the page and the feedback endpoint

**Files:**
- Create: `newshouse/serve.py`
- Modify: `newshouse/cli.py`
- Create: `launchd/com.bisati.news-house.serve.plist.template`
- Modify: `README.md` (a "Reading it on the phone" section)
- Test: `tests/test_serve.py`

**Interfaces:**
- Produces: `class FeedbackHandler(http.server.SimpleHTTPRequestHandler)` serving files from `out_dir` (directory set via `functools.partial(FeedbackHandler, directory=str(out_dir))`), `GET /` redirecting to `/latest.html`, `POST /feedback` reading a JSON body `{"action": str, "card_id"?: str, "cluster_id"?: str, "payload"?: dict}`, calling `record_feedback` inside `session_scope(engine)` and answering `201 {"id": ...}`; `400 {"error": ...}` on bad JSON, unknown action, missing ids, or a `card_id`/`cluster_id` that does not exist; `def make_server(out_dir: Path, *, host: str = "0.0.0.0", port: int = 8787, engine=None) -> http.server.ThreadingHTTPServer`; `def serve(out_dir, *, host, port) -> None` (blocks). CLI: `newshouse serve [--out out] [--port 8787] [--host 0.0.0.0]`. The plist template runs `newshouse serve` with `KeepAlive` true, patterned on the tick template (`@REPO@`, `@HOME@` placeholders).

- [ ] **Step 1: Write the failing tests**

```python
import json, threading, httpx
from newshouse.serve import make_server

def test_serve_page_and_feedback(session, tmp_path): ...
    # seed a card "card0"; (tmp_path/"out"/"latest.html").write_text("<p>hi</p>")
    # srv = make_server(tmp_path/"out", host="127.0.0.1", port=0, engine=session.get_bind()); thread start
    # GET /latest.html -> 200 "hi"; GET / -> 302 to /latest.html
    # POST /feedback {"action":"worth","card_id":"card0"} -> 201 with id; Feedback row exists
def test_serve_rejects_bad_feedback(session, tmp_path): ...
    # action "like" -> 400; card_id "nope" -> 400; body "not json" -> 400; no Feedback rows
```

- [ ] **Step 2: Run to verify failure, implement, run the suite, commit**

```bash
git add newshouse/serve.py newshouse/cli.py launchd/com.bisati.news-house.serve.plist.template README.md tests/test_serve.py
git commit -m "feat(serve): local server for the page and POST /feedback with a launchd template"
```

---

### Task 15: Screenshot and layout check script

**Files:**
- Create: `scripts/shot.py`
- Test: `tests/test_shot.py`

**Interfaces:**
- Produces: `SIZES = [(390, 844), (430, 932), (768, 1024), (1280, 800)]`; `def inject_checks(html: str) -> str` appending a `<script>` that, after fonts load, measures `document.documentElement.scrollWidth > innerWidth` (overflow), the smallest computed `font-size` of any visible text element, any `.visual` with zero height, and the tallest collapsed `.post` height divided by `innerHeight`, and writes `JSON.stringify({...})` into `document.title` prefixed `NHCHECK:`; `def parse_report(dom: str) -> dict` reading that title; `def chrome_path() -> str | None` from `$CHROME` or the default Mac path; `def shoot(html_path: Path, out_dir: Path, *, chrome: str) -> dict[str, dict]` running Chrome headless twice per size (`--screenshot` to `out_dir/<w>x<h>.png`, and `--dump-dom` on the injected copy) with `--virtual-time-budget=8000`; `def main(argv)` printing the reports and exiting 1 when any report has `overflow`, `min_font < 11`, `empty_visual`, or `tallest_post > 1.4`.

- [ ] **Step 1: Write the failing tests**

```python
def test_inject_and_parse_round_trip(): ...
    # inject_checks("<html><body></body></html>") contains "NHCHECK:"; parse_report('<title>NHCHECK:{"overflow":false,"min_font":15,"empty_visual":0,"tallest_post":0.9}</title>') == {...}
@pytest.mark.skipif(chrome_path() is None, reason="no Chrome")
def test_shoot_real_page(session, tmp_path): ...  # render a 3-card edition, shoot it, every report has overflow False and min_font >= 11
```

- [ ] **Step 2: Run to verify failure, implement, run the suite, commit**

```bash
git add scripts/shot.py tests/test_shot.py
git commit -m "feat(qa): headless Chrome screenshots with overflow, font-size and empty-visual checks"
```

---

### Task 16: Phase 1 closure: re-render the 30 October edition, screenshots, docs

**Files:**
- Modify: `README.md` (config file, validator, serve, shot), `docs/flow.html` (add the config, validator and serve stages in the file's own flowchart style; leave the artifact republish to the controller), `docs/first-run-notes.md` (a "v2 phase 1" section with what to look at)
- No new tests; this task runs the real data.

- [ ] **Step 1: Apply the schema to the real database and re-render**

Run, from the repo root with the real `newshouse.db` present:
```bash
.venv/bin/newshouse init-db
.venv/bin/newshouse render --date 2026-10-30 --validate --out out
```
Expected: `out/2026-10-30.html` and `.json` rewritten; the JSON's `warnings` lists the v1 cards' language problems (em dashes and the like) without any model call; the command prints the path.

- [ ] **Step 2: Screenshots**

Run: `.venv/bin/python scripts/shot.py out/2026-10-30.html out/shots`
Expected: four PNGs and a report with no overflow, no font under 11px, no empty visual. Fix the CSS until it passes.

- [ ] **Step 3: Compare with the canvas**

Open the PNGs beside https://claude.ai/artifact/2QaZHh7vTv1xNJ8dshLTc5 board 1 and note the differences in `docs/first-run-notes.md` under "v2 phase 1: what differs from the mockup and why" (expected: no slides, no pitch, no photos, no live tiles, since those are phase 2 and 3).

- [ ] **Step 4: Docs and commit**

```bash
git add README.md docs/flow.html docs/first-run-notes.md
git commit -m "docs: v2 phase 1 notes, flow diagram stages, README for config, validator, serve and shot"
```

- [ ] **Step 5: Full suite one last time**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS
