"""Replay proof for the lineup reader (scripts/fetch_lineups.py + the lineups_from_db_week switch in build_data.py).

Run:  python3 -I supabase/tests/test_lineups_replay.py        (about 30 seconds; no network, no keys)

It copies the project into a temp folder, then builds the WHOLE site many ways and compares each result with a build
from today's league.json (the baseline). Pretend "app" lineups are made by converting league.json's own entries into the
shape the app saves, so a faithful reader must reproduce today's scores exactly. Then it feeds in bad data and checks the
build neither crashes nor changes a score it shouldn't.
"""
import copy, json, os, pathlib, shutil, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
tmp = pathlib.Path(tempfile.mkdtemp(prefix="ll-replay-"))
work = tmp / "proj"
(work / "cache").mkdir(parents=True)
for name in ("scripts", "data"):
    shutil.copytree(ROOT / name, work / name, ignore=shutil.ignore_patterns("__pycache__"))
for f in (ROOT / "cache").iterdir():
    (work / "cache" / f.name).symlink_to(f)
LEAGUE = json.loads((ROOT / "league.json").read_text())

passed = failed = 0
def check(label, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print("PASS -", label)
    else: failed += 1; print("FAIL - %s   [%s]" % (label, str(extra)[:300]))

def first_diff(x, y, path="", out=None):
    """Where do two builds differ? Returns up to 4 paths with both values, for failure messages."""
    out = [] if out is None else out
    if len(out) >= 4 or x is None or y is None:
        return out or ["one build failed"]
    if type(x) != type(y): out.append("%s: type %s vs %s" % (path, type(x).__name__, type(y).__name__))
    elif isinstance(x, dict):
        for k in sorted(set(x) | set(y), key=str):
            if k not in x or k not in y: out.append("%s/%s: only in one" % (path, k))
            else: first_diff(x[k], y[k], path + "/" + str(k), out)
    elif isinstance(x, list):
        if len(x) != len(y): out.append("%s: length %d vs %d" % (path, len(x), len(y)))
        else:
            for i, (p, q) in enumerate(zip(x, y)): first_diff(p, q, "%s/%d" % (path, i), out)
    elif x != y: out.append("%s: %r vs %r" % (path, x, y))
    return out[:4]


def build(league, db=None, name="out"):
    """Build with the given league.json dict and optional app-lineups file. Returns (data dict | None, log text, exit code)."""
    (work / "league.json").write_text(json.dumps(league, indent=1))
    dbfile = work / "cache" / "lineups_db.json"
    dbfile.unlink(missing_ok=True)
    if db is not None:
        dbfile.write_text(db if isinstance(db, str) else json.dumps(db))
    out = tmp / (name + ".json")
    r = subprocess.run([sys.executable, "-I", "scripts/build_data.py", "cache", str(out)], cwd=work, capture_output=True, text=True)
    data = json.loads(out.read_text()) if r.returncode == 0 and out.exists() else None
    if data:
        data.pop("generated_at", None)
        build.switch = data.pop("lineups_from_db_week", "MISSING")      # the setting as published in data.json (checked on its own)
    return data, r.stdout + r.stderr, r.returncode

def app_rows(entries, start_id=1):
    """Convert league.json lineup entries to what the app would have saved (explicit captain every time), independently
    of build_data.py: a missing 'captain' keeps the old captain only if that crew still starts; "" clears it."""
    cap, rows = {}, []
    for i, e in enumerate(sorted(enumerate(entries), key=lambda x: (x[1]["week"], x[0]))):
        e = e[1]
        picks = e["start"]
        if cap.get(e["team"]) not in picks: cap[e["team"]] = None
        if e.get("captain"): cap[e["team"]] = e["captain"]
        elif "captain" in e: cap[e["team"]] = None
        rows.append({"id": start_id + i, "week": e["week"], "team": e["team"], "start": picks, "captain": cap[e["team"]], "created_at": "x"})
    return rows

def db(rows): return {"fetched_at": "2026-11-24T00:00:00Z", "league": "t", "entries": rows}
def without_switch(): l = copy.deepcopy(LEAGUE); l.pop("lineups_from_db_week", None); return l
def with_switch(w): l = without_switch(); l["lineups_from_db_week"] = w; return l

base, log, code = build(without_switch(), name="base")
check("baseline builds from league.json", base is not None, log[-300:])
check("data.json publishes the setting as null when it is not set", build.switch is None, build.switch)
ENT = LEAGUE["lineups"]
rows = app_rows(ENT)
print("  (baseline has %d league.json lineup entries, weeks %s)" % (len(ENT), sorted({e["week"] for e in ENT})))

print("\nFaithful copies must reproduce today's scores exactly")
d, log, _ = build(with_switch(8), db(rows), "all")
check("switch at Week 8, app holds every lineup: identical to baseline", d == base, first_diff(d, base))
check("...and the log says weeks 8+ come from the app", "week 8 and later come from the app" in log, log[-300:])
check("data.json publishes the setting (8) when it is set, so the app can tell which weeks scoring ignores", build.switch == 8, build.switch)
for w in (9, 10, 11, 12):
    d, log, _ = build(with_switch(w), db([r for r in rows if r["week"] >= w]), "sw%d" % w)
    check("switch at Week %d, app holds only lineups from Week %d on: identical" % (w, w), d == base, first_diff(d, base))
d, _, _ = build(with_switch(8), db(rows[::-1]), "rev")
check("rows arriving in the wrong order (by id they still replay correctly): identical", d == base, first_diff(d, base))
d, _, _ = build(without_switch(), db(rows), "shadow")
check("switch OFF while the app file exists: identical (the app is only watched)", d == base, first_diff(d, base))
d, log, _ = build(without_switch(), db(rows), "shadowlog")
check("...and the shadow check says league.json and the app agree", "league.json and the app agree" in log, log[-400:])

print("\nPast weeks and the single boundary")
bad_past = copy.deepcopy(rows) + [{"id": 900, "week": 9, "team": ENT[0]["team"], "start": ENT[0]["start"][::-1], "captain": None, "created_at": "x"}]
bad_past[-1]["start"] = [c for c in ENT[0]["start"]]
other = [c for t in LEAGUE["teams"] if t["name"] == ENT[0]["team"] for c in t["crews"]]
bad_past[-1]["start"] = other[:2][::-1] if other[:2] != ENT[0]["start"] else other[1:3]
d, log, _ = build(with_switch(12), db(bad_past), "pastedit")
check("an app row for Week 9 is IGNORED when the switch is at Week 12 (past weeks cannot change)", d == base, first_diff(d, base))
check("...and the build SAYS so: names the ignored row's week and team", "ignored by scoring" in log and "Week 9" in log and ENT[0]["team"] in log, log[-500:])
d, log, _ = build(with_switch(8), db(rows), "noignored")
check("no ignored-rows message when every app row is at or after the switch", "ignored by scoring" not in log, log[-300:])

print("\nAfter the switch the app is the ONLY source (a lineup only texted, never entered in the app, is ignored)")
for sw in (11, 12):
    texted_only = next(r for r in rows if r["week"] == sw)               # a team that has a league.json entry at the switch week
    d, log, _ = build(with_switch(sw), db([r for r in rows if r["week"] >= sw and r is not texted_only]), "textonly%d" % sw)
    check("Week %d: a team with a league.json entry but no app row keeps its earlier lineup (differs from baseline)" % sw, d is not None and d != base)
    # Independent expectation: the same result as a league.json that simply never had that entry.
    without = without_switch()
    without["lineups"] = [e for e in LEAGUE["lineups"] if not (e["week"] == sw and e["team"] == texted_only["team"])]
    expect, _, _ = build(without, None, "expect%d" % sw)
    check("Week %d: ...and it equals a league.json with that one entry deleted" % sw, d == expect, first_diff(d, expect))
    shadow_rows = [r for r in rows if r["week"] >= sw and r is not texted_only]
    if not shadow_rows:
        continue                                   # an empty app file has nothing to compare; that is fine
    shadow_log = build(without_switch(), db(shadow_rows), "shadowtext")[1]
    check("Week %d: ...and shadow mode (switch off) flags the missing app entry" % sw, "difference(s) between league.json and the app" in shadow_log and texted_only["team"] in shadow_log, shadow_log[-300:])

print("\nA different app lineup changes only what it should")
team = ENT[-1]["team"]; roster = next(t["crews"] for t in LEAGUE["teams"] if t["name"] == team)
mine = [r for r in rows if r["team"] == team]
changed = copy.deepcopy(rows)
last = [r for r in changed if r["team"] == team][-1]
last["start"] = [c for c in roster if c not in last["start"]][:1] + [last["start"][0]]
last["captain"] = None
d, log, _ = build(with_switch(8), db(changed), "diff")
check("a changed app lineup changes the output", d is not None and d != base)
d2, _, _ = build(with_switch(last["week"] + 1) if last["week"] < 18 else with_switch(18), db(changed), "diff2")
check("...but not when the switch is set AFTER that week (league.json still rules it)", d2 == base, first_diff(d2, base))
_, log, _ = build(without_switch(), db(changed), "shadowdiff")
check("shadow mode (switch off) prints the difference and still scores from league.json",
      "difference(s) between league.json and the app" in log and team in log, log[-500:])
d3, _, _ = build(without_switch(), db(changed), "shadowdiff2")
check("shadow mode: scores unchanged", d3 == base, first_diff(d3, base))

print("\nBad data must never crash the build or silently change a score")
# The switch is ON but the app's lineups can't be read. Scoring those weeks from league.json alone could flip published results
# (and flip them back on the next good run), so the build must STOP and publish nothing; the site keeps its last good results.
d, log, code = build(with_switch(8), None, "nofile")
check("switch set but no app file: the build STOPS (nothing published) with a clear message", code != 0 and d is None and "could not be read" in log and "last good results" in log, log[-300:])
for label, content in (("corrupt JSON", "{not json"), ("wrong shape (a list)", "[1,2,3]"), ("entries is not a list", '{"entries": 5}'), ("empty file", "")):
    d, log, code = build(with_switch(8), content, "bad")
    check("%s: the build STOPS (nothing published)" % label, code != 0 and d is None and "could not be read" in log, log[-300:])
d, log, code = build(without_switch(), None, "nofile_off")
check("switch OFF and no app file: builds normally, identical to baseline (today's real situation)", code == 0 and d == base, first_diff(d, base))
d, log, code = build(without_switch(), "{not json", "bad_off")
check("switch OFF and a corrupt app file: still builds normally (the app is only watched)", code == 0 and d == base, first_diff(d, base))
junk = [{"id": 801, "week": 12, "team": "No Such Team", "start": ["Scott Novak", "John Hussey"], "captain": None},
        {"id": 802, "week": 12, "team": team, "start": [roster[0], roster[0]], "captain": None},
        {"id": 803, "week": 12, "team": team, "start": [roster[0], next(c for t in LEAGUE["teams"] if t["name"] != team for c in t["crews"])], "captain": None},
        {"id": 804, "week": 12, "team": team, "start": roster[:2], "captain": roster[2]},
        {"id": 805, "week": 7, "team": team, "start": roster[:2], "captain": None},
        {"id": 806, "week": 99, "team": team, "start": roster[:2], "captain": None},
        {"id": 807, "week": 10, "team": team, "start": roster[:2], "captain": roster[0]},
        {"id": 808, "week": "twelve", "team": team, "start": roster[:2]},
        {"id": 809, "team": team},
        "not even a row",
        {"id": 810, "week": 12, "team": team, "start": "Scott Novak", "captain": None},
        {"id": 811, "week": 12, "team": team, "start": [roster[0], None], "captain": None}]
d, log, code = build(with_switch(8), db(rows + junk), "junk")
check("12 kinds of bad rows mixed in with good ones: builds and scores identical to baseline", code == 0 and d == base, log[-500:])
check("...each bad row is reported as skipped", log.count("skipped app lineup row") >= 11, log.count("skipped app lineup row"))
d, log, code = build(with_switch(8), db(junk), "onlyjunk")
check("ONLY bad rows: builds without crashing (every skipped row leaves league.json's earlier-week lineups standing)", code == 0 and d is not None, log[-300:])

print("\nSwitch value is validated")
for v in (7, "8", 8.5, True, -1):
    l = without_switch(); l["lineups_from_db_week"] = v
    _, log, code = build(l, db(rows), "badsw")
    check("lineups_from_db_week = %r is refused with a clear message" % (v,), code != 0 and "lineups_from_db_week" in log, log[-200:])

shutil.rmtree(tmp, ignore_errors=True)
print("\n%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
