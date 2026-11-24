"""Download the lineups players saved in the app (Supabase) so the score build can use them.

Usage: python3 -I scripts/fetch_lineups.py <cache_dir>        (run before build_data.py)

Writes <cache_dir>/lineups_db.json:  {"fetched_at": ..., "entries": [{id, week, team, start, captain, created_at}, ...]}
This script only DOWNLOADS. It does not judge: build_data.py checks every row and skips bad ones.

If anything goes wrong (Supabase down, wrong key, more than one league in the project) it deletes any old
lineups_db.json, prints a warning, and exits with an error. Deleting matters: a stale file must never be mistaken
for fresh data. build_data.py then falls back to the lineups in league.json. Callers (GitHub's bot) should let this
step fail without stopping the score update.

The key is the Supabase SECRET key (read-only use here). It comes from SUPABASE_URL / SUPABASE_SECRET_KEY in the
environment, or from the gitignored local files .env.rehearsal and .env.rehearsal-bot. It is never printed.
Standard library only.
"""
import datetime, json, os, pathlib, sys, urllib.error, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "cache"
OUT = CACHE / "lineups_db.json"
LIMIT = 5000                      # a season is a few hundred rows; hitting this means something is wrong


def config():
    env = dict(os.environ)
    for name in (".env.rehearsal", ".env.rehearsal-bot"):
        p = ROOT / name
        if p.exists():
            for line in p.read_text().splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.split("=", 1)
                    env.setdefault(k.strip(), v.strip())
    url, key = env.get("SUPABASE_URL", "").rstrip("/"), env.get("SUPABASE_SECRET_KEY", "")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL or SUPABASE_SECRET_KEY is not set")
    return url, key


def get(url, key, path):
    req = urllib.request.Request(url + path, headers={"apikey": key, "Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"GET {path.split('?')[0]} failed ({e.code}): {e.read().decode().replace(key, '<key>')[:200]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"could not reach Supabase: {e.reason}")


def fetch():
    url, key = config()
    leagues = get(url, key, "/rest/v1/leagues?select=id,name")
    if len(leagues) != 1:
        raise RuntimeError(f"expected exactly one league in the project, found {len(leagues)}; not guessing which one")
    teams = {t["id"]: t["name"] for t in get(url, key, "/rest/v1/teams?select=id,name&league_id=eq." + leagues[0]["id"])}
    rows = get(url, key, f"/rest/v1/lineups?select=id,team_id,week,starters,captain,created_at&order=id&limit={LIMIT}")
    if len(rows) >= LIMIT:
        raise RuntimeError(f"{len(rows)} lineup rows: more than expected, refusing to read a possibly cut-off list")
    entries = [{"id": r["id"], "week": r["week"], "team": teams.get(r["team_id"], "?unknown team?"),
                "start": r["starters"], "captain": r["captain"], "created_at": r["created_at"]} for r in rows]
    return {"fetched_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "league": leagues[0]["name"], "entries": entries}


if __name__ == "__main__":
    try:
        data = fetch()
    except (RuntimeError, ValueError, KeyError) as e:
        OUT.unlink(missing_ok=True)
        print(f"::warning::lineups: could not read lineups from the app ({e}); build will use league.json")
        sys.exit(1)
    CACHE.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1) + "\n")
    print(f"lineups: {len(data['entries'])} saved lineups read from the app ({data['league']})")
