#!/usr/bin/env bash
# Shared by the server scripts: where things are, how to reach the stack, how to say something.
# Sourced, never run. Every script that sources it runs with `set -Eeuo pipefail`.

KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREDIGOL_ENV_FILE="${PREDIGOL_ENV_FILE:-/etc/predigol/predigol.env}"
if [[ ! -r "$PREDIGOL_ENV_FILE" ]]; then
  echo "predigol: cannot read $PREDIGOL_ENV_FILE (run as root; see README.md)" >&2
  exit 2
fi
# The application's settings (FBI_*), for the notices below; the containers get them through docker-compose.yml.
PREDIGOL_APP_ENV_FILE="${PREDIGOL_APP_ENV_FILE:-/etc/predigol/app.env}"
set -a
# shellcheck disable=SC1090
. "$PREDIGOL_ENV_FILE"
# shellcheck disable=SC1090
[[ -r "$PREDIGOL_APP_ENV_FILE" ]] && . "$PREDIGOL_APP_ENV_FILE"
set +a
export PREDIGOL_ENV_FILE PREDIGOL_APP_ENV_FILE
PREDIGOL_DATA="${PREDIGOL_DATA:-/srv/predigol}"
STATE="$PREDIGOL_DATA/state"
# Caddy's own authority signs the certificate in internal mode (no domain yet: the IP) and in a *.localhost
# rehearsal; the checks below then trust that root instead of the public ones.
LOCAL_CA="$PREDIGOL_DATA/caddy/data/caddy/pki/authorities/local/root.crt"
uses_local_ca() { [[ "${PREDIGOL_TLS_MODE:-acme}" == internal || "${PREDIGOL_DOMAIN:-}" == *.localhost ]]; }
DB_BACKUPS="$PREDIGOL_DATA/backups/db"
mkdir -p "$STATE" "$DB_BACKUPS"
# The image versions the last deploy started (bin/predigolctl deploy writes them): a reboot or a plain `up`
# starts exactly those, never whatever happens to be tagged "local".
if [[ -r "$STATE/versions.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  . "$STATE/versions.env"
  set +a
fi

# The database image's version: the git tree of deploy/vps/postgres, which changes only when that folder does.
# (A rebuild of unchanged files still yields a new image id - build attestations carry a timestamp - and compose
# would then recreate the container: the database restarted on every deploy. Found by the rehearsal.)
pg_version() { git -C "$KIT/../.." rev-parse --short=12 HEAD:deploy/vps/postgres 2> /dev/null || echo 16; }
export PREDIGOL_PG_VERSION="${PREDIGOL_PG_VERSION:-$(pg_version)}"
export BUILDX_NO_DEFAULT_ATTESTATIONS=1

compose() {
  docker compose --project-directory "$KIT" --env-file "$PREDIGOL_ENV_FILE" -f "$KIT/docker-compose.yml" \
    ${PREDIGOL_COMPOSE_EXTRA:+-f "$PREDIGOL_COMPOSE_EXTRA"} "$@"
}

# One value from the database, read-only, through the postgres container (no port is published), as the owner.
# stdin is /dev/null: `compose exec` would otherwise swallow the rest of a `while read` loop's input (the
# rehearsal caught import.sh comparing ONE table with the manifest instead of all of them).
psql_q() {
  compose exec -T postgres psql -U fbi -d fbi -v ON_ERROR_STOP=1 -qAtX \
    -c "SET default_transaction_read_only = on" -c "$1" < /dev/null | tail -n 1
}

# What the worker and the API may do in the database (db/grants.sql), applied as the owner. Idempotent.
# The file travels through stdin, from the checkout: the container's copy is a bind mount of ONE file, which keeps pointing at the
# inode it was started with, and `git checkout` replaces the file (a new inode) - so after a deploy the container still showed the
# grants of the release before and the new ones were not applied (found by the F3 deploy: the referee tables had no grants for the
# API until the file was piped by hand).
apply_grants() {
  compose exec -T postgres psql -U fbi -d fbi -v ON_ERROR_STOP=1 -qX -f - < "$KIT/db/grants.sql" > /dev/null
}

# A one-off command in the backend image, as the database owner (the `ops` service). Never reads stdin.
ops() {
  compose --profile ops run --rm --no-deps -T ops "$@" < /dev/null
}

log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*"; }

# A message to the owner's Telegram. The host's alert bot (predigol.env: PREDIGOL_ALERT_BOT_TOKEN and PREDIGOL_ALERT_CHAT_ID, which no
# container receives) comes first; the application's FBI_TELEGRAM_* (app.env) are the fallback.
# notify_ok: 0 Telegram took the message | 1 it did not answer | 2 no channel is configured (the caller of alerts_lib.sh tries again on its next run).
notify_ok() {
  local token chat
  if [[ -n "${PREDIGOL_ALERT_BOT_TOKEN:-}" && -n "${PREDIGOL_ALERT_CHAT_ID:-}" ]]; then token=$PREDIGOL_ALERT_BOT_TOKEN; chat=$PREDIGOL_ALERT_CHAT_ID
  elif [[ -n "${FBI_TELEGRAM_BOT_TOKEN:-}" && -n "${FBI_TELEGRAM_CHAT_ID:-}" ]]; then token=$FBI_TELEGRAM_BOT_TOKEN; chat=$FBI_TELEGRAM_CHAT_ID  # a bot and a chat always travel as a pair
  else return 2; fi
  # The token travels in curl's config on stdin, not on its command line (which `ps` shows to every user).
  printf 'url = "https://api.telegram.org/bot%s/sendMessage"\n' "$token" |
    curl -fsS -m 15 -o /dev/null -K - --data-urlencode "chat_id=${chat}" \
      --data-urlencode "text=PrediGol ($(hostname)): $*" || { log "notify: Telegram did not answer"; return 1; }
}
# As before: a message to the owner's Telegram when one is configured. Never fails the caller.
notify() { notify_ok "$@" || true; }
# Which bot notify_ok would use, for the scripts that tell the owner about it (alert-test.sh, alert-drill.sh): "server" (PREDIGOL_ALERT_* in predigol.env), "app"
# (FBI_TELEGRAM_* in app.env) or nothing at all. The same two tests as notify_ok, in the same order; tests/vps_shell/test_notify.sh keeps the two in step.
alert_channel() {
  if [[ -n "${PREDIGOL_ALERT_BOT_TOKEN:-}" && -n "${PREDIGOL_ALERT_CHAT_ID:-}" ]]; then echo server
  elif [[ -n "${FBI_TELEGRAM_BOT_TOKEN:-}" && -n "${FBI_TELEGRAM_CHAT_ID:-}" ]]; then echo app
  fi
}

# Healthchecks.io: ping <url> [fail|start]. Empty url = not configured. Never fails the caller.
ping_hc() {
  local url="${1:-}" kind="${2:-}"
  [[ -n "$url" ]] || return 0
  curl -fsS -m 10 --retry 3 -o /dev/null "${url}${kind:+/$kind}" || log "ping: ${url%%/*}... did not answer"
}

# One at a time: `exclusive deploy` takes $STATE/deploy.lock for the rest of the script, or exits saying another
# run holds it. (A deploy that was still waiting for health once recorded its versions after a newer deploy.)
# A second lock in the same script needs its own descriptor: `exclusive pitr` after `exclusive deploy 8`.
exclusive() {
  local fd="${2:-9}"
  eval "exec $fd> \"\$STATE/\$1.lock\""
  flock -n "$fd" || { log "another $1 is running (lock $STATE/$1.lock)"; exit 1; }
}

# True while a deploy, a rollback or an import runs: the monitor then leaves the containers alone.
deploying() { ! flock -n "$STATE/deploy.lock" true 2> /dev/null; }
