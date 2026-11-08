def test_defaults_match_spec(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from newshouse.config import Settings
    s = Settings(_env_file=None)
    # the reading budget lives only in config/edition.yaml (no second default to drift)
    assert not hasattr(s, "budget_seconds")
    assert (s.noise_floor, s.breaking_threshold, s.breaking_daily_cap) == (30, 90, 3)
    assert s.classify_batch == 50 and s.cluster_window_hours == 48 and s.stale_hours == 72
    assert s.profile_id == "mihir"


def test_blank_env_template_uses_defaults(tmp_path, monkeypatch):
    from pathlib import Path
    from newshouse.config import Settings
    root = Path(__file__).resolve().parent.parent
    lines = [l for l in (root / ".env.example").read_text().splitlines() if l.strip()]
    lines = [l for l in lines if not l.startswith("BREAKING_DAILY_CAP=")] + ["BREAKING_DAILY_CAP=12"]
    env = tmp_path / "x.env"
    env.write_text("\n".join(lines) + "\n")
    for l in lines:
        monkeypatch.delenv(l.split("=")[0], raising=False)
    s = Settings(_env_file=env)
    assert s.breaking_daily_cap == 12
    assert s.database_url == "sqlite:///./newshouse.db"
    assert s.llm_backend == "claude-code" and s.profile_id == "mihir"


def test_publish_defaults(monkeypatch):
    for k in ("PUBLISH_WORKTREE", "PUBLISH_AUTHOR_NAME", "PUBLISH_AUTHOR_EMAIL"):
        monkeypatch.delenv(k, raising=False)
    from newshouse.config import Settings
    s = Settings(_env_file=None)
    assert s.publish_worktree is None  # per-repo default, see newshouse.publish.default_worktree
    assert s.publish_author_name == "bisati"
    assert s.publish_author_email == "81610063+bisati@users.noreply.github.com"
    from newshouse.publish import AUTHOR_EMAIL, AUTHOR_NAME
    assert (AUTHOR_NAME, AUTHOR_EMAIL) == (s.publish_author_name, s.publish_author_email)


def test_install_launchd_sets_the_publish_identity():
    from pathlib import Path
    sh = (Path(__file__).resolve().parent.parent / "scripts" / "install_launchd.sh").read_text()
    assert 'git -C "$PROD" config user.name bisati' in sh
    assert 'git -C "$PROD" config user.email 81610063+bisati@users.noreply.github.com' in sh
