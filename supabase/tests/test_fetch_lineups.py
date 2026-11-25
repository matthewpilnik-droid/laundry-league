"""Tests for scripts/fetch_lineups.py reading a long list of lineups. No network, no key.
Run:  python3 -I supabase/tests/test_fetch_lineups.py

Supabase quietly caps every answer at 1,000 rows (it does not say it cut anything off). The stand-in below does the same,
so these tests check that the fetcher gets EVERY row, in order, and fails loudly rather than returning a cut-off list.
"""
import importlib.util, io, json, pathlib, sys, tempfile, urllib.error, urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("fetch_lineups", ROOT / "scripts" / "fetch_lineups.py")
mod = importlib.util.module_from_spec(spec)
sys.argv = ["x", tempfile.mkdtemp()]
spec.loader.exec_module(mod)
mod.config = lambda: ("https://example.invalid", "KEY")

passed = failed = 0
def check(label, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print("PASS -", label)
    else: failed += 1; print("FAIL - %s   [%s]" % (label, str(extra)[:250]))

class Resp:
    def __init__(self, body, headers=None): self._b, self.headers, self.status = json.dumps(body).encode(), headers or {}, 200
    def read(self): return self._b
    def __enter__(self): return self
    def __exit__(self, *a): return False

def install_fake(n_rows, cap=1000, lie_after=None):
    """A stand-in for Supabase. lineups has n_rows rows with ids 1..n_rows; every answer is cut to `cap` rows, silently.
    lie_after: after this many rows are handed out, answer with an empty page though more remain (a broken server)."""
    rows = [{"id": i, "team_id": "t1", "week": 8 + i % 11, "starters": ["A", "B"], "captain": None, "created_at": "x"} for i in range(1, n_rows + 1)]
    def fake(req, timeout=None):
        path = req.full_url.replace("https://example.invalid", "")
        if path.startswith("/rest/v1/leagues"): return Resp([{"id": "L", "name": "Fake League"}])
        if path.startswith("/rest/v1/teams"): return Resp([{"id": "t1", "name": "Team One"}])
        if path.startswith("/rest/v1/lineups"):
            start, end = 0, cap - 1
            rng = req.get_header("Range")
            if rng: start, end = (int(x) for x in rng.split("-"))
            if "offset=" in path: start = int(path.split("offset=")[1].split("&")[0])
            page = rows[start:start + min(end - start + 1, cap)]
            if lie_after is not None and start >= lie_after: page = []
            hdr = {"Content-Range": ("%d-%d/%d" % (start, start + len(page) - 1, n_rows)) if page else "*/%d" % n_rows}
            return Resp(page, hdr)
        raise AssertionError("unexpected request " + path)
    urllib.request.urlopen = fake

for n in (0, 10, 999, 1000, 1001, 2500):
    install_fake(n)
    try:
        got = mod.fetch()["entries"]
        ok = [e["id"] for e in got] == list(range(1, n + 1))
        check("%d saved lineups: every one read, in order (got %d)" % (n, len(got)), ok, "got %d" % len(got))
    except RuntimeError as e:
        check("%d saved lineups: read without an error" % n, False, e)

install_fake(2500, cap=400)
got = mod.fetch()["entries"]
check("a stricter server cap (400 rows per answer) is handled too: all 2500 read", len(got) == 2500, "got %d" % len(got))

install_fake(2500, lie_after=1200)
try:
    mod.fetch(); check("a server that stops answering part-way fails LOUDLY (no cut-off list returned)", False, "returned without error")
except RuntimeError as e:
    check("a server that stops answering part-way fails LOUDLY (no cut-off list returned)", "cut off" in str(e) or "incomplete" in str(e), e)

install_fake(10)
d = mod.fetch()
check("entries carry the team's NAME (looked up), the week and the starters", d["entries"][0]["team"] == "Team One" and d["entries"][0]["start"] == ["A", "B"], d["entries"][0])

print("\n%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
