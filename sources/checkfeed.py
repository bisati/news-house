#!/usr/bin/env python3
"""Verify RSS/Atom/JSON feeds: are they alive, and how much did they publish recently?

Usage:
  python3 -I checkfeed.py URL [URL ...]
  python3 -I checkfeed.py -f urls.txt        # one URL per line, '#' comments ok

Prints one JSON object per line:
  {"url":..., "ok":bool, "kind":"rss|atom|json|html|error", "title":..., "items":N,
   "last7d":N, "last30d":N, "latest":"YYYY-MM-DD", "http":code, "err":...}
Exit code is always 0; look at "ok".
"""
import sys, json, re, urllib.request, urllib.error, email.utils, datetime as dt
import xml.etree.ElementTree as ET

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 feedcheck/0.1"
NOW = dt.datetime.now(dt.timezone.utc)

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, application/json, */*"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status, r.read(2_000_000), r.headers.get("Content-Type", "")

def parse_date(s):
    if not s: return None
    s = s.strip()
    try:
        d = email.utils.parsedate_to_datetime(s)
        if d.tzinfo is None: d = d.replace(tzinfo=dt.timezone.utc)
        return d
    except Exception: pass
    try:
        s2 = s.replace("Z", "+00:00")
        d = dt.datetime.fromisoformat(s2)
        if d.tzinfo is None: d = d.replace(tzinfo=dt.timezone.utc)
        return d
    except Exception: pass
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    if m:
        return dt.datetime.fromisoformat(m.group(1)).replace(tzinfo=dt.timezone.utc)
    return None

def strip_ns(tag):
    return tag.split("}", 1)[1] if "}" in tag else tag

def summarize(dates, title, kind, n):
    valid = [d for d in dates if d]
    last7 = sum(1 for d in valid if (NOW - d).days < 7)
    last30 = sum(1 for d in valid if (NOW - d).days < 30)
    latest = max(valid).strftime("%Y-%m-%d") if valid else None
    return {"ok": True, "kind": kind, "title": (title or "").strip()[:80], "items": n, "dated": len(valid), "last7d": last7, "last30d": last30, "latest": latest}

def parse_xml(body):
    root = ET.fromstring(body)
    rt = strip_ns(root.tag)
    if rt == "rss" or rt == "RDF":
        chan = root.find("channel")
        if chan is None: chan = root.find("{http://purl.org/rss/1.0/}channel")
        title = None
        if chan is not None:
            t = chan.find("title")
            if t is None: t = chan.find("{http://purl.org/rss/1.0/}title")
            title = t.text if t is not None else None
        items = [e for e in root.iter() if strip_ns(e.tag) == "item"]
        dates = []
        for it in items:
            d = None
            for c in it:
                if strip_ns(c.tag) in ("pubDate", "date", "updated", "published"):
                    d = parse_date(c.text);
                    if d: break
            dates.append(d)
        return summarize(dates, title, "rss", len(items))
    if rt == "feed":
        t = next((c for c in root if strip_ns(c.tag) == "title"), None)
        title = t.text if t is not None else None
        entries = [e for e in root if strip_ns(e.tag) == "entry"]
        dates = []
        for en in entries:
            d = None
            for c in en:
                if strip_ns(c.tag) in ("published", "updated"):
                    d = parse_date(c.text)
                    if d: break
            dates.append(d)
        return summarize(dates, title, "atom", len(entries))
    return {"ok": False, "kind": "xml-unknown", "err": f"root tag {rt}"}

def parse_json(body):
    data = json.loads(body)
    if isinstance(data, dict) and "items" in data and isinstance(data["items"], list):
        items = data["items"]
        dates = [parse_date(i.get("date_published") or i.get("date_modified") or "") for i in items if isinstance(i, dict)]
        return summarize(dates, data.get("title"), "json", len(items))
    # reddit listing
    if isinstance(data, dict) and data.get("kind") == "Listing":
        ch = data["data"]["children"]
        dates = [dt.datetime.fromtimestamp(c["data"]["created_utc"], dt.timezone.utc) for c in ch]
        return summarize(dates, data["data"].get("title") or "reddit listing", "reddit-json", len(ch))
    # HN algolia
    if isinstance(data, dict) and "hits" in data:
        dates = [parse_date(h.get("created_at")) for h in data["hits"]]
        return summarize(dates, "hn-algolia", "json", len(data["hits"]))
    return {"ok": False, "kind": "json-unknown", "err": "no items/hits/Listing"}

def check(url):
    out = {"url": url}
    try:
        status, body, ctype = fetch(url)
        out["http"] = status
    except urllib.error.HTTPError as e:
        out.update({"ok": False, "kind": "error", "http": e.code, "err": str(e)}); return out
    except Exception as e:
        out.update({"ok": False, "kind": "error", "err": str(e)[:120]}); return out
    head = body[:400].lstrip().lower()
    try:
        if head.startswith(b"{") or head.startswith(b"["):
            out.update(parse_json(body))
        elif b"<rss" in head or b"<feed" in head or b"<?xml" in head or b"<rdf" in head:
            out.update(parse_xml(body))
        elif b"<html" in head or b"<!doctype html" in head:
            # look for a feed link in the HTML so the caller can retry
            m = re.search(rb'<link[^>]+type=["\'](application/(?:rss|atom)\+xml)["\'][^>]*href=["\']([^"\']+)["\']', body, re.I)
            if not m:
                m = re.search(rb'<link[^>]+href=["\']([^"\']+)["\'][^>]*type=["\'](application/(?:rss|atom)\+xml)["\']', body, re.I)
                hint = m.group(1).decode() if m else None
            else:
                hint = m.group(2).decode() if m else None
            out.update({"ok": False, "kind": "html", "err": "got HTML, not a feed", "feed_hint": hint})
        else:
            try:
                out.update(parse_xml(body))
            except Exception:
                out.update({"ok": False, "kind": "unknown", "err": f"content-type {ctype[:40]}"})
    except Exception as e:
        out.update({"ok": False, "kind": "parse-error", "err": str(e)[:120]})
    return out

def main(argv):
    urls = []
    if len(argv) >= 2 and argv[0] == "-f":
        with open(argv[1]) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    urls.append(line.split()[-1] if " " in line else line)
    else:
        urls = argv
    for u in urls:
        print(json.dumps(check(u), ensure_ascii=False), flush=True)

if __name__ == "__main__":
    main(sys.argv[1:])
