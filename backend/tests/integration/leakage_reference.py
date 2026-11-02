"""The two rules of the leak audit as they were before they were made linear (``leak-audit-v6``, 24 Oct 2026), kept word for word.

They answered the same question as ``leakage.RULES`` today, but looked into a materialised CTE once per row (``NOT EXISTS (SELECT 1 FROM m
...)`` and ``SELECT min(...) FROM f ...`` inside a correlated ``EXISTS``), so the work grew with the SQUARE of the packets of the day: on
23 Oct 2026, with 10,209 packets of ``packet-v8``, the nightly run was still reading them after more than an hour. The test of
``test_leak_audit_scale.py`` runs both on the same world and wants the same row for row; this file is its yardstick and nothing else reads it."""

from __future__ import annotations

from fbi.intel import h2h, tactics
from fbi.intel.leakage import FINISHED, PACKETS, _int

H2H_KNOWN = f"""
        WITH p AS ({PACKETS}), b AS (
            SELECT p.id AS packet_id, p.as_of, p.content -> 'h2h' AS blk,
                   (p.content #>> '{{fixture,kickoff_at}}')::timestamptz AS kickoff,
                   CASE WHEN (p.content #>> '{{fixture,home,id}}') ~ '^[0-9]{{1,15}}$' THEN (p.content #>> '{{fixture,home,id}}')::bigint END AS home_id,
                   CASE WHEN (p.content #>> '{{fixture,away,id}}') ~ '^[0-9]{{1,15}}$' THEN (p.content #>> '{{fixture,away,id}}')::bigint END AS away_id
              FROM p WHERE jsonb_typeof(p.content #> '{{h2h,meetings}}') = 'array'),
        m AS (
            SELECT b.packet_id, b.as_of, b.kickoff, b.home_id, b.away_id,
                   CASE WHEN (x ->> 'fixture_id') ~ '^[0-9]{{1,15}}$' THEN (x ->> 'fixture_id')::bigint END AS leg,
                   CASE WHEN (x ->> 'days_ago') ~ '^[0-9]{{1,6}}$' THEN (x ->> 'days_ago')::int END AS days_ago,
                   (jsonb_typeof(x #> '{{coach_changed,home}}') = 'boolean'
                    OR jsonb_typeof(x #> '{{coach_changed,away}}') = 'boolean') AS coach_claim
              FROM b CROSS JOIN LATERAL jsonb_array_elements(b.blk -> 'meetings') AS x WHERE jsonb_typeof(x) = 'object'),
        c AS (
            SELECT m.packet_id,
                   (g.id IS NULL OR g.kickoff_at >= m.kickoff OR r.settled_at IS NULL OR r.settled_at > m.as_of
                    OR NOT (g.status_short = ANY({FINISHED}))
                    OR NOT ((g.home_team_id = m.home_id AND g.away_team_id = m.away_id)
                            OR (g.home_team_id = m.away_id AND g.away_team_id = m.home_id))
                    OR m.days_ago IS DISTINCT FROM floor(extract(epoch FROM (m.kickoff - g.kickoff_at)) / 86400)::int
                    OR (m.coach_claim AND NOT EXISTS (SELECT 1 FROM core.fixture_lineups l
                                                       WHERE l.fixture_id = m.leg AND l.fetched_at <= m.as_of))) AS bad
              FROM m LEFT JOIN core.fixtures g ON g.id = m.leg LEFT JOIN core.fixture_results r ON r.fixture_id = m.leg
            UNION ALL
            SELECT b.packet_id,
                   EXISTS (SELECT 1 FROM core.fixtures g JOIN core.fixture_results r ON r.fixture_id = g.id
                            WHERE ((g.home_team_id = b.home_id AND g.away_team_id = b.away_id)
                                   OR (g.home_team_id = b.away_id AND g.away_team_id = b.home_id))
                              AND g.kickoff_at < b.kickoff AND r.settled_at <= b.as_of AND g.status_short = ANY({FINISHED})
                              AND r.reg_goals_home IS NOT NULL AND r.reg_goals_away IS NOT NULL
                              AND NOT EXISTS (SELECT 1 FROM m WHERE m.packet_id = b.packet_id AND m.leg = g.id)
                              AND (jsonb_array_length(b.blk -> 'meetings') < {h2h.N}
                                   OR g.kickoff_at > (SELECT min(g2.kickoff_at) FROM m JOIN core.fixtures g2 ON g2.id = m.leg
                                                       WHERE m.packet_id = b.packet_id))) AS bad
              FROM b)
        SELECT count(*) AS n, count(*) FILTER (WHERE c.bad) AS bad,
               (array_agg(DISTINCT c.packet_id) FILTER (WHERE c.bad))[1:5] AS examples FROM c"""


TACTICS_KNOWN = f"""
        WITH p AS ({PACKETS}), b AS (
            SELECT p.id AS packet_id, p.as_of, (p.content #>> '{{fixture,kickoff_at}}')::timestamptz AS kickoff, v.side,
                   CASE WHEN (p.content #>> ARRAY['fixture', v.side, 'id']) ~ '^[0-9]{{1,15}}$'
                        THEN (p.content #>> ARRAY['fixture', v.side, 'id'])::bigint END AS team,
                   p.content #> ARRAY['dossier', 'tactics', v.side] AS blk
              FROM p CROSS JOIN (VALUES ('home'), ('away')) AS v(side)
             WHERE jsonb_typeof(p.content #> ARRAY['dossier', 'tactics', v.side, 'fixtures']) = 'array'),
        f AS (
            SELECT b.packet_id, b.side, b.team, b.kickoff, b.as_of, b.blk,
                   CASE WHEN (x #>> '{{}}') ~ '^[0-9]{{1,15}}$' THEN (x #>> '{{}}')::bigint END AS fid
              FROM b CROSS JOIN LATERAL jsonb_array_elements(b.blk -> 'fixtures') AS x),
        e AS (
            SELECT b.packet_id, b.side, b.team,
                   CASE WHEN (x #>> '{{}}') ~ '^[0-9]{{1,15}}$' THEN (x #>> '{{}}')::bigint END AS fid
              FROM b CROSS JOIN LATERAL jsonb_array_elements(
                       CASE WHEN jsonb_typeof(b.blk #> '{{read,events}}') = 'array' THEN b.blk #> '{{read,events}}'
                            ELSE '[]'::jsonb END) AS x),
        s AS (
            SELECT e.packet_id, e.side,
                   sum(CASE WHEN g.home_team_id = e.team THEN r.reg_goals_home ELSE r.reg_goals_away END) AS gf,
                   sum(CASE WHEN g.home_team_id = e.team THEN r.reg_goals_away ELSE r.reg_goals_home END) AS ga
              FROM e JOIN core.fixtures g ON g.id = e.fid JOIN core.fixture_results r ON r.fixture_id = g.id GROUP BY 1, 2),
        c AS (
            SELECT f.packet_id,
                   (g.id IS NULL OR f.team IS NULL OR NOT (g.home_team_id = f.team OR g.away_team_id = f.team)
                    OR g.kickoff_at >= f.kickoff OR g.kickoff_at < f.kickoff - interval '{tactics.WINDOW.days} days'
                    OR r.settled_at IS NULL OR r.settled_at > f.as_of
                    OR (COALESCE((f.blk #> '{{read,events}}') @> to_jsonb(f.fid), false)
                        AND NOT EXISTS (SELECT 1 FROM core.fixture_events ev
                                         WHERE ev.fixture_id = f.fid AND ev.fetched_at <= f.as_of))
                    OR (COALESCE((f.blk #> '{{read,sheets}}') @> to_jsonb(f.fid), false)
                        AND NOT EXISTS (SELECT 1 FROM core.fixture_lineups l
                                         WHERE l.fixture_id = f.fid AND l.fetched_at <= f.as_of
                                           AND l.team_side = CASE WHEN g.home_team_id = f.team THEN 'home' ELSE 'away' END))) AS bad
              FROM f LEFT JOIN core.fixtures g ON g.id = f.fid LEFT JOIN core.fixture_results r ON r.fixture_id = f.fid
            UNION ALL
            SELECT b.packet_id,
                   (b.team IS NULL OR jsonb_array_length(b.blk -> 'fixtures') > {tactics.N}
                    OR {_int("b.blk", "{n}")} IS DISTINCT FROM jsonb_array_length(b.blk -> 'fixtures')
                    OR NOT COALESCE((b.blk -> 'fixtures') @> COALESCE(b.blk #> '{{read,events}}', '[]'::jsonb)
                                    AND (b.blk -> 'fixtures') @> COALESCE(b.blk #> '{{read,sheets}}', '[]'::jsonb), false)
                    OR COALESCE({_int("b.blk", "{goals,total_for}")}, 0)
                         IS DISTINCT FROM COALESCE((SELECT s.gf FROM s WHERE s.packet_id = b.packet_id AND s.side = b.side), 0)
                    OR COALESCE({_int("b.blk", "{goals,total_against}")}, 0)
                         IS DISTINCT FROM COALESCE((SELECT s.ga FROM s WHERE s.packet_id = b.packet_id AND s.side = b.side), 0)
                    OR COALESCE({_int("b.blk", "{with_the_score,half_time,n}")}, 0)
                         IS DISTINCT FROM (SELECT count(*) FROM f JOIN core.fixture_results r ON r.fixture_id = f.fid
                                            WHERE f.packet_id = b.packet_id AND f.side = b.side
                                              AND r.ht_goals_home IS NOT NULL AND r.ht_goals_away IS NOT NULL)) AS bad
              FROM b
            UNION ALL
            SELECT b.packet_id,
                   EXISTS (SELECT 1 FROM core.fixtures g JOIN core.fixture_results r ON r.fixture_id = g.id
                            WHERE (g.home_team_id = b.team OR g.away_team_id = b.team) AND g.kickoff_at < b.kickoff
                              AND g.kickoff_at >= b.kickoff - interval '{tactics.WINDOW.days} days' AND r.settled_at <= b.as_of
                              AND NOT EXISTS (SELECT 1 FROM f WHERE f.packet_id = b.packet_id AND f.side = b.side AND f.fid = g.id)
                              AND (jsonb_array_length(b.blk -> 'fixtures') < {tactics.N}
                                   OR g.kickoff_at > (SELECT min(g2.kickoff_at) FROM f JOIN core.fixtures g2 ON g2.id = f.fid
                                                       WHERE f.packet_id = b.packet_id AND f.side = b.side))) AS bad
              FROM b)
        SELECT count(*) AS n, count(*) FILTER (WHERE c.bad) AS bad,
               (array_agg(DISTINCT c.packet_id) FILTER (WHERE c.bad))[1:5] AS examples FROM c"""
