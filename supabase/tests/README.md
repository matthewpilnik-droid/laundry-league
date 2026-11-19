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
2. **Run the seed** once: paste `supabase/seed/rehearsal.sql` into the SQL Editor and Run.

## Each run
1. SQL Editor: `truncate public.lineups, public.audit_log;` (the test needs an empty lineup history)
2. `python3 -I supabase/tests/burglar.py`

`.env.rehearsal` (gitignored) holds the project URL, the public key and the fake users' passwords.
No secret key is needed.
