"""Resolve a repo argument (local path or remote URL) to a local git directory."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# scp-style remotes (git@host:owner/repo.git) have no scheme, so match them separately.
_URL_RE = re.compile(r"^(https?|ssh|git|file)://|^[\w.-]+@[\w.-]+:")


class GitError(RuntimeError):
    """A git command failed or the target is not a usable repository."""


@dataclass(frozen=True)
class RepoSource:
    """A repository that git commands can run against.

    Attributes:
        git_dir: Path passed to ``git -C``.
        name: Short display name for reports and file names.
        origin: The original argument (path or URL) for display.
    """

    git_dir: Path
    name: str
    origin: str


def run_git(args: list[str], cwd: Path | None = None) -> str:
    """Run a git command and return stdout.

    Args:
        args: Arguments after ``git``.
        cwd: Directory passed as ``-C``. None runs in the current directory.

    Returns:
        Decoded stdout.

    Raises:
        GitError: If git is missing or exits non-zero.
    """
    cmd = ["git"]
    if cwd is not None:
        cmd += ["-C", str(cwd)]
    # quotepath=off keeps non-ASCII file names readable instead of octal-escaped.
    cmd += ["-c", "core.quotepath=off", *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, check=False)
    except FileNotFoundError as exc:
        raise GitError("git executable not found on PATH") from exc
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise GitError(f"git {' '.join(args[:2])} failed: {err}")
    return proc.stdout.decode("utf-8", errors="replace")


def is_url(target: str) -> bool:
    """Return True if the target looks like a remote URL rather than a path."""
    return bool(_URL_RE.match(target))


def cache_root() -> Path:
    """Return the directory where remote clones are cached."""
    base = os.environ.get("LOCALAPPDATA") if sys.platform == "win32" else None
    root = Path(base) if base else Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return root / "gitstat" / "repos"


def _name_from_url(url: str) -> str:
    tail = url.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    return tail.removesuffix(".git") or "repo"


def resolve(target: str, refresh: bool = True) -> RepoSource:
    """Turn a path or URL into a RepoSource.

    URLs are mirror-cloned into a cache dir so the user's working trees are never touched.
    A full mirror is used (not a blob-filtered partial clone) because ``--numstat`` needs
    file contents, and a partial clone would fetch every blob one request at a time.

    Args:
        target: Local path or remote URL.
        refresh: For URLs, fetch updates when a cached clone already exists.

    Returns:
        The resolved repository.

    Raises:
        GitError: If the path is not a git repo or the clone/fetch fails.
    """
    if is_url(target):
        name = _name_from_url(target)
        digest = hashlib.sha1(target.encode()).hexdigest()[:10]
        dest = cache_root() / f"{name}-{digest}"
        if dest.exists():
            if refresh:
                print(f"Updating cached clone {dest} ...", file=sys.stderr)
                run_git(["remote", "update", "--prune"], cwd=dest)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            print(f"Cloning {target} into {dest} ...", file=sys.stderr)
            run_git(["clone", "--mirror", "--quiet", target, str(dest)])
        return RepoSource(git_dir=dest, name=name, origin=target)

    path = Path(target).expanduser().resolve()
    if not path.exists():
        raise GitError(f"path does not exist: {path}")
    try:
        run_git(["rev-parse", "--git-dir"], cwd=path)
    except GitError as exc:
        raise GitError(f"not a git repository: {path}") from exc
    try:
        top = run_git(["rev-parse", "--show-toplevel"], cwd=path).strip()
    except GitError:
        top = ""  # bare repos have no work tree
    top_path = Path(top) if top else path
    return RepoSource(git_dir=path, name=top_path.name, origin=str(path))


def configured_email(repo: RepoSource) -> str | None:
    """Return ``user.email`` as git sees it for this repo (repo config, then global)."""
    try:
        email = run_git(["config", "user.email"], cwd=repo.git_dir).strip()
    except GitError:
        return None
    return email or None
