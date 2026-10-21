"""Download everything build_data.py needs.

Usage: python3 -I scripts/fetch_data.py <cache_dir>

Writes into <cache_dir>:
  games.csv              nflverse schedule (all seasons)
  pbp<season-1>.csv.gz   calibration season play-by-play
  pbp<season>.csv.gz     current season play-by-play
Updates data/referees.json (committed) with the referee for every completed
current-season game, filled from the schedule or, when the schedule lags,
from ESPN's game summary.
"""
import csv, json, pathlib, sys, time, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = pathlib.Path(sys.argv[1])
CACHE.mkdir(parents=True, exist_ok=True)
SEASON = json.loads((ROOT / "league.json").read_text())["season"]

GAMES_URL = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"
PBP_URL = "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{}.csv.gz"
ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={}"
UA = {"User-Agent": "laundry-league/1.0 (fantasy league for friends)"}


def get(url, dest=None, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                body = r.read()
            if dest:
                pathlib.Path(dest).write_bytes(body)
            return body
        except Exception as e:  # network hiccup: back off and retry
            if i == tries - 1:
                raise
            print("retry", url, e)
            time.sleep(5 * (i + 1))


get(GAMES_URL, CACHE / "games.csv")
for season in (SEASON - 1, SEASON):
    get(PBP_URL.format(season), CACHE / f"pbp{season}.csv.gz")
print("downloaded schedule and play-by-play")

ref_path = ROOT / "data" / "referees.json"
ref_path.parent.mkdir(exist_ok=True)
refs = json.loads(ref_path.read_text()) if ref_path.exists() else {}

added = 0
for g in csv.DictReader(open(CACHE / "games.csv")):
    if g["season"] != str(SEASON) or g["game_type"] != "REG" or not g["home_score"]:
        continue
    gid = g["game_id"]
    if g["referee"]:
        if refs.get(gid) != g["referee"]:
            refs[gid] = g["referee"]
            added += 1
        continue
    if gid in refs or not g["espn"]:
        continue
    try:
        d = json.loads(get(ESPN_URL.format(g["espn"])))
    except Exception as e:
        print("ESPN lookup failed for", gid, e)
        continue
    offs = (d.get("gameInfo") or {}).get("officials") or []
    ref = next((o["displayName"] for o in offs
                if o.get("position", {}).get("name") == "Referee"), "")
    if ref:
        refs[gid] = ref
        added += 1
    time.sleep(0.5)  # be polite to ESPN

ref_path.write_text(json.dumps(dict(sorted(refs.items())), indent=1) + "\n")
print(f"referees: {len(refs)} games known, {added} added or corrected")
