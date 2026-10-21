# The Laundry League

Fantasy football where you draft NFL officiating crews. Every flag scores.

The site is one page (`index.html`) that rebuilds itself every 6 hours from
free NFL data. During games it also shows live, provisional points straight
from ESPN in each viewer's browser.

## Commissioner guide

### Enter the draft (once)

1. On GitHub, open `league.json` and click the pencil (Edit).
2. For each team, fill in `name`, `manager`, and exactly 3 `crews`.
   A crew is named by its referee, e.g. `"Shawn Hochuli"` or just `"Hochuli"`.
3. Click **Commit changes**. The site rebuilds within a few minutes.

If a name is misspelled or a crew is drafted twice, the update fails and
GitHub emails you. The error lists every valid crew name.

```json
{ "name": "Holding Pattern", "manager": "Sam", "crews": ["Hochuli", "Novak", "Cheffers"] }
```

### Trades or swaps

Edit the `crews` lists in `league.json` the same way. Past weeks are
recalculated with the new rosters, so make swaps between weeks and tell the
league what changed.

### If scores stop updating

The page shows "updated <time>" at the top. If that is more than a day old:

- **Actions** tab → **Update scores** → **Run workflow** to run it now.
- If GitHub has paused the schedule (it does this to public projects with no
  activity for 60 days), the Actions tab shows an **Enable workflow** button.

## Scoring

| Item | Points |
|---|---|
| Each flag (accepted, declined, offsetting) | 2 |
| Penalty yards | 1 per 5 yards (0.2 per yard) |
| Uncommon / rare / unicorn call | +4 / +10 / +20 |
| Ejection | +20 |
| Flag wipes out a touchdown | +6 |
| Offsetting penalties | ×2 |
| Last 2:00 of either half | ×1.5 |

Tiers come from how often each foul was called the previous season:
0.1–0.3 per game is uncommon, 0.02–0.1 rare, under 0.02 unicorn. Each week a
team's best 2 of 3 crew scores count. Most points after Week 18 wins.

## How it works

| File | Role |
|---|---|
| `league.json` | Commissioner settings and rosters. The only file you edit. |
| `scripts/fetch_data.py` | Downloads the nflverse schedule and play-by-play; fills missing referees from ESPN into `data/referees.json`. |
| `scripts/build_data.py` | Parses every penalty from the play text, scores it, builds `data.json`. |
| `scripts/render.py` | Inlines `data.json` into `site/template.html` → `index.html`. |
| `.github/workflows/update.yml` | Runs the three scripts every 6 hours and publishes changes. |

Run locally: `python3 -I scripts/fetch_data.py cache && python3 -I scripts/build_data.py cache data.json && python3 -I scripts/render.py`

Data: [nflverse](https://github.com/nflverse) play-by-play and schedules;
ESPN's public game feed for officials and live play-by-play. ESPN's feed is
undocumented and can change; live numbers are provisional and the next
scheduled update replaces them with official ones. Not affiliated with the NFL.
