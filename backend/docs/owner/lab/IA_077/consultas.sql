-- IA-077: read-only queries run against production on 17 Nov 2026 (psql with default_transaction_read_only=on and
-- statement_timeout=95 s). The provider probe itself is probe_cuatro_ligas.py.txt (8 requests, nothing stored).

-- 1. The four in the catalogue (00:30-03:30 UTC)
select id, provider_league_id, name, country, type, competition_type, elo_weight, tier, is_tracked
  from core.competitions where provider_league_id in (268, 299, 241, 240) order by 1;

-- 2. Provider coverage flags per season (raw.league_coverage, refreshed by catalogue_refresh at 00:28:57 UTC)
select provider_league_id, season, league_name, country, league_type, is_current, start_date, end_date, events,
       lineups, statistics_fixtures, statistics_players, standings, injuries, odds, observed_at
  from raw.league_coverage where provider_league_id in (268, 299, 241, 240) and season >= 2024 order by 1, 2;
select provider_league_id, count(*), min(season), max(season), count(*) filter (where events),
       count(*) filter (where lineups), count(*) filter (where statistics_fixtures),
       count(*) filter (where statistics_players), count(*) filter (where injuries)
  from raw.league_coverage where provider_league_id in (268, 299, 241, 240) group by 1 order by 1;

-- 3. Fixtures already stored for them (0 rows: none, they were never tracked)
select c.provider_league_id, cs.season, count(*)
  from core.fixtures f join core.competition_seasons cs on cs.id = f.competition_season_id
  join core.competitions c on c.id = cs.competition_id
 where c.provider_league_id in (268, 299, 241, 240) group by 1, 2;

-- 4. Requests by job, 7 full days (10-16 Nov 2026), and tracked fixtures of those days
select job_name, sum(api_calls), count(*) from raw.ingestion_runs
 where started_at >= '2026-11-10' and started_at < '2026-11-17' group by 1 order by 2 desc;
select count(*) from core.competitions where is_tracked;
with f as (select competition_season_id, kickoff_at from core.fixtures
            where kickoff_at >= '2026-11-10' and kickoff_at < '2026-11-17')
select f.kickoff_at::date, count(*) from f join core.competition_seasons cs on cs.id = f.competition_season_id
  join core.competitions c on c.id = cs.competition_id where c.is_tracked group by 1 order by 1;

-- 5. Our daily budget counter, 31 days (17 Oct - 16 Nov 2026)
select count(*), round(avg(spent)), percentile_cont(0.5) within group (order by spent), max(spent)
  from raw.provider_quota where quota_date >= '2026-10-17' and quota_date < '2026-11-17';
select quota_date, spent from raw.provider_quota where quota_date >= '2026-10-17' order by spent desc limit 3;
