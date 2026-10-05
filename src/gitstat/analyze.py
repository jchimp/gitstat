"""Turn a list of commits into effort estimates and aggregate stats."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from gitstat.collect import Commit

_FEAT_RE = re.compile(r"^feat(\([^)]*\))?!?:", re.IGNORECASE)
_BIG_CHURN_FLOOR = 500  # below this a commit is never "major", even in a tiny repo


@dataclass
class Session:
    """A run of commits by one author with no gap longer than the session gap."""

    id: int
    email: str
    start: datetime
    end: datetime
    commits: list[Commit]
    hours: float


@dataclass
class Bucket:
    """Totals for one period (a day or a month)."""

    commits: int = 0
    added: int = 0
    deleted: int = 0
    hours: float = 0.0
    days: set[date] = field(default_factory=set)

    @property
    def churn(self) -> int:
        return self.added + self.deleted


@dataclass
class FileStat:
    """Totals for one file or directory across all commits."""

    path: str
    commits: int = 0
    added: int = 0
    deleted: int = 0

    @property
    def churn(self) -> int:
        return self.added + self.deleted


@dataclass
class Milestone:
    """A commit flagged as notable, with why."""

    date: datetime
    kind: str  # tag | merge | feat | big
    label: str
    commit: Commit


@dataclass
class Report:
    """Everything the TUI and exporters need, computed once."""

    repo_name: str
    origin: str
    authors: list[str]
    commits: list[Commit]
    sessions: list[Session]
    session_of: dict[str, int]
    daily: dict[date, Bucket]
    monthly: dict[str, Bucket]
    punchcard: list[list[int]]  # [weekday 0=Mon][hour] -> commits
    files: list[FileStat]
    dirs: list[FileStat]
    milestones: list[Milestone]
    total_hours: float
    longest_streak: int
    current_streak: int
    session_gap_min: int
    first_commit_min: int

    @property
    def coding_days(self) -> int:
        return len(self.daily)

    @property
    def total_added(self) -> int:
        return sum(c.added for c in self.commits)

    @property
    def total_deleted(self) -> int:
        return sum(c.deleted for c in self.commits)

    @property
    def first_date(self) -> datetime | None:
        return self.commits[0].date if self.commits else None

    @property
    def last_date(self) -> datetime | None:
        return self.commits[-1].date if self.commits else None


def estimate_sessions(
    commits: list[Commit], session_gap_min: int = 120, first_commit_min: int = 120
) -> list[Session]:
    """Group commits into work sessions and estimate hours (the git-hours method).

    Consecutive commits by the same author closer than ``session_gap_min`` count the gap
    as work time. Each session also gets ``first_commit_min`` for the work done before its
    first commit, which git cannot see. Authors are handled separately so two people
    committing at once do not merge into one session.

    Args:
        commits: Commits sorted by date ascending.
        session_gap_min: Max minutes between commits in one session.
        first_commit_min: Minutes credited before each session's first commit.

    Returns:
        Sessions sorted by start time, ids assigned in that order.
    """
    gap = timedelta(minutes=session_gap_min)
    lead = timedelta(minutes=first_commit_min)
    by_author: dict[str, list[Commit]] = defaultdict(list)
    for c in commits:
        by_author[c.email.casefold()].append(c)

    raw: list[tuple[str, list[Commit]]] = []
    for email, items in by_author.items():
        current: list[Commit] = []
        for c in items:
            if current and c.date - current[-1].date > gap:
                raw.append((email, current))
                current = []
            current.append(c)
        if current:
            raw.append((email, current))

    raw.sort(key=lambda r: r[1][0].date)
    sessions = []
    for i, (email, items) in enumerate(raw, start=1):
        span = items[-1].date - items[0].date
        hours = (span + lead).total_seconds() / 3600
        sessions.append(Session(i, email, items[0].date, items[-1].date, items, hours))
    return sessions


def streaks(days: set[date], today: date | None = None) -> tuple[int, int]:
    """Return (longest, current) runs of consecutive active days.

    The current streak still counts if the last active day was yesterday, so it does not
    drop to zero just because today has no commit yet.
    """
    if not days:
        return 0, 0
    ordered = sorted(days)
    longest = run = 1
    for prev, cur in zip(ordered, ordered[1:]):
        run = run + 1 if cur - prev == timedelta(days=1) else 1
        longest = max(longest, run)
    today = today or date.today()
    current = 0
    day = today if today in days else today - timedelta(days=1)
    while day in days:
        current += 1
        day -= timedelta(days=1)
    return longest, current


def _top_dir(path: str) -> str:
    return path.split("/", 1)[0] + "/" if "/" in path else "(root)"


def find_milestones(commits: list[Commit]) -> list[Milestone]:
    """Flag tags, merges, ``feat:`` commits, and unusually large commits.

    "Big" means churn above both a fixed floor and the repo's 95th percentile, so the
    threshold adapts to the repo instead of flagging every commit in a busy codebase.
    """
    churns = sorted(c.churn for c in commits if not c.is_merge)
    p95 = churns[int(len(churns) * 0.95)] if churns else 0
    big = max(_BIG_CHURN_FLOOR, p95)

    out: list[Milestone] = []
    for c in commits:
        if c.tags:
            out.append(Milestone(c.date, "tag", ", ".join(c.tags), c))
        if c.is_merge:
            out.append(Milestone(c.date, "merge", c.subject, c))
        elif _FEAT_RE.match(c.subject):
            out.append(Milestone(c.date, "feat", c.subject, c))
        elif c.churn > big:
            out.append(Milestone(c.date, "big", f"{c.subject} (+{c.added}/-{c.deleted})", c))
    return out


def build_report(
    commits: list[Commit],
    repo_name: str,
    origin: str,
    authors: list[str],
    session_gap_min: int = 120,
    first_commit_min: int = 120,
) -> Report:
    """Compute every stat the UI and exporters show.

    Day, month, and hour buckets use each commit's own UTC offset, so a commit at 23:00
    local time lands on that local day no matter where the report runs.

    Args:
        commits: Commits sorted by date ascending (already author-filtered).
        repo_name: Display name.
        origin: Path or URL the user gave.
        authors: Author filters applied, empty for all authors.
        session_gap_min: See ``estimate_sessions``.
        first_commit_min: See ``estimate_sessions``.

    Returns:
        The full report.
    """
    sessions = estimate_sessions(commits, session_gap_min, first_commit_min)
    session_of = {c.hash: s.id for s in sessions for c in s.commits}

    daily: dict[date, Bucket] = defaultdict(Bucket)
    monthly: dict[str, Bucket] = defaultdict(Bucket)
    punchcard = [[0] * 24 for _ in range(7)]
    files: dict[str, FileStat] = {}
    dirs: dict[str, FileStat] = {}

    for c in commits:
        d = c.date.date()
        for b in (daily[d], monthly[c.date.strftime("%Y-%m")]):
            b.commits += 1
            b.added += c.added
            b.deleted += c.deleted
            b.days.add(d)
        punchcard[c.date.weekday()][c.date.hour] += 1
        touched_dirs: set[str] = set()
        for f in c.files:
            fs = files.setdefault(f.path, FileStat(f.path))
            fs.commits += 1
            fs.added += f.added
            fs.deleted += f.deleted
            top = _top_dir(f.path)
            ds = dirs.setdefault(top, FileStat(top))
            ds.added += f.added
            ds.deleted += f.deleted
            touched_dirs.add(top)
        for top in touched_dirs:
            dirs[top].commits += 1

    # Session hours go to the day/month the session started; splitting across midnight
    # would add precision the estimate does not have.
    for s in sessions:
        daily[s.start.date()].hours += s.hours
        monthly[s.start.strftime("%Y-%m")].hours += s.hours

    # Fill idle months so time axes in charts stay linear.
    if commits:
        y, m = commits[0].date.year, commits[0].date.month
        last = commits[-1].date.strftime("%Y-%m")
        while (key := f"{y:04d}-{m:02d}") <= last:
            monthly.setdefault(key, Bucket())
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)

    longest, current = streaks(set(daily))
    return Report(
        repo_name=repo_name,
        origin=origin,
        authors=authors,
        commits=commits,
        sessions=sessions,
        session_of=session_of,
        daily=dict(sorted(daily.items())),
        monthly=dict(sorted(monthly.items())),
        punchcard=punchcard,
        files=sorted(files.values(), key=lambda f: f.churn, reverse=True),
        dirs=sorted(dirs.values(), key=lambda f: f.churn, reverse=True),
        milestones=find_milestones(commits),
        total_hours=sum(s.hours for s in sessions),
        longest_streak=longest,
        current_streak=current,
        session_gap_min=session_gap_min,
        first_commit_min=first_commit_min,
    )
