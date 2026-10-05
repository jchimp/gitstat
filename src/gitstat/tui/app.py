"""Textual app: overview, charts, months, files, and a commit timeline."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widget import Widget
from textual.widgets import DataTable, Footer, Header, Static, TabbedContent, TabPane

from gitstat.analyze import FileStat, Report
from gitstat.collect import Commit
from gitstat.export import export_all
from gitstat.tui import render

# One glyph per milestone kind keeps the Mark column narrow; the legend is in the footer hint.
_KIND_MARK = {"tag": "◆", "merge": "⑂", "feat": "★", "big": "▲"}


def _num(value: int | float, style: str = "", sign: str = "") -> Text:
    shown = f"{value:,.1f}" if isinstance(value, float) else f"{value:,}"
    return Text(f"{sign}{shown}", style=style if value else "dim", justify="right")


def _sort_key(cell: Any) -> Any:
    """Sort numbers numerically and everything else case-insensitively."""
    raw = cell.plain if isinstance(cell, Text) else str(cell)
    try:
        return (0, float(raw.replace(",", "").lstrip("+-#")))
    except ValueError:
        return (1, raw.casefold())


class Chart(Widget):
    """Re-renders a Rich Text builder at the widget's current width."""

    DEFAULT_CSS = "Chart { height: auto; }"

    def __init__(self, build: Callable[[int], Text], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._build = build

    def render(self) -> Text:
        return self._build(self.size.width or 100)

    def get_content_height(self, container: Any, viewport: Any, width: int) -> int:
        return len(self._build(width).plain.rstrip("\n").splitlines()) or 1


class GitStatApp(App[None]):
    """Interactive viewer for a gitstat Report."""

    TITLE = "gitstat"
    CSS = """
    .kpis { height: 5; }
    .kpi { width: 1fr; height: 5; border: round $primary-darken-2; padding: 0 1; }
    .section-title { text-style: bold; margin: 1 0 0 0; color: $accent; }
    .note { color: $text-muted; }
    #timeline-pane Horizontal { height: 1fr; }
    #commits { width: 1fr; }
    #detail-scroll { width: 64; border-left: solid $primary-darken-2; padding: 0 1; }
    #files-pane Horizontal { height: 1fr; }
    #dirs { width: 1fr; }
    #files { width: 2fr; }
    DataTable { height: 1fr; }
    """
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("e", "export", "Export HTML+CSV"),
        Binding("m", "toggle_milestones", "Milestones only (◆tag ⑂merge ★feat ▲big)"),
        Binding("1", "tab('overview')", "Overview", show=False, priority=True),
        Binding("2", "tab('charts')", "Charts", show=False, priority=True),
        Binding("3", "tab('months')", "Months", show=False, priority=True),
        Binding("4", "tab('files-pane')", "Files", show=False, priority=True),
        Binding("5", "tab('timeline-pane')", "Timeline", show=False, priority=True),
    ]

    def __init__(self, report: Report, out_root: Path) -> None:
        super().__init__()
        self.report = report
        self.out_root = out_root
        self.milestones_only = False
        self._by_hash = {c.hash: c for c in report.commits}
        self._milestone_kinds: dict[str, list[str]] = {}
        for m in report.milestones:
            self._milestone_kinds.setdefault(m.commit.hash, []).append(m.kind)
        self._sort_state: dict[str, tuple[str, bool]] = {}

    # ---- layout -------------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        r = self.report
        yield Header()
        with TabbedContent(initial="overview"):
            with TabPane("1 Overview", id="overview"), VerticalScroll():
                with Horizontal(classes="kpis"):
                    for label, value in self._kpi_values():
                        yield Static(f"[dim]{label}[/]\n[b]{value}[/]", classes="kpi")
                yield Static(self._subtitle(), classes="note")
                yield Static("Activity", classes="section-title")
                yield Static(render.all_heatmaps(r.daily))
                yield Static("Estimated hours per month", classes="section-title")
                yield Chart(lambda w: render.month_bars(r.monthly, "hours", w, " h"))
            with TabPane("2 Charts", id="charts"), VerticalScroll():
                yield Static("Commits per month", classes="section-title")
                yield Chart(lambda w: render.month_bars(r.monthly, "commits", w))
                yield Static("Lines changed per month  (deleted ◀ │ ▶ added)",
                             classes="section-title")
                yield Chart(lambda w: render.loc_bars(r.monthly, w))
                yield Static("When you work  (weekday × hour, commit local time)",
                             classes="section-title")
                yield Static(render.punchcard(r.punchcard))
            with TabPane("3 Months", id="months"):
                yield DataTable(id="months-table", cursor_type="row", zebra_stripes=True)
            with TabPane("4 Files", id="files-pane"), Horizontal():
                yield DataTable(id="dirs", cursor_type="row", zebra_stripes=True)
                yield DataTable(id="files", cursor_type="row", zebra_stripes=True)
            with TabPane("5 Timeline", id="timeline-pane"), Horizontal():
                yield DataTable(id="commits", cursor_type="row")
                with VerticalScroll(id="detail-scroll"):
                    yield Static(id="detail")
        yield Footer()

    def _kpi_values(self) -> list[tuple[str, str]]:
        r = self.report
        return [
            ("Est. hours", f"{r.total_hours:,.1f}"),
            ("Coding days", f"{r.coding_days:,}"),
            ("Commits", f"{len(r.commits):,}"),
            ("Lines +", f"[green]+{r.total_added:,}[/]"),
            ("Lines −", f"[red]-{r.total_deleted:,}[/]"),
            ("Streak", f"{r.longest_streak} d best · {r.current_streak} d now"),
        ]

    def _subtitle(self) -> str:
        r = self.report
        span = ""
        if r.first_date and r.last_date:
            span = f"{r.first_date:%d %b %Y} → {r.last_date:%d %b %Y} · "
        return (f"{span}{len(r.sessions)} sessions · {len(r.files):,} files touched · "
                f"hours = git-hours method ({r.session_gap_min} min gap, "
                f"+{r.first_commit_min} min per session). Estimate, not a timesheet.")

    def on_mount(self) -> None:
        r = self.report
        who = ", ".join(r.authors) if r.authors else "all authors"
        self.title = f"gitstat · {r.repo_name}"
        self.sub_title = who
        self._fill_months()
        self._fill_files(self.query_one("#dirs", DataTable), r.dirs, "Directory")
        self._fill_files(self.query_one("#files", DataTable), r.files, "File")
        commits = self.query_one("#commits", DataTable)
        commits.add_columns("Day", "Time", "Hash", "Sess", "+", "-", "Files", "Mark", "Subject")
        self._fill_commits()

    # ---- tables -------------------------------------------------------------------------

    def _fill_months(self) -> None:
        table = self.query_one("#months-table", DataTable)
        table.add_columns("Month", "Days", "Commits", "Hours", "+", "-", "Hours bar")
        peak = max((b.hours for b in self.report.monthly.values()), default=0)
        for key, b in reversed(self.report.monthly.items()):
            table.add_row(
                key, _num(len(b.days)), _num(b.commits), _num(round(b.hours, 1)),
                _num(b.added, "green", "+"), _num(b.deleted, "red", "-"),
                Text(render.hbar(b.hours, peak, 30), style=render.BAR),
                key=key,
            )

    def _fill_files(self, table: DataTable, stats: list[FileStat], label: str) -> None:
        # Path goes last: long paths would otherwise push the numbers off-screen.
        table.add_columns("Churn", "Commits", "+", "-", label)
        for f in stats:
            table.add_row(
                _num(f.churn), _num(f.commits), _num(f.added, "green"), _num(f.deleted, "red"),
                f.path, key=f.path,
            )

    def _fill_commits(self) -> None:
        table = self.query_one("#commits", DataTable)
        table.clear()
        last_day = None
        last_session = None
        for c in reversed(self.report.commits):
            kinds = self._milestone_kinds.get(c.hash, [])
            if self.milestones_only and not kinds:
                continue
            day = c.date.strftime("%a %d %b %Y")
            session = self.report.session_of.get(c.hash)
            # Only label the first row of each day/session so groups read as blocks.
            day_cell = Text(day, style="bold") if day != last_day else Text("")
            sess_style = "bold" if session != last_session else "dim"
            last_day, last_session = day, session
            mark = Text("".join(_KIND_MARK[k] for k in kinds), style="yellow")
            table.add_row(
                day_cell, c.date.strftime("%H:%M"), Text(c.hash[:8], style="dim"),
                Text(f"#{session}", style=sess_style, justify="right"),
                _num(c.added, "green", "+"), _num(c.deleted, "red", "-"),
                _num(len(c.files)), mark, c.subject,
                key=c.hash,
            )
        if table.row_count:
            self._show_commit(self._by_hash[str(table.coordinate_to_cell_key((0, 0)).row_key
                                                 .value)])

    def _show_commit(self, c: Commit) -> None:
        r = self.report
        sid = r.session_of.get(c.hash)
        session = r.sessions[sid - 1] if sid else None
        text = Text()
        text.append(f"{c.subject}\n\n", style="bold")
        text.append(f"{c.hash}\n", style="dim")
        text.append(f"{c.author} <{c.email}>\n")
        text.append(f"{c.date:%A %d %B %Y %H:%M %z}\n")
        if c.refs:
            text.append(f"{c.refs}\n", style="yellow")
        if c.is_merge:
            text.append(f"merge of {len(c.parents)} parents\n", style="yellow")
        if session:
            text.append(
                f"\nSession #{session.id}: {session.start:%H:%M}–{session.end:%H:%M}, "
                f"{len(session.commits)} commits, ~{session.hours:.1f} h\n", style="cyan")
        text.append(f"\n{len(c.files)} files  ", style="bold")
        text.append(f"+{c.added:,} ", style=render.ADD)
        text.append(f"-{c.deleted:,}\n\n", style=render.DEL)
        text.append_text(render.diffstat(c))
        self.query_one("#detail", Static).update(text)

    # ---- events -------------------------------------------------------------------------

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "commits" and event.row_key.value in self._by_hash:
            self._show_commit(self._by_hash[event.row_key.value])

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Enter on a month jumps to that month's newest commit in the timeline."""
        if event.data_table.id != "months-table":
            return
        month = event.row_key.value
        target = next(
            (c for c in reversed(self.report.commits) if c.date.strftime("%Y-%m") == month),
            None,
        )
        if target is None:
            self.notify(f"No commits in {month}")
            return
        if self.milestones_only and target.hash not in self._milestone_kinds:
            self.action_toggle_milestones()
        commits = self.query_one("#commits", DataTable)
        self.action_tab("timeline-pane")
        commits.move_cursor(row=commits.get_row_index(target.hash))
        commits.focus()

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        table = event.data_table
        if table.id == "commits":
            return  # the timeline's grouped Day/Sess cells only make sense in date order
        col = event.column_key.value or ""
        prev_col, prev_rev = self._sort_state.get(table.id or "", ("", True))
        reverse = (not prev_rev if prev_col == col
                   else event.label.plain not in ("Directory", "File", "Month"))
        self._sort_state[table.id or ""] = (col, reverse)
        table.sort(event.column_key, key=_sort_key, reverse=reverse)

    # ---- actions ------------------------------------------------------------------------

    def action_tab(self, tab: str) -> None:
        # TabbedContent snaps back to the pane holding focus, so drop focus before switching.
        self.set_focus(None)
        tabs = self.query_one(TabbedContent)
        tabs.active = tab
        tables = tabs.get_pane(tab).query(DataTable)
        (tables.first() if tables else tabs.query_one("ContentTabs")).focus()

    def action_toggle_milestones(self) -> None:
        self.milestones_only = not self.milestones_only
        self._fill_commits()
        state = "milestones only" if self.milestones_only else "all commits"
        self.notify(f"Timeline: {state}")
        self.action_tab("timeline-pane")

    def action_export(self) -> None:
        try:
            written = export_all(self.report, self.out_root)
        except OSError as exc:
            self.notify(f"Export failed: {exc}", severity="error", timeout=10)
            return
        self.notify(f"Wrote {len(written)} files to {written[0].parent}", timeout=8)
