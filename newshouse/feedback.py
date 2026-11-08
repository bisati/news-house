"""Reader feedback: recording reactions and turning them into topic/source weights."""
from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select

from newshouse.models import Card, Cluster, ClusterItem, Feedback, ItemSource

ACTIONS = ("worth", "skip", "later", "should_have", "tune", "seen", "read")


WEIGHTED = ("worth", "skip", "later", "should_have")  # the actions that move weights
TUNE_TOPIC_STEP = 0.3   # a tune tap moves a topic weight this far, for the next edition only
TUNE_BUDGET_STEP = 120  # ... or the budget this many seconds


@dataclass
class Weights:
    topic: dict[str, float] = field(default_factory=dict)
    source: dict[str, float] = field(default_factory=dict)


def record_feedback(session, *, profile_id: str, action: str, card_id: str | None = None,
                    cluster_id: str | None = None, at: datetime,
                    payload: dict | None = None, id: str | None = None) -> Feedback:
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}; expected one of {', '.join(ACTIONS)}")
    if action == "tune":
        check_tune_payload(payload)
    elif card_id is None and cluster_id is None:
        raise ValueError("card_id or cluster_id is required")
    fb = Feedback(id=id or uuid4().hex, profile_id=profile_id, card_id=card_id, cluster_id=cluster_id,
                  action=action, payload=payload, at=at)
    session.add(fb)
    session.flush()
    return fb


def _unit(v) -> bool:
    return type(v) is int and v in (1, -1)  # not True/False, not 1.0


def check_tune_payload(payload) -> None:
    """A tune payload is exactly {"topic": <slug>, "dir": 1 | -1} or {"budget": 1 | -1}."""
    if isinstance(payload, dict):
        if set(payload) == {"topic", "dir"} and isinstance(payload["topic"], str) \
                and payload["topic"] and _unit(payload["dir"]):
            return
        if set(payload) == {"budget"} and _unit(payload["budget"]):
            return
    raise ValueError('tune payload must be {"topic": str, "dir": 1|-1} or {"budget": 1|-1}')


def tune_adjustments(session, *, profile_id: str,
                     since: datetime | None) -> tuple[dict[str, float], int]:
    """Topic weight deltas and a budget delta (seconds) from the tune taps after ``since``.
    One step per chip per edition: a topic's delta is its last tap's direction only, and the
    budget's is the last budget tap only, so a reload, second tab or second device that taps
    again does not stack."""
    q = select(Feedback).where(Feedback.profile_id == profile_id, Feedback.action == "tune")
    if since is not None:
        q = q.where(Feedback.at > since)
    topics: dict[str, float] = {}
    budget = 0
    for fb in session.scalars(q.order_by(Feedback.at)).all():
        p = fb.payload
        try:
            check_tune_payload(p)
        except ValueError:
            continue  # a row from before the payload rule
        if "budget" in p:  # rows are in tap order: the last one wins
            budget = TUNE_BUDGET_STEP * p["budget"]
        else:
            topics[p["topic"]] = TUNE_TOPIC_STEP * p["dir"]
    return topics, budget


def _bump(d: dict[str, float], key: str, r: float, alpha: float) -> None:
    w = d.get(key, 0.0)
    d[key] = max(-1.0, min(1.0, w + alpha * (r - w)))


def compute_weights(session, *, profile_id: str, alpha: float = 0.2) -> Weights:
    weights = Weights()
    rows = session.scalars(select(Feedback).where(Feedback.profile_id == profile_id,
                                  Feedback.action.in_(WEIGHTED))
                           .order_by(Feedback.at)).all()
    for fb in rows:
        cid = fb.cluster_id
        if fb.card_id is not None:
            card = session.get(Card, fb.card_id)
            cid = card.cluster_id if card is not None else None
        cluster = session.get(Cluster, cid) if cid else None
        if cluster is None:
            continue
        r = -1.0 if fb.action == "skip" else 1.0
        sources = sorted(set(session.scalars(
            select(ItemSource.source_id).join(ClusterItem, ClusterItem.item_id == ItemSource.item_id)
            .where(ClusterItem.cluster_id == cluster.id)).all()))
        for t in cluster.topics or []:
            _bump(weights.topic, t, r, alpha)
        for s in sources:
            _bump(weights.source, s, r, alpha)
    return weights
