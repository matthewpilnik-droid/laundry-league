-- REHEARSAL seed, part 2 (step 5a): the `weeks` schedule the new lock rules need.
-- Run ONCE in the SQL Editor, after migration 05. Rehearsal project only. Contains no personal data.
--
--   Weeks 8-10: already finished   -> closed to managers, open to the commissioner (logged)
--   Week 11:    in progress        -> started 2026-11-01; per-crew kickoffs in game_slots decide the lock
--   Weeks 12-18: not started yet   -> open to everyone
-- (Week 11's end is set far in the future so the test never silently turns it into a finished week.)

insert into public.weeks (season, week, starts_at, ends_at) values
  (2026,  8, '2026-10-25 17:00+00', '2026-10-27 12:00+00'),
  (2026,  9, '2026-11-01 17:00+00', '2026-11-03 12:00+00'),
  (2026, 10, '2026-11-01 17:00+00', '2026-11-03 12:00+00'),
  (2026, 11, '2026-11-01 00:00+00', '2099-01-02 00:00+00'),
  (2026, 12, '2099-01-01 00:00+00', '2099-01-02 00:00+00'),
  (2026, 13, '2099-01-08 00:00+00', '2099-01-09 00:00+00'),
  (2026, 14, '2099-01-15 00:00+00', '2099-01-16 00:00+00'),
  (2026, 15, '2099-01-22 00:00+00', '2099-01-23 00:00+00'),
  (2026, 16, '2099-01-29 00:00+00', '2099-01-30 00:00+00'),
  (2026, 17, '2099-02-05 00:00+00', '2099-02-06 00:00+00'),
  (2026, 18, '2099-02-12 00:00+00', '2099-02-13 00:00+00');
