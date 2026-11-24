-- REHEARSAL seed: fills the rehearsal project with a fake "Rehearsal League" so the security
-- test (supabase/tests/burglar.py) has something to attack. Run it ONCE in the SQL Editor,
-- AFTER creating the four fake users in Authentication -> Users (see supabase/tests/README.md).
--
-- Contains only public information (team and referee names are already in league.json) and
-- reserved example.com addresses. Never run this on the real project.
--
-- Cast of fake users (matched by email, so no ids to copy):
--   ll-commish@example.com  -> commissioner, owns Matthew's team
--   ll-bryan@example.com    -> manager of Bryan's team
--   ll-mike@example.com     -> manager of Mike's team
--   ll-outsider@example.com -> signed in, belongs to nothing
--
-- Lock tests use these kickoff times for week 11:
--   Scott Novak, Craig Wrolstad: already kicked off (2026-11-01)
--   John Hussey, Brad Allen, Clete Blakeman: kick off in 2099
--   everyone else: no kickoff on file, so never locked

do $$
declare
  v_league uuid;
begin
  if exists (select 1 from public.leagues where name = 'Rehearsal League') then
    raise exception 'The seed already ran. To start over, run: truncate public.leagues cascade; (rehearsal project only)';
  end if;

  insert into public.leagues (name, season, start_week, captain_start_week, playoff_week)
  values ('Rehearsal League', 2026, 8, 11, 18)
  returning id into v_league;

  insert into public.teams (league_id, name, manager_name) values
    (v_league, 'Helen Keller''s School for Refs that Don''t See That Good', 'Bryan'),
    (v_league, 'I''m Blind, I''m Deaf',                                    'Matthew'),
    (v_league, 'This is not Nam, there are rules',                         'Mike'),
    (v_league, 'Zebras with Gambling Debts',                               'Stephan'),
    (v_league, 'DraftKings Employee of the Month',                         'Sean'),
    (v_league, 'Zebra Crime Syndicate',                                    'Danny');

  insert into public.roster (league_id, team_id, slot, crew)
  select v_league, t.id, r.slot, r.crew
  from (values
    ('Bryan',   1, 'Scott Novak'),     ('Bryan',   2, 'John Hussey'),     ('Bryan',   3, '2012 Replacement Refs'),
    ('Matthew', 1, 'Alex Moore'),      ('Matthew', 2, 'Ron Torbert'),     ('Matthew', 3, 'Alan Eck'),
    ('Mike',    1, 'Craig Wrolstad'),  ('Mike',    2, 'Brad Allen'),      ('Mike',    3, 'Clete Blakeman'),
    ('Stephan', 1, 'Adrian Hill'),     ('Stephan', 2, 'Bill Vinovich'),   ('Stephan', 3, 'Alex Kemp'),
    ('Sean',    1, 'Land Clark'),      ('Sean',    2, 'Shawn Smith'),     ('Sean',    3, 'Brad Rogers'),
    ('Danny',   1, 'Carl Cheffers'),   ('Danny',   2, 'Shawn Hochuli'),   ('Danny',   3, 'Clay Martin')
  ) as r(manager, slot, crew)
  join public.teams t on t.league_id = v_league and t.manager_name = r.manager;

  insert into public.league_members (league_id, user_id, role, team_id)
  select v_league, u.id, m.role, t.id
  from (values
    ('ll-commish@example.com', 'commissioner', 'Matthew'),
    ('ll-bryan@example.com',   'manager',      'Bryan'),
    ('ll-mike@example.com',    'manager',      'Mike')
  ) as m(email, role, manager)
  join auth.users u on u.email = m.email
  join public.teams t on t.league_id = v_league and t.manager_name = m.manager;

  if (select count(*) from public.league_members where league_id = v_league) <> 3 then
    raise exception 'Expected 3 fake users. Create ll-commish@, ll-bryan@ and ll-mike@example.com in Authentication -> Users first.';
  end if;

  insert into public.game_slots (season, week, crew, kickoff_at) values
    (2026, 11, 'Scott Novak',    '2026-11-01 00:00+00'),
    (2026, 11, 'Craig Wrolstad', '2026-11-01 00:00+00'),
    (2026, 11, 'John Hussey',    '2099-01-01 00:00+00'),
    (2026, 11, 'Brad Allen',     '2099-01-01 00:00+00'),
    (2026, 11, 'Clete Blakeman', '2099-01-01 00:00+00');
end;
$$;
