"""Try the lineup app on this computer only:   python3 -I scripts/serve_app.py   then open http://localhost:8765/app.html

Why not just `python3 -m http.server`? That would publish EVERY file in the project, including your gitignored .env
files with passwords and keys, to anyone on the same Wi-Fi. This server:
  * listens on 127.0.0.1 only (this computer; nothing else on the network can connect), and
  * serves ONLY an allowlist: app.html, data.json (the public page's data) and the app/ folder. Everything else is 404.
Check it yourself any time:  python3 -I scripts/serve_app.py --selftest
Stop it with Ctrl+C. Standard library only.
"""
import http.server, pathlib, posixpath, sys, urllib.parse

ROOT = pathlib.Path(__file__).resolve().parent.parent
PORT = 8765
EXACT = {"/app.html", "/data.json"}
PREFIX = "/app/"


def allowed(raw_path):
    """True only for the files the app needs. Rejects anything that tries to climb out with '..' or hides in odd encodings."""
    p = urllib.parse.unquote(urllib.parse.urlsplit(raw_path).path)
    if p != posixpath.normpath(p) and not p.endswith("/"):
        return False
    if "\\" in p or "\x00" in p or any(part.startswith(".") for part in p.split("/") if part):
        return False
    return p in EXACT or (p.startswith(PREFIX) and len(p) > len(PREFIX))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def do_GET(self):
        if self.path in ("/", ""):
            self.send_response(302); self.send_header("Location", "/app.html"); self.end_headers(); return
        if not allowed(self.path):
            self.send_error(404, "Not found"); return
        super().do_GET()

    do_HEAD = do_GET

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")     # always show the latest file while we are building
        super().end_headers()


def selftest():
    """Start the server on a spare port, ask it for files it should and should NOT serve, and report."""
    import threading, urllib.error, urllib.request
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    def code(path):
        try:
            return urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5).status
        except urllib.error.HTTPError as e:
            return e.code
    should = ["/app.html", "/app/app.js", "/app/app.css", "/app/config.js", "/app/vendor/supabase.js", "/data.json"]
    must_not = ["/.env.rehearsal", "/.env.rehearsal-bot", "/league.json", "/index.html", "/scripts/sync_supabase.py",
                "/supabase/seed/rehearsal.sql", "/.git/config", "/app/..%2f.env.rehearsal-bot", "/app/%2e%2e/.env.rehearsal-bot", "/app/"]
    bad = 0
    for p in should:
        c = code(p); bad += c != 200; print(("ok   " if c == 200 else "WRONG"), c, p, "(should be served)")
    for p in must_not:
        c = code(p); bad += c == 200; print(("ok   " if c != 200 else "WRONG"), c, p, "(must NOT be served)")
    srv.shutdown()
    print("\nSELF-TEST " + ("FAILED: do not use this server" if bad else "PASSED: only the app's own files are served"))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        selftest()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Serving the lineup app at http://localhost:{PORT}/app.html   (this computer only; Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
