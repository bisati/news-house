"""Stacks: one post per story, with its follow-ups to swipe (plan-f Rulings 1-4).

One cheap call groups the top pool clusters' headlines into same-story groups; one
writer call per chosen stack writes a short row for each extra member. Any failure
degrades quietly: no groups means no stacks, a bad row means a headline-only row."""
from __future__ import annotations

import logging
from importlib import resources

from sqlalchemy.orm import object_session

from newshouse.catalogue import _numbers
from newshouse.llm.backend import cheap_effort
from newshouse.llm.schemas import STACK_GROUPS_SCHEMA, STACK_LINES_SCHEMA
from newshouse.models import Card, Cluster
from newshouse.render_static import latest_title
from newshouse.select import ScoredCluster, primary_topic
from newshouse.write import HEADLINE_MAX, TIER_RANK, _load, items_for_write

log = logging.getLogger(__name__)

POOL_LIMIT = 60
MAX_STACK = 6  # members including the lead
MAX_STACKS = 10  # stacks per build that get written rows; the rest are headline-only
LINE_BODY_CAP = 1500
LINE_ITEMS = 6


def _prompt(name: str) -> str:
    return resources.files("newshouse.llm").joinpath(f"prompts/{name}").read_text()


def group_stacks(pool: list[ScoredCluster], titles: dict[str, str], backend, *,
                 limit: int = POOL_LIMIT, model: str = "haiku") -> dict[str, list[str]]:
    """Lead id -> member ids (lead excluded, in score order) for the top ``limit`` clusters.

    A group is dropped when it names an unknown id, repeats an id, spans primary topics,
    has more than ``MAX_STACK`` ids, or shares an id with another group; the rest are
    kept. Any call failure or malformed reply means no stacks."""
    top = sorted(pool, key=lambda c: c.final_score, reverse=True)[:limit]
    if len(top) < 2:
        return {}
    by_id = {c.id: c for c in top}
    user = "\n".join(f"{c.id} [{primary_topic(c.topics)}]: {titles.get(c.id, '')}" for c in top)
    try:
        reply = backend.complete_json(system=_prompt("stacks.system.md"), user=user,
                                      schema=STACK_GROUPS_SCHEMA, model=model,
                                      effort=cheap_effort(model))
        groups = reply["groups"]
        if not isinstance(groups, list):
            raise ValueError("groups is not a list")
    except Exception as e:  # a failed grouping never fails a build
        log.warning("stack grouping skipped: %r", e)
        return {}
    candidates: list[list[str]] = []
    for g in groups:
        ids = g.get("ids") if isinstance(g, dict) else None
        if (not isinstance(ids, list) or not 2 <= len(ids) <= MAX_STACK
                or not all(isinstance(i, str) and i in by_id for i in ids)
                or len(set(ids)) != len(ids)
                or len({primary_topic(by_id[i].topics) for i in ids}) != 1):
            log.info("stack group dropped: %r", g)
            continue
        candidates.append(ids)
    seen: dict[str, int] = {}
    for ids in candidates:
        for i in ids:
            seen[i] = seen.get(i, 0) + 1
    out: dict[str, list[str]] = {}
    for ids in candidates:
        if any(seen[i] > 1 for i in ids):  # a cluster in two groups: both are junk
            log.info("stack group dropped (overlaps another): %r", ids)
            continue
        ranked = sorted(ids, key=lambda i: by_id[i].final_score, reverse=True)
        out[ranked[0]] = ranked[1:]
    return out


def lead_with(stacks: dict[str, list[str]], preferred: set[str]) -> dict[str, list[str]]:
    """Re-lead each group so a ``preferred`` cluster (one that already has a card, such as
    a breaking card) leads it; other preferred clusters keep their own cards and leave
    the group. Groups keep their score order; a group left with no members is dropped."""
    out: dict[str, list[str]] = {}
    for lead, members in stacks.items():
        group = [lead, *members]
        pref = [g for g in group if g in preferred]
        if pref:
            lead, members = pref[0], [g for g in group if g not in preferred]
        if members:
            out[lead] = members
    return out


def same_story(candidate_title: str, today_breaking_titles: list[str], backend) -> bool:
    """Whether a breaking candidate is the same story as a breaking card already written
    today, by the grouping call on those headlines only (Ruling 3)."""
    if not today_breaking_titles:
        return False
    pool = [ScoredCluster("new", 0, 0.0, ["breaking"], None, "A")]
    pool += [ScoredCluster(f"b{n}", 0, float(n), ["breaking"], None, "A")
             for n in range(1, len(today_breaking_titles) + 1)]
    titles = {"new": candidate_title,
              **{f"b{n}": t for n, t in enumerate(today_breaking_titles, start=1)}}
    groups = group_stacks(pool, titles, backend, limit=len(pool))
    return any(lead == "new" or "new" in members for lead, members in groups.items())


def _cut_body(body: str) -> str:
    return body if len(body) <= LINE_BODY_CAP else body[:LINE_BODY_CAP] + " [truncated]"


def _short_headline(title: str) -> str:
    """A title cut to ``HEADLINE_MAX`` on a word boundary, with an ellipsis when cut."""
    title = title.strip()
    if len(title) <= HEADLINE_MAX:
        return title
    cut = title[:HEADLINE_MAX - 1]
    if " " in cut:
        cut = cut[:cut.rfind(" ")]
    return cut.rstrip(" ,;:-") + "\u2026"


def _member_facts(session, cluster: Cluster) -> dict:
    """What a member row needs: its shown items, their text, and its best item's link."""
    items, sbi = _load(session, cluster)
    shown, _ = items_for_write(items, sbi, cap=LINE_ITEMS)
    best = min(items, key=lambda it: (min((TIER_RANK.get(s.tier, 3) for s in sbi.get(it.id, [])),
                                          default=3), -it.published_at.timestamp(), it.id))
    srcs = sbi.get(best.id, [])
    # the truth rule checks against exactly what the prompt shows (bodies cut)
    text = "\n".join(x for it in shown
                     for x in (it.title, it.teaser, _cut_body(it.body) if it.body else None) if x)
    return {"items": shown, "text": text, "url": best.url, "source": srcs[0].name if srcs else ""}


def _render_member(cluster: Cluster, items) -> str:
    blocks = [f"## Cluster {cluster.id}"]
    for it in items:
        lines = [f"#### item {it.id}", f"title: {it.title}", f"teaser: {it.teaser}"]
        if it.body:
            lines += ["body:", _cut_body(it.body)]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _row_ok(row: dict, brief: str) -> bool:
    """The card rules that fit a row: a headline and line that are short strings, and
    every number in them present in the member's own items (Ruling 4)."""
    head, line = row.get("headline"), row.get("line")
    if not (isinstance(head, str) and head.strip() and isinstance(line, str) and line.strip()):
        return False
    if len(head) > HEADLINE_MAX:
        return False
    have = set(_numbers(brief))
    return all(v in have for v in {**_numbers(head), **_numbers(line)})


def _headline_row(session, cluster: Cluster, facts: dict) -> dict:
    return {"cluster_id": cluster.id, "headline": _short_headline(latest_title(session, cluster.id)),
            "line": "", "url": facts["url"], "source": facts["source"]}


def headline_rows(members: list[Cluster]) -> list[dict]:
    """Headline-only rows with no model call. A member whose facts cannot be read (no
    items, a DB error) is skipped and logged."""
    out = []
    for m in members:
        try:
            session = object_session(m)
            out.append(_headline_row(session, m, _member_facts(session, m)))
        except Exception as e:
            log.warning("stack member %s skipped: %r", m.id, e)
    return out


def write_stack_lines(lead_card: Card, members: list[Cluster], backend, *,
                      model: str = "opus") -> list[dict]:
    """One row per member, in order: ``{cluster_id, headline, line, url, source}``.
    A failed call, or a row that breaks the rules, gives a headline-only row (the
    member's latest title and an empty line)."""
    if not members:
        return []
    session = object_session(members[0])
    facts = {m.id: _member_facts(session, m) for m in members}
    rows = {m.id: _headline_row(session, m, facts[m.id]) for m in members}
    user = "\n\n".join([f"Lead story: {lead_card.headline}"]
                       + [_render_member(m, facts[m.id]["items"]) for m in members])
    system = _prompt("stack_lines.system.md") + "\n\n" + _prompt("house_style.md")
    try:
        reply = backend.complete_json(system=system, user=user, schema=STACK_LINES_SCHEMA,
                                      model=model, effort="low")
        written = reply["rows"]
        if not isinstance(written, list):
            raise ValueError("rows is not a list")
    except Exception as e:
        log.warning("stack lines failed for lead %s: %r", lead_card.cluster_id, e)
        written = []
    for row in written:
        cid = row.get("cluster_id") if isinstance(row, dict) else None
        if cid not in rows or rows[cid]["line"]:
            continue
        if _row_ok(row, facts[cid]["text"]):
            rows[cid].update(headline=row["headline"].strip(), line=row["line"].strip())
        else:
            log.info("stack row for %s fails the card rules; headline only", cid)
    return [rows[m.id] for m in members]
