// Browser-simulation checks for the lineup app (app.html + app/app.js). No network, no accounts, no keys.
// Run:  NODE_MODULES_DIR=<folder containing node_modules/jsdom> node supabase/tests/app_check.mjs
// A fake Supabase stands in for the real one, so every screen and error message can be exercised on demand.
// The REAL rules live in the database and are tested by burglar.py; here we test what the page shows and sends.
process.env.TZ = 'America/Chicago';   // pretend the reader is in Central time
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '../..');
const req = createRequire(path.join(process.env.NODE_MODULES_DIR || '.', 'x.js'));
const { JSDOM } = await import(pathToFileURL(req.resolve('jsdom')).href);
const read = (p) => readFileSync(path.join(ROOT, p), 'utf8');
const HTML = read('app.html'), APPJS = read('app/app.js'), CONFIG = read('app/config.js');
// For "what does the code actually contain" checks, ignore comments (they legitimately say things like "never use innerHTML").
const noComments = (js) => js.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:"'])\/\/.*$/gm, '$1');

let pass = 0, fail = 0;
const ok = (label, cond, extra = '') => { cond ? pass++ : fail++; console.log((cond ? 'PASS - ' : 'FAIL - ') + label + (cond ? '' : '   [' + String(extra).slice(0, 300) + ']')); };

// ---------------------------------------------------------------- the fake league
const NOW = Date.now(), H = 3600e3;
const iso = (ms) => new Date(ms).toISOString();
const NAMES = { bry: 'Bryan', mat: 'Matthew', mik: 'Mike' };
const TEAMS = [
  { id: 't-bry', league_id: 'L1', name: "Helen Keller's School for Refs", manager_name: 'Bryan' },
  { id: 't-mat', league_id: 'L1', name: "I'm Blind, I'm Deaf", manager_name: 'Matthew' },
  { id: 't-mik', league_id: 'L1', name: 'This is not Nam', manager_name: 'Mike' },
];
const ROSTER = [
  ['t-bry', 1, 'Scott Novak'], ['t-bry', 2, 'John Hussey'], ['t-bry', 3, '2012 Replacement Refs'],
  ['t-mat', 1, 'Alex Moore'], ['t-mat', 2, 'Ron Torbert'], ['t-mat', 3, 'Alan Eck'],
  ['t-mik', 1, 'Craig Wrolstad'], ['t-mik', 2, 'Brad Allen'], ['t-mik', 3, 'Clete Blakeman'],
].map(([team_id, slot, crew]) => ({ team_id, slot, crew }));
const LEAGUE = { id: 'L1', name: 'Rehearsal League', season: 2026, start_week: 8, captain_start_week: 11, playoff_week: 18 };
const WEEKS = [{ season: 2026, week: 10, starts_at: iso(NOW - 200 * H), ends_at: iso(NOW - 100 * H) },
  { season: 2026, week: 11, starts_at: iso(NOW - 5 * H), ends_at: iso(NOW + 100 * H) },
  { season: 2026, week: 12, starts_at: iso(NOW + 150 * H), ends_at: iso(NOW + 250 * H) }];
const SLOTS = [
  { week: 11, crew: 'Scott Novak', kickoff_at: iso(NOW - 2 * H) },            // kicked off
  { week: 11, crew: 'John Hussey', kickoff_at: '2026-11-29T18:00:00Z' },        // Sunday noon Central (in the future relative to the test? see below)
  { week: 11, crew: 'Alex Moore', kickoff_at: iso(NOW - 2 * H) },
  { week: 12, crew: 'John Hussey', kickoff_at: iso(NOW + 160 * H) },
];
SLOTS[1].kickoff_at = iso(NOW + 30 * H);
SLOTS.forEach((x) => { x.season = 2026; });
const PUB = {
  current_week: 11, off_weeks: { 11: ['Alan Eck'] },
  schedule: { 11: [{ gid: 'g1', game: 'MIA @ BUF', referee: 'Scott Novak' }, { gid: 'g2', game: 'PIT @ PHI', referee: '' }, { gid: 'g3', game: 'MIN @ SF', referee: 'Alex Moore' }, { gid: 'g4', game: 'LV @ DEN', referee: 'Clete Blakeman' }] },
  assignments: { 11: { games: { g2: 'John Hussey' } } }, game_fixes: {},
  weeks: [{ week: 11, games: [{ a: TEAMS[0].name, b: TEAMS[1].name }] }],
  standings: [{ team: TEAMS[0].name, manager: 'Bryan', w: 3, l: 1, t: 0, pf: 604.2 }],
};

function makeFake(o = {}) {
  const f = { calls: [], rpcCalls: [], session: o.session || null, listeners: [], otpError: o.otpError || null, setLineupError: null, errors: {} };
  const tables = {
    league_members: o.members || [{ user_id: 'u-bry', role: 'manager', team_id: 't-bry', league_id: 'L1' },
      { user_id: 'u-mat', role: 'commissioner', team_id: 't-mat', league_id: 'L1' }, { user_id: 'u-mik', role: 'manager', team_id: 't-mik', league_id: 'L1' }],
    leagues: [LEAGUE], teams: o.teams || TEAMS, roster: ROSTER, weeks: WEEKS, game_slots: o.slots || SLOTS,
    audit_log: o.audit || [{ action: 'lineup_set_past_week', actor: 'u-mat', created_at: iso(NOW - H), detail: { team_id: 't-bry', week: 10, starters: ['Scott Novak', 'John Hussey'], captain: null } }],
  };
  const lineups = o.lineups || { 't-bry': { starters: ['Scott Novak', 'John Hussey'], captain: null, from_week: 10 }, 't-mat': { starters: ['Alex Moore', 'Ron Torbert'], captain: 'Alex Moore', from_week: 11 }, 't-mik': { starters: ['Craig Wrolstad', 'Brad Allen'], captain: null, from_week: null } };
  f.client = {
    auth: {
      getSession: async () => ({ data: { session: f.session } }),
      onAuthStateChange: (cb) => { f.listeners.push(cb); return { data: { subscription: {} } }; },
      signInWithOtp: async (a) => { f.calls.push(['otp', a]); return { error: f.otpError }; },
      verifyOtp: async (a) => { f.calls.push(['verify', a]);
        if (a.token === '123456' || a.token === '12345678') { f.session = { user: { id: a.email.startsWith('bryan') ? 'u-bry' : a.email.startsWith('matthew') ? 'u-mat' : a.email.startsWith('stranger') ? 'u-out' : 'u-bry' } }; return { data: { session: f.session }, error: null }; }
        return { data: { session: null }, error: { message: 'Token has expired or is invalid' } }; },
      signOut: async () => { f.session = null; f.listeners.forEach((cb) => cb('SIGNED_OUT', null)); return { error: null }; },
    },
    from: (table) => {
      const st = { table, eqs: [], single: false };
      const run = async () => {
        f.calls.push(['from', table, st.eqs.slice()]);
        if (f.errors[table]) return { data: null, error: { message: f.errors[table] } };
        let rows = (tables[table] || []).filter((r) => st.eqs.every(([c, v]) => r[c] === v));
        return st.single ? { data: rows[0], error: null } : { data: rows, error: null };
      };
      const b = { select: () => b, eq: (c, v) => { st.eqs.push([c, v]); return b; }, order: () => b, limit: () => b, single: () => { st.single = true; return b; }, then: (res, rej) => run().then(res, rej) };
      return b;
    },
    rpc: async (name, args) => { f.rpcCalls.push([name, args]);
      if (name === 'effective_lineup') {
        if (o.effDelay && o.effDelay[args.p_week]) await new Promise((r) => setTimeout(r, o.effDelay[args.p_week]));   // a slow answer, to test overlapping requests
        if (o.effFor) return { data: [o.effFor(args.p_team_id, args.p_week)], error: null };
        return { data: [lineups[args.p_team_id] || { starters: [], captain: null, from_week: null }], error: null };
      }
      if (name === 'lineup_effect_range') return { data: [{ from_week: args.p_week, to_week: args.p_week + 1 }], error: null };
      if (name === 'set_lineup') return f.setLineupError ? { data: null, error: { message: f.setLineupError } } : { data: 99, error: null };
      return { data: null, error: { message: 'unknown rpc' } }; },
  };
  return f;
}

async function start(o = {}) {
  const fake = makeFake(o);
  const dom = new JSDOM(HTML, { url: 'http://localhost/app.html', runScripts: 'outside-only', pretendToBeVisual: true });
  const win = dom.window;
  win.supabase = { createClient: () => fake.client };
  win.fetch = async () => ({ ok: true, json: async () => o.pub || PUB });
  win.eval(CONFIG);
  win.eval(APPJS);
  const $ = (sel) => win.document.querySelector(sel), $$ = (sel) => [...win.document.querySelectorAll(sel)];
  const text = () => win.document.body.textContent.replace(/\s+/g, ' ');
  const waitFor = async (fn, what = 'condition') => { for (let i = 0; i < 300; i++) { try { if (fn()) return true; } catch (e) { /* not yet */ } await new Promise((r) => setTimeout(r, 5)); } ok('the page reached: ' + what, false, 'timed out; page says: ' + text().slice(0, 250)); console.log(`\n${pass} passed, ${fail} failed (stopped at the first timeout)`); process.exit(1); };
  const btn = (label) => $$('button').find((b) => b.textContent.trim() === label || b.getAttribute('aria-label') === label);
  const click = (el) => { el.dispatchEvent(new win.MouseEvent('click', { bubbles: true })); };
  const type = (sel, v) => { const el = $(sel); el.value = v; el.dispatchEvent(new win.Event('input', { bubbles: true })); };
  const crewCard = (name) => $$('.crew').find((c) => c.querySelector('.name').textContent === name);
  return { fake, win, $, $$, text, waitFor, btn, click, type, crewCard, L: win.LLApp };
}
const signedIn = (user) => ({ session: { user: { id: user } } });

// ================================================================ static checks (the files themselves)
console.log('Static checks');
ok('app.js never parses HTML (no innerHTML / outerHTML / insertAdjacentHTML / document.write / eval / new Function)',
  !/innerHTML|outerHTML|insertAdjacentHTML|document\.write|\beval\s*\(|new Function/.test(noComments(APPJS)), (noComments(APPJS).match(/innerHTML|outerHTML|insertAdjacentHTML|document\.write|\beval\s*\(|new Function/) || [])[0]);
const csp = (HTML.match(/Content-Security-Policy" content="([^"]+)"/) || [])[1] || '';
const dir = (n) => ((csp.split(';').map((s) => s.trim()).find((s) => s.startsWith(n + ' '))) || '');
ok('CSP: default-src none', dir('default-src') === "default-src 'none'", csp);
ok("CSP: scripts only from our own site (no inline, no eval, no other host)", dir('script-src') === "script-src 'self'", dir('script-src'));
ok("CSP: styles only from our own site", dir('style-src') === "style-src 'self'", dir('style-src'));
const url = (CONFIG.match(/supabaseUrl:\s*"([^"]+)"/) || [])[1];
ok('CSP: may talk only to itself and the Supabase address in config.js', dir('connect-src') === `connect-src 'self' ${url}`, dir('connect-src') + ' vs ' + url);
ok('CSP: no frames, forms or base tags', /base-uri 'none'/.test(csp) && /form-action 'none'/.test(csp));
ok('app.html loads no third-party scripts, styles or fonts', !/(src|href)="https?:\/\//.test(HTML.replace(/<link rel="icon"[^>]*>/, '')), (HTML.match(/(src|href)="https?:\/\/[^"]+/) || [])[0]);
ok('no secret key anywhere in the page files', !/sb_secret_|service_role/.test(HTML.replace(/<!--[\s\S]*?-->/g, '') + noComments(APPJS) + noComments(CONFIG)));
ok('config.js holds only the PUBLISHABLE key', /publishableKey:\s*"sb_publishable_/.test(CONFIG));
const vend = readFileSync(path.join(ROOT, 'app/vendor/supabase.js'));
const note = read('app/vendor/VENDOR.md');
ok('vendored library matches the checksum recorded in VENDOR.md', note.includes(createHash('sha256').update(vend).digest('hex')));

// ================================================================ sign in
console.log('\nSign in');
let t = await start();
await t.waitFor(() => t.$('#email'), 'sign-in screen');
ok('not signed in: shows the sign-in screen', /Sign in/.test(t.text()));
ok('...and asked the database for nothing', !t.fake.calls.some((c) => c[0] === 'from'));
t.type('#email', 'not-an-email'); t.click(t.btn('Send code'));
await t.waitFor(() => /Type the email/.test(t.text()), 'email error');
ok('a malformed email is refused before any request', !t.fake.calls.some((c) => c[0] === 'otp'));
t.type('#email', 'bryan@example.com'); t.click(t.btn('Send code'));
await t.waitFor(() => t.$('#code'), 'code screen');
const NEUTRAL = t.$('.notice').textContent;
ok('code requested for a known email, with sign-ups OFF (shouldCreateUser false)', JSON.stringify(t.fake.calls.find((c) => c[0] === 'otp')[1]) === JSON.stringify({ email: 'bryan@example.com', options: { shouldCreateUser: false } }));
ok('neutral message: "If that email is on the league..." (and it does not promise a code length)', /If that email is on the league/.test(NEUTRAL), NEUTRAL);
let t2 = await start({ otpError: { status: 422, message: 'Signups not allowed for otp' } });
await t2.waitFor(() => t2.$('#email'));
t2.type('#email', 'stranger@example.com'); t2.click(t2.btn('Send code'));
await t2.waitFor(() => t2.$('#code'), 'code screen for stranger');
ok('an unknown email gets the IDENTICAL message (the page cannot be used to find out who is on the league)', t2.$('.notice').textContent === NEUTRAL, t2.$('.notice').textContent);
let t3 = await start({ otpError: { status: 429, message: 'For security purposes, you can only request this after 52 seconds' } });
await t3.waitFor(() => t3.$('#email')); t3.type('#email', 'bryan@example.com'); t3.click(t3.btn('Send code'));
await t3.waitFor(() => /wait a minute/.test(t3.text()), 'rate-limit message');
ok('too many code requests: plain "wait a minute" message, stays on the email step', !t3.$('#code'));
t.type('#code', '12'); t.click(t.btn('Sign in'));
await t.waitFor(() => /6 to 8 digits/.test(t.text()));
ok('a short code is refused before any request', !t.fake.calls.some((c) => c[0] === 'verify'));
t.type('#code', '000000'); t.click(t.btn('Sign in'));
await t.waitFor(() => /didn't work/.test(t.text()), 'wrong code message');
ok('a wrong code gets a plain message and stays on the code screen', !!t.$('#code') && !/expired or is invalid/.test(t.text()));
t.type('#code', '123 456'); t.click(t.btn('Sign in'));
await t.waitFor(() => /Week 11/.test(t.text()), 'main screen');
ok('the right code (spaces ignored) signs in and shows My week', /Bryan/.test(t.text()) && /Helen Keller/.test(t.text()));

let t8 = await start();
await t8.waitFor(() => t8.$('#email')); t8.type('#email', 'bryan@example.com'); t8.click(t8.btn('Send code'));
await t8.waitFor(() => t8.$('#code')); t8.type('#code', '1234 5678'); t8.click(t8.btn('Sign in'));
await t8.waitFor(() => /Week 11/.test(t8.text()), 'main screen via 8-digit code');
ok('an 8-digit code (what this project actually emails) works too', t8.fake.calls.find((c) => c[0] === 'verify')[1].token === '12345678');

// ================================================================ My week
console.log('\nMy week (manager)');
t = await start(signedIn('u-bry'));
await t.waitFor(() => t.crewCard('Scott Novak'), 'crews');
ok('shows 3 crews with equal cards', t.$$('.crew').length === 3);
ok('tabs: My week and League, and NO Commissioner tab for a manager', !!t.btn('My week') && !!t.btn('League') && !t.btn('Commissioner'));
const nov = t.crewCard('Scott Novak'), hus = t.crewCard('John Hussey'), rr = t.crewCard('2012 Replacement Refs');
ok('kicked-off crew shows Locked with its game', /Locked/.test(nov.textContent) && /MIA @ BUF/.test(nov.textContent), nov.textContent);
ok('upcoming crew shows Open with its game and kickoff in the READER\'S zone (Central), not ET', /Open/.test(hus.textContent) && /PIT @ PHI/.test(hus.textContent) && /C[SD]T/.test(hus.textContent) && !/E[SD]T/.test(hus.textContent), hus.textContent);
ok('a crew whose game is not posted yet says so (no invented time)', /Game not posted yet/.test(rr.textContent) && !/C[SD]T/.test(rr.textContent), rr.textContent);
ok('current starters are pre-selected (Novak, Hussey)', nov.classList.contains('start') && hus.classList.contains('start') && !rr.classList.contains('start'));
ok('Save is disabled until something changes', t.btn('Save lineup').disabled);
ok('locked crew: Start and captain buttons are disabled', [...nov.querySelectorAll('button')].every((b) => b.disabled));
t.click([...rr.querySelectorAll('button')][0]);
await t.waitFor(() => /Bench one first/.test(t.text()), 'two-starter hint');
ok('starting a third crew explains "bench one first" and changes nothing', !t.crewCard('2012 Replacement Refs').classList.contains('start'));
t.click([...hus.querySelectorAll('button')][0]);   // bench Hussey
await t.waitFor(() => /Pick exactly two/.test(t.text()), 'one-starter message');
ok('one starter: Save disabled with "Pick exactly two starters."', t.btn('Save lineup').disabled);
t.click([...t.crewCard('2012 Replacement Refs').querySelectorAll('button')][0]);   // start RR
await t.waitFor(() => !t.btn('Save lineup').disabled, 'save enabled');
ok('swapping Hussey for the Replacement Refs enables Save, and the page shows the swap', t.crewCard('2012 Replacement Refs').classList.contains('start') && !t.crewCard('John Hussey').classList.contains('start'));
t.click(t.btn('Save lineup'));
await t.waitFor(() => /Saved\./.test(t.text()), 'saved message');
const sl = t.fake.rpcCalls.find((c) => c[0] === 'set_lineup')[1];
ok('Save sent the right request: this team, this week, starters in roster order, no captain (captain would be Week 11+: none chosen)',
  sl.p_team_id === 't-bry' && sl.p_week === 11 && JSON.stringify(sl.p_starters) === JSON.stringify(['Scott Novak', '2012 Replacement Refs']) && sl.p_captain === null, JSON.stringify(sl));

console.log('\nCaptain and the lock');
t = await start(signedIn('u-bry'));
await t.waitFor(() => t.crewCard('Scott Novak'));
const capBtn = (name) => [...t.crewCard(name).querySelectorAll('button')][1];
ok('captain buttons exist from Week 11', !!capBtn('John Hussey'));
ok('a bench crew cannot be captain (button disabled)', capBtn('2012 Replacement Refs').disabled);
t.click(capBtn('John Hussey'));
await t.waitFor(() => !t.btn('Save lineup').disabled, 'captain save enabled');
ok('naming an unlocked starter captain works', capBtn('John Hussey').getAttribute('aria-pressed') === 'true');
t.click(t.btn('Save lineup'));
await t.waitFor(() => /Saved\./.test(t.text()));
ok('...and is sent as the captain', t.fake.rpcCalls.filter((c) => c[0] === 'set_lineup').pop()[1].p_captain === 'John Hussey');
// move the captain onto the locked crew: the lock rule must refuse (Novak kicked off)
t = await start({ ...signedIn('u-bry'), lineups: { 't-bry': { starters: ['Scott Novak', 'John Hussey'], captain: 'John Hussey', from_week: 11 } } });
await t.waitFor(() => t.crewCard('Scott Novak'));
t.crewCard('Scott Novak').querySelectorAll('button')[1].disabled = false;     // even if the button were forced on...
t.crewCard('Scott Novak').querySelectorAll('button')[1].click();
await t.waitFor(() => /already kicked off/.test(t.text()), 'lock message');
ok('...the page itself refuses to move the captain onto a kicked-off crew', t.btn('Save lineup').disabled);

console.log('\nServer says no: its message is shown, in plain words, as text');
t = await start(signedIn('u-bry'));
await t.waitFor(() => t.crewCard('Scott Novak'));
t.fake.setLineupError = "Scott Novak's game has already kicked off, so that spot is locked <b>x</b>";
t.click([...t.crewCard('John Hussey').querySelectorAll('button')][0]);
t.click([...t.crewCard('2012 Replacement Refs').querySelectorAll('button')][0]);
await t.waitFor(() => !t.btn('Save lineup').disabled);
t.click(t.btn('Save lineup'));
await t.waitFor(() => /kicked off, so that spot is locked/.test(t.text()), 'server message');
ok('the server\'s refusal is shown (and a <b> tag in it stays plain text)', !t.$('.notice b') && /<b>x<\/b>/.test(t.text()));
t.fake.setLineupError = null;

console.log('\nWeeks');
t.click(t.btn('Previous week'));
await t.waitFor(() => /Week 10/.test(t.text()) && /Finished/.test(t.text()) && t.$$('.crew').length === 3, 'week 10');
ok('a finished week is closed to a manager: explanation shown and every button disabled', /Ask the commissioner/.test(t.text()) && t.$$('.crew button').every((b) => b.disabled));
t.click(t.btn('Next week')); t.click(t.btn('Next week'));
await t.waitFor(() => t.$('.weeknav h2').textContent === 'Week 12' && t.$$('.crew').length === 3, 'week 12');
ok('a future week is open (crew buttons enabled)', t.$$('.crew button').some((b) => !b.disabled) && !/Finished/.test(t.text()));
ok('captain buttons shown for Week 12', t.$$('.crew').every((c) => c.querySelectorAll('button').length === 2));
for (let i = 0; i < 8; i++) { if (t.btn('Next week').disabled) break; t.click(t.btn('Next week')); await new Promise((r) => setTimeout(r, 5)); }
await t.waitFor(() => t.$('.weeknav h2').textContent === 'Week 18' && t.$$('.crew').length === 3, 'week 18');
ok('week stepper stops at the last week of the season', t.btn('Next week').disabled);
await t.waitFor(() => /not been loaded|Schedule not loaded/.test(t.text()), 'no-schedule notice');
ok('a week with no schedule row is closed ("fail closed"), with an explanation', t.$$('.crew button').every((b) => b.disabled));

console.log('\nTwo quick week changes: the first answer arriving after the page has moved on must not land on the wrong week');
t = await start({ ...signedIn('u-bry'), effDelay: { 13: 150 },
  effFor: (team, week) => week === 12 ? { starters: ['Scott Novak', '2012 Replacement Refs'], captain: null, from_week: 12 }
                                      : { starters: ['John Hussey', '2012 Replacement Refs'], captain: null, from_week: week === 13 ? 13 : 10 } });
await t.waitFor(() => t.crewCard('Scott Novak'));
t.click(t.btn('Next week')); t.click(t.btn('Next week'));          // Week 12 answers quickly, Week 13 answers later
await t.waitFor(() => t.$('.weeknav h2').textContent === 'Week 13' && t.$$('.crew').length === 3, 'week 13');
await new Promise((r) => setTimeout(r, 400));                       // let the slower Week 13 answer arrive too
ok('the page still says Week 13 and shows Week 13\'s lineup (Hussey starts, Novak does not)', t.$('.weeknav h2').textContent === 'Week 13' && t.crewCard('John Hussey').classList.contains('start') && !t.crewCard('Scott Novak').classList.contains('start'), t.$$('.crew').map((c) => c.className).join(' | '));
ok('the draft belongs to Week 13 and holds Week 13\'s lineup', /\|13$/.test(t.L._state.draft.key) && t.L._state.draft.starters.join() === 'John Hussey,2012 Replacement Refs', JSON.stringify(t.L._state.draft));

console.log('\nTapping while a lineup is still loading');
t = await start(signedIn('u-bry'));
await t.waitFor(() => t.crewCard('Scott Novak'));
const staleBtn = [...t.crewCard('John Hussey').querySelectorAll('button')][0];
t.L._state.draft = null;                 // the state during a week change, before the new lineup arrives
let threw = false; try { t.click(staleBtn); } catch (e) { threw = true; }
ok('a tap on an old button while the next lineup loads is ignored (no crash, no change)', !threw && t.L._state.draft === null);
t.click(t.btn('Next week'));
ok('changing week at once replaces the old crews with "Loading lineup…" (no stale buttons to tap)', /Loading lineup/.test(t.text()) && t.$$('.crew').length === 0);
await t.waitFor(() => t.$$('.crew').length === 3, 'new week loaded');

console.log('\nThe clock: a lock engages without reloading');
t = await start({ ...signedIn('u-bry'), slots: [{ season: 2026, week: 11, crew: 'John Hussey', kickoff_at: iso(Date.now() + 60e3) }, { season: 2026, week: 11, crew: 'Scott Novak', kickoff_at: iso(Date.now() - H) }] });
await t.waitFor(() => t.crewCard('John Hussey'));
ok('before kickoff: Hussey is Open', /Open/.test(t.crewCard('John Hussey').textContent) && !t.crewCard('John Hussey').querySelector('button').disabled);
t.L._state.slots['11|John Hussey'].kickoff_at = iso(Date.now() - 1000);
t.L._tick();
ok('after kickoff: the card flips to Locked and its buttons disable', /Locked/.test(t.crewCard('John Hussey').textContent) && t.crewCard('John Hussey').querySelector('button').disabled);

// ================================================================ League
console.log('\nLeague');
t = await start(signedIn('u-bry'));
await t.waitFor(() => t.crewCard('Scott Novak'));
t.click(t.btn('League'));
await t.waitFor(() => /Standings/.test(t.text()) && !/Loading/.test(t.text()), 'league screen');
ok('shows the matchup with both teams\' lineups from the server', /Bryan/.test(t.text()) && /Matthew/.test(t.text()) && /Alex Moore \+ Ron Torbert\s+·\s+Captain: Alex Moore/.test(t.text()), t.text().slice(0, 400));
ok('shows standings', /3-1-0/.test(t.text()));
ok('asked the server for the lineup of each team (3 here)', t.fake.rpcCalls.filter((c) => c[0] === 'effective_lineup' && c[1].p_week === 11).map((c) => c[1].p_team_id).filter((v, i, a) => a.indexOf(v) === i).length === 3);

// ================================================================ outsider
console.log('\nSigned in but not on the league');
t = await start({ ...signedIn('u-out'), members: [] });
await t.waitFor(() => /Not on the league/.test(t.text()), 'outsider screen');
ok('shows a plain "not on the league yet" screen and loads no league data', !t.fake.calls.some((c) => c[0] === 'from' && c[1] !== 'league_members'));

// ================================================================ commissioner
console.log('\nCommissioner');
t = await start(signedIn('u-mat'));
await t.waitFor(() => t.crewCard('Alex Moore'));
ok('the Commissioner tab exists', !!t.btn('Commissioner'));
ok('a crew that is off this week says "Off this week" (Alan Eck, per the public data)', /Off this week/.test(t.crewCard('Alan Eck').textContent), t.crewCard('Alan Eck').textContent);
t.click(t.btn('Commissioner'));
await t.waitFor(() => t.$('.log') && t.$$('.crew').length === 3, 'commissioner screen');
ok('change log shows who did what, in words', /Matthew corrected a finished week for Bryan's lineup, Week 10: Scott Novak \+ John Hussey/.test(t.text()), t.text().slice(-400));
t.win.document.querySelector('#cteam').value = 't-bry';
t.win.document.querySelector('#cteam').dispatchEvent(new t.win.Event('change', { bubbles: true }));
await t.waitFor(() => /You're setting Bryan's lineup/.test(t.text()) && t.$$('.crew').length === 3 && t.crewCard('Scott Novak'), 'other-team banner');
ok('choosing another team shows "You\'re setting Bryan\'s lineup... flagged as yours"', /flagged as yours/.test(t.text()));
ok('the commissioner may touch a kicked-off crew (override)', !t.crewCard('Scott Novak').querySelector('button').disabled);
t.click(t.btn('Previous week'));
await t.waitFor(() => t.$('.weeknav h2').textContent === 'Week 10' && t.crewCard('Scott Novak'), 'week 10');
ok('a finished week is NOT closed to the commissioner', !t.crewCard('Scott Novak').querySelector('button').disabled);
t.click([...t.crewCard('John Hussey').querySelectorAll('button')][0]);
t.click([...t.crewCard('2012 Replacement Refs').querySelectorAll('button')][0]);
await t.waitFor(() => t.btn('Save correction') && !t.btn('Save correction').disabled, 'correction button');
t.click(t.btn('Save correction'));
await t.waitFor(() => t.btn('Confirm correction'), 'confirm step');
ok('correcting a finished week first shows how far it reaches ("Weeks 10 to 11") and asks to confirm', /Weeks 10 to 11/.test(t.text()) && /standings can change/.test(t.text()));
ok('...and nothing was saved yet', !t.fake.rpcCalls.some((c) => c[0] === 'set_lineup'));
t.click(t.btn('Confirm correction'));
await t.waitFor(() => t.fake.rpcCalls.some((c) => c[0] === 'set_lineup'), 'save after confirm');
const cs = t.fake.rpcCalls.find((c) => c[0] === 'set_lineup')[1];
ok('after confirming, it saves for Bryan\'s team, Week 10', cs.p_team_id === 't-bry' && cs.p_week === 10 && cs.p_starters[0] === 'Scott Novak', JSON.stringify(cs));

// ================================================================ new behaviours (round 2)
console.log('\nCommissioner: confirm before changing a kicked-off crew');
t = await start(signedIn('u-mat'));
await t.waitFor(() => t.crewCard('Alex Moore') && t.crewCard('Alan Eck'));
const btnAt = (name, i) => [...t.crewCard(name).querySelectorAll('button')][i];
ok('a note tells the commissioner that locks do not stop them', /locks and finished weeks don't stop you/.test(t.text()));
ok('...and her kicked-off crew (Alex Moore, Locked) is still editable', /Locked/.test(t.crewCard('Alex Moore').textContent) && !btnAt('Alex Moore', 0).disabled);
t.click(btnAt('Ron Torbert', 1));                       // make Ron captain: touches Alex (the old captain), who has kicked off
await t.waitFor(() => !t.btn('Save lineup').disabled, 'save enabled');
t.click(t.btn('Save lineup'));
await t.waitFor(() => t.btn('Confirm change'), 'confirm step');
ok('touching a kicked-off crew asks first, naming the crew', /Alex Moore's game has already kicked off/.test(t.text()) && /after the fact/.test(t.text()), t.text().slice(0, 300));
ok('...and nothing is saved until she confirms', !t.fake.rpcCalls.some((c) => c[0] === 'set_lineup'));
t.click(t.btn('Confirm change'));
await t.waitFor(() => t.fake.rpcCalls.some((c) => c[0] === 'set_lineup') && /Saved\./.test(t.text()), 'saved after confirm');
ok('after confirming it saves (captain Ron)', t.fake.rpcCalls.find((c) => c[0] === 'set_lineup')[1].p_captain === 'Ron Torbert');
ok('"Saved." is shown exactly once (no duplicate message)', (t.text().match(/Saved\./g) || []).length === 1, (t.text().match(/Saved\./g) || []).length);

console.log('\nCaptain with no game: a warning, but doable');
t = await start(signedIn('u-mat'));
await t.waitFor(() => t.crewCard('Alex Moore') && t.crewCard('Alan Eck'));
t.click(btnAt('Ron Torbert', 0));                       // bench Ron
t.click(btnAt('Alan Eck', 0));                          // start Alan Eck, who is OFF this week
t.click(btnAt('Alan Eck', 1));                          // ...and make him captain
await t.waitFor(() => /Alan Eck has no game this week/.test(t.text()), 'warning');
ok('the warning says the bonus will earn little or nothing, and that she can still save', /earn little or nothing\. You can still save/.test(t.text()));
ok('...and Save is NOT blocked', !t.btn('Save lineup').disabled);
t.click(t.btn('Save lineup'));
await t.waitFor(() => t.btn('Confirm change'));
t.click(t.btn('Confirm change'));
await t.waitFor(() => t.fake.rpcCalls.some((c) => c[0] === 'set_lineup'), 'save');
ok('...and it saves with the off-week crew as captain', t.fake.rpcCalls.find((c) => c[0] === 'set_lineup')[1].p_captain === 'Alan Eck');
t = await start(signedIn('u-mat'));
await t.waitFor(() => t.crewCard('Alex Moore'));
ok('no warning when the captain has a game', !/has no game this week, so the captain bonus/.test(t.text()));

console.log('\nStarting a crew with no game while a working crew sits on the bench');
t = await start(signedIn('u-mat'));
await t.waitFor(() => t.crewCard('Alex Moore') && t.crewCard('Alan Eck'));
ok('no warning at first (both starters play)', !/A starter with no game scores 0/.test(t.text()));
t.click(btnAt('Ron Torbert', 0)); t.click(btnAt('Alan Eck', 0));      // bench Ron (plays), start Alan Eck (off)
await t.waitFor(() => /Alan Eck has no game this week, and Ron Torbert does\. A starter with no game scores 0\. You can still save\./.test(t.text()), 'bench warning');
ok('...and Save is NOT blocked', !t.btn('Save lineup').disabled);
const offBoth = { ...PUB, off_weeks: { 11: ['Alan Eck', 'Ron Torbert'] } };
t = await start({ ...signedIn('u-mat'), pub: offBoth });
await t.waitFor(() => t.crewCard('Alex Moore') && t.crewCard('Alan Eck'));
t.click(btnAt('Ron Torbert', 0)); t.click(btnAt('Alan Eck', 0));      // starter Eck is off, but the only bench crew (Ron) is off too
await t.waitFor(() => t.crewCard('Alan Eck').classList.contains('start'));
ok('no warning when every crew on the bench is also off (the open-spot rule covers it)', !/A starter with no game scores 0/.test(t.text()));

console.log('\nCommissioner changing an UNLOCKED week saves without a confirm step');
t = await start(signedIn('u-mat'));
await t.waitFor(() => t.crewCard('Alex Moore'));
t.click(t.btn('Next week'));
await t.waitFor(() => t.$('.weeknav h2').textContent === 'Week 12' && t.$$('.crew').length === 3, 'week 12');
t.click(btnAt('Ron Torbert', 0)); t.click(btnAt('Alan Eck', 0));
await t.waitFor(() => !t.btn('Save lineup').disabled);
t.click(t.btn('Save lineup'));
await t.waitFor(() => t.fake.rpcCalls.some((c) => c[0] === 'set_lineup'), 'direct save');
ok('no kicked-off crew touched: saved directly, no confirm', !t.btn('Confirm change') && !t.btn('Confirm correction'));

console.log('\nA manager never sees commissioner prompts');
t = await start(signedIn('u-bry'));
await t.waitFor(() => t.crewCard('Scott Novak'));
ok('no commissioner note for a manager', !/don't stop you/.test(t.text()));

// ================================================================ escaping
console.log('\nHostile text stays text');
const EVIL = '<img src=x onerror="window.__pwned=1">';
const evilPub = { ...PUB, weeks: [{ week: 11, games: [{ name: EVIL, a: EVIL, b: TEAMS[1].name }] }],
  standings: [{ team: EVIL, manager: '<script>window.__pwned=1</script>', w: 1, l: 0, t: 0, pf: EVIL }] };
t = await start({ ...signedIn('u-mat'), pub: evilPub,
  teams: [{ id: 't-bry', league_id: 'L1', name: EVIL, manager_name: '<script>window.__pwned=1</script>' }, TEAMS[1], TEAMS[2]],
  audit: [{ action: 'lineup_set', actor: 'u-bry', created_at: iso(NOW), detail: { team_id: 't-bry', week: 11, starters: [EVIL, '<b>x</b>'], captain: EVIL } }] });
await t.waitFor(() => t.crewCard('Alex Moore'));
t.click(t.btn('Commissioner'));
await t.waitFor(() => t.$('.log') && t.$$('.crew').length === 3);
const safe = () => !t.$('img') && !t.$('b') && !t.$$('script').some((x) => !x.src) && t.win.__pwned === undefined;
ok('commissioner screen (team picker + change log): hostile names are shown as plain text, never as elements',
   safe() && t.text().includes('<img src=x') && t.text().includes('<script>window.__pwned=1</script>') && t.text().includes('<b>x</b>'), t.win.document.body.innerHTML.slice(0, 300));
t.click(t.btn('League'));
await t.waitFor(() => /Standings/.test(t.text()) && !/Loading/.test(t.text()));
ok('league screen (matchup titles, team names, standings): same', safe() && t.text().includes('<img src=x'));
ok('...and nothing ran', t.win.__pwned === undefined);

// ================================================================ sign out
console.log('\nSign out');
t = await start(signedIn('u-bry'));
await t.waitFor(() => t.crewCard('Scott Novak'));
t.click(t.btn('Sign out'));
await t.waitFor(() => t.$('#email'), 'sign-in screen again');
ok('signing out returns to the sign-in screen and forgets the league', !/Helen Keller/.test(t.text()) && t.L._state.teams.length === 0);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
