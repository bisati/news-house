"""Local server: serves the out/ directory and accepts POST /feedback from the page."""
import functools
import http.server
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from newshouse.config import get_settings
from newshouse.db import get_engine, session_scope
from newshouse.feedback import ACTIONS, check_tune_payload, record_feedback
from newshouse.models import Card, Cluster

log = logging.getLogger("newshouse.serve")
MAX_BODY = 64 * 1024


class FeedbackHandler(http.server.SimpleHTTPRequestHandler):
    timeout = 10  # seconds a request may stall on the socket (slow or short body)

    def __init__(self, *args, engine=None, profile_id=None, **kwargs):
        self.engine = engine
        self.profile_id = profile_id
        super().__init__(*args, **kwargs)

    def log_message(self, format, *args):
        log.info("%s %s", self.address_string(), format % args)

    def _json(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/":
            self.send_response(302)
            self.send_header("Location", "/latest.html")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        super().do_GET()

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/feedback":
            self._json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._json(400, {"error": "bad Content-Length"})
            return
        if length < 0:
            self._json(400, {"error": "bad Content-Length"})
            return
        if length > MAX_BODY:
            self.close_connection = True
            self._json(413, {"error": "body too large"})
            return
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            self._json(400, {"error": "body is not valid JSON"})
            return
        if not isinstance(body, dict):
            self._json(400, {"error": "body must be a JSON object"})
            return
        action = body.get("action")
        if action not in ACTIONS:
            self._json(400, {"error": f"unknown action; expected one of {', '.join(ACTIONS)}"})
            return
        card_id, cluster_id = body.get("card_id"), body.get("cluster_id")
        payload = body.get("payload")
        if action == "tune":  # an edition-wide tap: ids optional, payload checked
            try:
                check_tune_payload(payload)
            except ValueError as e:
                self._json(400, {"error": str(e)})
                return
        if card_id is None and cluster_id is None and action == "tune":
            target = None
        elif (card_id is None) == (cluster_id is None):
            self._json(400, {"error": "exactly one of card_id or cluster_id is required"})
            return
        else:
            target = card_id if card_id is not None else cluster_id
            if not isinstance(target, str) or not target:
                self._json(400, {"error": "card_id / cluster_id must be a string"})
                return
        if payload is not None and not isinstance(payload, dict):
            self._json(400, {"error": "payload must be an object"})
            return
        try:
            with session_scope(self.engine) as s:
                model = Card if card_id is not None else Cluster
                if target is not None and s.get(model, target) is None:
                    self._json(400, {"error": f"{model.__name__.lower()} not found"})
                    return
                fb = record_feedback(s, profile_id=self.profile_id, action=action,
                                     card_id=card_id, cluster_id=cluster_id,
                                     at=datetime.now(timezone.utc), payload=payload)
                fid = fb.id
        except Exception:
            log.exception("feedback failed")
            self._json(500, {"error": "internal"})
            return
        self._json(201, {"id": fid})


def make_server(out_dir: Path, *, host: str = "0.0.0.0", port: int = 8787, engine=None,
                profile_id: str | None = None) -> http.server.ThreadingHTTPServer:
    handler = functools.partial(
        FeedbackHandler, directory=str(out_dir),
        engine=engine if engine is not None else get_engine(),
        profile_id=profile_id or get_settings().profile_id)
    return http.server.ThreadingHTTPServer((host, port), handler)


def serve(out_dir: Path, *, host: str, port: int) -> None:
    srv = make_server(out_dir, host=host, port=port)
    print(f"serving {out_dir} on http://{host}:{srv.server_address[1]}/", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
