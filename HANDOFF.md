# Laundry League handoff

Everything needed to pick up The Laundry League on a new computer.
Updated October 20, 2026, after the switch to a 6-team head-to-head format with a waiver wire.

## At a glance

| Item | Value |
|---|---|
| Live site (share this) | https://matthewpilnik-droid.github.io/laundry-league/ |
| Code and data | https://github.com/matthewpilnik-droid/laundry-league |
| GitHub account | `matthewpilnik-droid`: personal account only, never a firm account |
| Commit email | `345613117+matthewpilnik-droid@users.noreply.github.com` (GitHub's no-reply address) |
| Format | 6 teams, 2 crews each, both count; head-to-head Weeks 8–17 (everyone plays everyone twice); Week 18 playoffs: Laundry Bowl (1 v 2), third place (3 v 4), Laundry Basket (5 v 6); 5 undrafted crews form the waiver wire |
| League starts | Week 8, Thursday, October 29, 2026 |
| Status | Live in **preview mode**: draft not yet entered in `league.json` |

The site updates itself. Nothing has to run on your computer. A new computer
only matters for editing code or running Claude Code against the project.

## Commissioner tasks (no computer setup needed)

Everything below works in a web browser on github.com, signed in as `matthewpilnik-droid`.

- **Enter the draft:** open `league.json` → pencil icon → fill each team's `name`,
  `manager` and 2 `crews` (referee last names are fine, e.g. `"Hochuli"`) →
  **Commit changes**. The page switches to real standings within a few minutes.
- **Waiver claims:** owners text "add X, drop Y" by Wednesday 9 p.m. ET; worst record
  wins ties. Add one line per approved claim to `moves` in `league.json`, e.g.
  `{ "week": 9, "team": "Holding Pattern", "add": "Eck", "drop": "Novak" }`.
  Each week keeps the roster it had, so moves never change past results.
  Expect about 1–3 a week, mostly crews with no game that week.
- **Crew assignments:** https://www.footballzebras.com/category/assignments/
- **Bad name or illegal move:** the update fails, and GitHub emails you an error naming
  the line and listing valid names.
- **Scores look stale:** the page header shows "updated <time>". If it's more than a day old,
  go to **Actions** → **Update scores** → **Run workflow**. If GitHub paused the schedule,
  click **Enable workflow** there.

## Setting up a new computer

1. **Install git**, which comes with Apple's command-line tools (`xcode-select --install`).
2. **Install the GitHub command-line tool (`gh`)**, using Homebrew (`brew install gh`) or the
   official download at https://github.com/cli/cli/releases. If downloading by hand,
   check the file against the release's `checksums.txt`.
3. **Sign in, including the workflow permission** (needed to push changes to the
   automation file):
   ```
   gh auth login --hostname github.com --git-protocol https --web --scopes workflow
   ```
   Check that the browser shows `matthewpilnik-droid` before approving the code.
4. **Get the project:**
   ```
   gh repo clone matthewpilnik-droid/laundry-league
   cd laundry-league
   git config user.name "matthewpilnik-droid"
   git config user.email "345613117+matthewpilnik-droid@users.noreply.github.com"
   gh auth setup-git
   ```
   `gh auth setup-git` lets git use the `gh` sign-in. On a work computer, set the
   name, email and sign-in for this project only, never globally.
5. **Optional: run it locally.** It uses Python 3 only, with no extra packages:
   ```
   python3 -I scripts/fetch_data.py cache
   python3 -I scripts/build_data.py cache data.json
   python3 -I scripts/render.py
   ```
   Then open `index.html` in a browser. The `cache/` folder is ignored by git.

## Retiring the old Mac

The old Mac has a `gh` sign-in for `matthewpilnik-droid`. To remove it:

- `gh auth logout --hostname github.com`
- Delete the program: `rm ~/.local/bin/gh`
- Optionally revoke the sign-in on github.com: **Settings** → **Applications** →
  **Authorized OAuth Apps** → GitHub CLI.
- The project folder was `~/CODEDEVELOPER/laundry-league/`. Everything in it is also on GitHub.

## Open items

- **Friday, October 23 check:** after Thursday's NE @ CHI game, confirm two things not yet
  seen in practice:
  1. The update job can reach ESPN from GitHub's servers to look up referees. No lookup
     has been needed yet, because all 93 completed games' referees came from saved data. If ESPN
     blocks it, the fallback is the nflverse schedule's referee column, which runs about
     3 weeks behind.
  2. Whether ESPN lists the officials *during* a live game. If not, live cards show
     "Crew not posted yet" until the next update.
  Check in **Actions** → latest **Update scores** run → log line `referees: N games known, N added`.
- **Confirm assignment timing.** The waiver wire depends on owners seeing which crews
  are off before Thursday. Football Zebras posted 2018 Week 7 assignments on the Tuesday
  and 2026 preseason assignments two days ahead; a 2026 regular-season post wasn't found
  in search. Check that Week 7 or 8 assignments appear before Thursday's game.
- **GitHub's 60-day pause rule.** GitHub disables scheduled jobs in public projects with
  "no repository activity" for 60 days and doesn't define activity. Each run commits an
  update (about 4 a day), which most likely counts. The page's "updated" time shows a stall.
- **ESPN's feed is undocumented** and can change without notice. Live points are
  provisional. In testing, 13 of 14 Week 6 games matched the official scores exactly. One
  (CAR @ PHI) was 14 points low live, because ESPN's live play-by-play was missing a taunting flag and
  marked one delay of game differently. The next scheduled update replaces live numbers.

## How it works

| File | Role |
|---|---|
| `league.json` | League settings and rosters, the only file the commissioner edits |
| `scripts/fetch_data.py` | Downloads the nflverse schedule and play-by-play; fills missing referees from ESPN into `data/referees.json` |
| `scripts/build_data.py` | Reads every penalty from the play text, scores it, replays `moves` week by week, runs the head-to-head schedule, standings, waiver order and weekly awards, writes `data.json` |
| `scripts/render.py` | Puts `data.json` inside `site/template.html` and writes `index.html` |
| `site/template.html` | Page design, plus the live scorer that reads ESPN in each viewer's browser |
| `.github/workflows/update.yml` | Runs the three scripts every 6 hours (at 17 minutes past 00, 06, 12 and 18 UTC), on edits to `league.json`, `site/` or `scripts/`, and on demand |

**Scoring:**
- **Base:** 2 points per flag, plus 1 point per 5 penalty yards (0.2 per yard). A 10-yard hold is worth 4 points.
- **Rare calls:** +4 uncommon, +10 rare, +20 unicorn.
- **Other bonuses:** +20 for an ejection; +6 when a flag wipes out a touchdown.
- **Multipliers:** ×2 for offsetting penalties; ×1.5 in the last 2:00 of either half. Multipliers stack.
- **Tiers:** set from how often each foul was called in the previous season: 0.1–0.3 a game is uncommon, 0.02–0.1 rare, under 0.02 unicorn.
- **Benchmarks:** an average crew game scored 75.0 points in 2025 (15.2 flags), and 85.5 points through Week 6 of 2026.

**Lessons from the build:**
- The nflverse `penalty` column records only one foul per play, and records offsetting
  penalties as no penalty. Scoring has to parse the play description text, which it does.
- ESPN and nflverse spell some referee names differently ("Ronald" vs. "Ron" Torbert).
  The build maps ESPN names to nflverse spellings by unambiguous last name.
  Commissioner entries in `league.json` are strict: full name or last name only.
- The nflverse schedule's `referee` column is filled in by hand and runs about 3 weeks behind;
  ESPN's game summary lists officials the same night.

## For Claude Code on the new computer

Claude's memory notes stay on the old Mac. To restore context, start a session in the
project folder and paste:

> Read HANDOFF.md in this repo. This is my Laundry League project. Save a project memory
> that it publishes only from my personal GitHub account `matthewpilnik-droid`, never a
> firm account; check `gh auth status` before any push; set git name and email per repo
> using the no-reply address in HANDOFF.md.
