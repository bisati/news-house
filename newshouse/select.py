"""Scoring formula and time-budgeted edition selection."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select

from newshouse.config import Settings
from newshouse.edition_config import EditionConfig, rule_for
from newshouse.feedback import compute_weights, tune_adjustments
from newshouse.models import Card, Cluster, Edition, ClusterItem, Item, ItemSource, Source

_TIER_RANK = {"primary": 3, "early-signal": 2, "mainstream": 1}


@dataclass
class ScoredCluster:
    id: str
    importance: int
    final_score: float
    topics: list[str]
    story_type: str | None
    expected_format: str
    thread_id: str | None = None


@dataclass
class Selection:
    selected: list[str]
    also: list[str]
    cut_score: float | None
    top_ids: list[str] = field(default_factory=list)
    cuts: dict[str, str] = field(default_factory=dict)
    unmet_floors: dict[str, int] = field(default_factory=dict)
    folded: list[str] = field(default_factory=list)
    tune: dict = field(default_factory=dict)  # {"topics": {slug: delta}, "budget": seconds}
    budget_seconds: int | None = None  # the budget this selection used (config plus tune)
    stacks: dict[str, list[str]] = field(default_factory=dict)  # chosen lead -> member ids


def primary_topic(topics: list[str] | None) -> str:
    """The topic a cluster counts against for floors and caps: its first slug."""
    return topics[0] if topics else "other"


def freshness(age_hours: float) -> float:
    if age_hours <= 24:
        return 1.0
    return 0.8 if age_hours <= 48 else 0.5


def tier_bonus(best_tier: str) -> int:
    return {"primary": 5, "early-signal": 3}.get(best_tier, 0)


def final_score(*, importance: int, age_hours: float, n_sources: int, best_tier: str,
                topic_w: float, source_w: float, chapter: int | None, is_delta: bool) -> float:
    cap = 40 if (chapter and chapter >= 2 and not is_delta) else 100
    return (min(importance, cap) * freshness(age_hours) + 5 * min(n_sources - 1, 4)
            + tier_bonus(best_tier) + 10 * topic_w + 5 * source_w)


def est_seconds(format: str) -> int:
    return 50 if format in ("B", "C", "D") else 35


STACK_MEMBER_SECONDS = 10


def stack_seconds(members) -> int:
    """A stack reads in its lead's time plus this much per extra member (Ruling 2)."""
    return STACK_MEMBER_SECONDS * len(members or [])


def expected_format(story_type: str | None, chapter: int | None) -> str:
    if chapter and chapter >= 2:
        return "D"
    return {"launch": "B", "number": "C", "debate": "E", "rule_change": "F"}.get(story_type or "", "A")


def _thread_homes(pool: list[ScoredCluster], member_threads: dict[str, set[str]] | None = None,
                  taken: set[str] = frozenset()) -> tuple[list[ScoredCluster], dict[str, str]]:
    """Step 3: keep the best-scored cluster of each thread; cut the rest. A stack lead is
    also the home of its members' threads (``member_threads``); ``taken`` threads are
    already home to a breaking lead's members."""
    member_threads = member_threads or {}
    eligible: list[ScoredCluster] = []
    cuts: dict[str, str] = {}
    homes: set[str] = set(taken)
    for c in pool:  # pool is already in final_score order
        if c.thread_id is not None and c.thread_id in homes:
            cuts[c.id] = "duplicate thread home"
            continue
        if c.thread_id is not None:
            homes.add(c.thread_id)
        homes |= member_threads.get(c.id, set())
        eligible.append(c)
    return eligible, cuts


def _also_lines(pool: list[ScoredCluster], chosen: dict[str, ScoredCluster], top_ids: set[str],
                cfg: EditionConfig, owned: set[str] = frozenset()) -> tuple[list[str], list[str]]:
    """Step 8: one line per story and a mix of topics.

    Walk the pool in score order. A cluster whose thread already has a printed card or an
    earlier line, or whose primary topic already has ``also_per_topic`` lines, gets no line:
    a top one is folded (kept, still explained by its cut reason), any other is left out.
    Lines stop at ``also_max``, except that a cut top story always gets a line. ``owned``
    threads belong to a printed stack's members and count as printed."""
    also: list[str] = []
    folded: list[str] = []
    threads = {c.thread_id for c in chosen.values() if c.thread_id is not None} | set(owned)
    per_topic: dict[str, int] = {}
    for c in pool:
        if c.id in chosen:
            continue
        top = c.id in top_ids
        t = primary_topic(c.topics)
        if ((c.thread_id is not None and c.thread_id in threads)
                or per_topic.get(t, 0) >= cfg.also_per_topic):
            if top:
                folded.append(c.id)
                if c.thread_id is not None:  # a folded row still owns its thread
                    threads.add(c.thread_id)
            continue
        if len(also) >= cfg.also_max and not top:
            continue
        also.append(c.id)
        per_topic[t] = per_topic.get(t, 0) + 1
        if c.thread_id is not None:
            threads.add(c.thread_id)
    return also, folded


def select_edition_v2(scored: list[ScoredCluster], *, cfg: EditionConfig,
                      noise_floor: int = 30, stacks: dict[str, list[str]] | None = None,
                      breaking: list[ScoredCluster] = ()) -> Selection:
    """``stacks`` (lead id -> member ids) makes each stack one post: its members leave the
    pool and the lead costs 10 s more per member. ``breaking`` are clusters already
    carded as breaking today: they count toward topic caps and floors (Ruling 3) and may
    lead a stack, but are never selected again."""
    stacks = stacks or {}
    members = {m for ms in stacks.values() for m in ms}
    # 1. pool: above the noise floor, by score; stack members ride on their lead
    pool = sorted((c for c in scored if c.importance >= noise_floor and c.story_type != "noise"
                   and c.id not in members), key=lambda c: c.final_score, reverse=True)
    # 2. top ids: the most important clusters, printed or explained (a lead is as
    # important as its most important member)
    imp = {c.id: c.importance for c in scored}
    rank = {c.id: max([c.importance] + [imp.get(m, 0) for m in stacks.get(c.id, [])])
            for c in pool}
    top_ids = [c.id for c in sorted(pool, key=lambda c: (rank[c.id], c.final_score),
                                    reverse=True)[:cfg.top_n]]
    # 3. one home per thread; a lead is also home to its members' threads
    thread_of = {c.id: c.thread_id for c in scored}
    member_threads = {lead: {thread_of[m] for m in ms if thread_of.get(m)}
                      for lead, ms in stacks.items()}
    breaking_ids = {b.id for b in breaking}
    # today's breaking cards are home to their own threads and their members' threads
    breaking_threads = {b.thread_id for b in breaking if b.thread_id}
    eligible, cuts = _thread_homes(
        pool, member_threads,
        taken=breaking_threads.union(*(member_threads.get(b, set()) for b in breaking_ids)))

    chosen: dict[str, ScoredCluster] = {}
    topic_count: dict[str, int] = {}
    for b in breaking:
        topic_count[primary_topic(b.topics)] = topic_count.get(primary_topic(b.topics), 0) + 1
    # today's breaking cards are posts too: they use up the card cap and floor (not the budget)
    cards_cap = max(0, cfg.cards_cap - len(breaking))
    cards_floor = max(0, cfg.cards_floor - len(breaking))
    spent = 0

    def cost(c: ScoredCluster) -> int:
        return est_seconds(c.expected_format) + stack_seconds(stacks.get(c.id))

    def under_cap(c: ScoredCluster) -> bool:
        t = primary_topic(c.topics)
        return topic_count.get(t, 0) < rule_for(cfg, t).max

    def take(c: ScoredCluster) -> None:
        nonlocal spent
        chosen[c.id] = c
        spent += cost(c)
        t = primary_topic(c.topics)
        topic_count[t] = topic_count.get(t, 0) + 1

    # 4. per-topic floors, ignoring the budget
    unmet_floors: dict[str, int] = {}
    for topic, rule in cfg.topics.items():
        if rule.min <= 0:
            continue
        taken = topic_count.get(topic, 0)  # today's breaking cards already count
        for c in eligible:
            if taken >= rule.min or len(chosen) >= cards_cap:
                break
            if c.id in chosen or primary_topic(c.topics) != topic or not under_cap(c):
                continue
            take(c)
            taken += 1
        if taken < rule.min:
            unmet_floors[topic] = rule.min - taken

    # 5. budget pass, remembering why each cluster was passed over
    reasons: dict[str, str] = {}
    for c in eligible:
        if c.id in chosen:
            continue
        t = primary_topic(c.topics)
        if not under_cap(c):
            reasons.setdefault(c.id, f"topic cap {t} ({rule_for(cfg, t).max})")
        elif spent + cost(c) > cfg.budget_seconds:
            reasons.setdefault(c.id, "budget")
        elif len(chosen) >= cards_cap:
            reasons.setdefault(c.id, "card cap")
        else:
            take(c)

    # 6. global card floor, ignoring the budget
    for c in eligible:
        if len(chosen) >= cards_floor:
            break
        if c.id not in chosen and under_cap(c):
            take(c)

    # 7. every top id not chosen gets its reason
    for cid in top_ids:
        if cid not in chosen and cid not in cuts:
            cuts[cid] = reasons[cid]  # a top id is always in the pool, so it was visited in step 5

    # 8. also happened, with every cut top id kept. A cut lead's members are normal
    # clusters again: Also candidates, explained by their lead's cut reason
    leads = set(chosen) | breaking_ids
    owned = breaking_threads.union(*(member_threads.get(lead, set()) for lead in leads))
    returned: list[ScoredCluster] = []
    by_id = {c.id: c for c in scored}
    for lead, ms in stacks.items():
        if lead in leads:
            continue
        why = cuts.get(lead) or reasons.get(lead)
        for m in ms:
            c = by_id.get(m)
            if c is None or c.importance < noise_floor or c.story_type == "noise":
                continue
            returned.append(c)
            if why:
                cuts.setdefault(m, why)
    also_pool = sorted([*pool, *returned], key=lambda c: c.final_score, reverse=True)
    also, folded = _also_lines(also_pool, chosen, set(top_ids), cfg, owned)

    # 9. selected in score order; stacks too, so the writer can cap them by lead score
    score_of = {c.id: c.final_score for c in [*scored, *breaking]}
    ordered = sorted(chosen.values(), key=lambda c: c.final_score, reverse=True)
    return Selection(selected=[c.id for c in ordered], also=also,
                     cut_score=ordered[-1].final_score if ordered else None,
                     top_ids=top_ids, cuts=cuts, unmet_floors=unmet_floors, folded=folded,
                     stacks={lead: list(stacks[lead]) for lead in sorted(  # best lead first
                         (l for l in stacks if l in leads), key=lambda l: -score_of[l])})


def _last_built_at(session, *, profile_id: str, edition: Edition | None) -> datetime | None:
    """When the latest built edition before ``edition`` was built (None when there is none)."""
    q = select(Edition.built_at).where(Edition.profile_id == profile_id,
                                       Edition.built_at.is_not(None))
    if edition is not None:
        q = q.where(Edition.id != edition.id, Edition.date < edition.date)
    return session.scalars(q.order_by(Edition.built_at.desc()).limit(1)).first()


def _breaking_cluster_ids(session, edition: Edition | None) -> set[str]:
    if edition is None:
        return set()
    return set(session.scalars(select(Card.cluster_id).where(
        Card.edition_id == edition.id, Card.breaking == True)))  # noqa: E712


def _group(session, scored: list[ScoredCluster], breaking: list[ScoredCluster], backend, *,
           noise_floor: int) -> dict[str, list[str]]:
    """Stacks over the top pool clusters, today's breaking cards included; a breaking
    card always leads its group (it already holds its rank-0 slot)."""
    # imported here because both modules import this one
    from newshouse.render_static import latest_title
    from newshouse.stacks import POOL_LIMIT, group_stacks, lead_with
    pool = sorted((c for c in [*scored, *breaking]
                   if c.importance >= noise_floor and c.story_type != "noise"),
                  key=lambda c: c.final_score, reverse=True)[:POOL_LIMIT]
    titles = {c.id: latest_title(session, c.id) for c in pool}
    return lead_with(group_stacks(pool, titles, backend), {b.id for b in breaking})


def score_and_select(session, *, now: datetime, settings: Settings,
                     cfg: EditionConfig, edition: Edition | None = None,
                     backend=None) -> Selection:
    """With a ``backend`` the selection groups stacks (one cheap call); without, none."""
    weights = compute_weights(session, profile_id=settings.profile_id)
    # tune taps since the last built edition steer this selection only (spec 4.9)
    tune_topics, tune_budget = tune_adjustments(
        session, profile_id=settings.profile_id,
        since=_last_built_at(session, profile_id=settings.profile_id, edition=edition))
    if tune_budget:
        cfg = cfg.model_copy(update={"budget_seconds": max(0, cfg.budget_seconds + tune_budget)})
    since = now - timedelta(hours=settings.cluster_window_hours)
    breaking_ids = _breaking_cluster_ids(session, edition)
    clusters = session.scalars(select(Cluster).where(
        Cluster.scored_at.is_not(None),
        (Cluster.carded == False) | Cluster.id.in_(breaking_ids),  # noqa: E712
        Cluster.created_at >= since)).all()
    scored: list[ScoredCluster] = []
    for c in clusters:
        if c.importance is None:
            continue
        rows = session.execute(
            select(Item.published_at, Source.id, Source.tier)
            .join(ClusterItem, ClusterItem.item_id == Item.id)
            .join(ItemSource, ItemSource.item_id == Item.id)
            .join(Source, Source.id == ItemSource.source_id)
            .where(ClusterItem.cluster_id == c.id)).all()
        if not rows:
            continue
        newest = max(r[0] for r in rows)
        srcs = {r[1]: r[2] for r in rows}
        best = max(srcs.values(), key=lambda t: _TIER_RANK.get(t, 1))
        best = best if best in _TIER_RANK else "mainstream"
        # the tune tap moves the cluster's primary topic on top of its best learned weight,
        # so "Less X" lowers a cluster even when a second topic weighs more
        topic_w = max((weights.topic.get(t, 0.0) for t in c.topics or []), default=0.0)
        topic_w = max(-1.0, min(1.0, topic_w + tune_topics.get(primary_topic(c.topics), 0.0)))
        source_w = sum(weights.source.get(s, 0.0) for s in srcs) / len(srcs)
        c.final_score = final_score(
            importance=c.importance, age_hours=(now - newest).total_seconds() / 3600,
            n_sources=len(srcs), best_tier=best, topic_w=topic_w, source_w=source_w,
            chapter=c.chapter, is_delta=c.is_delta)
        scored.append(ScoredCluster(c.id, c.importance, c.final_score, list(c.topics or []),
                                    c.story_type, expected_format(c.story_type, c.chapter),
                                    thread_id=c.thread_id))
    session.flush()
    breaking = [c for c in scored if c.id in breaking_ids]
    scored = [c for c in scored if c.id not in breaking_ids]
    stacks = (_group(session, scored, breaking, backend, noise_floor=settings.noise_floor)
              if backend is not None else {})
    sel = select_edition_v2(scored, cfg=cfg, noise_floor=settings.noise_floor, stacks=stacks,
                            breaking=breaking)
    sel.tune = {"topics": {t: round(d, 2) for t, d in tune_topics.items()}, "budget": tune_budget}
    sel.budget_seconds = cfg.budget_seconds
    return sel
