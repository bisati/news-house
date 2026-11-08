"""Vercel serverless function: receives taps from the page and stores them in Neon.

Self-contained (Vercel installs only site/requirements.txt). The database URL comes only
from the NEON_DATABASE_URL environment variable and is never logged or returned.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler

# Kept equal to newshouse.feedback.ACTIONS by tests/test_site_function.py.
ACTIONS = ("worth", "skip", "later", "should_have", "tune", "seen", "read")
MAX_BODY = 4096
MAX_ID = 64

INSERT = ("INSERT INTO feedback_inbox (id, received_at, body, synced_at) "
          "VALUES (%s, %s, %s, NULL)")


def _no_constant(name: str):
    raise ValueError(f"{name} is not allowed")  # Postgres json rejects NaN and Infinity


def check_body(raw: bytes) -> tuple[int, dict | None, str | None]:
    """Return (status, parsed body or None, error). 204 means the body is acceptable."""
    if not raw:
        return 400, None, "empty body"
    if len(raw) > MAX_BODY:
        return 413, None, "body too large"
    try:
        body = json.loads(raw, parse_constant=_no_constant)
    except (ValueError, UnicodeDecodeError):
        return 400, None, "body is not JSON"
    if not isinstance(body, dict):
        return 400, None, "body must be an object"
    if body.get("action") not in ACTIONS:
        return 400, None, "unknown action"
    for key in ("card_id", "cluster_id"):
        v = body.get(key)
        if v is not None and (not isinstance(v, str) or len(v) > MAX_ID):
            return 400, None, f"bad {key}"
    if body.get("payload") is not None and not isinstance(body["payload"], dict):
        return 400, None, "payload must be an object"
    return 204, body, None


def store(conn, body: dict, *, now: datetime) -> str:
    from psycopg.types.json import Json
    rid = uuid.uuid4().hex
    conn.execute(INSERT, (rid, now, Json(body)))
    return rid


def connect():
    """A Neon connection that gives up fast: the page's tap must not hang on a slow
    database (connect 5 s, each statement 5 s)."""
    import psycopg
    conn = psycopg.connect(os.environ["NEON_DATABASE_URL"], connect_timeout=5)
    conn.execute("SET statement_timeout = '5s'")
    return conn


class handler(BaseHTTPRequestHandler):
    def _reply(self, status: int, error: str | None = None) -> None:
        data = b"" if status == 204 else json.dumps({"error": error}).encode()
        self.send_response(status)
        if data:
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if data:
            self.wfile.write(data)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self._reply(400, "Content-Length required")
        if length < 0:
            return self._reply(400, "Content-Length required")
        if length > MAX_BODY:
            return self._reply(413, "body too large")
        status, body, err = check_body(self.rfile.read(length))
        if body is None:
            return self._reply(status, err)
        try:
            with connect() as conn:
                store(conn, body, now=datetime.now(timezone.utc))
        except Exception:  # never echo driver errors: they can carry connection details
            return self._reply(503, "storage unavailable")
        self._reply(204)

    def _not_allowed(self):
        self._reply(405, "POST only")

    do_GET = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _not_allowed

    def log_message(self, *args):
        pass
