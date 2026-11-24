-- Laundry League database, part 3 of 3: the front-desk clerk, set_lineup().
--
-- The ONLY way for the app to save a lineup. It runs with the database's own access
-- ("security definer") but first checks everything about the person asking.
-- Every check lives here, on the server, so a modified web page can't skip them.
--
--   select public.set_lineup(<team id>, <week>, array['Alex Moore','Ron Torbert'], 'Alex Moore');
--
-- Returns the id of the new lineup row.

create function public.set_lineup(
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
  v_by_comm      boolean;
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

  -- 4. The lock. First find the lineup that stands for this week right now
  --    (newest row at or before the week; before any row, the first 2 roster crews).
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

  -- Per-crew lock, using the SERVER's clock: you may not add, remove or re-captain a crew
  -- whose game has already kicked off. (A crew with no kickoff on file is not locked.)
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
    case when v_by_comm then 'lineup_set_by_commissioner' else 'lineup_set' end,
    jsonb_build_object('lineup_id', v_new_id, 'team_id', p_team_id, 'week', p_week,
                       'starters', p_starters, 'captain', p_captain)
  );

  return v_new_id;
end;
$$;

revoke execute on function public.set_lineup(uuid, int, text[], text) from public, anon;
grant  execute on function public.set_lineup(uuid, int, text[], text) to authenticated;
