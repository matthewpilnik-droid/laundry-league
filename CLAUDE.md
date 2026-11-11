# Laundry League: notes for Claude

Read `README.md` (league rules, scoring, files) and `HANDOFF.md` (setup, open items) for detail.

## Rules for this project
- **The repo is public and the site is live** (GitHub Pages:
  https://matthewpilnik-droid.github.io/laundry-league/). Anything pushed to `main` reaches
  league members within minutes. Ask before pushing.
- **A bot commits score updates about 4 times a day.** Always `git pull` before starting
  work and again right before pushing.
- Pushing changes to `league.json`, `site/` or `scripts/` triggers a rebuild of the site.
- Never edit `index.html` or `data.json` by hand: they are generated. Edit
  `site/template.html` or `scripts/`, then rebuild.
- Scoring changes: rebuild locally and compare scores before and after, so I can see which
  past results change. Past weeks changing affects standings, so call that out clearly.

## Test locally
```
python3 -I scripts/fetch_data.py cache
python3 -I scripts/build_data.py cache data.json
python3 -I scripts/render.py
open index.html
```
GitHub builds with Python 3.12; this laptop has 3.9. If something works on GitHub but not
locally (or the reverse), suspect the version difference.
