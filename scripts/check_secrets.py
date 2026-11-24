"""Look for secrets in files git tracks, before anything is pushed.

Run:  python3 -I scripts/check_secrets.py            (tracked files + staged changes)
      python3 -I scripts/check_secrets.py --history  (also every past commit)

Exits 1 and prints file names (never the secret itself) if it finds one.
The Supabase "anon"/"publishable" key is public by design, so it is allowed.
The "service_role"/"secret" key is not.
"""
import base64, json, re, subprocess, sys

JWT = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.([A-Za-z0-9_-]{8,})\.[A-Za-z0-9_-]{8,}")
OTHER = [
    ("Supabase secret key", re.compile(r"sb_secret_[A-Za-z0-9_-]{10,}")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("env-style secret", re.compile(r"(SERVICE_ROLE|SECRET_KEY|VAPID_PRIVATE|DB_PASSWORD)\s*[=:]\s*['\"]?[A-Za-z0-9_./+-]{12,}")),
    ("database URL with password", re.compile(r"postgres(ql)?://[^:\s]+:[^@\s]+@")),
]

def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, errors="replace").stdout

def jwt_role(m):
    try:
        p = m.group(1) + "=" * (-len(m.group(1)) % 4)
        return json.loads(base64.urlsafe_b64decode(p)).get("role")
    except Exception:
        return None

def scan(text):
    hits = []
    for m in JWT.finditer(text):
        if jwt_role(m) == "service_role":
            hits.append("Supabase service_role key")
    for label, rx in OTHER:
        if rx.search(text):
            hits.append(label)
    return hits

def main():
    problems = []
    tracked = git("ls-files").splitlines()
    for f in tracked:
        if re.search(r"(^|/)\.env($|\.)", f):
            problems.append((f, "an .env file is tracked by git"))
        try:
            text = open(f, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        problems += [(f, h) for h in scan(text)]
    for h in scan(git("diff", "--cached")):
        problems.append(("(staged changes)", h))
    if "--history" in sys.argv:
        for c in git("rev-list", "--all").split():
            for h in scan(git("show", c)):
                problems.append(("commit " + c[:8], h))
    for where, what in sorted(set(problems)):
        print("FOUND: %s in %s" % (what, where))
    print("Checked %d tracked files%s." % (len(tracked), " and full history" if "--history" in sys.argv else ""))
    print("Problems: %d" % len(set(problems)))
    sys.exit(1 if problems else 0)

main()
