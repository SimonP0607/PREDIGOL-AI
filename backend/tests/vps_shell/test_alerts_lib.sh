#!/usr/bin/env bash
# Tests of alerts_lib.sh with a fake channel. No network, no Docker, no production. usage: tests/vps_shell/test_alerts_lib.sh
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$(cd "$HERE/../../deploy/vps/bin" && pwd)   # the scripts under test: backend/deploy/vps/bin
PASS=0; FAIL=0
ok() { PASS=$((PASS + 1)); echo "ok   $*"; }
no() { FAIL=$((FAIL + 1)); echo "FAIL $*"; }
eq() { if [[ "$1" == "$2" ]]; then ok "$3"; else no "$3: got '$1', expected '$2'"; fi; }

T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
STATE="$T/state"; mkdir -p "$STATE"
log() { :; }
notify_ok() { if [[ -e "$T/fail" ]]; then return 1; fi; printf '%s\n' "$*" >> "$T/sent"; return 0; }
# shellcheck source=../../deploy/vps/bin/alerts_lib.sh
. "$SRC/alerts_lib.sh"

sent() { [[ -f "$T/sent" ]] && wc -l < "$T/sent" | tr -d ' ' || echo 0; }
lastmsg() { tail -n 1 "$T/sent"; }
run() { # run <epoch> [key sev text]...  one pass of a checker
  local now=$1; shift
  export ALERTS_NOW=$now
  alerts_begin
  while (( $# >= 3 )); do alert_set "$1" "$2" "$3"; shift 3; done
  alerts_end
}
t0=$(date -u -d '2026-10-25 20:00:00' +%s)
Y=2026

# 1. open
run "$t0" disk.usage SEV2 "disco al 82 %"
eq "$(sent)" 1 "1 one message when an alert opens"
eq "$(lastmsg)" "[SEV2] disk.usage: disco al 82 % (INC-$Y-001)" "1 message text and incident id"
eq "$(jq -r '."disk.usage".last_sent' "$STATE/alerts.json")" "$t0" "1 last_sent recorded"
eq "$(wc -l < "$STATE/incidents.jsonl" | tr -d ' ')" 1 "1 one register line"
eq "$(jq -r '.event + " " + .incident + " " + .service + " " + .severity' "$STATE/incidents.jsonl")" "open INC-$Y-001 disk SEV2" "1 register fields"

# 2. no change: silence
run $((t0 + 300)) disk.usage SEV2 "disco al 83 %"
run $((t0 + 600)) disk.usage SEV2 "disco al 83 %"
eq "$(sent)" 1 "2 no message while nothing changes (SEV2 is not reminded)"
eq "$(jq -r '."disk.usage".text' "$STATE/alerts.json")" "disco al 83 %" "2 the state keeps the newest text"
eq "$(jq -r '."disk.usage".since' "$STATE/alerts.json")" "2026-10-25T20:00:00Z" "2 since does not move"

# 3. close
run $((t0 + 1800))
eq "$(sent)" 2 "3 one message when it recovers"
eq "$(lastmsg)" "[recuperado] disk.usage tras 30 min (INC-$Y-001)" "3 recovery text"
eq "$(jq -c 'keys' "$STATE/alerts.json")" "[]" "3 state empty again"
eq "$(tail -n 1 "$STATE/incidents.jsonl" | jq -r '.event + " " + (.minutes | tostring)')" "close 30" "3 close event with minutes"

# 4. SEV1: reminded every hour, not before
n0=$(sent)
run $((t0 + 4000)) web.health SEV1 "no responde"
eq "$(sent)" $((n0 + 1)) "4 SEV1 opens"
eq "$(lastmsg)" "[SEV1] web.health: no responde (INC-$Y-002)" "4 second incident id"
run $((t0 + 4000 + 3599)) web.health SEV1 "no responde"
eq "$(sent)" $((n0 + 1)) "4 no reminder before one hour"
run $((t0 + 4000 + 3600)) web.health SEV1 "no responde"
eq "$(sent)" $((n0 + 2)) "4 reminder after one hour"
case "$(lastmsg)" in "[SEV1 sigue abierto desde las 21:06 UTC] web.health: no responde (INC-$Y-002)") ok "4 reminder text" ;; *) no "4 reminder text: $(lastmsg)" ;; esac
run $((t0 + 4000 + 3600 + 100)) web.health SEV1 "no responde"
eq "$(sent)" $((n0 + 2)) "4 not again right away"
run $((t0 + 4000 + 7200)) web.health SEV1 "no responde"
eq "$(sent)" $((n0 + 3)) "4 reminder again after another hour"

# 5. severity change
run $((t0 + 20000)) web.health SEV2 "responde lento"
case "$(lastmsg)" in "[SEV2] web.health: responde lento (antes SEV1; INC-$Y-002)") ok "5 severity change message" ;; *) no "5 severity change: $(lastmsg)" ;; esac
eq "$(tail -n 1 "$STATE/incidents.jsonl" | jq -r .event)" update "5 update event"
eq "$(jq -r '."web.health".incident' "$STATE/alerts.json")" "INC-$Y-002" "5 same incident"
run $((t0 + 20300))

# 6. channel down: the open message is retried
touch "$T/fail"
n=$(sent)
run $((t0 + 30000)) backup.local SEV2 "copia vieja"
eq "$(sent)" "$n" "6 nothing reached the channel"
eq "$(jq -r '."backup.local".last_sent' "$STATE/alerts.json")" 0 "6 last_sent stays 0"
run $((t0 + 30300)) backup.local SEV2 "copia vieja"
eq "$(sent)" "$n" "6 still down: nothing"
rm -f "$T/fail"
run $((t0 + 30600)) backup.local SEV2 "copia vieja"
eq "$(sent)" $((n + 1)) "6 the open message is retried once the channel is back"
run $((t0 + 30900)) backup.local SEV2 "copia vieja"
eq "$(sent)" $((n + 1)) "6 and only once"
eq "$(grep -c '"event":"open"' "$STATE/incidents.jsonl")" 3 "6 the register opened it once, not on every retry"
run $((t0 + 31200))

# 7. bad key / bad severity are refused
n=$(sent)
run $((t0 + 40000)) "Bad Key" SEV1 "x" good.key SEV9 "y" nodot SEV1 "z"
eq "$(sent)" "$n" "7 invalid keys and severities open nothing"
eq "$(jq -c 'keys' "$STATE/alerts.json")" "[]" "7 state stays empty"

# 8. the same key twice in a run: the more severe wins
run $((t0 + 41000)) api.errors SEV3 "uno" api.errors SEV1 "dos" api.errors SEV2 "tres"
eq "$(jq -r '."api.errors".sev + " " + ."api.errors".text' "$STATE/alerts.json")" "SEV1 dos" "8 the most severe wins"
run $((t0 + 41300))

# 9. several alerts in one run, one message each; closing one keeps the other
n=$(sent)
run $((t0 + 42000)) a.one SEV2 "uno" b.two SEV3 "dos"
eq "$(sent)" $((n + 2)) "9 two alerts, two messages"
run $((t0 + 42300)) a.one SEV2 "uno"
eq "$(sent)" $((n + 3)) "9 closing one sends one message"
eq "$(jq -c 'keys' "$STATE/alerts.json")" '["a.one"]' "9 the other stays open"
run $((t0 + 42600))

# 10. new year restarts the sequence
t1=$(date -u -d '2027-01-02 20:00:00' +%s)
run "$t1" db.conn SEV2 "conexiones"
case "$(lastmsg)" in "[SEV2] db.conn: conexiones (INC-2027-001)") ok "10 sequence restarts in January" ;; *) no "10 new year: $(lastmsg)" ;; esac
run $((t1 + 300))

# 11. a corrupt alerts.json is treated as empty (no crash)
echo '{not json' > "$STATE/alerts.json"
run $((t1 + 600)) c.d SEV3 "texto"
eq "$(jq -r 'keys[0]' "$STATE/alerts.json")" "c.d" "11 corrupt state does not stop the checker"
run $((t1 + 900))

# 12. a text with a newline is flattened to one line
n=$(sent)
run $((t1 + 1200)) e.f SEV2 $'dos\nlineas'
eq "$(lastmsg)" "[SEV2] e.f: dos lineas (INC-2027-003)" "12 one line"
run $((t1 + 1500))

# 13. dry run: prints, writes nothing
cp "$STATE/alerts.json" "$T/alerts.before"; cp "$STATE/incidents.jsonl" "$T/inc.before"; cp "$STATE/incident.seq" "$T/seq.before"; n=$(sent)
out=$(ALERTS_DRY_RUN=1 run $((t1 + 2000)) g.h SEV1 "prueba")
case "$out" in *"WOULD SEND: [SEV1] g.h: prueba"*) ok "13 dry run prints the message" ;; *) no "13 dry run output: $out" ;; esac
eq "$(sent)" "$n" "13 dry run sends nothing"
if cmp -s "$STATE/alerts.json" "$T/alerts.before" && cmp -s "$STATE/incidents.jsonl" "$T/inc.before" && cmp -s "$STATE/incident.seq" "$T/seq.before"; then ok "13 dry run writes nothing"; else no "13 dry run changed the state"; fi

# 14. two checkers share alerts.json: each one closes only its OWN alerts
rm -f "$STATE/alerts.json"; n=$(sent)
runo() { local owner=$1 now=$2; shift 2; export ALERTS_NOW=$now; alerts_begin "$owner"; while (( $# >= 3 )); do alert_set "$1" "$2" "$3"; shift 3; done; alerts_end; }
t2=$(date -u -d '2027-02-03 10:00:00' +%s)
runo main "$t2" web.health SEV1 "no responde"
runo security $((t2 + 300))
eq "$(sent)" $((n + 1)) "14 the other checker's quiet run does not close web.health"
eq "$(jq -r '."web.health".owner' "$STATE/alerts.json")" main "14 the owner is recorded"
runo security $((t2 + 600)) auth.bruteforce SEV2 "30 inicios fallidos"
eq "$(jq -c 'keys' "$STATE/alerts.json")" '["auth.bruteforce","web.health"]' "14 both stay open together"
runo main $((t2 + 900))
eq "$(lastmsg | cut -c1-35)" "[recuperado] web.health tras 15 min" "14 main closes its own"
eq "$(jq -c 'keys' "$STATE/alerts.json")" '["auth.bruteforce"]' "14 and security's stays open"
runo security $((t2 + 1200))
eq "$(jq -c 'keys' "$STATE/alerts.json")" '[]' "14 security closes its own"

# 15. alerts_hold: a pass that could not evaluate a check (the database did not answer) keeps its open alerts as they are
rm -f "$STATE/alerts.json"; n=$(sent)
runh() { local owner=$1 now=$2 holds=$3; shift 3; export ALERTS_NOW=$now; alerts_begin "$owner"; if [[ -n "$holds" ]]; then alerts_hold $holds; fi; while (( $# >= 3 )); do alert_set "$1" "$2" "$3"; shift 3; done; alerts_end; }
t3=$(date -u -d '2027-03-04 10:00:00' +%s)
runh main "$t3" "" ingest.runs SEV2 "25 ejecuciones fallidas" db.connections SEV2 "85 %"
eq "$(sent)" $((n + 2)) "15 two alerts open"
inc=$(jq -r '."ingest.runs".incident' "$STATE/alerts.json"); since=$(jq -r '."ingest.runs".since' "$STATE/alerts.json"); last=$(jq -r '."ingest.runs".last_sent' "$STATE/alerts.json")
closes=$(grep -c '"event":"close"' "$STATE/incidents.jsonl")
runh main $((t3 + 300)) "ingest.runs db.connections"
eq "$(sent)" $((n + 2)) "15 held: no message and no false recovery"
eq "$(jq -c 'keys' "$STATE/alerts.json")" '["db.connections","ingest.runs"]' "15 held: both still open"
eq "$(jq -r '."ingest.runs".incident + " " + ."ingest.runs".since + " " + (."ingest.runs".last_sent | tostring) + " " + ."ingest.runs".owner' "$STATE/alerts.json")" "$inc $since $last main" "15 held: incident, since, last_sent and owner untouched"
eq "$(grep -c '"event":"close"' "$STATE/incidents.jsonl")" "$closes" "15 held: no close event in the register"
runh main $((t3 + 600)) "ingest.runs"
eq "$(lastmsg | cut -c1-33)" "[recuperado] db.connections tras " "15 only the held key is spared: the other one closes"
eq "$(jq -c 'keys' "$STATE/alerts.json")" '["ingest.runs"]' "15 the held one stays"
runh main $((t3 + 900)) "ingest.runs" ingest.runs SEV1 "peor"
case "$(lastmsg)" in "[SEV1] ingest.runs: peor (antes SEV2; $inc)") ok "15 a held key that is also seen failing is treated as failing" ;; *) no "15 hold + set: $(lastmsg)" ;; esac
n2=$(sent)
runh main $((t3 + 1200)) "" ingest.runs SEV1 "peor"
eq "$(sent)" "$n2" "15 the database back and the problem still there: same incident, no new message"
eq "$(jq -r '."ingest.runs".incident' "$STATE/alerts.json")" "$inc" "15 same incident after the hold"
runh main $((t3 + 1500)) "nothing.here ingest.runs"
eq "$(jq -c 'keys' "$STATE/alerts.json")" '["ingest.runs"]' "15 holding a key that is not open creates nothing"
runo security $((t3 + 1800)) auth.bruteforce SEV2 "30 inicios fallidos"
runh main $((t3 + 2100)) "auth.bruteforce ingest.runs"
eq "$(jq -c 'keys' "$STATE/alerts.json")" '["auth.bruteforce","ingest.runs"]' "15 another checker's alert is left alone by a hold"
runo security $((t3 + 2400))
eq "$(jq -c 'keys' "$STATE/alerts.json")" '["ingest.runs"]' "15 and its own checker still closes it (a hold of another checker does not protect it)"
runh main $((t3 + 2700)) ""
eq "$(lastmsg | cut -c1-30)" "[recuperado] ingest.runs tras " "15 after the hold, a quiet pass closes normally"

# 16. a severity the owner chose (bin/incident.sh severity writes it with pinned = true): the check no longer changes it until the incident closes
t4=$(date -u -d '2026-10-26 09:00:00' +%s)
rm -f "$T/sent" "$STATE/incidents.jsonl" "$STATE/alerts.json" "$STATE/incident.seq"
run "$t4" cpu.high SEV2 "cpu al 90 %"
jq -c '.["cpu.high"].sev = "SEV1" | .["cpu.high"].pinned = true' "$STATE/alerts.json" > "$T/a.json" && mv "$T/a.json" "$STATE/alerts.json"
n=$(sent)
run $((t4 + 300)) cpu.high SEV2 "cpu al 91 %"
eq "$(sent)" "$n" "16 pinned: the check seeing SEV2 again announces no change"
eq "$(jq -r '.["cpu.high"].sev' "$STATE/alerts.json")" SEV1 "16 pinned: the severity in alerts.json stays the owner's"
eq "$(jq -r '.["cpu.high"].pinned' "$STATE/alerts.json")" true "16 pinned: and so does the flag"
eq "$(grep -c '"event":"update"' "$STATE/incidents.jsonl")" 0 "16 pinned: no update event"
run $((t4 + 3900)) cpu.high SEV2 "cpu al 92 %"
eq "$(lastmsg | cut -c1-24)" "[SEV1 sigue abierto desd" "16 pinned: the hourly reminder uses the owner's severity"
run $((t4 + 4200))
eq "$(grep '"event":"close"' "$STATE/incidents.jsonl" | tail -n 1 | jq -r .severity)" SEV1 "16 pinned: it closes with the owner's severity"
run $((t4 + 4500)) cpu.high SEV2 "cpu al 95 %"
eq "$(jq -r '.["cpu.high"] | has("pinned")' "$STATE/alerts.json")" false "16 a new incident of the same alert starts unpinned"
eq "$(jq -r '.["cpu.high"].sev' "$STATE/alerts.json")" SEV2 "16 and with the check's own severity"

# 17. a power cut half way through a register line: the next line must not be swallowed by the torn one, and the readers skip what is not JSON
t5=$(date -u -d '2026-10-26 10:00:00' +%s)
rm -f "$T/sent" "$STATE/incidents.jsonl" "$STATE/alerts.json" "$STATE/incident.seq"
run "$t5" web.health SEV1 "la web no responde"
printf '{"at":"2026-10-26T10:05:00Z","event":"note","incident":"INC-2026-0' >> "$STATE/incidents.jsonl"   # the torn line: no newline at the end
run $((t5 + 300)) web.health SEV1 "la web no responde" ingest.live SEV2 "sin capturas"
eq "$(wc -l < "$STATE/incidents.jsonl" | tr -d ' ')" 3 "17 torn: the new line went to a line of its own (open, torn, open)"
eq "$(incident_lines | wc -l | tr -d ' ')" 2 "17 torn: the reader gives the two valid lines and skips the torn one"
eq "$(incident_lines | jq -r '.key' | paste -sd, -)" "web.health,ingest.live" "17 torn: both are readable"
printf 'esto no es json\n[1,2]\n"texto"\n' >> "$STATE/incidents.jsonl"
eq "$(incident_lines | wc -l | tr -d ' ')" 2 "17 junk: lines that are not JSON objects are skipped (text, an array, a string)"
run $((t5 + 600)) web.health SEV1 "la web no responde"
eq "$(incident_lines | jq -r 'select(.event == "close") | .key')" "ingest.live" "17 and the register goes on being written after the junk"
rm -f "$STATE/incidents.jsonl"; eq "$(incident_lines | wc -l | tr -d ' ')" 0 "17 no file: nothing, no error"
: > "$STATE/incidents.jsonl"; _incident_append '{"a":1}'
eq "$(cat "$STATE/incidents.jsonl")" '{"a":1}' "17 an empty file gets no blank line before the first one"

echo; echo "RESULT: $PASS ok, $FAIL failed"
exit $(( FAIL > 0 ))
