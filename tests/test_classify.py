import re
from datetime import datetime, timedelta, timezone

from newshouse.classify import classify_clusters, feedback_examples, render_cluster_for_classify
from newshouse.config import Settings
from newshouse.llm.backend import LLMError
from newshouse.llm.fake import FakeBackend
from newshouse.models import Card, Cluster, ClusterItem, Edition, Feedback, Item, ItemSource, Profile, Source
from newshouse.profile import load_profile

NOW = datetime(2026, 10, 30, 6, 0, tzinfo=timezone.utc)


def mk_clusters(session, n):
    for i in range(n):
        session.add(Cluster(id=f"c{i:03d}", window_start=NOW, topics=["ai-models"],
                            created_at=NOW + timedelta(seconds=i)))
    session.flush()


def fake(**over):
    def fn(system, user, schema, model):
        ids = re.findall(r"^### cluster (\S+)", user, re.M)
        res = [{"cluster_id": i, "story_type": "launch", "topics": ["football"], "importance": 77,
                "early": 12, "reason": "r", "breaking_eligible": True, "is_delta": False} | over
               for i in ids]
        return {"results": res}
    return FakeBackend(fn)


def test_classify_batches_of_50_and_writes_scores(session):
    mk_clusters(session, 120)
    b = fake()
    n = classify_clusters(session, b, profile_text="p", batch=50, now=NOW)
    assert n == 120 and len(b.calls) == 3
    cs = session.query(Cluster).all()
    assert all(c.scored_at == NOW and c.importance == 77 and c.early == 12 and c.story_type == "launch"
               and c.topics == ["football"] and c.breaking_eligible and not c.is_delta for c in cs)
    assert b.calls[0]["model"] == "haiku" and "Score these 50 clusters" in b.calls[0]["user"]


def test_classify_system_prompt_contains_profile_and_examples(session):
    mk_clusters(session, 1)
    ed = Edition(id="e", date=NOW.date(), budget_seconds=1)
    session.add(ed)
    session.flush()
    for cid, h, act in [("k1", "Good headline", "worth"), ("k2", "Bad headline", "skip")]:
        session.add(Card(id=cid, edition_id="e", rank=1, cluster_id="c000", format="line", payload={},
                         headline=h, line="", para="", brief="", why="", est_seconds=1, cited_item_ids=[]))
        session.add(Feedback(id="f" + cid, card_id=cid, action=act, at=NOW))
    session.flush()
    b = fake()
    classify_clusters(session, b, profile_text="Mihir likes Barca", now=NOW)
    s = b.calls[0]["system"]
    assert "Mihir likes Barca" in s and "- Good headline" in s and "- Bad headline" in s
    assert "importance" in s


def test_feedback_latest_action_and_no_sections_when_empty(session):
    mk_clusters(session, 1)
    session.add(Edition(id="e", date=NOW.date(), budget_seconds=1))
    session.flush()
    session.add(Card(id="k", edition_id="e", rank=1, cluster_id="c000", format="line", payload={},
                     headline="H", line="", para="", brief="", why="", est_seconds=1, cited_item_ids=[]))
    session.add_all([Feedback(id="a", card_id="k", action="worth", at=NOW),
                     Feedback(id="b", card_id="k", action="skip", at=NOW + timedelta(hours=1)),
                     Feedback(id="c", card_id=None, cluster_id="c000", action="worth", at=NOW)])
    session.flush()
    assert feedback_examples(session, profile_id="mihir") == ([], ["H"])


def test_no_reactions_section_without_feedback(session):
    mk_clusters(session, 1)
    b = fake()
    classify_clusters(session, b, profile_text="P", now=NOW)
    assert "## Recent reactions" not in b.calls[0]["system"] and "## Profile\nP" in b.calls[0]["system"]


def test_profile_versioning(session, tmp_path):
    p = tmp_path / "profile.md"
    p.write_text("one")
    st = Settings(profile_path=p, profile_id="mihir")
    a = load_profile(session, st)
    b = load_profile(session, st)
    assert a.id == b.id and a.version == 1
    p.write_text("two")
    c = load_profile(session, st)
    assert c.version == 2 and c.text == "two"
    assert session.query(Profile).count() == 2


def test_profile_missing_file(session, tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError, match="nope.md"):
        load_profile(session, Settings(profile_path=tmp_path / "nope.md"))


def test_missing_cluster_in_response_stays_unscored(session):
    mk_clusters(session, 3)

    def fn(system, user, schema, model):
        r = fake().complete_json(system=system, user=user, schema=schema, model=model)
        r["results"] = [x for x in r["results"] if x["cluster_id"] != "c001"]
        r["results"].append({"cluster_id": "zzz", "story_type": "plain", "topics": [], "importance": 1,
                             "early": 1, "reason": "", "breaking_eligible": False, "is_delta": True})
        return r
    n = classify_clusters(session, FakeBackend(fn), profile_text="p", now=NOW)
    assert n == 2
    assert session.get(Cluster, "c001").scored_at is None
    assert session.get(Cluster, "c000").scored_at == NOW


def test_validation_rules(session):
    mk_clusters(session, 3)
    vals = {"c000": dict(story_type="bogus", importance=500, early=-5, topics=["nonsense"], reason="x" * 400),
            "c001": dict(topics=[], importance=40),
            "c002": dict(topics=["cricket", "bad"])}

    def fn(system, user, schema, model):
        return {"results": [{"cluster_id": k, "story_type": "launch", "topics": ["football"], "importance": 1,
                             "early": 1, "reason": "r", "breaking_eligible": False, "is_delta": True} | v
                            for k, v in vals.items()]}
    classify_clusters(session, FakeBackend(fn), profile_text="p", now=NOW)
    c0, c1, c2 = (session.get(Cluster, f"c00{i}") for i in range(3))
    assert c0.story_type == "plain" and c0.importance == 100 and c0.early == 0
    assert c0.topics == ["ai-models"] and len(c0.reason) == 300
    assert c1.topics == ["ai-models"] and c2.topics == ["ai-models"] and c1.importance == 40


def test_failed_batch_skipped_later_batches_run(session):
    mk_clusters(session, 4)
    calls = []

    def fn(system, user, schema, model):
        calls.append(1)
        if len(calls) == 1:
            raise LLMError("boom")
        return fake().complete_json(system=system, user=user, schema=schema, model=model)
    n = classify_clusters(session, FakeBackend(fn), profile_text="p", batch=2, now=NOW)
    assert n == 2 and len(calls) == 2
    assert session.get(Cluster, "c000").scored_at is None and session.get(Cluster, "c003").scored_at == NOW


def test_render_cluster(session):
    c = Cluster(id="cx", window_start=NOW, topics=["ai-models", "football"])
    src = [Source(id=f"s{i}", name=f"N{i}", topics=[], tier="primary", kind="rss", url=f"u{i}", paywall=False)
           for i in range(10)]
    items = [Item(id=f"i{i}", title=f"T{i}", url="u", canonical_url="u", teaser="x" * 400,
                  published_at=NOW - timedelta(hours=i), first_seen_at=NOW, dated=True, topics=[], raw={})
             for i in range(7)]
    sbi = {it.id: [src[j] for j in range(10)] for it in items}
    out = render_cluster_for_classify(c, items, sbi, now=NOW)
    lines = out.split("\n")
    assert lines[0] == "### cluster cx" and lines[1] == "topics: ai-models, football"
    assert lines[2].count("(primary)") == 8 and lines[3] == "items: 7"
    assert len(lines) == 9 and lines[4].startswith("- [0h] T0 — x") and len(lines[4].split(" — ")[1]) == 300
    assert "T5" not in out


def test_classify_stores_tone(session):
    mk_clusters(session, 3)
    tones = {"c000": "bad", "c001": "angry"}

    def fn(system, user, schema, model):
        res = []
        for cid in ("c000", "c001", "c002"):
            r = {"cluster_id": cid, "story_type": "plain", "topics": ["football"], "importance": 1,
                 "early": 1, "reason": "r", "breaking_eligible": False, "is_delta": True}
            if cid in tones:
                r["tone"] = tones[cid]
            res.append(r)
        return {"results": res}
    classify_clusters(session, FakeBackend(fn), profile_text="p", now=NOW)
    assert session.get(Cluster, "c000").tone == "bad"
    assert session.get(Cluster, "c001").tone is None
    assert session.get(Cluster, "c002").tone is None


def test_classify_prompt_has_lessons(session, tmp_path):
    from newshouse.lessons import Lesson, save_lessons
    path = tmp_path / "lessons.json"
    lessons = [Lesson(id=f"l{i:02d}", date=f"2026-10-{i + 1:02d}", miss=f"Miss number {i:02d}",
                      fix="Raise cricket cap" if i == 10 else "") for i in range(11)]
    save_lessons(path, lessons)
    mk_clusters(session, 1)
    b = fake()
    classify_clusters(session, b, profile_text="p", now=NOW, lessons_path=path)
    s = b.calls[0]["system"]
    assert "## Lessons" in s
    assert all(f"- Miss number {i:02d}" in s for i in range(1, 11))
    assert "Miss number 00" not in s
    assert "- Miss number 10 Fix: Raise cricket cap" in s


def test_classify_without_lessons_file(session, tmp_path):
    mk_clusters(session, 1)
    b = fake()
    classify_clusters(session, b, profile_text="p", now=NOW, lessons_path=tmp_path / "none.json")
    assert "## Lessons" not in b.calls[0]["system"]


def test_known_topics_include_new_slugs():
    from newshouse.classify import KNOWN_TOPICS
    assert {"startups", "ai-tools"} <= KNOWN_TOPICS
