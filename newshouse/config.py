"""Settings for News House.

Loads every ``~/.config/news-house/*.env`` file (sorted), then the process
environment overrides. Variable names are the upper-cased field names.
"""
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

CONFIG_DIR = Path("~/.config/news-house").expanduser()


def _env_files() -> list[Path]:
    if not CONFIG_DIR.is_dir():
        return []
    return sorted(CONFIG_DIR.glob("*.env"))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_env_files() or None, extra="ignore", env_ignore_empty=True
    )

    database_url: str = "sqlite:///./newshouse.db"
    profile_id: str = "mihir"
    profile_path: Path = Path("profile.md")
    sources_path: Path = Path("sources/sources.yaml")
    edition_config_path: Path = Path("config/edition.yaml")
    lessons_path: Path = Path("ledger/lessons.json")
    claude_bin: str = "claude"
    claude_cwd: Path = Path("~/.cache/news-house/claude-cwd").expanduser()
    llm_backend: Literal["claude-code", "api", "fake"] = "claude-code"
    tz: str = "Asia/Kolkata"
    noise_floor: int = 30
    breaking_threshold: int = 90
    breaking_daily_cap: int = 3
    classify_batch: int = 50
    cluster_window_hours: int = 48
    stale_hours: int = 72
    neon_database_url: str | None = None
    publish_remote: str | None = None  # a remote name or URL; unset means never publish
    publish_branch: str = "site"
    publish_worktree: Path | None = None  # unset: ~/.cache/news-house/site-<repo hash>
    publish_author_name: str = "bisati"
    publish_author_email: str = "81610063+bisati@users.noreply.github.com"  # Vercel accepts it
    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    reddit_username: str | None = None
    reddit_password: str | None = None
    reddit_refresh_token: str | None = None
    reddit_user_agent: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
