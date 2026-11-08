# News House v2, Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The writer picks each story's visual from the full catalogue (cover, chart, table, timeline, versus, before-after, pitch, photo, quote), writes slide decks for text-heavy stories, and sets a tone; the page renders all of it, and a real edition arrives with decks.

**Architecture:** A new pure module, `newshouse/catalogue.py`, owns the visual and slide vocabulary: names, payload checks, slide checks, and the mapping to v1 format letters. The writer, the edition validator and the renderer all call it, so one rule lives in one place. Enrich learns to read a preview image; classify learns tone. The writer's reply gains `visual`, `slides` and `tone`; a reply whose text is good but whose visual is bad keeps its text and falls back to a cover, with a warning, instead of being thrown away. The page gains three visual templates and a scroll-snap carousel. Phase 1's deferred items that touch the same code ride along: stable card ids across `--force`, the expand motion and header chevron, the outlet-stripper guard, and dead code.

**Tech Stack:** Python 3.12+, SQLAlchemy 2, pydantic 2, Jinja2, httpx, trafilatura, stdlib `html.parser`; pytest; headless Chrome (dev only).

**Spec:** `docs/design-v2.md`, sections 3.3 to 3.7, 3.10, 4.1 (tone only), 4.3, 4.4, 4.5 (shapes and fallbacks), 4.6, 5, and phase 2 in section 7. Where this plan and the spec disagree, the spec wins, except for the rulings listed below, which settle places where the spec contradicts itself or is silent.

## Rulings made in this plan (Mihir can overturn any of them)

1. **`visual` replaces `format` in the writer's reply.** `Card.format` is still stored, derived from the visual (`chart` to C, `table` to B, `timeline` to D, `versus` to E, `before-after` to F, everything else A), so v1 code and the 30 October edition keep working. A reply that still sends a v1 `format` and no `visual` is mapped the same way, so an old-style reply is not an error.
2. **A bad visual never costs the story its text.** When the writer's text passes but its visual or slides still fail after the retry, the card keeps the text, gets an automatic cover and no slides, and the edition carries a `payload-fallback` warning. v1's teaser fallback stays only for a reply whose text fails.
3. **Photo posts carry no text on the image.** Spec 3.4's table says "kicker overlaid at the top-left"; its rules say "keeps the kicker and headline below the image, never on it". The rule wins: only a small credit sits on the image, bottom right.
4. **Pitch rows run from the back line forward** and render bottom to top, so the first row sits nearest the bottom edge.
5. **Truth checks on the new payloads.** A cover's `big` may hold at most 14 characters, and any digits in it must appear in a cited item. A quote's text must appear in its item (case, spacing and quote marks ignored). Every pitch name must appear in a cited item. A photo's item must be cited and must have an image.
6. **`what-next` slides hold at most 60 words** (spec 3.5 says "two short paragraphs" without a number).
7. **Expand motion uses opacity and a small rise, not `max-height`.** Spec 3.10 asks for max-height growth, but the project rule is transform and opacity only. The chevron rotates.
8. **`headline-long` no longer triggers a model retry.** It is a soft rule (spec 4.3), and each retry is an Opus call. It stays a warning.
9. **Tone disagreements are logged without a reason.** The run log records `{card_id: [classify tone, writer tone]}`; asking the writer to explain costs tokens for no reader benefit.
10. **Card ids are stable per edition and cluster**, so a reaction survives `build --force`.

## Global Constraints

- Work on branch `v2/phase-2` off `main` (main is at `ec1a176`, the squash of phase 1). One commit per task; messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- No new runtime dependencies. Never commit `newshouse.db`, `out/`, `profile.md`. Secrets only in `~/.config/news-house/*.env`.
- No model call in `render`, in the validator's report mode, or in any test. Tests use `newshouse/llm/fake.py` (`FakeBackend`) and `tests/helpers.py` (`seed_edition`).
- Colour tokens exactly as spec 3.1 (see `newshouse/present.py`, `PALETTE`). Text on tomato is forest, never white. Radii: post 14px, inner panel 10px, buttons 8px, bars 4px. No shadows, no gradients, no emoji. Tap targets at least 44px. No text under 11px.
- All motion is `transform`/`opacity` only, inside the single `@media (prefers-reduced-motion: no-preference)` block in `edition.css` (a test counts it).
- Schema changes are additive with defaults through `ensure_columns`; the 30 October 2026 edition must re-render without a rebuild and look as it does today.
- Images: only `https` URLs, only from items whose sources are not Google News (`kind == "gnews"`), hotlinked, never downloaded or re-hosted. A broken image shows the cover fallback.
- Slides: zero, or two to four. Slide 1 is a `cover`. Kinds: `cover`, `chart`, `table`, `text` (body 35 words or fewer, title 4 words or fewer), `what-next` (60 words or fewer). Every number on a slide appears in the brief. Slide fills in order: butter, sand, tomato, forest (`present.SLIDE_FILLS`); the writer never picks colours.
- Headline: 12 words soft (warning only), 90 characters hard (`write.HEADLINE_MAX`). Gist (`line`): 40 words or fewer.
- The existing 275 tests keep passing. A test may change only where this plan changes the behaviour it pins, and the task says which.

## Review Focus

- A reply whose text is good but whose deck has a number missing from the brief, twice in a row: the card keeps the writer's headline, gist and brief, shows an automatic cover, has no slides, is not marked unverified, and the edition warns `payload-fallback`. Test in Task 4 (`test_bad_deck_keeps_text`).
- A photo whose image URL 404s or is blocked by the publisher: the post shows the cover fallback, never an empty panel or a broken-image icon. Test in Task 7 (`test_photo_renders_with_hidden_cover_fallback`) and the sample-edition shot in Task 11.
- An `og:image` that is relative, `http:`, `data:` or `javascript:`: it is never stored, and a stored bad URL is never rendered. Tests in Task 2 (`test_extract_image_rejects_non_https`) and Task 6 (`test_photo_with_unsafe_url_falls_back_to_cover`).
- The 30 October edition (v1 cards: `visual` "cover", `format` B to F, `slides` []): every card renders the same kind of visual as before phase 2. Test in Task 6 (`test_legacy_formats_render_as_before`).
- A rebuild with `--force` that selects the same clusters: card ids are the same as before, so a `worth` reaction recorded on the first build still points at a card. Test in Task 5 (`test_force_rebuild_keeps_card_ids`).

---

### Task 1: The catalogue module, schema columns

**Files:**
- Create: `newshouse/catalogue.py`
- Modify: `newshouse/models.py` (add columns), `newshouse/write.py` (move `_payload_problems` out, keep the name importable)
- Test: `tests/test_catalogue.py`, `tests/test_models.py`

**Interfaces:**
- Produces, in `newshouse/catalogue.py`:
  - `VISUALS = ("cover", "chart", "table", "timeline", "versus", "before-after", "pitch", "photo", "quote")`
  - `SLIDE_KINDS = ("cover", "chart", "table", "text", "what-next")`
  - `TONES = ("good", "bad", "mixed", "neutral")`
  - `VISUAL_FORMAT: dict[str, str]` (chart C, table B, timeline D, versus E, before-after F, all others A) and `FORMAT_VISUAL` (its inverse for B to F).
  - `@dataclass(frozen=True) class ItemFacts: text: str; image_url: str | None = None` (text is title, teaser and body joined by newlines).
  - `effective_visual(visual: str | None, format: str | None) -> str`: `visual` when it is a catalogue name other than `cover`; else `FORMAT_VISUAL.get(format, "cover")`.
  - `format_payload_problems(fmt, payload, cited, expected_chapters=None) -> list[str]`: the current `write._payload_problems`, moved verbatim. `write._payload_problems` stays as an alias so `validate.py` and tests keep importing it.
  - `payload_problems(visual: str, payload, *, cited: set[str], items: dict[str, ItemFacts], expected_chapters: list[dict] | None = None) -> list[str]`
  - `visual_seconds(visual: str, slides: list) -> int`: 50 when `slides` is non-empty or `visual` is chart, table, timeline or pitch; else 35.
- Produces, in `newshouse/models.py`: `Item.image_url: str | None`, `Item.image_w: int | None`, `Item.image_h: int | None`, `Cluster.tone: str | None`. All nullable, no default.

- [ ] **Step 1: Write the failing tests** in `tests/test_catalogue.py`:

```python
from newshouse.catalogue import (ItemFacts, effective_visual, payload_problems, visual_seconds)

ITEMS = {"i1": ItemFacts(text="Alphabet fell 13% on Thursday. 'We will spend more,' said Ashkenazi.\nBalde and Kounde start; Kounde out with an ankle knock.",
                         image_url="https://img.example.com/a.jpg"),
         "i2": ItemFacts(text="No image here.")}

def test_effective_visual_maps_legacy_formats():
    assert effective_visual("cover", "B") == "table"
    assert effective_visual(None, "C") == "chart"
    assert effective_visual("quote", "A") == "quote"
    assert effective_visual("cover", "A") == "cover"
    assert effective_visual("nonsense", "A") == "cover"

def test_cover_payload_empty_or_short_big():
    assert payload_problems("cover", {}, cited={"i1"}, items=ITEMS) == []
    assert payload_problems("cover", {"big": "-13%", "label": "Thursday", "line": "Worst day."},
                            cited={"i1"}, items=ITEMS) == []
    assert payload_problems("cover", {"big": "x" * 15}, cited={"i1"}, items=ITEMS)

def test_cover_digits_must_be_in_a_cited_item():
    assert payload_problems("cover", {"big": "-14%"}, cited={"i1"}, items=ITEMS)

def test_quote_text_must_appear_in_its_item():
    ok = {"text": "We will spend   MORE", "who": "Anat Ashkenazi", "where": "earnings call", "item_id": "i1"}
    assert payload_problems("quote", ok, cited={"i1"}, items=ITEMS) == []
    bad = {**ok, "text": "We will spend less"}
    assert payload_problems("quote", bad, cited={"i1"}, items=ITEMS)
    assert payload_problems("quote", ok, cited={"i2"}, items=ITEMS)  # item not cited

def test_pitch_names_must_appear_in_cited_items():
    p = {"rows": [[{"pos": "LB", "name": "Balde"}]], "note": "Predicted, per a fan site",
         "out": [{"name": "Kounde", "why": "ankle"}]}
    assert payload_problems("pitch", p, cited={"i1"}, items=ITEMS) == []
    p2 = {**p, "rows": [[{"pos": "ST", "name": "Haaland"}]]}
    assert any("Haaland" in x for x in payload_problems("pitch", p2, cited={"i1"}, items=ITEMS))

def test_photo_item_must_be_cited_and_have_an_image():
    ok = {"item_id": "i1", "alt": "Sundar Pichai on stage", "credit": "Wire"}
    assert payload_problems("photo", ok, cited={"i1"}, items=ITEMS) == []
    assert payload_problems("photo", {**ok, "item_id": "i2"}, cited={"i2"}, items=ITEMS)

def test_v1_visuals_delegate_to_format_rules():
    assert payload_problems("chart", {"series": []}, cited=set(), items={})
    assert payload_problems("before-after", {"before": "a", "after": "b", "effective": "c",
                                             "applies_to": "d"}, cited=set(), items={}) == []

def test_unknown_visual_is_a_problem():
    assert payload_problems("hologram", {}, cited=set(), items={})

def test_visual_seconds():
    assert visual_seconds("cover", []) == 35
    assert visual_seconds("cover", [{}, {}]) == 50
    assert visual_seconds("chart", []) == 50
```

And in `tests/test_models.py`, `test_phase2_columns_exist`: an `Item` stores and reloads `image_url`, `image_w`, `image_h`; a `Cluster` stores `tone="bad"`; `ensure_columns` on a database created without these columns adds all four (follow the existing `ensure_columns` test's pattern).

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_catalogue.py tests/test_models.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement.** Normalise text for the quote and pitch checks by lowercasing, folding curly quotes and apostrophes to straight ones, and collapsing whitespace. Digits for the cover check are `re.findall(r"\d+", ...)`; each must occur in the digits of some cited item. Pitch: `rows` a non-empty list of non-empty lists of `{pos, name}` strings, `note` non-empty, `out` an optional list of `{name, why}`; every name (rows and out) must occur in the normalised text of some cited item. Quote: `text`, `who`, `item_id` non-empty; `where` a string. Photo: `item_id`, `alt` non-empty; `credit` a string. Every problem string names the field, as `format_payload_problems` does.
- [ ] **Step 4: Run** the full suite: `.venv/bin/python -m pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** `feat(catalogue): visual catalogue rules and phase 2 columns`.

---

### Task 2: Slide checks

**Files:**
- Modify: `newshouse/catalogue.py`
- Test: `tests/test_catalogue.py`

**Interfaces:**
- Produces: `slide_problems(slides, *, brief: str, cited: set[str], items: dict[str, ItemFacts]) -> list[str]`. Each slide is `{"kind", "title", "body", "payload"}`.

- [ ] **Step 1: Write the failing tests:**

```python
BRIEF = "Revenue was $127.58B against $127.97B expected.\n\nAbout $500 billion was wiped off.\n\nWhat to watch next: the Q4 call."
def deck(*slides): return list(slides)
COVER = {"kind": "cover", "title": "", "body": "Worst day ever.", "payload": {"big": "$500B", "label": "The damage"}}
NEXT = {"kind": "what-next", "title": "What next", "body": "The Q4 call explains capex.", "payload": {}}

def test_empty_deck_is_fine():
    assert slide_problems([], brief=BRIEF, cited=set(), items={}) == []

def test_deck_needs_two_to_four_slides_and_cover_first():
    assert slide_problems([COVER], brief=BRIEF, cited=set(), items={})
    assert slide_problems([COVER] * 5, brief=BRIEF, cited=set(), items={})
    assert slide_problems([NEXT, COVER], brief=BRIEF, cited=set(), items={})
    assert slide_problems([COVER, NEXT], brief=BRIEF, cited=set(), items={}) == []

def test_slide_numbers_must_be_in_the_brief():
    bad = {**COVER, "payload": {"big": "$600B"}}
    assert any("600" in p for p in slide_problems([bad, NEXT], brief=BRIEF, cited=set(), items={}))

def test_text_slide_limits():
    long_body = {"kind": "text", "title": "One two three four five", "body": "word " * 36, "payload": {}}
    probs = slide_problems([COVER, long_body], brief=BRIEF, cited=set(), items={})
    assert any("title" in p for p in probs) and any("35" in p for p in probs)

def test_what_next_is_last_when_brief_has_watch_line():
    text = {"kind": "text", "title": "The miss", "body": "Revenue missed.", "payload": {}}
    assert slide_problems([COVER, text], brief=BRIEF, cited=set(), items={})  # brief has the line, no what-next
    assert slide_problems([COVER, NEXT, text], brief=BRIEF, cited=set(), items={})  # what-next not last

def test_chart_and_table_slides_use_their_payload_rules():
    table = {"kind": "table", "title": "The miss", "body": "", "payload": {"columns": ["x"], "rows": []}}
    assert slide_problems([COVER, table], brief=BRIEF, cited=set(), items={})
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_catalogue.py -q`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.** The numbers rule: collect `re.findall(r"\d+", ...)` over each slide's title, body and every string or number inside its payload (numbers via `format(v, "g")`); each must be in the set of digit runs of the brief. A cover slide's payload is checked with `payload_problems("cover", ...)`, including its 14-character and cited-digits rules; the brief rule applies on top. Chart and table slides use `format_payload_problems("C" | "B", ...)`. `what-next` body 60 words or fewer; it must be last when present, and must be present and last when the brief contains `What to watch next:`. Problem strings start with `slides[n]` so the writer can find the slide.
- [ ] **Step 4: Run** the full suite. Expected: all pass.
- [ ] **Step 5: Commit** `feat(catalogue): slide deck rules`.

---

### Task 3: Images at enrich, tone at classify

**Files:**
- Modify: `newshouse/enrich.py`, `newshouse/classify.py`, `newshouse/llm/schemas.py`, `newshouse/llm/prompts/classify.system.md`
- Test: `tests/test_enrich.py`, `tests/test_classify.py`, `tests/test_prompts.py`

**Interfaces:**
- Produces: `extract_image(html: str) -> tuple[str | None, int | None, int | None]` in `enrich.py`: the first absolute `https://` URL among, in this order, `<meta property="og:image">` (also `og:image:secure_url`), `<meta name="twitter:image">`, `<link rel="image_src">`; width and height from `og:image:width` / `og:image:height` when they are integers. Uses `html.parser.HTMLParser`.
- `enrich_clusters` stores `Item.image_url/_w/_h` for every item it fetches HTML for, whether or not a body was extracted, and only when the item's sources include one whose `kind != "gnews"`. The function's return value (bodies stored) is unchanged.
- `Cluster.tone` set by `classify_clusters` from the reply's `tone` when it is in `catalogue.TONES`, else `None`.

- [ ] **Step 1: Write the failing tests.** In `tests/test_enrich.py`:
  - `test_extract_image_prefers_og_image`: HTML with twitter and og tags returns the og URL and its width and height (`1200`, `630`).
  - `test_extract_image_rejects_non_https`: relative `/a.jpg`, `http://x/a.jpg`, `data:image/png;base64,AA`, `javascript:alert(1)` each return `(None, None, None)`; a later valid https tag is still found after an invalid og tag.
  - `test_enrich_stores_image_even_without_body`: with the existing fake-client pattern, a page whose body is too short still stores `image_url`.
  In `tests/test_classify.py`, `test_classify_stores_tone`: a fake reply with `"tone": "bad"` sets `Cluster.tone == "bad"`; `"tone": "angry"` or a missing key leaves `None`. In `tests/test_prompts.py`, `test_classify_prompt_defines_tone`: the prompt contains `` `tone` `` and the four values.
- [ ] **Step 2: Run** the three test files. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.** Add `tone` (`{"type": "string", "enum": [...TONES]}`) to `_CLASSIFY_FIELDS`, so it is required for the real model; the reader stays lenient as above. Prompt text to add after `is_delta`: `` `tone`: good, bad, mixed or neutral, from the reader's point of view: good when it helps him (a price cut, a win for his team), bad when it costs him (a curb on his commute, a loss), mixed when both, neutral otherwise. `` Add `tone` to the field list in the prompt's last rule.
- [ ] **Step 4: Run** the full suite. Expected: all pass.
- [ ] **Step 5: Commit** `feat(enrich,classify): preview images and tone`.

---

### Task 4: The writer learns the catalogue

**Files:**
- Modify: `newshouse/write.py`, `newshouse/llm/schemas.py`, `newshouse/llm/prompts/write.system.md`
- Test: `tests/test_write.py`, `tests/test_prompts.py`

**Interfaces:**
- Consumes: Task 1 and Task 2 functions; `Item.image_url`; `Cluster.tone`.
- Produces:
  - `allowed_visuals(cluster, items, sources_by_item) -> list[str]`: always `cover` and `quote`; `timeline` when `cluster.chapter >= 2`; `chart`, `table`, `versus`, `before-after` under the same condition that today unlocks B, C, E, F; `pitch` under that condition when `"football" in cluster.topics`; `photo` when a shown item has `image_url` and a non-gnews source. `allowed_formats` stays for v1 callers.
  - `item_facts(items, sources_by_item) -> dict[str, ItemFacts]` (image only for non-gnews items).
  - `write_card(..., notes: list[str] | None = None)`: appends one line per visual fallback (Ruling 2). Signature otherwise unchanged; still returns a `Card`.
  - The `Card` it returns has `visual`, `slides`, `tone` set and `format = VISUAL_FORMAT[visual]`, `est_seconds = visual_seconds(visual, slides)`.
- `WRITE_SCHEMA` fields: `visual` (enum `VISUALS`), `headline`, `line`, `para`, `brief`, `why`, `cited_item_ids`, `payload`, `slides` (array of objects with `kind` enum `SLIDE_KINDS`, `title`, `body` strings, `payload` object, all required), `tone` (enum `TONES`). `format` is no longer in the schema.

- [ ] **Step 1: Write the failing tests** in `tests/test_write.py` (reuse the file's existing cluster fixtures):
  - `test_allowed_visuals`: a plain cluster with teaser-only items gives `["cover", "quote"]`; adding an enriched non-gnews item adds chart, table, versus and before-after; football adds pitch; chapter 2 adds timeline; an item with `image_url` adds photo, but not when its only source is gnews.
  - `test_writer_input_lists_visuals_tone_and_images`: `render_cluster_for_write` output contains `Allowed visuals: cover, quote`, `tone (from classify): bad` when the cluster has one, and `image: https://...` under an item with an image.
  - `test_reply_with_deck_is_stored`: a fake reply with `visual: "cover"`, a valid two-slide deck and `tone: "bad"` yields a card with those slides, `format == "A"`, `est_seconds == 50`.
  - `test_legacy_format_reply_still_works`: a reply with `format: "C"`, a valid chart payload and no `visual`, `slides` or `tone` yields `visual == "chart"`, `slides == []`, `tone == cluster.tone`.
  - `test_bad_deck_keeps_text`: two replies, each with good text and a deck whose cover says `$600B` while the brief says `$500 billion`. The card keeps the reply's headline, line, brief; `visual == "cover"`, `payload == {}`, `slides == []`, `unverified is False`; `notes` has one entry naming `slides[0]`.
  - `test_bad_text_still_falls_back_to_teaser`: two replies with an empty headline still give the v1 teaser card, `unverified is True` (pins today's behaviour).
  - `test_visual_not_allowed_is_a_problem`: `visual: "photo"` on a cluster with no images triggers the retry, whose problem block names `photo`.
  In `tests/test_prompts.py`, `test_write_prompt_teaches_catalogue`: the prompt names every entry of `VISUALS` and `SLIDE_KINDS`, contains `35 words`, `Allowed visuals` and `tone`.
- [ ] **Step 2: Run** `tests/test_write.py tests/test_prompts.py`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.**
  - Split the reply check into text problems (citations, headline, line, para, a non-allowed visual) and visual problems (`payload_problems`, `slide_problems`, `tone` not in `TONES`). `validate_card` keeps returning their concatenation, so its current callers and tests hold.
  - Map a legacy reply first: no `visual` but a `format` letter gives `visual = FORMAT_VISUAL.get(format, "cover")`; for A, the payload must be `{}` (an automatic cover); missing `slides` is `[]`, missing `tone` is `cluster.tone`.
  - After the last attempt: no problems gives the card; text problems give `_fallback` as today; only visual problems give the card with `visual="cover"`, `payload={}`, `slides=[]` and one `notes` line: `"<headline>: <problems joined by '; '>"`.
  - Writer input: replace the `Allowed formats:` line with `Allowed visuals: ...`; add `tone (from classify): <tone>` to the header when set; add `image: <url>` after `url:` for items that have one and a non-gnews source.
  - Prompt: rewrite the "Choosing the format" section as "Choosing the visual" with the catalogue from spec 3.4 (when to use each, and its payload shape exactly as the spec's table gives it; cover payload may be `{}` to let the page choose); add a "Slides" section with spec 3.5's rules and the constraints above (one idea per slide, no slides for a single-fact story, slide 1 a cover, what-next last when the brief ends with "What to watch next:", every number also in the brief); add `tone`; state that `line` is the gist, 40 words or fewer, and must not repeat what the visual shows. Keep the priority ladder, citations, why rule, examples and rules sections; update the output-keys rule to the new key list. Keep the existing phrases that `test_prompts.py` asserts.
- [ ] **Step 4: Run** the full suite. Update only tests that assert the old schema's key list or the `Allowed formats:` line, and say which in the commit body. Expected: all pass.
- [ ] **Step 5: Commit** `feat(write): visuals, slides and tone in the writer`.

---

### Task 5: Build and edition validator on the catalogue

**Files:**
- Modify: `newshouse/build.py`, `newshouse/validate.py`
- Test: `tests/test_build.py`, `tests/test_validate.py`

**Interfaces:**
- Consumes: Task 4's `write_card(notes=...)`, Task 1/2 checks.
- Produces:
  - `card_id_for(edition_id: str, cluster_id: str) -> str` in `build.py`: `sha1(f"{edition_id}:{cluster_id}")` hex, first 32 characters. `_write_cards` sets `card.id` to it, unless a card with that id already exists in the session (a breaking card), in which case the writer's uuid stays.
  - `validate.card_problems` gains a keyword `items: dict[str, ItemFacts]` (default `{}`); its payload rule becomes `payload_problems(effective_visual(card["visual"], card["format"]), ...)` and a new `slides` rule runs `slide_problems` when `card["slides"]` is non-empty. Rule names: `payload` and `slides`.
  - `validate.cited_items(session, card) -> dict[str, ItemFacts]`: public helper used by `validate_edition` and `build._candidate_problems`. `_previous_headline` becomes public as `previous_headline` (the old name stays as an alias).

- [ ] **Step 1: Write the failing tests.** In `tests/test_build.py`:
  - `test_force_rebuild_keeps_card_ids`: build with the existing fake pipeline, record a `worth` on card 1, build again with `force=True`; the same card ids exist and the feedback row's `card_id` matches one of them.
  - `test_write_fallback_notes_become_warnings`: a fake writer whose replies always carry a bad deck; the edition's warnings include a `payload-fallback` entry for that card, and the card has `slides == []`.
  - `test_headline_long_does_not_retry`: a card whose only problem is a 13-word headline makes no second writer call (count `FakeBackend.calls` for that cluster) and keeps a `headline-long` warning.
  - `test_tone_changes_logged`: classify tone `bad`, writer tone `good` gives `stats["tone_changes"] == {card_id: ["bad", "good"]}` in the run.
  - `test_validator_fallback_clears_slides`: an edition-level `slides` problem that survives the retry sets `visual "cover"`, `payload {}`, `slides []`, `format "A"`.
  In `tests/test_validate.py`: `test_slide_problems_reported` (a seeded card with a one-slide deck gives a `slides` problem) and `test_legacy_card_payload_rule_unchanged` (a seeded format-B card with `visual "cover"` and a valid table payload gives no `payload` problem).
- [ ] **Step 2: Run** the two test files. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.** `REWRITTEN` gains `visual`, `slides`, `tone`. `_write_cards` passes a per-card notes list and stores them in `stats["write_fallbacks"]` as `{card_id: text}`; `apply_validation` appends one `payload-fallback` Problem per entry to the final warnings. The validator fallback (today `format "A"`, `payload {}`, `visual "cover"`) also clears `slides` and resets `est_seconds` with `visual_seconds("cover", [])`, and triggers on `payload` or `slides`. Exclude `headline-long` from the retry set in `apply_validation` (Ruling 8). Tone: when `card.tone != cluster.tone` and both are set, record it.
- [ ] **Step 4: Run** the full suite. Expected: all pass.
- [ ] **Step 5: Commit** `feat(build): stable card ids, catalogue validation, write fallbacks`.

---

### Task 6: Presentation for the new visuals and decks

**Files:**
- Modify: `newshouse/present.py`, `newshouse/render_static.py`
- Test: `tests/test_present.py`, `tests/test_render_v2.py`

**Interfaces:**
- Consumes: `catalogue.effective_visual`.
- Produces:
  - `visual_for(card: dict) -> dict` returns `{"kind", "payload"}` for every catalogue kind. Cover: the writer's payload when it has a non-empty `big`, else today's automatic cover (`cover_big`). Photo: payload plus `src`, the cited item's `image_url` from `card["sources"]` passed through a new `safe_image_url` (https only), and a `fallback` automatic cover; with no safe `src` the result is the automatic cover. Pitch and quote: their payloads.
  - `deck_for(card: dict, world) -> list[dict]`: one dict per slide with `kind`, `title`, `body_paras` (split on blank lines), `payload` (chart and table payloads run through the existing `_chart` / `_table` helpers, so move those two into `present.py` or call them from `render_static`), `fill` (the `SLIDE_FILLS` name by index) and `style` (CSS custom properties for that fill: butter, sand, tomato use forest ink; forest uses white ink with mint labels).
  - `render_static._sources` adds `image_url` to each source entry (safe https only, else `None`). `_present` sets `c["deck"]` from `deck_for` when the card has slides.

- [ ] **Step 1: Write the failing tests.** In `tests/test_present.py`:
  - `test_writer_cover_payload_wins`: a card with `visual "cover"` and payload `{"big": "-13%", "label": "Q3", "line": "Worst day."}` gives that payload.
  - `test_photo_with_unsafe_url_falls_back_to_cover`: a photo card whose cited source has `image_url "http://x/a.jpg"` gives kind `cover`.
  - `test_photo_has_src_and_fallback`: an https image gives kind `photo`, a `src` and a `fallback` with a non-empty `big`.
  - `test_deck_fills_follow_fixed_order`: a four-slide card gives fills `butter, sand, tomato, forest`.
  In `tests/test_render_v2.py`:
  - `test_legacy_formats_render_as_before`: seed cards of format A to F (with `visual` "cover", the existing seed shapes); the rendered `data-kind` values are `cover, table, chart, timeline, versus, before-after` in that order.
  - `test_json_has_visual_and_slides`: the edition JSON for a deck card carries `visual` and the raw `slides`, and no template extras (`deck`, `style`).
- [ ] **Step 2: Run** the two files. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** as in Interfaces. `colour_world` is unchanged; a pitch card's world is the team world when `team_for` names a team.
- [ ] **Step 4: Run** the full suite. Expected: all pass.
- [ ] **Step 5: Commit** `feat(present): visuals and decks for the page`.

---

### Task 7: Templates and styles for cover, quote, photo and pitch

**Files:**
- Modify: `newshouse/templates/edition.html.j2`, `newshouse/static/edition.css`, `newshouse/static/edition.js`
- Test: `tests/test_render_v2.py`, `tests/test_page_js.py`

**Interfaces:**
- Consumes: Task 6's `vis` shapes.
- Produces: markup `div.visual[data-kind="quote"]` (`blockquote` in Fraunces with `.who` and `.where`), `div.visual[data-kind="photo"]` (`img.photo` with `src`, `alt`, `loading="lazy"`, `referrerpolicy="no-referrer"`, a `.credit` chip, and the fallback cover rendered inside the same panel with the `hidden` attribute), `div.visual[data-kind="pitch"]` (`.pitch` with one `.pitch-row` per row in reverse order, each `.player` a disc plus name; an `.out` chip list; `.note` caption). JS `photoFallback()` swaps a failed image for its hidden cover on `error`, and also when the image is already `complete` with `naturalWidth === 0` at start.

- [ ] **Step 1: Write the failing tests.** In `tests/test_render_v2.py`:
  - `test_quote_renders`: a quote card shows its text inside `blockquote` and the speaker.
  - `test_photo_renders_with_hidden_cover_fallback`: the page has `img.photo` with the https `src`, `referrerpolicy="no-referrer"`, and a sibling cover with `hidden`; the headline is outside the `.visual` element.
  - `test_pitch_renders_rows_back_to_front`: rows `[[LB Balde, CB Cubarsi], [ST Lewandowski]]` render with Lewandowski's row before Balde's row in the HTML (the top of the pitch first), an `out` chip `Kounde · ankle`, and the team colours as `--accent` / `--secondary` on a Barça card.
  In `tests/test_page_js.py`, extend the names list with `photoFallback`.
- [ ] **Step 2: Run** the two files. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.** Styles: quote on the world's `--panel`, text 24 to 28px Fraunces 600 with an opening mark in `--accent`; photo `object-fit: cover`, panel height 240px at 390 wide, credit 11px in sand text on a solid forest chip; pitch panel `--panel` with hairline field markings (centre line, centre circle, one box) in `--track`, discs 36px filled `--accent` with a 3px `--secondary` ring (forest ring when no secondary), names 11px in `--ink`, at most five discs per row at 390 wide. All three stay within the 200 to 320px visual height of spec 3.3.
- [ ] **Step 4: Run** the full suite. Expected: all pass.
- [ ] **Step 5: Commit** `feat(page): quote, photo and pitch visuals`.

---

### Task 8: The slide carousel

**Files:**
- Modify: `newshouse/templates/edition.html.j2`, `newshouse/static/edition.css`, `newshouse/static/edition.js`
- Test: `tests/test_render_v2.py`, `tests/test_page_js.py`

**Interfaces:**
- Consumes: `c.deck` from Task 6.
- Produces: when a card has a deck, the post's visual slot holds `div.deck` with `div.slides` (a horizontal scroll-snap track, `role="group"`, `aria-roledescription="carousel"`, `aria-label` the headline) containing one `section.slide[data-slide-kind]` per slide, each `aria-label="n of N"`. The footer row's left holds `button.slide-prev` and `button.slide-next` (44px, `aria-label` "Previous slide" / "Next slide"), `.slide-dots` (one `span` per slide, the current one `.on`) and `.slide-count` (`1 / N`). JS `decks()` wires them: buttons scroll by one slide width; the current slide is tracked with an `IntersectionObserver` rooted on the track at threshold 0.6; left and right arrow keys move slides when focus is inside the post; expanding the post scrolls the track back to slide 1 and CSS shows only slide 1 with controls hidden (spec 3.7, "a deck collapses to its cover").

- [ ] **Step 1: Write the failing tests.** In `tests/test_render_v2.py`:
  - `test_deck_renders_slides_and_controls`: a three-slide card renders three `section.slide`, `1 / 3`, both buttons with their labels, slide fills butter, sand, tomato as `data-fill`, and no single `.visual` for that post outside the deck.
  - `test_deck_text_and_what_next_slides`: a text slide renders its title and body; a what-next slide renders two paragraphs.
  - `test_post_without_slides_has_no_deck_controls`.
  In `tests/test_page_js.py`: `decks` in the function list, and `scroll-snap-type` present in the CSS outside the motion block (snapping is not motion).
- [ ] **Step 2: Run** the two files. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.** Slide height 320px at 390 wide, padding 22px 20px, radius 10px (inner panel), layouts from the canvas board "Slides" (cover: label top, big figure, line bottom; table: title then label / big / small rows; text: title then body; what-next: mint title on forest, paragraphs, "Expand for the full brief" hint). Scrolling uses `scrollTo({left, behavior})` with `behavior` "smooth" only when reduced motion is not requested. Hide the native scrollbar. Dots change width under the motion block only.
- [ ] **Step 4: Run** the full suite. Expected: all pass.
- [ ] **Step 5: Commit** `feat(page): slide carousel`.

---

### Task 9: Expand motion and the header chevron (phase 1 deferral)

**Files:**
- Modify: `newshouse/templates/edition.html.j2`, `newshouse/static/edition.css`, `newshouse/static/edition.js`
- Test: `tests/test_render_v2.py`, `tests/test_page_js.py`

**Interfaces:**
- Produces: a `button.head-collapse` at the right of `.post-head` (44px, `aria-label` "Collapse", `aria-controls` the post's `.more`, `hidden` until open) that collapses the post; `expand()` shows it and hides it. Under the motion block, an opening `.more` fades and rises 8px over 320ms, and the Expand chevron rotates 180 degrees (Ruling 7).

- [ ] **Step 1: Write the failing tests:** `test_head_collapse_button` (every post has a hidden `button.head-collapse` with its `aria-controls`) and, in `tests/test_page_js.py`, that the motion block contains `.more` and `rotate(`, and that `max-height` appears nowhere in the CSS.
- [ ] **Step 2: Run** the two files. Expected: FAIL.
- [ ] **Step 3: Implement.** The header's existing Enter and Space handler stays. Since the post header row already shows the read time on the right, the collapse button replaces the read time while the post is open.
- [ ] **Step 4: Run** the full suite. Expected: all pass.
- [ ] **Step 5: Commit** `feat(page): expand motion and header collapse`.

---

### Task 10: Cleanup carried from phase 1

**Files:**
- Modify: `newshouse/render_static.py` (`strip_outlet`), `newshouse/validate.py` (`is_text_problem`, `TEXT_RULES`), `newshouse/select.py` (the unreachable `noise floor` cut reason, the v1 `select_edition` and its now-unused settings fields if nothing outside tests calls them), `newshouse/config.py`
- Test: `tests/test_render_v2.py`, `tests/test_select.py`, `tests/test_validate.py`

**Interfaces:**
- Produces: `strip_outlet(title: str, *, gnews: bool) -> str`: strips a trailing ` - <Outlet>` only when `gnews` is true. `latest_title` passes whether the newest item has a gnews source.

- [ ] **Step 1: Write the failing test:** `test_strip_outlet_only_for_gnews`: `"Kohli - the final chapter"` is unchanged with `gnews=False`; `"RBI holds rates - Mint"` loses `" - Mint"` with `gnews=True`.
- [ ] **Step 2: Run** it. Expected: FAIL.
- [ ] **Step 3: Implement**, then delete dead code: `is_text_problem` and `TEXT_RULES` (grep first; delete only if unused outside tests, and delete their tests with them); the `noise floor` reason string if no branch can produce it. Remove v1 `select_edition` and its tests only if `grep -rn "select_edition(" newshouse` shows no caller besides `select_edition_v2`'s own module; otherwise leave it and note why in the commit body.
- [ ] **Step 4: Run** the full suite. Expected: all pass.
- [ ] **Step 5: Commit** `chore: phase 1 leftovers (outlet stripper, dead code)`.

---

### Task 11: Sample edition, layout checks, docs

**Files:**
- Create: `scripts/sample_edition.py`
- Modify: `scripts/shot.py`, `README.md`, `docs/flow.html`, `docs/first-run-notes.md`
- Test: `tests/test_shot.py`, `tests/test_sample_edition.py`

**Interfaces:**
- Produces: `scripts/sample_edition.py --out out/sample` builds an in-memory SQLite database seeded with one card of every visual kind, a four-slide deck (cover, table, text, what-next), a two-slide deck, a Barça pitch card, a quote card and a photo card whose image URL is `https://invalid.example/missing.jpg` (so the fallback path is what the screenshot shows), renders it with `render_edition`, and prints the HTML path. No model call, no network beyond the page's own image request. Content is plainly labelled sample text (the masthead date is the run date; card text says what each card demonstrates). `shot.py` fails also on: a `.deck` with fewer than 2 or more than 4 `.slide`, any `.slide` whose content overflows it (`scrollHeight > clientHeight + 1`), and a visible `img.photo` with `naturalWidth === 0` after the delay.

- [ ] **Step 1: Write the failing tests.** `tests/test_sample_edition.py::test_sample_edition_renders_every_kind`: run the script's `main(["--out", str(tmp_path)])`; the HTML has a `data-kind` for each of cover, chart, table, timeline, versus, before-after, pitch, photo, quote, and two `.deck` elements. `tests/test_shot.py`: `failures()` reports a deck with one slide, an overflowing slide and a broken visible photo, using the existing report-dict pattern.
- [ ] **Step 2: Run** the two files. Expected: FAIL.
- [ ] **Step 3: Implement.** Then run `.venv/bin/python scripts/sample_edition.py --out out/sample` and `.venv/bin/python scripts/shot.py out/sample/<date>.html`; fix layout until it passes at all four sizes, and look at the PNGs. Docs: README gets a "Visuals and slides" section (what the writer can choose, how to run the sample edition); `docs/flow.html` adds image and tone to Enrich and Classify and visuals and slides to Write, with a change-log line dated the day of the change (keep its existing flowchart style); `docs/first-run-notes.md` gets "v2 phase 2: what differs from the spec and why" listing this plan's rulings.
- [ ] **Step 4: Run** the full suite. Expected: all pass.
- [ ] **Step 5: Commit** `feat(qa): sample edition and deck checks; docs`.

---

### Task 12: The first real phase 2 edition (controller, not a subagent)

This task spends Mihir's Max plan: one classify pass on Haiku and roughly 15 to 25 Opus writer calls, plus retries. The controller runs it after the final whole-branch review, not a subagent.

- [ ] **Step 1:** `cd news-house && .venv/bin/newshouse ingest`, then `.venv/bin/newshouse build`, then `.venv/bin/newshouse render`. Expected: a run row with status `ok` and today's `out/<date>.html`.
- [ ] **Step 2:** `.venv/bin/python scripts/shot.py out/latest.html`. Expected: passes at all four sizes. Look at every PNG.
- [ ] **Step 3:** Report to Mihir in a short table: cards, decks, visuals by kind, photos shown versus fallen back, why lines, warnings by rule, write fallbacks, Opus calls and wall time from the run stats. Name anything that looks wrong rather than fixing it silently.
- [ ] **Step 4:** If the edition shows a defect in this plan's code, fix it on the branch with a test, commit, and say so in the report.
