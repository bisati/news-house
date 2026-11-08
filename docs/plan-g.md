# Visuals phase A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Four new visual formats (Key facts, Number in context, What changes for you, Fact sheet), the headline-first order, and two edition warnings, so most posts carry a visual that says something.

**Architecture:** Each format is a new `visual` name: payload rules in `catalogue.payload_problems`, allowed in `write.allowed_visuals`, taught in `write.system.md`, drawn by a Jinja macro and CSS on the post's inner panel. Render-time derivations (number bars, date bar) are pure functions in `present.py`. The order is a set in `present.py` the template reads.

**Tech Stack:** Python 3.14, Jinja2, plain CSS, pytest.

**Spec:** `docs/design-visuals.md` (sections 4.1–4.4, 5, 6, 7, 9; phase A in 8).

## Global Constraints

- Visual names: `key-facts`, `number`, `changes`, `factsheet` (all format letter `A`).
- Every format is at most 320px tall at 390px wide (shot.py `tallest_visual`).
- Colours only from the world variables (`--panel`, `--label`, `--hi`, `--accent`, `--ink`, `--body`, `--muted`, `--track`); no tomato.
- A failing payload costs the post its visual, never its text (unchanged retry and fallback path).
- Headline first: key-facts, changes, factsheet, chart, table, timeline, versus, before-after, pitch. Visual first: photo, number, cover, quote, a deck.
- `number` and `cover` are ladder step 3 (tint, counted as tinted) like the cover today.

## Review Focus

1. A Key facts value whose first word is capitalised ordinary English ("Contract renewal") must not fail when the word appears in the sources case-insensitively; a made-up name must fail. Test in Task 1.
2. A What changes date written "5 to 20 November" in the source covers both `from` 5 Nov and `to` 20 Nov. Test in Task 1.
3. Number in context with mismatched currencies or unparseable values falls back to the "vs" line, never bars to a wrong scale. Test in Task 2.
4. A date bar where the edition date is before `from` or after `to` draws no "today" dot. Test in Task 2.
5. An edition of fewer than 6 posts never raises `format-mix`. Test in Task 4.

---

### Task 1: Catalogue rules for the four formats

**Files:** Modify `newshouse/catalogue.py`, `newshouse/write.py` (allowed_visuals); Test `tests/test_catalogue.py`, `tests/test_write.py`.

**Interfaces:**
- Produces: `VISUALS` gains the four names; `VISUAL_FORMAT[name] == "A"`; `payload_problems(name, payload, cited=, items=)` returns problem strings per spec 4.1–4.4 and 9.1–9.2; `allowed_visuals` always includes `key-facts` and `number`, and `changes`, `factsheet` when `_unlocks_rich`.
- Helpers (module-private): `_untraced(strings, cited, items) -> list[str]` (numbers by value not in any cited item), `_unnamed(strings, cited, items) -> list[str]` (capitalised words of 3+ letters not in any cited item, case-insensitive), `_date_in(iso, cited, items) -> bool` (one cited item has the day number and the month name or 3-letter abbreviation).

- [ ] Tests: `test_key_facts_rules` (2–4 facts; label ≤14, value ≤32; "Contract renewal" passes when "contract" is in the text; "Zubimendi" absent fails; a number absent fails), `test_number_rules` (value ≤12, what ≤48, compare optional with label ≤24 and value ≤12; both numbers traced), `test_changes_rules` (2–4 rows, what ≤22, change ≤40, where ≤32 traced, from/to ISO or null, from ≤ to, "5 to 20 November" traces both dates, "Thursday" traces nothing), `test_factsheet_rules` (has 1–4, lacks 0–2, each ≤26; price ≤28 with numbers traced; status in available/preview/beta/waitlist/limited/null; where ≤24), `test_allowed_visuals` updated.
- [ ] Implement; run `.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_catalogue.py tests/test_write.py`; commit.

### Task 2: Render: macros, CSS, order, derivations

**Files:** Modify `newshouse/present.py`, `newshouse/render_static.py`, `newshouse/templates/edition.html.j2`, `newshouse/static/edition.css`; Test `tests/test_present.py`, `tests/test_render_v2.py`.

**Interfaces:**
- Produces in `present.py`: `HEADLINE_FIRST: frozenset[str]` (the Global Constraints list); `amount(s: str) -> tuple[str, float] | None` (currency `$`, `₹` (Rs, Rs., INR), `€`, `£` or `""`, and the absolute value with scales K/thousand 1e3, lakh 1e5, M/mn/million 1e6, crore/cr 1e7, B/bn/billion 1e9); `number_bars(payload) -> list[dict] | None` (two bars `{"label", "value", "w"}` widths 0–100 relative to the larger, only when both parse with the same currency); `date_bar(frm: str | None, to: str | None, today: date) -> dict | None` (`{"from": "5 Nov" | None, "to": "20 Nov" | None, "today": pct | None}`; pct only when from ≤ today ≤ to and both set).
- `colour_world` tints `number` like `cover`.
- `_present` attaches `vis["payload"]["bars"]` for number and `vis["payload"]["bar"]` for changes (edition date from `ctx["date"]`), and `c["headline_first"]`.

- [ ] Tests: `test_amount_parses_scales_and_currencies` ($465M → ("$", 4.65e8); "₹143.63 cr" → ("₹", 1.4363e9); "Rs 69.71 crore" same currency as ₹; "about half" → None), `test_number_bars_only_for_matching_currencies`, `test_date_bar_today_dot_only_inside`, `test_number_is_tinted_like_cover`, render tests that each format draws its parts and that a versus post puts the headline before the visual while a photo post puts the visual first.
- [ ] Implement; run the full suite; commit.

### Task 3: Writer prompt and sample edition

**Files:** Modify `newshouse/llm/prompts/write.system.md`, `scripts/sample_edition.py`; Test `tests/test_prompts.py` (if it pins prompt text), `tests/test_sample_edition.py`.

- [ ] Prompt: the four formats with payload shapes and limits from the spec; the story-shape → format table (spec 6); "pick the most specific format the sources fill; Key facts is the fallback, then none"; Key facts values in lowercase except names; drop "Use a cover for at most one story in four"; `number` before `cover` for a post.
- [ ] Sample edition: one card per new format; `test_sample_edition_renders_every_kind` covers them; shot.py passes at the four widths, light and dark.
- [ ] Commit.

### Task 4: Edition warnings

**Files:** Modify `newshouse/validate.py`; Test `tests/test_validate.py`.

- [ ] `visual-share`: fewer than 80% of posts show a visual (a deck, a visual other than none via `present.visual_for`, which includes the photo fallback). `format-mix`: with 6 or more posts, one shown kind (cover and number counted together as `number`) above a third of posts. Tests for both, including an edition of 5 posts that never raises `format-mix`.
- [ ] Commit; then the test page from the latest edition rewritten on a DB copy, shot checks, final review.
