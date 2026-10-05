"""Tests for collection, analysis, exports, and the CLI."""

from __future__ import annotations

import csv
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from gitstat.analyze import build_report, estimate_sessions, find_milestones, streaks
from gitstat.cli import main
from gitstat.collect import Commit, FileChange, collect, filter_authors, normalize_rename
from gitstat.export_csv import write_csv
from gitstat.export_html import render_html
from gitstat.source import GitError, is_url, resolve


def _c(minutes: int, email: str = "a@x", churn: int = 1, subject: str = "s") -> Commit:
    when = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=minutes)
    return Commit(f"h{minutes}{email}", [], "A", email, when, "", subject,
                  [FileChange("f", churn, 0)])


@pytest.mark.parametrize(("raw", "expected"), [
    ("src/a.py", "src/a.py"),
    ("old.py => new.py", "new.py"),
    ("src/{old => new}/f.py", "src/new/f.py"),
    ("src/{ => sub}/f.py", "src/sub/f.py"),
    ("src/{sub => }/f.py", "src/f.py"),
])
def test_normalize_rename(raw: str, expected: str) -> None:
    assert normalize_rename(raw) == expected


@pytest.mark.parametrize(("target", "url"), [
    ("https://github.com/a/b.git", True),
    ("git@github.com:a/b.git", True),
    ("ssh://git@host/a/b", True),
    ("C:/src/repo", False),
    ("../repo", False),
])
def test_is_url(target: str, url: bool) -> None:
    assert is_url(target) is url


def test_sessions_split_on_gap_and_author() -> None:
    commits = [_c(0), _c(60), _c(60 + 121), _c(30, email="b@x")]
    commits.sort(key=lambda c: c.date)
    sessions = estimate_sessions(commits, session_gap_min=120, first_commit_min=120)
    hours = sorted(round(s.hours, 2) for s in sessions)
    # a@x: [0, 60] -> 1 h + 2 h; [181] -> 2 h. b@x: [30] -> 2 h.
    assert hours == [2.0, 2.0, 3.0]


def test_streaks() -> None:
    days = {date(2026, 1, d) for d in (1, 2, 3, 5, 6)}
    assert streaks(days, today=date(2026, 1, 7)) == (3, 2)
    assert streaks(days, today=date(2026, 1, 9)) == (3, 0)
    assert streaks(set()) == (0, 0)


def test_big_commit_threshold_has_floor() -> None:
    commits = [_c(i, churn=10) for i in range(40)] + [_c(100, churn=400), _c(200, churn=900)]
    kinds = [(m.kind, m.commit.churn) for m in find_milestones(commits)]
    assert kinds == [("big", 900)]


def test_collect_and_report(repo: Path) -> None:
    src = resolve(str(repo))
    commits = collect(src)
    assert len(commits) == 5
    assert commits[0].subject == "feat: start app"
    assert commits[1].added == 2 and commits[1].deleted == 1
    assert commits[-1].files[0].path == "src/main.py"  # rename resolved to new path
    assert "v0.1" in commits[2].tags

    mine = filter_authors(commits, ["me@example.com"])
    assert len(mine) == 4
    report = build_report(mine, src.name, src.origin, ["me@example.com"])
    assert len(report.sessions) == 3
    assert report.total_hours == pytest.approx(3.5 + 2 + 2)
    assert report.coding_days == 3
    assert list(report.monthly) == ["2026-01", "2026-02", "2026-03"]
    assert report.monthly["2026-02"].commits == 0
    assert report.monthly["2026-01"].hours == pytest.approx(5.5)
    # Local-time bucketing: 09:00-06:00 is a Sunday 09:00 in the author's zone.
    assert report.punchcard[6][9] == 1
    assert {m.kind for m in report.milestones} == {"feat", "tag"}


def test_exports(repo: Path, tmp_path: Path) -> None:
    src = resolve(str(repo))
    report = build_report(collect(src), src.name, src.origin, [])
    html = render_html(report)
    assert "<svg" in html and "feat: start app" in html and "v0.1" in html
    paths = write_csv(report, tmp_path / "csv")
    assert {p.name for p in paths} == {"commits.csv", "monthly.csv", "files.csv", "sessions.csv"}
    with (tmp_path / "csv" / "monthly.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert [r["month"] for r in rows] == ["2026-01", "2026-02", "2026-03"]


def test_html_escapes_subjects(repo: Path) -> None:
    src = resolve(str(repo))
    report = build_report(collect(src), src.name, src.origin, [])
    report.commits[0].subject = "<script>alert(1)</script>"
    assert "<script>alert(1)" not in render_html(report)


def test_cli_default_uses_git_user_email(repo: Path, tmp_path: Path,
                                        capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "r.html"
    assert main([str(repo), "--no-tui", "--html", str(out), "--csv", str(tmp_path / "c")]) == 0
    text = capsys.readouterr().out
    assert "commits       4" in text  # only me@example.com, from repo config
    assert out.exists()


def test_cli_all_authors(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(repo), "--no-tui", "--all-authors"]) == 0
    assert "commits       5" in capsys.readouterr().out


def test_cli_no_match_lists_authors(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(repo), "--no-tui", "--author", "nobody"]) == 1
    assert "them@example.com" in capsys.readouterr().err


def test_resolve_rejects_non_repo(tmp_path: Path) -> None:
    with pytest.raises(GitError):
        resolve(str(tmp_path))


def test_resolve_url_mirrors_into_cache(repo: Path, tmp_path: Path,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("gitstat.source.cache_root", lambda: tmp_path / "cache")
    url = repo.resolve().as_uri()  # file:// URL exercises the clone path without network
    src = resolve(url)
    assert src.git_dir.parent == tmp_path / "cache"
    assert len(collect(src)) == 5
    assert resolve(url).git_dir == src.git_dir  # second call reuses and fetches
