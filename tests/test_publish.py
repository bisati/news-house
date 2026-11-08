import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from newshouse.publish import publish

NOW = datetime(2026, 11, 3, 1, 5, tzinfo=timezone.utc)  # 06:35 IST


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A temp main repo (with site/ bundle and source), a temp bare remote and an out dir.
    Git never reads the real global or system config here."""
    empty = tmp_path / "gitconfig"
    empty.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(k, raising=False)

    repo = tmp_path / "repo"
    (repo / "newshouse").mkdir(parents=True)
    (repo / "newshouse" / "x.py").write_text("print(1)\n")
    (repo / "site" / "api" / "__pycache__").mkdir(parents=True)
    (repo / "site" / "vercel.json").write_text("{}\n")
    (repo / "site" / "requirements.txt").write_text("psycopg\n")
    (repo / "site" / "README.md").write_text("site\n")
    (repo / "site" / "api" / "feedback.py").write_text("# fn\n")
    (repo / "site" / "api" / "__pycache__" / "feedback.cpython-314.pyc").write_bytes(b"\0")
    git("init", "-q", "-b", "main", str(repo))
    git("config", "user.email", "test@example.invalid", cwd=repo)
    git("config", "user.name", "Test", cwd=repo)
    git("add", "newshouse", "site/vercel.json", "site/requirements.txt", "site/README.md",
        "site/api/feedback.py", cwd=repo)
    git("commit", "-q", "-m", "main", cwd=repo)
    (repo / "profile.md").write_text("secret profile")
    (repo / "newshouse.db").write_bytes(b"db")

    remote = tmp_path / "remote.git"
    git("init", "-q", "--bare", str(remote))

    out = tmp_path / "out"
    (out / "fonts").mkdir(parents=True)
    (out / "sample").mkdir()
    (out / "2026-11-03.html").write_text("<html>today</html>")
    (out / "2026-11-02.html").write_text("<html>yesterday</html>")
    (out / "latest.html").write_text("<html>today</html>")
    (out / "index.html").write_text("<html>archive</html>")
    (out / "_debug.html").write_text("<html>debug</html>")
    (out / "2026-11-03.json").write_text("{}")
    (out / "fonts" / "a.woff2").write_bytes(b"font")
    (out / "sample" / "s.html").write_text("sample")
    (out / "tick-debug.log").write_text("log")
    (out / "newshouse.db").write_bytes(b"db")
    (out / ".DS_Store").write_bytes(b"x")

    worktree = tmp_path / "cache" / "site"

    def run(now=NOW):
        return publish(out, repo=repo, remote=str(remote), branch="site", worktree=worktree,
                       now=now)
    return run, repo, remote, out, worktree


def remote_files(remote):
    return set(git("--git-dir", str(remote), "ls-tree", "-r", "--name-only", "site").splitlines())


def test_publish_creates_orphan_site_branch(world):
    run, repo, remote, out, worktree = world
    r = run()
    assert r["status"] == "pushed" and r["commit"]
    files = remote_files(remote)
    assert {"latest.html", "index.html", "2026-11-03.html", "2026-11-03.json",
            "fonts/a.woff2", "api/feedback.py", "vercel.json", "requirements.txt",
            "README.md"} <= files
    assert not any(f.startswith("newshouse/") for f in files)
    assert not files & {"profile.md", "newshouse.db", "tick-debug.log", ".DS_Store"}
    assert not any(f.startswith(("sample/", "site/")) or "__pycache__" in f for f in files)
    assert r["files"] == len(files)
    # orphan: one root commit, sharing no history with main
    assert git("--git-dir", str(remote), "rev-list", "--count", "site") == "1"
    assert git("--git-dir", str(remote), "log", "-1", "--format=%s", "site") == \
        "publish: 2026-11-03 06:35 IST"
    # the publish identity, not the repo's own user.email
    assert git("--git-dir", str(remote), "log", "-1", "--format=%an <%ae>", "site") == \
        "bisati <81610063+bisati@users.noreply.github.com>"
    assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo) == "main"
    assert git("status", "--porcelain", "--untracked-files=no", cwd=repo) == ""


def test_publish_skips_when_unchanged(world):
    run, repo, remote, out, worktree = world
    first = run()
    again = run()
    assert again == {"status": "unchanged", "commit": first["commit"], "files": first["files"]}
    assert git("--git-dir", str(remote), "rev-list", "--count", "site") == "1"


def test_publish_appends_a_commit_on_change(world):
    run, repo, remote, out, worktree = world
    first = run()
    (out / "latest.html").write_text("<html>new</html>")
    (out / "2026-11-02.html").unlink()
    second = run()
    assert second["status"] == "pushed" and second["commit"] != first["commit"]
    assert git("--git-dir", str(remote), "rev-parse", "site^") == first["commit"]
    assert "2026-11-02.html" not in remote_files(remote)


def test_publish_excludes_underscore_files(world):
    run, repo, remote, out, worktree = world
    run()
    assert not any(Path(f).name.startswith("_") for f in remote_files(remote))


def test_publish_recovers_when_worktree_deleted(world):
    import shutil
    run, repo, remote, out, worktree = world
    first = run()
    shutil.rmtree(worktree)
    assert run()["status"] == "unchanged"
    (out / "latest.html").write_text("<html>newer</html>")
    shutil.rmtree(worktree)
    r = run()
    assert r["status"] == "pushed"
    assert git("--git-dir", str(remote), "rev-parse", "site^") == first["commit"]


def test_publish_retries_a_failed_push(world, tmp_path):
    run, repo, remote, out, worktree = world
    moved = tmp_path / "away.git"
    remote.rename(moved)
    assert run()["status"] == "error"
    moved.rename(remote)
    r = run()
    assert r["status"] == "pushed"
    assert git("--git-dir", str(remote), "rev-parse", "site") == r["commit"]


def test_publish_refuses_to_clear_a_foreign_directory(world):
    run, repo, remote, out, worktree = world
    worktree.mkdir(parents=True)
    (worktree / "keep.txt").write_text("mine")
    r = run()
    assert r["status"] == "error"
    assert (worktree / "keep.txt").read_text() == "mine"


def test_cli_publish_requires_remote(monkeypatch, capsys):
    from newshouse.cli import main
    from newshouse.config import Settings
    monkeypatch.setattr("newshouse.cli.get_settings", lambda: Settings(publish_remote=None))
    monkeypatch.setattr("newshouse.publish.publish", lambda *a, **k: pytest.fail("called"))
    assert main(["publish"]) == 2
    assert "PUBLISH_REMOTE" in capsys.readouterr().err


def test_publish_ships_tracked_site_files_only(world):
    run, repo, remote, out, worktree = world
    (repo / "site" / "secret.env").write_text("NEON_DATABASE_URL=postgres://x")
    (repo / "site" / "api" / "neon.env").write_text("x")
    run()
    files = remote_files(remote)
    assert "secret.env" not in files and "api/neon.env" not in files
    assert {"vercel.json", "api/feedback.py"} <= files


def test_publish_skips_symlinks(world):
    run, repo, remote, out, worktree = world
    (out / "leak.html").symlink_to(repo / "profile.md")
    (out / "leak.json").symlink_to(repo / "profile.md")
    (out / "fonts" / "leak.woff2").symlink_to(repo / "profile.md")
    (repo / "site" / "leak.txt").symlink_to(repo / "profile.md")
    git("add", "site/leak.txt", cwd=repo)
    git("commit", "-q", "-m", "tracked symlink", cwd=repo)
    run()
    files = remote_files(remote)
    assert not files & {"leak.html", "leak.json", "fonts/leak.woff2", "leak.txt"}
    assert "latest.html" in files


def test_publish_continues_a_remote_only_branch(world):
    import shutil
    run, repo, remote, out, worktree = world
    first = run()
    shutil.rmtree(worktree)
    git("worktree", "prune", cwd=repo)
    git("branch", "-D", "site", cwd=repo)
    git("update-ref", "-d", "refs/newshouse/pushed/site", cwd=repo)
    r = run()
    assert r == {"status": "unchanged", "commit": first["commit"], "files": first["files"]}
    assert git("--git-dir", str(remote), "rev-list", "--count", "site") == "1"


def test_git_has_timeouts_no_prompts_and_a_clean_env(world, monkeypatch):
    import newshouse.publish as pub
    run, repo, remote, out, worktree = world
    monkeypatch.setenv("GIT_DIR", str(repo / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(repo))
    seen = []
    real = subprocess.run

    def spy(argv, **kw):
        seen.append((argv[1], kw))
        if argv[1] == "push":
            raise subprocess.TimeoutExpired(argv, kw["timeout"])
        return real(argv, **kw)

    monkeypatch.setattr(pub.subprocess, "run", spy)
    r = run()
    assert r["status"] == "error" and r["error"] == "git push timed out"
    assert seen and all(kw.get("timeout") for _, kw in seen)
    assert {kw["timeout"] for sub, kw in seen if sub in ("ls-remote", "push")} == {120}
    assert {kw["timeout"] for sub, kw in seen if sub == "add"} == {60}
    for _, kw in seen:
        assert kw["env"]["GIT_TERMINAL_PROMPT"] == "0"
        assert not {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"} & set(kw["env"])
    assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo) == "main"


def test_publish_commit_uses_the_author_setting(world):
    run, repo, remote, out, worktree = world
    r = publish(out, repo=repo, remote=str(remote), branch="site", worktree=worktree, now=NOW,
                author_name="Pub Bot", author_email="pub@users.noreply.github.com")
    assert r["status"] == "pushed"
    assert git("--git-dir", str(remote), "log", "-1", "--format=%an|%ae|%cn|%ce", "site") == \
        "Pub Bot|pub@users.noreply.github.com|Pub Bot|pub@users.noreply.github.com"


def test_default_worktree_is_per_repo(tmp_path, monkeypatch):
    import hashlib
    from newshouse.publish import default_worktree
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    a, b = tmp_path / "clone-a", tmp_path / "clone-b"
    a.mkdir()
    b.mkdir()
    wa = default_worktree(a)
    assert wa == tmp_path / "home" / ".cache" / "news-house" / \
        f"site-{hashlib.sha1(str(a.resolve()).encode()).hexdigest()[:8]}"
    assert wa != default_worktree(b)
    assert default_worktree(a) == wa  # stable


def test_publish_without_worktree_uses_the_per_repo_default(world, tmp_path, monkeypatch):
    from newshouse.publish import default_worktree
    run, repo, remote, out, worktree = world
    monkeypatch.setenv("HOME", str(tmp_path / "home"))  # never the real ~/.cache
    r = publish(out, repo=repo, remote=str(remote), branch="site", worktree=None, now=NOW)
    assert r["status"] == "pushed"
    assert (default_worktree(repo) / "latest.html").exists()


def test_second_clone_cannot_hijack_the_first_clones_worktree(world, tmp_path, monkeypatch):
    run, repo, remote, out, worktree = world
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    other = tmp_path / "other"
    git("clone", "-q", str(repo), str(other))
    assert publish(out, repo=repo, remote=str(remote), branch="site", worktree=None,
                   now=NOW)["status"] == "pushed"
    r = publish(out, repo=other, remote=str(remote), branch="site", worktree=None, now=NOW)
    assert r["status"] in ("pushed", "unchanged")
    # the first clone's worktree still belongs to the first clone
    from newshouse.publish import default_worktree
    common = git("rev-parse", "--path-format=absolute", "--git-common-dir",
                 cwd=default_worktree(repo))
    assert Path(common).resolve() == (repo / ".git").resolve()


def test_publish_keeps_the_site_bundles_vercel_json(world):
    run, repo, remote, out, worktree = world
    (repo / "vercel.json").write_text('{"root": true}\n')
    git("add", "vercel.json", cwd=repo)
    git("commit", "-q", "-m", "root vercel.json", cwd=repo)
    (out / "vercel.json").write_text('{"out": true}\n')
    run()
    assert git("--git-dir", str(remote), "show", "site:vercel.json") == "{}"


def test_publish_refuses_an_out_dir_with_nothing_rendered(world):
    run, repo, remote, out, worktree = world
    (out / "latest.html").unlink()
    r = run()
    assert r["status"] == "error" and "latest.html" in r["error"]
    assert git("--git-dir", str(remote), "branch", "--list") == ""
