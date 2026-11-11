-- IA-045 / INT-B09 · Estudio de eventos noticia → precio (LAB) · extracción de solo lectura
-- Protocolo proto-int-b09-v1, huella 2b8e49fb115f5cecbcb5e61f52d9ac11d8c8464ce7b3da97af62b3f9382e9232.
--
-- Cómo se ejecuta (ver «Reproducción» en IA_045_ESTUDIO_EVENTOS.md): cada bloque «-- @nombre» es UNA sentencia COPY ... TO STDOUT
-- que se lanza sola, una tras otra, con psql de solo lectura (default_transaction_read_only=on, statement_timeout=95 s):
--   psql -X -c "$(bloque)" > /tmp/lab_b09/<nombre>.csv
-- {{IDS}} y {{TRIPLES}} los rellena el script de la tarea a partir de events.csv (partidos y jugadores con evento).
-- Todas las horas salen en segundos de época UTC. Nada escribe: solo SELECT dentro de COPY TO STDOUT.
--
-- Fuentes de las afirmaciones (protocolo: «proveedor y Research v2»):
--   * core.player_availability_obs  historial de /injuries de API-Football (migración 0078). origin='answer': fila escrita al llegar la
--     respuesta, observed_at = cuándo PREGUNTAMOS (primera lectura). origin='snapshot': copia de core.player_absences hecha al crear la
--     tabla, con su fetched_at (la ÚLTIMA lectura, no la primera): esa afirmación no tiene hora de primera lectura conocida.
--   * ai.evidence origin='provider'  copia del parte del proveedor que hace el colector (retrieved_at = fetched_at del parte leído).
--   * ai.evidence origin='web' con subject_type='PLAYER'  afirmaciones de Research v2 (retrieved_at = la pasada que la leyó por primera
--     vez; una afirmación repetida no se guarda dos veces). Las de Research v1 no llevan jugador (provider_player_id NULL): fuera.
-- Tema: la misma regla del colector (fbi.ai.collectors._kind): motivo con suspen/red card/yellow card/sancion/expuls → sanción;
--   tipo «Questionable» → duda; el resto de «Missing Fixture» → baja. Research v2: OUT → baja, DOUBT → duda, SUSPENSION → sanción,
--   STARTER → titularidad (AVAILABLE no es un tema del protocolo).
-- Ligas prioritarias: grupo 1 de comp-priority-v1 (fbi.intel.day_priority): ids 2, 39, 140, 78, 61, 94, 135.

-- @meta
COPY (
SELECT extract(epoch FROM now()) AS extracted_at,
       (SELECT extract(epoch FROM min(observed_at)) FROM core.player_availability_obs WHERE origin = 'answer') AS answer_history_start,
       (SELECT extract(epoch FROM max(observed_at)) FROM core.player_availability_obs WHERE origin = 'answer') AS answer_history_end,
       (SELECT extract(epoch FROM min(retrieved_at)) FROM ai.evidence WHERE origin = 'web' AND subject_type = 'PLAYER') AS v2_player_start,
       (SELECT extract(epoch FROM max(retrieved_at)) FROM ai.evidence WHERE origin = 'web' AND subject_type = 'PLAYER') AS v2_player_end
) TO STDOUT WITH (FORMAT csv, HEADER)

-- @events
COPY (
WITH fx AS (
    SELECT f.id AS fixture_id
      FROM core.fixtures f
     WHERE f.kickoff_at >= timestamptz '2026-10-22 00:00:00+00' AND f.kickoff_at < now()
),
obs AS (
    SELECT o.fixture_id, o.provider_player_id, o.provider_team_id, o.player_name, o.absence_type, o.reason, o.observed_at, o.origin,
           CASE WHEN lower(coalesce(o.reason, '')) ~ '(suspen|red card|yellow card|sancion|expuls)' THEN 'sancion'
                WHEN lower(coalesce(o.absence_type, '')) LIKE 'question%' THEN 'duda'
                ELSE 'baja' END AS topic
      FROM core.player_availability_obs o
      JOIN fx ON fx.fixture_id = o.fixture_id
     WHERE o.source = 'api-football' AND o.status = 'LISTED'
),
prov AS (
    SELECT fixture_id, provider_player_id, topic,
           min(observed_at) FILTER (WHERE origin = 'answer') AS t_answer,
           min(observed_at) FILTER (WHERE origin = 'snapshot') AS t_snapshot,
           (array_agg(provider_team_id ORDER BY observed_at))[1] AS provider_team_id,
           (array_agg(player_name ORDER BY observed_at))[1] AS player_name,
           (array_agg(coalesce(absence_type, '') || ' / ' || coalesce(reason, '') ORDER BY observed_at))[1] AS detail
      FROM obs
     GROUP BY 1, 2, 3
),
evp AS (
    SELECT e.fixture_id, e.provider_player_id,
           CASE e.kind WHEN 'suspension' THEN 'sancion' WHEN 'doubtful' THEN 'duda' ELSE 'baja' END AS topic,
           min(e.retrieved_at) AS t_evidence, min(e.team_id) AS team_id
      FROM ai.evidence e
      JOIN fx ON fx.fixture_id = e.fixture_id
     WHERE e.origin = 'provider' AND e.kind IN ('injury', 'doubtful', 'suspension') AND e.provider_player_id IS NOT NULL
     GROUP BY 1, 2, 3
),
p AS (
    SELECT coalesce(a.fixture_id, b.fixture_id) AS fixture_id,
           coalesce(a.provider_player_id, b.provider_player_id) AS provider_player_id,
           coalesce(a.topic, b.topic) AS topic, a.t_answer, a.t_snapshot, b.t_evidence,
           coalesce(t.id, b.team_id) AS team_id, a.player_name, a.detail
      FROM prov a
      FULL JOIN evp b ON b.fixture_id = a.fixture_id AND b.provider_player_id = a.provider_player_id AND b.topic = a.topic
      LEFT JOIN core.teams t ON t.provider_team_id = a.provider_team_id
),
v2 AS (
    SELECT e.id, e.fixture_id AS fx_direct, e.team_id, e.provider_player_id, e.claim_type, e.retrieved_at, e.source_tier,
           e.source_domain, e.status, coalesce(e.attributes ->> 'instruction_like', 'false') AS flagged,
           e.attributes ->> 'applies_to' AS applies_to, e.attributes ->> 'player_name' AS player_name
      FROM ai.evidence e
     WHERE e.origin = 'web' AND e.subject_type = 'PLAYER' AND e.claim_type IN ('OUT', 'DOUBT', 'SUSPENSION', 'STARTER')
),
tf AS (
    SELECT f.id AS fixture_id, f.kickoff_at, x.team_id
      FROM core.fixtures f
     CROSS JOIN LATERAL (VALUES (f.home_team_id), (f.away_team_id)) AS x(team_id)
     WHERE f.kickoff_at >= timestamptz '2026-11-01 00:00:00+00' AND f.kickoff_at < now() + interval '11 days'
       AND x.team_id IN (SELECT team_id FROM v2 WHERE fx_direct IS NULL)
),
v2m AS (
    SELECT v.*,
           CASE WHEN v.fx_direct IS NOT NULL THEN 'direct' ELSE 'next' END AS mapping,
           coalesce(v.fx_direct,
                    (SELECT tf.fixture_id FROM tf
                      WHERE tf.team_id = v.team_id AND tf.kickoff_at > v.retrieved_at
                        AND tf.kickoff_at <= v.retrieved_at + interval '10 days'
                      ORDER BY tf.kickoff_at LIMIT 1)) AS fixture_id
      FROM v2 v
),
ev AS (
    SELECT 'provider' AS family, 'P:' || p.fixture_id || ':' || p.provider_player_id || ':' || p.topic AS ev_key,
           p.fixture_id, p.team_id, p.provider_player_id, p.topic,
           extract(epoch FROM p.t_answer) AS t_answer, extract(epoch FROM p.t_snapshot) AS t_snapshot,
           extract(epoch FROM p.t_evidence) AS t_evidence, NULL::numeric AS t_v2,
           'proveedor' AS source_type, 'provider' AS source_tier, NULL::text AS source_domain, NULL::text AS ev_status,
           NULL::text AS applies_to, NULL::text AS mapping, p.player_name, p.detail, NULL::text AS flagged
      FROM p
    UNION ALL
    SELECT 'v2', 'W:' || v.id, v.fixture_id, v.team_id, v.provider_player_id,
           CASE v.claim_type WHEN 'OUT' THEN 'baja' WHEN 'DOUBT' THEN 'duda' WHEN 'SUSPENSION' THEN 'sancion' ELSE 'titularidad' END,
           NULL, NULL, NULL, extract(epoch FROM v.retrieved_at),
           CASE WHEN v.flagged = 'true' THEN 'rumor'
                WHEN v.source_tier IN ('official', 'competition', 'club') THEN 'oficial'
                WHEN v.source_tier = 'provider' THEN 'proveedor'
                WHEN v.source_tier IN ('journalist', 'media') THEN 'medio'
                ELSE 'rumor' END,
           v.source_tier, v.source_domain, v.status, v.applies_to, v.mapping, v.player_name, v.claim_type, v.flagged
      FROM v2m v
)
SELECT ev.*, extract(epoch FROM f.kickoff_at) AS kickoff, f.status_group,
       CASE WHEN ev.team_id = f.home_team_id THEN 'home' WHEN ev.team_id = f.away_team_id THEN 'away' ELSE '' END AS side,
       c.provider_league_id, c.name AS league,
       CASE WHEN c.provider_league_id IN (2, 39, 140, 78, 61, 94, 135) THEN 1 ELSE 0 END AS priority
  FROM ev
  LEFT JOIN core.fixtures f ON f.id = ev.fixture_id
  LEFT JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  LEFT JOIN core.competitions c ON c.id = cs.competition_id
 ORDER BY ev.fixture_id, ev.provider_player_id, ev.topic, ev.family
) TO STDOUT WITH (FORMAT csv, HEADER)

-- @prices
COPY (
SELECT c.fixture_id, extract(epoch FROM c.as_of) AS as_of,
       max(c.p_fair) FILTER (WHERE c.selection = 'Home') AS p_home,
       max(c.p_fair) FILTER (WHERE c.selection = 'Draw') AS p_draw,
       max(c.p_fair) FILTER (WHERE c.selection = 'Away') AS p_away,
       max(c.n_bookmakers) AS n_bk
  FROM market.market_consensus c
  JOIN core.fixtures f ON f.id = c.fixture_id
 WHERE c.fixture_id = ANY ('{ {{IDS}} }'::bigint[])
   AND c.market_key = '1X2' AND c.line = 0 AND c.devig_method = 'shin'
   AND c.as_of < f.kickoff_at AND c.as_of >= f.kickoff_at - interval '11 days'
 GROUP BY c.fixture_id, c.as_of
 ORDER BY c.fixture_id, c.as_of
) TO STDOUT WITH (FORMAT csv, HEADER)

-- @importance
COPY (
WITH e(fixture_id, team_id, provider_player_id) AS (VALUES {{TRIPLES}}),
ef AS (
    SELECT DISTINCT e.fixture_id, e.team_id, e.provider_player_id, f.kickoff_at
      FROM e JOIN core.fixtures f ON f.id = e.fixture_id
),
tfx AS (
    SELECT f.id AS prev_id, f.kickoff_at, x.team_id, x.side
      FROM core.fixtures f
     CROSS JOIN LATERAL (VALUES (f.home_team_id, 'home'), (f.away_team_id, 'away')) AS x(team_id, side)
     WHERE f.kickoff_at >= timestamptz '2026-06-15 00:00:00+00' AND f.kickoff_at < now()
       AND x.team_id IN (SELECT team_id FROM ef)
),
prev AS (
    SELECT ef.fixture_id, ef.team_id, ef.provider_player_id, t.prev_id, t.side,
           row_number() OVER (PARTITION BY ef.fixture_id, ef.team_id, ef.provider_player_id ORDER BY t.kickoff_at DESC) AS rn
      FROM ef
      JOIN tfx t ON t.team_id = ef.team_id AND t.kickoff_at < ef.kickoff_at AND t.kickoff_at >= ef.kickoff_at - interval '120 days'
     WHERE EXISTS (SELECT 1 FROM core.fixture_lineups l WHERE l.fixture_id = t.prev_id AND l.team_side = t.side)
)
SELECT prev.fixture_id, prev.team_id, prev.provider_player_id, count(*) AS n_prev,
       count(*) FILTER (WHERE lp.is_starter) AS starts, count(lp.provider_player_id) AS in_lineup
  FROM prev
  LEFT JOIN core.fixture_lineup_players lp
         ON lp.fixture_id = prev.prev_id AND lp.team_side = prev.side AND lp.provider_player_id = prev.provider_player_id
 WHERE prev.rn <= 5
 GROUP BY 1, 2, 3
) TO STDOUT WITH (FORMAT csv, HEADER)
