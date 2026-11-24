"""Feed the lineup lock: copy each week's schedule and each crew's kickoff time into Supabase.

Usage:
    python3 -I scripts/sync_supabase.py            # DRY RUN: prints what it would write, writes nothing
    python3 -I scripts/sync_supabase.py --apply    # really writes (rows in `weeks`, `game_slots`, `sync_status`)

Run it AFTER build_data.py: it reads the finished data.json, so the lock sees exactly what the page shows
(ESPN kickoff times, actual or provisional referee, the commissioner's game fixes).

Why it exists: the database enforces "a crew locks at its own kickoff" using the SERVER's clock, but the
database doesn't know the NFL schedule. This script tells it. It writes with the Supabase SECRET key, the only
key allowed to write these tables.

Where the key comes from (it is never printed, never in git):
  * environment variables SUPABASE_URL and SUPABASE_SECRET_KEY (how GitHub's bot will get them, step 7), or
  * gitignored local files .env.rehearsal (SUPABASE_URL) and .env.rehearsal-bot (SUPABASE_SECRET_KEY).

Safety rules built in:
  * Upserts first, then deletes stale rows, so there is never a moment with no rows for a week.
  * Never deletes a week's rows if the new list for that week is empty (a bad read must not wipe the lock).
  * The heartbeat (`sync_status`) is stamped only after every write succeeded.
  * Standard library only. Exits non-zero on failure so a caller can notice; callers should not let that stop scoring.
"""
import datetime, json, os, pathlib, sys, urllib.error, urllib.request, zoneinfo

ROOT = pathlib.Path(__file__).resolve().parent.parent
ET = zoneinfo.ZoneInfo("America/New_York")
END_PAD = datetime.timedelta(days=1)       # a week "ends" a day after its last kickoff


def build_rows(data):
    """Pure function: data.json (as a dict) -> (weeks_rows, slot_rows, warnings). No network."""
    season = data["season"]
    fixes = data.get("game_fixes", {})
    assign = data.get("assignments", {})
    weeks, slots, warns = [], [], []
    for wk, games in sorted(data.get("schedule", {}).items(), key=lambda kv: int(kv[0])):
        w = int(wk)
        kicks, week_slots, seen = [], {}, {}
        for g in games:
            gid, fix = g["gid"], fixes.get(g["gid"], {})
            if "cancelled" in fix or not g.get("date") or not g.get("time"):
                continue                                   # cancelled, or no kickoff known: nothing to lock on
            try:
                t = datetime.datetime.fromisoformat(f"{g['date']}T{g['time']}").replace(tzinfo=ET)
            except ValueError:
                warns.append(f"Week {w}: {gid} has an unreadable kickoff ({g['date']} {g['time']}); skipped")
                continue
            t = t.astimezone(datetime.timezone.utc)
            kicks.append(t)
            crew = fix.get("crew") or g.get("referee") or assign.get(wk, {}).get("games", {}).get(gid)
            if not crew:
                continue                                   # referee not known yet (normal early in the week)
            if crew in seen:
                warns.append(f"Week {w}: {crew} appears in two games ({seen[crew]} and {gid}); keeping the earlier kickoff")
                if t >= week_slots[crew]:
                    continue
            seen[crew] = gid
            week_slots[crew] = t
        if not kicks:
            continue                                       # no schedule for this week: no `weeks` row (managers stay locked out)
        weeks.append({"season": season, "week": w, "starts_at": min(kicks).isoformat(),
                      "ends_at": (max(kicks) + END_PAD).isoformat()})
        slots += [{"season": season, "week": w, "crew": c, "kickoff_at": t.isoformat()}
                  for c, t in sorted(week_slots.items())]
    return weeks, slots, warns


def load_config():
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
        sys.exit("Missing SUPABASE_URL or SUPABASE_SECRET_KEY (see supabase/tests/README.md and .env.rehearsal-bot).")
    return url, key


class Api:
    def __init__(self, url, key):
        self.url, self.key = url, key

    def call(self, method, path, body=None, prefer=None):
        h = {"apikey": self.key, "Authorization": "Bearer " + self.key, "Content-Type": "application/json"}
        if prefer:
            h["Prefer"] = prefer
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                text = r.read().decode()
                return json.loads(text) if text else None
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{method} {path.split('?')[0]} failed ({e.code}): {e.read().decode().replace(self.key, '<key>')[:300]}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"could not reach Supabase: {e.reason}")


def main():
    apply = "--apply" in sys.argv[1:]
    data_file = ROOT / "data.json"
    if not data_file.exists():
        sys.exit("data.json not found. Run build_data.py first.")
    weeks, slots, warns = build_rows(json.loads(data_file.read_text()))
    for w in warns:
        print("warning:", w)
    if not weeks or not slots:
        sys.exit("Nothing to sync (no weeks or no crew kickoffs found in data.json). Not touching the database.")

    by_week = {}
    for s in slots:
        by_week.setdefault(s["week"], []).append(s["crew"])
    if apply:
        url, key = load_config()
        print(f"APPLYING to {url.split('//')[-1]}: {len(weeks)} weeks, {len(slots)} crew kickoffs")
    else:
        print(f"DRY RUN (no network, no key needed): {len(weeks)} weeks, {len(slots)} crew kickoffs")
    if not apply:
        for w in weeks:
            print(f"  Week {w['week']}: {w['starts_at'][:16]}Z to {w['ends_at'][:16]}Z, {len(by_week.get(w['week'], []))} crews")
        print("Nothing written. Add --apply to write.")
        return

    api = Api(url, key)
    api.call("POST", "/rest/v1/weeks?on_conflict=season,week", weeks, "resolution=merge-duplicates,return=minimal")
    api.call("POST", "/rest/v1/game_slots?on_conflict=season,week,crew", slots, "resolution=merge-duplicates,return=minimal")

    # Remove kickoffs for crews no longer assigned that week (a provisional assignment changed). Only for weeks
    # where we have a fresh, non-empty list; never wipe a week from an empty read.
    season, removed = weeks[0]["season"], 0
    for wk, crews in by_week.items():
        have = api.call("GET", f"/rest/v1/game_slots?select=crew&season=eq.{season}&week=eq.{wk}") or []
        for stale in sorted({r["crew"] for r in have} - set(crews)):
            q = urllib.request.quote(stale, safe="")
            api.call("DELETE", f"/rest/v1/game_slots?season=eq.{season}&week=eq.{wk}&crew=eq.{q}", prefer="return=minimal")
            removed += 1
            print(f"  removed stale kickoff: Week {wk} {stale}")

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    api.call("POST", "/rest/v1/sync_status?on_conflict=key",
             [{"key": "kickoffs", "synced_at": now,
               "detail": {"weeks": len(weeks), "crew_kickoffs": len(slots), "removed": removed}}],
             "resolution=merge-duplicates,return=minimal")
    print(f"Done: {len(weeks)} weeks, {len(slots)} crew kickoffs, {removed} stale removed, heartbeat stamped.")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        sys.exit(f"sync failed: {e}")
