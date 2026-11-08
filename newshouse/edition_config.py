"""Edition configuration: per-topic floors and caps, card limits, colours.

Read from the committed ``config/edition.yaml`` (no secrets).
"""
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from newshouse.config import Settings


class TopicRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min: int = 0
    max: int = 4

    @model_validator(mode="after")
    def _min_not_above_max(self) -> "TopicRule":
        if self.min > self.max:
            raise ValueError(f"topic rule min {self.min} is above max {self.max}")
        return self


HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
# the colour families in newshouse/present.py (FAMILIES); test_present checks they agree
FAMILY_NAMES = ("world", "ai", "business", "sport", "city", "screen")


class TeamColours(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary: str
    secondary: str

    @field_validator("primary", "secondary")
    @classmethod
    def _hex(cls, v: str) -> str:
        if not HEX.match(v):
            raise ValueError(f"team colour {v!r} is not a #RRGGBB hex colour")
        return v


class EditionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    budget_seconds: int = 900
    cards_floor: int = 8
    cards_cap: int = 25
    top_n: int = 10
    also_max: int = 25
    also_per_topic: int = 2
    topics: dict[str, TopicRule] = {}
    topic_default: TopicRule = TopicRule()
    colours_topic: dict[str, str] = {}
    teams: dict[str, TeamColours] = {}
    live: dict = {}

    @field_validator("colours_topic")
    @classmethod
    def _families(cls, v: dict[str, str]) -> dict[str, str]:
        bad = sorted(f"{t}: {f}" for t, f in v.items() if f not in FAMILY_NAMES)
        if bad:
            raise ValueError(f"unknown colour family ({', '.join(bad)}); "
                             f"known: {', '.join(FAMILY_NAMES)}")
        return v


_TOP_KEYS = {"budget_seconds", "top_n", "live", "cards", "also", "topics", "colours"}
_CARDS_KEYS = {"floor", "cap"}
_ALSO_KEYS = {"max", "per_topic"}
_COLOURS_KEYS = {"topic", "teams"}


def _check_keys(where: str, given, allowed: set[str]) -> None:
    unknown = sorted(str(k) for k in (given or {}) if k not in allowed)
    if unknown:
        raise ValueError(f"unknown key{'s' if len(unknown) > 1 else ''} in edition config "
                         f"{where}: {', '.join(unknown)}")


def _reshape(raw: dict) -> dict:
    """Map the YAML layout onto the flat EditionConfig field names; unknown keys raise."""
    _check_keys("(top level)", raw, _TOP_KEYS)
    _check_keys("cards", raw.get("cards"), _CARDS_KEYS)
    _check_keys("also", raw.get("also"), _ALSO_KEYS)
    _check_keys("colours", raw.get("colours"), _COLOURS_KEYS)
    data = {k: v for k, v in raw.items() if k in ("budget_seconds", "top_n", "live")}
    cards = raw.get("cards") or {}
    if "floor" in cards:
        data["cards_floor"] = cards["floor"]
    if "cap" in cards:
        data["cards_cap"] = cards["cap"]
    also = raw.get("also") or {}
    if "max" in also:
        data["also_max"] = also["max"]
    if "per_topic" in also:
        data["also_per_topic"] = also["per_topic"]
    topics = dict(raw.get("topics") or {})
    if "default" in topics:
        data["topic_default"] = topics.pop("default")
    data["topics"] = topics
    colours = raw.get("colours") or {}
    if "topic" in colours:
        data["colours_topic"] = colours["topic"]
    if "teams" in colours:
        data["teams"] = colours["teams"]
    return data


def load_edition_config(path: Path | None = None) -> EditionConfig:
    """Load the edition config; a missing file gives the defaults."""
    path = path if path is not None else Settings().edition_config_path
    if not path.exists():
        return EditionConfig()
    raw = yaml.safe_load(path.read_text()) or {}
    return EditionConfig(**_reshape(raw))


def rule_for(cfg: EditionConfig, topic: str | None) -> TopicRule:
    """The floor/cap rule for a topic, or the default for unknown/None."""
    if topic is None:
        return cfg.topic_default
    return cfg.topics.get(topic, cfg.topic_default)
