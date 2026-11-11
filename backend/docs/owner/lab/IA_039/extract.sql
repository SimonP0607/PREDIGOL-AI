-- IA-039 — E4: tiros y xG en los ratings (LAB). Plan Maestro de Evolución de PrediGol Intelligence 2026, pieza INT-A09.
-- Protocolo proto-int-a09-v1 (huella 400778f85de7acdfc59b1d9e265d7f4c4d5fe42abc4abf71cb5785b33604bd36).
--
-- Extracción de SOLO LECTURA para ia_lab_e4_xg.py. Cada bloque empieza con una línea «-- @file <nombre>.csv» y se ejecuta
-- con psql de solo lectura (default_transaction_read_only=on, statement_timeout=95 s) como
--     \copy (<bloque en una línea>) to stdout with csv header   >  /tmp/lab_a09/<nombre>.csv
-- Las líneas de comentario se quitan antes; dentro de los bloques no hay comentarios ni el carácter dólar.
-- Todas las consultas filtran por fecha o por partido (índices fixtures_kickoff_at_idx, predictions_fixture_id_market_key_idx,
-- market_consensus_fixture_id_as_of_idx); core.fixture_team_stats (~360 mil filas) se agrega entera, una vez por bloque.
-- Los bloques marcados «@weekly» se ejecutan por semanas de saque (el generador añade a «ev» la condición
-- f.kickoff_at >= <lunes> AND f.kickoff_at < <lunes siguiente>) y se concatenan: en una sola sentencia, la lectura de
-- models.predictions de todos los partidos superó los 95 s de statement_timeout.
--
-- Definiciones (fijadas antes de mirar resultados):
--   * Partido evaluable: status_group = 'finished', con marcador, saque entre el 1-sep-2026 y now() - 3 h.
--   * Momento de decisión T = saque - 3 h. Modelo actual: su última predicción en tiempo real (backtest_session_id IS NULL)
--     con data_cutoff_ts <= T y created_at <= T. Mercado: consenso Shin (devig_method = 'shin') más reciente con
--     T - 6 h <= as_of <= T, con el mercado completo en ese as_of (1X2: Home, Draw, Away; más/menos 2,5: Over, Under).
--   * Resultado: marcador reglamentario (reg_goals_*) si existe; si no, el final (como fbi.features.data.MatchRecord.settle_*).
--   * Estadísticas: api-football si trae tiros y tiros a puerta de los dos lados; si no, football-data.co.uk. xG solo existe
--     en api-football.

-- @file coverage.csv
WITH api AS (
  SELECT fixture_id,
         bool_and(shots IS NOT NULL AND shots_on_target IS NOT NULL) AS shots2,
         bool_and(expected_goals IS NOT NULL) AS xg2
    FROM core.fixture_team_stats WHERE source = 'api-football'
   GROUP BY fixture_id HAVING count(*) = 2
), fd AS (
  SELECT fixture_id, bool_and(shots IS NOT NULL AND shots_on_target IS NOT NULL) AS shots2
    FROM core.fixture_team_stats WHERE source = 'football-data.co.uk'
   GROUP BY fixture_id HAVING count(*) = 2
)
SELECT c.id AS competition_id, c.provider_league_id, c.name, c.country, c.competition_type, cs.season,
       count(*) AS finished,
       count(api.fixture_id) AS api_rows2,
       count(*) FILTER (WHERE api.shots2 OR fd.shots2) AS shots_sot2,
       count(*) FILTER (WHERE api.xg2) AS xg2,
       min(f.kickoff_at)::date AS first_ko, max(f.kickoff_at)::date AS last_ko
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  JOIN core.fixture_results r ON r.fixture_id = f.id
  LEFT JOIN api ON api.fixture_id = f.id
  LEFT JOIN fd ON fd.fixture_id = f.id
 WHERE f.status_group = 'finished' AND r.goals_home IS NOT NULL AND r.goals_away IS NOT NULL
 GROUP BY 1, 2, 3, 4, 5, 6
 ORDER BY 1, 6

-- @file matches.csv
WITH api AS (
  SELECT fixture_id,
         max(shots) FILTER (WHERE team_side = 'home') AS h_sh,
         max(shots_on_target) FILTER (WHERE team_side = 'home') AS h_sot,
         max(expected_goals) FILTER (WHERE team_side = 'home') AS h_xg,
         max(shots) FILTER (WHERE team_side = 'away') AS a_sh,
         max(shots_on_target) FILTER (WHERE team_side = 'away') AS a_sot,
         max(expected_goals) FILTER (WHERE team_side = 'away') AS a_xg
    FROM core.fixture_team_stats WHERE source = 'api-football'
   GROUP BY fixture_id HAVING count(*) = 2
), fd AS (
  SELECT fixture_id,
         max(shots) FILTER (WHERE team_side = 'home') AS h_sh,
         max(shots_on_target) FILTER (WHERE team_side = 'home') AS h_sot,
         max(shots) FILTER (WHERE team_side = 'away') AS a_sh,
         max(shots_on_target) FILTER (WHERE team_side = 'away') AS a_sot
    FROM core.fixture_team_stats WHERE source = 'football-data.co.uk'
   GROUP BY fixture_id HAVING count(*) = 2
), j AS (
  SELECT f.id AS fixture_id, f.kickoff_at, c.id AS competition_id, c.provider_league_id, c.competition_type, cs.season,
         f.home_team_id, f.away_team_id,
         coalesce(r.reg_goals_home, r.goals_home) AS gh, coalesce(r.reg_goals_away, r.goals_away) AS ga,
         (f.is_neutral OR c.neutral_venue) AS neutral,
         EXISTS (SELECT 1 FROM analytics.fixture_validation v
                  WHERE v.fixture_id = f.id AND v.state IN ('QUARANTINED', 'INGESTED')) AS excluded,
         (api.h_sh IS NOT NULL AND api.h_sot IS NOT NULL AND api.a_sh IS NOT NULL AND api.a_sot IS NOT NULL) AS api_ok,
         (fd.h_sh IS NOT NULL AND fd.h_sot IS NOT NULL AND fd.a_sh IS NOT NULL AND fd.a_sot IS NOT NULL) AS fd_ok,
         api.h_sh AS api_h_sh, api.h_sot AS api_h_sot, api.a_sh AS api_a_sh, api.a_sot AS api_a_sot,
         fd.h_sh AS fd_h_sh, fd.h_sot AS fd_h_sot, fd.a_sh AS fd_a_sh, fd.a_sot AS fd_a_sot,
         api.h_xg, api.a_xg
    FROM core.fixtures f
    JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
    JOIN core.competitions c ON c.id = cs.competition_id
    JOIN core.fixture_results r ON r.fixture_id = f.id
    LEFT JOIN api ON api.fixture_id = f.id
    LEFT JOIN fd ON fd.fixture_id = f.id
   WHERE f.status_group = 'finished' AND f.kickoff_at >= '2024-01-01' AND f.kickoff_at < now()
     AND r.goals_home IS NOT NULL AND r.goals_away IS NOT NULL
)
SELECT fixture_id, extract(epoch FROM kickoff_at)::bigint AS ko, competition_id, provider_league_id, competition_type, season,
       home_team_id, away_team_id, gh, ga, neutral::int AS neutral, excluded::int AS excluded,
       CASE WHEN api_ok THEN 'api' WHEN fd_ok THEN 'fd' END AS src,
       CASE WHEN api_ok THEN api_h_sh WHEN fd_ok THEN fd_h_sh END AS h_sh,
       CASE WHEN api_ok THEN api_h_sot WHEN fd_ok THEN fd_h_sot END AS h_sot,
       CASE WHEN api_ok THEN api_a_sh WHEN fd_ok THEN fd_a_sh END AS a_sh,
       CASE WHEN api_ok THEN api_a_sot WHEN fd_ok THEN fd_a_sot END AS a_sot,
       h_xg, a_xg
  FROM j
 ORDER BY kickoff_at, fixture_id

-- @file current.csv @weekly
WITH ev AS (
  SELECT f.id, f.kickoff_at FROM core.fixtures f
   WHERE f.kickoff_at >= '2026-09-01' AND f.kickoff_at < now() - interval '3 hours' AND f.status_group = 'finished'
), p AS (
  SELECT p.fixture_id, r.name AS model, p.model_version_id, p.market_key, p.selection, p.line, p.p_raw, p.p_calibrated,
         p.data_cutoff_ts, p.created_at
    FROM ev
    JOIN models.predictions p ON p.fixture_id = ev.id AND p.market_key IN ('1X2', 'OU') AND p.backtest_session_id IS NULL
    JOIN models.model_versions v ON v.id = p.model_version_id
    JOIN models.model_registry r ON r.id = v.model_id
   WHERE r.name IN ('poisson', 'dixon_coles', 'elo_ologit') AND (p.market_key = '1X2' OR p.line = 2.5)
     AND p.data_cutoff_ts <= ev.kickoff_at - interval '3 hours' AND p.created_at <= ev.kickoff_at - interval '3 hours'
), last AS (
  SELECT fixture_id, model, market_key, max(data_cutoff_ts) AS c FROM p GROUP BY 1, 2, 3
)
SELECT p.fixture_id, p.model, p.model_version_id, p.market_key, p.selection, p.line, p.p_raw, p.p_calibrated,
       extract(epoch FROM p.data_cutoff_ts)::bigint AS cutoff, extract(epoch FROM p.created_at)::bigint AS created
  FROM p JOIN last l ON l.fixture_id = p.fixture_id AND l.model = p.model AND l.market_key = p.market_key
                    AND l.c = p.data_cutoff_ts
 ORDER BY 1, 2, 4, 5

-- @file market.csv @weekly
WITH ev AS (
  SELECT f.id, f.kickoff_at FROM core.fixtures f
   WHERE f.kickoff_at >= '2026-09-01' AND f.kickoff_at < now() - interval '3 hours' AND f.status_group = 'finished'
), m AS (
  SELECT m.fixture_id, m.market_key, m.as_of, m.selection, m.p_fair, m.n_bookmakers
    FROM ev JOIN market.market_consensus m ON m.fixture_id = ev.id
   WHERE m.devig_method = 'shin'
     AND m.as_of <= ev.kickoff_at - interval '3 hours' AND m.as_of >= ev.kickoff_at - interval '9 hours'
     AND ((m.market_key = '1X2' AND m.line = 0 AND m.selection IN ('Home', 'Draw', 'Away'))
       OR (m.market_key = 'OU' AND m.line = 2.5 AND m.selection IN ('Over', 'Under')))
     AND m.p_fair > 0 AND m.p_fair < 1
), complete AS (
  SELECT fixture_id, market_key, as_of FROM m GROUP BY 1, 2, 3
  HAVING count(DISTINCT selection) = CASE WHEN market_key = '1X2' THEN 3 ELSE 2 END
), last AS (
  SELECT fixture_id, market_key, max(as_of) AS a FROM complete GROUP BY 1, 2
)
SELECT m.fixture_id, m.market_key, m.selection, m.p_fair, m.n_bookmakers, extract(epoch FROM m.as_of)::bigint AS as_of
  FROM m JOIN last l ON l.fixture_id = m.fixture_id AND l.market_key = m.market_key AND l.a = m.as_of
 ORDER BY 1, 2, 3
