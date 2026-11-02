#!/usr/bin/env bash
# Logic of security-alerts.sh with a fake lib.sh (fake psql_q, fake channel) and a fake Caddy log. No Docker, no network.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$(cd "$HERE/../../deploy/vps/bin" && pwd)   # the scripts under test: backend/deploy/vps/bin
PASS=0; FAIL=0
ok() { PASS=$((PASS + 1)); echo "ok   $*"; }
no() { FAIL=$((FAIL + 1)); echo "FAIL $*"; }
eq() { if [[ "$1" == "$2" ]]; then ok "$3"; else no "$3: got '$1', expected '$2'"; fi; }

T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
BIN="$T/bin"; mkdir -p "$BIN" "$T/state" "$T/data/caddy/data"
cp "$SRC/security-alerts.sh" "$SRC/alerts_lib.sh" "$SRC/security_alerts_sql.sh" "$BIN/"
cat > "$BIN/lib.sh" <<'FAKELIB'
STATE=$FAKE_STATE; PREDIGOL_DATA=$FAKE_DATA
log() { echo "LOG $*" >> "$FAKE_LOG"; }
notify_ok() { printf '%s\n' "$*" >> "$FAKE_SENT"; }
psql_q() {
  printf '%s\n----\n' "$1" >> "$FAKE_SQLLOG"
  [[ "${FAKE_DB_DOWN:-0}" == 1 ]] && return 1
  case "$1" in
    *"min(id)"*) echo "${FAKE_OWNER_Q:-1}" ;;
    *"user.role_changed"*) echo "${FAKE_PRIV:-0|0|}" ;;
    *"NOT EXISTS"*) echo "${FAKE_NEWDEV:-0|}" ;;
    *"login.locked"*) echo "${FAKE_LOCKED:-0|}" ;;
    *"login.failed"*) echo "${FAKE_FAILED:-0}" ;;
  esac
}
FAKELIB
export FAKE_STATE="$T/state" FAKE_DATA="$T/data" FAKE_SENT="$T/sent" FAKE_LOG="$T/log" FAKE_SQLLOG="$T/sql"
ACCESS="$T/data/caddy/data/access.log"
run() { bash "$BIN/security-alerts.sh" "$@"; }
reset() { rm -f "$T/sent" "$T/log" "$T/sql" "$T/state"/*; : > "$ACCESS"; unset FAKE_FAILED FAKE_LOCKED FAKE_NEWDEV FAKE_PRIV FAKE_OWNER_Q FAKE_DB_DOWN PREDIGOL_OWNER_USER_ID; }
sent() { [[ -f "$T/sent" ]] && wc -l < "$T/sent" | tr -d ' ' || echo 0; }
keys() { jq -r 'keys | join(",")' "$T/state/alerts.json" 2> /dev/null || echo none; }
logline() { # logline <seconds ago> <status> <uri>
  jq -cn --argjson ts "$(( $(date +%s) - $1 ))" --argjson st "$2" --arg uri "$3" '{ts: $ts, status: $st, request: {uri: $uri, method: "GET"}}' >> "$ACCESS"
}

# 1. quiet
reset; run; eq "$?" 0 "1 a quiet run exits 0"; eq "$(sent)" 0 "1 sends nothing"; eq "$(keys)" "" "1 opens nothing"

# 2. failed sign-ins: > 20
reset; FAKE_FAILED=20 run; eq "$(keys)" "" "2 20 failures is not above the threshold"
reset; FAKE_FAILED=21 run; eq "$(keys)" "auth.bruteforce" "2 21 failures opens auth.bruteforce"
case "$(tail -n 1 "$T/sent")" in "[SEV2] auth.bruteforce: 21 inicios de sesión fallidos en 5 min (INC-"*) ok "2 message text" ;; *) no "2 message: $(tail -n 1 "$T/sent")" ;; esac
FAKE_FAILED=3 run; eq "$(keys)" "" "2 and closes when the count falls"
eq "$(tail -n 1 "$T/sent" | cut -c1-34)" "[recuperado] auth.bruteforce tras " "2 recovery message"

# 3. accounts on hold
reset; FAKE_LOCKED='0|' run; eq "$(keys)" "" "3 none on hold: nothing"
reset; FAKE_LOCKED='2|6,7' run; eq "$(keys)" "auth.locked" "3 two on hold: SEV3"
case "$(tail -n 1 "$T/sent")" in "[SEV3] auth.locked: 2 cuenta(s) en espera en la última hora (id 6,7) (INC-"*) ok "3 message text" ;; *) no "3 message: $(tail -n 1 "$T/sent")" ;; esac

# 4. new device
reset; FAKE_NEWDEV='1|5' run; eq "$(keys)" "auth.newdevice" "4 new browser of an administrator"
case "$(tail -n 1 "$T/sent")" in "[SEV2] auth.newdevice:"*"(id 5)"*) ok "4 message carries the id only" ;; *) no "4 message: $(tail -n 1 "$T/sent")" ;; esac

# 5. privileged changes
reset; FAKE_PRIV='0|0|' run; eq "$(keys)" "" "5 none: nothing"
reset; FAKE_PRIV='2|0|7' run; eq "$(jq -r '."auth.privileged".sev' "$T/state/alerts.json")" SEV2 "5 only the owner or the command line: SEV2"
reset; FAKE_PRIV='3|1|6,7' run; eq "$(jq -r '."auth.privileged".sev' "$T/state/alerts.json")" SEV1 "5 another account did it: SEV1"

# 6. the owner id in the query
reset; PREDIGOL_OWNER_USER_ID=1 FAKE_OWNER_Q=99 run
grep -q 'actor_user_id <> 1)' "$T/sql" && ok "6 PREDIGOL_OWNER_USER_ID is used" || no "6 owner id not in the SQL"
grep -q ':owner' "$T/sql" && no "6 the placeholder was not replaced" || ok "6 no placeholder left in the SQL"
grep -q 'min(id)' "$T/sql" && no "6 the owner was looked up although it is set" || ok "6 no lookup when it is set"
reset; FAKE_OWNER_Q=5 run
grep -q 'actor_user_id <> 5)' "$T/sql" && ok "6 default owner = the oldest SUPER_ADMIN" || no "6 default owner not used"
reset; FAKE_OWNER_Q='?' FAKE_PRIV='3|1|6,7' run; eq "$?" 0 "6 an unreadable owner does not stop the script"; eq "$(keys)" "" "6 and the privileged check is skipped (no guess about who the owner is)"

# 7. database down: no alert, no crash
reset; FAKE_DB_DOWN=1 FAKE_FAILED=99 run; eq "$?" 0 "7 database down: exit 0"; eq "$(keys)" "" "7 database down: no alert from here"

# 8. Caddy log: 401/403 on /api/v1/admin in the last 10 minutes
reset; for _ in $(seq 20); do logline 30 403 /api/v1/admin/users; done; run; eq "$(keys)" "" "8 20 denied is not above the threshold"
reset; for _ in $(seq 11); do logline 30 403 /api/v1/admin/users; logline 60 401 "/api/v1/admin/system?x=1"; done; run; eq "$(keys)" "admin.denied" "8 22 denied (401+403) opens admin.denied"
reset; for _ in $(seq 30); do logline 700 403 /api/v1/admin/users; logline 30 200 /api/v1/admin/users; logline 30 403 /api/v1/matches; logline 30 401 /api/v1/auth/me; done; run; eq "$(keys)" "" "8 old lines, 200s and other routes are not counted"
reset; run; eq "$(keys)" "" "8 an empty log is fine"
rm -f "$ACCESS"; run; eq "$?" 0 "8 a missing log is fine"; : > "$ACCESS"

# 9. dry run
reset; FAKE_FAILED=50 run --dry-run > "$T/dry.out"; eq "$(sent)" 0 "9 dry run sends nothing"; eq "$(find "$T/state" -mindepth 1 -maxdepth 1 ! -name '*lock*' | wc -l | tr -d ' ')" 0 "9 dry run writes no state"
grep -q 'WOULD SEND: \[SEV2\] auth.bruteforce' "$T/dry.out" && ok "9 dry run prints what it would send" || no "9 dry run output: $(cat "$T/dry.out")"

# 10. no personal data in any message
reset; FAKE_FAILED=50 FAKE_LOCKED='3|6,7,8' FAKE_NEWDEV='1|5' FAKE_PRIV='3|1|6,7' run
if grep -qE '@|[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+|Mozilla' "$T/sent"; then no "10 an email, address or user agent reached a message"; else ok "10 messages hold no email, address or user agent"; fi
eq "$(sent)" 4 "10 four alerts, four messages"

# 11. a second run while one is running: exits quietly
reset; ( exec 9> "$T/state/security-alerts.lock"; flock -n 9; sleep 2 ) & sleep 0.5
FAKE_FAILED=50 run; eq "$?" 0 "11 a concurrent run exits 0"; eq "$(sent)" 0 "11 and does nothing"; wait

# 12. a source that does not answer holds what is open: no false "recuperado", no new incident when it is back
reset; export FAKE_FAILED=50 FAKE_LOCKED='2|6,7' FAKE_NEWDEV='1|5' FAKE_PRIV='3|1|6,7'
for _ in $(seq 21); do logline 30 403 /api/v1/admin/users; done; run
eq "$(keys)" "admin.denied,auth.bruteforce,auth.locked,auth.newdevice,auth.privileged" "12 five alerts open"
n0=$(sent); inc0=$(jq -r '."auth.bruteforce".incident // empty' "$T/state/alerts.json")
FAKE_DB_DOWN=1 run
eq "$(keys)" "admin.denied,auth.bruteforce,auth.locked,auth.newdevice,auth.privileged" "12 database down: the five stay open"
eq "$(sent)" "$n0" "12 database down: no 'recuperado' and no new message"
grep -q 'recuperado' "$T/sent" && no "12 a recovery message was sent while the database was down" || ok "12 no recovery message anywhere"
run
eq "$(sent)" "$n0" "12 database back, same condition: still no new message (same incident)"
eq "$(jq -r '."auth.bruteforce".incident // empty' "$T/state/alerts.json")" "$inc0" "12 and the incident number did not change"
# the owner cannot be read: the privileged alert is held, the others are judged normally
unset FAKE_FAILED FAKE_LOCKED FAKE_NEWDEV   # these three conditions end; the privileged one (FAKE_PRIV) goes on
FAKE_OWNER_Q='?' run
eq "$(keys)" "admin.denied,auth.privileged" "12 owner unreadable: auth.privileged held; the other database alerts close; admin.denied is judged from the log"
# the log cannot be read: admin.denied is held
rm -f "$ACCESS"; FAKE_OWNER_Q=1 run
eq "$(keys)" "admin.denied,auth.privileged" "12 log missing: admin.denied stays open"
: > "$ACCESS"; FAKE_PRIV='0|0|' run
eq "$(keys)" "" "12 everything readable and quiet: both close"
grep -c 'recuperado' "$T/sent" | grep -qx 5 && ok "12 five recoveries, one per alert, only when they really recovered" || no "12 recoveries: $(grep -c recuperado "$T/sent")"
unset FAKE_FAILED FAKE_LOCKED FAKE_NEWDEV FAKE_PRIV

echo; echo "RESULT: $PASS ok, $FAIL failed"
exit $(( FAIL > 0 ))
