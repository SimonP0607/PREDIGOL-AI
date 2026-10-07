#!/usr/bin/env bash
# Shared by the server scripts: where things are, how to reach the stack, how to say something.
# Sourced, never run. Every script that sources it runs with `set -Eeuo pipefail`.

KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREDIGOL_ENV_FILE="${PREDIGOL_ENV_FILE:-/etc/predigol/predigol.env}"
if [[ ! -r "$PREDIGOL_ENV_FILE" ]]; then
  echo "predigol: cannot read $PREDIGOL_ENV_FILE (run as root; see README.md)" >&2
  exit 2
fi
set -a
# shellcheck disable=SC1090
. "$PREDIGOL_ENV_FILE"
set +a
export PREDIGOL_ENV_FILE
PREDIGOL_DATA="${PREDIGOL_DATA:-/srv/predigol}"
STATE="$PREDIGOL_DATA/state"
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

compose() {
  docker compose --project-directory "$KIT" --env-file "$PREDIGOL_ENV_FILE" -f "$KIT/docker-compose.yml" \
    ${PREDIGOL_COMPOSE_EXTRA:+-f "$PREDIGOL_COMPOSE_EXTRA"} "$@"
}

# One value from the database, read-only, through the postgres container (no port is published).
psql_q() {
  compose exec -T postgres psql -U fbi -d fbi -v ON_ERROR_STOP=1 -qAtX \
    -c "SET default_transaction_read_only = on" -c "$1" | tail -n 1
}

log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*"; }

# A message to the owner's Telegram, when one is configured. Never fails the caller.
notify() {
  [[ -n "${FBI_TELEGRAM_BOT_TOKEN:-}" && -n "${FBI_TELEGRAM_CHAT_ID:-}" ]] || return 0
  # The token travels in curl's config on stdin, not on its command line (which `ps` shows to every user).
  printf 'url = "https://api.telegram.org/bot%s/sendMessage"\n' "$FBI_TELEGRAM_BOT_TOKEN" |
    curl -fsS -m 15 -o /dev/null -K - --data-urlencode "chat_id=${FBI_TELEGRAM_CHAT_ID}" \
      --data-urlencode "text=PrediGol ($(hostname)): $*" || log "notify: Telegram did not answer"
}

# Healthchecks.io: ping <url> [fail|start]. Empty url = not configured. Never fails the caller.
ping_hc() {
  local url="${1:-}" kind="${2:-}"
  [[ -n "$url" ]] || return 0
  curl -fsS -m 10 --retry 3 -o /dev/null "${url}${kind:+/$kind}" || log "ping: ${url%%/*}... did not answer"
}

# One at a time: `exclusive deploy` takes $STATE/deploy.lock for the rest of the script, or exits saying another
# run holds it. (A deploy that was still waiting for health once recorded its versions after a newer deploy.)
exclusive() {
  exec 9> "$STATE/$1.lock"
  flock -n 9 || { log "another $1 is running (lock $STATE/$1.lock)"; exit 1; }
}

# True while a deploy, a rollback or an import runs: the monitor then leaves the containers alone.
deploying() { ! flock -n "$STATE/deploy.lock" true 2> /dev/null; }
