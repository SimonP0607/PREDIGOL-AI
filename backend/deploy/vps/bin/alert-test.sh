#!/usr/bin/env bash
# One test message through the very function every alert uses (lib.sh: notify_ok), and an answer in plain words. For the owner: after
# creating the alert bot, after changing its token (docs/owner/SECRETS_AND_ROTATION.md, "Bot de avisos") and before a drill.
#
#   bin/alert-test.sh            (predigolctl alert-test)
#
# It says WHICH bot took the message - the host's (PREDIGOL_ALERT_* in predigol.env) or the application's (FBI_TELEGRAM_* in app.env) -
# and never prints a token or a chat id. What no script can know is whether the chat is the owner's: Telegram takes a message for any
# chat the bot may write to, so the last word is the owner's phone.
# Exit 0 Telegram took it | 1 Telegram did not answer or refused it | 2 no channel is configured (a token without its chat, or a chat
# without its token, is no channel).
set -Eeuo pipefail
# shellcheck source=bin/lib.sh
. "$(dirname "$0")/lib.sh"

case "$(alert_channel)" in
  server) via="the server's alert bot (PREDIGOL_ALERT_* in predigol.env)" ;;
  app) via="the application's bot (FBI_TELEGRAM_* in app.env)" ;;
  *)
    log "alert-test: no channel is configured. PREDIGOL_ALERT_BOT_TOKEN and PREDIGOL_ALERT_CHAT_ID (predigol.env) need a value each, both of them"
    exit 2
    ;;
esac

rc=0
notify_ok "mensaje de prueba de los avisos ($(date -u +%H:%M) UTC): si lo lees, los avisos de PrediGol te llegan a este chat." || rc=$?
if (( rc == 0 )); then
  log "alert-test: Telegram took the message, through $via. Look at your phone: if nothing arrives, the chat id is not yours (or you have not pressed Start in the bot's chat)"
  exit 0
fi
log "alert-test: Telegram did not take the message (through $via). 401 or 404 above = the token is wrong or was revoked; 400 or 403 = the bot may not write to that chat (open the bot in Telegram and press Start); no answer at all = the server has no way out to api.telegram.org"
exit 1
