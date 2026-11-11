echo "== window finished fixtures by priority, with api-football stats"
psq -tc "with s as (select fixture_id, bool_and(shots is not null and shots_on_target is not null) sh, bool_and(expected_goals is not null) xg from core.fixture_team_stats where source='api-football' group by 1 having count(*)=2)
select (c.provider_league_id in (2,39,140,78,61,135)) prio, count(*) fin, count(r.fixture_id) withres, count(s.fixture_id) stats2, sum(s.sh::int) shots2, sum(s.xg::int) xg2, min(f.kickoff_at)::date, max(f.kickoff_at)::date
 from core.fixtures f join core.competition_seasons cs on cs.id=f.competition_season_id join core.competitions c on c.id=cs.competition_id left join core.fixture_results r on r.fixture_id=f.id left join s on s.fixture_id=f.id
 where f.kickoff_at >= '2026-09-01' and f.kickoff_at < now() and f.status_group='finished' group by 1 order by 1"
echo "== explain predictions window"
psq -tc "explain select r.name, count(distinct p.fixture_id) from core.fixtures f join models.predictions p on p.fixture_id=f.id and p.market_key in ('1X2','OU') and p.backtest_session_id is null join models.model_versions v on v.id=p.model_version_id join models.model_registry r on r.id=v.model_id where f.kickoff_at >= '2026-09-01' and f.kickoff_at < now() and f.status_group='finished' and p.data_cutoff_ts <= f.kickoff_at - interval '3 hours' group by 1"
