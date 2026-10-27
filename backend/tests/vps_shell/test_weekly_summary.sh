#!/usr/bin/env bash
# Test of weekly-summary.sh with a fake lib.sh and an incident register. No network, no Docker, no production.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$(cd "$HERE/../../deploy/vps/bin" && pwd)   # the scripts under test: backend/deploy/vps/bin
PASS=0; FAIL=0
ok() { PASS=$((PASS + 1)); echo "ok   $*"; }
no() { FAIL=$((FAIL + 1)); echo "FAIL $*"; }
eq() { if [[ "$1" == "$2" ]]; then ok "$3"; else no "$3: got '$1', expected '$2'"; fi; }
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin" "$T/state" "$T/backups"
cp "$SRC/weekly-summary.sh" "$T/bin/"
cat > "$T/bin/lib.sh" <<LIB
STATE="$T/state"; PREDIGOL_DATA="$T"; DB_BACKUPS="$T/backups"
notify() { printf '%s\n' "\$*" >> "$T/sent"; }
LIB
NOW=$(date -u -d '2026-10-26 08:00:00' +%s)
ev() { jq -cn --arg at "$1" --arg e "$2" --arg i "$3" --arg k "$4" --arg s "$5" --argjson m "${6:-null}" '{at:$at,event:$e,incident:$i,key:$k,service:($k|split(".")[0]),severity:$s,text:"x"} + (if $m == null then {} else {minutes:$m} end)'; }
{
  ev 2026-10-17T10:00:00Z open INC-2026-001 old.one SEV1          # older than 7 days: not counted
  ev 2026-10-20T10:00:00Z open INC-2026-002 disk.usage SEV2
  ev 2026-10-20T12:00:00Z close INC-2026-002 disk.usage SEV2 120
  ev 2026-10-22T10:00:00Z open INC-2026-003 web.health SEV1
  ev 2026-10-22T10:30:00Z close INC-2026-003 web.health SEV1 30
  ev 2026-10-24T10:00:00Z open INC-2026-004 auth.locked SEV3
  ev 2026-10-25T10:00:00Z open INC-2026-005 backup.local SEV2
} > "$T/state/incidents.jsonl"
echo '{"backup.local":{"sev":"SEV2"}}' > "$T/state/alerts.json"
echo '{}' > "$T/backups/predigol-x.json"; touch -d '@'"$((NOW - 5 * 3600))" "$T/backups/predigol-x.json"
out="$(SUMMARY_NOW=$NOW "$T/bin/weekly-summary.sh" --dry-run)"
case "$out" in *"SEV1 1, SEV2 2, SEV3 1"*) ok "counts by severity (the old incident is left out)" ;; *) no "counts: $out" ;; esac
case "$out" in *"cerrados 2"*) ok "closed count" ;; *) no "closed: $out" ;; esac
case "$out" in *"el más largo: disk.usage 120 min (INC-2026-002)"*) ok "longest incident" ;; *) no "longest: $out" ;; esac
case "$out" in *"abiertos ahora: 1"*) ok "open now" ;; *) no "open now: $out" ;; esac
case "$out" in *"última copia local hace 5 h"*) ok "backup age" ;; *) no "backup: $out" ;; esac
if [[ -e "$T/sent" ]]; then no "dry run sent something"; else ok "dry run sends nothing"; fi
SUMMARY_NOW=$NOW "$T/bin/weekly-summary.sh" > /dev/null
eq "$(wc -l < "$T/sent" | tr -d ' ')" 1 "a real run sends exactly one message"
# a torn last line (power cut) and junk in the register must not turn the week into "0 incidents"
cp "$T/state/incidents.jsonl" "$T/register.good"
printf 'basura que no es json\n[1,2]\n' >> "$T/state/incidents.jsonl"; printf '{"at":"2026-10-25T11:00:00Z","event":"op' >> "$T/state/incidents.jsonl"
out="$(SUMMARY_NOW=$NOW "$T/bin/weekly-summary.sh" --dry-run)"
case "$out" in *"SEV1 1, SEV2 2, SEV3 1"*"cerrados 2"*"el más largo: disk.usage 120 min"*) ok "junk and a torn line in the register: the counts are the same" ;; *) no "junk: $out" ;; esac
rm -f "$T/state/incidents.jsonl" "$T/sent"
out="$(SUMMARY_NOW=$NOW "$T/bin/weekly-summary.sh" --dry-run)"
case "$out" in *"SEV1 0, SEV2 0, SEV3 0"*"el más largo: ninguno"*) ok "quiet week without a register" ;; *) no "quiet week: $out" ;; esac
echo; echo "RESULT: $PASS ok, $FAIL failed"; exit $(( FAIL > 0 ))
