"""The breaking lane: between-edition cards for very important, eligible clusters."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from newshouse.build import get_or_create_edition
from newshouse.config import Settings
from newshouse.edition_config import EditionConfig, load_edition_config
from newshouse.enrich import enrich_clusters
from newshouse.models import Card, Cluster, ClusterItem, Item, Run
from newshouse.profile import load_profile
from newshouse.render_static import latest_title
from newshouse.stacks import same_story
from newshouse.write import _fallback, write_card

log = logging.getLogger(__name__)


def run_breaking(session: Session, backend, *, settings: Settings, now: datetime,
                 client, cfg: EditionConfig | None = None) -> list[Card]:
    """Write breaking cards for today's edition, up to ``breaking_daily_cap`` a day and
    never past the edition config's ``cards_cap`` posts. ``cap_reached`` is set only when
    a cap stopped a candidate."""
    last = session.scalar(select(Run.started_at).where(Run.kind == "breaking")
                          .order_by(Run.started_at.desc()).limit(1))
    run = Run(id=uuid.uuid4().hex, kind="breaking", started_at=now, status="running", stats={})
    session.add(run)
    session.commit()
    run_id = run.id
    stats = {"candidates": 0, "written": 0, "fallback": 0, "cap_reached": False, "same_story": 0}
    cards: list[Card] = []
    try:
        q = select(Cluster).where(Cluster.breaking_eligible == True,  # noqa: E712
                                  Cluster.importance >= settings.breaking_threshold,
                                  Cluster.carded == False,  # noqa: E712
                                  Cluster.scored_at.is_not(None))
        if last is not None:
            q = q.where(Cluster.scored_at >= last)
        candidates = session.scalars(q.order_by(Cluster.importance.desc(), Cluster.scored_at)).all()
        stats["candidates"] = len(candidates)
        if cfg is None:  # the edition's budget and card cap live in the edition config
            cfg = load_edition_config(settings.edition_config_path)
        day = now.astimezone(ZoneInfo(settings.tz)).date()
        edition = get_or_create_edition(session, profile_id=settings.profile_id, date=day,
                                        budget_seconds=cfg.budget_seconds)
        posts = session.scalar(select(func.count()).select_from(Card)
                               .where(Card.edition_id == edition.id)) or 0
        # today's breaking headlines: a candidate on the same story is skipped (Ruling 3)
        today = [latest_title(session, cid) for cid in session.scalars(
            select(Card.cluster_id).where(Card.edition_id == edition.id,
                                          Card.breaking == True))]  # noqa: E712
        existing = len(today)
        profile_text = load_profile(session, settings).text if candidates else ""
        for cluster in candidates:
            if (existing + len(cards) >= settings.breaking_daily_cap
                    or posts + len(cards) >= cfg.cards_cap):  # never past the edition's cap
                stats["cap_reached"] = True
                break
            title = latest_title(session, cluster.id)
            if same_story(title, today, backend):  # Ruling 3: it joins that card's stack
                stats["same_story"] += 1
                continue
            enrich_clusters(session, [cluster.id], client=client)
            try:
                card = write_card(session, backend, cluster, profile_text=profile_text)
            except Exception:
                log.exception("breaking write_card failed for cluster %s; storing fallback",
                              cluster.id)
                items = session.scalars(select(Item).join(ClusterItem, ClusterItem.item_id == Item.id)
                                        .where(ClusterItem.cluster_id == cluster.id)).all()
                if not items:
                    continue
                card = _fallback(cluster, items)
                stats["fallback"] += 1
            card.edition_id, card.rank, card.breaking = edition.id, 0, True
            cluster.breaking = True
            cluster.carded = True
            session.add(card)
            session.flush()
            cards.append(card)
            today.append(title)
        stats["written"] = len(cards)
        run.status, run.stats, run.finished_at = "ok", stats, datetime.now(timezone.utc)
        session.commit()
    except Exception as e:
        session.rollback()
        run = session.get(Run, run_id)
        run.status, run.error, run.stats = "error", str(e), stats
        run.finished_at = datetime.now(timezone.utc)
        session.commit()
        raise
    return cards
