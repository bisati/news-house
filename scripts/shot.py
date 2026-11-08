#!/usr/bin/env python3
"""Screenshot an edition page at four sizes with headless Chrome and fail on layout defects.

Usage: scripts/shot.py <page.html> <out_dir> [--keep] [--theme dark|light]

Headless Chrome (``--headless=new``) clamps its window to at least 500px wide, so a plain
``--window-size=390,844`` lays the page out at 500px. Instead each size loads a wrapper page
holding an ``<iframe>`` of exactly <w>x<h> that shows a copy of the page with a check script
injected. The check script writes its report into the page's ``document.title`` as
``NHCHECK:<json>``; the wrapper copies that title into its own, and ``--dump-dom`` of the
wrapper exposes it. At phone sizes the PNG therefore shows the page at the left of a 500px
window with a grey margin on the right; that margin is the wrapper, not the page.

The helper files (``_check-<w>x<h>.html``, ``_wrap-<w>x<h>.html``) are written next to the page
so its relative ``fonts/`` paths keep working, and deleted after the run unless ``--keep``.

``--theme dark`` (or ``light``) loads the page with ``?theme=dark`` so the night palette shows
whatever the headless system setting is, and names the PNGs ``<w>x<h>-dark.png``.

Exit codes: 0 all checks pass, 1 a check failed, 2 Chrome not found.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SIZES = [(390, 844), (430, 932), (768, 1024), (1280, 800)]
MAC_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CHROME_MIN_WIDTH = 500
PHONE_MAX_W = 430  # spec 3.3: a visual or deck is at most 320px tall at phone width
VISUAL_MAX_H = 320

CHECK_JS = """<script>
window.addEventListener("load", function () {
  // a lazy photo below the fold is never requested in a short screenshot run: load it now,
  // so a photo still 0 wide after the delay is a broken one
  document.querySelectorAll("img.photo").forEach(function (el) { el.loading = "eager"; });
  setTimeout(function () {
    var skip = {SCRIPT: 1, STYLE: 1, TITLE: 1, NOSCRIPT: 1};
    var minFont = null;
    document.querySelectorAll("body *").forEach(function (el) {
      if (skip[el.tagName] || el.closest("[hidden]") || el.getClientRects().length === 0) return;
      var own = Array.prototype.some.call(el.childNodes, function (n) {
        return n.nodeType === 3 && n.textContent.trim() !== "";
      });
      if (!own) return;
      var size = parseFloat(getComputedStyle(el).fontSize);
      if (minFont === null || size < minFont) minFont = size;
    });
    var emptyVisual = 0;
    document.querySelectorAll(".visual").forEach(function (el) {
      if (el.closest("[hidden]") || el.getClientRects().length === 0) return;
      if (el.getBoundingClientRect().height < 40) emptyVisual++;
    });
    var posts = document.querySelectorAll("article.post");
    var tallest = 0;
    posts.forEach(function (el) { tallest = Math.max(tallest, el.getBoundingClientRect().height); });
    var tallestVisual = 0;
    document.querySelectorAll(".visual, .slides").forEach(function (el) {
      if (el.closest("[hidden]") || el.getClientRects().length === 0) return;
      tallestVisual = Math.max(tallestVisual, el.getBoundingClientRect().height);
    });
    var deckSlides = [];
    document.querySelectorAll(".deck").forEach(function (el) {
      deckSlides.push(el.querySelectorAll(".slide").length);
    });
    var slideOverflow = 0;
    document.querySelectorAll(".slide").forEach(function (el) {
      if (el.scrollHeight > el.clientHeight + 1) slideOverflow++;
    });
    // a stack strip lives in the hidden expanded body: show it for a moment to measure it
    var tallestStack = 0, stackCount = 0;
    document.querySelectorAll(".stack").forEach(function (el) {
      var more = el.closest(".more");
      var was = more ? more.hidden : false;
      var post = el.closest(".post");
      if (more) more.hidden = false;
      if (post) post.classList.add("open");
      tallestStack = Math.max(tallestStack, el.getBoundingClientRect().height);
      stackCount++;
      if (post) post.classList.remove("open");
      if (more) more.hidden = was;
    });
    var brokenPhoto = 0;
    document.querySelectorAll("img.photo").forEach(function (el) {
      if (el.closest("[hidden]") || el.getClientRects().length === 0) return;
      if (el.naturalWidth === 0) brokenPhoto++;
    });
    var report = {
      ground: getComputedStyle(document.body).backgroundColor,
      overflow: document.documentElement.scrollWidth > window.innerWidth,
      min_font: minFont === null ? null : Math.round(minFont * 100) / 100,
      empty_visual: emptyVisual,
      tallest_post: Math.round(tallest / window.innerHeight * 100) / 100,
      posts: posts.length,
      viewport_w: window.innerWidth,
      tallest_visual: Math.round(tallestVisual * 10) / 10,
      deck_slides: deckSlides,
      slide_overflow: slideOverflow,
      stacks: stackCount,
      tallest_stack: Math.round(tallestStack * 10) / 10,
      broken_photo: brokenPhoto
    };
    document.title = "NHCHECK:" + JSON.stringify(report);
  }, 1200);
});
</script>"""

WRAP_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>NHWRAP</title>
<style>html,body{{margin:0;padding:0;background:#888}}iframe{{display:block;border:0;width:{w}px;height:{h}px;background:#fff}}</style>
</head><body>
<iframe id="f" src="{src}" width="{w}" height="{h}"></iframe>
<script>
var f = document.getElementById("f");
f.addEventListener("load", function () {{
  var tries = 0;
  setTimeout(function copy() {{
    var t = "";
    try {{ t = f.contentDocument.title; }} catch (e) {{ t = ""; }}
    if (t.indexOf("NHCHECK:") === 0) {{ document.title = t; return; }}
    if (++tries < 40) setTimeout(copy, 100);
  }}, {delay});
}});
</script>
</body></html>
"""

_REPORT = re.compile(r"<title>\s*NHCHECK:(.*?)</title>", re.S)


def inject_checks(page: str) -> str:
    """Return ``page`` with the check script before ``</body>`` (or appended when there is none)."""
    idx = page.rfind("</body>")
    if idx == -1:
        return page + CHECK_JS
    return page[:idx] + CHECK_JS + page[idx:]


def parse_report(dom: str) -> dict:
    """Read the ``NHCHECK:`` report from a dumped DOM; raise ``ValueError`` when absent."""
    m = _REPORT.search(dom)
    if not m:
        raise ValueError("no NHCHECK report in the dumped DOM: the page or the wrapper failed to load "
                         "or the check script did not finish within the virtual time budget")
    return json.loads(html.unescape(m.group(1)))


def frame_src(check_name: str, theme: str | None) -> str:
    """The wrapper's iframe ``src``: the check page, with ``?theme=<theme>`` when one is asked for."""
    return f"{check_name}?theme={theme}" if theme else check_name


def png_name(key: str, theme: str | None) -> str:
    """``390x844.png``, or ``390x844-dark.png`` under ``--theme dark``."""
    return f"{key}-{theme}.png" if theme else f"{key}.png"


def chrome_path() -> str | None:
    """Chrome from ``$CHROME`` or the default Mac install, or None."""
    for cand in (os.environ.get("CHROME"), MAC_CHROME):
        if cand and Path(cand).exists():
            return cand
    return None


def _chrome(chrome: str, w: int, h: int, *extra: str) -> subprocess.CompletedProcess:
    args = [chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--allow-file-access-from-files",
            "--virtual-time-budget=8000", f"--window-size={max(w, CHROME_MIN_WIDTH)},{h}", *extra]
    return subprocess.run(args, capture_output=True, text=True, timeout=120)


def shoot(html_path: Path, out_dir: Path, *, chrome: str, sizes=SIZES, delay_ms: int = 1500,
          keep: bool = False, theme: str | None = None) -> dict[str, dict]:
    """Screenshot ``html_path`` at each size into ``out_dir/<w>x<h>.png`` (``<w>x<h>-<theme>.png``
    with a theme) and return the check reports.

    ``delay_ms`` is the wrapper's wait after the iframe's load event before it starts copying
    the report (the page's own checks run 1200 ms after load)."""
    html_path, out_dir = Path(html_path).resolve(), Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    checked = inject_checks(html_path.read_text())
    reports: dict[str, dict] = {}
    for w, h in sizes:
        key = f"{w}x{h}"
        check = html_path.parent / f"_check-{key}.html"
        wrap = html_path.parent / f"_wrap-{key}.html"
        try:
            check.write_text(checked)
            wrap.write_text(WRAP_HTML.format(w=w, h=h, src=frame_src(check.name, theme), delay=int(delay_ms)))
            url = wrap.as_uri()
            _chrome(chrome, w, h, f"--screenshot={out_dir / png_name(key, theme)}", url)
            dumped = _chrome(chrome, w, h, "--dump-dom", url)
            try:
                reports[key] = parse_report(dumped.stdout)
            except ValueError as e:
                raise ValueError(f"{key}: {e}") from None
        finally:
            if not keep:
                check.unlink(missing_ok=True)
                wrap.unlink(missing_ok=True)
    return reports


def failures(report: dict) -> list[str]:
    """The failed checks of one report (a missing min_font means no visible text: a failure).

    Also fails, at widths up to 430px, a visual or deck taller than 320px (spec 3.3); an expanded stack strip taller than 320px; a deck with fewer than 2 or more than 4 slides, a slide whose content overflows
    it, and a visible ``img.photo`` that has not loaded (``naturalWidth`` 0) after the delay."""
    bad = []
    if report.get("overflow"):
        bad.append("overflow")
    if report.get("min_font") is None or report["min_font"] < 11:
        bad.append("min_font")
    if report.get("empty_visual", 0) > 0:
        bad.append("empty_visual")
    if report.get("tallest_post", 0) > 1.4:
        bad.append("tallest_post")
    if report.get("viewport_w", 0) <= PHONE_MAX_W and report.get("tallest_visual", 0) > VISUAL_MAX_H:
        bad.append("tallest_visual")
    if any(not 2 <= n <= 4 for n in report.get("deck_slides", [])):
        bad.append("deck_slides")
    if report.get("viewport_w", 0) <= PHONE_MAX_W and report.get("tallest_stack", 0) > VISUAL_MAX_H:
        bad.append("tallest_stack")
    if report.get("slide_overflow", 0) > 0:
        bad.append("slide_overflow")
    if report.get("broken_photo", 0) > 0:
        bad.append("broken_photo")
    return bad


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="scripts/shot.py", description="Screenshot an edition page and check its layout.")
    p.add_argument("page")
    p.add_argument("out_dir")
    p.add_argument("--keep", action="store_true", help="keep the _check-/_wrap- helper files")
    p.add_argument("--theme", choices=("dark", "light"), default=None,
                   help="force the night or day palette with ?theme=")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    try:
        args = parse_args(argv)
    except SystemExit:
        return 2
    chrome = chrome_path()
    if chrome is None:
        print(f"Chrome not found: set $CHROME or install {MAC_CHROME}", file=sys.stderr)
        return 2
    reports = shoot(Path(args.page), Path(args.out_dir), chrome=chrome, keep=args.keep, theme=args.theme)
    failed = False
    for key, r in reports.items():
        bad = failures(r)
        failed = failed or bool(bad)
        print(f"{key}: ground={r.get('ground')} overflow={r['overflow']} min_font={r['min_font']} empty_visual={r['empty_visual']} "
              f"tallest_post={r['tallest_post']} posts={r['posts']} decks={r.get('deck_slides')} "
              f"tallest_visual={r.get('tallest_visual')} slide_overflow={r.get('slide_overflow')} stacks={r.get('stacks')} tallest_stack={r.get('tallest_stack')} broken_photo={r.get('broken_photo')}" + (f"  FAIL: {', '.join(bad)}" if bad else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
