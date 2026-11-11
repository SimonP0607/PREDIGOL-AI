-- INT-A02 (IA-036, LAB) · extracción de solo lectura para el protocolo proto-int-a02-v1 (huella 2a1cdb3e…).
-- Una consulta por tramo de saques [lo, hi); el script de la tarea la corre DÍA A DÍA (UTC), una a la vez, y para si un tramo falla:
--   docker exec -i -e PGOPTIONS="-c default_transaction_read_only=on -c statement_timeout=95000" predigol-postgres \
--     psql -U fbi -d fbi -X -q -v ON_ERROR_STOP=1 -v lo=2026-09-01 -v hi=2026-09-02 -v units=true  -f - < extract.sql > units_d.csv
--   ... -v units=false ... > picks_w.csv
-- COPY ... TO STDOUT es una lectura: corre en una transacción de solo lectura y escribe en la salida de psql (el host), no en el
-- servidor de la base de datos.
--
-- (v2 de la consulta, 11-nov 05:45 UTC: un LATERAL por partido en lugar de un CTE referido dos veces, que PostgreSQL materializaba
--  y barría models.predictions entero; la primera ejecución, semana a semana, superó el statement_timeout en 6 de 11 tramos.)
-- units=true  · UNA FILA POR (partido, modelo, mercado, resultado) de 1X2, más/menos 2,5 y ambos marcan:
--   partido   terminado (status_group 'finished'), con su marcador reglamentario y su hora de liquidación (core.fixture_results)
--   modelo    su ÚLTIMA predicción guardada 3 h o más antes del saque (created_at <= saque - 3 h), real (no de backtest), por
--             (partido, modelo, mercado): la de data_cutoff_ts más reciente y, a igualdad, la versión más nueva (como market_reader)
--   mercado   por resultado, el consenso Shin sin margen MÁS RECIENTE con 6 h o menos de antigüedad en el momento de esa
--             predicción (as_of en [t - 6 h, t], t = created_at), p_fair en (0, 1) (como market_reader.CONSENSUS_SQL);
--             NULL cuando no hay ninguno (el script excluye ese partido-mercado)
-- units=false · LA POBLACIÓN DE cal-logit2-v1 (fbi.intel.calibration.SETTLED_SQL sin el corte, que aplica el script por día):
--   el último pick antes del saque de cada (partido, mercado, selección, línea, modelo) de 1X2, OU (todas las líneas, como el
--   calibrador en producción, que no separa líneas) y BTTS, con su resultado liquidado; los filtros win/loss y p en (0, 1) los
--   aplica el script, que también usa estas filas para marcar las selecciones que el modelo señaló.
\if :units
COPY (
SELECT f.id AS fixture_id, f.kickoff_at, f.status_short, r.settled_at, r.reg_goals_home AS gh, r.reg_goals_away AS ga,
       c.provider_league_id, l.model, l.market_key, l.line, l.model_version_id, l.data_cutoff_ts, l.created_at AS t,
       p.selection, p.p_raw::float8 AS q, p.p_calibrated::float8 AS q_cal, mc.p_fair AS m, mc.as_of AS m_as_of
  FROM core.fixtures f
  JOIN core.fixture_results r ON r.fixture_id = f.id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  CROSS JOIN LATERAL (
       SELECT DISTINCT ON (mr.name, pp.market_key)
              mr.name AS model, pp.market_key, pp.line, pp.model_version_id, pp.data_cutoff_ts, pp.created_at
         FROM models.predictions pp
         JOIN models.model_versions v ON v.id = pp.model_version_id
         JOIN models.model_registry mr ON mr.id = v.model_id
        WHERE pp.fixture_id = f.id AND pp.market_key IN ('1X2', 'OU', 'BTTS') AND pp.backtest_session_id IS NULL
          AND ((pp.market_key IN ('1X2', 'BTTS') AND pp.line = 0) OR (pp.market_key = 'OU' AND pp.line = 2.5))
          AND pp.created_at <= f.kickoff_at - interval '3 hours'
        ORDER BY mr.name, pp.market_key, pp.data_cutoff_ts DESC, pp.model_version_id DESC, pp.created_at DESC) l
  JOIN models.predictions p ON p.fixture_id = f.id AND p.model_version_id = l.model_version_id
       AND p.market_key = l.market_key AND p.line = l.line AND p.data_cutoff_ts = l.data_cutoff_ts
       AND p.backtest_session_id IS NULL
  LEFT JOIN LATERAL (
       SELECT cc.p_fair::float8 AS p_fair, cc.as_of
         FROM market.market_consensus cc
        WHERE cc.fixture_id = f.id AND cc.market_key = l.market_key AND cc.selection = p.selection AND cc.line = l.line
          AND cc.devig_method = 'shin' AND cc.as_of <= l.created_at AND cc.as_of >= l.created_at - interval '6 hours'
          AND cc.p_fair > 0 AND cc.p_fair < 1
        ORDER BY cc.as_of DESC
        LIMIT 1) mc ON true
 WHERE f.kickoff_at >= :'lo'::timestamptz AND f.kickoff_at < :'hi'::timestamptz AND f.status_group = 'finished'
 ORDER BY f.id, l.model, l.market_key, p.selection
) TO STDOUT WITH (FORMAT csv, HEADER true);
\else
COPY (
WITH last AS (
    SELECT DISTINCT ON (p.fixture_id, p.market_key, p.selection, p.line, r.name)
           p.id AS pick_id, p.fixture_id, f.kickoff_at, p.market_key, p.selection, p.line, r.name AS model,
           p.p_calibrated::float8 AS p_model, p.p_market_fair::float8 AS p_market, p.market_odds::float8 AS odds,
           pr.result_status, pr.settled_at, p.created_at
      FROM picks.picks p
      JOIN core.fixtures f ON f.id = p.fixture_id
      JOIN models.model_versions v ON v.id = p.model_version_id
      JOIN models.model_registry r ON r.id = v.model_id
      JOIN picks.pick_results pr ON pr.pick_id = p.id
     WHERE p.market_key IN ('1X2', 'OU', 'BTTS')
       AND f.kickoff_at >= :'lo'::timestamptz AND f.kickoff_at < :'hi'::timestamptz
       AND p.created_at < f.kickoff_at
       AND pr.settled_at IS NOT NULL
     ORDER BY p.fixture_id, p.market_key, p.selection, p.line, r.name, p.created_at DESC, p.id DESC
)
SELECT * FROM last ORDER BY kickoff_at, pick_id
) TO STDOUT WITH (FORMAT csv, HEADER true);
\endif
