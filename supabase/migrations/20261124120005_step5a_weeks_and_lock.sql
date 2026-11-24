-- Laundry League database, part 5 (step 5a): weeks, a safer lock, and "who actually starts".
--
-- What changes, in plain language:
--   1. A `weeks` table: when each NFL week starts and ends. The database can now tell "this week is
--      over" without trusting a phone's clock.
--   2. set_lineup() is rewritten with two new rules for MANAGERS:
--        * Finished weeks are closed. (The commissioner may still correct them; each such edit is
--          logged under its own action name, 'lineup_set_past_week', so it is easy to find.)
--        * Fail closed: if a week's schedule is missing, or the week has started but no per-crew
--          kickoff times were synced, managers are refused instead of the lock silently switching off.
--      Everything else in set_lineup() is unchanged.
--   3. effective_lineup(): one server answer to "who starts and who captains this week?"
--   4. lineup_effect_range(): "if I save a lineup for week N, which weeks change?" (the app shows this
--      to the commissioner before a correction, because a lineup stands until replaced).
--   5. sync_status: a heartbeat the bot writes, so we can see if it stopped feeding the lock.

-- ---------------------------------------------------------------- weeks
-- One row per NFL week. Filled in by the score bot (secret key), like game_slots.
create table public.weeks (
  season    int  not null,
  week      int  not null,
  starts_at timestamptz not null,   -- first kickoff of the week
  ends_at   timestamptz not null,   -- after this, the week is "finished" (bot: last kickoff + about a day)
  primary key (season, week),
  check (starts_at < ends_at)
);

-- Heartbeat: one row per kind of sync ('kickoffs'), stamped by the bot after each successful run.
create table public.sync_status (
  key        text primary key,
  synced_at  timestamptz not null,
  detail     jsonb not null default '{}'
);

alter table public.weeks       enable row level security;
alter table public.sync_status enable row level security;

revoke all on public.weeks, public.sync_status from anon, authenticated;
grant select on public.weeks, public.sync_status to authenticated;     -- public schedule facts; read-only
grant all    on public.weeks, public.sync_status to service_role;      -- the bot

create policy "signed-in read weeks" on public.weeks
  for select to authenticated using (true);
create policy "signed-in read sync status" on public.sync_status
  for select to authenticated using (true);
-- As before: no insert/update/delete rule exists for clients, so only the bot can write.

-- ---------------------------------------------------------------- set_lineup (rewritten)
create or replace function public.set_lineup(
  p_team_id  uuid,
  p_week     int,
  p_starters text[],
  p_captain  text default null
) returns bigint
language plpgsql security definer set search_path = ''
as $$
declare
  v_uid          uuid := auth.uid();
  v_team         public.teams%rowtype;
  v_league       public.leagues%rowtype;
  v_member       public.league_members%rowtype;
  v_week         public.weeks%rowtype;
  v_by_comm      boolean;
  v_past         boolean := false;
  v_crew         text;
  v_cur_starters text[];
  v_cur_captain  text;
  v_new_id       bigint;
begin
  -- 1. Who is asking? (A signed-in person. Not signed in = refused.)
  if v_uid is null then
    raise exception 'Not signed in';
  end if;

  -- 2. May they change THIS team? Their own team, or any team if they are the commissioner.
  --    "No such team" and "not yours" give the same answer so nobody can probe for team ids.
  select * into v_team from public.teams where id = p_team_id;
  if found then
    select * into v_member from public.league_members
      where league_id = v_team.league_id and user_id = v_uid;
  end if;
  if not found or v_member.user_id is null
     or not (v_member.role = 'commissioner' or v_member.team_id = p_team_id) then
    raise exception 'Not allowed';
  end if;
  v_by_comm := v_member.role = 'commissioner' and v_member.team_id is distinct from p_team_id;

  select * into v_league from public.leagues where id = v_team.league_id;

  -- 3. Is the lineup itself legal?
  if p_week is null or p_week < v_league.start_week or p_week > v_league.playoff_week then
    raise exception 'Week % is outside this season (weeks % to %)',
      p_week, v_league.start_week, v_league.playoff_week;
  end if;

  if p_starters is null or cardinality(p_starters) <> 2
     or p_starters[1] is null or p_starters[2] is null or p_starters[1] = p_starters[2] then
    raise exception 'Pick exactly 2 different crews';
  end if;

  foreach v_crew in array p_starters loop
    if not exists (select 1 from public.roster r where r.team_id = p_team_id and r.crew = v_crew) then
      raise exception '% is not on this team''s roster', v_crew;
    end if;
  end loop;

  if p_captain is not null then
    if p_captain <> p_starters[1] and p_captain <> p_starters[2] then
      raise exception 'The captain must be one of the two starters';
    end if;
    if p_week < v_league.captain_start_week then
      raise exception 'Captains start in Week %', v_league.captain_start_week;
    end if;
  end if;

  -- 4a. Is the WEEK open? (Server clock, not the phone's.)
  select * into v_week from public.weeks w where w.season = v_league.season and w.week = p_week;
  v_past := found and v_week.ends_at <= now();

  if v_member.role <> 'commissioner' then
    -- Finished weeks are closed to managers. (A lineup stands until replaced, so editing an old
    -- week could rewrite the results of every week after it.)
    if v_past then
      raise exception 'Week % is finished and closed to managers. Ask the commissioner to correct it.', p_week;
    end if;
    -- Fail closed: no schedule on file means we cannot tell what is locked, so do not guess.
    if v_week.week is null then
      raise exception 'Week %''s schedule has not been loaded yet, so it cannot be changed right now', p_week;
    end if;
    if v_week.starts_at <= now() and not exists (
         select 1 from public.game_slots g where g.season = v_league.season and g.week = p_week) then
      raise exception 'Week % has started but its kickoff times are missing, so changes are paused', p_week;
    end if;
  end if;

  -- 4b. The per-crew lock. First find the lineup that stands for this week right now
  --     (newest row at or before the week; before any row, the first 2 roster crews).
  select l.starters, l.captain into v_cur_starters, v_cur_captain
    from public.lineups l
    where l.team_id = p_team_id and l.week <= p_week
    order by l.week desc, l.id desc
    limit 1;
  if v_cur_starters is null then
    select array_agg(r.crew order by r.slot) into v_cur_starters
      from (select crew, slot from public.roster where team_id = p_team_id order by slot limit 2) r;
    v_cur_captain := null;
  end if;

  -- You may not add, remove or re-captain a crew whose game has already kicked off.
  -- (A crew with no kickoff on file is not locked, but see the fail-closed rule above.)
  -- The commissioner may override; the audit log shows that they did.
  if v_member.role <> 'commissioner' then
    select c.crew into v_crew
    from (
      (select unnest(p_starters) as crew except select unnest(v_cur_starters))
      union
      (select unnest(v_cur_starters) except select unnest(p_starters))
      union
      (select p_captain where p_captain is not null and p_captain is distinct from v_cur_captain)
      union
      (select v_cur_captain where v_cur_captain is not null and p_captain is distinct from v_cur_captain)
    ) c
    join public.game_slots g
      on g.season = v_league.season and g.week = p_week and g.crew = c.crew
    where g.kickoff_at <= now()
    limit 1;

    if v_crew is not null then
      raise exception '%''s game has already kicked off, so that spot is locked', v_crew;
    end if;
  end if;

  -- 5. Save it, and leave a note in the audit log.
  insert into public.lineups (league_id, team_id, week, starters, captain, created_by, by_commissioner)
  values (v_team.league_id, p_team_id, p_week, p_starters, p_captain, v_uid, v_by_comm)
  returning id into v_new_id;

  insert into public.audit_log (league_id, actor, action, detail)
  values (
    v_team.league_id, v_uid,
    case when v_past               then 'lineup_set_past_week'
         when v_by_comm            then 'lineup_set_by_commissioner'
         else 'lineup_set' end,
    jsonb_build_object('lineup_id', v_new_id, 'team_id', p_team_id, 'week', p_week,
                       'starters', p_starters, 'captain', p_captain, 'past_week', v_past)
  );

  return v_new_id;
end;
$$;

revoke execute on function public.set_lineup(uuid, int, text[], text) from public, anon;
grant  execute on function public.set_lineup(uuid, int, text[], text) to authenticated;

-- ---------------------------------------------------------------- effective_lineup
-- "Who actually starts, and who captains, for this team in this week?" Same carry-forward rule as
-- set_lineup and the score bot: the newest saved row at or before the week; before any row, the
-- first two roster crews with no captain. from_week says which week's row is standing (null = default).
create function public.effective_lineup(p_team_id uuid, p_week int)
returns table (starters text[], captain text, from_week int)
language plpgsql stable security definer set search_path = ''
as $$
declare
  v_league uuid;
begin
  select t.league_id into v_league from public.teams t where t.id = p_team_id;
  -- Same answer for "no such team" and "not in your league".
  if v_league is null or not private.is_league_member(v_league) then
    raise exception 'Not allowed';
  end if;

  return query
    select l.starters, l.captain, l.week
    from public.lineups l
    where l.team_id = p_team_id and l.week <= p_week
    order by l.week desc, l.id desc
    limit 1;
  if not found then
    return query
      select array_agg(r.crew order by r.slot), null::text, null::int
      from (select crew, slot from public.roster where team_id = p_team_id order by slot limit 2) r;
  end if;
end;
$$;

revoke execute on function public.effective_lineup(uuid, int) from public, anon;
grant  execute on function public.effective_lineup(uuid, int) to authenticated;

-- ---------------------------------------------------------------- lineup_effect_range
-- "If this team saves a lineup for week N, which weeks does it change?" From N up to the week before
-- the team's next own saved lineup (or the last week of the season). The app shows this before a correction.
create function public.lineup_effect_range(p_team_id uuid, p_week int)
returns table (from_week int, to_week int)
language plpgsql stable security definer set search_path = ''
as $$
declare
  v_league uuid;
  v_last   int;
  v_next   int;
begin
  select t.league_id into v_league from public.teams t where t.id = p_team_id;
  if v_league is null or not private.is_league_member(v_league) then
    raise exception 'Not allowed';
  end if;
  select playoff_week into v_last from public.leagues where id = v_league;
  select min(l.week) into v_next from public.lineups l where l.team_id = p_team_id and l.week > p_week;
  return query select p_week, coalesce(v_next - 1, v_last);
end;
$$;

revoke execute on function public.lineup_effect_range(uuid, int) from public, anon;
grant  execute on function public.lineup_effect_range(uuid, int) to authenticated;
