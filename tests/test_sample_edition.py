import importlib.util
from pathlib import Path

from newshouse.catalogue import VISUALS
from newshouse.render_static import edition_view
from newshouse.validate import Banned, card_problems, cited_items
from newshouse.models import ClusterItem
from sqlalchemy import select

_path = Path(__file__).resolve().parent.parent / "scripts" / "sample_edition.py"
_spec = importlib.util.spec_from_file_location("sample_edition", _path)
sample = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sample)


def test_sample_edition_renders_every_kind(tmp_path, capsys):
    assert sample.main(["--out", str(tmp_path)]) == 0
    printed = capsys.readouterr().out.strip()
    page = Path(printed)
    assert page.exists() and page.parent == tmp_path
    html = page.read_text()
    for kind in VISUALS:
        if kind != "none":  # a post with no visual has no panel to find
            assert f'data-kind="{kind}"' in html, kind
    assert html.split("<body", 1)[1].count('data-fill="hi"') == 2  # the writers' highlighted slides
    assert html.count('<div class="deck">') == 5
    posts = [p for p in html.split("<article")[1:] if '<div class="deck">' in p]
    assert sorted(p.count('<section class="slide"') for p in posts) == [2, 2, 3, 4, 4]
    assert "https://invalid.example/missing.jpg" in html
    assert html.count('class="stack-chip"') == 1 and "+3 more on this story" in html
    assert "#A50044" in html  # the Barcelona kit colour reached the pitch post


def test_sample_cards_pass_the_truth_checks(session):
    ed = sample.seed(session)
    view = edition_view(session, ed)
    assert len(view["cards"]) == 43
    four = [c for c in view["cards"] if len(c["slides"]) == 4]
    assert ["cover", "table", "text", "what-next"] in [[s["kind"] for s in c["slides"]] for c in four]
    for card in view["cards"]:
        in_cluster = set(session.scalars(select(ClusterItem.item_id)
                                         .where(ClusterItem.cluster_id == card["cluster_id"])))
        problems = card_problems(card, profile=set(), banned=Banned(), previous_headline=None,
                                 cluster_item_ids=in_cluster, items=cited_items(session, card))
        hard = [p for p in problems if p.rule in ("payload", "slides", "citation")]
        assert hard == [], (card["id"], hard)


def test_a_failed_photo_hides_its_credit(tmp_path, capsys):
    sample.main(["--out", str(tmp_path)])
    html = Path(capsys.readouterr().out.strip()).read_text()
    assert ".photo[hidden] + .credit { display: none; }" in html


def test_sample_pitch_is_the_worst_case(session):
    ed = sample.seed(session)
    pitch = [c for c in edition_view(session, ed)["cards"] if c["visual"] == "pitch"][0]
    assert len(pitch["payload"]["rows"]) == 4 and len(pitch["payload"]["out"]) == 3
