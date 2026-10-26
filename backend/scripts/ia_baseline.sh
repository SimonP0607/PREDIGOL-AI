#!/usr/bin/env bash
# PrediGol Intelligence - Plan Maestro IA, Phase 0: runs the READ ONLY baseline (ia_baseline.sql) on the production server.
#
#   bash ia_baseline.sh [output-file]
#
# It must be run ON the server, next to ia_baseline.sql. The session is read-only (default_transaction_read_only=on, which
# also makes the script's own BEGIN READ ONLY redundant on purpose), has a statement time limit and cannot sit idle in a
# transaction. It connects as the database owner (fbi): the baseline does not need the superuser. The output is a text
# file of "### section" lines each followed by a CSV table; the sha256 of the file is printed so the report can name it.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${1:-$HERE/baseline_$(date -u +%Y%m%dT%H%MZ).txt}"
SQL="$HERE/ia_baseline.sql"
[ -r "$SQL" ] || { echo "ia_baseline.sql not found next to this script" >&2; exit 2; }
PGRO='-c default_transaction_read_only=on -c statement_timeout=90000 -c idle_in_transaction_session_timeout=120000'
{
  echo "### run"
  echo "started_utc,host"
  echo "$(date -u +%FT%TZ),$(hostname)"
  docker exec -i -e PGOPTIONS="$PGRO" predigol-postgres psql --csv -U fbi -d fbi < "$SQL" 2>&1
} > "$OUT"
rc=$?
echo "output: $OUT"
echo "bytes:  $(wc -c < "$OUT")"
echo "sha256: $(sha256sum "$OUT" | cut -d' ' -f1)"
echo "sections: $(grep -c '^### ' "$OUT")  psql errors: $(grep -ci 'ERROR:' "$OUT")"
exit $rc
