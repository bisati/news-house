# News House v2: posts, slides, colour

Date: 2026-11-03. Status: draft for Mihir's review; revised the same day after a builder check (seven clarifications, each marked "my call" where it sits). Builds on `docs/design.md` (v1, 2026-10-30): this document replaces v1 sections 5.2, 5.4 and 5.5 and extends 7.4, 7.5, 7.6 and 7.9. Everything not mentioned here stays as v1 built it.

Companions:
- Mood board (Mihir, 2026-11-02): https://claude.ai/artifact/FYUrjLf89C5wVV51P6Bb85
- Mockups, round 2 (approved direction, 2026-11-03): https://claude.ai/artifact/2QaZHh7vTv1xNJ8dshLTc5. Board 1 is the feed as posts, board 2 a post expanded in place, board 3 the end card, board 4 one story unrolled into four slides.
- Reference build: Parth Bhatia's House of 1400 (github.com/thefirstparth/house-of-1400), for the validator gate, the lessons ledger and the "top stories are printed or explained" rule.
- Decision log: D-009 (direction), see `~/.claude/decisions.md`.

---

## 1. Intent and why

The first edition (2026-10-30, 23 cards) worked as a pipeline and failed as a product. Mihir's verdict: "very bland and plain-AI like. It is very blocky. It is not very elegant. Visual storytelling should be better. We are using too many words, and it is, in turn, becoming just like inshorts." Then, on the round-1 mockups: "it looks like a continuous sheet of paper that I'm scrolling through." He wants discrete posts, like Instagram without the engagement buttons; text-heavy stories told as swipeable slides; more colour, life and motion; and the "why it matters to you" line only when it earns its place.

v2 changes what the reader sees and the two pipeline rules that decide what gets in. The ingest, clustering, threads and scheduling stay as built.

The product promise does not change: one finite edition a day, ranked by importance to him, about 15 minutes, every claim traceable to a source.

---

## 2. Goals, non-goals, anti-goals

### Goals (v2)

- G1. The edition reads as a stack of posts, each with one visual, a headline and a two-line gist. No post opens with a paragraph.
- G2. Text-heavy stories are told as two to four slides inside the post, swiped sideways, one idea per slide. Expand still opens the full brief and sources, in place.
- G3. Every post has a colour world set by its topic, its team, or the tone of the news. The page is lively without any engagement mechanics.
- G4. Motion: numbers count up, bars grow in, slides ease, the progress bar fills. All CSS, respects reduced-motion.
- G5. Photos where the source has a preview image; drawn visuals (chart, table, pitch, timeline, versus) where the data allows; a typographic cover otherwise. Never a placeholder box.
- G6. "Why it matters to you" appears only when it names something specific that changes what Mihir does or decides. Otherwise the space goes to the visual.
- G7. Per-topic floors and caps, and a "top stories are printed or explained" rule, so a day can no longer be 20 AI stories and a big story cannot vanish silently.
- G8. An edition-level validator is the publish gate: counts, floors, payload shapes, slide rules, banned AI tells, follow-up rules.
- G9. A lessons ledger: every miss Mihir flags becomes a written lesson with a rule or config change, and the pipeline is reminded of it.
- G10. Reactions (Worth it / Skip / Later / Should have been in) work from the page itself, not only from the CLI.
- G11. Live tiles under the masthead: Gurgaon air now, the next Barça fixture. Keyless sources only.
- G12. The 30 October edition re-renders in the new look without re-running the model, so the renderer can be judged against real data on day one.

### Non-goals (v2)

- Illustrations drawn by a model. Mihir, 2026-11-03: not yet.
- Multi-user, accounts, hosting for other people.
- Night palette. Designed as tokens in section 3.1 so it is a later switch, not a redesign. Not built in v2 unless phase 3 has time.
- Polls, "see how others voted", streaks, greetings by name, the topic-picker onboarding from the mood board. One reader, and the profile file is richer than a picker.
- Live tracker, short clips, maps, before/after sliders, claim-versus-fact. They need data or a live layer we do not have. The format catalogue leaves room for them.
- The newspaper view (v1 phase 2). Still later.

### Anti-goals

- Anything that makes the feed infinite or sticky. The end card stays the end.
- Likes, comments, shares, counts of any kind on a post.
- A visual that is decoration: every chart, number, table or pitch must come from facts in the cited items. A post with no honest visual gets a typographic cover, never a stock photo.
- Colour that lies: tomato is for urgent news only, mint for good news. Never swap them for variety.
- A card that could run in Inshorts unchanged.

---

## 3. The look: "Calm Forest, lively"

### 3.1 Tokens

Colours. Six paint colours and a small set of neutrals. Hex values are the ones on the approved mockups.

| Token | Hex | Use |
|---|---|---|
| sand | #F3EEE4 | page ground |
| white | #FFFFFF | default post, live tiles, inner panels on coloured posts |
| forest | #12372A | ink; the lead post's fill; one side of a versus split |
| forest-deep | #1E4A3A | inner panel on a forest post |
| ink-body | #2C3A32 | body text on light posts |
| muted | #5B6A61 | meta text, captions, secondary |
| hairline | #E4DDCD | rules inside white posts |
| track | #DDD5C4 | progress track, bar tracks on light posts |
| tomato | #F25C3B | urgent only: the breaking bar (at most two per edition), the AQI poor-or-worse dot, the wordmark's full stop |
| tomato-ink | #B23A1C | tomato as text on a light ground (a market fall); by night it is tomato |
| butter | #F6C945 | the "keep" side of a versus, tune-tomorrow card |
| mint | #A8F0C6 | labels and bars on forest, the Why label and the progress bar by night |
| mint-light | #D9F5E3 | fill of a good-news post (mint-night #143A2B by night) |
| good | #3CC77A | the "better" bar, the AQI-moderate dot |

Text on tomato is forest, never white (white fails contrast at body sizes). Text on forest is white for headlines, #D7E4DB for body, mint for labels. Muted on sand and on white passes 4.5:1; do not lighten it.

Topic families (2026-11-05, replacing the topic paint colours). Each family has five values; `config/edition.yaml` maps each topic to one, and a topic with none is neutral (muted marks, never tinted). A Barça story takes a family made from the kit (garnet accent, ring in blue); its pitch discs stay garnet by day and night.

| Family | Accent (dot, story bar) | Tint (fill) | Ink (labels, big text) | Night fill | Night accent | Topics |
|---|---|---|---|---|---|---|
| world | #4C7BE0 | #E3ECFF | #1F3A6B | #16233D | #8FB4FF | india-news, geopolitics |
| ai | #7C6CF0 | #ECE7FF | #3B2C7A | #221C3D | #B9AEFF | ai-models, ai-built, ai-tools, product-design |
| business | #A87F00 | #FBEFC4 | #5A4300 | #2B2412 | #F6C945 | startups, india-tech-biz, intl-biz-tech, edtech-competitors |
| sport | #C4672F | #F9E3D3 | #6B3216 | #33200F | #F2A36B | football, cricket, tennis-f1 |
| city | #D6456B | #F9DEE5 | #6B1E33 | #331620 | #F28BA8 | gurgaon-local |
| screen | #1F8F83 | #D6F1EE | #0F4A45 | #0F2A28 | #7FDCCF | movies |

Every pair a world uses passes WCAG AA by day and by night (text 4.5:1, marks 3:1); `tests/test_present.py` checks all of them, team kits included.

Type. Two families, self-hosted woff2 under `newshouse/static/fonts/` (Google Fonts links are fine for the mockups, not for the product: the page must render offline and without a third-party request).

| Role | Face | Size / weight |
|---|---|---|
| wordmark | Fraunces italic 700 | 30px, tomato full stop |
| big number (cover) | Fraunces 700 | 84 to 112px, line-height 0.85, tracking -0.04em, tabular figures |
| headline | Fraunces 600 | 24px on the lead, 22px elsewhere, line-height 1.12 to 1.15, tracking -0.01em |
| slide title, versus names | Fraunces 600 | 20 to 24px |
| drop cap in the brief | Fraunces 600 | 56px |
| gist, body | DM Sans 400 | 15 to 15.5px, line-height 1.5 to 1.6 |
| meta, labels | DM Sans 600 | 11px uppercase, tracking 0.08 to 0.1em |
| post header | DM Sans 600/400 | 13px |
| figures in tables and bars | DM Sans 600, tabular | 13 to 14px |

Shape. Post radius 14px. Inner visual panel 10px. Buttons and the Expand pill 8px. Bars 4px. No shadows, no gradients, no borders on posts (the fill is the edge). Hairlines only inside white posts.

Spacing. Page gutter 12px. Gap between posts 12px. Post padding 16px, bottom 14px. Inner panel padding 16 to 18px. Touch targets 44px.

Night palette: ground #141A16, post #1C2620, ink #F3EEE4, body #D7E4DB, hairline #2E3A33. Every post keeps its own night surface: a white post takes the night post, a good-news post mint-night, a tinted post its family's night fill, the forest lead forest-deep. Each world carries its day and night values (section 3.6), so no surface collapses to one.

### 3.2 Page anatomy

Top to bottom:

1. Masthead: wordmark left, date right (`Fri 30 Oct`). No double rule any more: the posts carry the structure.
2. Live tiles: two white tiles side by side (section 3.8). Hidden when no tile has data.
3. Progress line: `23 posts · 14 min` left, state right (`Nothing read yet`, `4 of 23 seen`, `12 min left`), a 3px track with a forest fill (mint by night). It sticks to the top of the viewport while the feed scrolls, so there is no "n more posts" foot line; the whole edition renders at once, nothing is paginated or loaded on tap (my call, after the builder check).
4. Posts in rank order. A breaking post, when one exists, sits first with a tomato header (at most two; a third shows a quiet `Update` marker instead).
5. The "Also today" post: white, numbered one-liners, "no click needed". This is the one and only rendering of the `also_happened` list: the first four lines show, a `Show 21 more` control expands the rest in place, every line carries a small `Should have been in` control, and a cut TOP line is marked `cut: <reason>`. The end card does not repeat it (my call; the earlier draft had the list in two places).
6. End card (section 3.9).

An archive page lists editions by date and opens any past edition as it was.

### 3.3 Post anatomy

Collapsed, every post has exactly these parts, in this order:

1. Header row: a 10px topic dot in the post's accent, the topic name in 600, then `· subject · n sources` in muted, and on the right either the read time (`35 sec`), `Lead · 50 sec` on the lead, or the Update marker (a muted dot + `Update`) on a thread chapter.
2. Visual: one panel from the catalogue (3.4), or a slide deck (3.5). Height 200 to 320px, never taller than the viewport minus the header and headline.
3. Headline: Fraunces, 12 words or fewer as a target, 90 characters as the hard limit.
4. Gist: one or two sentences, 40 words or fewer. It must add to the visual, never repeat it. On a post whose visual already says everything (a big number with its caption), the gist may be omitted.
5. Footer row: slide dots on the left when the post has slides; the Expand pill on the right.

Nothing else. No why line unless the writer produced one (section 4.3). No reactions in the collapsed state. No source list.

The "why it matters" line, when present, sits between the gist and the footer, as a forest label `Why it matters to you` (mint on forest and by night) and one sentence.

### 3.4 Visual catalogue

The visual is chosen per story by the writer from what the cited items support, and validated. v1's formats A to F map onto it; three visuals are new.

| Visual | v1 format | When | Payload | Renders as |
|---|---|---|---|---|
| none | new | nothing can be drawn honestly | `{}` | no visual: the post is its text |
| cover | new | one number or short phrase, stated in the sources, carries the story; at most one story in four | `{"big": "-13%", "label": "Q3 2026 · Thursday's close", "line": "Alphabet's worst day ever on the market."}` | big number set on the post itself, no panel, in the family ink |
| chart | C | three or more comparable figures | as v1 C: `series`, `unit`, `caption`; one point may carry `key: true` | horizontal bars, label left, value right; only the key bar (the writer's point, else the largest) in the topic accent |
| table | B | actual against expected, old against new, two or more rows | as v1 B | rows of label / big figure / small comparison, hairline separated |
| timeline | D | thread chapter 2 or later | as v1 D | rail with dots; today in the topic accent, earlier chapters muted |
| versus | E | a disagreement with two named sides | as v1 E | split panel, forest left, butter right, side name in Fraunces, one or two sentences each |
| before-after | F | a rule or price changes | as v1 F | two stacked rows, `Before` muted and `After` in the accent |
| pitch | new | a football story whose sources name a line-up or part of one | `{"rows": [[{"pos": "LB", "name": "Balde"}, ...]], "note": "Predicted back four, per Barca Blaugranes", "out": [{"name": "Koundé", "why": "ankle"}]}` | drawn pitch, player discs in kit colours, an `out` chip |
| photo | new | a cited item has a usable preview image and the story is about a person, place or event | `{"item_id": "...", "alt": "...", "credit": "Hindustan Times"}` | image panel with the kicker overlaid at the top-left |
| quote | new | the story is what someone said, on the record | `{"text": "...", "who": "...", "where": "...", "item_id": "..."}` | large Fraunces quote set on the post itself, the mark in the topic accent |

Rules:
- A story with none of the above gets `none`: no visual, and no automatic cover (2026-11-05; before that the renderer built a cover from the headline). A cover's `big` is always filled by the writer. A payload or deck that fails validation also falls back to `none`. A photo whose hotlink breaks still swaps to a cover in place.
- `photo` is allowed only when the image came from a cited item (section 4.4). A photo post keeps the kicker and headline below the image, never on it.
- `pitch` is allowed only when every named player appears in a cited item. Positions come from the sources; the renderer places by position.
- The existing payload validator (`newshouse/write.py`, `_payload_problems`) extends to the new shapes.

### 3.5 Slides

A post may carry a deck of two to four slides instead of a single visual. The writer decides, with these rules written into the prompt and enforced by the validator:

- Use slides when the brief has three or more distinct facts that each deserve their own frame (an earnings miss, a policy with before and after and effective date, a multi-step saga). Do not use slides for a single-fact story.
- Slide 1 is always a `cover`. The last slide is `what-next` when the brief ends with "What to watch next"; otherwise the last slide carries the consequence.
- Each slide is one of: `cover`, `chart`, `table`, `text` (35 words or fewer, a title of four words or fewer), `what-next` (two short paragraphs). One idea per slide.
- Every number on a slide must also appear in the brief. The validator checks this by string match on the digits.
- Slides stay in the post's colour family (2026-11-05, replacing the fixed butter, sand, tomato, forest order). Slide 1 takes the family tint with its big text in the family ink; the other slides sit on the post's inner panel; the one slide the writer marks `highlight: true` (never slide 1, at most one) takes the family's deepest shade with light text. On the forest lead the slides are forest-deep and the highlight mint; on a good-news post the slides are white and the highlight forest. By night each role takes the family's night values. The writer picks the highlight, never a colour.

Rendering: a horizontal carousel, one slide visible, swipe on touch, arrow buttons (44px) and dots below, `n / 4` counter. Slides are fixed-height within the post (320px at 390 wide). Keyboard: left and right arrows when the post has focus.

### 3.6 Colour worlds: the ladder

Colour carries meaning (urgency, topic, good news), never decoration. Each post climbs only as high as its reason allows (`present.colour_world`):

1. **Forest**: the lead (the first story that is not breaking news). Forest fill, white headline, mint labels and big number.
2. **Breaking**: an urgent card, at most two per edition. White post with the tomato header strip; tomato appears nowhere else on it.
3. **Tinted**: a good-news post (`tone: good`) gets mint-light; a cover or quote post without a deck gets its family tint. Never two tinted posts in a row: the second drops to step 4.
4. **White** (the default): the family accent marks the dot, the story's bar, today's timeline dot and the quote mark; labels take the family ink.
5. **Main text**: on top of step 3 or 4, a cover's big number or phrase takes the family ink.

Bad news gets no colour of its own. A Barça story is a step-3 or step-4 post in its kit family. Rank order is never changed for rhythm; rhythm changes the colour. "Also today" numbers each take their line's topic accent.

### 3.7 Expanded state

Expand opens the post in place, without navigation, and pushes `#card-<id>` into the URL so a position survives reload and can be shared.

Expanded, the post shows in order: header row with a collapse chevron on the right; the cover or the first visual (a deck collapses to its cover); the headline and gist; the structured block when there is one (table rows or chart) as a sand panel; the brief with a drop cap, paragraphs as written; the source list (outlet in 600, title in muted, each a 44px row, paywalled and via-Google-News marked); the reaction row `Worth it | Skip | Later` as three equal buttons (Worth it filled forest); a Collapse link. The next post peeks below.

Two client events feed the pipeline through the same endpoint as reactions (4.8), queued the same way: `seen` when a post has been fully in view for 1.5 seconds, `read` when it is expanded. The progress line counts `seen`. Thread chapters count as read when their card was `seen`; `_read_chapters` in `build.py` switches from "printed in an earlier edition" to "has a `seen` event", so an edition Mihir never opened makes the next chapter carry its recap instead of only the delta. When the events never arrive (phone offline, Mac asleep) the recap is the failure mode, which is the safe one (my call).

### 3.8 Live tiles

Two white tiles under the masthead, rendered at build time from keyless sources listed in v1 section 3, and refreshed client-side every 30 minutes when the page is open:

- Gurgaon air now: AQI from Open-Meteo's air-quality endpoint for Gurugram, labelled by CPCB band (good, satisfactory, moderate, poor, very poor, severe), dot coloured good / butter / tomato by band.
- Next match: Barça's next fixture from ESPN's public schedule JSON, as `Barça v Alavés · Sat 9 pm` in IST. On match day the tile shows the kick-off time; the live score tile is a later phase.

A tile with no data is hidden; the row disappears when both are. Tiles never block the build: a fetch failure logs and renders nothing.

### 3.9 End card

A forest post: `That's today.` in Fraunces 52px with a mint full stop; one line `23 posts in 14 minutes. The edition ends here.`; three stat tiles (posts, minutes, below the cut). Then a butter post `Tune tomorrow` with four chips the pipeline generates from the day's topics (`More AI tooling`, `Less football`, `More Gurgaon`, `Shorter edition`) and a line explaining what a tap does. Then `Next edition · Saturday morning, 31 October`, and in small muted type any validator warnings (4.5). Nothing after. The "Also today" post (3.2, item 5) sits just above the end card and is the only place the below-the-cut list appears.

Tune chips record as feedback with `action=tune` and a payload (`{"topic": "ai-built", "dir": +1}` or `{"budget": -1}`); section 4.9 says how they feed back.

### 3.10 Motion

All motion is CSS, GPU-only (transform and opacity), and disabled under `prefers-reduced-motion`.

- Post entry: translateY(12px) and opacity 0 to rest over 500ms, staggered 60ms per post, triggered by IntersectionObserver once.
- Bars: scaleX from 0 to full over 600ms when the panel enters view. Big numbers count up over 700ms from 0 (or from the previous value on a timeline) using the final string's digits; non-numeric covers fade.
- Slides: translateX ease 280ms; dots animate width.
- Expand: the brief block grows with max-height over 320ms; the chevron rotates.
- Progress bar: width transitions 400ms on each read.
- Nothing loops. No ambient animation.

### 3.11 Visual QA

A `scripts/shot.py` renders `out/latest.html` with headless Chrome at 390×844, 430×932, 768×1024 and 1280×800, saves PNGs under `out/shots/`, and fails on: horizontal overflow, any text under 11px, a post taller than 1.4 viewports when collapsed, or an empty visual panel. The canvas boards are the reference; a change to the look updates the canvas first.

---

## 4. Pipeline changes

### 4.1 Classify (Haiku)

- Add the three tests to the importance guidance in `classify.system.md`, in Mihir's terms: would he be annoyed tomorrow to have missed it; would a well-informed person in India be caught out not knowing it; does it change what he pays, earns, saves or decides. They sharpen the existing 0 to 100 rubric; the scale stays.
- Add `tone`: `good | bad | mixed | neutral`, from the reader's point of view. Stored on the cluster, copied to the card.
- Feed the ledger: the last ten lessons (section 4.7) are appended after the recent reactions as `## Lessons` so the scorer sees what it got wrong before.

### 4.2 Select: floors, caps and the top rule

`select_edition` gains two mechanisms, both deterministic and both configured in `config/edition.yaml` (committed; no secrets):

- Per-topic floors and caps. Today there is one global `per_topic_cap` (5) and a "best qualifying cluster of each topic" pass gated at importance 85. v2 replaces it with a table: for each topic slug, `min` and `max` items per edition, with a default for unlisted topics. Floors are filled before the budget pass from the best cluster of that topic above the noise floor; a floor that cannot be met (nothing above noise) is recorded, not forced. Starting values are in section 6; they are knobs for Mihir, like Parth's `desk_min`.
- Top stories are printed or explained. The `top_n` clusters by importance (start: 10), whatever their topic, are TOP. After selection, every TOP cluster is either a card or an `also_happened` row with a `cut_reason` written by the code (`budget`, `topic cap ai-models (5)`, `duplicate thread home`, `noise floor`). The edition stores `top_ids` and the run log shows the explanations. The end card marks a cut TOP line with `cut: <reason>` so Mihir sees what the rules removed, and his `Should have been in` tap on it becomes a lesson with the rule named.

The budget pass, the floor of 8 and the cap of 25 stay.

Two definitions the builder check asked for (my calls):
- One home per thread: at most one card per thread per edition. When two selected clusters match the same thread, the higher final score is the home and the other becomes an `also_happened` row with `cut_reason: duplicate thread home`. v1 does not enforce this; v2 adds it to `select_edition`.
- Topic counting: a cluster has 1 to 3 topics from classify, in order of fit. Floors and caps count a cluster against its first topic only, and cut reasons name that topic. (v1's single cap counted a cluster against every topic, which would make the per-topic floors impossible to reason about.)

### 4.3 Write (Opus)

The writer's output gains `visual`, `slides`, `tone` and a stricter `why`. `line`, `para`, `brief`, `headline`, `cited_item_ids` and `payload` stay so the old renderer and tests keep working.

- `visual`: one of the catalogue names (3.4), with its payload in `payload`. The prompt lists, as today, the allowed visuals for this cluster (pitch only for football with named players, photo only when an item has an image, table and chart only with the data).
- `slides`: an array, empty or two to four entries `{"kind": "cover|chart|table|text|what-next", "title": str, "body": str, "payload": {...}}`, under the rules in 3.5.
- `line` is the gist: 40 words or fewer, must not repeat the visual's content. Headline 12 words or fewer is a soft rule the validator reports; 90 characters stays hard.
- `why`: the rule tightens from "references a specific fact from the profile" to "names a specific fact from the profile and says what changes for the reader this week or this month: a cost, a decision, a commute, a match he will watch." If the sentence would only restate that the topic is one he follows, it is empty. The 30 October edition under this rule would have had a why line on perhaps three cards (Gemini pricing, GRAP curbs on his commute, Alphabet capex); the mockups show none and Mihir preferred that.
- `tone` is copied from classify unless the writer disagrees after reading the bodies, in which case it says why in the run log.

Images (4.4) and the pitch make the writer's input richer: the cluster block lists `image: <url>` under an item that has one.

### 4.4 Images

`enrich` already fetches the HTML of shortlisted items. It additionally reads `og:image`, `twitter:image` and the first `<link rel="image_src">`, stores the first absolute https URL on `Item.image_url`, and records width and height when the meta tags give them. The renderer hotlinks the image for the reader's own use and falls back to a cover panel on load error. No download, no re-hosting in v2. Images from Google News items are never used (they are Google's, not the publisher's). A later phase caches images locally for the archive.

### 4.5 The edition validator

`newshouse/validate.py` runs after write and before render, on the whole edition, and is the only thing that can mark an edition publishable. It checks:

- Counts: 8 to 25 cards; est_minutes within 12 to 18; per-topic floors met or explained; every TOP printed or explained.
- Shapes: every `visual` and slide payload valid for its kind; slides two to four with slide 1 a cover; numbers on slides present in the brief; headline length; gist length; `why` empty or naming a profile fact (checked by token overlap with the profile file).
- Threads: one home per thread; a chapter 2 or later card's headline shares under 60% of its tokens with the previous chapter's headline; `payload.delta` present.
- Language: a banned-words list (`config/banned.yaml`, started from Parth's: pivotal, crucial, landmark, testament, underscores, highlights, showcases, delve, landscape, navigate, robust, seamless, notably, quietly, amid, game-changer) and patterns (em dashes, "experts say", "not just X but Y", "sources say" when an outlet is named).
- Citations: every `cited_item_ids` entry exists in the cluster; `photo.item_id` and `quote.item_id` are cited.

On failure the build asks the writer once more for the failing cards with the problems listed (the retry path exists in `write.py`). A card that still fails is handled by what failed (my calls):
- A visual or slide problem: the card keeps its text and falls back to `visual: cover`, `slides: []`.
- A text problem (a banned word, an em dash, a long gist, a headline that repeats the previous chapter): the card keeps the writer's text and the problem becomes a warning. v1's `_fallback` (the latest item's teaser, marked unverified) is only for a writer that returned nothing usable, as today.
- A count or floor problem is never auto-fixed; it becomes a warning.

"Publishable" means the validator ran to completion and wrote `warnings[]` on the edition; it does not block. The edition is rendered, replaces `out/latest.html` and enters the archive with its warnings shown on the end card in small type and in the run log. The only thing that stops the day's edition is the validator itself crashing, which fails the build like any other exception. No status column is needed. On a re-render without a model call (the 30 October edition in phase 1, and any `newshouse render`) the validator runs in report mode: warnings only, no retry.

### 4.6 Rendering

- `render_static.py` keeps producing `out/<date>.html`, `out/<date>.json` and `out/latest.html`. The JSON gains the new fields and `warnings`, `top_ids` and `live`.
- The template is rewritten (`newshouse/templates/edition.html.j2`), with the CSS in `newshouse/static/edition.css` inlined at render time and the JS in `newshouse/static/edition.js` inlined likewise, so the page stays one file. Fonts are referenced from `static/fonts/` next to `out/` (copied on render).
- `out/index.html` is the archive: one line per edition, newest first.
- Rhythm, colour worlds and fallbacks (3.6, 3.4) are renderer logic in Python, testable without a browser: `color_world(card, position)` and `visual_for(card)` are pure functions.

### 4.7 Lessons ledger

`ledger/lessons.json` in the repo, committed, no secrets. Each entry: `id`, `date`, `miss` (what was wrong, in Mihir's words), `why` (the cause found in the run log), `fix` (the rule, prompt or config change, with the commit), `owed` (optional: a thread or topic the next edition must carry when it reappears), `status`.

Two ways in:
- `newshouse lesson add --from-feedback <feedback_id>` turns a `Should have been in` tap into a stub with the cluster, its score, its cut reason and the run that cut it. Claude or Mihir fills `why` and `fix` in the same session.
- `newshouse lesson add --text "..."` for anything else.

Two ways out: the last ten lessons go into the classify prompt (4.1); `owed` entries are checked by the validator (a thread marked owed that has a fresh cluster above noise must be printed or explained).

### 4.8 Reactions from the page

`newshouse serve [--port 8787]` starts a small stdlib HTTP server on the Mac that serves `out/` and accepts `POST /feedback` with `{card_id|cluster_id, action, payload?}`, calling `record_feedback`. Actions: `worth`, `skip`, `later`, `should_have`, `tune`, `seen`, `read`. The page posts with `fetch`; when the request fails (phone not on the same network, Mac asleep), the reaction is queued in `localStorage` and retried on the next load. `launchd` keeps the server up alongside the tick. On the phone, the page is reached over the home network or Tailscale at `http://<mac>:8787/latest.html`. Hosting on Vercel with Neon as the feedback store is the next phase and needs Mihir's Neon project (still pending from v1).

### 4.9 Feedback into ranking

Unchanged weights for worth, skip, later and should_have. New: `tune` events from the end card adjust the topic weight by ±0.3 (clamped) or the budget by ±120 seconds for the next edition only, logged in the run. A `should_have` on a cut TOP line also creates the lesson stub (4.7).

### 4.10 One-pass writing, as an experiment

House of 1400 writes its whole paper in one model session over a compact pool. v2 adds `newshouse build --writer onepass` that renders the selected clusters as one compact pool (headline, two best items' bodies capped at 1,600 characters, the thread summary) and asks Opus for all cards in one call (two calls above 14 cards). The validator is the judge. It runs on the same day's selection as the per-card writer for three editions and the run log records validator pass rate, wall time, token usage and Mihir's reactions per card. Default stays per-card until the comparison says otherwise. Not a phase 1 item.

---

## 5. Data model changes

- `Item.image_url: str | None`, `Item.image_w`, `Item.image_h`.
- `Cluster.tone: str | None`.
- `Card.visual: str` (catalogue name; default `cover` on migration), `Card.slides: list` (JSON, default `[]`), `Card.tone: str | None`. `payload` stays and holds the visual's payload.
- `Edition.top_ids: list`, `Edition.warnings: list`, `Edition.live: dict` (the tiles as rendered).
- `AlsoHappened.cut_reason: str | None`, `AlsoHappened.is_top: bool`.
- `Feedback.action` gains `tune`, `seen` and `read`; `Feedback.payload: dict | None`. `seen` and `read` are excluded from the weights in `compute_weights`.
- A `Lesson` table mirrors `ledger/lessons.json` (the file is the source of truth; the table is for joins in the run log). Builder's call whether to skip the table and read the file.

Migrations are additive with defaults so the 30 October edition re-renders without a rebuild.

---

## 6. Configuration: `config/edition.yaml`

Committed, no secrets, every knob Mihir may want to turn without touching code:

```yaml
budget_seconds: 900
cards: {floor: 8, cap: 25}
top_n: 10
topics:
  default: {min: 0, max: 4}
  ai-models: {min: 1, max: 4}
  ai-built: {min: 1, max: 4}
  india-news: {min: 1, max: 4}
  gurgaon-local: {min: 1, max: 3}
  football: {min: 1, max: 4}
  india-tech-biz: {min: 0, max: 3}
  intl-biz-tech: {min: 0, max: 3}
  geopolitics: {min: 0, max: 2}
  movies: {min: 0, max: 2}
  cricket: {min: 0, max: 2}
  tennis-f1: {min: 0, max: 2}
colours:
  topic: {india-news: world, geopolitics: world, ai-models: ai, ai-built: ai, ai-tools: ai, product-design: ai, startups: business, india-tech-biz: business, intl-biz-tech: business, edtech-competitors: business, football: sport, cricket: sport, tennis-f1: sport, gurgaon-local: city, movies: screen}
  teams:
    barcelona: {primary: "#A50044", secondary: "#004D98"}
live:
  aqi: {provider: open-meteo, lat: 28.4595, lon: 77.0266}
  fixtures: {provider: espn, team: barcelona}
```

The starting floors reflect the 30 October edition's topic mix and Mihir's interests; they are the first thing to tune after a week of v2 editions.

---

## 7. Phases

Each phase ends with `scripts/shot.py` screenshots compared against the canvas, a re-render of the 30 October edition, and Mihir's reaction before the next phase starts.

**Phase 1, the look on existing data.** New template, CSS, JS (carousel, expand, motion, reactions queue), `color_world`, `visual_for` with the v1 formats mapped onto the catalogue, cover fallback, end card, archive page, `scripts/shot.py`. `config/edition.yaml` with floors, caps and the top rule in `select.py`. The why rule and the three tests in the prompts. The validator for counts, shapes, threads and language. `newshouse serve`. Output: the 30 October edition in the new look, and the next real edition under the new selection rules.

**Phase 2, the writer learns the catalogue.** `visual`, `slides`, `tone` in the write schema, prompt and validator; `pitch`, `quote`, `cover` payloads; images at enrich and the `photo` visual; slide rendering with real decks. Output: an edition where text-heavy stories arrive as decks.

**Phase 3, alive.** Live tiles, tune chips, the lessons ledger with both entry paths and the classify reminder, motion polish, the night tokens if time allows.

**Phase 4, the one-pass experiment.** Three editions, both writers, one comparison note in `docs/`.

Phase 1 is the plan to write first. Phases 2 to 4 get their own plans once phase 1 has produced an edition Mihir has read.

---

## 8. Left to the builder

- Carousel implementation (CSS scroll-snap with buttons versus transform): pick the one that works on iOS Safari without jank.
- Count-up animation details and the exact easing curves.
- How `color_world` breaks ties when a team story is also bad news (team colours win; tone shows in the header dot).
- Whether the `Lesson` table exists or the JSON file is read directly.
- The `serve` server's shape (stdlib `http.server` is enough; no framework).
- Font subsetting for Fraunces (it is large; subset to Latin plus the rupee sign).
- The archive page's design beyond "a list of dates".

---

## 9. Risks

- Slides invite the writer to pad. The validator's 35-word slide cap and "numbers must be in the brief" rule are the guard; the three-slide minimum stays at two so a thin story is not stretched.
- Hotlinked images break or change. The cover fallback is instant and the alt text is the kicker, so a broken image costs nothing visible.
- Floors force weak stories in. A floor is met only from clusters above the noise floor; an unmet floor is logged, never faked.
- Team colours are brand colours. Used only as discs and dots, never as a crest or wordmark; a table in config, not fetched from anywhere.
- More fields mean more validator failures on day one. The fallback to `cover` keeps the edition shipping; the warnings list is how we tune.
- The lessons ledger goes stale if nobody fills `why` and `fix`. The CLI stub makes the entry; the session that handles a `Should have been in` is expected to finish it, and the validator's `owed` check makes a half-filled lesson visible.

---

## 10. Open questions, answered by Mihir on 2026-11-03

All six answered with "agreed with all your recommendations" (logged as D-010):

1. Phone access in v2: the Mac's `serve` over the home network or Tailscale now; Vercel plus Neon in phase 3.
2. Night palette: later. Tokens stay in 3.1.
3. Team colours for Barça (garnet and blue) on the pitch discs and the topic dot: yes, no crest.
4. Headline: 12 words as a soft target reported by the validator; 90 characters hard.
5. Starting floors in section 6: tune after a week of v2 editions, using the cut reasons on the end card.
6. `build/plan-a` is squash-merged to `main` before v2 starts; v2 work goes on a branch off `main`.
