// Local rehearsal of the database rules, in a throwaway in-memory Postgres (PGlite). No network, no secrets.
// Run:  PGLITE_DIR=<folder containing node_modules/@electric-sql/pglite> node supabase/tests/local_check.mjs
// It builds the real migrations + seeds in memory, then tries the rules. Nothing is saved anywhere.
import { readFileSync, readdirSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';
import path from 'node:path';

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const req = createRequire(path.join(process.env.PGLITE_DIR || '.', 'x.js'));
const { PGlite } = await import(pathToFileURL(req.resolve('@electric-sql/pglite')).href);
const db = new PGlite();

// Stand-ins for what Supabase provides itself: the three visitor roles, auth.users, auth.uid().
await db.exec(`
  create role anon nologin; create role authenticated nologin; create role service_role nologin bypassrls;  -- like Supabase: the bot skips row rules
  create schema auth;
  create table auth.users (id uuid primary key default gen_random_uuid(), email text);
  create function auth.uid() returns uuid language sql stable as
    $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
  grant usage on schema auth, public to anon, authenticated, service_role;
  grant execute on function auth.uid() to anon, authenticated, service_role;
  insert into auth.users (email) values ('ll-commish@example.com'),('ll-bryan@example.com'),
    ('ll-mike@example.com'),('ll-outsider@example.com');
`);
for (const f of readdirSync(path.join(root, 'migrations')).sort()) {
  await db.exec(readFileSync(path.join(root, 'migrations', f), 'utf8'));
}
await db.exec(readFileSync(path.join(root, 'seed/rehearsal.sql'), 'utf8'));
await db.exec(readFileSync(path.join(root, 'seed/rehearsal_weeks.sql'), 'utf8'));

let pass = 0, fail = 0;
const ok = (label, cond, extra = '') => { cond ? pass++ : fail++; console.log((cond ? 'PASS - ' : 'FAIL - ') + label + (cond ? '' : '   [' + extra + ']')); };
const uid = async (email) => (await db.query('select id from auth.users where email=$1', [email])).rows[0].id;
const team = async (m) => (await db.query('select id from public.teams where manager_name=$1', [m])).rows[0].id;
const U = { comm: await uid('ll-commish@example.com'), bry: await uid('ll-bryan@example.com'),
            mike: await uid('ll-mike@example.com'), out: await uid('ll-outsider@example.com') };
const TB = await team('Bryan'), TM = await team('Matthew'), TMK = await team('Mike');

// Run SQL as a given kind of visitor. Returns {rows} or {error}. Always restores the superuser role.
async function as(who, sql, params = []) {
  const role = who === 'anon' ? 'anon' : who === 'bot' ? 'service_role' : 'authenticated';
  await db.exec(`set role ${role}; select set_config('request.jwt.claim.sub', '${U[who] || ''}', false);`);
  try { return { rows: (await db.query(sql, params)).rows }; }
  catch (e) { return { error: e.message }; }
  finally { await db.exec(`reset role; select set_config('request.jwt.claim.sub', '', false);`); }
}
const lineup = (who, t, w, s, c = null) =>
  as(who, 'select public.set_lineup($1,$2,$3,$4) as id', [t, w, s, c]);
const refused = (label, r, text) => ok(label, !!r.error && (!text || r.error.toLowerCase().includes(text.toLowerCase())), JSON.stringify(r));
const worked = (label, r) => ok(label, !r.error, JSON.stringify(r));
const NOVAK = 'Scott Novak', HUSSEY = 'John Hussey', RR = '2012 Replacement Refs';

console.log('\nFinished weeks (Week 10 ended in the past)');
refused('manager cannot save a lineup for a finished week', await lineup('bry', TB, 10, [NOVAK, HUSSEY]), 'finished');
refused('...even a different lineup for Week 8', await lineup('bry', TB, 8, [HUSSEY, RR]), 'finished');
refused('...and Mike cannot either', await lineup('mike', TMK, 9, ['Craig Wrolstad', 'Brad Allen']), 'finished');
worked('commissioner CAN correct Bryan\'s finished Week 10', await lineup('comm', TB, 10, [HUSSEY, RR]));
let a = (await db.query(`select action, detail from public.audit_log order by id desc limit 1`)).rows[0];
ok('that correction is logged as lineup_set_past_week with past_week=true', a.action === 'lineup_set_past_week' && a.detail.past_week === true, JSON.stringify(a));
worked('commissioner can correct their OWN finished week too', await lineup('comm', TM, 9, ['Alex Moore', 'Ron Torbert']));
a = (await db.query(`select action from public.audit_log order by id desc limit 1`)).rows[0];
ok('...also logged as lineup_set_past_week', a.action === 'lineup_set_past_week', a.action);
refused('a correction still has to be a legal lineup (crew not on roster)', await lineup('comm', TB, 10, [NOVAK, 'Alex Moore']), 'not on this team');
ok('history kept (append-only): both corrections are new rows', (await db.query('select count(*)::int n from public.lineups')).rows[0].n === 2);

console.log('\nLineup effect range (which weeks a correction changes)');
await lineup('bry', TB, 12, [HUSSEY, RR]);                       // Bryan has his own Week 12 row now
let r = await as('comm', 'select * from public.lineup_effect_range($1, 10)', [TB]);
ok('Bryan Week 10 correction changes weeks 10 to 11 (his next own row is Week 12)', r.rows?.[0]?.from_week === 10 && r.rows[0].to_week === 11, JSON.stringify(r));
r = await as('comm', 'select * from public.lineup_effect_range($1, 9)', [TMK]);
ok('a team with no later row: changes run to the end of the season (Week 18)', r.rows?.[0]?.to_week === 18, JSON.stringify(r));
refused('outsider cannot ask for it', await as('out', 'select * from public.lineup_effect_range($1, 10)', [TB]), 'not allowed');
refused('not signed in cannot ask for it', await as('anon', 'select * from public.lineup_effect_range($1, 10)', [TB]));

console.log('\neffective_lineup (who actually starts)');
r = await as('mike', 'select * from public.effective_lineup($1, 11)', [TB]);
ok('Week 11 for Bryan = his Week 10 correction carried forward', JSON.stringify(r.rows?.[0]?.starters) === JSON.stringify([HUSSEY, RR]) && r.rows[0].from_week === 10, JSON.stringify(r));
r = await as('mike', 'select * from public.effective_lineup($1, 12)', [TB]);
ok('Week 12 = his own Week 12 row', r.rows?.[0]?.from_week === 12, JSON.stringify(r));
r = await as('bry', 'select * from public.effective_lineup($1, 9)', [TB]);
ok('before any saved row: default = first two roster crews, no captain',
   JSON.stringify(r.rows?.[0]?.starters) === JSON.stringify([NOVAK, HUSSEY]) && r.rows[0].captain === null && r.rows[0].from_week === null, JSON.stringify(r));
refused('outsider cannot read effective_lineup', await as('out', 'select * from public.effective_lineup($1, 11)', [TB]), 'not allowed');
refused('no such team gives the same refusal', await as('out', 'select * from public.effective_lineup($1, 11)', ['00000000-0000-0000-0000-000000000000']), 'not allowed');
refused('not signed in cannot call it', await as('anon', 'select * from public.effective_lineup($1, 11)', [TB]));

console.log('\nFail closed (the lock must not silently switch off)');
await db.exec(`delete from public.weeks where week = 14`);
refused('manager: week with no schedule row is refused', await lineup('bry', TB, 14, [NOVAK, HUSSEY]), 'not been loaded');
worked('commissioner can still set a week with no schedule row', await lineup('comm', TB, 14, [NOVAK, HUSSEY]));
await db.exec(`update public.weeks set starts_at = '2026-11-02 00:00+00' where week = 13`);   // started, no kickoff times
refused('manager: week started but no kickoff times synced is refused', await lineup('bry', TB, 13, [NOVAK, HUSSEY]), 'kickoff times are missing');
worked('commissioner can still set it', await lineup('comm', TB, 13, [NOVAK, HUSSEY]));
await db.exec(`insert into public.game_slots values (2026, 13, 'Scott Novak', '2099-01-08 00:00+00')`);
worked('once kickoffs are synced the manager can save again', await lineup('bry', TB, 13, [NOVAK, HUSSEY]));

console.log('\nThe old rules still hold (Mike: Wrolstad has kicked off in Week 11, Allen has not)');
const CW = 'Craig Wrolstad', BA = 'Brad Allen', CB = 'Clete Blakeman';
refused('bench kicked-off Wrolstad in Week 11', await lineup('mike', TMK, 11, [BA, CB]), 'locked');
refused('make kicked-off Wrolstad captain in Week 11', await lineup('mike', TMK, 11, [CW, BA], CW), 'locked');
worked('Week 11: captain Allen (not kicked off)', await lineup('mike', TMK, 11, [CW, BA], BA));
refused('captain before Week 11', await lineup('mike', TMK, 10, [CW, BA], BA), 'captains start');
refused('captain before Week 11 (commissioner, so the week rule is out of the way)', await lineup('comm', TMK, 10, [CW, BA], BA), 'captains start');
refused('someone else\'s team', await lineup('bry', TMK, 12, [CW, BA]), 'not allowed');
worked('commissioner lock override in Week 11', await lineup('comm', TMK, 11, [BA, CB]));
a = (await db.query(`select action from public.audit_log order by id desc limit 1`)).rows[0];
ok('...logged as lineup_set_by_commissioner', a.action === 'lineup_set_by_commissioner', a.action);

console.log('\nThe back door stays shut');
for (const who of ['bry', 'comm', 'out', 'anon']) {
  for (const t of ['weeks', 'sync_status']) {
    ok(`${who} cannot insert into ${t}`, !!(await as(who, t === 'weeks'
      ? `insert into public.weeks values (2026, 99, now(), now() + interval '1 day')`
      : `insert into public.sync_status values ('kickoffs', now(), '{}')`)).error);
  }
}
const before = (await db.query(`select count(*)::int n, min(ends_at) e from public.weeks`)).rows[0];
await as('comm', `update public.weeks set ends_at = starts_at + interval '1 hour'`);
await as('comm', `delete from public.weeks`);
const after = (await db.query(`select count(*)::int n, min(ends_at) e from public.weeks`)).rows[0];
ok('a commissioner\'s update/delete on weeks changed nothing', before.n === after.n && String(before.e) === String(after.e));
ok('anon cannot read weeks', !!(await as('anon', 'select * from public.weeks')).error);
ok('signed-in can read weeks', (await as('out', 'select * from public.weeks')).rows?.length === before.n);
ok('signed-in can read sync_status (a heartbeat, nothing secret)', !(await as('out', 'select * from public.sync_status')).error);
worked('the bot (service role) can write weeks', await as('bot', `insert into public.weeks values (2026, 99, now(), now() + interval '1 day')`));
worked('the bot can write the heartbeat', await as('bot', `insert into public.sync_status values ('kickoffs', now(), '{}')`));
ok('no add_member function exists for clients to call', (await db.query(`select count(*)::int n from pg_proc where proname = 'add_member'`)).rows[0].n === 0);
ok('only the expected public functions exist', JSON.stringify((await db.query(`select proname from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='public' order by 1`)).rows.map(x => x.proname)) === JSON.stringify(['effective_lineup', 'lineup_effect_range', 'lineups_are_append_only', 'set_lineup']), '');
ok('lineup history still append-only', !!(await db.query('update public.lineups set week = 9').catch(e => ({ error: 1 }))).error);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
