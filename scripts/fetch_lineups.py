"""Download the lineups players saved in the app (Supabase) so the score build can use them.

Usage: python3 -I scripts/fetch_lineups.py <cache_dir>        (run before build_data.py)

Writes <cache_dir>/lineups_db.json:  {"fetched_at": ..., "entries": [{id, week, team, start, captain, created_at}, ...]}
This script only DOWNLOADS. It does not judge: build_data.py checks every row and skips bad ones.

If anything goes wrong (Supabase down, wrong key, more than one league in the project) it deletes any old
lineups_db.json, prints a warning, and exits with an error. Deleting matters: a stale file must never be mistaken
for fresh data. What build_data.py does next depends on league.json: if `lineups_from_db_week` is NOT set it simply uses
league.json's lineups; if it IS set, the build STOPS so the site keeps its last good results (scoring from league.json alone
could flip published results). Callers (GitHub's bot) should let THIS step fail without stopping, and let the build decide.

The key is the Supabase SECRET key (read-only use here). It comes from SUPABASE_URL / SUPABASE_SECRET_KEY in the
environment, or from the gitignored local files .env.rehearsal and .env.rehearsal-bot. It is never printed.
Standard library only.
"""
import datetime, json, os, pathlib, sys, urllib.error, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "cache"
OUT = CACHE / "lineups_db.json"
PAGE = 1000                       # rows asked for per request. Supabase silently cuts every answer at its own cap (1,000 by default),
                                  # so we never trust one answer to be the whole list: we ask for the total and read until we have it all


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


def get(url, key, path, extra_headers=None, want_headers=False):
    req = urllib.request.Request(url + path, headers={"apikey": key, "Authorization": "Bearer " + key, **(extra_headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.loads(r.read().decode())
            return (body, r.headers) if want_headers else body
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"GET {path.split('?')[0]} failed ({e.code}): {e.read().decode().replace(key, '<key>')[:200]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"could not reach Supabase: {e.reason}")


def get_all(url, key, path):
    """Every row of a list, however long. Asks for a page at a time and for the TOTAL (the Content-Range answer, like
    '0-999/2500'), and keeps going until it holds that many. A server that stops early, or a total that doesn't add up,
    is an error: a cut-off list must never be returned as if it were complete."""
    rows, total = [], None
    while total is None or len(rows) < total:
        page, headers = get(url, key, path, {"Range-Unit": "items", "Range": f"{len(rows)}-{len(rows) + PAGE - 1}", "Prefer": "count=exact"}, True)
        span = headers.get("Content-Range") or ""
        try:
            total = int(span.rsplit("/", 1)[1])
        except (IndexError, ValueError):
            raise RuntimeError(f"the server did not say how many rows there are (Content-Range: {span!r}); not trusting a possibly cut-off list")
        if not page and len(rows) < total:
            raise RuntimeError(f"the list was cut off: got {len(rows)} of {total} rows and the server stopped answering")
        rows += page
    if len(rows) != total:
        raise RuntimeError(f"the list is incomplete or changed while reading: got {len(rows)}, expected {total}")
    ids = [r.get("id") for r in rows]
    if ids != sorted(set(ids)):
        raise RuntimeError("the rows came back out of order or repeated; not trusting the list")
    return rows


def fetch():
    url, key = config()
    leagues = get(url, key, "/rest/v1/leagues?select=id,name")
    if len(leagues) != 1:
        raise RuntimeError(f"expected exactly one league in the project, found {len(leagues)}; not guessing which one")
    teams = {t["id"]: t["name"] for t in get(url, key, "/rest/v1/teams?select=id,name&league_id=eq." + leagues[0]["id"])}
    rows = get_all(url, key, "/rest/v1/lineups?select=id,team_id,week,starters,captain,created_at&order=id")
    entries = [{"id": r["id"], "week": r["week"], "team": teams.get(r["team_id"], "?unknown team?"),
                "start": r["starters"], "captain": r["captain"], "created_at": r["created_at"]} for r in rows]
    return {"fetched_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "league": leagues[0]["name"], "entries": entries}


if __name__ == "__main__":
    try:
        data = fetch()
    except (RuntimeError, ValueError, KeyError) as e:
        OUT.unlink(missing_ok=True)
        print(f"::warning::lineups: could not read lineups from the app ({e}); if lineups_from_db_week is set the build will stop and keep the last good results, otherwise it uses league.json")
        sys.exit(1)
    CACHE.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1) + "\n")
    print(f"lineups: {len(data['entries'])} saved lineups read from the app ({data['league']})")
