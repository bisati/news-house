from pathlib import Path
import pytest
from newshouse.edition_config import EditionConfig, load_edition_config, rule_for

def test_loads_committed_file():
    cfg = load_edition_config(Path("config/edition.yaml"))
    assert cfg.budget_seconds == 1200 and cfg.cards_floor == 8 and cfg.cards_cap == 36
    assert cfg.top_n == 10
    assert cfg.topics["ai-models"].min == 1 and cfg.topics["ai-models"].max == 4
    assert cfg.topics["gurgaon-local"].min == 0 and cfg.topics["gurgaon-local"].max == 2
    assert (cfg.topics["product-design"].min, cfg.topics["product-design"].max) == (2, 4)
    assert (cfg.topics["startups"].min, cfg.topics["startups"].max) == (1, 4)
    assert (cfg.topics["ai-tools"].min, cfg.topics["ai-tools"].max) == (1, 4)
    assert (cfg.topics["edtech-competitors"].min, cfg.topics["edtech-competitors"].max) == (1, 3)
    assert cfg.colours_topic["startups"] == "business" and cfg.colours_topic["ai-tools"] == "ai"
    assert cfg.colours_topic["gurgaon-local"] == "city"
    assert cfg.teams["barcelona"].primary == "#A50044"

def test_missing_file_gives_defaults(tmp_path):
    cfg = load_edition_config(tmp_path / "nope.yaml")
    assert cfg == EditionConfig()

def test_rule_for_unknown_topic_is_default():
    cfg = EditionConfig(topic_default={"min": 0, "max": 2})
    assert rule_for(cfg, "zzz").max == 2 and rule_for(cfg, None).max == 2

def test_min_above_max_rejected(tmp_path):
    p = tmp_path / "e.yaml"
    p.write_text("topics:\n  football: {min: 5, max: 2}\n")
    with pytest.raises(ValueError):
        load_edition_config(p)


@pytest.mark.parametrize("text, key", [
    ("top-n: 10\n", "top-n"),
    ("cards: {flor: 8}\n", "flor"),
    ("colours: {topics: {movies: tomato}}\n", "topics"),
])
def test_unknown_keys_rejected(tmp_path, text, key):
    p = tmp_path / "e.yaml"
    p.write_text(text)
    with pytest.raises(ValueError, match=key):
        load_edition_config(p)


def test_unknown_field_on_model_rejected():
    with pytest.raises(ValueError):
        EditionConfig(top_nn=3)


def test_live_kept_as_dict(tmp_path):
    p = tmp_path / "e.yaml"
    p.write_text("live:\n  aqi: {provider: open-meteo}\n")
    assert load_edition_config(p).live == {"aqi": {"provider": "open-meteo"}}


def test_also_config_keys(tmp_path):
    p = tmp_path / "e.yaml"
    p.write_text("also: {max: 10, per_topic: 1}\n")
    cfg = load_edition_config(p)
    assert cfg.also_max == 10 and cfg.also_per_topic == 1
    assert EditionConfig().also_max == 25 and EditionConfig().also_per_topic == 2
    assert load_edition_config(Path("config/edition.yaml")).also_per_topic == 2
    p.write_text("also: {max: 10, per_topics: 1}\n")
    with pytest.raises(ValueError, match="per_topics"):
        load_edition_config(p)


def test_colour_values_are_checked():
    import pytest
    from newshouse.edition_config import EditionConfig
    with pytest.raises(ValueError, match="unknown colour family"):
        EditionConfig(colours_topic={"gurgaon-local": "sky"})
    with pytest.raises(ValueError, match="hex"):
        EditionConfig(teams={"barcelona": {"primary": "#fff", "secondary": "#004D98"}})
