#!/usr/bin/env bash
# usage: day_digest.sh [--rows] <cutoff, ISO timestamp>   READ ONLY (a read-only session with a time limit).
# Plan UX, section 4 and 45: "picks y decisiones del día idénticos antes y después" of every deploy. Prints one line:
#   picks <n> <md5> | decisions <n> <md5>
# With --rows it prints instead one line per row, "pick <id> <md5 of its fields>" / "decision <id> <md5 of its fields>": step_deploy.sh keeps them
# before and step_verify.sh uses them only when the two lines above differ, to tell a row that CHANGED (or went) from a row that was ADDED by a
# writer that had started before the cutoff and committed after the first read (pick_pipeline stamps its picks with the moment it STARTS and a run
# takes 7 to 15 minutes; on 27-oct-2026 one of 14 minutes added 37 picks to a digest of 147 that the ten-minute margin had not covered).
# over the rows of picks.picks and intel.decisions created since the start of the product day (Bogotá) and BEFORE the cutoff, by their
# fields that never change once written (a pick's qualification status may move during the deploy and is left out). The same cutoff
# read before and after the deploy must print the same line: the deploy did not alter what the intelligence had already decided.
set -uo pipefail
ROWS=0
if [ "${1:-}" = "--rows" ]; then ROWS=1; shift; fi
CUTOFF=${1:?cutoff}
if [ "$ROWS" = 1 ]; then
  docker exec -e PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=120000' predigol-postgres psql -U fbi -d fbi -At -F ' ' -v ON_ERROR_STOP=1 -c "
WITH day AS (SELECT (date_trunc('day', timestamptz '$CUTOFF' AT TIME ZONE 'America/Bogota') AT TIME ZONE 'America/Bogota') AS start)
SELECT 'pick', id, md5(concat_ws('|', id, fixture_id, market_key, selection, line, model_version_id, market_odds, p_calibrated, edge, ev, stake_units, created_at))
  FROM picks.picks, day WHERE created_at >= day.start AND created_at < timestamptz '$CUTOFF'
UNION ALL
SELECT 'decision', id, md5(concat_ws('|', id, fixture_id, market_key, selection, line, state, input_hash, created_at))
  FROM intel.decisions, day WHERE created_at >= day.start AND created_at < timestamptz '$CUTOFF'
ORDER BY 1, 2" < /dev/null
  exit
fi
docker exec -e PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=120000' predigol-postgres psql -U fbi -d fbi -At -F ' ' -v ON_ERROR_STOP=1 -c "
WITH day AS (SELECT (date_trunc('day', timestamptz '$CUTOFF' AT TIME ZONE 'America/Bogota') AT TIME ZONE 'America/Bogota') AS start),
p AS (SELECT count(*) AS n, coalesce(md5(string_agg(concat_ws('|', id, fixture_id, market_key, selection, line, model_version_id, market_odds,
                                                        p_calibrated, edge, ev, stake_units, created_at), E'\n' ORDER BY id)), '-') AS h
        FROM picks.picks, day WHERE created_at >= day.start AND created_at < timestamptz '$CUTOFF'),
d AS (SELECT count(*) AS n, coalesce(md5(string_agg(concat_ws('|', id, fixture_id, market_key, selection, line, state, input_hash, created_at),
                                                    E'\n' ORDER BY id)), '-') AS h
        FROM intel.decisions, day WHERE created_at >= day.start AND created_at < timestamptz '$CUTOFF')
SELECT 'picks', p.n, p.h, '| decisions', d.n, d.h FROM p, d" < /dev/null
