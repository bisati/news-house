"""Fetch Fraunces and DM Sans (latin subset, variable woff2) once and self-host them.

Run: .venv/bin/python scripts/fetch_fonts.py
Writes newshouse/static/fonts/*.woff2 and newshouse/static/fonts.css.
"""
import re
import sys
from pathlib import Path

import httpx

CSS_URL = (
    "https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400..700;1,9..144,400..700"
    "&family=DM+Sans:opsz,wght@9..40,400..700&display=swap"
)
CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
FILENAMES = {
    ("Fraunces", "normal"): "fraunces-latin.woff2",
    ("Fraunces", "italic"): "fraunces-italic-latin.woff2",
    ("DM Sans", "normal"): "dmsans-latin.woff2",
}
OFL_URLS = {
    "OFL-Fraunces.txt": "https://raw.githubusercontent.com/google/fonts/main/ofl/fraunces/OFL.txt",
    "OFL-DMSans.txt": "https://raw.githubusercontent.com/google/fonts/main/ofl/dmsans/OFL.txt",
}

_BLOCK = re.compile(r"(?:/\*\s*([\w-]+)\s*\*/\s*)?@font-face\s*\{([^}]*)\}", re.S)


def _prop(body: str, name: str) -> str:
    m = re.search(rf"{name}\s*:\s*([^;]+);", body)
    return m.group(1).strip() if m else ""


def _parse(css: str) -> list[dict]:
    out = []
    for m in _BLOCK.finditer(css):
        subset, body = m.group(1) or "", m.group(2)
        url = re.search(r"url\(\s*['\"]?([^'\")\s]+)['\"]?\s*\)", _prop(body, "src"))
        out.append({
            "subset": subset,
            "family": _prop(body, "font-family").strip("'\""),
            "style": _prop(body, "font-style"),
            "weight": _prop(body, "font-weight"),
            "url": url.group(1) if url else "",
            "unicode_range": _prop(body, "unicode-range"),
        })
    return out


def parse_font_faces(css: str) -> list[dict]:
    return [{k: v for k, v in f.items() if k != "subset"} for f in _parse(css)]


def fetch(out_dir: Path) -> list[Path]:
    out_dir = Path(out_dir)
    fonts_dir = out_dir / "fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)
    with httpx.Client(headers={"User-Agent": CHROME_UA}, timeout=30, follow_redirects=True) as client:
        r = client.get(CSS_URL)
        r.raise_for_status()
        wanted = {}
        for f in _parse(r.text):
            key = (f["family"], f["style"])
            if f["subset"] == "latin" and key in FILENAMES:
                wanted[key] = f
        missing = set(FILENAMES) - set(wanted)
        if missing:
            raise RuntimeError(f"latin subset not found for {sorted(missing)}")
        paths, rules = [], []
        for key, name in FILENAMES.items():
            f = wanted[key]
            resp = client.get(f["url"])
            resp.raise_for_status()
            path = fonts_dir / name
            path.write_bytes(resp.content)
            paths.append(path)
            rules.append(
                "@font-face {\n"
                f"  font-family: '{f['family']}';\n"
                f"  font-style: {f['style']};\n"
                "  font-weight: 400 700;\n"
                "  font-display: swap;\n"
                f"  src: url(fonts/{name}) format('woff2');\n"
                f"  unicode-range: {f['unicode_range']};\n"
                "}\n"
            )
        for name, url in OFL_URLS.items():
            lic = client.get(url)
            lic.raise_for_status()
            (fonts_dir / name).write_text(lic.text)
    css_path = out_dir / "fonts.css"
    css_path.write_text("\n".join(rules))
    return paths + [css_path]


if __name__ == "__main__":
    target = Path(__file__).resolve().parent.parent / "newshouse" / "static"
    for p in fetch(target):
        print(p, p.stat().st_size)
    sys.exit(0)
