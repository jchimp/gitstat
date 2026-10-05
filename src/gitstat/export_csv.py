"""Write report data as CSV files for spreadsheets and further scripting."""

from __future__ import annotations

import csv
from pathlib import Path

from gitstat.analyze import Report


def write_csv(report: Report, out_dir: Path) -> list[Path]:
    """Write commits.csv, monthly.csv, files.csv, and sessions.csv.

    Args:
        report: Report to export.
        out_dir: Target directory, created if missing.

    Returns:
        Paths written.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def _write(name: str, header: list[str], rows: list[list[object]]) -> None:
        path = out_dir / name
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(header)
            w.writerows(rows)
        written.append(path)

    _write(
        "commits.csv",
        ["hash", "date", "author", "email", "session", "added", "deleted", "files", "merge",
         "tags", "subject"],
        [
            [c.hash, c.date.isoformat(), c.author, c.email, report.session_of.get(c.hash, ""),
             c.added, c.deleted, len(c.files), int(c.is_merge), " ".join(c.tags), c.subject]
            for c in report.commits
        ],
    )
    _write(
        "monthly.csv",
        ["month", "coding_days", "commits", "hours", "added", "deleted"],
        [
            [m, len(b.days), b.commits, round(b.hours, 2), b.added, b.deleted]
            for m, b in report.monthly.items()
        ],
    )
    _write(
        "files.csv",
        ["path", "commits", "added", "deleted", "churn"],
        [[f.path, f.commits, f.added, f.deleted, f.churn] for f in report.files],
    )
    _write(
        "sessions.csv",
        ["session", "email", "start", "end", "commits", "hours"],
        [
            [s.id, s.email, s.start.isoformat(), s.end.isoformat(), len(s.commits),
             round(s.hours, 2)]
            for s in report.sessions
        ],
    )
    return written
