"""The "burglar" test: signs in as fake users on the REHEARSAL project and tries to break the rules.

Every attack must be refused, and every normal action must work. Prints PASS/FAIL per attempt.
Run:   python3 -I supabase/tests/burglar.py
Needs: .env.rehearsal in the project root (gitignored) with SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY and a password
       for each fake user: PW_COMMISH, PW_BRYAN, PW_MIKE, PW_OUTSIDER (or one shared TEST_PASSWORD for all four).
Needs the fake users and the seed from supabase/tests/README.md. The schedule fixtures are installed automatically when
.env.rehearsal-bot holds the bot's key (the real schedule is restored afterward); otherwise run rehearsal_weeks.sql by hand.
Starts from an empty lineup history (the script checks, and tells you how to reset).
Uses only the public key and the fake users' passwords. No secret key is involved.
Python standard library only.
"""
import base64
import datetime
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
env = {}
try:
    for line in (ROOT / ".env.rehearsal").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    URL = env["SUPABASE_URL"].rstrip("/")
    KEY = env["SUPABASE_PUBLISHABLE_KEY"]
    PWS = {u: env.get("PW_" + u) or env["TEST_PASSWORD"] for u in ("COMMISH", "BRYAN", "MIKE", "OUTSIDER")}
except (OSError, KeyError) as e:
    sys.exit("Missing or incomplete .env.rehearsal (%s). See supabase/tests/README.md." % e)

NOBODY = "00000000-0000-0000-0000-000000000000"
UNLOCKED_WEEK, LOCK_WEEK = 12, 11


class Resp:
    def __init__(self, status, text, method="GET"):
        self.status, self.text, self.method = status, text, method
        try:
            self.json = json.loads(text) if text else None
        except ValueError:
            self.json = None

    @property
    def message(self):
        return (self.json or {}).get("message", self.text) if isinstance(self.json, dict) else self.text


def http(method, path, body=None, token=None, headers=None):
    h = {"apikey": KEY, "Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    h.update(headers or {})
    # Inserts do NOT ask for the row back: asking can make a successful insert fail only because the
    # attacker can't READ the row, which would hide a real hole. So for inserts, status 2xx = it worked.
    # Updates/deletes ask for the changed rows, so "changed nothing" can be told from "changed something".
    if "/rest/v1/" in path and "/rpc/" not in path:
        if method == "POST":
            h.setdefault("Prefer", "return=minimal")
        elif method in ("PATCH", "DELETE"):
            h.setdefault("Prefer", "return=representation")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(URL + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return Resp(r.status, r.read().decode(), method)
    except urllib.error.HTTPError as e:
        return Resp(e.code, e.read().decode(), method)
    except urllib.error.URLError as e:
        sys.exit("Could not reach Supabase: %s" % e.reason)


def sign_in(email):
    who = email.split("@")[0].replace("ll-", "").upper()
    r = http("POST", "/auth/v1/token?grant_type=password", {"email": email, "password": PWS[who]})
    if r.status != 200:
        sys.exit("Could not sign in as %s (%s %s). Is the user created with Auto Confirm, and does the "
                 "password in .env.rehearsal match? See supabase/tests/README.md." % (email, r.status, r.message[:120]))
    return r.json["access_token"], r.json["user"]["id"]


passed = failed = 0


def record(label, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print("PASS - " + label)
    else:
        failed += 1
        print("FAIL - %s   [%s]" % (label, detail[:200]))


def refused(label, r, contains=None):
    ok = r.status >= 400 and (contains is None or contains.lower() in r.text.lower())
    record(label, ok, "got %s: %s" % (r.status, r.text))


def blocked_write(label, r):
    """A write is blocked if refused outright, or if it succeeded but changed no rows."""
    if r.method == "POST":
        ok = r.status >= 400                      # an insert that returns 2xx went in
    else:
        ok = r.status >= 400 or r.text.strip() in ("", "[]")
    record(label, ok, "write went through? %s: %s" % (r.status, r.text))


def allowed(label, r, check=None):
    ok = 200 <= r.status < 300 and (check is None or check(r))
    record(label, ok, "got %s: %s" % (r.status, r.text))


def rpc_lineup(token, team, week, starters, captain=None):
    return http("POST", "/rest/v1/rpc/set_lineup", token=token, body={
        "p_team_id": team, "p_week": week, "p_starters": starters, "p_captain": captain})


def get(path, token=None, headers=None):
    return http("GET", path, token=token, headers=headers)


ZERO = None   # (defaults in http() decide how each write asks for rows back)

# ---------------------------------------------------------------- sign in
print("Signing in four fake users...")
t_comm, id_comm = sign_in("ll-commish@example.com")
t_bry, id_bry = sign_in("ll-bryan@example.com")
t_mike, id_mike = sign_in("ll-mike@example.com")
t_out, id_out = sign_in("ll-outsider@example.com")

teams = {t["manager_name"]: t["id"] for t in (get("/rest/v1/teams?select=id,manager_name", t_bry).json or [])}
if len(teams) != 6:
    sys.exit("Expected 6 teams visible to Bryan, saw %d. Did the seed run?" % len(teams))
TB, TM, TMK = teams["Bryan"], teams["Matthew"], teams["Mike"]
league_id = get("/rest/v1/leagues?select=id", t_bry).json[0]["id"]

members_before = sorted((m["user_id"], m["role"], str(m["team_id"])) for m in get("/rest/v1/league_members?select=user_id,role,team_id", t_comm).json)
existing = get("/rest/v1/lineups?select=id", t_comm).json
if existing:
    sys.exit("lineups is not empty (%d rows). Reset first in the SQL Editor:\n"
             "  truncate public.lineups, public.audit_log;\nThen run this script again." % len(existing))

NOVAK, HUSSEY, RR = "Scott Novak", "John Hussey", "2012 Replacement Refs"

# ---------------------------------------------------------------- test fixtures
# The lock rules need a known schedule: Weeks 8-10 finished, Week 11 half kicked off, Weeks 12-18 in the future.
# If the bot's key is in .env.rehearsal-bot, this script saves the REAL schedule from the rehearsal project,
# installs these fixtures, and puts the real schedule back when it ends (even on an early exit). If the key isn't
# there, it assumes you ran supabase/seed/rehearsal_weeks.sql by hand. The key is used only for the two schedule
# tables (weeks, game_slots) and is never printed.
FIXTURE_WEEKS = [(8, "2026-10-25T17:00:00Z", "2026-10-27T12:00:00Z"), (9, "2026-11-01T17:00:00Z", "2026-11-03T12:00:00Z"),
                 (10, "2026-11-01T17:00:00Z", "2026-11-03T12:00:00Z"), (11, "2026-11-01T00:00:00Z", "2099-01-02T00:00:00Z")] + [
                 (w, (datetime.date(2099, 1, 1) + datetime.timedelta(days=7 * (w - 12))).isoformat() + "T00:00:00Z",
                  (datetime.date(2099, 1, 2) + datetime.timedelta(days=7 * (w - 12))).isoformat() + "T00:00:00Z") for w in range(12, 19)]
FIXTURE_SLOTS = [("Scott Novak", "2026-11-01T00:00:00Z"), ("Craig Wrolstad", "2026-11-01T00:00:00Z"), ("John Hussey", "2099-01-01T00:00:00Z"),
                 ("Brad Allen", "2099-01-01T00:00:00Z"), ("Clete Blakeman", "2099-01-01T00:00:00Z")]
SECRET = None
try:
    for _line in (ROOT / ".env.rehearsal-bot").read_text().splitlines():
        if _line.startswith("SUPABASE_SECRET_KEY="):
            SECRET = _line.split("=", 1)[1].strip() or None
except OSError:
    pass


def bot(method, path, body=None):
    """Request as the bot (secret key). Exits with a clear message on failure; never prints the key."""
    r = http(method, path, body, token=SECRET,
             headers={"apikey": SECRET, "Prefer": "return=minimal" if method == "POST" else "return=representation"})
    if r.status >= 300:
        sys.exit("Fixture setup failed (%s %s): %s" % (method, path.split("?")[0], r.text.replace(SECRET, "<key>")[:200]))
    return r.json


def install_fixtures():
    import atexit
    saved_weeks, saved_slots = bot("GET", "/rest/v1/weeks?select=*&season=eq.2026"), bot("GET", "/rest/v1/game_slots?select=*&season=eq.2026")

    def restore():
        bot("DELETE", "/rest/v1/game_slots?season=eq.2026")
        bot("DELETE", "/rest/v1/weeks?season=eq.2026")
        if saved_weeks:
            bot("POST", "/rest/v1/weeks", saved_weeks)
        if saved_slots:
            bot("POST", "/rest/v1/game_slots", saved_slots)
        print("(restored the real schedule: %d weeks, %d crew kickoffs)" % (len(saved_weeks), len(saved_slots)))

    atexit.register(restore)   # runs on normal exit AND on sys.exit; if the process is killed, re-run scripts/sync_supabase.py --apply
    bot("DELETE", "/rest/v1/game_slots?season=eq.2026")
    bot("DELETE", "/rest/v1/weeks?season=eq.2026")
    bot("POST", "/rest/v1/weeks", [{"season": 2026, "week": w, "starts_at": a, "ends_at": b} for w, a, b in FIXTURE_WEEKS])
    bot("POST", "/rest/v1/game_slots", [{"season": 2026, "week": 11, "crew": c, "kickoff_at": t} for c, t in FIXTURE_SLOTS])
    print("(installed the test schedule; the real one is saved and will be restored at the end)")
if SECRET:
    install_fixtures()
else:
    print("(no .env.rehearsal-bot: assuming you ran supabase/seed/rehearsal_weeks.sql by hand)")
ok_lineups = 0   # normal saves we expect to succeed; used for the final cross-check

# ---------------------------------------------------------------- A. stranger (not signed in)
print("\nA. A stranger who is not signed in")
for table in ["leagues", "teams", "roster", "league_members", "game_slots", "lineups", "audit_log", "weeks", "sync_status"]:
    refused("read %s" % table, get("/rest/v1/%s?select=*" % table))
refused("call set_lineup", http("POST", "/rest/v1/rpc/set_lineup", body={
    "p_team_id": TB, "p_week": 12, "p_starters": [NOVAK, HUSSEY], "p_captain": None}))
refused("insert a lineup directly (a complete, valid row)", http("POST", "/rest/v1/lineups", {
    "league_id": league_id, "team_id": TB, "week": 12, "starters": [NOVAK, HUSSEY], "created_by": NOBODY}))
refused("reach the private schema", get("/rest/v1/teams", headers={"Accept-Profile": "private"}), "invalid schema")
refused("call the removed public helper", http("POST", "/rest/v1/rpc/is_league_member", {"p_league": league_id}))
refused("call effective_lineup", http("POST", "/rest/v1/rpc/effective_lineup", body={"p_team_id": TB, "p_week": 12}))
refused("call lineup_effect_range", http("POST", "/rest/v1/rpc/lineup_effect_range", body={"p_team_id": TB, "p_week": 12}))

# ---------------------------------------------------------------- B. forged logins
print("\nB. Forged logins")
h, p, s = t_bry.split(".")
def b64(d):
    return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
payload = json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
payload["role"] = "service_role"
refused("Bryan's token edited to say service_role", get("/rest/v1/lineups?select=*", h + "." + b64(payload) + "." + s))
none_token = b64({"alg": "none", "typ": "JWT"}) + "." + b64({"role": "service_role", "aud": "authenticated"}) + "."
refused("token with no signature at all", get("/rest/v1/lineups?select=*", none_token))
refused("garbage token", get("/rest/v1/lineups?select=*", "not-a-token"))

# ---------------------------------------------------------------- C. outsider
print("\nC. Signed in, but not in the league (outsider)")
for table in ["leagues", "teams", "roster", "league_members", "lineups", "audit_log"]:
    allowed("sees zero rows of %s" % table, get("/rest/v1/%s?select=*" % table, t_out), lambda r: r.json == [])
allowed("can read public kickoff times", get("/rest/v1/game_slots?select=*", t_out), lambda r: len(r.json) == 5)
allowed("can read public weeks schedule", get("/rest/v1/weeks?select=*", t_out), lambda r: len(r.json) >= 11)
allowed("can read the sync heartbeat", get("/rest/v1/sync_status?select=*", t_out))
refused("cannot read Bryan's effective_lineup", http("POST", "/rest/v1/rpc/effective_lineup", token=t_out, body={"p_team_id": TB, "p_week": 12}), "not allowed")
refused("cannot read lineup_effect_range", http("POST", "/rest/v1/rpc/lineup_effect_range", token=t_out, body={"p_team_id": TB, "p_week": 12}), "not allowed")
refused("cannot set a lineup on Bryan's team", rpc_lineup(t_out, TB, 12, [NOVAK, HUSSEY]), "not allowed")
blocked_write("cannot insert a lineup directly", http("POST", "/rest/v1/lineups", token=t_out, body={
    "league_id": league_id, "team_id": TB, "week": 12, "starters": [NOVAK, HUSSEY], "created_by": id_out}))
blocked_write("cannot add self to the league", http("POST", "/rest/v1/league_members", token=t_out, body={
    "league_id": league_id, "user_id": id_out, "role": "commissioner"}))

# ---------------------------------------------------------------- D. manager (Bryan)
print("\nD. A normal manager (Bryan)")
allowed("sees all 6 teams", get("/rest/v1/teams?select=id", t_bry), lambda r: len(r.json) == 6)
allowed("sees all 18 roster rows", get("/rest/v1/roster?select=team_id", t_bry), lambda r: len(r.json) == 18)
print("  finished weeks are closed to managers (Weeks 8-10 ended in the past)")
for wk in (8, 9, 10):
    refused("own lineup for finished Week %d" % wk, rpc_lineup(t_bry, TB, wk, [HUSSEY, RR]), "finished")

r1 = rpc_lineup(t_bry, TMK, 12, [NOVAK, HUSSEY])
r2 = rpc_lineup(t_bry, NOBODY, 12, [NOVAK, HUSSEY])
refused("cannot set Mike's lineup", r1, "not allowed")
record("'someone else's team' and 'no such team' give the same answer (no probing)",
       r1.status == r2.status and r1.message == r2.message, "%r vs %r" % (r1.message, r2.message))
refused("crew not on his roster (Mike's crew)", rpc_lineup(t_bry, TB, 12, [NOVAK, "Brad Allen"]), "not on this team")
refused("same crew twice", rpc_lineup(t_bry, TB, 12, [NOVAK, NOVAK]), "exactly 2")
refused("only one starter", rpc_lineup(t_bry, TB, 12, [NOVAK]), "exactly 2")
refused("three starters", rpc_lineup(t_bry, TB, 12, [NOVAK, HUSSEY, RR]), "exactly 2")
refused("no starters", rpc_lineup(t_bry, TB, 12, []), "exactly 2")
refused("captain who isn't a starter", rpc_lineup(t_bry, TB, 12, [NOVAK, HUSSEY], RR), "captain must be")
refused("captain before Week 11", rpc_lineup(t_bry, TB, 10, [NOVAK, HUSSEY], NOVAK), "captains start")
refused("Week 7 (before the season)", rpc_lineup(t_bry, TB, 7, [NOVAK, HUSSEY]), "outside this season")
refused("Week 19 (after the season)", rpc_lineup(t_bry, TB, 19, [NOVAK, HUSSEY]), "outside this season")
refused("Week missing", http("POST", "/rest/v1/rpc/set_lineup", token=t_bry, body={
    "p_team_id": TB, "p_week": None, "p_starters": [NOVAK, HUSSEY]}))

print("  per-crew lock (Novak has kicked off in Week 11, Hussey has not)")
refused("bench Novak after kickoff", rpc_lineup(t_bry, TB, LOCK_WEEK, [HUSSEY, RR]), "locked")
refused("make Novak captain after kickoff", rpc_lineup(t_bry, TB, LOCK_WEEK, [NOVAK, HUSSEY], NOVAK), "locked")
allowed("name Hussey captain (not kicked off)", rpc_lineup(t_bry, TB, LOCK_WEEK, [NOVAK, HUSSEY], HUSSEY)); ok_lineups += 1
refused("move captain from Hussey onto kicked-off Novak", rpc_lineup(t_bry, TB, LOCK_WEEK, [NOVAK, HUSSEY], NOVAK), "locked")
allowed("swap Hussey for Replacement Refs, keep Novak", rpc_lineup(t_bry, TB, LOCK_WEEK, [NOVAK, RR])); ok_lineups += 1
allowed("Week 12 has no kickoffs yet: free to set", rpc_lineup(t_bry, TB, UNLOCKED_WEEK, [HUSSEY, RR], HUSSEY)); ok_lineups += 1

print("  direct writes (every one must be blocked)")
writes = [
    ("insert into lineups", "POST", "/rest/v1/lineups", {"league_id": league_id, "team_id": TB, "week": 12,
                                                          "starters": [NOVAK, HUSSEY], "created_by": id_bry}),
    ("update lineups", "PATCH", "/rest/v1/lineups?id=gt.0", {"week": 9}),
    ("delete lineups", "DELETE", "/rest/v1/lineups?id=gt.0", None),
    ("make himself commissioner", "PATCH", "/rest/v1/league_members?user_id=eq." + id_bry, {"role": "commissioner"}),
    ("make the outsider a commissioner (valid new row)", "POST", "/rest/v1/league_members",
     {"league_id": league_id, "user_id": id_out, "role": "commissioner"}),
    ("delete members", "DELETE", "/rest/v1/league_members?role=eq.commissioner", None),
    ("write the audit log", "POST", "/rest/v1/audit_log", {"league_id": league_id, "action": "fake"}),
    ("edit kickoff times", "PATCH", "/rest/v1/game_slots?crew=eq.Scott%20Novak", {"kickoff_at": "2099-01-01T00:00:00Z"}),
    ("add kickoff times", "POST", "/rest/v1/game_slots", {"season": 2026, "week": 12, "crew": NOVAK, "kickoff_at": "2099-01-01T00:00:00Z"}),
    ("edit weeks (reopen a finished week)", "PATCH", "/rest/v1/weeks?week=eq.10", {"ends_at": "2099-01-01T00:00:00Z"}),
    ("add weeks", "POST", "/rest/v1/weeks", {"season": 2026, "week": 99, "starts_at": "2099-01-01T00:00:00Z", "ends_at": "2099-01-02T00:00:00Z"}),
    ("delete weeks", "DELETE", "/rest/v1/weeks?week=gt.0", None),
    ("forge the sync heartbeat", "POST", "/rest/v1/sync_status", {"key": "kickoffs", "synced_at": "2099-01-01T00:00:00Z"}),
    ("edit the sync heartbeat", "PATCH", "/rest/v1/sync_status?key=eq.kickoffs", {"synced_at": "2099-01-01T00:00:00Z"}),
    ("edit rosters", "PATCH", "/rest/v1/roster?crew=eq.Scott%20Novak", {"crew": "Hacked"}),
    ("edit teams", "PATCH", "/rest/v1/teams?manager_name=eq.Mike", {"manager_name": "Hacked"}),
    ("edit the league", "PATCH", "/rest/v1/leagues?id=gt.0", {"name": "Hacked"}),
    ("delete the league", "DELETE", "/rest/v1/leagues?name=neq.zzz", None),
]
for label, method, path, body in writes:
    blocked_write("Bryan: " + label, http(method, path, body, t_bry, ZERO))
refused("reach the private schema", get("/rest/v1/teams", t_bry, {"Accept-Profile": "private"}), "invalid schema")
refused("call the removed public helper", http("POST", "/rest/v1/rpc/is_league_member", {"p_league": league_id}, t_bry))
refused("call add_member (must not exist as a function)", http("POST", "/rest/v1/rpc/add_member", token=t_bry, body={"email": "x@example.com"}))

print("  claiming to be commissioner in his own profile")
http("PUT", "/auth/v1/user", {"data": {"role": "commissioner", "team_id": TMK, "is_admin": True}}, t_bry)
t_bry_edited, _ = sign_in("ll-bryan@example.com")   # a fresh login now carries the edited profile
_p = t_bry_edited.split(".")[1]
claims = json.loads(base64.urlsafe_b64decode(_p + "=" * (-len(_p) % 4)))
record("(setup) Bryan's new login really does carry the fake profile claims",
       claims.get("user_metadata", {}).get("role") == "commissioner", str(claims.get("user_metadata")))
refused("with 'commissioner' in his profile, still can't set Mike's lineup", rpc_lineup(t_bry_edited, TMK, 12, ["Craig Wrolstad", "Brad Allen"]), "not allowed")
http("PUT", "/auth/v1/user", {"data": {"role": None, "team_id": None, "is_admin": None}}, t_bry_edited)

# ---------------------------------------------------------------- E. another manager (Mike)
print("\nE. Another manager (Mike)")
allowed("save own lineup + captain, Week 12", rpc_lineup(t_mike, TMK, 12, ["Brad Allen", "Clete Blakeman"], "Brad Allen")); ok_lineups += 1
refused("cannot save a finished week (Week 9)", rpc_lineup(t_mike, TMK, 9, ["Brad Allen", "Clete Blakeman"]), "finished")
refused("cannot bench Wrolstad after kickoff (Week 11)", rpc_lineup(t_mike, TMK, LOCK_WEEK, ["Brad Allen", "Clete Blakeman"]), "locked")
refused("cannot touch Bryan's team", rpc_lineup(t_mike, TB, 12, [HUSSEY, RR]), "not allowed")
allowed("can SEE Bryan's lineups (league is open)", get("/rest/v1/lineups?select=team_id&team_id=eq." + TB, t_mike),
        lambda r: len(r.json) >= 3)

# ---------------------------------------------------------------- F. commissioner
print("\nF. The commissioner")
allowed("override: set Bryan's Week 11 lineup even though Novak kicked off",
        rpc_lineup(t_comm, TB, LOCK_WEEK, [HUSSEY, RR])); ok_lineups += 1
allowed("set own team's lineup + captain, Week 11", rpc_lineup(t_comm, TM, LOCK_WEEK, ["Alex Moore", "Ron Torbert"], "Alex Moore")); ok_lineups += 1
allowed("CORRECT Bryan's finished Week 10 (commissioner may; logged)", rpc_lineup(t_comm, TB, 10, [HUSSEY, RR])); ok_lineups += 1
allowed("correct her own finished Week 9 too", rpc_lineup(t_comm, TM, 9, ["Alex Moore", "Ron Torbert"])); ok_lineups += 1
n_past = 2
refused("override still needs a legal lineup: crew not on roster", rpc_lineup(t_comm, TB, 12, [NOVAK, "Alex Moore"]), "not on this team")
refused("override still needs a legal lineup: Week 7", rpc_lineup(t_comm, TB, 7, [NOVAK, HUSSEY]), "outside this season")
refused("override still needs a legal lineup: captain before Week 11", rpc_lineup(t_comm, TB, 10, [NOVAK, HUSSEY], NOVAK), "captains start")
blocked_write("commissioner cannot write lineups directly either (must be logged)",
              http("POST", "/rest/v1/lineups", token=t_comm, body={
                  "league_id": league_id, "team_id": TB, "week": 12, "starters": [NOVAK, HUSSEY], "created_by": id_comm}))
blocked_write("commissioner cannot edit lineup history", http("PATCH", "/rest/v1/lineups?id=gt.0", {"week": 9}, t_comm, ZERO))
blocked_write("commissioner cannot delete lineup history", http("DELETE", "/rest/v1/lineups?id=gt.0", None, t_comm, ZERO))

# ---------------------------------------------------------------- G. did anything sneak through?
print("\nG. Cross-checks: did anything sneak in?")
rows = get("/rest/v1/lineups?select=id,by_commissioner,created_by,team_id&order=id", t_comm).json
record("lineup rows == successful saves (%d)" % ok_lineups, len(rows) == ok_lineups, "found %d" % len(rows))
record("exactly two rows flagged as commissioner-for-another-team (Week 11 override, Week 10 correction)",
       sum(1 for x in rows if x["by_commissioner"]) == 2, str(rows))
audit = get("/rest/v1/audit_log?select=action", t_comm).json
record("audit log: %d 'lineup_set' + 1 override + %d past-week corrections" % (ok_lineups - 1 - n_past, n_past),
       sorted(a["action"] for a in audit) == sorted(["lineup_set"] * (ok_lineups - 1 - n_past) + ["lineup_set_by_commissioner"]
                                                    + ["lineup_set_past_week"] * n_past), str(audit))
past_log = [a for a in get("/rest/v1/audit_log?select=detail&action=eq.lineup_set_past_week", t_comm).json]
record("past-week corrections are marked past_week=true in the log", len(past_log) == n_past and all(a["detail"].get("past_week") is True for a in past_log), str(past_log))

print("\nH. New server answers: effective_lineup and lineup_effect_range")
def rpc(token, fn, team, week):
    return http("POST", "/rest/v1/rpc/" + fn, token=token, body={"p_team_id": team, "p_week": week})
r = rpc(t_mike, "effective_lineup", TB, 12)
allowed("Mike (a member) can read Bryan's Week 12 lineup", r,
        lambda r: r.json and r.json[0]["starters"] == [HUSSEY, RR] and r.json[0]["captain"] == HUSSEY and r.json[0]["from_week"] == 12)
r = rpc(t_mike, "effective_lineup", TB, 9)
allowed("before any saved row: first two roster crews, no captain", r,
        lambda r: r.json and r.json[0]["starters"] == [NOVAK, HUSSEY] and r.json[0]["captain"] is None and r.json[0]["from_week"] is None)
r = rpc(t_mike, "effective_lineup", TB, 10)
allowed("Week 10 = the commissioner's logged correction", r, lambda r: r.json and r.json[0]["starters"] == [HUSSEY, RR] and r.json[0]["from_week"] == 10)
r1, r2 = rpc(t_out, "effective_lineup", TB, 12), rpc(t_out, "effective_lineup", NOBODY, 12)
record("outsider: 'real team' and 'no such team' give the same refusal", r1.status >= 400 and (r1.status, r1.message) == (r2.status, r2.message), "%r vs %r" % (r1.message, r2.message))
allowed("a Week 10 correction for Bryan would change weeks 10 to 10 (his next own row is Week 11)", rpc(t_comm, "lineup_effect_range", TB, 10),
        lambda r: r.json and (r.json[0]["from_week"], r.json[0]["to_week"]) == (10, 10))
allowed("Matthew's team: a Week 9 correction already made; a new one would run 9 to 10", rpc(t_comm, "lineup_effect_range", TM, 9),
        lambda r: r.json and (r.json[0]["from_week"], r.json[0]["to_week"]) == (9, 10))
allowed("a team with no later row runs to the end of the season (Mike, Week 12 row exists, so 12-18)", rpc(t_comm, "lineup_effect_range", TMK, 12),
        lambda r: r.json and (r.json[0]["from_week"], r.json[0]["to_week"]) == (12, 18))
weeks = get("/rest/v1/weeks?select=week,ends_at&order=week", t_out).json
record("weeks schedule unchanged (Week 10 still finished)", any(w["week"] == 10 and w["ends_at"].startswith("2026-11-03") for w in weeks), str(weeks[:4]))
members_after = sorted((m["user_id"], m["role"], str(m["team_id"])) for m in get("/rest/v1/league_members?select=user_id,role,team_id", t_comm).json)
record("membership unchanged by the whole run (same people, roles and teams as before it started)", members_after == members_before, "%d before, %d after" % (len(members_before), len(members_after)))
record("the outsider was never added", id_out not in [m[0] for m in members_after])
record("the three test users still have their original roles",
       {m[0]: m[1] for m in members_after if m[0] in (id_comm, id_bry, id_mike)} == {id_comm: "commissioner", id_bry: "manager", id_mike: "manager"})
slots = get("/rest/v1/game_slots?select=crew", t_out).json
record("kickoff times unchanged (5)", len(slots) == 5, str(len(slots)))
record("team names unchanged", get("/rest/v1/teams?select=manager_name&manager_name=eq.Hacked", t_comm).json == [], "")

print("\n%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
