-- IA-073 (AD-B03): repetición del sello en producción, solo lectura. Para cada conjunto de forecast-v1 de los últimos 7 días,
-- el sello que habría dado seal-v1 (campeón vigente y algún consenso sin margen en los 4 días anteriores) y los cambios de
-- sello de cada regla, con y sin cambio de motivo. Ejecutar con default_transaction_read_only=on y statement_timeout.
WITH s AS (
    SELECT DISTINCT fixture_id, market_key, line, known_at, calibration, basis
      FROM models.match_forecasts
     WHERE version = 'forecast-v1' AND known_at >= now() - interval '7 days'
), a AS (
    SELECT s.*, EXISTS (SELECT 1 FROM market.market_consensus m
                         WHERE m.fixture_id = s.fixture_id AND m.market_key = s.market_key AND m.line = s.line
                           AND m.devig_method = 'shin' AND m.as_of <= s.known_at AND m.as_of > s.known_at - interval '4 days'
                           AND m.p_fair > 0 AND m.p_fair < 1) AS has_price
      FROM s
), b AS (
    SELECT *, CASE WHEN basis IN ('champion', 'needs_price') AND has_price THEN 'CALIBRATED' ELSE 'UNCALIBRATED' END AS new_cal
      FROM a
), c AS (
    SELECT *, lag(calibration) OVER w AS pv1, lag(new_cal) OVER w AS pv2, lag(has_price) OVER w AS php
      FROM b WINDOW w AS (PARTITION BY fixture_id, market_key, line ORDER BY known_at)
)
SELECT count(*) FILTER (WHERE pv1 IS NOT NULL AND pv1 <> calibration)                   AS cambios_forecast_v1,
       count(*) FILTER (WHERE pv2 IS NOT NULL AND pv2 <> new_cal)                       AS cambios_seal_v1,
       count(*) FILTER (WHERE pv2 IS NOT NULL AND pv2 <> new_cal AND php = has_price)   AS cambios_seal_v1_sin_motivo,
       count(*) FILTER (WHERE calibration = 'UNCALIBRATED')                             AS sin_calibrar_forecast_v1,
       count(*) FILTER (WHERE new_cal = 'UNCALIBRATED')                                 AS sin_calibrar_seal_v1,
       count(*)                                                                         AS conjuntos
  FROM c;
