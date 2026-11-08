from importlib import resources


def _p(name):
    return resources.files("newshouse.llm").joinpath(f"prompts/{name}").read_text()


def test_classify_prompt_carries_the_three_tests():
    t = _p("classify.system.md")
    assert "annoyed tomorrow" in t and "well-informed person in India" in t
    assert "what they pay, earn, save or decide" in t


def test_write_prompt_why_rule_and_headline_target():
    t = _p("write.system.md")
    assert "this week or this month" in t
    assert "12 words" in t and "90 characters" in t


def test_classify_prompt_defines_tone():
    t = _p("classify.system.md")
    assert "`tone`" in t
    assert all(v in t for v in ("good", "bad", "mixed", "neutral"))


def test_write_prompt_teaches_catalogue():
    from newshouse.catalogue import SLIDE_KINDS, VISUALS
    t = _p("write.system.md")
    assert all(f"`{v}`" in t for v in VISUALS)
    assert all(f"`{k}`" in t for k in SLIDE_KINDS)
    assert "35 words" in t and "Allowed visuals" in t and "`tone`" in t


def test_classify_prompt_lists_new_topics_and_grap_breaking_case():
    t = _p("classify.system.md")
    assert "startups" in t and "ai-tools" in t
    assert "A Gurgaon GRAP stage change or a major closure affecting the same day (not a new AQI reading)." in t


def test_write_prompt_gives_photos_their_story_shapes():
    t = _p("write.system.md")
    for row in ("| about a person otherwise: a death, an appointment or exit, a completed signing, a profile | `photo` |",
                "| a disaster, accident, attack or crash | `photo` |",
                "| another event: a ceremony, protest, rally or summit | `photo` |",
                "| a footballer's injury, suspension, doubt or return | `availability` |",
                "| a football match result | `scoreline` |"):
        assert row in t
    assert "For a launch, a rule or a number, use its fact format, not a photo." in t


def test_write_prompt_limits_match_the_validator():
    """The prompt states the same limits catalogue.py checks (a mismatch costs posts their visual)."""
    t = _p("write.system.md")
    assert "2 or 3 rows" in t and "`change` at most 32" in t and "`has` 1 to 3 things" in t
    assert "2 to 4 rows" not in t and "`has` 1 to 4" not in t


def test_write_prompt_states_story_format_limits():
    t = _p("write.system.md")
    for frag in ("`from` (the buyer, or the investors for funding) at most 28", "`to_does` (what the target does) at most 48",
                 "up to 3 fixtures, each `vs` at most 18 and `date` at most 8", "each `then` at most 36",
                 "Teams at most 20 characters", "name at most 18", "3 or 4 steps of at most 16 characters",
                 "`key-facts` holds at most 3 facts", "at most 2 ticks and 1 cross", "`to_does` at most 32 characters",
                 "exactly 3 steps of at most 60 characters", "up to 3 `affects` of at most 28"):
        assert frag in t, frag
    t_rows = t.index("| `availability` |"), t.index("| about a person otherwise")
    assert t_rows[0] < t_rows[1]  # the new formats come before the photo rows
