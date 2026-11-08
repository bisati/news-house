import threading
from contextlib import contextmanager
from datetime import datetime, timezone

import httpx
from sqlalchemy import func, select

from newshouse.db import session_scope
from newshouse.models import Card, Cluster, Edition, Feedback
from newshouse.serve import make_server

NOW = datetime(2026, 10, 30, 6, 0, tzinfo=timezone.utc)


def seed(session):
    session.add(Cluster(id="cl0", window_start=NOW, topics=[]))
    session.add(Edition(id="e1", date=NOW.date(), budget_seconds=900))
    session.flush()
    session.add(Card(id="card0", edition_id="e1", rank=1, cluster_id="cl0", format="A", payload={},
                     headline="h", line="", para="", brief="", why="", est_seconds=35,
                     cited_item_ids=[]))
    session.commit()


@contextmanager
def running(session, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "latest.html").write_text("<p>hi</p>")
    srv = make_server(out, host="127.0.0.1", port=0, engine=session.get_bind(), profile_id="mihir")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{srv.server_address[1]}") as c:
            yield c
    finally:
        srv.shutdown()
        srv.server_close()


def count(engine):
    with session_scope(engine) as s:
        return s.scalar(select(func.count()).select_from(Feedback))


def test_serve_page_and_feedback(session, tmp_path):
    seed(session)
    with running(session, tmp_path) as c:
        r = c.get("/latest.html")
        assert r.status_code == 200 and "hi" in r.text
        r = c.get("/")
        assert r.status_code == 302 and r.headers["location"] == "/latest.html"
        r = c.post("/feedback", json={"action": "worth", "card_id": "card0"})
        assert r.status_code == 201
        fid = r.json()["id"]
        r = c.post("/feedback", json={"action": "tune", "cluster_id": "cl0",
                                         "payload": {"budget": 1}})
        assert r.status_code == 201
        assert c.post("/nope", json={}).status_code == 404
    with session_scope(session.get_bind()) as s:
        fb = s.get(Feedback, fid)
        assert fb.action == "worth" and fb.card_id == "card0" and fb.profile_id == "mihir"
    assert count(session.get_bind()) == 2


def test_serve_rejects_bad_feedback(session, tmp_path):
    seed(session)
    with running(session, tmp_path) as c:
        bad = [
            {"action": "like", "card_id": "card0"},
            {"action": "worth", "card_id": "nope"},
            {"action": "worth", "cluster_id": "nope"},
            {"action": "worth"},
            {"action": "worth", "card_id": "card0", "cluster_id": "cl0"},
            {"action": "worth", "card_id": "card0", "payload": [1]},
            {"action": "worth", "card_id": 5},
            [1, 2],
        ]
        for body in bad:
            r = c.post("/feedback", json=body)
            assert r.status_code == 400 and "error" in r.json(), body
        r = c.post("/feedback", content=b"not json")
        assert r.status_code == 400 and "error" in r.json()
        r = c.post("/feedback", content=b"x" * 70000)
        assert r.status_code == 413
    assert count(session.get_bind()) == 0


def raw_post(port, head, body=b""):
    import socket
    s = socket.create_connection(("127.0.0.1", port), timeout=12)
    s.sendall(b"POST /feedback HTTP/1.1\r\nHost: x\r\n" + head + b"\r\n\r\n" + body)
    return s


def test_serve_short_body_times_out(session, tmp_path, monkeypatch):
    import time
    from newshouse.serve import FeedbackHandler
    monkeypatch.setattr(FeedbackHandler, "timeout", 1)
    seed(session)
    with running(session, tmp_path) as c:
        s = raw_post(c.base_url.port, b"Content-Length: 1000", b"0123456789")
        t0 = time.time()
        try:
            data = s.recv(100)
        except OSError:
            data = b""
        s.close()
        assert data == b"" and time.time() - t0 < 12
    assert count(session.get_bind()) == 0


def test_serve_negative_content_length(session, tmp_path):
    seed(session)
    with running(session, tmp_path) as c:
        s = raw_post(c.base_url.port, b"Content-Length: -1")
        assert s.recv(100).startswith(b"HTTP/1.0 400")
        s.close()
    assert count(session.get_bind()) == 0


def test_serve_internal_error_is_json_500(session, tmp_path, monkeypatch):
    import newshouse.serve as sv

    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(sv, "record_feedback", boom)
    seed(session)
    with running(session, tmp_path) as c:
        r = c.post("/feedback", json={"action": "worth", "card_id": "card0"})
        assert r.status_code == 500 and r.json() == {"error": "internal"}
        assert c.get("/latest.html").status_code == 200
    assert count(session.get_bind()) == 0


def test_serve_accepts_tune_without_ids(session, tmp_path):
    seed(session)
    with running(session, tmp_path) as c:
        r = c.post("/feedback", json={"action": "tune", "payload": {"topic": "movies", "dir": 1}})
        assert r.status_code == 201
        fid = r.json()["id"]
        assert c.post("/feedback", json={"action": "tune", "payload": {"budget": -1}}).status_code == 201
        for bad in ({"action": "tune"}, {"action": "tune", "payload": {"budget": 3}},
                    {"action": "tune", "payload": {"topic": "movies", "dir": 1, "x": 0}},
                    {"action": "tune", "payload": {"a": 1}},
                    {"action": "tune", "card_id": "nope", "payload": {"budget": 1}}):
            r = c.post("/feedback", json=bad)
            assert r.status_code == 400 and "error" in r.json(), bad
    with session_scope(session.get_bind()) as s:
        fb = s.get(Feedback, fid)
        assert fb.action == "tune" and fb.card_id is None and fb.cluster_id is None
        assert fb.payload == {"topic": "movies", "dir": 1}
    assert count(session.get_bind()) == 2
