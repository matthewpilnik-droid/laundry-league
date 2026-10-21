"""Build data.json for The Laundry League.

Usage: python3 -I scripts/build_data.py <cache_dir> <out_json>

Reads league.json (commissioner settings), data/referees.json (referee per
game), and the files fetch_data.py put in <cache_dir>. Until every team has
its crews, the page runs in preview mode with a mock league; after that it
scores the real league from start_week on.
"""
import csv, datetime, gzip, json, pathlib, re, sys, collections

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
OFFSET_MULT = 2
CLUTCH_MULT = 1.5             # last 2:00 of the 2nd or 4th quarter

# Shared with the page's live scorer, so both read play text the same way.
PEN_PATTERN = (r"PENALTY on ([A-Z]{2,3})(?:-([^,]+?))?, ([^,.]+?)"
               r"(?:, (?:(\d+) yards?|(declined|offsetting|superseded))|, placed at)")
PEN = re.compile(PEN_PATTERN, re.I)


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
        if r["season_type"] == "REG" and "PENALTY ON" in r["desc"].upper():
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
g_cal = {gid for gid, g in games.items() if g["season"] == str(CAL) and g["home_score"]}
type_count = collections.Counter()
for r in plays(CACHE / f"pbp{CAL}.csv.gz"):
    for f in parse_flags(r["desc"]):
        type_count[f["type"]] += 1
tiers = {t: tier_for(c / len(g_cal)) for t, c in type_count.items()}


def score_play(r):
    """Return (list of scored flags, td_wipe_points) for one play row."""
    clutch = r["qtr"] in ("2", "4") and r["half_seconds_remaining"] != "" and \
        float(r["half_seconds_remaining"]) <= 120
    scored = []
    for f in parse_flags(r["desc"]):
        eject = "disqualif" in f["type"].lower()
        tier = "ejection" if eject else tiers.get(f["type"], "unicorn")
        bonus = EJECTION_BONUS if eject else TIER_BONUS[tier]
        base = PTS_PER_FLAG + f["yards"] * PTS_PER_YARD + bonus
        mult = (OFFSET_MULT if f["status"] == "offsetting" else 1) * \
            (CLUTCH_MULT if clutch else 1)
        f.update(tier=tier, bonus=bonus, clutch=bool(clutch), pts=round(base * mult, 1))
        scored.append(f)
    u = r["desc"].upper()
    wipe = TD_WIPE_BONUS if ("TOUCHDOWN" in u and "NULLIFIED" in u) else 0
    return scored, wipe


def score_season(path):
    per_game = collections.defaultdict(lambda: {"flags": 0, "yards": 0, "pts": 0.0,
                                                 "wipes": 0, "list": []})
    for r in plays(path):
        if r["game_id"] not in games:
            continue
        flags, wipe = score_play(r)
        pg = per_game[r["game_id"]]
        for f in flags:
            pg["flags"] += 1
            pg["yards"] += f["yards"]
            pg["pts"] += f["pts"]
            f["qtr"], f["clock"] = r["qtr"], r["time"]
            pg["list"].append(f)
        if wipe:
            pg["wipes"] += 1
            pg["pts"] += wipe
    return per_game


s_cal = score_season(CACHE / f"pbp{CAL}.csv.gz")
s_cur = score_season(CACHE / f"pbp{SEASON}.csv.gz")

# A current-season game counts once it is final and in the play-by-play.
g_cur = [gid for gid, g in games.items()
         if g["season"] == str(SEASON) and g["home_score"] and gid in s_cur]
unknown_ref = [gid for gid in g_cur if not games[gid]["referee"]]
weeks_played = sorted({int(games[g]["week"]) for g in g_cur})
label = lambda g: f'{g["away_team"]} @ {g["home_team"]}'

# ---- Crew summaries -------------------------------------------------------
crews = collections.defaultdict(lambda: {"gc": 0, "flags": 0, "yds": 0, "pts": 0.0, "weeks": {}})
for gid in g_cal:
    c = crews[games[gid]["referee"]]
    pg = s_cal.get(gid, {"flags": 0, "yards": 0, "pts": 0})
    c["gc"] += 1
    c["flags"] += pg["flags"]
    c["yds"] += pg["yards"]
    c["pts"] += pg["pts"]
for gid in g_cur:
    g, pg = games[gid], s_cur[gid]
    if g["referee"]:
        crews[g["referee"]]["weeks"][int(g["week"])] = {
            "game": label(g), "flags": pg["flags"], "yards": pg["yards"],
            "pts": round(pg["pts"], 1)}

# The current season's referees are the draftable pool; fall back to the
# calibration season's list early in a season.
pool = {games[g]["referee"] for g in g_cur if games[g]["referee"]} or \
       {games[g]["referee"] for g in g_cal}
crew_list = []
for ref in pool:
    c = crews[ref]
    pts_cur = sum(w["pts"] for w in c["weeks"].values())
    crew_list.append({
        "referee": ref,
        "g25": c["gc"],
        "flags25": round(c["flags"] / c["gc"], 1) if c["gc"] else None,
        "ppg25": round(c["pts"] / c["gc"], 1) if c["gc"] else None,
        "g26": len(c["weeks"]),
        "pts26": round(pts_cur, 1),
        "ppg26": round(pts_cur / len(c["weeks"]), 1) if c["weeks"] else None,
        "weeks": c["weeks"],
    })
crew_list.sort(key=lambda c: -(c["ppg25"] or 0))
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
        "flags": pg["flags"], "yards": pg["yards"], "pts": round(pg["pts"], 1),
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

# ---- League: real rosters once drafted, otherwise a mock league ------------
N_CREWS, N_COUNT = LEAGUE["crews_per_team"], LEAGUE["counting_crews"]
START = LEAGUE["start_week"]
teams = LEAGUE["teams"]
drafted = all(len(t["crews"]) == N_CREWS for t in teams)
partly = any(t["crews"] for t in teams) and not drafted
def roster_name(c):
    """Commissioner input: exact full name, or last name alone if unambiguous."""
    c = c.strip()
    if c in by_ref:
        return c
    hits = [r for r in by_ref if r.split()[-1].lower() == c.lower()]
    return hits[0] if len(hits) == 1 else c


if drafted:
    picks = [roster_name(c) for t in teams for c in t["crews"]]
    bad = [c for c in picks if c not in by_ref]
    dupes = [c for c, n in collections.Counter(picks).items() if n > 1]
    if bad or dupes:
        sys.exit(f"league.json problem - unknown crews: {bad}, drafted twice: {dupes}. "
                 f"Valid names: {sorted(by_ref)}")
    rosters = [{"team": t["name"], "manager": t.get("manager", ""),
                "crews": [roster_name(c) for c in t["crews"]]} for t in teams]
    league_weeks = [w for w in weeks_played if w >= START]
else:
    names = ["Holding Pattern", "False Start Kids", "Laundry Day",
             "Flag on the Play", "Pick Up the Flag"]
    order = [c["referee"] for c in crew_list]
    rosters = [{"team": n, "manager": "", "crews": []} for n in names]
    pick = 0
    for rnd in range(N_CREWS):
        seq = rosters if rnd % 2 == 0 else rosters[::-1]
        for r in seq:
            r["crews"].append(order[pick])
            pick += 1
    league_weeks = weeks_played

taken = {c for r in rosters for c in r["crews"]}
standings = []
for r in rosters:
    wk = {}
    for w in league_weeks:
        scores = sorted((by_ref[c]["weeks"].get(w, {}).get("pts", 0) for c in r["crews"]),
                        reverse=True)
        wk[w] = round(sum(scores[:N_COUNT]), 1)
    standings.append({**r, "weeks": wk, "total": round(sum(wk.values()), 1)})
for w in league_weeks:
    best = max(standings, key=lambda s: s["weeks"][w])
    best["high"] = best.get("high", 0) + 1
for s in standings:
    s["wins"] = s.pop("high", 0)
standings.sort(key=lambda s: -s["total"])

# ---- Tier reference and dates ----------------------------------------------
tier_table = sorted(
    [{"type": t, "per_game": round(c / len(g_cal), 3), "season": c, "tier": tiers[t]}
     for t, c in type_count.items()], key=lambda x: -x["season"])
start_dates = sorted(g["gameday"] for g in games.values()
                     if g["season"] == str(SEASON) and int(g["week"]) == START)
scored_espn = sorted(games[g]["espn"] for g in g_cur if games[g]["espn"])

json.dump({
    "league_name": LEAGUE["league_name"],
    "season": SEASON, "cal_season": CAL,
    "mode": "live" if drafted else "preview",
    "partly_drafted": partly,
    "start_week": START,
    "start_date": start_dates[0] if start_dates else None,
    "crews_per_team": N_CREWS, "counting_crews": N_COUNT,
    "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
    "updated": max(games[g]["gameday"] for g in g_cur) if g_cur else None,
    "last_week": last,
    "weeks_played": weeks_played,
    "league_weeks": league_weeks,
    "calibration_games": len(g_cal),
    "avg_ppg25": round(sum(s_cal[g]["pts"] for g in g_cal if g in s_cal) / len(g_cal), 1),
    "avg_flags25": round(sum(s_cal[g]["flags"] for g in g_cal if g in s_cal) / len(g_cal), 1),
    "rules": {"per_flag": PTS_PER_FLAG, "per_yard": PTS_PER_YARD, "tiers": TIER_BONUS,
              "ejection": EJECTION_BONUS, "td_wipe": TD_WIPE_BONUS,
              "offset_mult": OFFSET_MULT, "clutch_mult": CLUTCH_MULT},
    "pen_pattern": PEN_PATTERN,
    "tier_of": tiers,
    "ref_last_names": {k: next(iter(v)) for k, v in by_last.items() if len(v) == 1},
    "scored_espn": scored_espn,
    "crews": crew_list,
    "week_games": week_games,
    "top_flags": top_flags,
    "sightings": sightings,
    "standings": standings,
    "free_agents": [c["referee"] for c in crew_list if c["referee"] not in taken],
    "tier_table": tier_table,
    "unknown_ref_games": unknown_ref,
}, open(OUT, "w"), indent=1)
print(f"wrote {OUT} | mode {'live' if drafted else 'preview'} | crews {len(crew_list)} "
      f"| weeks {weeks_played} | games missing a referee: {len(unknown_ref)}")
