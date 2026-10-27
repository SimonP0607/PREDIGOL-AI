#!/usr/bin/env bash
# Tests of alert-drill.sh (security plan S3.5) with the REAL lib.sh and alerts_lib.sh and a fake curl. No network, no Docker, no production.
# usage: tests/vps_shell/test_alert_drill.sh
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$(cd "$HERE/../../deploy/vps/bin" && pwd)   # the scripts under test: backend/deploy/vps/bin
DRILL=$SRC/alert-drill.sh
PASS=0; FAIL=0
ok() { PASS=$((PASS + 1)); echo "ok   $*"; }
no() { FAIL=$((FAIL + 1)); echo "FAIL $*"; }
eq() { if [[ "$1" == "$2" ]]; then ok "$3"; else no "$3: got '$1', expected '$2'"; fi; }
has() { if grep -qF -- "$1" "$2" 2> /dev/null; then ok "$3"; else no "$3: '$1' is not in $(basename "$2"): $(head -c 400 "$2" 2> /dev/null)"; fi; }
hasnt() { if grep -qF -- "$1" "$2" 2> /dev/null; then no "$3: '$1' IS in $(basename "$2")"; else ok "$3"; fi; }

T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin" "$T/data"
cat > "$T/bin/curl" <<'FAKE'
#!/usr/bin/env bash
# records the command line (one line per call) and what arrives on stdin (the -K - config); FAKE_CURL_RC makes every call fail like curl -f does on a 401,
# FAKE_CURL_FAIL_ON="2 5" makes only the calls with those numbers (the 2nd and the 5th since setup) fail
printf '%s\n' "$*" >> "$FAKE_DIR/argv"
cat > "$FAKE_DIR/stdin"
n=$(wc -l < "$FAKE_DIR/argv"); rc=${FAKE_CURL_RC:-0}
case " ${FAKE_CURL_FAIL_ON:-} " in *" ${n// /} "*) rc=22 ;; esac
if [[ "$rc" != 0 ]]; then echo "curl: (22) The requested URL returned error: ${FAKE_HTTP:-401}" >&2; fi
exit "$rc"
FAKE
chmod +x "$T/bin/curl"
# a sleep that only writes down how long it was asked to wait, for the tests that must see the pauses (the others use the real one: test 11 times a hold)
mkdir -p "$T/fastsleep"
printf '#!/usr/bin/env bash\necho "$*" >> "$FAKE_DIR/sleeps"\n' > "$T/fastsleep/sleep"; chmod +x "$T/fastsleep/sleep"
export FAKE_DIR=$T PATH="$T/bin:$PATH"

export PREDIGOL_ENV_FILE=$T/predigol.env PREDIGOL_APP_ENV_FILE=$T/app.env PREDIGOL_DATA=$T/data
unset PREDIGOL_ALERT_BOT_TOKEN PREDIGOL_ALERT_CHAT_ID FBI_TELEGRAM_BOT_TOKEN FBI_TELEGRAM_CHAT_ID
STATE_DIR=$T/data/state
EVID=$STATE_DIR/drills.jsonl
YEAR=$(date -u +%Y)

BOT=$'PREDIGOL_ALERT_BOT_TOKEN=ALERTTOK-SECRET-1\nPREDIGOL_ALERT_CHAT_ID=987654'
setup() {  # setup "<predigol.env lines>" "<app.env lines>" [curl rc] [http code]: a clean slate, the two environment files, curl's behaviour
  rm -f "$T/argv" "$T/stdin" "$T/out" "$T/sleeps"; rm -rf "$STATE_DIR"
  printf '%s\n' "$1" > "$PREDIGOL_ENV_FILE"; printf '%s\n' "$2" > "$PREDIGOL_APP_ENV_FILE"
  export FAKE_CURL_RC=${3:-0} FAKE_HTTP=${4:-401}; unset FAKE_CURL_FAIL_ON
}
run() { "$DRILL" "$@" > "$T/out" 2>&1 < /dev/null; echo $?; }
calls() { if [[ -s "$T/argv" ]]; then wc -l < "$T/argv" | tr -d ' '; else echo 0; fi; }
texts() { grep -o 'text=.*' "$T/argv" 2> /dev/null | sed 's/^text=//'; }   # what each call said
leaks() {  # leaks TOKEN CHAT_ID: is the token in the output, in the record or on curl's command line, or the chat id in the output or the record?
  grep -qF -- "$1" "$T/out" 2> /dev/null || grep -qF -- "$1" "$T/argv" 2> /dev/null || grep -qF -- "$1" "$EVID" 2> /dev/null \
    || grep -qF -- "$2" "$T/out" 2> /dev/null || grep -qF -- "$2" "$EVID" 2> /dev/null
}
sums() { (cd "$STATE_DIR" && for f in alerts.json incidents.jsonl incident.seq; do [[ -e "$f" ]] && sha256sum "$f"; done; ls -A) 2> /dev/null | grep -v drills.jsonl; }

# 1. --list: what it can send. Needs no channel and sends nothing.
setup "PREDIGOL_DOMAIN=x" ""
eq "$(run --list)" 0 "1 --list: exit 0, with no channel at all"
eq "$(calls)" 0 "1 --list calls curl never"
grep -Eq '^disk\.usage +SEV1 +el disco está al 91 %' "$T/out" && grep -Eq '^disk\.usage +SEV2 ' "$T/out" && ok "1 a key with two severities is listed twice, with its text" || no "1 disk.usage rows: $(head -5 "$T/out")"
hasnt '<nombre>' "$T/out" "1 the <nombre> placeholder is expanded"
n=0; for s in postgres api worker web caddy; do grep -Eq "^svc\.$s +SEV1 .*contenedor $s " "$T/out" && grep -Eq "^svc\.$s\.loop +SEV1 .*contenedor $s " "$T/out" && n=$((n + 1)); done
eq "$n" 5 "1 svc.<nombre> and svc.<nombre>.loop are listed for each of the five services, each text naming its service"
has 'health backup restore-test raw-sync pitr pitr-test maint' "$T/out" "1 the seven Healthchecks checks are listed"
rows=$(grep -cE '^[a-z0-9_.-]+ +SEV[123] ' "$T/out")
dups=$(grep -E '^[a-z0-9_.-]+ +SEV[123] ' "$T/out" | awk '{print $1, $2}' | sort | uniq -d | wc -l | tr -d ' ')
eq "$dups" 0 "1 no (key, severity) twice in the table ($rows rows)"
(( rows >= 45 )) && ok "1 the table has its rows ($rows)" || no "1 only $rows rows"
eq "$(run --help)" 0 "1 --help: exit 0"
has 'bin/alert-drill.sh --list' "$T/out" "1 --help prints the header of the file"
hasnt 'set -Eeuo pipefail' "$T/out" "1 and stops before the code"

# 2. one alert, through the real bot: the opening message and the recovery one
setup "$BOT" ""
eq "$(run disk.usage --hold 0)" 0 "2 disk.usage: exit 0"
eq "$(calls)" 2 "2 two messages: the opening and the recovery"
t1=$(texts | sed -n 1p); t2=$(texts | sed -n 2p)
eq "$t1" "PrediGol ($(hostname)): SIMULACRO · [SEV1] disk.usage: el disco está al 91 % (INC-$YEAR-901)" "2 the opening message: SIMULACRO, the most severe severity by default, the real text, the drill's own INC number"
eq "$t2" "PrediGol ($(hostname)): SIMULACRO · [recuperado] disk.usage tras 0 min (INC-$YEAR-901)" "2 the recovery message of the same incident"
has 'look at the phone' "$T/out" "2 it tells the session to look at the phone and note the time"
has "the server's alert bot" "$T/out" "2 and which bot it went through"
grep -q 'ALERTTOK-SECRET-1' "$T/stdin" && ok "2 the token travelled in curl's config on stdin" || no "2 token not on stdin"
grep -q 'chat_id=987654' "$T/argv" && ok "2 to the host's chat" || no "2 chat: $(cat "$T/argv")"
leaks ALERTTOK-SECRET-1 987654 && no "2 A SECRET IS IN THE OUTPUT, THE RECORD OR THE COMMAND LINE" || ok "2 no token on the command line, in the output or in the record; no chat id in the output or in the record"
eq "$(jq -c '[.kind, .key, .severity, .channel, .ok]' "$EVID")" '["alert","disk.usage","SEV1","server",true]' "2 the record has one line: what, which alert, severity, channel, result"
jq -e '.at | test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")' "$EVID" > /dev/null && ok "2 with the UTC time of the trigger" || no "2 'at': $(cat "$EVID")"
eq "$(jq -c .sent "$EVID")" '["open","close"]' "2 and the stages Telegram took: the opening message and the recovery one"

# 3. the severity can be chosen, before or after the key
setup "$BOT" ""
eq "$(run disk.usage SEV2 --hold 0)" 0 "3 disk.usage SEV2: exit 0"
eq "$(texts | sed -n 1p | sed 's/^PrediGol ([^)]*): //')" "SIMULACRO · [SEV2] disk.usage: el disco está al 83 % (INC-$YEAR-901)" "3 the text of that severity"
setup "$BOT" ""
eq "$(run SEV3 backup.offsite --hold 0)" 0 "3 the severity may come first"
texts | sed -n 1p | grep -q '\[SEV3\] backup.offsite: todavía no hay ninguna copia verificada' && ok "3 and picks the SEV3 text of a key that has three" || no "3 text: $(texts | sed -n 1p)"
setup "$BOT" ""
eq "$(run svc.worker --hold 0)" 0 "3 svc.worker (a service name filled in)"
texts | sed -n 1p | grep -q '\[SEV1\] svc.worker: el contenedor worker no está sano' && ok "3 the text names the service" || no "3 text: $(texts | sed -n 1p)"

# 4. the real register and the open alerts are never touched
real_register() {  # a state directory that has been in use: one alert open, its register, its counter
  mkdir -p "$STATE_DIR"
  printf '%s\n' '{"disk.usage":{"sev":"SEV2","since":1700000000,"text":"el disco está al 83 %","inc":"INC-2026-040","last":1700000000}}' > "$STATE_DIR/alerts.json"
  printf '%s\n' '{"inc":"INC-2026-040","event":"open"}' > "$STATE_DIR/incidents.jsonl"
  printf '2026 40\n' > "$STATE_DIR/incident.seq"
}
setup "$BOT" ""
real_register
before=$(sums)
eq "$(run disk.usage --hold 0)" 0 "4 a drill of an alert that is really open: exit 0"
eq "$(sums)" "$before" "4 alerts.json, incidents.jsonl and incident.seq are byte for byte the same, and no file was added (no lock either)"
has '(INC-' "$T/argv" "4 the message carries an incident number"
texts | sed -n 1p | grep -q "INC-$YEAR-901" && ok "4 and it is the drill's (901), not the real next one (41)" || no "4 INC: $(texts | sed -n 1p)"

# 5. --reminder: the reminder of a SEV1 that stays open
setup "$BOT" ""
eq "$(run worker.heartbeat --reminder --hold 0)" 0 "5 SEV1 with --reminder: exit 0"
eq "$(calls)" 3 "5 three messages: opening, reminder, recovery"
texts | sed -n 2p | grep -Eq 'SIMULACRO · \[SEV1 sigue abierto desde las [0-9]{2}:[0-9]{2} UTC\] worker\.heartbeat: el worker dejó de latir' && ok "5 the second one is the hourly reminder, with the time it opened" || no "5 second: $(texts | sed -n 2p)"
texts | sed -n 3p | grep -q 'SIMULACRO · \[recuperado\] worker.heartbeat' && ok "5 the third one closes it" || no "5 third: $(texts | sed -n 3p)"
setup "$BOT" ""
eq "$(run disk.forecast --reminder --hold 0)" 2 "5 --reminder on an alert that is not a SEV1: exit 2"
has 'SEV1' "$T/out" "5 it says only a SEV1 is repeated"
eq "$(calls)" 0 "5 and nothing was sent"

# 6. --dry-run: prints, sends nothing, writes nothing, needs no channel
setup "PREDIGOL_DOMAIN=x" ""
eq "$(run disk.usage --dry-run)" 0 "6 --dry-run without any channel: exit 0"
eq "$(calls)" 0 "6 curl was not called"
n=$(grep -c '^WOULD SEND: SIMULACRO · ' "$T/out"); eq "$n" 2 "6 it prints the two messages it would send"
[[ ! -e "$EVID" ]] && ok "6 and writes no record" || no "6 a record was written: $(cat "$EVID")"
eq "$(run worker.heartbeat --reminder --dry-run)" 0 "6 --dry-run --reminder: exit 0"
n=$(grep -c '^WOULD SEND: SIMULACRO · ' "$T/out"); eq "$n" 3 "6 and shows the reminder too"
setup "HC_PING_HEALTH=https://hc-ping.com/SECRET-UUID-HEALTH" ""
eq "$(run --healthchecks health --dry-run --hold 3)" 0 "6 --healthchecks --dry-run with the URL filled: exit 0"
has 'WOULD PING: HC_PING_HEALTH /fail, then after 3 s' "$T/out" "6 it names the variable and says what it would do"
hasnt 'SECRET-UUID' "$T/out" "6 without printing the URL"
eq "$(calls)" 0 "6 and pings nothing"
setup "PREDIGOL_DOMAIN=x" ""
eq "$(run --healthchecks health --dry-run)" 2 "6 --healthchecks --dry-run with the URL empty: exit 2, as the real run would (the dry run is how the pre-window checklist finds it)"
has 'HC_PING_HEALTH is empty' "$T/out" "6 and names the variable to fill"
setup "PREDIGOL_DOMAIN=x" ""
run disk.usage --dry-run > /dev/null
has 'a real run would stop' "$T/out" "6 a dry run without a channel says that the real one would stop there"

# 7. every row of the table can be drilled (the table is whole and its texts have the shape the scripts give them)
setup "PREDIGOL_DOMAIN=x" ""
"$DRILL" --list > "$T/list" 2>&1 < /dev/null
bad=0; n=0
while read -r key sev _; do
  out=$("$DRILL" "$key" "$sev" --dry-run 2>&1 < /dev/null); rc=$?
  n=$((n + 1))
  if (( rc != 0 )) || ! grep -qF "WOULD SEND: SIMULACRO · [$sev] $key: " <<< "$out"; then bad=$((bad + 1)); echo "     $key $sev rc=$rc: ${out:0:160}"; fi
done < <(grep -E '^[a-z0-9_.-]+ +SEV[123] ' "$T/list")
eq "$bad/$n" "0/$n" "7 every one of the $n rows of --list can be dry-run with its own key and severity"

# 8. what it refuses
setup "$BOT" ""
eq "$(run nope.key)" 2 "8 an alert the scripts never raise: exit 2"
has 'disk.usage' "$T/out" "8 it lists the ones that exist"
eq "$(run disk.usage SEV3)" 2 "8 a severity the alert is never raised at: exit 2"
has 'SEV1 SEV2' "$T/out" "8 it says which ones it is raised at"
eq "$(run disk.usage disk.forecast)" 2 "8 two alerts at once: exit 2"
eq "$(run)" 2 "8 no alert at all: exit 2"
eq "$(run disk.usage --hold abc)" 2 "8 --hold with a word: exit 2"
eq "$(run disk.usage --hold 601)" 2 "8 --hold over 600 s: exit 2"
eq "$(run disk.usage --hold)" 2 "8 --hold without a number: exit 2"
eq "$(run disk.usage --frobnicate)" 2 "8 an unknown option: exit 2"
eq "$(run --healthchecks)" 2 "8 --healthchecks without a name: exit 2"
eq "$(run --healthchecks nope --hold 0)" 2 "8 a check that does not exist: exit 2"
eq "$(calls)" 0 "8 none of those called curl"
[[ ! -e "$EVID" ]] && ok "8 and none left a record" || no "8 a record: $(cat "$EVID")"

# 9. no channel
setup "PREDIGOL_DOMAIN=x" ""
eq "$(run disk.usage --hold 0)" 2 "9 no bot configured: exit 2"
has 'PREDIGOL_ALERT_BOT_TOKEN and PREDIGOL_ALERT_CHAT_ID' "$T/out" "9 it names the two variables to fill"
eq "$(calls)" 0 "9 curl was not called"
setup "PREDIGOL_ALERT_BOT_TOKEN=ALERTTOK-SECRET-1" ""
eq "$(run disk.usage --hold 0)" 2 "9 a token without its chat is no channel: exit 2"
leaks ALERTTOK-SECRET-1 987654 && no "9 THE HALF PAIR IS PRINTED" || ok "9 and the half pair is not printed"

# 10. the application's bot, when the host has none
setup "PREDIGOL_DOMAIN=x" $'FBI_TELEGRAM_BOT_TOKEN=APPTOK-SECRET-2\nFBI_TELEGRAM_CHAT_ID=424242'
eq "$(run disk.usage --hold 0)" 0 "10 only the application's bot: exit 0"
has "the application's bot" "$T/out" "10 it says so"
eq "$(jq -r .channel "$EVID")" app "10 and the record says app"
leaks APPTOK-SECRET-2 424242 && no "10 A SECRET IS OUT" || ok "10 no secret in the output, the record or the command line"
setup $'PREDIGOL_ALERT_BOT_TOKEN=ALERTTOK-SECRET-1\nPREDIGOL_ALERT_CHAT_ID=987654' $'FBI_TELEGRAM_BOT_TOKEN=APPTOK-SECRET-2\nFBI_TELEGRAM_CHAT_ID=424242'
eq "$(run disk.usage --hold 0)" 0 "10 both bots: exit 0"
grep -q 'ALERTTOK-SECRET-1' "$T/stdin" && ! grep -q 'APPTOK-SECRET-2' "$T/stdin" && ok "10 the server's bot is the one used (the same choice as notify_ok)" || no "10 wrong bot"

# 11. Telegram refuses: it stops at the first message that was not taken
setup "$BOT" "" 22 401
t0=$SECONDS
eq "$(run disk.usage --hold 30)" 1 "11 Telegram refuses: exit 1"
(( SECONDS - t0 < 20 )) && ok "11 and it does not wait the 30 s hold for a message that never arrived" || no "11 it waited $((SECONDS - t0)) s"
eq "$(calls)" 1 "11 one attempt only (no recovery message for an alert that never opened)"
has 'the opening message was NOT taken' "$T/out" "11 it says which message"
has '401 or 404' "$T/out" "11 it tells what a 401 means (token wrong or revoked)"
has '400 or 403' "$T/out" "11 and a 400 or 403 (the chat)"
has 'alert-test.sh' "$T/out" "11 and where to check the channel alone"
eq "$(jq -c '[.ok, .failed]' "$EVID")" '[false,"the opening message"]' "11 the record says it failed, and what"
leaks ALERTTOK-SECRET-1 987654 && no "11 A SECRET IS OUT" || ok "11 even when it fails, no token and no chat id in the output or in the record"
setup "$BOT" "" 0
eq "$(run worker.heartbeat --reminder --hold 0)" 0 "11 control: the same drill with a working bot passes"

# 12. Healthchecks: the /fail ping and the one that recovers
HCV=$'HC_PING_HEALTH=https://hc-ping.com/SECRET-UUID-HEALTH\nHC_PING_BACKUP=https://hc-ping.com/SECRET-UUID-BACKUP\nHC_PING_RESTORE_TEST=https://hc-ping.com/SECRET-UUID-RESTORE\nHC_PING_RAW_SYNC=https://hc-ping.com/SECRET-UUID-RAW\nHC_PING_PITR=https://hc-ping.com/SECRET-UUID-PITR\nHC_PING_PITR_TEST=https://hc-ping.com/SECRET-UUID-PITRTEST\nHC_PING_MAINT='
setup "$HCV" ""
eq "$(run --healthchecks health --hold 0)" 0 "12 --healthchecks health: exit 0, with no bot configured (Healthchecks uses its own)"
eq "$(calls)" 2 "12 two pings"
eq "$(sed -n 1p "$T/argv" | awk '{print $NF}')" "https://hc-ping.com/SECRET-UUID-HEALTH/fail" "12 the first one is the /fail of that check"
eq "$(sed -n 2p "$T/argv" | awk '{print $NF}')" "https://hc-ping.com/SECRET-UUID-HEALTH" "12 the second one is the plain ping that recovers it"
hasnt 'SECRET-UUID' "$T/out" "12 the URL is a secret: never in the output"
hasnt 'SECRET-UUID' "$EVID" "12 nor in the record"
eq "$(jq -c '[.kind, .name, .channel, .ok]' "$EVID")" '["healthchecks","health","healthchecks",true]' "12 the record: a Healthchecks drill, which check, ok"
eq "$(jq -c .sent "$EVID")" '["fail","up"]' "12 and the two pings it made"
for pair in backup:BACKUP restore-test:RESTORE raw-sync:RAW pitr:PITR pitr-test:PITRTEST; do
  setup "$HCV" ""
  rc=$(run --healthchecks "${pair%%:*}" --hold 0)
  eq "$rc:$(sed -n 1p "$T/argv" | awk '{print $NF}')" "0:https://hc-ping.com/SECRET-UUID-${pair##*:}/fail" "12 the check '${pair%%:*}' pings its own variable (HC_PING_*, a dash is an underscore)"
done
setup "$HCV" ""
eq "$(run --healthchecks maint --hold 0)" 2 "12 a check whose URL is empty: exit 2"
has 'HC_PING_MAINT is empty' "$T/out" "12 it names the variable"
eq "$(calls)" 0 "12 and pings nothing"
setup "$HCV" "" 22
eq "$(run --healthchecks health --hold 30)" 1 "12 Healthchecks does not answer: exit 1"
eq "$(calls)" 2 "12 it still sends the recovery ping, so no check is left failed"
eq "$(jq -r '.ok, .failed' "$EVID" | paste -sd' ')" "false the /fail ping and the recovery ping" "12 the record says both failed"
eq "$(jq -c .sent "$EVID")" '[]' "12 and that no ping was taken"
setup "$HCV" ""
eq "$(FAKE_CURL_FAIL_ON=1 run --healthchecks health --hold 0)" 1 "12 only the /fail ping unanswered: exit 1"
eq "$(jq -r '.failed' "$EVID")" "the /fail ping" "12 the record names the one that failed"
eq "$(jq -c .sent "$EVID")" '["up"]' "12 and the recovery ping that did go"
hasnt 'SECRET-UUID' "$T/out" "12 even then the URL is not printed (curl's own message is dropped)"

# 13. --evidence: the rows of the drill record
setup "$BOT" ""
eq "$(run --evidence)" 0 "13 --evidence with nothing sent yet: exit 0"
has 'nothing was sent yet' "$T/out" "13 it says so"
setup "$BOT"$'\n'"$HCV" ""
run disk.usage --hold 0 > /dev/null; run --healthchecks health --hold 0 > /dev/null; FAKE_CURL_RC=22 run worker.heartbeat --hold 0 > /dev/null
eq "$(run --evidence)" 0 "13 --evidence with three drills: exit 0"
has '| Disparo (UTC) | Qué | Clave o check | Gravedad | Mensajes | Canal | Resultado |' "$T/out" "13 a markdown table with the columns of the drill record"
grep -Eq '^\| [0-9T:Z-]+ \| aviso \| disk\.usage \| SEV1 \| apertura \+ recuperado \| bot del servidor \| enviado \|$' "$T/out" && ok "13 a row for the alert that was sent, with the messages it made" || no "13 rows: $(cat "$T/out")"
grep -Eq '^\| [0-9T:Z-]+ \| Healthchecks \| health \| - \| /fail \+ recuperación \| Healthchecks \| enviado \|$' "$T/out" && ok "13 a row for the Healthchecks check" || no "13 rows: $(cat "$T/out")"
grep -Eq '^\| [0-9T:Z-]+ \| aviso \| worker\.heartbeat \| SEV1 \| - \| bot del servidor \| FALLÓ: the opening message \|$' "$T/out" && ok "13 and a row for the one Telegram refused, saying what failed and that no message went" || no "13 rows: $(cat "$T/out")"

# 14. --open-only, and the stages that the record keeps of each drill
setup "$BOT" ""
eq "$(run disk.usage --open-only)" 0 "14 --open-only: exit 0"
eq "$(calls)" 1 "14 one message only"
texts | sed -n 1p | grep -q 'SIMULACRO · \[SEV1\] disk.usage: el disco está al 91 %' && ok "14 the opening one" || no "14 text: $(texts | sed -n 1p)"
eq "$(jq -c .sent "$EVID")" '["open"]' "14 the record says that only the opening stage went"
setup "$BOT" ""
run worker.heartbeat --reminder --hold 0 > /dev/null
eq "$(jq -c .sent "$EVID")" '["open","remind","close"]' "14 with --reminder: opening, reminder and recovery"
run --evidence > /dev/null
grep -Eq '\| apertura \+ recordatorio \+ recuperado \|' "$T/out" && ok "14 --evidence names the three stages in Spanish" || no "14 evidence: $(cat "$T/out")"
setup "$BOT" ""
eq "$(FAKE_CURL_FAIL_ON=2 run worker.heartbeat --reminder --hold 0)" 1 "14 the reminder refused: exit 1"
eq "$(calls)" 2 "14 the opening and the reminder that failed: the recovery is not even tried"
has 'the reminder of the SEV1 that stays open was NOT taken' "$T/out" "14 it says which message"
eq "$(jq -c '[.ok, .failed, .sent]' "$EVID")" '[false,"the reminder of the SEV1 that stays open",["open"]]' "14 the record: failed, what, and that the opening one did go"
setup "$BOT" ""
eq "$(FAKE_CURL_FAIL_ON=2 run disk.usage --hold 0)" 1 "14 the recovery message refused: exit 1"
eq "$(jq -c '[.ok, .failed, .sent]' "$EVID")" '[false,"the recovery message",["open"]]' "14 the record names the recovery message"
setup "PREDIGOL_DOMAIN=x" ""
eq "$(run disk.usage --open-only --dry-run)" 0 "14 --open-only --dry-run: exit 0"
eq "$(grep -c '^WOULD SEND: SIMULACRO · ' "$T/out")" 1 "14 and it shows one message"

# 15. --all: the record, the opening message of each alert one after the other
setup "PREDIGOL_DOMAIN=x" ""
"$DRILL" --list > "$T/list" 2>&1 < /dev/null
has 'The record (--all sends the opening message of each' "$T/list" "15 --list shows the record"
sed -n '/^The record/,$p' "$T/list" | grep -E '^  [a-z0-9_.-]+ SEV[123]$' | sed 's/^  //' > "$T/record"
eq "$(wc -l < "$T/record" | tr -d ' ')" 36 "15 the record has 36 messages"
bad=0
while read -r key sev; do
  awk -v k="$key" -v s="$sev" 'NF >= 3 && $1 == k && $2 == s {f = 1} END {exit !f}' "$T/list" || { bad=$((bad + 1)); echo "     $key $sev is not a row of the table"; }
done < "$T/record"
eq "$bad" 0 "15 every one of them is a row of the table, at that severity"
eq "$(sort "$T/record" | uniq -d | wc -l | tr -d ' ')" 0 "15 and none is twice"
eq "$(run --all --dry-run)" 0 "15 --all --dry-run with no channel at all: exit 0"
eq "$(grep -c '^\[[0-9]*/36\] ' "$T/out")" 36 "15 it numbers them [1/36] to [36/36]"
eq "$(grep -c '^WOULD SEND: SIMULACRO · ' "$T/out")" 36 "15 and shows 36 messages"
grep -E '^\[[0-9]+/36\] ' "$T/out" | sed -E 's/^\[[0-9]+\/36\] //' | diff -q - "$T/record" > /dev/null && ok "15 in the order of the record" || no "15 the order is not the record's"
has 'dry run, 36 messages shown and none sent' "$T/out" "15 the last line says that nothing was sent"
[[ ! -e "$EVID" ]] && ok "15 and no record was written" || no "15 a record: $(head -3 "$EVID")"
setup "$BOT" ""
real_register
before=$(sums)
eq "$(PATH="$T/fastsleep:$PATH" run --all --pause 7)" 0 "15 --all with the real bot: exit 0"
eq "$(calls)" 36 "15 36 messages, one per alert of the record"
eq "$(texts | grep -c 'SIMULACRO · ')" 36 "15 each one is a drill"
eq "$(texts | grep -c 'recuperado')" 0 "15 and none is a recovery message (each alert is a drill of its own and is left open)"
eq "$(texts | grep -o 'INC-[0-9]*-[0-9]*' | sort -u | wc -l | tr -d ' ')" 36 "15 each with an INC number of its own"
eq "$(texts | sed -n 1p | grep -o 'INC-[0-9-]*')" "INC-$YEAR-901" "15 the first is 901"
eq "$(texts | sed -n 36p | grep -o 'INC-[0-9-]*')" "INC-$YEAR-936" "15 and the last 936"
texts | sed -n 1p | grep -q '\[SEV2\] admin.denied: 34 respuestas' && ok "15 the first message is the first of the record" || no "15 first: $(texts | sed -n 1p)"
eq "$(texts | grep -c '\[SEV1\] svc.api: el contenedor api no está sano')" 1 "15 a service stands for its five: svc.api"
eq "$(wc -l < "$T/sleeps" | tr -d ' '):$(sort -u "$T/sleeps")" "35:7" "15 a pause of 7 s between messages, none after the last, and no hold (there is no recovery to wait for)"
eq "$(wc -l < "$EVID" | tr -d ' ')" 36 "15 36 lines in the record"
eq "$(jq -s -c '[.[].sent] | unique' "$EVID")" '[["open"]]' "15 each with the opening stage only"
eq "$(jq -s '[.[] | select(.ok)] | length' "$EVID")" 36 "15 all of them taken"
jq -r '[.key, .severity] | join(" ")' "$EVID" | diff -q - "$T/record" > /dev/null && ok "15 the record keeps them in the order they were sent" || no "15 the order of the record file"
eq "$(sums)" "$before" "15 the real register, its alert and its counter are byte for byte the same"
has '36 of 36 opening messages taken' "$T/out" "15 the last line adds them up"
leaks ALERTTOK-SECRET-1 987654 && no "15 A SECRET IS OUT" || ok "15 no token and no chat id in the output, in the record or on curl's command line"
setup "$BOT" ""
eq "$(FAKE_CURL_FAIL_ON="2 3" PATH="$T/fastsleep:$PATH" run --all --pause 0)" 1 "15 two refused, not in a row of three: exit 1"
eq "$(calls)" 36 "15 it still tried every alert"
has '34 of 36 opening messages taken; NOT taken: api.login SEV1,auth.bruteforce SEV2' "$T/out" "15 the summary says how many and names the two"
eq "$(jq -s -c '[.[] | select(.ok == false) | .key]' "$EVID")" '["api.login","auth.bruteforce"]' "15 the record keeps those two as failed"
setup "$BOT" ""
eq "$(FAKE_CURL_FAIL_ON="1 2 4 5" PATH="$T/fastsleep:$PATH" run --all --pause 0)" 1 "15 refusals with a good message between them do not stop it: exit 1"
eq "$(calls)" 36 "15 every alert was tried"
setup "$BOT" "" 22 401
eq "$(PATH="$T/fastsleep:$PATH" run --all --pause 0)" 1 "15 the channel is down: exit 1"
eq "$(calls)" 3 "15 it stops after the third refusal in a row"
has 'three in a row were refused' "$T/out" "15 it says why it stopped"
has '33 more were not even tried' "$T/out" "15 and how many it did not try"
has '401 or 404' "$T/out" "15 each refusal tells what a 401 means"
leaks ALERTTOK-SECRET-1 987654 && no "15 A SECRET IS OUT (refused)" || ok "15 even refused, no secret"
setup "PREDIGOL_DOMAIN=x" ""
eq "$(run --all)" 2 "15 --all with no channel: exit 2"
eq "$(calls)" 0 "15 and nothing was sent"
has 'no channel is configured' "$T/out" "15 it says why"

# 16. options that go together, and options that do not
setup "$BOT" ""
for a in "--all disk.usage" "--all SEV1" "--all --hold 5" "--all --reminder" "--all --open-only" "--all --pause 61" "--all --pause abc" "--pause 5 disk.usage" "--all --list" "--list --evidence" \
  "--evidence --healthchecks health" "worker.heartbeat --reminder --open-only" "--healthchecks health --open-only"; do
  # shellcheck disable=SC2086  # the words of $a are the arguments
  eq "$(run $a)" 2 "16 '$a': exit 2"
done
eq "$(calls)" 0 "16 none of those sent anything"
[[ ! -e "$EVID" ]] && ok "16 or left a record" || no "16 a record: $(cat "$EVID")"
eq "$(PATH="$T/fastsleep:$PATH" run --all --pause 0 --dry-run)" 0 "16 --pause 0 is a pause like another"
eq "$(run --help)" 0 "16 --help: exit 0"
has '--all' "$T/out" "16 --help documents --all"
has '--open-only' "$T/out" "16 --help documents --open-only"
has '--pause SECONDS' "$T/out" "16 and --pause"

# 17. the dispatcher has the command and the usage text lists it
grep -qE '^  alert-drill\) shift; exec "\$BIN/alert-drill.sh" "\$@" ;;$' "$SRC/predigolctl" && ok "17 predigolctl dispatches alert-drill to the script" || no "17 not in the dispatcher"
setup "PREDIGOL_DOMAIN=x" ""
usage=$("$SRC/predigolctl" 2>&1 < /dev/null || true)   # no argument: the dispatcher prints its own usage text, the header of the file
case "$usage" in *"predigolctl alert-drill"*"predigolctl cloudflare"*) ok "17 the usage text shows alert-drill and still reaches the last command" ;; *) no "17 usage cut short: ${usage: -200}" ;; esac

echo; echo "RESULT: $PASS ok, $FAIL failed"
exit $(( FAIL > 0 ))
