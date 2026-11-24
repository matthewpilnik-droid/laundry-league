# The lineup app (`app.html` + this folder)

Players sign in with an emailed 6-digit code, set their lineup, and see the league. The database decides what is allowed;
this page only shows its answers. **Currently points at the REHEARSAL project (fake data).** Not linked from the public page.

| File | What it is |
|---|---|
| `../app.html` | The page shell. Its Content-Security-Policy line limits it to our own scripts and one Supabase address. |
| `app.js` | All the logic: sign in, My week, League, Commissioner. Never uses `innerHTML`; every name goes through `textContent`. |
| `app.css` | Styles (no third-party fonts). |
| `config.js` | Project address and **publishable** key (public by design). Never the secret key. |
| `vendor/supabase.js` | Supabase's browser library, pinned and checksum-verified (see `vendor/VENDOR.md`). |

**Try it on your computer:** `python3 -I scripts/serve_app.py`, then open http://localhost:8765/app.html.
That server shows only the app's own files and only to this computer. Check it: `python3 -I scripts/serve_app.py --selftest`.

**Tests (no network, no keys):** `NODE_MODULES_DIR=<folder with node_modules/jsdom> node supabase/tests/app_check.mjs`
(simulated browser: every screen, error messages, hostile text, the lock). The database rules are tested by `supabase/tests/burglar.py`.

**Step 7 (real project):** change the address in `config.js` AND in the `connect-src` part of the CSP line in `app.html`,
then re-run the tests (one checks that the two match).
