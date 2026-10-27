#!/usr/bin/env bash
# Tests of incident.sh, the owner's pen (security plan S3): no database, no network, no Docker, nothing of production. The mirror of the register
# into audit.incident_events (incident-dump.sh) is tested in tests/integration/test_incident_dump.py.   usage: tests/vps_shell/test_incident_pen.sh
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$(cd "$HERE/../../deploy/vps/bin" && pwd)   # the scripts under test: backend/deploy/vps/bin
PASS=0; FAIL=0
ok() { PASS=$((PASS + 1)); echo "ok   $*"; }
no() { FAIL=$((FAIL + 1)); echo "FAIL $*"; }
eq() { if [[ "$1" == "$2" ]]; then ok "$3"; else no "$3: got '$1', expected '$2'"; fi; }
has() { case "$1" in *"$2"*) ok "$3" ;; *) no "$3: '$2' not in '${1:0:300}'" ;; esac; }
hasnt() { case "$1" in *"$2"*) no "$3: '$2' is in '${1:0:300}'" ;; *) ok "$3" ;; esac; }
T=$(mktemp -d)
# shellcheck disable=SC2329  # (run by the trap)
cleanup() {
  if [[ -n "${KEEP_T:-}" ]]; then echo "(KEEP_T set: the files of the test stay in $T)"; else rm -rf "$T"; fi
}
trap cleanup EXIT

# ---- the host: a fake lib.sh (STATE, log, a channel that writes down what it is given), the real alerts_lib.sh and the two scripts
mkdir -p "$T/bin" "$T/state"
cp "$SRC/alerts_lib.sh" "$SRC/incident.sh" "$SRC/incident-dump.sh" "$T/bin/"
cat > "$T/bin/lib.sh" <<LIB
STATE="$T/state"; PREDIGOL_DATA="$T"
log() { printf '%s\n' "\$*" >> "$T/log"; }
notify_ok() { printf '%s\n' "\$*" >> "$T/sent"; return 0; }
LIB
S="$T/state"; FILE="$S/incidents.jsonl"
export INCIDENT_NO_DUMP=1
now=$(date -u -d '2026-10-26 16:00:00' +%s)
inc() { INCIDENT_NOW=$now "$T/bin/incident.sh" "$@" 2>&1; }            # the output (stdout and stderr) of one command
incs() { INCIDENT_NOW=$now "$T/bin/incident.sh" "$@" > /dev/null 2>&1; echo $?; }   # its exit status
sent_n() { [[ -f "$T/sent" ]] && wc -l < "$T/sent" | tr -d ' ' || echo 0; }
last_sent() { tail -n 1 "$T/sent"; }
nlines() { [[ -f "$FILE" ]] && wc -l < "$FILE" | tr -d ' ' || echo 0; }

echo "== A. the owner's pen"
out="$(inc open web SEV1 "la web no responde desde fuera" --at 2026-10-26T15:02Z)"
has "$out" "Abierto INC-2026-001 (SEV1, web)" "A1 a manual incident gets the next number"
eq "$(nlines)" 1 "A1 one line in the register"
eq "$(jq -r '[.event, .incident, .key, .service, .severity, .actor, .at] | join(" ")' "$FILE")" "open INC-2026-001 manual.web web SEV1 owner 2026-10-26T15:02:00Z" "A1 the line has what the checks' lines have, plus the actor and the time given"
has "$(last_sent)" "[SEV1] manual.web: la web no responde desde fuera (INC-2026-001; abierto a mano por el dueño)" "A1 the message goes to the channel"
has "$(inc list)" "INC-2026-001  SEV1  ABIERTO  desde 2026-10-26T15:02:00Z  manual.web" "A2 list shows it open"

echo "-- refusals (nothing is written)"
n=$(nlines)
eq "$(incs open web SEV1 "escribí a ana@example.com")" 2 "A3 an e-mail address is refused"
eq "$(incs open web SEV1 "clave 0123456789abcdef0123456789abcdef0123")" 2 "A3 a long token-like string is refused"
eq "$(incs open web SEV1 "password=hola")" 2 "A3 'password=' is refused"
eq "$(incs open web SEV1 "contraseña: algo")" 2 "A3 'contraseña:' is refused"
eq "$(incs open web SEV1 "postgres://u:p@host/db")" 2 "A3 an address with user and password is refused"
eq "$(incs open web SEV1 "$(printf 'a\nb')")" 2 "A3 two lines are refused"
eq "$(incs open web SEV1 "$(head -c 1600 /dev/zero | tr '\0' 'x' | sed 's/xxxxxxxxxx/xxxx xxxxx /g')")" 2 "A3 more than 1500 characters is refused"
eq "$(incs open web SEV1 "")" 2 "A3 an empty text is refused"
eq "$(incs open nginx SEV1 "x")" 2 "A4 a service that is not on the list is refused"
eq "$(incs open web SEV9 "x")" 2 "A4 a severity that does not exist is refused"
eq "$(incs open web SEV1 "x" --at 2026-10-26)" 2 "A4 a malformed --at is refused"
eq "$(incs open web SEV1 "x" --at 2026-10-27T15:02Z)" 2 "A4 an --at in the future is refused"
eq "$(incs note INC-2026-099 cause "x")" 2 "A4 a note on an unknown incident is refused"
eq "$(incs note INC-26-1 cause "x")" 2 "A4 a malformed number is refused"
eq "$(incs note INC-2026-001 nickname "x")" 2 "A4 a field that does not exist is refused"
eq "$(incs note INC-2026-001 affected_users "Ana, Luis")" 2 "A4 users as names are refused: a number only"
eq "$(incs note INC-2026-001 personal_data "quizás")" 2 "A4 personal_data must start with si or no"
eq "$(nlines)" "$n" "A4 not one line was written by all of them"
hasnt "$(cat "$T/sent")" "ana@example.com" "A4 nothing refused reached the channel"

echo "-- notes"
has "$(inc note INC-2026-001 cause "el proceso de Caddy se quedó sin memoria")" "Anotado en INC-2026-001: cause" "A5 a note"
inc note INC-2026-001 cause "falta de memoria del servidor por un pico de peticiones" > /dev/null
inc note INC-2026-001 affected_users 12 > /dev/null
eq "$(jq -r 'select(.field == "affected_users") | .value' "$FILE")" 12 "A5 users as a number"
out="$(inc note INC-2026-001 personal_data "si: correos de 12 titulares")"
has "$out" "Llama a tu abogado hoy" "A6 a yes on personal data says what comes next"
has "$(last_sent)" "[datos personales] INC-2026-001" "A6 and tells the channel"
show="$(inc show INC-2026-001)"
has "$show" "open    owner  SEV1  la web no responde desde fuera" "A7 show: the opening"
has "$show" "cause: falta de memoria del servidor por un pico de peticiones" "A7 show: the newest note of a field"
current="${show#*$'\n'---$'\n'}"   # (the part after the history: the current notes)
has "$show" "cause: el proceso de Caddy" "A7 show: the history keeps the older note"
hasnt "$current" "cause: el proceso de Caddy" "A7 show: the older note of the same field is not in the current notes"
has "$current" "cause: falta de memoria del servidor por un pico de peticiones" "A7 and the newest one is"
eq "$(jq -r 'select(.event == "note") | .severity' "$FILE" | sort -u)" SEV1 "A7 a note carries the severity of the moment"

echo "-- severity"
n=$(sent_n)
has "$(inc severity INC-2026-001 SEV2 "ya funciona desde dentro")" "pasa de SEV1 a SEV2" "A8 the owner changes the severity"
eq "$(sent_n)" $((n + 1)) "A8 and it is announced"
eq "$(jq -r 'select(.event == "update") | [.severity, .actor] | join(" ")' "$FILE")" "SEV2 owner" "A8 the line"
eq "$(incs severity INC-2026-001 SEV2)" 2 "A8 the same severity again is refused"
eq "$(incs severity INC-2026-001 SEV2 "x")" 2 "A8 (still)"

echo "-- an automatic incident (opened by a check), the owner's severity and its closing"
cat > "$T/auto.sh" <<AUTO
set -u
. "$T/bin/lib.sh"; . "$T/bin/alerts_lib.sh"
export ALERTS_NOW=\$1
alerts_begin; if [[ \$# -ge 2 ]]; then alert_set disk.usage SEV2 "\$2"; fi; alerts_end
AUTO
bash "$T/auto.sh" "$(date -u -d '2026-10-26 15:30:00' +%s)" "disco al 82 %"
eq "$(jq -r '.["disk.usage"].incident' "$S/alerts.json")" INC-2026-002 "A9 the check's incident takes the next number of the same sequence"
has "$(inc severity INC-2026-002 SEV1 "el disco crece rápido")" "pasa de SEV2 a SEV1" "A9 the owner raises it"
eq "$(jq -r '.["disk.usage"] | [.sev, .pinned] | map(tostring) | join(" ")' "$S/alerts.json")" "SEV1 true" "A9 alerts.json says so, pinned"
n=$(sent_n)
bash "$T/auto.sh" "$(date -u -d '2026-10-26 15:35:00' +%s)" "disco al 83 %"
eq "$(sent_n)" "$n" "A9 the next pass of the check does not put SEV2 back, and says nothing"
eq "$(incs close INC-2026-002)" 2 "A10 the owner may not close an automatic incident"
has "$(inc close INC-2026-002)" "la misma comprobación lo cierra" "A10 and is told why"
has "$(inc note INC-2026-002 cause "volcados antiguos")" "Anotado en INC-2026-002" "A10 but may note it"
bash "$T/auto.sh" "$(date -u -d '2026-10-26 15:50:00' +%s)"
eq "$(jq -r 'select(.incident == "INC-2026-002" and .event == "close") | [.severity, .minutes] | map(tostring) | join(" ")' "$FILE")" "SEV1 20" "A10 the check closes it, with the owner's severity"

echo "-- closing a manual incident"
eq "$(incs close INC-2026-001 "x" --at 2026-10-26T14:00Z)" 2 "A11 a closing before the opening is refused"
out="$(inc close INC-2026-001 "reiniciado el contenedor de Caddy" --at 2026-10-26T15:30Z)"
has "$out" "Cerrado INC-2026-001 tras 28 min" "A11 the minutes are from the opening to the closing"
has "$(last_sent)" "[recuperado] manual.web tras 28 min (INC-2026-001; cerrado a mano por el dueño)" "A11 announced"
eq "$(incs close INC-2026-001)" 2 "A11 closing twice is refused"
eq "$(incs severity INC-2026-001 SEV1)" 2 "A11 a closed incident keeps its severity"
has "$(inc note INC-2026-001 prevention "vigilar la memoria de Caddy")" "Anotado" "A11 a note on a closed incident is still welcome (the review comes later)"
has "$(inc list)" "Nada abierto." "A12 nothing open"
has "$(inc list --all)" "INC-2026-001  SEV2  cerrado  desde 2026-10-26T15:02:00Z hasta 2026-10-26T15:30:00Z" "A12 --all lists the closed ones, with their last severity"
has "$(inc help)" "incident.sh note INC-2026-014" "A13 help"

echo "-- a dry run writes nothing"
n=$(nlines); seq0=$(cat "$S/incident.seq")
out="$(ALERTS_DRY_RUN=1 INCIDENT_NOW=$now "$T/bin/incident.sh" open api SEV3 "prueba en seco" 2>&1)"
has "$out" "WOULD WRITE:" "A14 it shows the line"
eq "$(nlines)" "$n" "A14 and writes none"
eq "$(cat "$S/incident.seq")" "$seq0" "A14 and does not use a number"

echo "-- a torn last line (power cut) and junk in the file"
cp "$FILE" "$T/register.keep"; cp "$S/incident.seq" "$T/seq.keep"
printf 'basura que no es json\n' >> "$FILE"; printf '{"at":"2026-10-26T16:30:00Z","event":"note","incident":"INC-2026-0' >> "$FILE"
has "$(inc list --all)" "INC-2026-001  SEV2  cerrado" "A15 list still works"
has "$(inc show INC-2026-001)" "open    owner  SEV1" "A15 show too"
has "$(inc note INC-2026-001 impact "tras la línea rota")" "Anotado en INC-2026-001: impact" "A15 a note after the torn line"
eq "$(tail -n 1 "$FILE" | jq -r '.event + " " + .field')" "note impact" "A15 went to a line of its own"
has "$(inc open dns SEV3 "después de la línea rota")" "Abierto INC-2026-0" "A15 an opening after it"
cp "$T/register.keep" "$FILE"; cp "$T/seq.keep" "$S/incident.seq"

echo; echo "RESULT: $PASS ok, $FAIL failed"
exit $(( FAIL > 0 ))
