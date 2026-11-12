# Laundry League handoff

Everything needed to pick up The Laundry League on a new computer.
Updated November 5, 2026: the league is live. The draft is entered, Week 8 is scored and final, and Week 9 is under way. Two open items are closed (ESPN referee lookups, assignment timing). New: score drill-down. Tap a crew's score in a matchup or a past result to see every flag and review behind it, with live (provisional) lists during games.

## At a glance

| Item | Value |
|---|---|
| Live site (share this) | https://matthewpilnik-droid.github.io/laundry-league/ |
| Code and data | https://github.com/matthewpilnik-droid/laundry-league |
| GitHub account | `matthewpilnik-droid`: personal account only, never a firm account |
| Commit email | `345613117+matthewpilnik-droid@users.noreply.github.com` (GitHub's no-reply address) |
| Format | 6 teams, 3 crews each from a 3-round snake draft of all 17 crews + the 2012 Replacement Refs (scores the weekly average of crews that worked); start 2 of 3 each week, lineups carry forward; head-to-head Weeks 8–17, everyone plays everyone twice; Week 18 playoffs: Laundry Bowl (1 v 2), third place (3 v 4), Delicates Bowl (5 v 6) |
| League starts | Week 8, Thursday, October 29, 2026 |
| Status | **Live** (2026-11-05): draft entered 2026-10-26; Week 8 scored and final; real standings showing |
| Draft order | 1 Bryan, 2 Matthew, 3 Mike, 4 Stephan, 5 Sean, 6 Danny (Zebra Crime Syndicate) (set by the commissioner 2026-10-26); 3-round snake |

The site updates itself. Nothing has to run on your computer. A new computer
only matters for editing code or running Claude Code against the project.

## Commissioner tasks (no computer setup needed)

Everything below works in a web browser on github.com, signed in as `matthewpilnik-droid`.
Easiest: the commissioner page, https://matthewpilnik-droid.github.io/laundry-league/commish.html
(added 2026-10-21), builds `league.json` for the draft and weekly lineups; copy, paste into GitHub's editor, commit.

- **Enter the draft:** open `league.json` → pencil icon → fill each team's `name`,
  `manager` and 3 `crews` in draft order (referee last names are fine, e.g. `"Hochuli"`;
  the fake crew is `"Replacement Refs"`) →
  **Commit changes**. The page switches to real standings within a few minutes.
- **Lineups:** owners text their 2 starters by Thursday kickoff. Add a line to `lineups`
  in `league.json` only when a team changes, e.g.
  `{ "week": 9, "team": "Holding Pattern", "start": ["Hochuli", "Replacement Refs"] }`.
  A lineup stands until replaced; before any entry a team starts its first 2 listed crews.
  There is no waiver wire: all 18 picks are drafted.
- **Crew assignments:** https://www.footballzebras.com/category/assignments/
- **Off this week (added 2026-10-26):** once Football Zebras posts the week's assignments (usually
  Tuesday or Wednesday), open the commissioner page → **Lineups** → pick the week → tick every crew
  whose referee isn't assigned → Copy → commit. It saves under `off` in `league.json`, e.g.
  `"off": {"8": ["Ron Torbert", "Alex Kemp"]}`. The league page shows the list to everyone,
  tags off crews in every lineup, and warns an owner who is starting one.
- **Bad name or illegal lineup:** the update fails, and GitHub emails you an error naming
  the line and listing valid names.
- **Scores look stale:** the page header shows "updated <time>". If it's more than a day old,
  go to **Actions** → **Update scores** → **Run workflow**. If GitHub paused the schedule,
  click **Enable workflow** there.
- **Week on hold (added 2026-11-12):** if a finished game's referee isn't known, its week is held
  (nothing in it counts), the page says so, and GitHub emails you each run until it clears.
  It usually clears by itself; see README → "If a week is on hold" for the manual fix.
- **Final weeks are locked** on the commissioner page (added 2026-11-12); tick "Unlock to correct
  this week" only to fix a genuine mistake, since it rewrites that week's result.
- **Game fixes (added 2026-11-12):** commissioner page → Lineups → Game fixes. "Counts for crew"
  credits a game to a crew when the data shows a substitute referee or an unmatched spelling (also
  how to clear a week on hold); "Cancelled" gives the assigned crew 85% of the weekly average
  (decided 2026-11-12: "bad luck is bad luck", same as open spots). Saved under `game_fixes`.
  Not handled: a game moved to a different week; see README → "Game fixes".

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

## New season checklist (written 2026-11-12, for 2027)

Do this in the summer, before the draft, on a branch, and rehearse it locally before going live.
None of it should be changed mid-season.

1. **Fix the page crashes known to hit a new season** (`site/template.html`, found 2026-11-12):
   - Before Week 1 is played there are no scored games, and the page's header code expects one
     (`D.week_games[0]`, and `D.top_flags` for the scoring example), so most of the page goes blank.
   - A newly promoted referee has no stats from last season, and the draft board calls
     `.toFixed()` on that empty value, which stops everything drawn after it, including live scoring.
2. **Check the draft pool.** Until the new season's first games are scored, the draftable crews
   are last season's referees. Retired referees would still be listed and new ones missing, so
   compare against the NFL's announced crews (Football Zebras posts them) before drafting.
3. **Reset `league.json`:** `season`, `start_week`, `regular_season_end`, `playoff_week`; empty
   each team's `crews` (the page switches to preview mode); clear `lineups` and `off`.
4. **Check the data downloads.** `fetch_data.py` downloads the new season's play-by-play file
   from nflverse. Confirm it exists before switching `season`; if it doesn't yet, the update
   job fails until it does.
5. **Small clean-up:** sort the `ref_last_names` list in `build_data.py`. Its order is random
   today, so the robot commits a change every run even when no score changed.
6. **Rehearse:** run the three local test commands, open `index.html`, and check that preview
   mode, the draft board and the commissioner page all work before pushing.
7. **Match Python versions** on the laptop and in `.github/workflows/update.yml` (see CLAUDE.md).
8. Tiers recalibrate automatically from the previous season; nothing to do.

## Open items

- **Live crews:** check whether ESPN lists the officials *during* a live game. If not, live
  cards show "Crew not posted yet" until the next update. Watch a live card during a game.
  (Referee lookups from ESPN after games are confirmed working, using ESPN's spellings,
  e.g. "Ronald Torbert". Check in **Actions** → latest **Update scores** run → log line
  `referees: N games known, N added`.)
- **Assignment timing** (confirmed): Football Zebras posts assignments about two days before
  Thursday's game, at `footballzebras.com/2026/<month>/week-<N>-referee-assignments-2026/`.
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
| `scripts/build_data.py` | Reads every penalty from the play text, scores it, scores the Replacement Refs' weekly average, replays `lineups` week by week, runs the head-to-head schedule, standings and weekly awards, writes `data.json`. Since 2026-11-05 it also writes `ledger`: every scoring line per league-week game. The build stops if a game's lines don't add up to its score |
| `scripts/render.py` | Puts `data.json` inside `site/template.html` and writes `index.html` |
| `site/template.html` | Page design, plus the live scorer that reads ESPN in each viewer's browser, and the tap-to-expand score drill-down (official lines from `ledger`, live lines from the live scorer) |
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
