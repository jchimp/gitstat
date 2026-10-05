"""Write every report file for one repo into a single output folder."""

from __future__ import annotations

from pathlib import Path

from gitstat.analyze import Report
from gitstat.export_csv import write_csv
from gitstat.export_html import write_html

DEFAULT_OUT = Path("reports")


def report_dir(out_root: Path, repo_name: str) -> Path:
    """Return ``<out_root>/<repo_name>`` so reports for different repos never collide."""
    return out_root / repo_name


def export_all(report: Report, out_root: Path) -> list[Path]:
    """Write report.html and the CSV files into ``<out_root>/<repo>/``.

    Args:
        report: Report to export.
        out_root: Root reports folder, created if missing.

    Returns:
        Paths written, HTML first.
    """
    target = report_dir(out_root, report.repo_name)
    return [write_html(report, target / "report.html"), *write_csv(report, target)]
