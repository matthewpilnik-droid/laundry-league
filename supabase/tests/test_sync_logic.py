"""Tests for scripts/sync_supabase.py. No network, no key: the database is replaced by a recording stand-in.
Run:  python3 -I supabase/tests/test_sync_logic.py
"""
import importlib.util, json, pathlib, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("sync", ROOT / "scripts" / "sync_supabase.py")
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)

passed = failed = 0
def check(label, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print("PASS -", label)
    else: failed += 1; print("FAIL - %s   [%s]" % (label, extra))

def game(gid, date, time, ref=""):
    return {"gid": gid, "game": gid, "referee": ref, "played": False, "day": "", "date": date, "time": time}

# ---- the rules, on made-up data
data = {"season": 2026,
        "schedule": {"12": [
            game("2026_12_A_B", "2026-11-01", "13:00", "Alex Moore"),     # day DST ends in the US (EST from 1:00 am)
            game("2026_12_C_D", "2026-10-25", "13:00", ""),               # before DST ends (EDT)
            game("2026_12_E_F", "2026-11-02", "20:15", ""),               # no actual ref: provisional used
            game("2026_12_G_H", "2026-11-02", "20:15", "Ron Torbert"),    # fix credits it to another crew
            game("2026_12_I_J", "2026-11-02", "13:00", "Scott Novak"),    # cancelled
            game("2026_12_K_L", "", "", "Brad Allen"),                    # no kickoff known
            game("2026_12_M_N", "2026-11-02", "13:00", ""),               # no referee known anywhere
          ],
          "13": [game("2026_13_A_B", "2026-11-08", "13:00")],             # kickoff but no crew at all
          "14": []},
        "assignments": {"12": {"games": {"2026_12_C_D": "Shawn Smith", "2026_12_E_F": "Land Clark"}}},
        "game_fixes": {"2026_12_G_H": {"crew": "Brad Rogers"}, "2026_12_I_J": {"cancelled": "Scott Novak"}}}
weeks, slots, warns = sync.build_rows(data)
S = {(s["week"], s["crew"]): s["kickoff_at"] for s in slots}
check("actual referee used", (12, "Alex Moore") in S)
check("13:00 ET on Nov 1 (after DST ends) = 18:00 UTC", S[(12, "Alex Moore")].startswith("2026-11-01T18:00"), S.get((12, "Alex Moore")))
check("13:00 ET on Oct 25 (still daylight time) = 17:00 UTC", S[(12, "Shawn Smith")].startswith("2026-10-25T17:00"), S.get((12, "Shawn Smith")))
check("provisional referee used when no actual one", (12, "Land Clark") in S)
check("game fix credits the other crew", (12, "Brad Rogers") in S and (12, "Ron Torbert") not in S)
check("cancelled game skipped", (12, "Scott Novak") not in S)
check("game with no kickoff skipped", (12, "Brad Allen") not in S)
check("game with no referee anywhere makes no slot", len(slots) == 4, str(slots))
w12 = [w for w in weeks if w["week"] == 12][0]
check("week starts at its first kickoff", w12["starts_at"].startswith("2026-10-25T17:00"), w12["starts_at"])
check("week ends one day after its last kickoff", w12["ends_at"].startswith("2026-11-04T01:15"), w12["ends_at"])
check("week with kickoffs but no crews still gets a weeks row", any(w["week"] == 13 for w in weeks))
check("week with no games gets no weeks row (managers stay locked out)", not any(w["week"] == 14 for w in weeks))
_, dup_slots, dup_warns = sync.build_rows({"season": 2026, "assignments": {}, "game_fixes": {}, "schedule": {"5": [
    game("g1", "2026-09-13", "13:00", "X Y"), game("g2", "2026-09-13", "16:25", "X Y")]}})
check("a crew in two games: warns and keeps the earlier kickoff", len(dup_slots) == 1 and dup_slots[0]["kickoff_at"].startswith("2026-09-13T17:00") and dup_warns, str(dup_slots))
_, _, bad = sync.build_rows({"season": 2026, "assignments": {}, "game_fixes": {}, "schedule": {"5": [game("g1", "2026-09-13", "bogus", "X Y")]}})
check("unreadable kickoff time: skipped with a warning, no crash", len(bad) == 1)

# ---- the real data.json
real = json.loads((ROOT / "data.json").read_text())
rw, rs, _ = sync.build_rows(real)
check("real data: at least one week and crew kickoff", bool(rw) and bool(rs))
check("real data: no crew twice in a week", len({(s["week"], s["crew"]) for s in rs}) == len(rs))
wk = {w["week"]: w for w in rw}
check("real data: every kickoff falls inside its week", all(wk[s["week"]]["starts_at"] <= s["kickoff_at"] <= wk[s["week"]]["ends_at"] for s in rs))
known = {c["referee"] for c in real["crews"]}
check("real data: every crew name to be written is a known crew in the league's crew list",
      {s["crew"] for s in rs} <= known, str(sorted({s["crew"] for s in rs} - known)))

# ---- the writing order, with a recording stand-in for the database
class Fake:
    log, fail_on, existing = [], None, {}
    def __init__(self, url, key): pass
    def call(self, method, path, body=None, prefer=None):
        Fake.log.append((method, path.split("?")[0] + ("?" + path.split("?")[1] if method != "POST" and "?" in path else ""), body))
        if Fake.fail_on and Fake.fail_on in path:
            raise RuntimeError("boom")
        if method == "GET":
            wk = path.split("week=eq.")[1]
            return [{"crew": c} for c in Fake.existing.get(int(wk), [])]
        return None

def run_main(existing=None, fail_on=None):
    Fake.log, Fake.existing, Fake.fail_on = [], existing or {}, fail_on
    sync.Api, sync.load_config = Fake, lambda: ("https://example.invalid", "KEY")
    d = pathlib.Path(tempfile.mkdtemp()); (d / "data.json").write_text(json.dumps(data)); sync.ROOT = d
    sys.argv = ["x", "--apply"]
    try:
        sync.main(); return None
    except (RuntimeError, SystemExit) as e:
        return e

err = run_main(existing={12: ["Alex Moore", "Old Crew"]})
kinds = [(m, p.split("?")[0]) for m, p, _ in Fake.log]
check("order: weeks, then game_slots, then stale removal, then heartbeat last",
      kinds[0] == ("POST", "/rest/v1/weeks") and kinds[1] == ("POST", "/rest/v1/game_slots") and kinds[-1] == ("POST", "/rest/v1/sync_status"), str(kinds))
dels = [p for m, p, _ in Fake.log if m == "DELETE"]
check("a crew no longer assigned is removed, and only that crew", len(dels) == 1 and "crew=eq.Old%20Crew" in dels[0], str(dels))
check("heartbeat stamped after success", Fake.log[-1][2][0]["key"] == "kickoffs")
err = run_main(fail_on="game_slots")
check("a failed write stops the run and leaves NO heartbeat", isinstance(err, RuntimeError) and not any("sync_status" in p for _, p, _ in Fake.log), str(err))
err = run_main(fail_on="weeks")
check("failure before any slot write: nothing else is written", isinstance(err, RuntimeError) and len(Fake.log) == 1, str(Fake.log))

print("\n%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
