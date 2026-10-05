"""Rich Text builders for terminal charts: heatmap, bars, punchcard, diffstat."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from rich.text import Text

from gitstat.analyze import Bucket
from gitstat.collect import Commit
from gitstat.export_html import heat_level, heat_levels

# Sequential blue ramp tuned for dark terminals: level 0 recedes toward the background.
HEAT = ["#2a2a28", "#184f95", "#256abf", "#3987e5", "#86b6ef"]
BAR = "#3987e5"
ADD = "#3fb950"
DEL = "#e66767"
MUTED = "#898781"
_EIGHTHS = " ▏▎▍▌▋▊▉"
_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def hbar(value: float, peak: float, width: int) -> str:
    """Horizontal bar using eighth blocks so small differences stay visible."""
    if peak <= 0 or width <= 0 or value <= 0:
        return ""
    eighths = max(1, round(value / peak * width * 8))
    return "█" * (eighths // 8) + (_EIGHTHS[eighths % 8] if eighths % 8 else "")


def year_heatmap(year: int, daily: dict[date, Bucket], cuts: list[int]) -> Text:
    """GitHub-style grid for one calendar year, one column per week."""
    start = date(year, 1, 1)
    grid_start = start - timedelta(days=start.weekday())
    end = date(year, 12, 31)
    weeks = (end - grid_start).days // 7 + 1

    header = [" "] * (weeks * 2)
    for m in range(1, 13):
        col = (date(year, m, 1) - grid_start).days // 7 * 2
        name = date(year, m, 1).strftime("%b")
        if col + len(name) <= len(header):
            header[col:col + len(name)] = name
    text = Text(f"{year}\n", style="bold")
    text.append("    " + "".join(header) + "\n", style=MUTED)
    for wd in range(7):
        text.append(f"{_DAYS[wd] if wd % 2 == 0 else '':<4}", style=MUTED)
        for w in range(weeks):
            d = grid_start + timedelta(days=w * 7 + wd)
            if d.year != year:
                text.append("  ")
                continue
            b = daily.get(d)
            text.append("■ ", style=HEAT[heat_level(b.commits if b else 0, cuts)])
        text.append("\n")
    return text


def heat_legend() -> Text:
    text = Text("    Less ", style=MUTED)
    for color in HEAT:
        text.append("■ ", style=color)
    text.append("More  (commits per day)", style=MUTED)
    return text


def all_heatmaps(daily: dict[date, Bucket]) -> Text:
    """Heatmaps for every active year, newest first, plus a legend."""
    cuts = heat_levels([b.commits for b in daily.values()])
    text = Text()
    for year in sorted({d.year for d in daily}, reverse=True):
        text.append_text(year_heatmap(year, daily, cuts))
        text.append("\n")
    text.append_text(heat_legend())
    return text


def month_bars(monthly: dict[str, Bucket], metric: str, width: int, unit: str = "") -> Text:
    """One row per month: label, bar, value."""
    vals = {k: getattr(b, metric) for k, b in monthly.items()}
    peak = max(vals.values(), default=0)
    bar_w = max(10, width - 24)
    text = Text()
    for k, v in vals.items():
        label = datetime.strptime(k, "%Y-%m").strftime("%b %Y")
        shown = f"{v:,.1f}" if isinstance(v, float) else f"{v:,}"
        text.append(f"{label:<9}│", style=MUTED)
        text.append(f"{hbar(v, peak, bar_w):<{bar_w}}", style=BAR)
        text.append(f" {shown}{unit}\n")
    return text


def loc_bars(monthly: dict[str, Bucket], width: int) -> Text:
    """Diverging rows: deleted grows left of the axis, added grows right, on one scale."""
    peak = max((max(b.added, b.deleted) for b in monthly.values()), default=0)
    half = max(8, (width - 32) // 2)
    text = Text()
    for k, b in monthly.items():
        label = datetime.strptime(k, "%Y-%m").strftime("%b %Y")
        text.append(f"{label:<9}", style=MUTED)
        text.append(f"{'-' + format(b.deleted, ','):>9} ", style=DEL)
        # Eighth blocks are left-anchored, so a left-growing bar uses whole cells only.
        left = max(1, round(b.deleted / peak * half)) if peak and b.deleted else 0
        text.append(f"{'█' * left:>{half}}", style=DEL)
        text.append("│", style=MUTED)
        text.append(f"{hbar(b.added, peak, half):<{half}}", style=ADD)
        text.append(f" +{b.added:,}\n", style=ADD)
    return text


def punchcard(punch: list[list[int]]) -> Text:
    """Weekday x hour grid of commit counts."""
    cuts = heat_levels([v for row in punch for v in row])
    text = Text("     " + "".join(f"{h:<3}" if h % 3 == 0 else "   " for h in range(24)) + "\n",
                style=MUTED)
    for wd, row in enumerate(punch):
        text.append(f"{_DAYS[wd]:<5}", style=MUTED)
        for v in row:
            text.append("██ ", style=HEAT[heat_level(v, cuts)])
        text.append(f" {sum(row):>5}\n", style=MUTED)
    return text


def diffstat(commit: Commit, width: int = 30) -> Text:
    """Per-file +/- bars like ``git show --stat``."""
    files = sorted(commit.files, key=lambda f: f.added + f.deleted, reverse=True)
    peak = max((f.added + f.deleted for f in files), default=0)
    path_w = min(60, max((len(f.path) for f in files), default=10))
    text = Text()
    for f in files:
        path = f.path if len(f.path) <= path_w else "…" + f.path[-(path_w - 1):]
        text.append(f"{path:<{path_w}} ")
        if f.binary:
            text.append("  bin\n", style=MUTED)
            continue
        total = f.added + f.deleted
        n = max(1, round(total / peak * width)) if peak and total else 0
        plus = round(n * f.added / total) if total else 0
        text.append(f"{total:>6} ", style=MUTED)
        text.append("+" * plus, style=ADD)
        text.append("-" * (n - plus), style=DEL)
        text.append("\n")
    return text
