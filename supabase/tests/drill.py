"""The rehearsal-week drill (step 5d), run automatically against the REHEARSAL project. Never point this at the real league.

Run:  python3 -I supabase/tests/drill.py        (about 2 minutes; most of it is waiting for a test kickoff to pass)

What it proves, using the real database rules and the fake users (Bryan = manager, ll-commish = commissioner):
  1. Before a crew's kickoff, the manager can change his lineup.
  2. After that crew's kickoff, the manager is REFUSED if he touches that crew (bench it, or make it captain)...
  3. ...but can still change OTHER crews (the lock is per crew, not per team).
  4. The commissioner CAN override the lock, and the override is logged.
  5. FAILURE DRILL: if the bot stops feeding kickoff times (we delete them), a manager is BLOCKED ("fail closed")...
  6. ...and when the feed comes back, the manager can edit again.
Needs .env.rehearsal (fake users' passwords) and .env.rehearsal-bot (the bot's secret key, used only to set up and restore
the schedule). The real schedule is saved first and put back at the end, even on an early exit.
Side effect: a few fake lineup rows and log entries are left in the rehearsal project (history is append-only). Before the next
security test, run in the SQL Editor:  truncate public.lineups, public.audit_log;
Standard library only.
"""
import atexit, datetime, json, pathlib, sys, time, urllib.error, urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
env = {}
for name in (".env.rehearsal", ".env.rehearsal-bot"):
    try:
        for line in (ROOT / name).read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    except OSError:
        sys.exit("Missing %s (see supabase/tests/README.md)." % name)
URL, KEY, SECRET = env["SUPABASE_URL"].rstrip("/"), env["SUPABASE_PUBLISHABLE_KEY"], env["SUPABASE_SECRET_KEY"]
SEASON, WEEK = 2026, 12
KICKOFF_IN = 75          # seconds from setup until the test crew "kicks off"

passed = failed = 0


def call(method, path, body=None, token=None, key=None, headers=None):
    h = {"apikey": key or KEY, "Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    h.update(headers or {})
    req = urllib.request.Request(URL + path, data=json.dumps(body).encode() if body is not None else None, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read().decode()
            return r.status, (json.loads(text) if text else None), text
    except urllib.error.HTTPError as e:
        text = e.read().decode().replace(SECRET, "<key>")
        try:
            return e.code, json.loads(text), text
        except ValueError:
            return e.code, None, text
    except urllib.error.URLError as e:
        sys.exit("Could not reach Supabase: %s" % e.reason)


def bot(method, path, body=None, prefer="return=minimal"):
    s, j, t = call(method, path, body, token=SECRET, key=SECRET, headers={"Prefer": prefer})
    if s >= 300:
        sys.exit("Setup failed (%s %s): %s" % (method, path.split("?")[0], t[:200]))
    return j


def sign_in(who):
    pw = env.get("PW_" + who.upper()) or env["TEST_PASSWORD"]
    s, j, t = call("POST", "/auth/v1/token?grant_type=password", {"email": "ll-%s@example.com" % who, "password": pw})
    if s != 200:
        sys.exit("Could not sign in as the fake user %s (%s)." % (who, s))
    return j["access_token"]


def record(label, ok, detail=""):
    global passed, failed
    if ok: passed += 1; print("PASS - " + label)
    else: failed += 1; print("FAIL - %s   [%s]" % (label, str(detail)[:220]))


def set_lineup(token, team, starters, captain):
    return call("POST", "/rest/v1/rpc/set_lineup", {"p_team_id": team, "p_week": WEEK, "p_starters": starters, "p_captain": captain}, token=token)


def effective(token, team):
    s, j, t = call("POST", "/rest/v1/rpc/effective_lineup", {"p_team_id": team, "p_week": WEEK}, token=token)
    return j[0] if s == 200 and j else None


def allowed(label, r):
    record(label, r[0] == 200, "got %s: %s" % (r[0], r[2]))


def refused(label, r, text):
    record(label, r[0] >= 400 and text.lower() in r[2].lower(), "got %s: %s" % (r[0], r[2]))


iso = lambda dt: dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ---------------------------------------------------------------- setup (and a guaranteed restore)
print("Setting up (saving the real schedule first)...")
saved_weeks = bot("GET", "/rest/v1/weeks?select=*&season=eq.%d" % SEASON, prefer="return=representation")
saved_slots = bot("GET", "/rest/v1/game_slots?select=*&season=eq.%d" % SEASON, prefer="return=representation")


def restore():
    bot("DELETE", "/rest/v1/game_slots?season=eq.%d" % SEASON)
    bot("DELETE", "/rest/v1/weeks?season=eq.%d" % SEASON)
    if saved_weeks: bot("POST", "/rest/v1/weeks", saved_weeks)
    if saved_slots: bot("POST", "/rest/v1/game_slots", saved_slots)
    print("(restored the real schedule: %d weeks, %d crew kickoffs)" % (len(saved_weeks), len(saved_slots)))


atexit.register(restore)

t_bry, t_com = sign_in("bryan"), sign_in("commish")
teams = {t["manager_name"]: t["id"] for t in call("GET", "/rest/v1/teams?select=id,manager_name", token=t_bry)[1]}
TB = teams["Bryan"]
roster = [r["crew"] for r in sorted(call("GET", "/rest/v1/roster?select=crew,slot&team_id=eq." + TB, token=t_bry)[1], key=lambda r: r["slot"])]
cur = effective(t_bry, TB)
A, B = cur["starters"]          # Bryan's two starters this week: A is the crew we will "kick off"
C = next(c for c in roster if c not in (A, B))
print("Bryan's Week %d lineup: starters %s and %s, bench %s. Test crew that will 'kick off': %s" % (WEEK, A, B, C, A))

now = datetime.datetime.now(datetime.timezone.utc)
kick = now + datetime.timedelta(seconds=KICKOFF_IN)
# Week 12 must look "started" (so the fail-closed rule applies), with ONLY our test kickoff on file.
bot("POST", "/rest/v1/weeks?on_conflict=season,week", [{"season": SEASON, "week": WEEK, "starts_at": iso(now - datetime.timedelta(hours=1)),
                                                        "ends_at": iso(now + datetime.timedelta(days=7))}], "resolution=merge-duplicates,return=minimal")
bot("DELETE", "/rest/v1/game_slots?season=eq.%d&week=eq.%d" % (SEASON, WEEK))
bot("POST", "/rest/v1/game_slots", [{"season": SEASON, "week": WEEK, "crew": A, "kickoff_at": iso(kick)}])
print("Test kickoff for %s set for %s UTC (in %d seconds).\n" % (A, iso(kick)[11:19], KICKOFF_IN))

# ---------------------------------------------------------------- 1. before kickoff
print("1. Before the kickoff")
new_cap = B if cur["captain"] != B else None
allowed("manager changes his captain (touches only %s, who has not kicked off)" % B, set_lineup(t_bry, TB, [A, B], new_cap))
allowed("manager may even change the crew that is ABOUT to kick off (%s): still open" % A, set_lineup(t_bry, TB, [A, B], A))

# ---------------------------------------------------------------- 2. wait for the kickoff
wait = (kick - datetime.datetime.now(datetime.timezone.utc)).total_seconds() + 8      # margin for clock differences
print("\nWaiting %d seconds for %s's kickoff to pass..." % (max(0, wait), A))
time.sleep(max(0, wait))

print("\n2. After the kickoff: the manager is refused if he touches the kicked-off crew")
refused("bench %s (replace with %s)" % (A, C), set_lineup(t_bry, TB, [B, C], None), "kicked off")
refused("move the captain away from %s after kickoff" % A, set_lineup(t_bry, TB, [A, B], B), "kicked off")
allowed("...but he CAN still change an unlocked crew (swap %s for %s, keep %s): the lock is per crew" % (B, C, A), set_lineup(t_bry, TB, [A, C], A))

# ---------------------------------------------------------------- 3. commissioner override
print("\n3. The commissioner overrides")
allowed("commissioner benches the kicked-off %s anyway" % A, set_lineup(t_com, TB, [C, B], None))
audit = call("GET", "/rest/v1/audit_log?select=action,detail&order=id.desc&limit=1", token=t_com)[1]
record("the override is logged as lineup_set_by_commissioner", bool(audit) and audit[0]["action"] == "lineup_set_by_commissioner", audit)

# ---------------------------------------------------------------- 4. failure drill
print("\n4. FAILURE DRILL: the bot stops feeding kickoff times")
bot("DELETE", "/rest/v1/game_slots?season=eq.%d&week=eq.%d" % (SEASON, WEEK))
refused("manager is BLOCKED while kickoff times are missing (fail closed)", set_lineup(t_bry, TB, [C, B], B), "kickoff times are missing")
refused("...even for a change that would normally be fine", set_lineup(t_bry, TB, [B, C], None), "kickoff times are missing")
print("   (the feed comes back)")
bot("POST", "/rest/v1/game_slots", [{"season": SEASON, "week": WEEK, "crew": A, "kickoff_at": iso(kick)}])
allowed("with the feed back, the manager can edit unlocked crews again", set_lineup(t_bry, TB, [C, B], B))
refused("...and the kicked-off crew is locked again", set_lineup(t_bry, TB, [A, B], B), "kicked off")

print("\n%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
