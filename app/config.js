// Public settings for the lineup app. Safe to be public: the project address and the PUBLISHABLE key are meant
// for browsers; what a visitor can do is decided by the database's security rules, not by hiding these.
// NEVER put the secret key (sb_secret_...) here. The secret scanner and the push hook will refuse it.
//
// This points at the REHEARSAL project (fake data). Step 7 swaps in the real project: change the two values below
// AND the matching address in the Content-Security-Policy line of app.html.
window.LL_CONFIG = {
  supabaseUrl: "https://stwadwgwzulkfuqebxrf.supabase.co",
  publishableKey: "sb_publishable_fpnb0K8E8LCYQGOTwWJlNQ_vRcmEAQu",
  dataUrl: "data.json"   // the public page's generated data: matchups, standings, game names
};
