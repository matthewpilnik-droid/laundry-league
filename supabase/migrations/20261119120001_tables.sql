-- Laundry League database, part 1 of 3: the tables ("sheets") and their columns ("headings").
-- No people, emails or secrets live in this file. It is only the shape of the workbook.
-- Run order: 01 tables, 02 security rules, 03 set_lineup function.

-- One row per league (we have one: The Laundry League, 2026).
create table public.leagues (
  id                 uuid primary key default gen_random_uuid(),
  name               text not null,
  season             int  not null,
  start_week         int  not null,   -- first scored week (8)
  captain_start_week int  not null,   -- first week captains count (11)
  playoff_week       int  not null,   -- last week (18)
  created_at         timestamptz not null default now(),
  check (start_week <= playoff_week)
);

-- One row per fantasy team.
create table public.teams (
  id           uuid primary key default gen_random_uuid(),
  league_id    uuid not null references public.leagues(id) on delete cascade,
  name         text not null,
  manager_name text not null,        -- first name shown in the app, e.g. 'Bryan'
  unique (league_id, name),
  unique (id, league_id)             -- lets other tables prove a team belongs to a league
);

-- The 3 drafted crews per team. A read-only copy of league.json so the database can check
-- "is this crew really on your team?". slot = the order listed (the default starters are slots 1 and 2).
create table public.roster (
  league_id uuid     not null,
  team_id   uuid     not null,
  slot      smallint not null check (slot >= 1),
  crew      text     not null,       -- referee name as in league.json, e.g. 'Alex Moore'
  primary key (team_id, slot),
  unique (team_id, crew),
  unique (league_id, crew),          -- a crew is drafted by exactly one team
  foreign key (team_id, league_id) references public.teams (id, league_id) on delete cascade
);

-- Who belongs to which league, and in what role. Users come from Supabase's own sign-in
-- system (auth.users). Emails are NOT copied here: they stay inside the sign-in system.
create table public.league_members (
  league_id uuid not null references public.leagues(id) on delete cascade,
  user_id   uuid not null references auth.users(id) on delete cascade,
  role      text not null check (role in ('commissioner', 'manager')),
  team_id   uuid,
  primary key (league_id, user_id),
  unique (team_id),                  -- one person per team
  check (role = 'commissioner' or team_id is not null),
  foreign key (team_id, league_id) references public.teams (id, league_id)
);

-- Kickoff time of each crew's game each week. Filled in by the score bot (it already
-- downloads the schedule). This is what the per-crew lineup lock reads.
create table public.game_slots (
  season     int  not null,
  week       int  not null,
  crew       text not null,
  kickoff_at timestamptz not null,
  primary key (season, week, crew)
);

-- Lineup history. APPEND-ONLY: every change is a new row; old rows are never edited or deleted.
-- "A lineup stands until replaced" works the same as today: the newest row at or before a week wins.
create table public.lineups (
  id              bigint generated always as identity primary key,
  league_id       uuid not null,
  team_id         uuid not null,
  week            int  not null,
  starters        text[] not null,
  captain         text,                              -- null = no captain
  created_at      timestamptz not null default now(), -- stamped by the server, never by a phone
  created_by      uuid not null,                     -- who pressed save (no link, so history survives)
  by_commissioner boolean not null default false,    -- true when the commissioner set another team's lineup
  foreign key (team_id, league_id) references public.teams (id, league_id),
  check (cardinality(starters) = 2),
  check (starters[1] is not null and starters[2] is not null and starters[1] <> starters[2]),
  check (captain is null or captain = any (starters))
);
create index lineups_lookup on public.lineups (team_id, week, id desc);

-- A plain record of notable actions, visible to the league ("Matthew set Danny's lineup").
create table public.audit_log (
  id         bigint generated always as identity primary key,
  league_id  uuid not null references public.leagues(id) on delete cascade,
  actor      uuid,
  action     text not null,
  detail     jsonb not null default '{}',
  created_at timestamptz not null default now()
);
