"""Write the cards the reader reads: one model call per selected cluster, strictly validated."""
from __future__ import annotations

import logging
import re
import uuid
from importlib import resources

from sqlalchemy import select
from sqlalchemy.orm import Session

from newshouse.catalogue import (SLIDE_FORMATS, FORMAT_VISUAL, TONES, VISUAL_FORMAT, VISUALS, ItemFacts,
                                 _nonempty_str, _strs, payload_problems, photo_eligible, slide_problems,
                                 visual_seconds)
from newshouse.catalogue import format_payload_problems as _payload_problems
from newshouse.llm.backend import LLMError
from newshouse.llm.schemas import WRITE_SCHEMA
from newshouse.models import Card, Cluster, ClusterItem, Item, ItemSource, Source, Thread
from newshouse.select import est_seconds

log = logging.getLogger(__name__)

BODY_CAP = 6000
ITEM_CAP = 12
TIER_RANK = {"primary": 0, "early-signal": 1, "mainstream": 2}
HEADLINE_MAX = 90
RICH = ("B", "C", "E", "F")
RICH_VISUALS = ("chart", "table", "versus", "before-after")
LEGACY_FORMATS = ("A", "B", "C", "D", "E", "F")


def _prompt(name: str) -> str:
    return resources.files("newshouse.llm").joinpath(f"prompts/{name}").read_text()


def _load(session: Session, cluster: Cluster) -> tuple[list[Item], dict[str, list[Source]]]:
    items = list(session.scalars(
        select(Item).join(ClusterItem, ClusterItem.item_id == Item.id)
        .where(ClusterItem.cluster_id == cluster.id).order_by(Item.published_at, Item.id)))
    sbi: dict[str, list[Source]] = {i.id: [] for i in items}
    rows = session.execute(
        select(ItemSource.item_id, Source).join(Source, Source.id == ItemSource.source_id)
        .where(ItemSource.item_id.in_(list(sbi)))
        .order_by(ItemSource.item_id, Source.id)).all() if sbi else []
    for item_id, src in rows:
        sbi[item_id].append(src)
    return items, sbi


def items_for_write(items: list[Item], sources_by_item: dict[str, list[Source]],
                    cap: int = ITEM_CAP) -> tuple[list[Item], int]:
    """The items the writer sees: enriched (with body) first, then best source tier
    (primary > early-signal > mainstream), then newest. Returns (shown, omitted count)."""
    def key(it: Item):
        tiers = [TIER_RANK.get(s.tier, 3) for s in sources_by_item.get(it.id, [])]
        return (it.body is None, min(tiers, default=3), -it.published_at.timestamp(), it.id)
    ranked = sorted(items, key=key)
    return ranked[:cap], max(0, len(ranked) - cap)


def _unlocks_rich(items: list[Item], sources_by_item: dict[str, list[Source]]) -> bool:
    for it in items:
        srcs = sources_by_item.get(it.id, [])
        non_gnews = any(s.kind != "gnews" for s in srcs)
        # gnews items are teaser-only: a primary-tier gnews source unlocks nothing.
        if (it.body and non_gnews) or any(s.tier == "primary" and s.kind != "gnews" for s in srcs):
            return True
    return False


def _image(it: Item, sources_by_item: dict[str, list[Source]]) -> str | None:
    """The item's preview image, only when it came from a publisher (never Google News)."""
    url = it.image_url
    if not url or not url.startswith("https://"):
        return None
    return url if photo_eligible(s.kind for s in sources_by_item.get(it.id, [])) else None


def allowed_formats(cluster: Cluster, items: list[Item],
                    sources_by_item: dict[str, list[Source]]) -> list[str]:
    """v1 format letters (kept for v1 callers; the writer now uses allowed_visuals)."""
    out = ["A"]
    if cluster.chapter and cluster.chapter >= 2:
        out.append("D")
    if _unlocks_rich(items, sources_by_item):
        out += list(RICH)
    return out


def allowed_visuals(cluster: Cluster, items: list[Item],
                    sources_by_item: dict[str, list[Source]]) -> list[str]:
    topics = set(cluster.topics or [])
    out = ["none", "key-facts", "number", "cover", "quote", "countdown", "deal"]  # a teaser can fill these
    if "football" in topics:  # spec 6: the sport formats are football's
        out += ["availability", "scoreline", "stakes", "rumour"]
    if cluster.chapter and cluster.chapter >= 2:
        out.append("timeline")
    if _unlocks_rich(items, sources_by_item):
        out += ["changes", "factsheet", "incident", "case", "steps", *RICH_VISUALS]
        if "football" in topics:
            out.append("pitch")
        text = " ".join(f"{it.title or ''} {it.teaser or ''} {it.body or ''}" for it in items).lower()
        if re.search(r"\b(grap|aqi)\b", text):
            out.append("scale")  # a body, and the scale's name in the sources
    if any(_image(it, sources_by_item) for it in items):
        out.append("photo")
    return out


def item_facts(items: list[Item], sources_by_item: dict[str, list[Source]]) -> dict[str, ItemFacts]:
    return {it.id: ItemFacts("\n".join(x for x in (it.title, it.teaser, it.body) if x),
                             _image(it, sources_by_item)) for it in items}


def earlier_chapters(session: Session, thread: Thread, *, before_chapter: int,
                     read_chapters) -> list[dict]:
    """One entry per chapter 1..before_chapter-1 that has a card or cluster to name it."""
    out: list[dict] = []
    for n in range(1, (before_chapter or 0)):
        card = session.scalars(select(Card).where(Card.thread_id == thread.id, Card.chapter == n)
                               .order_by(Card.created_at, Card.id)).first()
        if card is not None:
            title, when = card.headline, card.created_at
        else:
            cl = session.scalars(select(Cluster).where(Cluster.thread_id == thread.id,
                                                       Cluster.chapter == n)
                                 .order_by(Cluster.created_at, Cluster.id)).first()
            if cl is None:
                continue
            its, _ = _load(session, cl)
            if not its:
                continue
            title, when = max(its, key=lambda i: i.published_at).title, cl.created_at
        out.append({"chapter": n, "title": title, "date": when.date().isoformat(),
                    "read": n in read_chapters})
    return out


def render_cluster_for_write(session: Session, cluster: Cluster, *, thread: Thread | None,
                             read_chapters) -> str:
    items, sbi = _load(session, cluster)
    items, omitted = items_for_write(items, sbi)
    allowed = allowed_visuals(cluster, items, sbi)
    head = [f"## Cluster {cluster.id}",
            f"topics: {', '.join(cluster.topics or [])}",
            f"story type: {cluster.story_type or 'unknown'}"]
    if cluster.tone:
        head.append(f"tone (from classify): {cluster.tone}")
    if cluster.chapter:
        head.append(f"chapter: {cluster.chapter}")
    if thread is not None:
        head.append(f"thread: {thread.title}")
    head.append(f"Allowed visuals: {', '.join(allowed)}")
    blocks = ["\n".join(head)]
    for it in items:
        srcs = sbi.get(it.id, [])
        lines = [f"#### item {it.id}"]
        if srcs:
            s = srcs[0]
            lines.append(f"source: {s.name} ({s.tier}, {'paywall' if s.paywall else 'open'}, {s.kind})")
        lines += [f"published: {it.published_at.isoformat()}", f"url: {it.url}"]
        if img := _image(it, sbi):
            lines.append(f"image: {img}")
        lines += [f"title: {it.title}", f"teaser: {it.teaser}"]
        if it.body:
            body = it.body
            if len(body) > BODY_CAP:
                body = body[:BODY_CAP] + " [truncated]"
            lines += ["body:", body]
        elif srcs and all(s.paywall for s in srcs):
            lines.append("body: (paywalled; teaser only)")
        else:
            lines.append("body: (none; teaser only)")
        blocks.append("\n".join(lines))
    if omitted:
        blocks.append(f"[{omitted} more items omitted]")
    if thread is not None:
        read = ", ".join(str(c) for c in sorted(read_chapters)) or "none"
        thread_lines = [f'### Thread "{thread.title}" ({thread.chapters} chapters so far)',
                        thread.summary, f"Read chapters: {read}"]
        earlier = earlier_chapters(session, thread, before_chapter=cluster.chapter or 0,
                                   read_chapters=read_chapters)
        if earlier:
            thread_lines.append("Earlier chapters:")
            thread_lines += [f"- chapter {e['chapter']} ({e['date']}, "
                             f"{'read' if e['read'] else 'unread'}): {e['title']}" for e in earlier]
        blocks.append("\n".join(thread_lines))
    return "\n\n".join(blocks)


def _visual_of(out: dict) -> tuple[str | None, str | None]:
    """(visual, legacy format letter). A v1 reply has no ``visual`` but a ``format``
    letter, mapped as Ruling 1 says; a v1 letter A keeps its own rule (payload ``{}``)."""
    visual = out.get("visual")
    if visual is not None:
        return visual, None
    fmt = out.get("format")
    if fmt in LEGACY_FORMATS:
        return FORMAT_VISUAL.get(fmt, "none"), fmt  # a v1 A card had no visual of its own
    return None, fmt


def reply_problems(out: dict, item_ids: set[str], *, allowed,
                   expected_chapters: list[dict] | None = None,
                   items: dict[str, ItemFacts] | None = None) -> tuple[list[str], list[str]]:
    """(text problems, visual problems). Text problems cost the card its text; visual
    problems (payload, slides, tone) only cost it its visual (Ruling 2)."""
    if not isinstance(out, dict):
        return ["reply must be a JSON object"], []
    items = items or {}
    text: list[str] = []
    vis: list[str] = []
    visual, fmt = _visual_of(out)
    if visual is None:
        text.append(f"visual is missing (format {fmt!r} is not a v1 format); "
                    f"allowed visuals: {', '.join(allowed)}")
    elif visual not in allowed and VISUAL_FORMAT.get(visual) not in allowed:
        shown = f"visual {visual!r}" + (f" (format {fmt})" if fmt else "")
        vis.append(f"{shown} is not allowed; allowed: {', '.join(allowed)}")
    cited = out.get("cited_item_ids")
    if not isinstance(cited, list) or not cited:
        text.append("cited_item_ids must be a non-empty list")
        cited = []
    for c in cited:
        if c not in item_ids:
            text.append(f"cited item id {c!r} is not in this cluster")
    headline = out.get("headline")
    if not _nonempty_str(headline):
        text.append("headline is empty")
    elif len(headline) > HEADLINE_MAX:
        text.append(f"headline is {len(headline)} characters; maximum is {HEADLINE_MAX}")
    for k in ("line", "para"):
        if not _nonempty_str(out.get(k)):
            text.append(f"{k} is empty")
    cited_set = {c for c in cited if isinstance(c, str)}
    if fmt is not None:
        vis += _payload_problems(fmt, out.get("payload"), cited_set, expected_chapters)
    elif visual in VISUALS:
        vis += payload_problems(visual, out.get("payload"), cited=cited_set, items=items,
                                expected_chapters=expected_chapters)
    slides = out.get("slides", [])
    if not isinstance(slides, list):
        vis.append("slides must be a list")
    else:
        brief = out.get("brief")
        vis += slide_problems(slides, brief=brief if isinstance(brief, str) else "",
                              cited=cited_set, items=items)
        for n, sl in enumerate(slides):
            k = sl.get("kind") if isinstance(sl, dict) else None
            if k in SLIDE_FORMATS and k not in allowed:
                vis.append(f"slides[{n}] kind {k!r} is not allowed for this story; allowed: {', '.join(allowed)}")
    if "tone" in out and out["tone"] not in TONES:
        vis.append(f"tone {out['tone']!r} is not one of {', '.join(TONES)}")
    return text, vis


def validate_card(out: dict, item_ids: set[str], *, allowed,
                  expected_chapters: list[dict] | None = None,
                  items: dict[str, ItemFacts] | None = None) -> list[str]:
    text, vis = reply_problems(out, item_ids, allowed=allowed,
                               expected_chapters=expected_chapters, items=items)
    return text + vis


def _fallback(cluster: Cluster, items: list[Item]) -> Card:
    latest = max(items, key=lambda i: i.published_at)
    return Card(id=uuid.uuid4().hex, cluster_id=cluster.id, thread_id=cluster.thread_id,
                chapter=cluster.chapter, format="A", visual="none", slides=[], tone=cluster.tone,
                payload={}, headline=latest.title[:HEADLINE_MAX],
                line=(latest.teaser or "")[:200], para="", brief="", why="",
                est_seconds=est_seconds("A"), cited_item_ids=[latest.id], unverified=True)


def _problem_block(problems: list[str]) -> str:
    return ("\n\nYour previous reply had these problems:\n- " + "\n- ".join(problems)
            + "\nFix them and reply again with JSON only.")


def _card_from(cluster: Cluster, out: dict, *, keep_visual: bool) -> Card:
    """A card from a reply whose text passed. Without ``keep_visual`` the card gets an
    no visual and no slides (its visual failed)."""
    if keep_visual:
        visual, _ = _visual_of(out)
        payload, slides = out.get("payload") or {}, list(out.get("slides") or [])
    else:
        visual, payload, slides = "none", {}, []
    tone = out.get("tone", cluster.tone)
    if tone is not None and tone not in TONES:
        tone = cluster.tone
    return Card(id=uuid.uuid4().hex, cluster_id=cluster.id, thread_id=cluster.thread_id,
                chapter=cluster.chapter, format=VISUAL_FORMAT[visual], visual=visual,
                payload=payload, slides=slides, tone=tone,
                headline=out["headline"], line=out["line"], para=out["para"],
                brief=out.get("brief") or "", why=out.get("why") or "",
                est_seconds=visual_seconds(visual, slides),
                cited_item_ids=list(out["cited_item_ids"]), unverified=False)


def write_card(session: Session, backend, cluster: Cluster, *, profile_text: str,
               model: str = "opus", read_chapters=frozenset(),
               problems: list[str] | None = None, notes: list[str] | None = None) -> Card:
    """One card for the cluster. With ``problems`` (from the edition validator) the
    first and only attempt already carries them; otherwise a bad reply gets one retry.
    A reply whose text passes but whose visual still fails keeps its text with no
    visual; ``notes`` then gets one line saying why."""
    items, sbi = _load(session, cluster)
    if not items:
        raise ValueError(f"cluster {cluster.id} has no items")
    thread = session.get(Thread, cluster.thread_id) if cluster.thread_id else None
    shown, _ = items_for_write(items, sbi)  # the writer can only cite what it was shown
    allowed = allowed_visuals(cluster, shown, sbi)
    facts = item_facts(shown, sbi)
    system = (_prompt("write.system.md") + "\n\n" + _prompt("house_style.md")
              + "\n\n## Reader profile\n" + profile_text)
    user = render_cluster_for_write(session, cluster, thread=thread, read_chapters=read_chapters)
    item_ids = {i.id for i in shown}
    expected = (earlier_chapters(session, thread, before_chapter=cluster.chapter,
                                 read_chapters=read_chapters)
                if thread is not None and cluster.chapter and cluster.chapter >= 2 else None)
    card: Card | None = None
    text_ok: tuple[dict, list[str]] | None = None  # the latest reply whose text passed
    prompt = user + _problem_block(problems) if problems else user
    for attempt in range(1 if problems else 2):
        try:
            out = backend.complete_json(system=system, user=prompt, schema=WRITE_SCHEMA, model=model)
        except LLMError as e:
            log.warning("write failed for cluster %s: %s", cluster.id, e)
            break
        text, vis = reply_problems(out, item_ids, allowed=allowed, expected_chapters=expected,
                                   items=facts)
        if not text:
            text_ok = (out, vis)
        if not text and not vis:
            card = _card_from(cluster, out, keep_visual=True)
            break
        log.warning("write problems for cluster %s: %s", cluster.id, text + vis)
        prompt = user + _problem_block(text + vis)
    if card is None and text_ok is not None:
        out, vis = text_ok
        card = _card_from(cluster, out, keep_visual=False)
        if notes is not None:
            notes.append(f"{out['headline']}: {'; '.join(vis)}")
    if card is None:
        card = _fallback(cluster, items)
    cluster.carded = True
    return card
