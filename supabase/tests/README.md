# Security test ("burglar") for the rehearsal project

Signs in as four fake users and tries to break the rules. Every attack must be refused and every
normal action must work. Rehearsal project only; never point this at the real league.

## One-time setup
1. **Create four fake users** in the Supabase dashboard: Authentication -> Users -> Add user -> Create new user.
   For each: tick **Auto Confirm User**, and use the shared test password from `.env.rehearsal`
   (copy it with: `! grep TEST_PASSWORD .env.rehearsal | cut -d= -f2 | pbcopy`).
   - ll-commish@example.com
   - ll-bryan@example.com
   - ll-mike@example.com
   - ll-outsider@example.com
2. **Run the seed** once: paste `supabase/seed/rehearsal.sql` into the SQL Editor and Run.

## Each run
1. SQL Editor: `truncate public.lineups, public.audit_log;` (the test needs an empty lineup history)
2. `python3 -I supabase/tests/burglar.py`

`.env.rehearsal` (gitignored) holds the project URL, the public key and the shared test password.
No secret key is needed.
