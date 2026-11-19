-- Laundry League database, part 2 of 3: who may see and change what.
--
-- Three layers, all "deny unless allowed":
--   1. Privileges (GRANT/REVOKE): which doors exist at all for each kind of visitor.
--   2. Row-level security (RLS): on every table, a rule decides which ROWS you may see.
--      A table with RLS on and no rule shows nobody anything.
--   3. No client can write to any table directly. Lineups change only through set_lineup() (part 3).
--
-- Kinds of visitor: 'anon' = not signed in, 'authenticated' = signed in,
-- 'service_role' = the score bot's secret key (skips RLS; never in the browser).

-- Layer 1a: turn RLS on for every table.
alter table public.leagues        enable row level security;
alter table public.teams          enable row level security;
alter table public.roster         enable row level security;
alter table public.league_members enable row level security;
alter table public.game_slots     enable row level security;
alter table public.lineups        enable row level security;
alter table public.audit_log      enable row level security;

-- Layer 1b: Supabase hands new tables to visitors by default. Take everything away,
-- then give back only "read" to signed-in people. Not-signed-in visitors get nothing.
alter default privileges in schema public revoke all on tables    from anon, authenticated;
alter default privileges in schema public revoke all on functions from anon, authenticated;
alter default privileges in schema public revoke all on sequences from anon, authenticated;

revoke all on public.leagues, public.teams, public.roster, public.league_members,
              public.game_slots, public.lineups, public.audit_log
  from anon, authenticated;

grant select on public.leagues, public.teams, public.roster, public.league_members,
                public.game_slots, public.lineups, public.audit_log
  to authenticated;

-- The score bot (secret key) may do everything it needs. Spelled out so we don't depend on
-- a Supabase default. (The append-only seat belt below still applies to it.)
grant all on public.leagues, public.teams, public.roster, public.league_members,
             public.game_slots, public.lineups, public.audit_log
  to service_role;
grant usage, select on all sequences in schema public to service_role;

-- Helper questions the rules ask. "security definer" means the helper looks inside
-- league_members with the database's own access (otherwise the rule that protects
-- league_members would have to ask itself, forever). search_path = '' is a standard
-- safety setting that stops a look-alike table from being substituted.
create function public.is_league_member(p_league uuid) returns boolean
language sql stable security definer set search_path = ''
as $$
  select exists (
    select 1 from public.league_members m
    where m.league_id = p_league and m.user_id = auth.uid()
  );
$$;

create function public.is_league_commissioner(p_league uuid) returns boolean
language sql stable security definer set search_path = ''
as $$
  select exists (
    select 1 from public.league_members m
    where m.league_id = p_league and m.user_id = auth.uid() and m.role = 'commissioner'
  );
$$;

-- Functions are callable by everyone unless we say otherwise. Say otherwise.
revoke execute on function public.is_league_member(uuid)       from public, anon;
revoke execute on function public.is_league_commissioner(uuid) from public, anon;
grant  execute on function public.is_league_member(uuid)       to authenticated;
grant  execute on function public.is_league_commissioner(uuid) to authenticated;

-- Layer 2: row rules. Everyone in a league sees that league's rows (standings, rosters,
-- lineups, matchups). Nobody outside the league sees anything of it.
create policy "members read their league"   on public.leagues
  for select to authenticated using (public.is_league_member(id));
create policy "members read teams"          on public.teams
  for select to authenticated using (public.is_league_member(league_id));
create policy "members read rosters"        on public.roster
  for select to authenticated using (public.is_league_member(league_id));
create policy "members read members"        on public.league_members
  for select to authenticated using (public.is_league_member(league_id));
create policy "members read lineups"        on public.lineups
  for select to authenticated using (public.is_league_member(league_id));
create policy "members read the audit log"  on public.audit_log
  for select to authenticated using (public.is_league_member(league_id));
-- Kickoff times are public NFL schedule facts, so any signed-in person may read them.
create policy "signed-in read kickoff times" on public.game_slots
  for select to authenticated using (true);

-- Layer 3: there is deliberately NO insert / update / delete rule on any table, and no
-- such privilege was granted. The only ways in are set_lineup() and the bot's secret key.

-- Extra seat belt: even the secret key cannot quietly rewrite lineup history.
-- (To reset a rehearsal database, use: truncate public.lineups;)
create function public.lineups_are_append_only() returns trigger
language plpgsql set search_path = ''
as $$
begin
  raise exception 'Lineup history is append-only: add a new row instead of changing or deleting one.';
end;
$$;

create trigger lineups_no_update_or_delete
  before update or delete on public.lineups
  for each row execute function public.lineups_are_append_only();
