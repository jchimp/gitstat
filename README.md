# gitstat

**How much work went into this repo?** Point `gitstat` at any git repository, local or
remote, and it tells you:

- how many hours you spent (estimated)
- how many days you coded, and your longest streak
- how many commits and lines you added or deleted
- which months were busiest, and what hours of the week you work
- which files and folders took the most effort
- when the big moments happened: tags, merges, features, large commits

You can explore it all in the terminal, or export a single HTML page to share.

## What you get

**A terminal dashboard** (built with [Textual](https://textual.textualize.io/)) with
five tabs:

| Tab | What it shows |
|---|---|
| **Overview** | Headline numbers, a GitHub-style activity grid, hours per month |
| **Charts** | Commits per month, lines added vs. deleted, a weekday × hour heatmap |
| **Months** | One row per month. Press Enter to jump to that month's commits |
| **Files** | The folders and files that changed most. Click a header to sort |
| **Timeline** | Scroll through every commit, grouped by day and work session, with a per-file diffstat |

**An HTML report** in one file with no internet needed. It has interactive charts with
hover details, a months table that opens into commits and then files, search, and
sortable tables. It follows your light or dark theme.

**CSV files** (commits, months, files, sessions) for spreadsheets or your own scripts.

Press `e` in the dashboard, or pass `--export`, and gitstat saves all of these to
`reports/<repo>/`.

## Install

You need **Python 3.12+** and **git** on your PATH.

```bash
# with uv (recommended)
uv tool install git+https://github.com/jchimp/gitstat

# or with pipx
pipx install git+https://github.com/jchimp/gitstat
```

## Quick start

```bash
cd my-project
gitstat
```

By default, gitstat counts **your** commits only. It finds you with
`git config user.email`.

## More examples

```bash
gitstat ../other-repo                     # any local repo
gitstat https://github.com/owner/repo     # a remote repo (cloned to a cache first)
gitstat --all-authors                     # count everyone
gitstat --author alice --author bob@      # match parts of names or emails
gitstat --since 2026-01-01                # limit the date range
gitstat --since "3 months ago" --until "1 week ago"

# No dashboard: print a summary and write the reports to reports/<repo>/
gitstat --no-tui --export
gitstat --no-tui --export --out ~/gitstat-reports
```

Example `--no-tui` output:

```
myproject  (me@example.com)
  span          2026-08-12 to 2026-09-21
  est. hours    29.4  (11 sessions)
  coding days   9  (longest streak 3)
  commits       121
  lines         +16,815 / -543
  busiest       2026-08 (18 h), 2026-09 (11 h)
  top dirs      client/ (7,950), server/ (7,181), (root) (1,513)
```

## Keys in the dashboard

| Key | Action |
|---|---|
| `1` – `5` | Switch tabs |
| `↑` `↓` | Move through rows |
| `Enter` (Months tab) | Jump to that month in the Timeline |
| `m` | Timeline: show milestones only (◆ tag, ⑂ merge, ★ feat, ▲ big) |
| `e` | Export the HTML report and CSV files |
| `q` | Quit |

## Where reports go

All exports go into one folder, `reports/` by default, with a subfolder for each repo:

```
reports/
  my-project/
    report.html     # the interactive dashboard
    commits.csv     # one row per commit
    monthly.csv     # one row per month
    files.csv       # one row per file
    sessions.csv    # one row per work session
  other-repo/
    ...
```

`reports/` is relative to the folder you run gitstat from. Use `--out DIR` to pick a
different folder. Exporting again replaces the files for that repo.

## All options

| Option | Default | Meaning |
|---|---|---|
| `REPO` | `.` | Path or URL of the repo |
| `--author PATTERN` | your `user.email` | Only count authors whose name or email contains this. Repeatable |
| `--all-authors` | off | Count every author |
| `--since DATE`, `--until DATE` | all time | Any date git understands |
| `--session-gap MIN` | `120` | Max minutes between commits in one work session |
| `--first-commit MIN` | `120` | Minutes credited for work before a session's first commit |
| `--export` | off | Write the HTML report and CSV files when gitstat starts |
| `--out DIR` | `reports` | Folder for exports. Files go in `DIR/<repo>/` |
| `--no-tui` | off | Print a summary instead of opening the dashboard |
| `--no-fetch` | off | For URLs: use the cached copy without updating it |

## How the numbers are calculated

**Hours are an estimate, not a timesheet.** gitstat uses the same method as
[git-hours](https://github.com/kimmobrunfeldt/git-hours):

1. Commits by the same person less than 2 hours apart are one **work session**. The
   time between them counts as work.
2. Each session gets 2 extra hours for the work you did before the first commit, which
   git cannot see.

If you commit often, the estimate is close. If you commit once a day, it is low. Use
`--session-gap` and `--first-commit` to tune it for how you work.

Other details:

- **Lines** come from `git log --numstat` across all branches. Merge commits add no
  lines, so nothing is counted twice. Binary files count as changed, with 0 lines.
- **Days and hours** use the time zone of each commit, so a commit at 11 pm your time
  counts on your day.
- **Milestones** are tags, merges, `feat:` commits, and commits much bigger than usual
  for the repo (more than 500 lines and in the top 5%).
- **Remote URLs** are cloned once into `%LOCALAPPDATA%\gitstat\repos` (Windows) or
  `~/.cache/gitstat/repos` (macOS and Linux), then updated on later runs. Your own
  working copies are never changed.
- If the repo has a `.mailmap`, gitstat uses it, so one person with several emails
  counts once.

## Troubleshooting

**"no commits matched"**: your `user.email` does not match the commits in that repo.
gitstat prints the top authors so you can pick one with `--author`, or use
`--all-authors`.

**Line counts look too high**: generated files such as lock files or build output count
as lines too. Check the Files tab to see what is inflating the numbers.

## Development

```bash
git clone https://github.com/jchimp/gitstat
cd gitstat
uv run pytest          # run the tests
uv run gitstat .       # run from source
```

## License

[MIT](LICENSE)
