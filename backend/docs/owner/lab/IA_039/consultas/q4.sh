echo "== realtime predictions <=KO-3h in window, per model x market"
psq -tc "select r.name, p.market_key, count(distinct p.fixture_id), count(distinct p.model_version_id), min(p.data_cutoff_ts)::date, max(p.data_cutoff_ts)::date from core.fixtures f join models.predictions p on p.fixture_id=f.id and p.market_key in ('1X2','OU') and p.backtest_session_id is null join models.model_versions v on v.id=p.model_version_id join models.model_registry r on r.id=v.model_id where f.kickoff_at >= '2026-09-01' and f.kickoff_at < now() and f.status_group='finished' and p.data_cutoff_ts <= f.kickoff_at - interval '3 hours' and (p.market_key='1X2' or p.line=2.5) group by 1,2 order by 1,2"
echo "== match_forecasts model per market (known_at last 30d)"
psq -tc "select market_key, line, model_name, calibration, count(distinct fixture_id) from models.match_forecasts where known_at >= now() - interval '30 days' and ((market_key='1X2') or (market_key='OU' and line=2.5)) group by 1,2,3,4 order by 1,2,5 desc"
echo "== calibrator champions"
psq -tc "select p.market_key, p.model_name, p.at::date, c.method from intel.promotions p join intel.calibrators c on c.id=p.entity_id where p.entity='calibrator' and p.to_role='CHAMPION' and not exists (select 1 from intel.promotions q where q.entity='calibrator' and q.entity_id=p.entity_id and q.to_role='RETIRED' and q.at>=p.at) order by 1,2"
echo "== promoted forecast spec (newest)"
psq -tc "select id, session_id, promoted_at, promoted_by, left(reason,120), snapshot::text from analytics.promoted_forecast_spec order by promoted_at desc limit 2" | cut -c1-1500
