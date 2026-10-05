"""Command-line entry point: ``gitstat <repo>``."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from gitstat import __version__
from gitstat.analyze import Report, build_report
from gitstat.collect import collect, filter_authors
from gitstat.export import DEFAULT_OUT, export_all
from gitstat.source import GitError, configured_email, resolve


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    p = argparse.ArgumentParser(
        prog="gitstat",
        description="Effort and activity stats for a git repo (local path or URL).",
    )
    p.add_argument("repo", nargs="?", default=".", help="repo path or URL (default: .)")
    who = p.add_mutually_exclusive_group()
    who.add_argument("--author", action="append", metavar="PATTERN",
                     help="count commits whose author email/name contains PATTERN "
                          "(repeatable; default: your git user.email)")
    who.add_argument("--all-authors", action="store_true", help="count every author")
    p.add_argument("--since", help="git date, e.g. 2025-01-01 or '6 months ago'")
    p.add_argument("--until", help="git date upper bound")
    p.add_argument("--session-gap", type=int, default=120, metavar="MIN",
                   help="max minutes between commits in one work session (default: 120)")
    p.add_argument("--first-commit", type=int, default=120, metavar="MIN",
                   help="minutes credited before each session's first commit (default: 120)")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, metavar="DIR",
                   help="reports folder; files go in DIR/<repo>/ (default: reports)")
    p.add_argument("--export", action="store_true",
                   help="write report.html and CSV files without pressing e in the TUI")
    p.add_argument("--no-tui", action="store_true", help="print a summary instead of the TUI")
    p.add_argument("--no-fetch", action="store_true",
                   help="for URLs, use the cached clone without fetching")
    p.add_argument("--version", action="version", version=f"gitstat {__version__}")
    return p.parse_args(argv)


def print_summary(report: Report) -> None:
    """Print the headline numbers for non-interactive use."""
    r = report
    busiest = sorted(r.monthly.items(), key=lambda kv: kv[1].hours, reverse=True)[:3]
    print(f"{r.repo_name}  ({', '.join(r.authors) or 'all authors'})")
    if r.first_date and r.last_date:
        print(f"  span          {r.first_date:%Y-%m-%d} to {r.last_date:%Y-%m-%d}")
    print(f"  est. hours    {r.total_hours:,.1f}  ({len(r.sessions)} sessions)")
    print(f"  coding days   {r.coding_days:,}  (longest streak {r.longest_streak})")
    print(f"  commits       {len(r.commits):,}")
    print(f"  lines         +{r.total_added:,} / -{r.total_deleted:,}")
    print("  busiest       " + ", ".join(f"{k} ({b.hours:.0f} h)" for k, b in busiest))
    print("  top dirs      " + ", ".join(f"{d.path} ({d.churn:,})" for d in r.dirs[:3]))


def main(argv: list[str] | None = None) -> int:
    """Run gitstat. Returns a process exit code."""
    args = parse_args(argv)
    # Windows consoles default to cp1252; commit subjects and paths can hold any character.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    try:
        repo = resolve(args.repo, refresh=not args.no_fetch)
        commits = collect(repo, since=args.since, until=args.until)
    except GitError as exc:
        print(f"gitstat: {exc}", file=sys.stderr)
        return 2

    if args.all_authors:
        authors: list[str] = []
    elif args.author:
        authors = args.author
    else:
        email = configured_email(repo)
        if not email:
            print("gitstat: no git user.email configured; use --author or --all-authors",
                  file=sys.stderr)
            return 2
        authors = [email]

    total = len(commits)
    if authors:
        commits = filter_authors(commits, authors)
    if not commits:
        print(f"gitstat: no commits matched ({total} commits in range).", file=sys.stderr)
        if total:
            top = Counter(f"{c.author} <{c.email}>" for c in collect(repo)).most_common(5)
            print("Top authors in this repo (try --author or --all-authors):", file=sys.stderr)
            for who, n in top:
                print(f"  {n:>6}  {who}", file=sys.stderr)
        return 1

    report = build_report(commits, repo.name, repo.origin, authors,
                          args.session_gap, args.first_commit)

    try:
        if args.export:
            written = export_all(report, args.out)
            print(f"Wrote {len(written)} files to {written[0].parent}")
    except OSError as exc:
        print(f"gitstat: export failed: {exc}", file=sys.stderr)
        return 1

    if args.no_tui:
        print_summary(report)
        return 0

    from gitstat.tui.app import GitStatApp  # deferred: Textual import is slow for --no-tui

    GitStatApp(
        report,
        out_root=args.out,
    ).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
