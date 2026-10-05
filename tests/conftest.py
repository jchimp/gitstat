"""Shared fixtures: a throwaway git repo with commits at fixed times."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                   env={**os.environ, **(env or {})})


def commit(repo: Path, when: str, files: dict[str, str], msg: str,
           email: str = "me@example.com", name: str = "Me") -> None:
    """Write files and commit them with a fixed author/committer date."""
    for rel, content in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    env = {"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when,
           "GIT_AUTHOR_EMAIL": email, "GIT_AUTHOR_NAME": name,
           "GIT_COMMITTER_EMAIL": email, "GIT_COMMITTER_NAME": name}
    _git(repo, "commit", "-q", "-m", msg, env=env)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Repo with 4 commits by me in 3 sessions, plus 1 commit by someone else.

    Expected with defaults (120 min gap, 120 min lead), for me only:
      session 1: 2026-01-04 09:00 -> 10:30 = 1.5 h + 2 h = 3.5 h
      session 2: 2026-01-05 14:00 alone    = 2 h
      session 3: 2026-03-02 08:00 rename   = 2 h
    February has no commits and must still appear as an empty month.
    """
    r = tmp_path / "proj"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "me@example.com")
    _git(r, "config", "user.name", "Me")
    commit(r, "2026-01-04T09:00:00-06:00", {"src/app.py": "a\nb\nc\n"}, "feat: start app")
    commit(r, "2026-01-04T10:30:00-06:00", {"src/app.py": "a\nB\nc\nd\n"}, "Tweak app")
    commit(r, "2026-01-05T14:00:00-06:00", {"README.md": "hi\n"}, "Add readme")
    _git(r, "tag", "v0.1")
    commit(r, "2026-03-01T12:00:00+00:00", {"other.txt": "x\n"}, "Their work",
           email="them@example.com", name="Them")
    _git(r, "mv", "src/app.py", "src/main.py")
    commit(r, "2026-03-02T08:00:00-06:00", {}, "Rename app")
    return r
