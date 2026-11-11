echo "== nproc / mem"; nproc; free -g | head -2
IMG=$(docker inspect -f '{{.Config.Image}}' predigol-worker); echo "IMG $IMG"
docker run --rm --network none --entrypoint python "$IMG" -c "
import numpy, scipy, sys; print('py', sys.version.split()[0], 'numpy', numpy.__version__, 'scipy', scipy.__version__)
try:
    import fbi.research.blend as b; print('blend ok', b.BOOTSTRAP_DRAWS, b.SEED, b.W_BOUNDS)
except Exception as e: print('blend missing', type(e).__name__)
try:
    import fbi.research.protocol as p; print('protocol ok', p.stamp('INT-A09'))
except Exception as e: print('protocol missing', type(e).__name__)
"
echo "== spec in force"
psq -tc "select id, session_id, promoted_at, promoted_by, spec->'history_days', (spec->'goal')::text from analytics.promoted_forecast_spec order by promoted_at desc, id desc limit 1"
echo "== rt prediction lag (poisson, window): created_at - data_cutoff_ts > 10 min"
psq -tc "select count(*) filter (where p.created_at - p.data_cutoff_ts > interval '10 minutes'), count(*) from core.fixtures f join models.predictions p on p.fixture_id=f.id and p.market_key='1X2' and p.selection='Home' and p.backtest_session_id is null join models.model_versions v on v.id=p.model_version_id join models.model_registry r on r.id=v.model_id and r.name='poisson' where f.kickoff_at >= '2026-09-20' and f.kickoff_at < now() and f.status_group='finished'"
