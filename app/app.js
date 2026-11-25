/* Laundry League lineup app.
 *
 * Four screens: Sign in, My week, League, Commissioner.
 * The SERVER decides everything (who you are, what you may change, what is locked). This page only shows the
 * server's answers and mirrors its lock rule so that buttons can be greyed out. If the page and the server ever
 * disagree, the server wins and its message is shown.
 *
 * Safety rules for this file:
 *   - Never use innerHTML (or anything that parses HTML). Every name, message and number is put on the page with
 *     textContent, so nothing a server returns can be run as code. Run supabase/tests/app_check.mjs to re-check.
 *   - The only key here is the PUBLISHABLE key from config.js.
 */
(function () {
  'use strict';

  const CFG = window.LL_CONFIG || {};
  const LL = (window.LLApp = {});
  const sb = window.supabase.createClient(CFG.supabaseUrl, CFG.publishableKey, {
    auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: false },
  });

  // ------------------------------------------------------------------ tiny DOM helper
  // h('div', {class: 'card', onclick: fn}, 'text', childNode, [more, nodes])  -> element
  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    for (const k in props || {}) {
      const v = props[k];
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'value') el.value = v;
      else if (k.slice(0, 2) === 'on') el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? '' : String(v));
    }
    (function add(list) {
      for (const c of list) {
        if (c === null || c === undefined || c === false) continue;
        if (Array.isArray(c)) add(c);
        else el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
      }
    })(kids);
    return el;
  }

  // ------------------------------------------------------------------ state
  const S = {
    view: 'boot',            // boot | signin | loading | outsider | main | error
    tab: 'week',             // week | league | commish
    signin: { step: 'email', email: '', code: '', msg: null, busy: false },
    me: null, league: null, teams: [], roster: {}, members: [], weeks: {}, slots: {}, pub: null,
    week: null, cTeam: null,
    eff: {},                 // "teamId|week" -> {starters, captain, from_week}
    draft: null,             // {key, starters, captain}
    msg: null,               // {kind: 'ok'|'err'|'warn', text}
    busy: false, confirm: null, justSaved: false, audit: [], now: Date.now(), sig: '', fatal: null,
    gen: 0,                  // bumped on every sign-out: an answer that arrives for an earlier "generation" is thrown away
  };
  LL._state = S;

  const root = () => document.getElementById('app');

  // ------------------------------------------------------------------ pure helpers (also used by the tests)
  /** "Sun 12:00 PM CST": the kickoff in the READER's own time zone, with its abbreviation. */
  function fmtKickoff(iso, opts) {
    const d = new Date(iso);
    if (isNaN(d)) return '';
    return new Intl.DateTimeFormat('en-US', {
      weekday: 'short', hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
      timeZone: opts && opts.timeZone,
    }).format(d);
  }
  function fmtStamp(iso) {
    const d = new Date(iso);
    return isNaN(d) ? '' : new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' }).format(d);
  }

  /** The server's lock rule: which crew (if any) would this change touch that has already kicked off?
   *  cur / next = {starters: [..], captain: name|null}; isLocked(crew) -> boolean. */
  function lockConflict(cur, next, isLocked) {
    const touched = new Set();
    cur.starters.forEach((c) => { if (next.starters.indexOf(c) < 0) touched.add(c); });
    next.starters.forEach((c) => { if (cur.starters.indexOf(c) < 0) touched.add(c); });
    if ((cur.captain || null) !== (next.captain || null)) {
      if (cur.captain) touched.add(cur.captain);
      if (next.captain) touched.add(next.captain);
    }
    for (const c of touched) if (isLocked(c)) return c;
    return null;
  }
  const sameLineup = (a, b) =>
    [...a.starters].sort().join('|') === [...b.starters].sort().join('|') && (a.captain || null) === (b.captain || null);
  LL.fmtKickoff = fmtKickoff;
  LL.lockConflict = lockConflict;

  function friendly(err) {
    const m = String((err && err.message) || err || '');
    if (/failed to fetch|networkerror|load failed|network request failed/i.test(m)) return "Can't reach the league server. Check your connection and try again.";
    return m ? m.slice(0, 240) : 'Something went wrong. Try again.';
  }
  async function q(promise) {
    const r = await promise;
    if (r.error) throw r.error;
    return r.data;
  }

  // ------------------------------------------------------------------ league knowledge
  const teamById = (id) => S.teams.find((t) => t.id === id);
  const myTeam = () => teamById(S.me && S.me.team_id);
  const isCommish = () => !!S.me && S.me.role === 'commissioner';
  const crewsOf = (teamId) => (S.roster[teamId] || []).map((r) => r.crew);
  const captainsOn = (week) => S.league.captain_start_week != null && week >= S.league.captain_start_week;

  function weekState(week) {
    const w = S.weeks[week];
    if (!w) return 'noschedule';
    if (new Date(w.ends_at) <= S.now) return 'past';
    if (new Date(w.starts_at) <= S.now && !Object.keys(S.slots).some((k) => k.indexOf(week + '|') === 0)) return 'nokickoffs';
    return 'open';
  }
  const slotOf = (week, crew) => S.slots[week + '|' + crew] || null;
  const kickedOff = (week, crew) => { const s = slotOf(week, crew); return !!s && new Date(s.kickoff_at) <= S.now; };

  /** The game (from the public page's data) that a crew works in a week, if known. */
  function gameFor(week, crew) {
    const p = S.pub;
    if (!p) return null;
    const fixes = p.game_fixes || {};
    const asg = ((p.assignments || {})[week] || {}).games || {};
    for (const g of (p.schedule || {})[week] || []) {
      const fx = fixes[g.gid] || {};
      if (fx.cancelled === crew) return { label: g.game, cancelled: true };
      if ((fx.crew || g.referee || asg[g.gid]) === crew && !fx.cancelled) return { label: g.game };
    }
    return null;
  }
  const isOff = (week, crew) => !!(S.pub && ((S.pub.off_weeks || {})[week] || []).indexOf(crew) >= 0);

  function crewStatus(week, crew) {
    const game = gameFor(week, crew), slot = slotOf(week, crew);
    const when = slot ? fmtKickoff(slot.kickoff_at) : '';
    if (isOff(week, crew)) return { kind: 'off', badge: 'Off this week', text: 'No game this week' };
    if (game && game.cancelled) return { kind: 'off', badge: 'Cancelled', text: game.label + ' was cancelled' };
    if (kickedOff(week, crew)) return { kind: 'locked', badge: 'Locked', text: [game && game.label, 'kicked off ' + when].filter(Boolean).join(' · ') };
    if (slot) return { kind: 'open', badge: 'Open', text: [game && game.label, when].filter(Boolean).join(' · ') };
    return { kind: 'none', badge: 'Open', text: game ? game.label + ' · kickoff time not posted yet' : 'Game not posted yet' };
  }

  // ------------------------------------------------------------------ data loading
  async function loadAll() {
    // If you sign out while this is still loading, everything it fetches is thrown away (nothing is written to the page).
    const gen = S.gen, gone = () => gen !== S.gen;
    S.view = 'loading'; render();
    try {
      const uid = S.session.user.id;
      const mem = await q(sb.from('league_members').select('league_id,role,team_id').eq('user_id', uid));
      if (gone()) return;
      if (!mem.length) { S.view = 'outsider'; return render(); }
      const me = mem[0];
      const league = await q(sb.from('leagues').select('id,name,season,start_week,captain_start_week,playoff_week').eq('id', me.league_id).single());
      if (gone()) return;
      const [teams, roster, members] = await Promise.all([
        q(sb.from('teams').select('id,name,manager_name').eq('league_id', league.id).order('manager_name')),
        q(sb.from('roster').select('team_id,slot,crew').order('slot')),
        q(sb.from('league_members').select('user_id,role,team_id')),
      ]);
      if (gone()) return;
      S.me = me; S.league = league; S.teams = teams; S.members = members; S.roster = {};
      roster.forEach((r) => { (S.roster[r.team_id] = S.roster[r.team_id] || []).push(r); });
      await refreshSchedule();
      if (gone()) return;
      const pubWeek = S.pub && S.pub.current_week;
      const open = Object.values(S.weeks).filter((w) => new Date(w.ends_at) > S.now).map((w) => w.week).sort((a, b) => a - b)[0];
      S.week = clampWeek(pubWeek || open || S.league.start_week);
      S.cTeam = S.me.team_id || (S.teams[0] && S.teams[0].id);
      S.view = 'main'; S.tab = 'week'; S.msg = null; S.draft = null; S.confirm = null; S.eff = {};
      render();
      await refreshTab();
    } catch (e) {
      if (gone()) return;
      S.view = 'error'; S.fatal = friendly(e); render();
    }
  }

  async function refreshSchedule() {
    const gen = S.gen, season = S.league.season;
    const [weeks, slots, pub] = await Promise.all([
      q(sb.from('weeks').select('week,starts_at,ends_at').eq('season', season)),
      q(sb.from('game_slots').select('week,crew,kickoff_at').eq('season', season)),
      fetch(CFG.dataUrl || 'data.json', { cache: 'no-store' }).then((r) => (r.ok ? r.json() : null)).catch(() => null),
    ]);
    if (gen !== S.gen) return;                        // signed out while this was loading
    S.weeks = {}; weeks.forEach((w) => { S.weeks[w.week] = w; });
    S.slots = {}; slots.forEach((s) => { S.slots[s.week + '|' + s.crew] = s; });
    S.pub = pub;
    S.now = Date.now();
  }

  const clampWeek = (w) => Math.max(S.league.start_week, Math.min(S.league.playoff_week, w));

  async function getEff(teamId, week, force) {
    const key = teamId + '|' + week;
    if (!force && S.eff[key]) return S.eff[key];
    const rows = await q(sb.rpc('effective_lineup', { p_team_id: teamId, p_week: week }));
    S.eff[key] = rows[0] || { starters: [], captain: null, from_week: null };
    return S.eff[key];
  }

  /** Load whatever the current tab needs, then draw. */
  async function refreshTab() {
    // Remember what we were asked about. If you move to another week, team or tab while an answer is on its way,
    // that answer is for the wrong place and must be thrown away (a newer call is already fetching the right one).
    const week = S.week, tab = S.tab, team = S.cTeam, gen = S.gen;
    const stale = () => S.week !== week || S.tab !== tab || S.cTeam !== team || S.gen !== gen;
    try {
      if (S.tab === 'week' || S.tab === 'commish') {
        const tid = S.tab === 'week' ? S.me.team_id : S.cTeam;
        if (tid) {
          const e = await getEff(tid, week);
          if (stale()) return;
          const key = tid + '|' + week;
          if (!S.draft || S.draft.key !== key) S.draft = { key, starters: e.starters.slice(), captain: e.captain || null };
        }
        if (S.tab === 'commish') S.audit = await q(sb.from('audit_log').select('action,actor,detail,created_at').order('created_at', { ascending: false }).limit(25));
      } else if (S.tab === 'league') {
        await Promise.all(S.teams.map((t) => getEff(t.id, S.week)));
      }
      render();
    } catch (e) { S.msg = { kind: 'err', text: friendly(e) }; render(); }
  }

  // ------------------------------------------------------------------ sign in
  async function sendCode() {
    const si = S.signin, email = si.email.trim();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) { si.msg = { kind: 'err', text: 'Type the email address you use for the league.' }; return render(); }
    si.busy = true; si.msg = null; render();
    const { error } = await sb.auth.signInWithOtp({ email, options: { shouldCreateUser: false } });
    si.busy = false;
    if (error && (error.status === 429 || /rate|too many|seconds/i.test(error.message || ''))) {
      si.msg = { kind: 'err', text: 'Please wait a minute before asking for another code.' };
    } else if (error && /failed to fetch|network/i.test(error.message || '')) {
      si.msg = { kind: 'err', text: friendly(error) };
    } else {
      // Same message whether or not the email is on the league, so nobody can use this page to find out who is.
      si.step = 'code'; si.code = '';
      si.msg = { kind: 'ok', text: 'If that email is on the league, a code is on its way. It can take a minute.' };
    }
    render();
  }
  async function checkCode() {
    const si = S.signin, token = si.code.replace(/\s+/g, '');
    if (!/^\d{6,8}$/.test(token)) { si.msg = { kind: 'err', text: 'The code is the 6 to 8 digits from your email.' }; return render(); }
    si.busy = true; si.msg = null; render();
    const { data, error } = await sb.auth.verifyOtp({ email: si.email.trim(), token, type: 'email' });
    si.busy = false;
    if (error || !data || !data.session) {
      si.msg = { kind: 'err', text: /failed to fetch|network/i.test((error && error.message) || '') ? friendly(error) : "That code didn't work. Check it, or go back and ask for a new one." };
      return render();
    }
    S.session = data.session;
    S.signin = { step: 'email', email: '', code: '', msg: null, busy: false };
    loadAll();
  }
  async function signOut() {
    await sb.auth.signOut();
    resetToSignIn();
  }
  function resetToSignIn() {
    S.gen += 1;               // anything still loading from before this moment must now be ignored
    Object.assign(S, { session: null, me: null, league: null, teams: [], roster: {}, members: [], weeks: {}, slots: {}, pub: null,
      eff: {}, draft: null, msg: null, confirm: null, audit: [], view: 'signin', tab: 'week',
      signin: { step: 'email', email: '', code: '', msg: null, busy: false } });
    render();
  }

  // ------------------------------------------------------------------ saving
  function draftValid(d) {
    return d.starters.length === 2 && (!d.captain || d.starters.indexOf(d.captain) >= 0);
  }
  /** A draft change, refused up front if it would touch a crew that has kicked off (unless you are the commissioner). */
  function tryDraft(teamId, change) {
    const d = S.draft, cur = d && S.eff[d.key];
    if (!d || !cur) return;                      // a tap while a lineup is still loading: ignore it
    const next = { starters: d.starters.slice(), captain: d.captain };
    const warn = change(next);
    if (warn) { S.msg = warn; return render(); }
    if (next.captain && next.starters.indexOf(next.captain) < 0) next.captain = null;
    if (!isCommish()) {
      const hit = lockConflict(cur, next, (c) => kickedOff(S.week, c));
      if (hit) { S.msg = { kind: 'err', text: hit + "'s game has already kicked off, so that spot is locked." }; return render(); }
    }
    S.draft = { key: d.key, starters: next.starters, captain: next.captain };
    S.msg = null; S.confirm = null; S.justSaved = false; render();
  }
  function toggleStart(teamId, crew) {
    tryDraft(teamId, (n) => {
      const i = n.starters.indexOf(crew);
      if (i >= 0) n.starters.splice(i, 1);
      else if (n.starters.length < 2) n.starters.push(crew);
      else return { kind: 'warn', text: 'You already have two starters. Bench one first, then pick this crew.' };
    });
  }
  function toggleCaptain(teamId, crew) {
    tryDraft(teamId, (n) => { n.captain = n.captain === crew ? null : crew; });
  }

  async function save(teamId, asCommish) {
    const d = S.draft;
    if (!d) return;
    const order = crewsOf(teamId), starters = d.starters.slice().sort((a, b) => order.indexOf(a) - order.indexOf(b));
    // A correction to a FINISHED week changes later weeks too (a lineup stands until replaced): show how far, ask first.
    if (asCommish && !S.confirm) {
      if (weekState(S.week) === 'past') {
        try {
          const r = await q(sb.rpc('lineup_effect_range', { p_team_id: teamId, p_week: S.week }));
          S.confirm = { kind: 'past', from: r[0].from_week, to: r[0].to_week };
        } catch (e) { S.msg = { kind: 'err', text: friendly(e) }; }
        return render();
      }
      // A change that touches a crew whose game already kicked off rewrites this week's score after the fact: ask first.
      const hit = lockConflict(S.eff[d.key], d, (c) => kickedOff(S.week, c));
      if (hit) { S.confirm = { kind: 'locked', crew: hit }; return render(); }
    }
    S.busy = true; S.msg = null; render();
    try {
      await q(sb.rpc('set_lineup', { p_team_id: teamId, p_week: S.week, p_starters: starters, p_captain: d.captain }));
    } catch (e) {
      S.busy = false; S.confirm = null; S.msg = { kind: 'err', text: friendly(e) }; return render();
    }
    // Saved. Everything below only refreshes what is on screen, so a failure here must never look like a failed save.
    S.eff = {}; S.confirm = null; S.draft = null;
    try { await refreshSchedule(); } catch (e) { /* keep the schedule we already have */ }
    S.busy = false;
    await refreshTab();
    if (S.draft) { S.msg = null; S.justSaved = true; }
    else S.msg = { kind: 'warn', text: 'Your lineup was saved, but the page could not reload it. Refresh the page to see it.' };
    render();
  }

  // ------------------------------------------------------------------ views
  function header() {
    const t = myTeam();
    return h('div', { class: 'top' },
      h('div', null, h('h1', null, 'Laundry League'), h('div', { class: 'small muted' }, S.league ? S.league.name : '')),
      h('div', { class: 'who' }, t ? h('div', null, t.manager_name) : null,
        h('button', { class: 'link', onclick: signOut }, 'Sign out')));
  }

  function viewSignIn() {
    const si = S.signin;
    const msg = si.msg ? h('p', { class: 'notice ' + si.msg.kind, role: 'status' }, si.msg.text) : null;
    if (si.step === 'email') {
      return h('div', { class: 'card stack' },
        h('h2', null, 'Sign in'),
        h('p', { class: 'muted' }, "Type your league email and we'll email you a code. No password."),
        msg,
        h('div', null, h('label', { class: 'label', for: 'email' }, 'Email'),
          h('input', { id: 'email', type: 'email', autocomplete: 'email', inputmode: 'email', value: si.email,
            oninput: (e) => { si.email = e.target.value; },
            onkeydown: (e) => { if (e.key === 'Enter') sendCode(); } })),
        h('button', { class: 'primary', disabled: si.busy, onclick: sendCode }, si.busy ? 'Sending…' : 'Send code'));
    }
    return h('div', { class: 'card stack' },
      h('h2', null, 'Enter your code'),
      msg,
      h('div', null, h('label', { class: 'label', for: 'code' }, 'Code from your email'),
        h('input', { id: 'code', class: 'code', type: 'text', inputmode: 'numeric', autocomplete: 'one-time-code', maxlength: 8, value: si.code,
          oninput: (e) => { si.code = e.target.value; },
          onkeydown: (e) => { if (e.key === 'Enter') checkCode(); } })),
      h('button', { class: 'primary', disabled: si.busy, onclick: checkCode }, si.busy ? 'Checking…' : 'Sign in'),
      h('button', { class: 'link', onclick: () => { si.step = 'email'; si.msg = null; render(); } }, 'Use a different email'));
  }

  function weekNav() {
    const go = (d) => { S.week = clampWeek(S.week + d); S.draft = null; S.msg = null; S.confirm = null; S.justSaved = false; render(); refreshTab(); };
    const st = weekState(S.week);
    const note = { past: 'Finished', open: '', noschedule: 'Schedule not loaded yet', nokickoffs: 'Kickoff times missing' }[st];
    return h('div', { class: 'weeknav' },
      h('button', { 'aria-label': 'Previous week', disabled: S.week <= S.league.start_week, onclick: () => go(-1) }, '‹'),
      h('div', null, h('h2', null, 'Week ' + S.week), note ? h('div', { class: 'small muted' }, note) : null),
      h('button', { 'aria-label': 'Next week', disabled: S.week >= S.league.playoff_week, onclick: () => go(1) }, '›'));
  }

  /** The first week scored from the app's lineups (published in data.json), or null while league.json decides every week. */
  function cutoverWeek() {
    return S.pub && Number.isInteger(S.pub.lineups_from_db_week) ? S.pub.lineups_from_db_week : null;
  }
  function offStarterWarnings(teamId, d) {
    const working = crewsOf(teamId).filter((c) => d.starters.indexOf(c) < 0 && !isOff(S.week, c));
    if (!working.length) return [];                 // nobody better to start: the open-spot rule credits the empty spot instead
    return d.starters.filter((c) => isOff(S.week, c)).map((c) =>
      c + ' has no game this week, and ' + working.join(' or ') + ' ' + (working.length > 1 ? 'do' : 'does') + '. A starter with no game scores 0. You can still save.');
  }

  /** The lineup editor, for one team and the selected week. Used by "My week" and by the commissioner. */
  function editor(teamId, asCommish) {
    const team = teamById(teamId), key = teamId + '|' + S.week, cur = S.eff[key];
    if (!cur || !S.draft || S.draft.key !== key) {
      // Still loading, or the load failed: show any message too, otherwise a failure looks like an endless "Loading…".
      return h('div', null, S.msg ? h('p', { class: 'notice ' + S.msg.kind, role: 'status' }, S.msg.text) : null, h('p', { class: 'muted' }, 'Loading lineup…'));
    }
    const d = S.draft, st = weekState(S.week), cap = captainsOn(S.week);
    const closed = !asCommish && st !== 'open';
    const why = { past: 'This week is finished, so lineups are closed. Ask the commissioner if something needs fixing.',
      noschedule: "This week's schedule hasn't been loaded yet, so it can't be changed right now.",
      nokickoffs: "This week has started but its kickoff times are missing, so changes are paused. Tell the commissioner." }[st];
    const dirty = !sameLineup(d, cur);
    const crews = crewsOf(teamId).map((crew) => {
      const s = crewStatus(S.week, crew), starter = d.starters.indexOf(crew) >= 0, locked = !asCommish && s.kind === 'locked';
      return h('div', { class: 'crew' + (starter ? ' start' : '') },
        h('div', null, h('div', { class: 'name' }, crew), h('div', { class: 'game' }, s.text)),
        h('span', { class: 'badge ' + (s.kind === 'locked' ? 'locked' : s.kind === 'off' ? '' : 'open') }, s.badge),
        h('div', { class: 'btns' },
          h('button', { class: starter ? 'on' : '', 'aria-pressed': String(starter), disabled: closed || locked || S.busy, onclick: () => toggleStart(teamId, crew) }, starter ? 'Starting' : 'Start'),
          cap ? h('button', { class: d.captain === crew ? 'on' : '', 'aria-pressed': String(d.captain === crew), disabled: closed || !starter || S.busy || (!asCommish && s.kind === 'locked'), onclick: () => toggleCaptain(teamId, crew) }, d.captain === crew ? 'Captain' : 'Make captain') : null));
    });
    const needs = d.starters.length !== 2 ? 'Pick exactly two starters.' : '';
    const past = asCommish && st === 'past';
    return h('div', null,
      closed ? h('p', { class: 'notice' }, why) : null,
      asCommish && (st === 'past' || crewsOf(teamId).some((c) => kickedOff(S.week, c))) ? h('p', { class: 'small muted' }, "You're the commissioner: locks and finished weeks don't stop you. Changes to them ask you to confirm and are logged.") : null,
      // A starter with no game scores 0 when a crew that DOES play is sitting on the bench (the scorer treats that as a lineup mistake).
      offStarterWarnings(teamId, d).map((w) => h('p', { class: 'notice' }, w)),
      cutoverWeek() !== null && S.week < cutoverWeek() ? h('p', { class: 'notice' }, 'Scoring uses league.json for weeks before Week ' + cutoverWeek() + ", so a change here won't affect scores. Make this change in league.json instead.") : null,
      cap && d.captain && isOff(S.week, d.captain) ? h('p', { class: 'notice' }, d.captain + ' has no game this week, so the captain bonus will earn little or nothing. You can still save.') : null,
      S.msg ? h('p', { class: 'notice ' + S.msg.kind, role: 'status' }, S.msg.text) : null,
      h('div', { class: 'crews' }, crews),
      S.confirm && S.confirm.kind === 'locked' ? h('div', { class: 'notice' },
        h('strong', null, S.confirm.crew + "'s game has already kicked off. "),
        "Saving changes Week " + S.week + "'s score after the fact for " + team.manager_name + '. The change is logged.') : null,
      S.confirm && S.confirm.kind === 'past' ? h('div', { class: 'notice' },
        h('strong', null, 'Week ' + S.week + ' is finished. '),
        'Saving this changes ' + (S.confirm.from === S.confirm.to ? 'Week ' + S.confirm.from : 'Weeks ' + S.confirm.from + ' to ' + S.confirm.to) +
        " for " + team.manager_name + '. A lineup stands until it is replaced, so the standings can change. The correction is logged.') : null,
      h('div', { class: 'row between' },
        h('span', { class: 'small ' + (S.justSaved && !dirty ? 'ok' : 'muted') }, needs || (dirty ? 'Not saved yet.' : S.justSaved ? 'Saved.' : (cur.from_week && cur.from_week !== S.week ? 'Carried over from Week ' + cur.from_week + '.' : (cur.from_week ? 'Saved.' : 'Default lineup: your first two crews.')))),
        h('button', { class: 'primary', disabled: closed || S.busy || !dirty || !draftValid(d), onclick: () => save(teamId, asCommish) },
          S.busy ? 'Saving…' : S.confirm ? (S.confirm.kind === 'past' ? 'Confirm correction' : 'Confirm change') : past ? 'Save correction' : 'Save lineup')));
  }

  function viewWeek() {
    const t = myTeam();
    if (!t) return h('p', { class: 'notice' }, "You're signed in, but no team is linked to your account yet. Ask the commissioner.");
    return h('div', null, weekNav(),
      h('p', { class: 'muted small' }, t.manager_name + ' · ' + t.name),
      editor(t.id, isCommish()));
  }

  function lineupText(teamId) {
    const e = S.eff[teamId + '|' + S.week];
    if (!e) return 'Loading…';
    return e.starters.join(' + ') + (e.captain ? '  ·  Captain: ' + e.captain : '');
  }
  function viewLeague() {
    const p = S.pub, wk = p && (p.weeks || []).find((w) => w.week === S.week);
    const row = (name) => {
      const t = S.teams.find((x) => x.name === name);
      return h('div', { class: 'team' }, h('div', null, h('strong', null, t ? t.manager_name : name), ' ', h('span', { class: 'muted small' }, name)),
        h('div', { class: 'lineup' }, t ? lineupText(t.id) : ''));
    };
    const cards = wk && wk.games && wk.games.length
      ? wk.games.map((g) => h('div', { class: 'card match' }, g.name ? h('h3', null, g.name) : null, row(g.a), h('div', { class: 'vs' }, 'vs'), row(g.b)))
      : [h('div', { class: 'card match' }, S.teams.map((t) => row(t.name)))];
    const st = (p && p.standings) || [];
    return h('div', null, weekNav(),
      h('p', { class: 'small muted' }, 'Lineups as saved in the app. Matchups come from the public page.'),
      cards,
      st.length ? h('div', { class: 'card' }, h('h3', null, 'Standings'),
        h('table', null,
          h('thead', null, h('tr', null, h('th', null, 'Team'), h('th', { class: 'num' }, 'W-L-T'), h('th', { class: 'num' }, 'PF'))),
          h('tbody', null, st.map((r) => h('tr', null, h('td', null, r.manager + ' '), h('td', { class: 'num' }, r.w + '-' + r.l + '-' + r.t), h('td', { class: 'num' }, r.pf)))))) : null);
  }

  const ACTIONS = { lineup_set: 'set', lineup_set_by_commissioner: 'set (as commissioner)', lineup_set_past_week: 'corrected a finished week for', member_added: 'added a member' };
  function actorName(uid) {
    const m = S.members.find((x) => x.user_id === uid);
    const t = m && teamById(m.team_id);
    return t ? t.manager_name : m && m.role === 'commissioner' ? 'Commissioner' : 'Someone';
  }
  function viewCommish() {
    const tid = S.cTeam, d = (id) => teamById(id);
    return h('div', null, weekNav(),
      h('div', { class: 'card stack' },
        h('div', null, h('label', { class: 'label', for: 'cteam' }, 'Set the lineup for'),
          h('select', { id: 'cteam', onchange: (e) => { S.cTeam = e.target.value; S.draft = null; S.msg = null; S.confirm = null; S.justSaved = false; render(); refreshTab(); } },
            S.teams.map((t) => h('option', { value: t.id, selected: t.id === tid }, t.manager_name + ' · ' + t.name)))),
        tid !== S.me.team_id ? h('p', { class: 'notice' }, "You're setting " + d(tid).manager_name + "'s lineup. It will be flagged as yours in the change log.") : null),
      editor(tid, true),
      h('div', { class: 'card' }, h('h3', null, 'Recent changes'),
        S.audit.length ? h('ul', { class: 'log' }, S.audit.map((a) => {
          const det = a.detail || {}, tm = teamById(det.team_id);
          const what = a.action === 'member_added' ? 'added a member' :
            (ACTIONS[a.action] || a.action) + ' ' + (tm ? tm.manager_name + "'s lineup" : 'a lineup') + (det.week ? ', Week ' + det.week : '') +
            (det.starters ? ': ' + det.starters.join(' + ') + (det.captain ? ' (C: ' + det.captain + ')' : '') : '');
          return h('li', null, h('time', null, fmtStamp(a.created_at)), actorName(a.actor) + ' ' + what);
        })) : h('p', { class: 'muted small' }, 'Nothing yet.')));
  }

  function viewMain() {
    const tabs = [['week', 'My week'], ['league', 'League']].concat(isCommish() ? [['commish', 'Commissioner']] : []);
    return h('div', null,
      h('div', { class: 'tabs', role: 'tablist' }, tabs.map(([id, label]) =>
        h('button', { role: 'tab', 'aria-selected': String(S.tab === id), class: S.tab === id ? 'on' : '', onclick: () => { S.tab = id; S.msg = null; S.confirm = null; S.justSaved = false; S.draft = null; render(); refreshTab(); } }, label))),
      S.tab === 'week' ? viewWeek() : S.tab === 'league' ? viewLeague() : viewCommish());
  }

  function render() {
    S.sig = lockSignature();
    const r = root();
    if (!r) return;
    let body;
    if (S.view === 'boot' || S.view === 'loading') body = h('p', { class: 'muted' }, 'Loading…');
    else if (S.view === 'signin') body = viewSignIn();
    else if (S.view === 'outsider') body = h('div', { class: 'card stack' }, h('h2', null, 'Not on the league yet'),
      h('p', null, "You're signed in, but this account isn't linked to a team. Ask the commissioner to add you."),
      h('button', { onclick: signOut }, 'Sign out'));
    else if (S.view === 'error') body = h('div', { class: 'card stack' }, h('h2', null, "Couldn't load the league"), h('p', { class: 'notice err' }, S.fatal),
      h('button', { class: 'primary', onclick: () => (S.session ? loadAll() : resetToSignIn()) }, 'Try again'), h('button', { class: 'link', onclick: signOut }, 'Sign out'));
    else body = viewMain();
    const keep = document.activeElement && document.activeElement.id;
    const top = S.view === 'signin' || S.view === 'boot' ? h('div', { class: 'top' }, h('h1', null, 'Laundry League')) : header();
    r.replaceChildren(top, body);
    if (keep) { const el = document.getElementById(keep); if (el && el.focus) el.focus(); }
  }

  // ------------------------------------------------------------------ keep lock status fresh without disturbing typing
  function lockSignature() {
    if (S.view !== 'main' || !S.league) return '';
    const crews = [];
    S.teams.forEach((t) => crewsOf(t.id).forEach((c) => crews.push(c)));
    return crews.map((c) => (kickedOff(S.week, c) ? 'L' : 'o')).join('') + weekState(S.week);
  }
  function tick() {
    S.now = Date.now();
    if (S.view === 'main' && lockSignature() !== S.sig) render();
  }
  LL._tick = tick;

  // ------------------------------------------------------------------ start
  async function boot() {
    render();
    sb.auth.onAuthStateChange((evt, session) => {
      if (evt === 'SIGNED_OUT') { if (S.view !== 'signin') resetToSignIn(); }
      else if (session) S.session = session;
    });
    const { data } = await sb.auth.getSession();
    if (data && data.session) { S.session = data.session; loadAll(); }
    else { S.view = 'signin'; render(); }
    setInterval(tick, 30000);
    document.addEventListener('visibilitychange', async () => {
      if (document.visibilityState === 'visible' && S.view === 'main') { try { await refreshSchedule(); render(); } catch (e) { /* keep what we have */ } }
    });
  }
  LL.boot = boot;
  if (!window.LL_NO_AUTOBOOT) boot();
})();
