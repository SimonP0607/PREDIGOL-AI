#!/usr/bin/env bash
# Every 5 minutes (predigol-security-alerts.timer): the security alerts of section 20 of the plan that come from the application's own records
# (auth.audit_events) and from Caddy's access log. Only counts and user ids leave this script: never the email column, an address or a user agent.
#
#   bin/security-alerts.sh [--dry-run]      --dry-run prints what it would send and writes nothing
#
# 23 auth.bruteforce SEV2 | 24 auth.locked SEV3 | 25 auth.newdevice SEV2 | 26 auth.privileged SEV1 (an account other than the owner did it) or SEV2 |
# 28 admin.denied SEV2 (401+403 on /api/v1/admin in Caddy's log). A check that cannot read its source says nothing (healthcheck.sh tells when the
# database is down); a source that is unreadable is not a reason to open an incident here, and it is not a reason to close one either: the alert that
# was open stays exactly as it is (alerts_hold) until the source answers again, so there is no false "recuperado" and no new incident when it is back.
set -Euo pipefail
HERE="$(dirname "$0")"
# shellcheck source=bin/lib.sh
. "$HERE/lib.sh"
# shellcheck source=bin/alerts_lib.sh
. "$HERE/alerts_lib.sh"
# shellcheck source=bin/security_alerts_sql.sh
. "$HERE/security_alerts_sql.sh"

[[ "${1:-}" == "--dry-run" ]] && export ALERTS_DRY_RUN=1
exec 9> "$STATE/security-alerts.lock"
flock -n 9 || { log "security-alerts: another run holds the lock"; exit 0; }

ACCESS="${ACCESS_LOG:-$PREDIGOL_DATA/caddy/data/access.log}"
num() { [[ "$1" =~ ^[0-9]+$ ]]; }

alerts_begin security

# 23. failed sign-ins
n="$(psql_q "$SQL_FAILED" 2> /dev/null || echo "?")"
num "$n" || alerts_hold auth.bruteforce
if num "$n" && (( n > 20 )); then alert_set auth.bruteforce SEV2 "$n inicios de sesión fallidos en 5 min"; fi

# 24. accounts on hold
r="$(psql_q "$SQL_LOCKED" 2> /dev/null || echo "?")"
[[ "$r" =~ ^([0-9]+)\|([0-9,]*)$ ]] || alerts_hold auth.locked
if [[ "$r" =~ ^([0-9]+)\|([0-9,]*)$ ]] && (( BASH_REMATCH[1] > 0 )); then
  alert_set auth.locked SEV3 "${BASH_REMATCH[1]} cuenta(s) en espera en la última hora (id ${BASH_REMATCH[2]})"
fi

# 25. an administrator from a new browser
r="$(psql_q "$SQL_NEWDEVICE" 2> /dev/null || echo "?")"
[[ "$r" =~ ^([0-9]+)\|([0-9,]*)$ ]] || alerts_hold auth.newdevice
if [[ "$r" =~ ^([0-9]+)\|([0-9,]*)$ ]] && (( BASH_REMATCH[1] > 0 )); then
  alert_set auth.newdevice SEV2 "inicio de sesión de administrador desde un navegador nuevo (id ${BASH_REMATCH[2]})"
fi

# 26. privileged changes
owner="${PREDIGOL_OWNER_USER_ID:-}"
num "$owner" || owner="$(psql_q "$SQL_OWNER" 2> /dev/null || echo "?")"
if num "$owner"; then
  r="$(psql_q "${SQL_PRIVILEGED//:owner/$owner}" 2> /dev/null || echo "?")"
  [[ "$r" =~ ^([0-9]+)\|([0-9]+)\|([0-9,]*)$ ]] || alerts_hold auth.privileged
  if [[ "$r" =~ ^([0-9]+)\|([0-9]+)\|([0-9,]*)$ ]] && (( BASH_REMATCH[1] > 0 )); then
    if (( BASH_REMATCH[2] > 0 )); then
      alert_set auth.privileged SEV1 "${BASH_REMATCH[1]} cambio(s) de rol, MFA o contraseña, ${BASH_REMATCH[2]} hecho(s) por otra cuenta que no es la del dueño (id ${BASH_REMATCH[3]})"
    else
      alert_set auth.privileged SEV2 "${BASH_REMATCH[1]} cambio(s) de rol, MFA o contraseña (id ${BASH_REMATCH[3]})"
    fi
  fi
else
  alerts_hold auth.privileged   # who the owner is could not be read: no guess, and nothing open is closed
fi

# 28. 401 and 403 on the administrator's routes, from Caddy's access log (last 10 minutes)
if [[ -r "$ACCESS" ]]; then
  since=$(( $(date +%s) - 600 ))
  n="$(tail -n 50000 "$ACCESS" | jq -r --argjson since "$since" 'select((.ts // 0) >= $since and ((.status // 0) == 401 or (.status // 0) == 403) and ((.request.uri // "") | startswith("/api/v1/admin"))) | .status' 2> /dev/null | wc -l)"
  if num "$n" && (( n > 20 )); then alert_set admin.denied SEV2 "$n respuestas 401/403 en rutas de administrador en 10 min"; fi
else
  alerts_hold admin.denied   # the log cannot be read (rotating, or Caddy not started): nothing open is closed
fi

alerts_end
