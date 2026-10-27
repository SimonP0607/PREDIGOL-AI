#!/usr/bin/env bash
# Tests of notify_ok / notify (lib.sh, security plan S3) with a fake curl. No network. usage: tests/vps_shell/test_notify.sh [lib.sh]
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$(cd "$HERE/../../deploy/vps/bin" && pwd)   # the scripts under test: backend/deploy/vps/bin
LIB=${1:-$SRC/lib.sh}
PASS=0; FAIL=0
ok() { PASS=$((PASS + 1)); echo "ok   $*"; }
no() { FAIL=$((FAIL + 1)); echo "FAIL $*"; }
eq() { if [[ "$1" == "$2" ]]; then ok "$3"; else no "$3: got '$1', expected '$2'"; fi; }

T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin"
cat > "$T/bin/curl" <<'FAKE'
#!/usr/bin/env bash
# records the command line and what arrives on stdin (the -K - config)
printf '%s\n' "$*" >> "$FAKE_DIR/argv"
cat > "$FAKE_DIR/stdin"
exit "${FAKE_CURL_RC:-0}"
FAKE
chmod +x "$T/bin/curl"
export FAKE_DIR=$T PATH="$T/bin:$PATH"

log() { echo "LOG $*" >> "$T/log"; }
# the two functions under test, cut out of the patched lib.sh
eval "$(sed -n '/^notify_ok() {/,/^notify() /p' "$LIB")"

reset() { rm -f "$T/argv" "$T/stdin" "$T/log"; unset PREDIGOL_ALERT_BOT_TOKEN PREDIGOL_ALERT_CHAT_ID FBI_TELEGRAM_BOT_TOKEN FBI_TELEGRAM_CHAT_ID; export FAKE_CURL_RC=0; }

# 1. no channel
reset; notify_ok "hola"; eq "$?" 2 "1 notify_ok returns 2 without a channel"
notify "hola"; eq "$?" 0 "1 notify returns 0 without a channel"
[[ ! -e "$T/argv" ]] && ok "1 curl was not called" || no "1 curl was called without a channel"

# 2. the application's variables only
reset; export FBI_TELEGRAM_BOT_TOKEN=APPTOKEN123 FBI_TELEGRAM_CHAT_ID=4242
notify_ok "mensaje uno"; eq "$?" 0 "2 notify_ok returns 0"
grep -q 'bot' "$T/stdin" && grep -q 'APPTOKEN123' "$T/stdin" && ok "2 the token is in curl's config on stdin" || no "2 token not on stdin"
grep -q 'APPTOKEN123' "$T/argv" && no "2 TOKEN ON THE COMMAND LINE" || ok "2 the token is not on the command line"
grep -q 'chat_id=4242' "$T/argv" && ok "2 chat id from FBI_TELEGRAM_CHAT_ID" || no "2 chat id missing"
grep -q "text=PrediGol ($(hostname)): mensaje uno" "$T/argv" && ok "2 message text with the host name" || no "2 text: $(cat "$T/argv")"

# 3. the host's alert bot wins
reset; export FBI_TELEGRAM_BOT_TOKEN=APPTOKEN123 FBI_TELEGRAM_CHAT_ID=4242 PREDIGOL_ALERT_BOT_TOKEN=ALERTTOKEN9 PREDIGOL_ALERT_CHAT_ID=777
notify_ok "m"; eq "$?" 0 "3 notify_ok returns 0"
grep -q 'ALERTTOKEN9' "$T/stdin" && ! grep -q 'APPTOKEN123' "$T/stdin" && ok "3 the alert token is the one used" || no "3 wrong token on stdin"
grep -q 'chat_id=777' "$T/argv" && ok "3 the alert chat is the one used" || no "3 wrong chat: $(cat "$T/argv")"
grep -q 'ALERTTOKEN9\|APPTOKEN123' "$T/argv" && no "3 TOKEN ON THE COMMAND LINE" || ok "3 no token on the command line"

# 4. half a channel is no channel
reset; export PREDIGOL_ALERT_BOT_TOKEN=ALERTTOKEN9
notify_ok "m"; eq "$?" 2 "4 a token without a chat is no channel"
reset; export PREDIGOL_ALERT_CHAT_ID=777
notify_ok "m"; eq "$?" 2 "4 a chat without a token is no channel"
reset; export PREDIGOL_ALERT_BOT_TOKEN=ALERTTOKEN9 FBI_TELEGRAM_CHAT_ID=4242
notify_ok "m"; eq "$?" 2 "4 the alert bot is never mixed with the application's chat (the pair travels together)"
reset; export PREDIGOL_ALERT_BOT_TOKEN=ALERTTOKEN9 FBI_TELEGRAM_BOT_TOKEN=APPTOKEN123 FBI_TELEGRAM_CHAT_ID=4242
notify_ok "m"; eq "$?" 0 "4 a half alert pair falls back to the complete application pair"
grep -q 'APPTOKEN123' "$T/stdin" && grep -q 'chat_id=4242' "$T/argv" && ok "4 and uses that pair as a whole" || no "4 wrong pair used"

# 5. Telegram does not answer
reset; export PREDIGOL_ALERT_BOT_TOKEN=ALERTTOKEN9 PREDIGOL_ALERT_CHAT_ID=777 FAKE_CURL_RC=22
notify_ok "m"; eq "$?" 1 "5 notify_ok returns 1 when curl fails"
grep -q 'did not answer' "$T/log" && ok "5 the failure is logged" || no "5 no log line"
grep -q 'ALERTTOKEN9' "$T/log" && no "5 TOKEN IN THE LOG" || ok "5 the log has no token"
notify "m"; eq "$?" 0 "5 notify never fails its caller"

# 6. alert_channel names the bot notify_ok uses. alert-test.sh and alert-drill.sh tell the owner "through the server's bot" with it, so the two tests of the same
#    variables must never disagree: every combination of the four variables is run through both, and the token that reached curl says which bot really took it.
eval "$(sed -n '/^alert_channel() {/,/^}/p' "$LIB")"
channel_case() {  # <what> <channel the two must agree on: server|app|none> <VAR=value>...
  local what=$1 want=$2 kv got used rc=0; shift 2
  reset; for kv in "$@"; do export "${kv?}"; done
  got=$(alert_channel); [[ -n "$got" ]] || got=none
  notify_ok "m" || rc=$?
  if (( rc == 2 )); then used=none; elif grep -q 'ALERTTOKEN9' "$T/stdin"; then used=server; elif grep -q 'APPTOKEN123' "$T/stdin"; then used=app; else used="unknown (exit $rc)"; fi
  eq "$got/$used" "$want/$want" "6 alert_channel and notify_ok agree: $what -> $want"
}
channel_case "no variable" none
channel_case "the application's pair" app FBI_TELEGRAM_BOT_TOKEN=APPTOKEN123 FBI_TELEGRAM_CHAT_ID=4242
channel_case "the server's pair" server PREDIGOL_ALERT_BOT_TOKEN=ALERTTOKEN9 PREDIGOL_ALERT_CHAT_ID=777
channel_case "both pairs" server PREDIGOL_ALERT_BOT_TOKEN=ALERTTOKEN9 PREDIGOL_ALERT_CHAT_ID=777 FBI_TELEGRAM_BOT_TOKEN=APPTOKEN123 FBI_TELEGRAM_CHAT_ID=4242
channel_case "a server token without its chat" none PREDIGOL_ALERT_BOT_TOKEN=ALERTTOKEN9
channel_case "a server chat without its token" none PREDIGOL_ALERT_CHAT_ID=777
channel_case "a server token with the application's chat" none PREDIGOL_ALERT_BOT_TOKEN=ALERTTOKEN9 FBI_TELEGRAM_CHAT_ID=4242
channel_case "the application's token alone" none FBI_TELEGRAM_BOT_TOKEN=APPTOKEN123
channel_case "half a server pair and a whole application pair" app PREDIGOL_ALERT_BOT_TOKEN=ALERTTOKEN9 FBI_TELEGRAM_BOT_TOKEN=APPTOKEN123 FBI_TELEGRAM_CHAT_ID=4242

echo; echo "RESULT: $PASS ok, $FAIL failed"
exit $(( FAIL > 0 ))
