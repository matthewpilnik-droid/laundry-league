-- Laundry League database, part 4: move the rule-book helper into a private schema.
--
-- Supabase turns every function in the "public" schema into a web address that signed-in
-- people can call. The helper that answers "am I in this league?" doesn't need to be one.
-- A "schema" is a folder inside the database; Supabase only exposes "public" to the web,
-- so a function in "private" can still be used by the row rules but can't be called directly.
--
-- Changes:
--   * is_league_member moves from public to private (row rules are repointed first, so
--     there is never a moment when a table is unprotected).
--   * is_league_commissioner is dropped: nothing used it (set_lineup does its own check).

create schema private;
revoke all on schema private from public, anon;
grant usage on schema private to authenticated;

create function private.is_league_member(p_league uuid) returns boolean
language sql stable security definer set search_path = ''
as $$
  select exists (
    select 1 from public.league_members m
    where m.league_id = p_league and m.user_id = auth.uid()
  );
$$;

revoke execute on function private.is_league_member(uuid) from public, anon;
grant  execute on function private.is_league_member(uuid) to authenticated;

-- Repoint every row rule at the private helper.
alter policy "members read their league"   on public.leagues        using (private.is_league_member(id));
alter policy "members read teams"          on public.teams          using (private.is_league_member(league_id));
alter policy "members read rosters"        on public.roster         using (private.is_league_member(league_id));
alter policy "members read members"        on public.league_members using (private.is_league_member(league_id));
alter policy "members read lineups"        on public.lineups        using (private.is_league_member(league_id));
alter policy "members read the audit log"  on public.audit_log      using (private.is_league_member(league_id));

-- Now nothing depends on the public copies.
drop function public.is_league_member(uuid);
drop function public.is_league_commissioner(uuid);
