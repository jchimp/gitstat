"""Read commit history and per-file line counts from git in one ``git log`` pass."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from gitstat.source import RepoSource, run_git

_RS = "\x1e"  # starts each commit record
_FS = "\x1f"  # separates header fields
# %aN/%aE apply .mailmap so one person with several emails counts once.
_FORMAT = _RS + _FS.join(["%H", "%P", "%aN", "%aE", "%aI", "%D", "%s"])
_BRACE_RENAME = re.compile(r"\{([^{}]*) => ([^{}]*)\}")


@dataclass(frozen=True)
class FileChange:
    """Line counts for one file in one commit. Binary files have zero counts."""

    path: str
    added: int
    deleted: int
    binary: bool = False


@dataclass
class Commit:
    """One commit with its numstat file changes."""

    hash: str
    parents: list[str]
    author: str
    email: str
    date: datetime  # author date, in the author's own UTC offset
    refs: str
    subject: str
    files: list[FileChange] = field(default_factory=list)

    @property
    def added(self) -> int:
        return sum(f.added for f in self.files)

    @property
    def deleted(self) -> int:
        return sum(f.deleted for f in self.files)

    @property
    def churn(self) -> int:
        return self.added + self.deleted

    @property
    def is_merge(self) -> bool:
        return len(self.parents) > 1

    @property
    def tags(self) -> list[str]:
        return [r.strip()[5:] for r in self.refs.split(",") if r.strip().startswith("tag: ")]


def normalize_rename(path: str) -> str:
    """Return the new path from a numstat rename like ``a/{x => y}/f`` or ``old => new``."""
    if " => " not in path:
        return path
    if _BRACE_RENAME.search(path):
        new = _BRACE_RENAME.sub(lambda m: m.group(2), path)
        return re.sub(r"/{2,}", "/", new).strip("/")
    return path.split(" => ", 1)[1]


def parse_log(text: str) -> list[Commit]:
    """Parse output of ``git log --numstat`` using this module's format string.

    Args:
        text: Raw git output.

    Returns:
        Commits in the order git printed them.
    """
    commits: list[Commit] = []
    for record in text.split(_RS):
        if not record.strip():
            continue
        header, _, body = record.partition("\n")
        parts = header.split(_FS)
        if len(parts) != 7:
            continue  # defensive: a malformed record should not abort the whole report
        sha, parents, author, email, date, refs, subject = parts
        commit = Commit(
            hash=sha,
            parents=parents.split(),
            author=author,
            email=email,
            date=datetime.fromisoformat(date),
            refs=refs,
            subject=subject,
        )
        commit.files = list(_parse_numstat(body.splitlines()))
        commits.append(commit)
    return commits


def _parse_numstat(lines: Iterable[str]) -> Iterable[FileChange]:
    for line in lines:
        cols = line.split("\t", 2)
        if len(cols) != 3:
            continue
        added, deleted, path = cols
        path = normalize_rename(path)
        if added == "-" or deleted == "-":
            yield FileChange(path, 0, 0, binary=True)
        else:
            yield FileChange(path, int(added), int(deleted))


def collect(repo: RepoSource, since: str | None = None, until: str | None = None) -> list[Commit]:
    """Read all commits reachable from any ref, oldest first.

    All refs are read (not just HEAD) because work on unmerged branches is still work.
    Merge commits get no numstat by default, so their lines are not double counted.

    Args:
        repo: Repository to read.
        since: Optional git date expression for ``--since``.
        until: Optional git date expression for ``--until``.

    Returns:
        Commits sorted by author date ascending.
    """
    args = ["log", "--all", "--numstat", f"--format={_FORMAT}"]
    if since:
        args.append(f"--since={since}")
    if until:
        args.append(f"--until={until}")
    commits = parse_log(run_git(args, cwd=repo.git_dir))
    commits.sort(key=lambda c: c.date)
    return commits


def filter_authors(commits: list[Commit], patterns: list[str]) -> list[Commit]:
    """Keep commits whose author email or name contains any pattern (case-insensitive)."""
    needles = [p.casefold() for p in patterns]
    return [
        c for c in commits
        if any(n in c.email.casefold() or n in c.author.casefold() for n in needles)
    ]
