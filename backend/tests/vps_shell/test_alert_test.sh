#!/usr/bin/env bash
# Tests of alert-test.sh (security plan S3) with the REAL lib.sh and a fake curl. No network, no Docker, no production.
# usage: tests/vps_shell/test_alert_test.sh
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$(cd "$HERE/../../deploy/vps/bin" && pwd)   # the scripts under test: backend/deploy/vps/bin
PASS=0; FAIL=0
ok() { PASS=$((PASS + 1)); echo "ok   $*"; }
no() { FAIL=$((FAIL + 1)); echo "FAIL $*"; }
eq() { if [[ "$1" == "$2" ]]; then ok "$3"; else no "$3: got '$1', expected '$2'"; fi; }

T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin" "$T/data"
cat > "$T/bin/curl" <<'FAKE'
#!/usr/bin/env bash
# records the command line and what arrives on stdin (the -K - config); FAKE_CURL_RC makes it fail like curl -f does on a 401
printf '%s\n' "$*" >> "$FAKE_DIR/argv"
cat > "$FAKE_DIR/stdin"
if [[ "${FAKE_CURL_RC:-0}" != 0 ]]; then echo "curl: (22) The requested URL returned error: ${FAKE_HTTP:-401}" >&2; fi
exit "${FAKE_CURL_RC:-0}"
FAKE
chmod +x "$T/bin/curl"
export FAKE_DIR=$T PATH="$T/bin:$PATH"

# The two environment files the real lib.sh reads, written per case.
export PREDIGOL_ENV_FILE=$T/predigol.env PREDIGOL_APP_ENV_FILE=$T/app.env PREDIGOL_DATA=$T/data
unset PREDIGOL_ALERT_BOT_TOKEN PREDIGOL_ALERT_CHAT_ID FBI_TELEGRAM_BOT_TOKEN FBI_TELEGRAM_CHAT_ID
setup() {  # setup "<predigol.env lines>" "<app.env lines>" [curl rc]
  rm -f "$T/argv" "$T/stdin" "$T/out"
  printf '%s\n' "$1" > "$PREDIGOL_ENV_FILE"; printf '%s\n' "$2" > "$PREDIGOL_APP_ENV_FILE"
  export FAKE_CURL_RC=${3:-0} FAKE_HTTP=${4:-401}
}
run() { "$SRC/alert-test.sh" > "$T/out" 2>&1; echo $?; }
# The token must never be in what the script prints nor on curl's command line (`ps` shows that to every user); the chat id is on the command
# line by design (notify_ok sends it as chat_id=...), so for it only the output counts.
leaks() {  # leaks TOKEN CHAT_ID: is the token in the output or on the command line, or the chat id in the output?
  grep -qF -- "$1" "$T/out" 2> /dev/null || grep -qF -- "$1" "$T/argv" 2> /dev/null || grep -qF -- "$2" "$T/out" 2> /dev/null
}

# 1. no channel at all
setup "PREDIGOL_DOMAIN=x" "FBI_ENV=production"
eq "$(run)" 2 "1 no channel: exit 2"
[[ ! -e "$T/argv" ]] && ok "1 curl was not called" || no "1 curl was called without a channel"
grep -q 'no channel is configured' "$T/out" && ok "1 it says there is no channel" || no "1 no explanation: $(cat "$T/out")"
grep -q 'PREDIGOL_ALERT_BOT_TOKEN and PREDIGOL_ALERT_CHAT_ID' "$T/out" && ok "1 it names the two variables to fill" || no "1 variables not named"

# 2. the server's alert bot
setup $'PREDIGOL_ALERT_BOT_TOKEN=ALERTTOK-SECRET-1\nPREDIGOL_ALERT_CHAT_ID=987654' ""
eq "$(run)" 0 "2 the server's bot: exit 0"
grep -q 'PREDIGOL_ALERT_\* in predigol.env' "$T/out" && ok "2 it says the server's bot took it" || no "2 which bot? $(cat "$T/out")"
grep -q 'Look at your phone' "$T/out" && ok "2 it tells the owner to look at the phone (only the phone knows)" || no "2 no hint about the phone"
grep -q 'ALERTTOK-SECRET-1' "$T/stdin" && ok "2 the token travelled in curl's config on stdin" || no "2 token not on stdin"
grep -q 'chat_id=987654' "$T/argv" && ok "2 the chat id is the host's" || no "2 chat: $(cat "$T/argv")"
grep -q 'text=PrediGol (.*): mensaje de prueba de los avisos' "$T/argv" && ok "2 the text is a test message in Spanish" || no "2 text: $(cat "$T/argv")"
leaks ALERTTOK-SECRET-1 987654 && no "2 THE TOKEN IS IN THE OUTPUT OR ON THE COMMAND LINE, OR THE CHAT ID IN THE OUTPUT" || ok "2 no token in the output or on the command line, no chat id in the output"

# 3. the application's bot only
setup "PREDIGOL_DOMAIN=x" $'FBI_TELEGRAM_BOT_TOKEN=APPTOK-SECRET-2\nFBI_TELEGRAM_CHAT_ID=424242'
eq "$(run)" 0 "3 the application's bot: exit 0"
grep -q 'FBI_TELEGRAM_\* in app.env' "$T/out" && ok "3 it says the application's bot took it" || no "3 which bot? $(cat "$T/out")"
leaks APPTOK-SECRET-2 424242 && no "3 THE TOKEN IS IN THE OUTPUT OR ON THE COMMAND LINE, OR THE CHAT ID IN THE OUTPUT" || ok "3 no token in the output or on the command line, no chat id in the output"

# 4. both: the server's wins
setup $'PREDIGOL_ALERT_BOT_TOKEN=ALERTTOK-SECRET-1\nPREDIGOL_ALERT_CHAT_ID=987654' $'FBI_TELEGRAM_BOT_TOKEN=APPTOK-SECRET-2\nFBI_TELEGRAM_CHAT_ID=424242'
eq "$(run)" 0 "4 both configured: exit 0"
grep -q 'ALERTTOK-SECRET-1' "$T/stdin" && ! grep -q 'APPTOK-SECRET-2' "$T/stdin" && ok "4 the server's bot is the one used" || no "4 wrong token"
grep -q "the server's alert bot" "$T/out" && ok "4 and it says so" || no "4 says: $(cat "$T/out")"

# 5. half a channel is no channel
setup "PREDIGOL_ALERT_BOT_TOKEN=ALERTTOK-SECRET-1" ""
eq "$(run)" 2 "5 a token without its chat: exit 2"
leaks ALERTTOK-SECRET-1 987654 && no "5 THE TOKEN IS IN THE OUTPUT" || ok "5 and the half pair is not printed"
setup "PREDIGOL_ALERT_CHAT_ID=987654" ""
eq "$(run)" 2 "5 a chat without its token: exit 2"

# 6. Telegram refuses (a revoked token answers 401)
setup $'PREDIGOL_ALERT_BOT_TOKEN=ALERTTOK-SECRET-1\nPREDIGOL_ALERT_CHAT_ID=987654' "" 22 401
eq "$(run)" 1 "6 Telegram refuses: exit 1"
grep -q 'did not take the message' "$T/out" && ok "6 it says the message was not taken" || no "6 says: $(cat "$T/out")"
grep -q '401 or 404' "$T/out" && ok "6 it tells what a 401 means (token wrong or revoked)" || no "6 no hint for 401"
grep -q '400 or 403' "$T/out" && ok "6 and what a 400 or 403 means (the chat)" || no "6 no hint for 400/403"
leaks ALERTTOK-SECRET-1 987654 && no "6 A SECRET IS IN THE OUTPUT" || ok "6 even when it fails, no token and no chat id in the output"

# 7. the dispatcher has the command and the usage text lists it
grep -qE '^  alert-test\) shift; exec "\$BIN/alert-test.sh" "\$@" ;;$' "$SRC/predigolctl" && ok "7 predigolctl dispatches alert-test to the script" || no "7 not in the dispatcher"
setup "PREDIGOL_DOMAIN=x" ""
usage=$("$SRC/predigolctl" 2>&1 || true)   # no argument: the dispatcher prints its own usage text, the header of the file
case "$usage" in *"predigolctl alert-test"*"predigolctl cloudflare"*) ok "7 the usage text the dispatcher prints shows alert-test and still reaches the last command" ;; *) no "7 usage cut short: ${usage: -200}" ;; esac

echo; echo "RESULT: $PASS ok, $FAIL failed"
exit $(( FAIL > 0 ))
