echo "== priority comps"
psq -tc "select c.id, c.provider_league_id, c.name, c.country, c.competition_type, c.is_tracked from core.competitions c where c.provider_league_id in (2,39,140,78,61,135) order by 2"
echo "== by source"
psq -tc "select source, count(*), count(distinct fixture_id), count(shots), count(shots_on_target), count(expected_goals), min(fetched_at)::date, max(fetched_at)::date from core.fixture_team_stats group by 1"
echo "== api-football by season: finished fixtures | with both-sides shots | both sot | both xg  (all comps)"
psq -tc "with s as (select fixture_id, bool_and(shots is not null) sh, bool_and(shots_on_target is not null) so, bool_and(expected_goals is not null) xg, count(*) n from core.fixture_team_stats where source='api-football' group by 1 having count(*)=2)
select cs.season, count(*) fin, count(s.fixture_id) stats2, sum(s.sh::int), sum(s.so::int), sum(s.xg::int) from core.fixtures f join core.competition_seasons cs on cs.id=f.competition_season_id left join s on s.fixture_id=f.id where f.status_group='finished' group by 1 order by 1"
echo "== football-data by season"
psq -tc "with s as (select fixture_id, bool_and(shots is not null) sh, bool_and(shots_on_target is not null) so from core.fixture_team_stats where source='football-data.co.uk' group by 1 having count(*)=2)
select cs.season, count(s.fixture_id), sum(s.sh::int), sum(s.so::int) from core.fixtures f join core.competition_seasons cs on cs.id=f.competition_season_id join s on s.fixture_id=f.id where f.status_group='finished' group by 1 order by 1"
