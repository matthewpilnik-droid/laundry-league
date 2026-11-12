# The Laundry League

Fantasy football where you draft NFL officiating crews. Six owners, three crews
each, two start every week, head-to-head. Every flag scores.

The site is one page (`index.html`) that rebuilds itself every 6 hours from
free NFL data. During games it also shows live, provisional points straight
from ESPN in each viewer's browser.

## League format

- 6 teams, 3 crews each, from a three-round snake draft. The 18 picks are all
  17 real crews plus the **2012 Replacement Refs**, who never have a week off
  and score the average of every real crew that worked that week (posted once
  the week is final).
- Each week a team starts 2 of its 3 crews; only starters score. A crew with no
  game that week scores 0, so bench it.
- **Open spot:** if a team has fewer than 2 crews with a game in a week, each
  starting spot it can't fill scores 85% of that week's average crew score (the
  same average the Replacement Refs get; they still get 100%). It posts when the
  week is final. If the team had a working crew on the bench and started an idle
  one instead, that spot still scores 0. The 85% is the `open_spot_pct` setting
  in `league.json`; change that one number to adjust it (0 turns the rule off).
- Weeks 8–17: head-to-head, everyone plays everyone twice.
- Draft order: Bryan, Matthew, Mike, Stephan, Sean, Danny.
  `league.json` lists the teams in that order; the site's draft board reads it.
- Week 18: Laundry Bowl (1st vs 2nd), third-place game (3rd vs 4th) and the
  Delicates Bowl (5th vs 6th). Seeds come from the Week 17 standings.
- Standings: win–loss record, ties broken by total points scored.

## Commissioner guide

The easy way: open the **commissioner page**
(https://matthewpilnik-droid.github.io/laundry-league/commish.html, also linked at the bottom of
the league page). Enter the draft or tick each week's starters, click **Copy**, then **Open
GitHub editor**, paste over everything and **Commit changes**. It checks your entries first and
never saves anything by itself. The steps below are the same edits done by hand.

### Enter the draft (once)

1. On GitHub, open `league.json` and click the pencil (Edit).
2. For each team, fill in `name`, `manager`, and exactly 3 `crews`, in draft
   order. A crew is named by its referee, e.g. `"Shawn Hochuli"` or just
   `"Hochuli"`. The fake crew is `"2012 Replacement Refs"` (or just
   `"Replacement Refs"`).
3. Click **Commit changes**. The site rebuilds within a few minutes.

```json
{ "name": "Holding Pattern", "manager": "Sam", "crews": ["Hochuli", "Novak", "Replacement Refs"] }
```

Until someone sends a lineup, a team starts the first 2 crews listed.

### Lineups (weekly)

Owners text you their 2 starters by the deadline (`lineup_deadline`, default
Thursday kickoff). Add one line to the `lineups` list, with the first week it
applies. A lineup stands until that team sends a new one, so only add a line
when someone changes:

```json
"lineups": [
  { "week": 9, "team": "Holding Pattern", "start": ["Hochuli", "Replacement Refs"] }
]
```

Each week keeps the lineup it had, so a new line never alters a past result. A line dated to a
week that's already final does rewrite that week's result, so the commissioner page locks final
weeks; tick **Unlock to correct this week** only to fix a genuine mistake. It then marks the
change with a ⚠ warning.

The commissioner page reads `league.json` straight from GitHub, so a change you saved a minute
ago is already there. If it can't (GitHub allows 60 of these reads an hour per internet
connection), it uses the live site's copy and says so; that copy can be a minute or two behind,
so wait 2 minutes and reload before making another change.
Weekly crew assignments: https://www.footballzebras.com/category/assignments/

If a name is misspelled, a crew is drafted twice, or a lineup lists a crew the
team doesn't have (or not exactly 2 different crews), the update fails and
GitHub emails you. The error says which line and lists the valid names.

### If scores stop updating

The page shows "updated <time>" at the top. If that is more than a day old:

- **Actions** tab → **Update scores** → **Run workflow** to run it now.
- If GitHub has paused the schedule (it does this to public projects with no
  activity for 60 days), the Actions tab shows an **Enable workflow** button.

### If a week is "on hold"

A crew is scored through its referee, so a finished game whose referee isn't known (or doesn't
match a drafted crew) can't be credited. Rather than score that crew as off, the whole week is
put on hold: no result in it counts, the league page says which game is waiting, and the update
run is marked failed after publishing, so GitHub emails you (every run, about 4 a day, until it
clears). Usually ESPN lists the referee by the next run and the week finishes by itself.

If it's still on hold after a day: check the referee for that game (Football Zebras or the game's
ESPN page), add a line to `data/referees.json` such as `"2026_09_HOU_LAC": "Alex Moore"`, commit,
then **Actions** → **Update scores** → **Run workflow**. That works while the NFL data source has
no referee listed for the game. If the email says the referee "doesn't match a drafted crew"
(a misspelling, or a substitute referee working a crew's game), it needs a code or settings fix.

Each week, after Football Zebras posts assignments, tick the crews with no game under **Off this
week** on the commissioner page's Lineups tab. The league page lists them for everyone and flags
any owner starting one.

## Scoring

| Item | Points |
|---|---|
| Each flag (accepted, declined, offsetting) | 2 |
| Penalty yards | 1 per 5 yards (0.2 per yard) |
| Uncommon / rare / unicorn call | +4 / +10 / +20 |
| Ejection | +20 |
| Flag wipes out a touchdown | +6 |
| Call overturned: ruling reversed by a coach's challenge or replay review, or a flag picked up after replay help (no multipliers) | −5 |
| Stood tall: a coach's challenge of the crew's ruling fails (booth reviews don't count; no multipliers) | +3 |
| Offsetting penalties | ×2 |
| Last 2:00 of either half | ×1.5 |
| Open spot (fewer than 2 crews with a game that week) | 85% of the week's average crew score (`open_spot_pct`) |

Tiers come from how often each foul was called the previous season:
0.1–0.3 per game is uncommon, 0.02–0.1 rare, under 0.02 unicorn.

## How it works

| File | Role |
|---|---|
| `league.json` | Commissioner settings, draft rosters and weekly lineups. The only file you edit. |
| `commish.html` | Commissioner page: reads the live `league.json` and `data.json`, builds an updated `league.json` to paste into GitHub. Hand-written; not generated. |
| `scripts/fetch_data.py` | Downloads the nflverse schedule and play-by-play; fills missing referees from ESPN into `data/referees.json`. |
| `scripts/build_data.py` | Parses every penalty from the play text, scores it, scores the Replacement Refs' weekly average, applies lineups, runs the head-to-head schedule, standings and awards, builds `data.json`. |
| `scripts/render.py` | Inlines `data.json` into `site/template.html` → `index.html`. |
| `.github/workflows/update.yml` | Runs the three scripts every 6 hours and publishes changes. |

Run locally: `python3 -I scripts/fetch_data.py cache && python3 -I scripts/build_data.py cache data.json && python3 -I scripts/render.py`

Data: [nflverse](https://github.com/nflverse) play-by-play and schedules;
ESPN's public game feed for officials and live play-by-play. ESPN's feed is
undocumented and can change; live numbers are provisional and the next
scheduled update replaces them with official ones. Not affiliated with the NFL.
