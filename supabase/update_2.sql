-- Update 2: HTML-style report, NEW badges, default theaters, reset button.
-- Run once in Supabase → SQL Editor. Safe to run again.

alter table run_results add column if not exists poster  text;
alter table run_results add column if not exists rating  text;
alter table run_results add column if not exists runtime int;
alter table run_results add column if not exists genre   text;
alter table run_results add column if not exists is_new  boolean not null default false;

create table if not exists seen_movies (
    user_id      bigint not null references users(id) on delete cascade,
    amc_movie_id bigint not null,
    title        text,
    first_seen   timestamptz not null default now(),
    primary key (user_id, amc_movie_id)
);
alter table seen_movies enable row level security;
