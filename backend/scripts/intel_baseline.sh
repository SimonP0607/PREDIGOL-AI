#!/usr/bin/env bash
# PrediGol Intelligence - Plan Maestro RP, RP-0.1: runs the READ ONLY baseline of 22 indicators on the production server.
#
#   bash intel_baseline.sh [cut-utc] [output-file]
#
# cut-utc  the freeze moment, e.g. 2026-11-26T03:15:00Z (default: now). Every figure is bounded by it, so a second run with the
#          same cut gives the same hash (except the sections marked live).
# It must be run ON the server, next to intel_baseline.sql. The session is read-only (default_transaction_read_only=on), has a
# statement time limit and cannot sit idle in a transaction. The output is a file of "### section" lines each followed by a CSV
# table; scripts/intel_baseline_report.py turns it into docs/intelligence/baseline/baseline-v1.json.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CUT="${1:-$(date -u +%FT%TZ)}"
OUT="${2:-$HERE/intel_baseline_$(date -u +%Y%m%dT%H%MZ).txt}"
SQL="$HERE/intel_baseline.sql"
BASE_BEFORE="${BASE_BEFORE:-2026-11-24T00:00:00Z}"
[ -r "$SQL" ] || { echo "intel_baseline.sql not found next to this script" >&2; exit 2; }
PGRO='-c default_transaction_read_only=on -c statement_timeout=150000 -c idle_in_transaction_session_timeout=180000'
{
  echo "### run"
  echo "started_utc,host,cut_utc,base_before_utc"
  echo "$(date -u +%FT%TZ),$(hostname),$CUT,$BASE_BEFORE"
  docker exec -i -e PGOPTIONS="$PGRO" predigol-postgres psql --csv -U fbi -d fbi \
    -v "cut='$CUT'" -v "base_before='$BASE_BEFORE'" < "$SQL" 2>&1
} > "$OUT"
rc=$?
echo "output: $OUT"
echo "bytes:  $(wc -c < "$OUT")"
echo "sha256: $(sha256sum "$OUT" | cut -d' ' -f1)"
echo "sections: $(grep -c '^### ' "$OUT")  psql errors: $(grep -ci 'ERROR:' "$OUT")"
exit $rc
