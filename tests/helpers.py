"""Shared test seeding: one edition of cards, each on its own cluster and item."""
from datetime import date, datetime, timezone

from newshouse.models import AlsoHappened, Card, Cluster, ClusterItem, Edition, Item, ItemSource, Source

NOW = datetime(2026, 10, 30, 6, 0, tzinfo=timezone.utc)


def seed_edition(session, specs, *, also=()):
    """specs: list of (rank, format, headline, payload, extra) -> edition "e1".

    Card n is "card{n}" on cluster "c{n}" citing item "i{n}"; ``also`` holds
    AlsoHappened kwargs beyond edition_id.
    """
    session.add(Source(id="s1", name="Wire", topics=["ai"], tier="mainstream", kind="rss",
                       url="https://feeds/s1", paywall=False))
    ed = Edition(id="e1", date=date(2026, 10, 30), built_at=NOW, budget_seconds=900, cut_score=40.0)
    session.add(ed)
    session.flush()
    for n, (rank, fmt, headline, payload, extra) in enumerate(specs):
        cid, iid = f"c{n}", f"i{n}"
        session.add(Item(id=iid, title=f"Source title {n}", url=f"http://x/{n}", canonical_url=f"http://x/{n}",
                         teaser="t", published_at=NOW, first_seen_at=NOW, dated=True, topics=[], raw={}))
        session.add(Cluster(id=cid, window_start=NOW, topics=["ai-models"], chapter=0))
        session.flush()
        session.add(ItemSource(item_id=iid, source_id="s1"))
        session.add(ClusterItem(cluster_id=cid, item_id=iid))
        kw = dict(id=f"card{n}", edition_id="e1", rank=rank, cluster_id=cid, format=fmt, payload=payload,
                  headline=headline, line=f"Line {n}", para=f"Para {n}", brief=f"Brief {n}", why=f"Why {n}",
                  est_seconds=60, cited_item_ids=[iid])
        kw.update(extra)
        session.add(Card(**kw))
    for a in also:
        session.add(AlsoHappened(edition_id="e1", **a))
    session.flush()
    return ed
