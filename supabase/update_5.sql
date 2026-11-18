-- Update 5: 'A-List Available' becomes YES / NO / blank, and 'Jonathan Purchased'
-- becomes NEEDS Purchase / x / blank. Existing ticks are kept (YES and x).
-- Run once in Supabase → SQL Editor. Safe to run again.
do $$
begin
    -- A-List Available: YES / NO / blank   (a ticked box becomes YES)
    if (select data_type from information_schema.columns
        where table_name = 'movies' and column_name = 'alist_available') = 'boolean' then
        alter table movies alter column alist_available drop default;
        alter table movies alter column alist_available type text
            using case when alist_available then 'YES' else '' end;
        alter table movies alter column alist_available set default '';
    end if;
    -- Jonathan Purchased: NEEDS Purchase / x / blank   (a ticked box becomes x)
    if (select data_type from information_schema.columns
        where table_name = 'movies' and column_name = 'jonathan_purchased') = 'boolean' then
        alter table movies alter column jonathan_purchased drop default;
        alter table movies alter column jonathan_purchased type text
            using case when jonathan_purchased then 'x' else '' end;
        alter table movies alter column jonathan_purchased set default '';
    end if;
end $$;
