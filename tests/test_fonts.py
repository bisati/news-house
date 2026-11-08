from pathlib import Path
from importlib import resources
import importlib.util

FONTS = resources.files("newshouse").joinpath("static/fonts")


def test_parse_font_faces_reads_google_css():
    spec = importlib.util.spec_from_file_location("ff", Path("scripts/fetch_fonts.py"))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    css = "/* latin */\n@font-face {\n  font-family: 'DM Sans';\n  font-style: normal;\n  font-weight: 400 700;\n  src: url(https://fonts.gstatic.com/s/x.woff2) format('woff2');\n  unicode-range: U+0000-00FF;\n}\n"
    faces = mod.parse_font_faces(css)
    assert faces == [{"family": "DM Sans", "style": "normal", "weight": "400 700",
                      "url": "https://fonts.gstatic.com/s/x.woff2", "unicode_range": "U+0000-00FF"}]


def test_font_files_are_committed():
    for name in ("fraunces-latin.woff2", "fraunces-italic-latin.woff2", "dmsans-latin.woff2"):
        assert FONTS.joinpath(name).stat().st_size > 10_000
    css = resources.files("newshouse").joinpath("static/fonts.css").read_text()
    assert "font-family: 'Fraunces'" in css and "font-family: 'DM Sans'" in css
    assert "gstatic" not in css
    for name in ("OFL-Fraunces.txt", "OFL-DMSans.txt"):
        head = FONTS.joinpath(name).read_text()[:400]
        assert "Copyright" in head and "<Copyright Holder>" not in head
