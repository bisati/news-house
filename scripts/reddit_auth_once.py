"""One-time Reddit OAuth flow (works with 2FA). Prints REDDIT_REFRESH_TOKEN=... to paste
into ~/.config/news-house/reddit.env. Needs REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET."""
import os
import secrets
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

REDIRECT = "http://localhost:8080"
ENV_FILE = Path("~/.config/news-house/reddit.env").expanduser()


def load_creds() -> tuple[str, str]:
    vals = {k: os.environ[k] for k in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET") if k in os.environ}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip() in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET") and k.strip() not in vals:
                vals[k.strip()] = v.strip().strip('"')
    if len(vals) < 2:
        sys.exit("Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET (env or reddit.env)")
    return vals["REDDIT_CLIENT_ID"], vals["REDDIT_CLIENT_SECRET"]


def main() -> None:
    cid, secret = load_creds()
    state = secrets.token_urlsafe(16)
    got: dict[str, list[str]] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            got.update(parse_qs(urlparse(self.path).query))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Done. You can close this tab.")

        def log_message(self, *a):
            pass

    server = HTTPServer(("localhost", 8080), Handler)
    webbrowser.open("https://www.reddit.com/api/v1/authorize?" + urlencode({
        "client_id": cid, "response_type": "code", "state": state,
        "redirect_uri": REDIRECT, "duration": "permanent", "scope": "read"}))
    server.handle_request()
    if got.get("state", [""])[0] != state or "code" not in got:
        sys.exit(f"Authorization failed: {got}")
    r = httpx.post("https://www.reddit.com/api/v1/access_token", auth=(cid, secret),
                   headers={"User-Agent": "macos:news-house:0.1 (auth once)"},
                   data={"grant_type": "authorization_code", "code": got["code"][0],
                         "redirect_uri": REDIRECT})
    token = r.json().get("refresh_token")
    if r.status_code != 200 or not token:
        sys.exit(f"Token exchange failed: {r.status_code} {r.text}")
    print(f"REDDIT_REFRESH_TOKEN={token}")


if __name__ == "__main__":
    main()
