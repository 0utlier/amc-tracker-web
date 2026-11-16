-- Update 3: per-person "show showtimes in the date pop-up" setting (off by default).
-- Run once in Supabase → SQL Editor. Safe to run again.
alter table users add column if not exists show_times boolean not null default false;
