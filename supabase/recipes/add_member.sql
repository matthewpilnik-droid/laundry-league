-- RECIPE: link a signed-in person to a team in a league.   Run by hand in the SQL Editor. NOT a migration.
--
-- Why a recipe and not an app feature: adding a player must be a deliberate act by the commissioner,
-- and the email address must never be saved in git. So: type the email into the SQL Editor only,
-- run it, and DO NOT save or commit the edited copy. (Sign-ups are OFF, so the person must exist first:
-- Supabase dashboard -> Authentication -> Users -> Add user -> "Send invitation" or create with Auto Confirm.)
--
-- Fill in the three values on the 'values' line below, then Run.
--   email   : the person's sign-in email (as in Authentication -> Users)
--   manager : the first name of their team's manager as it appears in teams.manager_name, e.g. 'Danny'
--   role    : 'manager' (normal) or 'commissioner'
--   league  : the league's name, e.g. 'The Laundry League'
do $$
declare
  v_email   text := 'PUT-EMAIL-HERE';
  v_manager text := 'PUT-FIRST-NAME-HERE';
  v_role    text := 'manager';
  v_league  text := 'PUT-LEAGUE-NAME-HERE';
  v_uid     uuid;
  v_lid     uuid;
  v_tid     uuid;
begin
  select id into v_uid from auth.users where lower(email) = lower(v_email);
  if v_uid is null then raise exception 'No signed-up user with that email. Create them in Authentication -> Users first.'; end if;
  select id into v_lid from public.leagues where name = v_league;
  if v_lid is null then raise exception 'No league named %', v_league; end if;
  select id into v_tid from public.teams where league_id = v_lid and manager_name = v_manager;
  if v_tid is null then raise exception 'No team managed by % in that league', v_manager; end if;
  if v_role not in ('manager', 'commissioner') then raise exception 'role must be manager or commissioner'; end if;

  -- A commissioner here also owns a team (their own), as in the rehearsal league.
  insert into public.league_members (league_id, user_id, role, team_id) values (v_lid, v_uid, v_role, v_tid);

  insert into public.audit_log (league_id, actor, action, detail)
  values (v_lid, null, 'member_added', jsonb_build_object('user_id', v_uid, 'role', v_role, 'team_id', v_tid));
end;
$$;
