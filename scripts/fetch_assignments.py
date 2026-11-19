"""Read each week's referee assignments from Football Zebras and save them as PROVISIONAL.

Usage: python3 -I scripts/fetch_assignments.py <cache_dir>      (run after fetch_data.py)

Reads the public weekly post ("Week N referee assignments") and writes data/assignments.json,
committed like data/referees.json. The page shows these with a "Provisional" label until the real
referee is known from the NFL data after kickoff. Nothing here affects scoring.

Also saves each unplayed game's kickoff time from ESPN to data/kickoffs.json. The nflverse schedule can lag
when the NFL swaps or flexes a game's time (Week 11: PIT@PHI and JAX@NYG), and a wrong time on the page
is worse than none. build_data.py prefers these times and falls back to nflverse.

This is plain pattern matching, not AI: a line like "Colts at Texans" followed by a referee name and a
time. If anything in a post doesn't look right (an unknown team, a game that isn't on the schedule),
that week is skipped, the old data stays, and a warning is printed. It never stops the score update.
Be gentle on the site: only weeks that still have unplayed games are fetched, a few requests a day.
"""
import csv, html, http.client, json, pathlib, re, sys, time, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "cache"
OUT = ROOT / "data" / "assignments.json"
LEAGUE = json.loads((ROOT / "league.json").read_text())
SEASON, FIRST, LAST = LEAGUE["season"], LEAGUE["start_week"], LEAGUE["regular_season_end"]
CATEGORY = "https://www.footballzebras.com/category/assignments/"
UA = {"User-Agent": "laundry-league/1.0 (fantasy league for friends)"}

# Football Zebras writes team nicknames; the schedule uses nflverse abbreviations.
NICK = {
    "Cardinals": "ARI", "Falcons": "ATL", "Ravens": "BAL", "Bills": "BUF", "Panthers": "CAR", "Bears": "CHI",
    "Bengals": "CIN", "Browns": "CLE", "Cowboys": "DAL", "Broncos": "DEN", "Lions": "DET", "Packers": "GB",
    "Texans": "HOU", "Colts": "IND", "Jaguars": "JAX", "Chiefs": "KC", "Raiders": "LV", "Chargers": "LAC",
    "Rams": "LA", "Dolphins": "MIA", "Vikings": "MIN", "Patriots": "NE", "Saints": "NO", "Giants": "NYG",
    "Jets": "NYJ", "Eagles": "PHI", "Steelers": "PIT", "49ers": "SF", "Seahawks": "SEA", "Buccaneers": "TB",
    "Titans": "TEN", "Commanders": "WAS",
}
GAME_RE = re.compile(r"^(.+?)\s+(?:at|vs\.?|@)\s+(.+?)\s*$")
NAME_RE = re.compile(r"^[A-Z][A-Za-z'.\-]+(?: [A-Z][A-Za-z'.\-]+){1,2}$")
TIME_RE = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?", re.I)
OFF_RE = re.compile(r"crews? of (.+?) (?:is|are) off this week", re.I)


def warn(msg):
    print(f"::warning::assignments: {msg}")     # GitHub shows this as a yellow note; harmless elsewhere


def get(url, tries=5, need=None):
    """Download a page. `need` is a phrase the page must contain; if it's missing (the connection dropped
    partway, which happens), try again instead of trusting a half-page."""
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={**UA, "Accept-Encoding": "identity"}), timeout=30) as r:
                try:
                    body = r.read()
                except http.client.IncompleteRead as e:
                    body = e.partial
            text = body.decode("utf-8", "replace")
            if need is None or need in text:
                return text
            raise ValueError(f"page is missing '{need}' (download cut short?)")
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def article_lines(page):
    """The post's visible text, one line per block, trimmed to the article itself."""
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", page, flags=re.S)
    page = re.sub(r"</(p|li|h\d|div|tr|td)>|<br\s*/?>", "\n", page)
    text = html.unescape(re.sub(r"<[^>]+>", "", page))
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    start = next((i for i, ln in enumerate(lines) if ln.lower().startswith("all times are eastern")), 0)
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("Share on")), len(lines))   # after the list
    head = " ".join(lines[max(0, start - 6):start + 1])      # the intro sentences sit just above the list
    return lines[start:end], head


def to_24h(t):
    m = TIME_RE.match(t or "")
    if not m:
        return ""
    h, mi, ap = int(m.group(1)) % 12, m.group(2) or "00", m.group(3).lower()
    return f"{h + (12 if ap == 'p' else 0):02d}:{mi}"


def parse_post(page, week, sched, canon):
    """sched: {frozenset({away, home}): (gid, kickoff 'HH:MM')} for this week. Returns (result, problems)."""
    lines, head = article_lines(page)
    by_last = {}
    for n in canon:
        by_last.setdefault(n.split()[-1].lower(), set()).add(n)
    games, problems = {}, []
    for i, ln in enumerate(lines):
        m = GAME_RE.match(ln)
        if not m:
            continue
        a, b = (NICK.get(m.group(1).strip().rstrip(".")), NICK.get(m.group(2).strip().rstrip(".")))
        if not (a and b):
            continue                                            # not a game line (some other sentence)
        ref = lines[i + 1] if i + 1 < len(lines) else ""
        when = lines[i + 2] if i + 2 < len(lines) else ""
        if not NAME_RE.match(ref):
            problems.append(f"no referee name after '{ln}'")
            continue
        hit = sched.get(frozenset((a, b)))
        if not hit:
            problems.append(f"'{ln}' is not a Week {week} game on the schedule")
            continue
        gid, kick = hit
        if ref not in canon:
            cands = by_last.get(ref.split()[-1].lower(), set())
            ref = next(iter(cands)) if len(cands) == 1 else ref     # same last-name rule the score build uses
        if to_24h(when) and kick and to_24h(when) != kick:
            problems.append(f"{ln}: post says {when}, schedule says {kick} (kept anyway)")
        games[gid] = {"referee": ref, "time": when if TIME_RE.match(when) else ""}
    off = []
    m = OFF_RE.search(head + " " + " ".join(lines[:8]))
    if m:
        off = [n.strip() for n in re.split(r",\s*(?:and\s+)?|\s+and\s+", m.group(1)) if n.strip()]
    return {"games": games, "off": off, "complete": len(games) == len(sched)}, problems


ESPN_ABBR = {"WSH": "WAS", "LAR": "LA"}      # ESPN's spelling -> nflverse's


def get_json(url, tries=6):
    """ESPN's scoreboard is a big file and the connection sometimes drops partway; just try again."""
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={**UA, "Accept-Encoding": "identity"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2)


def fetch_kickoffs(weeks, sched_by_week):
    """{game id: {"date": "2026-11-22", "time": "13:00"}} in Eastern time, from ESPN, for these weeks."""
    import datetime, zoneinfo
    et, out = zoneinfo.ZoneInfo("America/New_York"), {}
    for w in sorted(weeks):
        try:
            d = get_json(f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?seasontype=2&week={w}&dates={SEASON}")
        except Exception as e:
            warn(f"Week {w}: could not read kickoff times from ESPN ({e}); using the nflverse schedule")
            continue
        for ev in d.get("events", []):
            try:
                teams = {c["team"]["abbreviation"] for c in ev["competitions"][0]["competitors"]}
                pair = frozenset(ESPN_ABBR.get(t, t) for t in teams)
                hit = sched_by_week[w].get(pair)
                if hit:
                    t = datetime.datetime.fromisoformat(ev["date"].replace("Z", "+00:00")).astimezone(et)
                    out[hit[0]] = {"date": t.strftime("%Y-%m-%d"), "time": t.strftime("%H:%M")}
            except (KeyError, IndexError, ValueError):
                continue
    return out


def main():
    sched_by_week, canon, unplayed = {}, set(), set()
    for r in csv.DictReader(open(CACHE / "games.csv")):
        if r["referee"]:
            canon.add(r["referee"])
        if r["season"] == str(SEASON) and r["game_type"] == "REG" and FIRST <= int(r["week"]) <= LAST:
            w = int(r["week"])
            sched_by_week.setdefault(w, {})[frozenset((r["away_team"], r["home_team"]))] = (r["game_id"], r["gametime"])
            if r["result"] == "" and r["home_score"] == "":
                unplayed.add(w)
    old = json.loads(OUT.read_text()) if OUT.exists() else {"weeks": {}}
    weeks = dict(old.get("weeks", {}))

    kicks_file = ROOT / "data" / "kickoffs.json"
    kicks = json.loads(kicks_file.read_text()) if kicks_file.exists() else {}
    # Only the next two weeks: that's where flex swaps happen, and it keeps the requests few.
    soon = sorted(unplayed)[:2]
    fresh = fetch_kickoffs(soon, sched_by_week)
    got = {int(g.split("_")[1]) for g in fresh}
    # Keep older saved times only for a soon-week whose ESPN read failed this time; drop the rest (they go stale).
    kicks = {g: v for g, v in kicks.items() if int(g.split("_")[1]) in soon and int(g.split("_")[1]) not in got}
    kicks.update(fresh)
    ktext = json.dumps(dict(sorted(kicks.items())), indent=1) + "\n"
    if not kicks_file.exists() or kicks_file.read_text() != ktext:
        kicks_file.parent.mkdir(exist_ok=True)
        kicks_file.write_text(ktext)
        print(f"updated data/kickoffs.json ({len(fresh)} games read from ESPN)")
    for w in sched_by_week:        # prefer ESPN's time when we have it, for the post's time check
        for pair, (gid, kick) in list(sched_by_week[w].items()):
            if gid in kicks:
                sched_by_week[w][pair] = (gid, kicks[gid]["time"])

    try:
        listing = get(CATEGORY, need="referee-assignments-")
    except Exception as e:
        warn(f"could not open the assignments list ({e}); keeping what we have")
        return
    links = {}
    for m in re.finditer(rf'href="(https://www\.footballzebras\.com/{SEASON}/\d{{2}}/week-(\d+)-referee-assignments-{SEASON}/?)"', listing):
        links.setdefault(int(m.group(2)), m.group(1))

    for w in sorted(unplayed):
        if w not in links:
            continue                                            # not posted yet: normal early in the week
        try:
            result, problems = parse_post(get(links[w], need="All times are Eastern"), w, sched_by_week[w], canon)
        except Exception as e:
            warn(f"Week {w}: could not read the post ({e}); keeping what we have")
            continue
        hard = [p for p in problems if "kept anyway" not in p]
        for p in problems:
            warn(f"Week {w}: {p}")
        if hard or not result["games"]:
            warn(f"Week {w}: the post didn't read cleanly, so nothing was changed" +
                 ("" if str(w) in weeks else "; the page won't show assignments for this week"))
            continue
        weeks[str(w)] = {"source": links[w], **result}
        print(f"Week {w}: {len(result['games'])} of {len(sched_by_week[w])} games, off: {', '.join(result['off']) or 'not stated'}")

    text = json.dumps({"note": "Provisional referee assignments read from footballzebras.com; display only.",
                       "weeks": dict(sorted(weeks.items(), key=lambda kv: int(kv[0])))}, indent=1) + "\n"
    if not OUT.exists() or OUT.read_text() != text:
        OUT.parent.mkdir(exist_ok=True)
        OUT.write_text(text)
        print("updated data/assignments.json")
    else:
        print("assignments unchanged")


if __name__ == "__main__":
    main()
