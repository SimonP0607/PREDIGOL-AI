#!/usr/bin/env bash
# Every Monday (predigol-weekly-summary.timer): ONE message with the last 7 days: incidents by severity, the longest one, what is open now, and the
# three numbers that decide whether the week was calm (disk, local backup age, certificate days). Counts and ids only.
#
#   bin/weekly-summary.sh [--dry-run]      --dry-run prints the message and sends nothing
set -Euo pipefail
HERE="$(dirname "$0")"
# shellcheck source=bin/lib.sh
. "$HERE/lib.sh"

DRY=0; [[ "${1:-}" == "--dry-run" ]] && DRY=1
NOW=${SUMMARY_NOW:-$(date +%s)}
since="$(date -u -d "@$(( NOW - 7 * 86400 ))" +%FT%TZ)"
inc="$STATE/incidents.jsonl"

# the valid lines of the register: a torn or hand-edited line is skipped, it must not turn the week into "0 incidents"
lines() { [[ -r "$inc" ]] && jq -cR 'fromjson? | select(type == "object")' "$inc" 2> /dev/null; return 0; }
count() { lines | jq -rs --arg s "$since" --arg sev "$1" '[.[] | select(.event == "open" and .at >= $s and .severity == $sev)] | length' 2> /dev/null || echo 0; }
sev1="$(count SEV1)"; sev2="$(count SEV2)"; sev3="$(count SEV3)"
closed="$(lines | jq -rs --arg s "$since" '[.[] | select(.event == "close" and .at >= $s)] | length' 2> /dev/null || echo 0)"
longest="$(lines | jq -rs --arg s "$since" '[.[] | select(.event == "close" and .at >= $s)] | max_by(.minutes) | if . == null then "ninguno" else "\(.key) \(.minutes) min (\(.incident))" end' 2> /dev/null || echo ninguno)"
open_now="$(jq -r 'length' "$STATE/alerts.json" 2> /dev/null || echo 0)"
disk="$(df -P "${PREDIGOL_DATA:-/}" | awk 'NR==2 {gsub("%",""); print $5}')"
newest="$(find "${DB_BACKUPS:-/nonexistent}" -maxdepth 1 -name 'predigol-*.json' -printf '%T@\n' 2> /dev/null | sort -nr | head -n 1)"
if [[ -n "$newest" ]]; then backup="hace $(( (NOW - ${newest%.*}) / 3600 )) h"; else backup="sin copia"; fi
msg="Resumen semanal (7 días): incidentes abiertos SEV1 $sev1, SEV2 $sev2, SEV3 $sev3; cerrados $closed; el más largo: $longest; abiertos ahora: $open_now. Disco al ${disk} %, última copia local $backup."
if (( DRY )); then echo "WOULD SEND: $msg"; else notify "$msg"; fi
