import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from newshouse.feedback import ACTIONS as PIPELINE_ACTIONS

SITE = Path(__file__).resolve().parent.parent / "site"


def _load():
    spec = importlib.util.spec_from_file_location("site_feedback", SITE / "api" / "feedback.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fn = _load()


def raw(obj):
    return json.dumps(obj).encode()


def test_function_actions_match_pipeline():
    assert tuple(fn.ACTIONS) == tuple(PIPELINE_ACTIONS)


@pytest.mark.parametrize("body", [
    {"action": "worth", "card_id": "abc"},
    {"action": "tune", "payload": {"topic": "ai", "dir": "up"}},
    {"action": "tune"},
])
def test_function_accepts_good_bodies(body):
    status, parsed, err = fn.check_body(raw(body))
    assert (status, parsed, err) == (204, body, None)


@pytest.mark.parametrize("data", [
    b"",
    b"x" * 5000,
    raw({"action": "worth", "card_id": "a", "payload": {"k": "v" * 5000}}),
    b"not json",
    raw([1, 2]),
    raw({"action": "explode"}),
    raw({"action": "worth", "card_id": "a" * 65}),
    raw({"action": "worth", "cluster_id": 5}),
    raw({"action": "tune", "payload": [1]}),
])
def test_function_rejects_bad_bodies(data):
    status, parsed, err = fn.check_body(data)
    assert status in (400, 413) and parsed is None and err
    if len(data) > 4096:
        assert status == 413


class FakeConn:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))


def test_function_stores_row():
    conn = FakeConn()
    now = datetime(2026, 11, 3, tzinfo=timezone.utc)
    body = {"action": "worth", "card_id": "c1"}
    rid = fn.store(conn, body, now=now)
    assert len(rid) == 32 and int(rid, 16) >= 0
    (sql, params), = conn.calls
    assert "feedback_inbox" in sql
    assert params[0] == rid and params[1] == now
    assert params[2].obj == body


def test_vercel_json_rules():
    cfg = json.loads((SITE / "vercel.json").read_text())
    assert {"source": "/feedback", "destination": "/api/feedback"} in cfg["rewrites"]
    assert any(r["source"] == "/" and r["destination"] == "/latest.html" for r in cfg["redirects"])
    hdrs = {h["source"]: {x["key"]: x["value"] for x in h["headers"]} for h in cfg["headers"]}
    assert hdrs["/(.*)\\.html"]["Cache-Control"] == "no-cache"
    # font file names are fixed, so a changed font must reach readers within a day
    assert hdrs["/fonts/(.*)"]["Cache-Control"] == "public, max-age=86400"


@pytest.mark.parametrize("data", [
    b'{"action": "worth", "payload": {"x": NaN}}',
    b'{"action": "worth", "payload": {"x": Infinity}}',
    b'{"action": "worth", "payload": {"x": -Infinity}}',
])
def test_function_rejects_non_finite_numbers(data):
    status, parsed, err = fn.check_body(data)
    assert status == 400 and parsed is None and err


ROOT = SITE.parent


@pytest.mark.parametrize("cfg_path", [ROOT / "vercel.json", SITE / "vercel.json"])
@pytest.mark.parametrize("ref,code", [("main", 0), ("v2/hosting", 0), ("", 0), ("site", 1)])
def test_vercel_builds_only_the_site_branch(cfg_path, ref, code):
    """Vercel's ignoreCommand: exit 0 skips the build, exit 1 builds."""
    import os
    import subprocess
    cmd = json.loads(cfg_path.read_text())["ignoreCommand"]
    env = {"PATH": os.environ["PATH"], "VERCEL_GIT_COMMIT_REF": ref}
    assert subprocess.run(cmd, shell=True, env=env, timeout=10).returncode == code


def test_function_connects_with_timeouts(monkeypatch):
    import sys
    import types
    seen = {}

    class Conn:
        def execute(self, sql, *a):
            seen.setdefault("sql", []).append(sql)

    def connect(url, **kw):
        seen.update(url=url, kw=kw)
        return Conn()

    monkeypatch.setitem(sys.modules, "psycopg", types.SimpleNamespace(connect=connect))
    monkeypatch.setenv("NEON_DATABASE_URL", "postgresql://u:p@example.invalid/db")
    fn.connect()
    assert seen["url"] == "postgresql://u:p@example.invalid/db"
    assert seen["kw"] == {"connect_timeout": 5}
    assert seen["sql"] == ["SET statement_timeout = '5s'"]
