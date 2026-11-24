# Security test ("burglar") for the rehearsal project

Signs in as four fake users and tries to break the rules. Every attack must be refused and every
normal action must work. Rehearsal project only; never point this at the real league.

## One-time setup
1. **Create four fake users** in the Supabase dashboard: Authentication -> Users -> Add user -> Create new user.
   For each: tick **Auto Confirm User**, and pick any throwaway password (never one you use anywhere real).
   Put each password in `.env.rehearsal` as PW_COMMISH, PW_BRYAN, PW_MIKE, PW_OUTSIDER
   (or use one shared TEST_PASSWORD for all four).
   - ll-commish@example.com
   - ll-bryan@example.com
   - ll-mike@example.com
   - ll-outsider@example.com
2. **Run the seeds** once, in this order, pasting each into the SQL Editor and pressing Run:
   `supabase/seed/rehearsal.sql`, then (after migration 05) `supabase/seed/rehearsal_weeks.sql`.

## Each run
1. SQL Editor: `truncate public.lineups, public.audit_log;` (the test needs an empty lineup history)
2. `python3 -I supabase/tests/burglar.py`

`.env.rehearsal` (gitignored) holds the project URL, the public key and the fake users' passwords.
No secret key is needed.

## Two kinds of test
- **Local rehearsal (no network, no accounts):** `PGLITE_DIR=<folder with @electric-sql/pglite installed> node supabase/tests/local_check.mjs`
  builds all migrations and seeds in a throwaway in-memory database and checks the rules (including the
  finished-week and fail-closed rules, which the live test cannot reach because they need the bot's key to set up).
- **Live burglar test (above):** the real rehearsal project, signed in as the fake users.
