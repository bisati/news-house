"""Publish the rendered pages and the Vercel site bundle to an orphan branch.

The branch (default ``site``) lives in a git worktree kept between runs (default
``~/.cache/news-house/site-<first 8 hex of sha1(repo root)>``, one per clone, so a second
clone can never take over or break another clone's worktree). Its contents are replaced on every run with exactly:
``out/*.html`` (except names starting with ``_``), ``out/*.json``, ``out/fonts/`` and the
repo's ``site/`` bundle at the branch root. Nothing else ever reaches the branch.

Git runs through ``subprocess`` with argument lists. Git's own output is never logged:
it can carry the remote URL and, with it, credentials.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
# Kept equal to the Settings defaults by tests/test_config.py.
AUTHOR_NAME = "bisati"
AUTHOR_EMAIL = "81610063+bisati@users.noreply.github.com"  # the no-reply address Vercel accepts
IST = ZoneInfo("Asia/Kolkata")
DATED = re.compile(r"^\d{4}-\d{2}-\d{2}\.html$")
MARKER = "refs/newshouse/pushed/"  # the last commit known to be on the remote


class PublishError(Exception):
    pass


def default_worktree(repo: Path) -> Path:
    """The per-clone worktree path: two clones never share one."""
    digest = hashlib.sha1(str(Path(repo).resolve()).encode()).hexdigest()[:8]
    return Path("~/.cache/news-house").expanduser() / f"site-{digest}"


NETWORK = ("ls-remote", "fetch", "push")
SCRUB = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
         "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE")


def _env() -> dict[str, str]:
    """The child env: never prompt (a scheduled run has no terminal), and never let an
    inherited GIT_DIR and friends point git at another repository."""
    env = {k: v for k, v in os.environ.items() if k not in SCRUB}
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _git(*args: str, cwd: Path, check: bool = True,
         config: tuple[str, ...] = ()) -> subprocess.CompletedProcess:
    timeout = 120 if args[0] in NETWORK else 60
    pre = [x for kv in config for x in ("-c", kv)]
    try:
        return subprocess.run(["git", *pre, *args], cwd=cwd, check=check, capture_output=True,
                              text=True, env=_env(), timeout=timeout)
    except subprocess.CalledProcessError as e:
        # name the subcommand only: argv and stderr can carry the remote URL
        raise PublishError(f"git {args[0]} failed ({e.returncode})") from None
    except subprocess.TimeoutExpired:
        raise PublishError(f"git {args[0]} timed out") from None


def _ref(repo: Path, ref: str) -> str | None:
    r = _git("rev-parse", "--verify", "--quiet", ref, cwd=repo, check=False)
    return (r.stdout.strip() or None) if r.returncode == 0 else None


def _ensure_worktree(repo: Path, remote: str, branch: str, worktree: Path) -> None:
    _git("worktree", "prune", cwd=repo)  # forget a worktree whose directory was deleted
    if (worktree / ".git").exists():
        top = _git("rev-parse", "--show-toplevel", cwd=worktree).stdout.strip()
        common = _git("rev-parse", "--path-format=absolute", "--git-common-dir",
                      cwd=worktree).stdout.strip()
        mine = _git("rev-parse", "--path-format=absolute", "--git-common-dir",
                    cwd=repo).stdout.strip()
        head = _git("symbolic-ref", "--short", "HEAD", cwd=worktree, check=False).stdout.strip()
        if Path(top).resolve() != worktree.resolve() or Path(common).resolve() != \
                Path(mine).resolve() or head != branch:
            raise PublishError(f"{worktree} is not this repo's {branch} worktree")
        return
    if worktree.exists() and any(worktree.iterdir()):
        raise PublishError(f"{worktree} exists and is not a git worktree; not touching it")
    worktree.parent.mkdir(parents=True, exist_ok=True)
    local = f"refs/heads/{branch}"
    if _ref(repo, local) is None:
        found = _git("ls-remote", "--heads", remote, local, cwd=repo).stdout.strip()
        if found:  # the branch lives on the remote only (a fresh clone): continue its history
            _git("fetch", "--quiet", remote, f"{local}:{local}", cwd=repo)
            _git("update-ref", MARKER + branch, local, cwd=repo)
    if _ref(repo, local) is not None:
        _git("worktree", "add", "--quiet", str(worktree), branch, cwd=repo)
        return
    # First publish: an orphan branch. `worktree add --orphan` needs git 2.42, so start
    # detached with nothing checked out, then switch to an unborn branch with an empty index.
    _git("worktree", "add", "--quiet", "--no-checkout", "--detach", str(worktree), cwd=repo)
    _git("checkout", "--quiet", "--orphan", branch, cwd=worktree)
    _git("read-tree", "--empty", cwd=worktree)


def _visible(p: Path) -> bool:
    return not p.name.startswith(".") and p.name != "__pycache__" and p.suffix != ".pyc"


def _copytree(src: Path, dst: Path) -> None:
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        if not all(_visible(Path(part)) for part in rel.parts) or p.is_symlink() \
                or not p.is_file():
            continue
        (dst / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, dst / rel)


def _copy_site(repo: Path, worktree: Path) -> None:
    """Copy the site/ bundle from tracked files only, so an untracked secret placed in
    site/ (say site/neon.env) can never be published."""
    listed = _git("ls-files", "-z", "--", "site", cwd=repo).stdout.split("\0")
    tracked = [Path(f) for f in listed if f]
    if not tracked:
        raise PublishError(f"no tracked site bundle in {repo / 'site'}")
    for rel in tracked:
        p = repo / rel
        inner = rel.relative_to("site")
        if not all(_visible(Path(part)) for part in inner.parts) or p.is_symlink() \
                or not p.is_file():
            continue
        (worktree / inner).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, worktree / inner)


def _fill(out_dir: Path, repo: Path, worktree: Path) -> None:
    for p in worktree.iterdir():
        if p.name == ".git":
            continue
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p)
        else:
            p.unlink()
    for p in sorted(out_dir.iterdir()):
        # vercel.json comes from the site bundle only, never from out/
        if p.is_file() and not p.is_symlink() and _visible(p) and not p.name.startswith("_") \
                and p.suffix in (".html", ".json") and p.name != "vercel.json":
            shutil.copyfile(p, worktree / p.name)
    fonts = out_dir / "fonts"
    if fonts.is_dir() and not fonts.is_symlink():
        _copytree(fonts, worktree / "fonts")
    _copy_site(repo, worktree)


def _edition_date(out_dir: Path, now: datetime) -> str:
    dated = sorted(p.stem for p in out_dir.iterdir() if DATED.match(p.name))
    return dated[-1] if dated else now.astimezone(IST).date().isoformat()


def publish(out_dir: Path, *, repo: Path, remote: str, branch: str, worktree: Path | None,
            now: datetime, author_name: str = AUTHOR_NAME,
            author_email: str = AUTHOR_EMAIL) -> dict:
    """Replace the branch's contents with the rendered pages and the site bundle, commit
    when anything changed (as ``author_name <author_email>``), and push. ``worktree`` None
    means :func:`default_worktree`. Returns ``{"status", "commit", "files"}``; status is
    "pushed", "unchanged" or "error" (then also "error": a short reason without URLs)."""
    out_dir, repo = Path(out_dir), Path(repo)
    worktree = default_worktree(repo) if worktree is None else Path(worktree).expanduser()
    files = 0
    try:
        if not (out_dir / "latest.html").is_file():  # never publish an empty site
            raise PublishError(f"nothing rendered: no latest.html in {out_dir}")
        _ensure_worktree(repo, remote, branch, worktree)
        _fill(out_dir, repo, worktree)
        _git("add", "--all", ".", cwd=worktree)
        files = len(_git("ls-files", cwd=worktree).stdout.splitlines())
        head = _ref(worktree, "HEAD")
        changed = (head is None) or (_git("diff", "--cached", "--quiet", cwd=worktree,
                                         check=False).returncode != 0)
        if changed:
            local = now.astimezone(IST)
            msg = f"publish: {_edition_date(out_dir, now)} {local:%H:%M} IST"
            _git("commit", "--quiet", "--no-verify", "-m", msg, cwd=worktree,
                 config=(f"user.name={author_name}", f"user.email={author_email}"))
            head = _ref(worktree, "HEAD")
        elif _ref(repo, MARKER + branch) == head:
            return {"status": "unchanged", "commit": head, "files": files}
        # changed, or an earlier push failed: push what the branch has
        _git("push", "--quiet", remote, f"refs/heads/{branch}:refs/heads/{branch}",
             cwd=worktree)
        _git("update-ref", MARKER + branch, head, cwd=repo)
        return {"status": "pushed", "commit": head, "files": files}
    except (PublishError, OSError) as e:
        reason = str(e) if isinstance(e, PublishError) else type(e).__name__
        log.warning("publish failed: %s", reason)
        return {"status": "error", "commit": None, "files": files, "error": reason}
