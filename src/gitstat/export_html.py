"""Write a single self-contained, offline HTML dashboard.

Charts are SVG generated here rather than drawn by a bundled JS chart library: the
output stays small, works offline, and needs no vendored third-party code. JS is only
used for tooltips, expanding rows, sorting, and filtering.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path

from gitstat import __version__
from gitstat.analyze import Bucket, FileStat, Report

_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MAX_BAR = 48  # a few months of data should not render as slabs
_TOP_FILES = 300  # the full list is in files.csv; thousands of rows make the page sluggish


def _esc(value: object) -> str:
    return escape(str(value), quote=True)


def _fmt_int(n: int) -> str:
    return f"{n:,}"


def _fmt_hours(h: float) -> str:
    return f"{h:,.1f}"


def _nice_step(span: float, target_ticks: int = 4) -> float:
    """Return a 1/2/2.5/5 x 10^k step so ``span`` is covered in about ``target_ticks``."""
    if span <= 0:
        return 1
    raw = span / target_ticks
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def _tick_label(v: float) -> str:
    if abs(v) >= 1000:
        return f"{v / 1000:g}k"
    return f"{v:g}"


def _bar_path(x: float, w: float, y_base: float, y_end: float) -> str:
    """Bar with 4px rounded corners on the data end only, square at the baseline."""
    h = abs(y_base - y_end)
    if h < 0.5:
        return ""
    r = min(4.0, w / 2, h)
    if y_end < y_base:  # grows up
        return (f"M{x:.1f},{y_base:.1f}V{y_end + r:.1f}Q{x:.1f},{y_end:.1f} {x + r:.1f},"
                f"{y_end:.1f}H{x + w - r:.1f}Q{x + w:.1f},{y_end:.1f} {x + w:.1f},"
                f"{y_end + r:.1f}V{y_base:.1f}Z")
    return (f"M{x:.1f},{y_base:.1f}V{y_end - r:.1f}Q{x:.1f},{y_end:.1f} {x + r:.1f},"
            f"{y_end:.1f}H{x + w - r:.1f}Q{x + w:.1f},{y_end:.1f} {x + w:.1f},"
            f"{y_end - r:.1f}V{y_base:.1f}Z")


def _month_label(key: str) -> str:
    return datetime.strptime(key, "%Y-%m").strftime("%b %Y")


def _x_label_every(n: int, max_labels: int = 12) -> int:
    return max(1, math.ceil(n / max_labels))


def svg_month_bars(monthly: dict[str, Bucket], metric: str, label: str) -> str:
    """Single-series monthly bar chart for ``hours`` or ``commits``."""
    keys = list(monthly)
    vals = [getattr(monthly[k], metric) for k in keys]
    W, H, L, R, T, B = 960, 220, 44, 8, 12, 26
    pw, ph = W - L - R, H - T - B
    step = _nice_step(max(vals, default=0))
    top = max(step, math.ceil(max(vals, default=0) / step) * step)
    y = lambda v: T + ph - v / top * ph  # noqa: E731
    out = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="{_esc(label)}">']
    v = 0.0
    while v <= top + 1e-9:
        out.append(f'<line class="grid" x1="{L}" x2="{W - R}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>')
        out.append(f'<text class="tick" x="{L - 6}" y="{y(v) + 4:.1f}" text-anchor="end">'
                   f'{_tick_label(v)}</text>')
        v += step
    n = max(len(keys), 1)
    slot = pw / n
    bw = min(_MAX_BAR, max(1.0, slot - 2))  # 2px surface gap between adjacent bars
    every = _x_label_every(n)
    for i, (k, val) in enumerate(zip(keys, vals)):
        x = L + i * slot + (slot - bw) / 2
        shown = _fmt_hours(val) if metric == "hours" else _fmt_int(val)
        tip = f"{_month_label(k)}\n{label}: {shown}"
        out.append(f'<g class="col" data-tip="{_esc(tip)}">'
                   f'<rect class="hit" x="{L + i * slot:.1f}" y="{T}" width="{slot:.1f}" '
                   f'height="{ph}"/><path class="s1" d="{_bar_path(x, bw, T + ph, y(val))}"/>'
                   f'</g>')
        if i % every == 0:
            out.append(f'<text class="tick" x="{x + bw / 2:.1f}" y="{H - 8}" '
                       f'text-anchor="middle">{datetime.strptime(k, "%Y-%m"):%b %y}</text>')
    out.append(f'<line class="axis" x1="{L}" x2="{W - R}" y1="{T + ph}" y2="{T + ph}"/></svg>')
    return "".join(out)


def svg_loc_bars(monthly: dict[str, Bucket]) -> str:
    """Diverging monthly bars: lines added above the baseline, deleted below it."""
    keys = list(monthly)
    adds = [monthly[k].added for k in keys]
    dels = [monthly[k].deleted for k in keys]
    W, H, L, R, T, B = 960, 260, 44, 8, 12, 26
    pw, ph = W - L - R, H - T - B
    step = _nice_step(max(adds, default=0) + max(dels, default=0))
    up = max(step, math.ceil(max(adds, default=0) / step) * step)
    down = math.ceil(max(dels, default=0) / step) * step
    y = lambda v: T + (up - v) / (up + down) * ph  # noqa: E731
    out = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" '
           f'aria-label="Lines added and deleted per month">']
    v = -down
    while v <= up + 1e-9:
        out.append(f'<line class="grid" x1="{L}" x2="{W - R}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>')
        out.append(f'<text class="tick" x="{L - 6}" y="{y(v) + 4:.1f}" text-anchor="end">'
                   f'{_tick_label(abs(v))}</text>')
        v += step
    n = max(len(keys), 1)
    slot = pw / n
    bw = min(_MAX_BAR, max(1.0, slot - 2))
    every = _x_label_every(n)
    for i, (k, a, d) in enumerate(zip(keys, adds, dels)):
        x = L + i * slot + (slot - bw) / 2
        tip = f"{_month_label(k)}\nAdded: +{_fmt_int(a)}\nDeleted: -{_fmt_int(d)}"
        out.append(f'<g class="col" data-tip="{_esc(tip)}">'
                   f'<rect class="hit" x="{L + i * slot:.1f}" y="{T}" width="{slot:.1f}" '
                   f'height="{ph}"/><path class="pos" d="{_bar_path(x, bw, y(0), y(a))}"/>'
                   f'<path class="neg" d="{_bar_path(x, bw, y(0), y(-d))}"/></g>')
        if i % every == 0:
            out.append(f'<text class="tick" x="{x + bw / 2:.1f}" y="{H - 8}" '
                       f'text-anchor="middle">{datetime.strptime(k, "%Y-%m"):%b %y}</text>')
    out.append(f'<line class="axis" x1="{L}" x2="{W - R}" y1="{y(0):.1f}" y2="{y(0):.1f}"/>'
               f'</svg>')
    return "".join(out)


def heat_levels(counts: list[int]) -> list[int]:
    """Cut points for 4 non-zero heat levels from the quartiles of active-day counts."""
    nz = sorted(c for c in counts if c > 0)
    if not nz:
        return [1, 1, 1]
    return [nz[int(len(nz) * q)] for q in (0.25, 0.5, 0.75)]


def heat_level(count: int, cuts: list[int]) -> int:
    """Map a count to level 0..4 using ``heat_levels`` cut points."""
    if count <= 0:
        return 0
    return 1 + sum(count > c for c in cuts)


def svg_year_heatmap(year: int, daily: dict[date, Bucket], cuts: list[int]) -> str:
    """GitHub-style 53x7 contribution grid for one calendar year."""
    start = date(year, 1, 1)
    grid_start = start - timedelta(days=start.weekday())  # Monday-aligned columns
    end = date(year, 12, 31)
    C, G, L, T = 12, 3, 30, 18
    weeks = (end - grid_start).days // 7 + 1
    W, H = L + weeks * (C + G), T + 7 * (C + G)
    out = [f'<svg viewBox="0 0 {W} {H}" class="heat" role="img" '
           f'aria-label="Commit activity {year}">']
    for r, name in ((0, "Mon"), (2, "Wed"), (4, "Fri")):
        out.append(f'<text class="tick" x="0" y="{T + r * (C + G) + C - 2}">{name}</text>')
    last_month = 0
    d = start
    while d <= end:
        col = (d - grid_start).days // 7
        x, yy = L + col * (C + G), T + d.weekday() * (C + G)
        if d.month != last_month:
            out.append(f'<text class="tick" x="{x}" y="11">{d:%b}</text>')
            last_month = d.month
        b = daily.get(d)
        lvl = heat_level(b.commits if b else 0, cuts)
        tip = (f"{d:%a %d %b %Y}\n{b.commits} commits, {_fmt_hours(b.hours)} h\n"
               f"+{_fmt_int(b.added)} / -{_fmt_int(b.deleted)}") if b else f"{d:%a %d %b %Y}\n—"
        out.append(f'<rect class="h{lvl}" x="{x}" y="{yy}" width="{C}" height="{C}" rx="2" '
                   f'data-tip="{_esc(tip)}"/>')
        d += timedelta(days=1)
    out.append("</svg>")
    return "".join(out)


def svg_punchcard(punch: list[list[int]]) -> str:
    """Weekday x hour grid of commit counts."""
    C, G, L, T = 30, 3, 40, 18
    W, H = L + 24 * (C + G), T + 7 * (C + G)
    cuts = heat_levels([v for row in punch for v in row])
    out = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" '
           f'aria-label="Commits by weekday and hour">']
    for h in range(0, 24, 3):
        out.append(f'<text class="tick" x="{L + h * (C + G) + C / 2}" y="11" '
                   f'text-anchor="middle">{h:02d}</text>')
    for wd, row in enumerate(punch):
        yy = T + wd * (C + G)
        out.append(f'<text class="tick" x="0" y="{yy + C / 2 + 4}">{_DAYS[wd]}</text>')
        for h, v in enumerate(row):
            tip = f"{_DAYS[wd]} {h:02d}:00–{h:02d}:59\n{v} commits"
            out.append(f'<rect class="h{heat_level(v, cuts)}" x="{L + h * (C + G)}" y="{yy}" '
                       f'width="{C}" height="{C}" rx="3" data-tip="{_esc(tip)}"/>')
    out.append("</svg>")
    return "".join(out)


def _kpis(report: Report) -> str:
    span = ""
    if report.first_date and report.last_date:
        span = f"{report.first_date:%d %b %Y} → {report.last_date:%d %b %Y}"
    tiles = [
        ("Est. hours", _fmt_hours(report.total_hours),
         f"{len(report.sessions)} sessions"),
        ("Coding days", _fmt_int(report.coding_days),
         f"longest streak {report.longest_streak} d"),
        ("Commits", _fmt_int(len(report.commits)), span),
        ("Lines added", f"+{_fmt_int(report.total_added)}", ""),
        ("Lines deleted", f"-{_fmt_int(report.total_deleted)}", ""),
        ("Files touched", _fmt_int(len(report.files)), ""),
    ]
    return "".join(
        f'<div class="kpi"><div class="kpi-label">{_esc(a)}</div>'
        f'<div class="kpi-value">{_esc(b)}</div><div class="kpi-sub">{_esc(c)}</div></div>'
        for a, b, c in tiles
    )


def _months_grid(report: Report) -> str:
    by_month = defaultdict(list)
    for c in report.commits:
        by_month[c.date.strftime("%Y-%m")].append(c)
    peak = max((b.hours for b in report.monthly.values()), default=0) or 1
    rows: list[str] = []
    for key in reversed(report.monthly):
        b = report.monthly[key]
        pct = b.hours / peak * 100
        rows.append(
            f'<tbody class="month"><tr class="mrow" tabindex="0" aria-expanded="false">'
            f'<td><span class="caret">▸</span>{_esc(_month_label(key))}</td>'
            f'<td class="num">{len(b.days)}</td><td class="num">{b.commits}</td>'
            f'<td class="num">{_fmt_hours(b.hours)}</td>'
            f'<td class="num add">+{_fmt_int(b.added)}</td>'
            f'<td class="num del">-{_fmt_int(b.deleted)}</td>'
            f'<td class="barcell"><div class="mbar" style="width:{pct:.1f}%"></div></td>'
            f'</tr></tbody><tbody class="kids" hidden>'
        )
        for c in reversed(by_month[key]):
            files = "".join(
                f'<tr><td class="path">{_esc(f.path)}</td>'
                f'<td class="num add">{"bin" if f.binary else f"+{f.added}"}</td>'
                f'<td class="num del">{"" if f.binary else f"-{f.deleted}"}</td></tr>'
                for f in sorted(c.files, key=lambda f: f.added + f.deleted, reverse=True)
            )
            tags = "".join(f'<span class="badge tag">{_esc(t)}</span>' for t in c.tags)
            merge = '<span class="badge merge">merge</span>' if c.is_merge else ""
            rows.append(
                f'<tr class="crow" tabindex="0" aria-expanded="false">'
                f'<td class="mono"><span class="caret">▸</span>{c.date:%d %a %H:%M}</td>'
                f'<td class="mono muted">{c.hash[:8]}</td>'
                f'<td class="num">#{report.session_of.get(c.hash, "")}</td>'
                f'<td class="num">{len(c.files)}</td>'
                f'<td class="num add">+{_fmt_int(c.added)}</td>'
                f'<td class="num del">-{_fmt_int(c.deleted)}</td>'
                f'<td class="subj">{merge}{tags}{_esc(c.subject)}</td></tr>'
                f'<tr class="frow" hidden><td colspan="7"><table class="ftable">{files}'
                f'</table></td></tr>'
            )
        rows.append("</tbody>")
    return (
        '<table class="grid months"><thead><tr><th>Month</th><th class="num">Days</th>'
        '<th class="num">Commits</th><th class="num">Hours</th><th class="num">Added</th>'
        '<th class="num">Deleted</th><th>Hours vs. peak month</th></tr></thead>'
        + "".join(rows) + "</table>"
    )


def _file_table(stats: list[FileStat], table_id: str) -> str:
    rows = "".join(
        f'<tr><td class="path">{_esc(f.path)}</td><td class="num">{f.commits}</td>'
        f'<td class="num add">{f.added}</td><td class="num del">{f.deleted}</td>'
        f'<td class="num">{f.churn}</td></tr>'
        for f in stats
    )
    return (
        f'<table class="grid sortable" id="{table_id}"><thead><tr>'
        f'<th data-type="text">Path</th><th class="num" data-type="num">Commits</th>'
        f'<th class="num" data-type="num">Added</th><th class="num" data-type="num">Deleted</th>'
        f'<th class="num" data-type="num" aria-sort="descending">Churn</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>'
    )


def _milestones(report: Report) -> str:
    items = "".join(
        f'<li data-kind="{m.kind}"><span class="mdate mono">{m.date:%Y-%m-%d}</span>'
        f'<span class="badge {m.kind}">{m.kind}</span>'
        f'<span class="mono muted">{m.commit.hash[:8]}</span> {_esc(m.label)}</li>'
        for m in reversed(report.milestones)
    )
    kinds = sorted({m.kind for m in report.milestones})
    chips = "".join(
        f'<label class="chip"><input type="checkbox" value="{k}" checked> {k}</label>'
        for k in kinds
    )
    return f'<div class="filters" id="mfilters">{chips}</div><ul class="milestones">{items}</ul>'


def render_html(report: Report) -> str:
    """Render the full dashboard as one HTML string."""
    years = sorted({d.year for d in report.daily}, reverse=True)
    cuts = heat_levels([b.commits for b in report.daily.values()])
    heatmaps = "".join(
        f'<div class="year"><h3>{y}</h3>{svg_year_heatmap(y, report.daily, cuts)}</div>'
        for y in years
    )
    who = ", ".join(report.authors) if report.authors else "all authors"
    legend_heat = "".join(f'<rect class="h{i}" x="{i * 15}" y="0" width="12" height="12" rx="2"/>'
                          for i in range(5))
    method = (f"Hours use the git-hours method: commits less than {report.session_gap_min} min "
              f"apart are one session, and each session adds {report.first_commit_min} min "
              f"before its first commit. It is an estimate, not a timesheet.")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>gitstat · {_esc(report.repo_name)}</title>
<style>{_CSS}</style></head>
<body>
<header>
  <div><h1>{_esc(report.repo_name)}</h1>
  <p class="muted">{_esc(report.origin)} · {_esc(who)} ·
  generated {datetime.now():%Y-%m-%d %H:%M} by gitstat {__version__}</p></div>
  <button id="theme" type="button" aria-label="Toggle dark mode">◐</button>
</header>
<main>
<section class="kpis">{_kpis(report)}</section>
<p class="note">{_esc(method)}</p>

<section><h2>Activity</h2>
<div class="legend"><span class="muted">Less</span>
<svg width="72" height="12" aria-hidden="true">{legend_heat}</svg><span class="muted">More</span>
<span class="muted">· commits per day</span></div>
<div class="scroll">{heatmaps}</div></section>

<section><h2>Estimated hours per month</h2>{svg_month_bars(report.monthly, "hours", "Hours")}
</section>
<section><h2>Commits per month</h2>{svg_month_bars(report.monthly, "commits", "Commits")}
</section>
<section><h2>Lines changed per month</h2>
<div class="legend"><span class="sw pos"></span>Added (up)<span class="sw neg"></span>Deleted
(down)</div>{svg_loc_bars(report.monthly)}</section>
<section><h2>When you work</h2><div class="scroll">{svg_punchcard(report.punchcard)}</div>
<p class="muted small">Times are each commit's local time.</p></section>

<section><h2>Months</h2>
<div class="toolbar"><button type="button" id="expand">Expand all</button>
<button type="button" id="collapse">Collapse all</button>
<input type="search" id="csearch" placeholder="Filter commits by message or hash"></div>
<p class="muted small">Click a month to see its commits. Click a commit to see its files.</p>
<div class="scroll">{_months_grid(report)}</div></section>

<section><h2>Milestones</h2>
<p class="muted small">Tags, merges, <code>feat:</code> commits, and unusually large commits.</p>
{_milestones(report)}</section>

<section class="two">
<div><h2>Top directories</h2><div class="scroll">{_file_table(report.dirs, "dirs")}</div></div>
<div><h2>Top files</h2><input type="search" class="tfilter" data-table="files"
placeholder="Filter paths">
<div class="scroll tall">{_file_table(report.files[:_TOP_FILES], "files")}</div>
<p class="muted small">Top {min(_TOP_FILES, len(report.files))} of {len(report.files)} by churn.
The full list is in files.csv.</p></div>
</section>
</main>
<div id="tip" role="tooltip" hidden></div>
<script>{_JS}</script>
</body></html>
"""


def write_html(report: Report, path: Path) -> Path:
    """Render the dashboard and write it to ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(report), encoding="utf-8")
    return path


_CSS = """
:root{--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--grid:#e1e0d9;--axis:#c3c2b7;--border:rgba(11,11,11,.10);--s1:#2a78d6;--pos:#2a78d6;
--neg:#e34948;--h0:#f0efec;--h1:#b7d3f6;--h2:#6da7ec;--h3:#2a78d6;--h4:#104281;
--add:#006300;--del:#b42318;--hover:rgba(42,120,214,.08)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--page:#0d0d0d;
--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;
--border:rgba(255,255,255,.10);--s1:#3987e5;--pos:#3987e5;--neg:#e66767;--h0:#262624;
--h1:#184f95;--h2:#256abf;--h3:#3987e5;--h4:#86b6ef;--add:#0ca30c;--del:#e66767;
--hover:rgba(57,135,229,.12)}}
:root[data-theme="dark"]{--page:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;
--muted:#898781;--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);--s1:#3987e5;
--pos:#3987e5;--neg:#e66767;--h0:#262624;--h1:#184f95;--h2:#256abf;--h3:#3987e5;--h4:#86b6ef;
--add:#0ca30c;--del:#e66767;--hover:rgba(57,135,229,.12)}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);
font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
header{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;
padding:24px 16px 8px;max-width:1100px;margin:0 auto}
h1{margin:0;font-size:24px}h2{font-size:16px;margin:0 0 12px}h3{font-size:13px;margin:8px 0 4px;
color:var(--ink2)}
main{max-width:1100px;margin:0 auto;padding:0 16px 48px}
section{background:var(--surface);border:1px solid var(--border);border-radius:10px;
padding:16px;margin:16px 0}
section.two{display:grid;grid-template-columns:1fr 2fr;gap:24px}
@media (max-width:800px){section.two{grid-template-columns:1fr}}
.muted{color:var(--muted)}.small{font-size:12px}.mono{font-family:ui-monospace,Consolas,monospace}
.note{color:var(--ink2);font-size:12px;margin:0 2px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;
background:none;border:0;padding:0}
.kpi{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px 14px}
.kpi-label{color:var(--ink2);font-size:12px}.kpi-value{font-size:26px;font-weight:600;
font-variant-numeric:tabular-nums}.kpi-sub{color:var(--muted);font-size:12px;min-height:1em}
.chart{width:100%;height:auto;display:block}.heat{width:100%;min-width:640px;height:auto}
.scroll{overflow-x:auto}.tall{max-height:520px;overflow-y:auto}
line.grid{stroke:var(--grid);stroke-width:1}line.axis{stroke:var(--axis)}
text.tick{fill:var(--muted);font-size:11px}
.s1{fill:var(--s1)}.pos{fill:var(--pos)}.neg{fill:var(--neg)}
.hit{fill:transparent}.col:hover .hit{fill:var(--hover)}
.h0{fill:var(--h0)}.h1{fill:var(--h1)}.h2{fill:var(--h2)}.h3{fill:var(--h3)}.h4{fill:var(--h4)}
rect[data-tip]:hover{stroke:var(--ink);stroke-width:1}
.legend{display:flex;gap:8px;align-items:center;font-size:12px;margin-bottom:8px;flex-wrap:wrap}
.sw{display:inline-block;width:12px;height:12px;border-radius:3px}.sw.pos{background:var(--pos)}
.sw.neg{background:var(--neg)}
#tip{position:fixed;pointer-events:none;background:var(--ink);color:var(--surface);
padding:6px 8px;border-radius:6px;font-size:12px;white-space:pre-line;z-index:10;max-width:320px}
table.grid{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
table.grid th{text-align:left;color:var(--ink2);font-weight:600;border-bottom:1px solid var(--axis);
padding:6px 8px;position:sticky;top:0;background:var(--surface)}
table.grid td{padding:5px 8px;border-bottom:1px solid var(--grid);vertical-align:top}
.num{text-align:right;white-space:nowrap}.add{color:var(--add)}.del{color:var(--del)}
#dirs .path{white-space:nowrap}
.path{word-break:break-all;font-family:ui-monospace,Consolas,monospace;font-size:12px}
.mrow,.crow{cursor:pointer}.mrow:hover,.crow:hover{background:var(--hover)}
.mrow td{font-weight:600}.crow td{font-size:13px}.crow td:first-child{padding-left:24px}
.caret{display:inline-block;width:14px;color:var(--muted);transition:transform .15s}
[aria-expanded="true"] .caret{transform:rotate(90deg)}
.barcell{width:30%}.mbar{height:10px;border-radius:0 4px 4px 0;background:var(--s1);min-width:1px}
.frow td{padding:0 8px 8px 48px}.ftable{width:100%;font-size:12px}
.ftable td{padding:2px 6px;border:0}
.subj{word-break:break-word}
.badge{display:inline-block;font-size:11px;border:1px solid var(--axis);border-radius:999px;
padding:0 7px;margin-right:6px;color:var(--ink2)}
.toolbar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px}
button,input[type=search]{font:inherit;color:var(--ink);background:var(--page);
border:1px solid var(--border);border-radius:6px;padding:5px 10px}
input[type=search]{flex:1;min-width:200px}.tfilter{width:100%;margin-bottom:8px}
th[data-type]{cursor:pointer;user-select:none}
th[aria-sort="ascending"]::after{content:" ▲"}th[aria-sort="descending"]::after{content:" ▼"}
.filters{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px}
.chip{border:1px solid var(--border);border-radius:999px;padding:2px 10px;font-size:12px}
ul.milestones{list-style:none;margin:0;padding:0;max-height:420px;overflow-y:auto}
ul.milestones li{padding:5px 0;border-bottom:1px solid var(--grid);display:flex;gap:8px;
align-items:baseline;flex-wrap:wrap}
.mdate{color:var(--ink2)}
"""

_JS = r"""
(() => {
const tip = document.getElementById('tip');
document.addEventListener('mouseover', e => {
  const t = e.target.closest('[data-tip]');
  if (!t) { tip.hidden = true; return; }
  tip.textContent = t.dataset.tip; tip.hidden = false;
});
document.addEventListener('mousemove', e => {
  if (tip.hidden) return;
  const pad = 14, w = tip.offsetWidth, h = tip.offsetHeight;
  let x = e.clientX + pad, y = e.clientY + pad;
  if (x + w > innerWidth) x = e.clientX - w - pad;
  if (y + h > innerHeight) y = e.clientY - h - pad;
  tip.style.left = x + 'px'; tip.style.top = y + 'px';
});

const setOpen = (row, open) => {
  row.setAttribute('aria-expanded', open);
  if (row.classList.contains('mrow')) {
    row.closest('tbody').nextElementSibling.hidden = !open;
  } else {
    row.nextElementSibling.hidden = !open;
  }
};
const toggle = row => setOpen(row, row.getAttribute('aria-expanded') !== 'true');
document.addEventListener('click', e => {
  const row = e.target.closest('.mrow, .crow');
  if (row) toggle(row);
});
document.addEventListener('keydown', e => {
  const row = e.target.closest && e.target.closest('.mrow, .crow');
  if (row && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); toggle(row); }
});
document.getElementById('expand').onclick = () =>
  document.querySelectorAll('.mrow').forEach(r => setOpen(r, true));
document.getElementById('collapse').onclick = () =>
  document.querySelectorAll('.mrow, .crow').forEach(r => setOpen(r, false));

document.getElementById('csearch').addEventListener('input', e => {
  const q = e.target.value.trim().toLowerCase();
  document.querySelectorAll('tbody.kids').forEach(kids => {
    let hits = 0;
    kids.querySelectorAll('.crow').forEach(r => {
      const show = !q || r.textContent.toLowerCase().includes(q);
      r.hidden = !show;
      if (!show) { r.nextElementSibling.hidden = true; r.setAttribute('aria-expanded', false); }
      hits += show;
    });
    const mrow = kids.previousElementSibling.querySelector('.mrow');
    kids.previousElementSibling.hidden = q && !hits;
    setOpen(mrow, !!q && hits > 0);
  });
});

document.querySelectorAll('table.sortable th[data-type]').forEach(th => {
  th.addEventListener('click', () => {
    const table = th.closest('table'), idx = [...th.parentNode.children].indexOf(th);
    const cur = th.getAttribute('aria-sort');
    const asc = cur ? cur === 'descending' : th.dataset.type === 'text';
    table.querySelectorAll('th').forEach(h => h.removeAttribute('aria-sort'));
    th.setAttribute('aria-sort', asc ? 'ascending' : 'descending');
    const body = table.tBodies[0], rows = [...body.rows];
    const key = r => th.dataset.type === 'num'
      ? Number(r.cells[idx].textContent) : r.cells[idx].textContent.toLowerCase();
    rows.sort((a, b) => (key(a) > key(b) ? 1 : key(a) < key(b) ? -1 : 0) * (asc ? 1 : -1));
    rows.forEach(r => body.appendChild(r));
  });
});
document.querySelectorAll('.tfilter').forEach(inp => inp.addEventListener('input', () => {
  const q = inp.value.trim().toLowerCase();
  document.querySelectorAll(`#${inp.dataset.table} tbody tr`).forEach(r => {
    r.hidden = q && !r.cells[0].textContent.toLowerCase().includes(q);
  });
}));
document.querySelectorAll('#mfilters input').forEach(cb => cb.addEventListener('change', () => {
  const on = new Set([...document.querySelectorAll('#mfilters input:checked')].map(c => c.value));
  document.querySelectorAll('ul.milestones li').forEach(li => li.hidden = !on.has(li.dataset.kind));
}));

const root = document.documentElement;
document.getElementById('theme').onclick = () => {
  const dark = root.dataset.theme
    ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  root.dataset.theme = dark ? 'light' : 'dark';
};
})();
"""
