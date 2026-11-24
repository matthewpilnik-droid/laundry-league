# Vendored library: @supabase/supabase-js

- **What:** Supabase's browser library (sign-in and database calls). MIT licence (LICENSE-supabase-js.txt).
- **Version:** 2.119.2 (pinned). File: `dist/umd/supabase.js` from the npm package.
- **Source:** https://registry.npmjs.org/@supabase/supabase-js/-/supabase-js-2.119.2.tgz
- **Verified 2026-11-24:** the downloaded tarball's SHA-512 matched the registry's published value
  `sha512-4HvF4G2DwdqjmwPBpz9RHnXWfdK0wSkw4yBhxe64CdeF8gdxsTF9WZuHFuNWtQnHllq71ZDyAghr4Q8nC0m/NA==`.
- **SHA-256 of the file in this folder:** `8816af04d9915dbba1882d6f84f0b402dc40268063a63d9c66d24f52f371c263`
- **Why it lives here:** the page loads it from our own site, never from a third-party server, and the app's
  Content-Security-Policy only allows scripts from our own site.
- **To upgrade:** download the new version the same way, compare the checksum with the registry, replace the file, update
  this note, and re-run `node supabase/tests/app_check.mjs`. Never edit the file by hand.
