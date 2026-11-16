-- AMC Tracker website — Supabase schema
-- Paste this whole file into Supabase → SQL Editor → New query → Run.
-- Safe to re-run: everything uses "if not exists" / "or replace".

-- ── Users & their own search preferences ────────────────────────────────────
create table if not exists users (
    id            bigserial primary key,
    slug          text not null unique,          -- the part after the slash: yoursite/jd
    display_name  text not null,                 -- what goes in the USER column
    zip           text,
    theatre_count int  not null default 5 check (theatre_count between 1 and 12),
    days          int  not null default 90 check (days between 1 and 120),
    created_at    timestamptz not null default now(),
    constraint slug_format check (slug ~ '^[a-z0-9_-]+$')
);

insert into users (slug, display_name) values
    ('jd', 'JD'), ('meagan', 'Meagan'), ('kevin', 'Kevin')
on conflict (slug) do nothing;

-- ── Shared tracker: one consolidated row per movie ──────────────────────────
create table if not exists movies (
    id                 bigserial primary key,
    amc_movie_id       bigint unique,             -- AMC's id; this is what prevents duplicates
    title              text not null,
    users              text[] not null default '{}',
    alist_available    boolean not null default false,
    jonathan_purchased boolean not null default false,
    needs_refund       boolean not null default false,
    needs_alternative  boolean not null default false,
    notes              text not null default '',
    movie_url          text,
    created_at         timestamptz not null default now(),
    updated_at         timestamptz not null default now()
);

create table if not exists movie_dates (
    movie_id  bigint not null references movies(id) on delete cascade,
    show_date date   not null,
    primary key (movie_id, show_date)
);

-- Atomic add-or-merge. Two people adding the same movie at the same moment
-- still end up with one row: the unique amc_movie_id + ON CONFLICT handles it.
create or replace function add_movie_to_tracker(
    p_amc_movie_id  bigint,
    p_title         text,
    p_user          text,
    p_dates         date[],
    p_is_imax       boolean,
    p_theatre_count int,
    p_movie_url     text
) returns bigint
language plpgsql as $$
declare
    v_id   bigint;
    v_note text;
begin
    v_note := concat_ws('; ',
        case when p_is_imax then 'IMAX' end,
        case when p_theatre_count = 1 then 'Only one theater' end);

    insert into movies (amc_movie_id, title, users, notes, movie_url)
    values (p_amc_movie_id, p_title, array[p_user], v_note, p_movie_url)
    on conflict (amc_movie_id) do update
        set users = case
                        when p_user = any (movies.users) then movies.users
                        else array_append(movies.users, p_user)
                    end,
            -- keep everyone's checkboxes and notes; only fill a missing link
            movie_url  = coalesce(movies.movie_url, excluded.movie_url),
            updated_at = now()
    returning id into v_id;

    insert into movie_dates (movie_id, show_date)
    select v_id, d from unnest(p_dates) as d
    on conflict do nothing;

    return v_id;
end $$;

-- ── Search history: last 5 runs per user (pruned by the app) ────────────────
create table if not exists runs (
    id              uuid primary key default gen_random_uuid(),
    user_id         bigint not null references users(id) on delete cascade,
    run_at          timestamptz not null default now(),
    zip             text,
    theatre_count   int,
    days            int,
    theatres        jsonb not null default '[]',   -- [{id, name, miles, color}]
    movie_count     int  not null default 0,
    empty_days      int  not null default 0,
    screenshot_path text
);
create index if not exists runs_user_time on runs (user_id, run_at desc);

-- Frozen copy of every movie in a run (with full showtimes), so history never
-- changes even after AMC's listings do.
create table if not exists run_results (
    id            bigserial primary key,
    run_id        uuid not null references runs(id) on delete cascade,
    amc_movie_id  bigint,
    title         text not null,
    movie_url     text,
    is_imax       boolean not null default false,
    formats       text[] not null default '{}',
    theatre_count int not null default 0,
    dates         date[] not null default '{}',
    theatres      jsonb not null default '{}'      -- {tid: {name, dates: {YYYY-MM-DD: [{time, formats, url}]}}}
);
create index if not exists run_results_run on run_results (run_id);

-- ── Lock the tables down ────────────────────────────────────────────────────
-- The website talks to Supabase with the secret service_role key from the
-- server, which bypasses RLS. Turning RLS on with no policies means the public
-- "anon" key can't read or change anything.
alter table users       enable row level security;
alter table movies      enable row level security;
alter table movie_dates enable row level security;
alter table runs        enable row level security;
alter table run_results enable row level security;

-- ── Screenshot storage bucket (private) ─────────────────────────────────────
insert into storage.buckets (id, name, public)
values ('run-screenshots', 'run-screenshots', false)
on conflict (id) do nothing;
