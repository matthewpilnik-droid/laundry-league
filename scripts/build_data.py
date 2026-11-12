"""Build data.json for The Laundry League.

Usage: python3 -I scripts/build_data.py <cache_dir> <out_json>

Reads league.json (commissioner settings), data/referees.json (referee per
game), and the files fetch_data.py put in <cache_dir>. Until every team has
its crews, the page runs in preview mode with a mock league; after that it
scores the real league from start_week on.
"""
import csv, datetime, gzip, json, math, pathlib, re, sys, collections

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE, OUT = pathlib.Path(sys.argv[1]), sys.argv[2]
LEAGUE = json.loads((ROOT / "league.json").read_text())
SEASON = LEAGUE["season"]
CAL = SEASON - 1                      # calibration season for rare-call tiers

# ---- Scoring rules -------------------------------------------------------
PTS_PER_FLAG = 2
PTS_PER_YARD = 0.2            # 1 point per 5 yards, fractional
TIER_BONUS = {"common": 0, "uncommon": 4, "rare": 10, "unicorn": 20}
EJECTION_BONUS = 20
TD_WIPE_BONUS = 6
OVERTURN_PTS = -5             # crew's ruling reversed on review, or its flag picked up via replay
STOOD_TALL_PTS = 3            # a coach challenged the crew's ruling and lost
OFFSET_MULT = 2
CLUTCH_MULT = 1.5             # last 2:00 of the 2nd or 4th quarter

# Shared with the page's live scorer, so both read play text the same way.
PEN_PATTERN = (r"PENALTY on ([A-Z]{2,3})(?:-([^,]+?))?, ([^,.]+?)"
               r"(?:, (?:(\d+) yards?|(declined|offsetting|superseded))|, placed at)")
PEN = re.compile(PEN_PATTERN, re.I)
# A reversed play's text repeats the play: original ruling, "...the play was REVERSED.",
# then the final ruling. Only the final ruling scores.
REV_PATTERN = r"the play was REVERSED\.?"
REPLAY_PEN_PATTERN = r"The penalty was assisted by replay"
UPHELD_PATTERN = r"challenged [^.]*?the play was Upheld"
REV, REPLAY_PEN = re.compile(REV_PATTERN, re.I), re.compile(REPLAY_PEN_PATTERN, re.I)
UPHELD = re.compile(UPHELD_PATTERN, re.I)


def final_ruling(desc):
    return REV.split(desc)[-1]


def overturned(desc):
    """True when replay undid the crew's call: a reversal, or a flag gone after replay help."""
    return bool(REV.search(desc)) or (bool(REPLAY_PEN.search(desc)) and not PEN.search(final_ruling(desc)))


def tier_for(rate):
    if rate >= 0.3:
        return "common"
    if rate >= 0.1:
        return "uncommon"
    if rate >= 0.02:
        return "rare"
    return "unicorn"


def parse_flags(desc):
    out = []
    for team, player, ptype, yds, status in PEN.findall(desc):
        out.append({
            "team": team.upper(),
            "player": re.sub(r"^\d+-", "", player or "").strip(),
            "type": ptype.strip(),
            "yards": int(yds) if yds else 0,
            "status": (status or "accepted").lower(),
        })
    return out


def plays(path):
    for r in csv.DictReader(gzip.open(path, "rt")):
        d = r["desc"]
        if r["season_type"] == "REG" and ("PENALTY ON" in d.upper() or REV.search(d) or REPLAY_PEN.search(d)
                                          or UPHELD.search(d)):
            yield r


# ---- Schedule and referees ----------------------------------------------
games = {}
for r in csv.DictReader(open(CACHE / "games.csv")):
    if r["season"] in (str(CAL), str(SEASON)) and r["game_type"] == "REG":
        games[r["game_id"]] = r

# ESPN and nflverse spell some names differently ("Ronald" vs "Ron" Torbert).
# nflverse spellings are canonical; ESPN names map to them by unambiguous last name.
canon = {g["referee"] for g in games.values() if g["referee"]}

ref_file = ROOT / "data" / "referees.json"
known_refs = json.loads(ref_file.read_text()) if ref_file.exists() else {}
for gid, name in known_refs.items():
    if gid in games and not games[gid]["referee"]:
        games[gid]["referee"] = name

by_last = collections.defaultdict(set)
for n in canon:
    by_last[n.split()[-1].lower()].add(n)


def normalize(name):
    if not name or name in canon:
        return name
    cands = by_last.get(name.split()[-1].lower(), set())
    return next(iter(cands)) if len(cands) == 1 else name


for g in games.values():
    g["referee"] = normalize(g["referee"])

# ---- Calibrate rare-call tiers on the prior season -------------------------
# Lists are kept in a fixed (sorted) order and totals use math.fsum, an exact sum, so every
# build of the same data gives the same numbers. Adding floats in a different order can
# shift a total by a hair and tip a value sitting on a rounding edge (e.g. 90.6 vs 90.7).
g_cal = sorted(gid for gid, g in games.items() if g["season"] == str(CAL) and g["home_score"])
type_count = collections.Counter()
for r in plays(CACHE / f"pbp{CAL}.csv.gz"):
    for f in parse_flags(final_ruling(r["desc"])):
        type_count[f["type"]] += 1
tiers = {t: tier_for(c / len(g_cal)) for t, c in type_count.items()}


def score_play(r):
    """Return (scored flags, td_wipe_points, overturn_points, stood_tall_points) for one play row."""
    clutch = r["qtr"] in ("2", "4") and r["half_seconds_remaining"] != "" and \
        float(r["half_seconds_remaining"]) <= 120
    scored = []
    final = final_ruling(r["desc"])
    for f in parse_flags(final):
        eject = "disqualif" in f["type"].lower()
        tier = "ejection" if eject else tiers.get(f["type"], "unicorn")
        bonus = EJECTION_BONUS if eject else TIER_BONUS[tier]
        base = PTS_PER_FLAG + f["yards"] * PTS_PER_YARD + bonus
        mult = (OFFSET_MULT if f["status"] == "offsetting" else 1) * \
            (CLUTCH_MULT if clutch else 1)
        f.update(tier=tier, bonus=bonus, clutch=bool(clutch), pts=round(base * mult, 1))
        scored.append(f)
    u = final.upper()
    wipe = TD_WIPE_BONUS if ("TOUCHDOWN" in u and "NULLIFIED" in u) else 0
    return (scored, wipe, OVERTURN_PTS if overturned(r["desc"]) else 0,
            STOOD_TALL_PTS if UPHELD.search(r["desc"]) else 0)


def score_season(path):
    per_game = collections.defaultdict(lambda: {"flags": 0, "yards": 0, "pts": 0.0,
                                                 "wipes": 0, "overturns": 0, "stood": 0, "list": [],
                                                 "items": []})
    for r in plays(path):
        if r["game_id"] not in games:
            continue
        flags, wipe, over, stood = score_play(r)
        pg = per_game[r["game_id"]]
        for f in flags:
            pg["flags"] += 1
            pg["yards"] += f["yards"]
            pg["pts"] += f["pts"]
            f["qtr"], f["clock"] = r["qtr"], r["time"]
            pg["list"].append(f)
            pg["items"].append({"k": "flag", **f})
        # Non-flag scoring events, kept in play order with the flags for the drill-down.
        for kind, pts in (("wipe", wipe), ("over", over), ("stood", stood)):
            if pts:
                pg[{"wipe": "wipes", "over": "overturns", "stood": "stood"}[kind]] += 1
                pg["pts"] += pts
                pg["items"].append({"k": kind, "pts": pts, "qtr": r["qtr"], "clock": r["time"]})
    return per_game


s_cal = score_season(CACHE / f"pbp{CAL}.csv.gz")
s_cur = score_season(CACHE / f"pbp{SEASON}.csv.gz")

# A current-season game counts once it is final and in the play-by-play.
g_cur = [gid for gid, g in games.items()
         if g["season"] == str(SEASON) and g["home_score"] and gid in s_cur]
weeks_played = sorted({int(games[g]["week"]) for g in g_cur})
label = lambda g: f'{g["away_team"]} @ {g["home_team"]}'
PLAYOFF = LEAGUE["playoff_week"]


def resolve_crew(c, names):
    """Commissioner input: exact full name, or a last name alone if it matches exactly one."""
    c = c.strip()
    if c in names:
        return c
    hits = [n for n in names if n.split()[-1].lower() == c.lower()]
    return hits[0] if len(hits) == 1 else c


def drafted_referees():
    """The drafted real crews' referee names, or None before the draft is complete."""
    teams = LEAGUE["teams"]
    if not all(t["name"].strip() and len(t["crews"]) == LEAGUE["crews_per_team"] for t in teams):
        return None
    names = canon | {games[g]["referee"] for g in g_cur if games[g]["referee"]}
    return {resolve_crew(c, names) for t in teams for c in t["crews"] if "replacement" not in c.lower()}


drafted_refs = drafted_referees()

# ---- Game fixes (commissioner) -----------------------------------------------
# league.json "game_fixes", keyed by game id (e.g. "2026_09_TB_CHI"), one fix per game:
#   {"crew": "Shawn Hochuli"}     the game counts for this crew, whatever referee name the data
#                                 shows: a substitute referee working the crew's game, or a
#                                 spelling that doesn't match. The crew is the crew.
#   {"cancelled": "Ron Torbert"}  the game won't be played. The crew assigned to it scores the
#                                 open-spot share (open_spot_pct) of the week's average, and the
#                                 week stops waiting for the game.
real_crews = drafted_refs if drafted_refs is not None else \
    ({games[g]["referee"] for g in g_cur if games[g]["referee"]} or canon)
GID = re.compile(rf"{SEASON}_(\d\d)_[A-Z]{{2,3}}_[A-Z]{{2,3}}")
g_cur_set = set(g_cur)
credited, cancelled = {}, {}     # game id -> crew; game id -> {"week", "game", "crew"}
for gid, fx in LEAGUE.get("game_fixes", {}).items():
    where = f"league.json problem - game_fixes, {gid}"
    g = games.get(gid) if games.get(gid, {}).get("season") == str(SEASON) else None
    m = GID.fullmatch(gid)
    if not (isinstance(fx, dict) and len(fx) == 1 and next(iter(fx)) in ("crew", "cancelled")
            and isinstance(next(iter(fx.values())), str)):
        sys.exit(f'{where}: write {{"crew": "Name"}} or {{"cancelled": "Name"}}.')
    kind, raw = next(iter(fx.items()))
    # A cancelled game may drop off the schedule entirely; its id still says which week it was.
    if g is None and not (kind == "cancelled" and m):
        sys.exit(f"{where}: no {SEASON} regular-season game with that id (ids look like {SEASON}_09_TB_CHI).")
    crew = resolve_crew(raw, real_crews)
    if crew not in real_crews:
        sys.exit(f"{where}: '{raw}' isn't one of the real crews. Valid names: {sorted(real_crews)}")
    if kind == "crew":
        g["referee"] = crew
        credited[gid] = crew
    else:
        if gid in g_cur_set:
            sys.exit(f"{where}: this game was played, so it can't be marked cancelled.")
        cancelled[gid] = {"week": int(g["week"]) if g else int(m.group(1)), "game": label(g) if g else gid, "crew": crew}

unknown_ref = [gid for gid in g_cur if not games[gid]["referee"]]

# A week is final once every scheduled game that week is scored or cancelled.
sched_count = collections.Counter(int(g["week"]) for g in games.values() if g["season"] == str(SEASON))
done_count = collections.Counter(int(games[g]["week"]) for g in g_cur)
done_count.update(c["week"] for gid, c in cancelled.items() if gid in games)
week_final = {w: done_count[w] >= sched_count[w] > 0 for w in range(1, PLAYOFF + 1)}

# A crew works one game a week, so a fix mustn't hand a crew a second game.
seen = {}
for gid in g_cur + list(cancelled):
    w = cancelled[gid]["week"] if gid in cancelled else int(games[gid]["week"])
    crew = cancelled[gid]["crew"] if gid in cancelled else games[gid]["referee"]
    other = seen.setdefault((w, crew), gid) if crew else gid
    if other != gid and (credited.keys() | cancelled.keys()) & {gid, other}:
        sys.exit(f"league.json problem - game_fixes: {crew} would have two games in Week {w} "
                 f"({other} and {gid}). Check which game that crew actually worked.")
cancelled_crews = collections.defaultdict(dict)  # week -> crew -> label of its cancelled game
for c in cancelled.values():
    cancelled_crews[c["week"]][c["crew"]] = c["game"]


# ---- Hold a week whose referee isn't known ------------------------------------
# A scored game with no referee, or (once the draft is in) a referee who isn't one of the
# drafted crews, can't be credited to the right crew. Scoring it anyway would show that crew
# as off (0 points) and skew the weekly average. Instead the week is held: it isn't final,
# so no result in it counts, until the referee is known (usually by the next update), or
# the commissioner credits the game to a crew under "game_fixes".
held = []
for gid in g_cur:
    g, w = games[gid], int(games[gid]["week"])
    if not g["referee"]:
        why = "no referee listed yet"
    elif drafted_refs is not None and w >= LEAGUE["start_week"] and g["referee"] not in drafted_refs:
        why = f"referee \"{g['referee']}\" doesn't match a drafted crew"
    else:
        continue
    week_final[w] = False
    held.append({"week": w, "game": label(g), "gid": gid, "why": why})
held.sort(key=lambda h: (h["week"], h["gid"]))
held_gids = {h["gid"] for h in held}
for h in held:
    print(f'HOLD Week {h["week"]}: {h["game"]} ({h["gid"]}) - {h["why"]}', file=sys.stderr)

# ---- Crew summaries -------------------------------------------------------
crews = collections.defaultdict(lambda: {"gc": 0, "flags": 0, "yds": 0, "pts": [], "weeks": {}})
for gid in g_cal:
    c = crews[games[gid]["referee"]]
    pg = s_cal.get(gid, {"flags": 0, "yards": 0, "pts": 0})
    c["gc"] += 1
    c["flags"] += pg["flags"]
    c["yds"] += pg["yards"]
    c["pts"].append(pg["pts"])
for gid in g_cur:
    g, pg = games[gid], s_cur[gid]
    if g["referee"]:
        crews[g["referee"]]["weeks"][int(g["week"])] = {
            "game": label(g), "flags": pg["flags"], "yards": pg["yards"],
            "overturns": pg["overturns"], "stood": pg["stood"], "pts": round(pg["pts"], 1), "gid": gid}

# The current season's referees are the draftable pool; fall back to the
# calibration season's list early in a season.
# A held game's referee isn't a real crew (or isn't known), so it doesn't join the pool.
pool = {games[g]["referee"] for g in g_cur if games[g]["referee"] and g not in held_gids} or \
       {games[g]["referee"] for g in g_cal}
crew_list = []
for ref in sorted(pool):
    c = crews[ref]
    pts_cur = math.fsum(w["pts"] for w in c["weeks"].values())
    crew_list.append({
        "referee": ref,
        "g25": c["gc"],
        "flags25": round(c["flags"] / c["gc"], 1) if c["gc"] else None,
        "ppg25": round(math.fsum(c["pts"]) / c["gc"], 1) if c["gc"] else None,
        "g26": len(c["weeks"]),
        "pts26": round(pts_cur, 1),
        "ppg26": round(pts_cur / len(c["weeks"]), 1) if c["weeks"] else None,
        "weeks": c["weeks"],
    })

# The 2012 Replacement Refs: a draftable 18th "crew" that never has a bye and
# scores the average of every real crew that worked that week, once the week is final.
REPLACEMENT = "2012 Replacement Refs"
rr_weeks = {}
for w in weeks_played:
    worked = [c["weeks"][w]["pts"] for c in crew_list if w in c["weeks"]]
    if week_final[w] and worked:
        rr_weeks[w] = {"game": f"Weekly average of {len(worked)} crews", "flags": None,
                       "yards": None, "pts": round(math.fsum(worked) / len(worked), 1)}
rr_pts = math.fsum(x["pts"] for x in rr_weeks.values())
crew_list.append({
    "referee": REPLACEMENT, "replacement": True,
    "g25": None,
    "flags25": round(sum(s_cal[g]["flags"] for g in g_cal if g in s_cal) / len(g_cal), 1),
    "ppg25": round(math.fsum(s_cal[g]["pts"] for g in g_cal if g in s_cal) / len(g_cal), 1),
    "g26": len(rr_weeks),
    "pts26": round(rr_pts, 1),
    "ppg26": round(rr_pts / len(rr_weeks), 1) if rr_weeks else None,
    "weeks": rr_weeks,
})
# Ties broken by name so the order (and the preview mock draft) is the same on every run.
crew_list.sort(key=lambda c: (-(c["ppg25"] or 0), c["referee"]))
by_ref = {c["referee"]: c for c in crew_list}

# ---- Latest week detail ----------------------------------------------------
last = max(weeks_played) if weeks_played else None
week_games = []
for gid in g_cur:
    g, pg = games[gid], s_cur[gid]
    if int(g["week"]) != last or not pg["list"]:
        continue
    top = max(pg["list"], key=lambda f: f["pts"])
    week_games.append({
        "referee": g["referee"] or "Unknown", "game": label(g), "day": g["weekday"],
        "flags": pg["flags"], "yards": pg["yards"], "overturns": pg["overturns"], "stood": pg["stood"],
        "pts": round(pg["pts"], 1),
        "top": {k: top[k] for k in ("type", "team", "player", "yards", "pts", "tier",
                                     "status", "clutch", "qtr", "clock")},
    })
week_games.sort(key=lambda x: -x["pts"])

# ---- Season highlights -------------------------------------------------------
all_cur = []
for gid in g_cur:
    g = games[gid]
    for f in s_cur[gid]["list"]:
        all_cur.append({**{k: f[k] for k in ("type", "team", "player", "yards", "pts",
                                              "tier", "status", "clutch", "qtr", "clock")},
                        "week": int(g["week"]), "referee": g["referee"], "game": label(g)})
top_flags = sorted(all_cur, key=lambda f: -f["pts"])[:8]
sightings = [f for f in all_cur if f["tier"] in ("unicorn", "ejection")]

# ---- League engine: head-to-head, 3 crews per team, 2 starters a week -------
ROSTER = LEAGUE["crews_per_team"]
STARTERS = LEAGUE["starters_per_week"]
START = LEAGUE["start_week"]
REG_END = LEAGUE["regular_season_end"]
teams_cfg = LEAGUE["teams"]
lineups_cfg = LEAGUE.get("lineups", [])
# Open spot: when a team has fewer crews with a game than starting spots, each starting
# spot it can't fill scores this percent of the week's average (the Replacement Refs' score).
OPEN_PCT = LEAGUE.get("open_spot_pct", 85)
if not isinstance(OPEN_PCT, (int, float)) or isinstance(OPEN_PCT, bool) or not 0 <= OPEN_PCT <= 100:
    sys.exit(f"league.json problem - open_spot_pct must be a number from 0 to 100, not {OPEN_PCT!r}.")
drafted = all(t["name"].strip() and len(t["crews"]) == ROSTER for t in teams_cfg)
partly = any(t["crews"] for t in teams_cfg) and not drafted
if len(teams_cfg) % 2:
    sys.exit("league.json problem - head-to-head needs an even number of teams.")


def roster_name(c):
    """Commissioner input: exact full name, or last name alone if unambiguous."""
    c = c.strip()
    if c in by_ref:
        return c
    if "replacement" in c.lower():
        return REPLACEMENT
    hits = [r for r in by_ref if r.split()[-1].lower() == c.lower()]
    return hits[0] if len(hits) == 1 else c


def round_robin(names):
    """Circle method: every team plays every other team once per cycle."""
    arr, n, rounds = list(names), len(names), []
    for _ in range(n - 1):
        rounds.append([(arr[i], arr[n - 1 - i]) for i in range(n // 2)])
        arr = [arr[0], arr[-1]] + arr[1:-1]
    return rounds


def make_schedule(names, start):
    rr, sched = round_robin(names), {}
    for w in range(start, REG_END + 1):
        i = w - start
        pairs = rr[i % len(rr)]
        if (i // len(rr)) % 2:                    # second cycle swaps home and away
            pairs = [(b, a) for a, b in pairs]
        sched[w] = pairs
    return sched


def has_game(c, w):
    """A crew "has a game" if it worked one, or its assigned game was cancelled (it still scores)."""
    return c == REPLACEMENT or w in by_ref[c]["weeks"] or c in cancelled_crews.get(w, {})


def weekly_starters(roster, lineups, start):
    """Replay the commissioner's lineup entries; a lineup stands until the team sends a new one.
    With no entry yet, a team starts the first crews listed on its roster."""
    cur = {t: cs[:STARTERS] for t, cs in roster.items()}
    ordered = sorted(enumerate(lineups), key=lambda x: (x[1]["week"], x[0]))
    out, i = {}, 0
    for w in range(start, PLAYOFF + 1):
        while i < len(ordered) and ordered[i][1]["week"] <= w:
            n, l = ordered[i]
            team, picks = l["team"], [roster_name(c) for c in l["start"]]
            where = f'lineups entry {n + 1} (week {l["week"]}, {team})'
            if team not in roster:
                sys.exit(f"league.json problem - {where}: no team named '{team}'.")
            if len(set(picks)) != STARTERS:
                sys.exit(f"league.json problem - {where}: list exactly {STARTERS} different crews to start.")
            off = [c for c in picks if c not in roster[team]]
            if off:
                sys.exit(f"league.json problem - {where}: {off} not on {team}'s roster {roster[team]}.")
            cur[team] = picks
            i += 1
        out[w] = {t: list(c) for t, c in cur.items()}
    return out


def mock_starters(roster, start):
    """Preview only: each mock owner starts the first listed crews that have a game that week."""
    out = {}
    for w in range(start, PLAYOFF + 1):
        out[w] = {}
        for t, cs in roster.items():
            working = [c for c in cs if has_game(c, w) or not week_final[w]]
            out[w][t] = (working + [c for c in cs if c not in working])[:STARTERS]
    return out


def mock_league():
    """Preview: a mock league snake-drafted by last season's points per game, played from Week 1."""
    names = ["Holding Pattern", "False Start Kids", "Laundry Day",
             "Flag on the Play", "Pick Up the Flag", "Yellow Hankies"][:len(teams_cfg)]
    order = [c["referee"] for c in crew_list]
    init, pick = {n: [] for n in names}, 0
    for rnd in range(ROSTER):
        for n in (names if rnd % 2 == 0 else names[::-1]):
            init[n].append(order[pick])
            pick += 1
    return names, {n: "" for n in names}, init, mock_starters(init, 1), 1


PLAYOFF_NAMES = ["Laundry Bowl", "Third-place game", "Delicates Bowl"]


def play_season(names, managers, init, starters, lg_start):
    """Head-to-head weeks, standings, Week 18 playoffs and weekly awards for one league."""
    schedule = make_schedule(names, lg_start)
    rosters = {w: {t: list(cs) for t, cs in init.items()} for w in range(lg_start, PLAYOFF + 1)}

    def crew_week(c, w):
        """Score and status of one crew in one week."""
        wk = by_ref[c]["weeks"].get(w)
        if wk:
            return {"crew": c, "pts": wk["pts"], "game": wk["game"], "status": "final"}
        if c == REPLACEMENT:
            return {"crew": c, "pts": 0, "game": None, "status": "pending"}
        if c in cancelled_crews.get(w, {}):
            # Its game was cancelled: the open-spot share of the week's average, once the week is final.
            avg = rr_weeks[w]["pts"] if week_final[w] and w in rr_weeks else None
            return {"crew": c, "pts": round(avg * OPEN_PCT / 100, 1) if avg is not None else 0,
                    "game": cancelled_crews[w][c], "status": "cancelled", "avg": avg, "pct": OPEN_PCT}
        return {"crew": c, "pts": 0, "game": None, "status": "bye" if week_final[w] else "pending"}

    def team_week(t, w):
        lines = [{**crew_week(c, w), "starter": c in starters[w][t]} for c in rosters[w][t]]
        lines.sort(key=lambda x: not x["starter"])               # starters first, bench last
        # Open spots: a team with fewer crews working than starting spots gets credit for each
        # spot it couldn't fill. An idle starter beyond that count is a lineup mistake and scores 0.
        if week_final[w] and w in rr_weeks:
            spots = max(0, STARTERS - sum(1 for c in rosters[w][t] if has_game(c, w)))
            avg = rr_weeks[w]["pts"]
            for x in lines:
                if spots and x["starter"] and x["status"] == "bye":
                    x.update(status="open", pts=round(avg * OPEN_PCT / 100, 1), avg=avg, pct=OPEN_PCT)
                    spots -= 1
        return {"crews": lines, "pts": round(sum(x["pts"] for x in lines if x["starter"]), 1)}

    rec = {n: {"w": 0, "l": 0, "t": 0, "pf": 0.0, "pa": 0.0, "results": []} for n in names}
    series = collections.defaultdict(lambda: [0, 0, 0])      # "A|B" (sorted) -> A wins, B wins, ties
    weeks_out = []
    for w in range(lg_start, REG_END + 1):
        games_w = []
        for a, b in schedule[w]:
            A, B = team_week(a, w), team_week(b, w)
            m = {"a": a, "b": b, "A": A, "B": B, "final": week_final[w], "winner": None}
            if week_final[w]:
                for x, y, X, Y in ((a, b, A, B), (b, a, B, A)):
                    rec[x]["pf"] += X["pts"]
                    rec[x]["pa"] += Y["pts"]
                key, flip = "|".join(sorted((a, b))), sorted((a, b))[0] != a
                if A["pts"] == B["pts"]:
                    rec[a]["t"] += 1; rec[b]["t"] += 1
                    rec[a]["results"].append("T"); rec[b]["results"].append("T")
                    series[key][2] += 1
                else:
                    win, lose = (a, b) if A["pts"] > B["pts"] else (b, a)
                    m["winner"] = win
                    rec[win]["w"] += 1; rec[lose]["l"] += 1
                    rec[win]["results"].append("W"); rec[lose]["results"].append("L")
                    series[key][0 if (win == a) != flip else 1] += 1
            games_w.append(m)
        weeks_out.append({"week": w, "final": week_final[w], "playoff": False, "games": games_w})

    def standing_key(n):
        r = rec[n]
        return (-(r["w"] + 0.5 * r["t"]), -r["pf"])

    order_now = sorted(names, key=standing_key)
    standings = []
    for n in order_now:
        r = rec[n]
        res = r["results"]
        streak = ""
        if res:
            last_r = res[-1]
            k = 1
            while k < len(res) and res[-1 - k] == last_r:
                k += 1
            streak = f"{last_r}{k}"
        standings.append({"team": n, "manager": managers.get(n, ""), "w": r["w"], "l": r["l"],
                          "t": r["t"], "pf": round(r["pf"], 1), "pa": round(r["pa"], 1),
                          "streak": streak})

    # Week 18: seeds 1 v 2 for the title, 3 v 4, 5 v 6.
    reg_done = all(week_final[w] for w in range(lg_start, REG_END + 1))
    po_games = []
    for i in range(0, len(order_now), 2):
        a, b = order_now[i], order_now[i + 1]
        m = {"a": a, "b": b, "seeds": [i + 1, i + 2], "name": PLAYOFF_NAMES[i // 2] if i // 2 < 3 else f"Seeds {i+1}-{i+2}",
             "set": reg_done, "final": week_final[PLAYOFF] and reg_done, "winner": None}
        if reg_done:
            m["A"], m["B"] = team_week(a, PLAYOFF), team_week(b, PLAYOFF)
            if m["final"] and m["A"]["pts"] != m["B"]["pts"]:
                m["winner"] = a if m["A"]["pts"] > m["B"]["pts"] else b
        po_games.append(m)
    weeks_out.append({"week": PLAYOFF, "final": week_final[PLAYOFF] and reg_done, "playoff": True,
                      "games": po_games})

    # Weekly awards for final weeks. Only starters' flags count; the Replacement Refs throw none.
    awards = {}
    for wk in weeks_out:
        if not wk["final"]:
            continue
        w = wk["week"]
        best, over = None, {}
        for t in names:
            for c in starters[w][t]:
                info = by_ref[c]["weeks"].get(w)
                if not info or "gid" not in info:
                    continue
                if info["overturns"]:
                    over.setdefault(t, []).append({"crew": c, "n": info["overturns"], "game": info["game"]})
                for f in s_cur[info["gid"]]["list"]:
                    if best is None or f["pts"] > best["pts"]:
                        best = {"team": t, "crew": c, "type": f["type"], "pts": f["pts"],
                                "tier": f["tier"], "nfl_team": f["team"], "player": f["player"],
                                "game": info["game"], "status": f["status"], "clutch": f["clutch"]}
        top = max((sum(x["n"] for x in cs) for cs in over.values()), default=0)
        awards[w] = {"golden_flag": best,
                     "overturned": {"n": top, "pts": top * OVERTURN_PTS,
                                    "teams": [{"team": t, "crews": cs} for t, cs in over.items()
                                              if sum(x["n"] for x in cs) == top]} if top else None}

    return {
        "league_start": lg_start,
        # The week to feature: the first league week that isn't final.
        "current_week": next((w["week"] for w in weeks_out if not w["final"]), PLAYOFF),
        "teams": [{"team": n, "manager": managers.get(n, "")} for n in names],
        "rosters": {str(w): r for w, r in rosters.items()},
        "starters": {str(w): s for w, s in starters.items()},
        "weeks": weeks_out,
        "standings": standings,
        "series": dict(series),
        "awards": awards,
    }


if drafted:
    names = [t["name"].strip() for t in teams_cfg]
    managers = {t["name"].strip(): t.get("manager", "") for t in teams_cfg}
    init = {t["name"].strip(): [roster_name(c) for c in t["crews"]] for t in teams_cfg}
    picks = [c for r in init.values() for c in r]
    bad = [c for c in picks if c not in by_ref]
    dupes = [c for c, n in collections.Counter(picks).items() if n > 1]
    if bad or dupes:
        sys.exit(f"league.json problem - unknown crews: {bad}, drafted twice: {dupes}. "
                 f"Valid names: {sorted(by_ref)}")
    league = play_season(names, managers, init, weekly_starters(init, lineups_cfg, START), START)
    # Once live, the mock league stays on the page as a "what a season looks like" sample.
    sample = play_season(*mock_league())
else:
    league, sample = play_season(*mock_league()), None

# Crews the commissioner marked as off (no assignment) ahead of each week,
# from Football Zebras' posted assignments. Shown on the site before games are played.
off_weeks = {}
for w, cs in LEAGUE.get("off", {}).items():
    names = [roster_name(c) for c in cs if c.strip()]
    bad = [c for c in names if c not in by_ref or c == REPLACEMENT]
    if bad:
        sys.exit(f"league.json problem - off, Week {w}: unknown crews {bad}. "
                 f"Valid names: {sorted(c for c in by_ref if c != REPLACEMENT)}")
    off_weeks[str(int(w))] = names

# The real draft as entered so far. Teams are listed in draft-slot order, so the
# site's draft board can lay out the snake before the league goes live.
draft = [{"team": t["name"].strip(), "manager": t.get("manager", ""),
          "picks": [roster_name(c) if c.strip() else "" for c in t["crews"]]} for t in teams_cfg]


# ---- Tier reference and dates ----------------------------------------------
tier_table = sorted(
    [{"type": t, "per_game": round(c / len(g_cal), 3), "season": c, "tier": tiers[t]}
     for t, c in type_count.items()], key=lambda x: -x["season"])
start_dates = sorted(g["gameday"] for g in games.values()
                     if g["season"] == str(SEASON) and int(g["week"]) == START)
scored_espn = sorted(games[g]["espn"] for g in g_cur if games[g]["espn"])

# ---- Score drill-down ----------------------------------------------------------
# Every scoring line behind each crew's game total, for league weeks only, keyed by game id
# (crews[].weeks[w].gid). k = "flag", "wipe" (a flag wiped out a touchdown), "over" (call
# overturned) or "stood" (coach's challenge failed); flags also carry their call details.
# ---- League weeks' games, for the commissioner page ------------------------------
schedule_out = collections.defaultdict(list)
for gid, g in sorted(games.items()):
    if g["season"] == str(SEASON) and START <= int(g["week"]) <= PLAYOFF:
        schedule_out[str(int(g["week"]))].append(
            {"gid": gid, "game": label(g), "referee": g["referee"] or "", "played": gid in g_cur_set})
for gid, c in cancelled.items():          # a cancelled game that's gone from the schedule
    if gid not in games:
        schedule_out[str(c["week"])].append({"gid": gid, "game": gid, "referee": "", "played": False})
schedule_out = dict(sorted(schedule_out.items(), key=lambda kv: int(kv[0])))

LEDGER_KEYS = ("k", "type", "team", "player", "yards", "tier", "status", "clutch", "qtr", "clock", "pts")
ledger = {}
for gid in g_cur:
    if int(games[gid]["week"]) < league["league_start"]:
        continue
    items = [{k: it[k] for k in LEDGER_KEYS if k in it} for it in s_cur[gid]["items"]]
    total, scored = round(sum(it["pts"] for it in items), 1), round(s_cur[gid]["pts"], 1)
    if abs(total - scored) > 0.05:
        # Display-only feature: warn and skip this game's list rather than stop the score update.
        print(f"WARNING drill-down skipped - {gid}: lines add to {total}, but the game scored {scored}",
              file=sys.stderr)
        continue
    ledger[gid] = items

json.dump({
    "league_name": LEAGUE["league_name"],
    "season": SEASON, "cal_season": CAL,
    "mode": "live" if drafted else "preview",
    "partly_drafted": partly,
    "start_week": START, "league_start": league["league_start"],
    "regular_season_end": REG_END, "playoff_week": PLAYOFF,
    "start_date": start_dates[0] if start_dates else None,
    "crews_per_team": ROSTER, "starters_per_week": STARTERS,
    "replacement": REPLACEMENT,
    "open_spot_pct": OPEN_PCT,
    "lineup_deadline": LEAGUE.get("lineup_deadline", ""),
    "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
    "updated": max(games[g]["gameday"] for g in g_cur) if g_cur else None,
    "last_week": last,
    "weeks_played": weeks_played,
    "current_week": league["current_week"],
    "calibration_games": len(g_cal),
    "avg_ppg25": round(math.fsum(s_cal[g]["pts"] for g in g_cal if g in s_cal) / len(g_cal), 1),
    "avg_flags25": round(sum(s_cal[g]["flags"] for g in g_cal if g in s_cal) / len(g_cal), 1),
    "rules": {"per_flag": PTS_PER_FLAG, "per_yard": PTS_PER_YARD, "tiers": TIER_BONUS,
              "ejection": EJECTION_BONUS, "td_wipe": TD_WIPE_BONUS, "overturn": OVERTURN_PTS,
              "stood_tall": STOOD_TALL_PTS,
              "offset_mult": OFFSET_MULT, "clutch_mult": CLUTCH_MULT},
    "pen_pattern": PEN_PATTERN,
    "rev_pattern": REV_PATTERN,
    "replay_pen_pattern": REPLAY_PEN_PATTERN,
    "upheld_pattern": UPHELD_PATTERN,
    "tier_of": tiers,
    "ref_last_names": {k: next(iter(v)) for k, v in sorted(by_last.items()) if len(v) == 1},
    "scored_espn": scored_espn,
    "crews": crew_list,
    "draft": draft,
    "off_weeks": off_weeks,
    "week_games": week_games,
    "top_flags": top_flags,
    "sightings": sightings,
    "ledger": ledger,
    **{k: league[k] for k in ("teams", "rosters", "starters", "weeks", "standings", "series", "awards")},
    "sample": sample,
    "tier_table": tier_table,
    "unknown_ref_games": unknown_ref,
    # Games whose week is on hold until their referee is known (see "Hold a week" above).
    "held": held,
    # Every league week's games, for the commissioner page's game fixes.
    "schedule": schedule_out,
    "game_fixes": {gid: {"crew": c} for gid, c in credited.items()} |
                  {gid: {"cancelled": c["crew"]} for gid, c in cancelled.items()},
}, open(OUT, "w"), indent=1)
print(f"wrote {OUT} | mode {'live' if drafted else 'preview'} | crews {len(crew_list)} "
      f"| weeks {weeks_played} | current league week {league['current_week']} | games missing a referee: {len(unknown_ref)} "
      f"| weeks on hold: {sorted({h['week'] for h in held}) or 'none'}")
