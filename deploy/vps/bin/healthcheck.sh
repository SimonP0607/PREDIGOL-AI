#!/usr/bin/env bash
# Every 5 minutes (predigol-health.timer): is PrediGol serving, capturing and backed up?
#
#   bin/healthcheck.sh [--quiet]
#
# One line per check. The verdict goes to $PREDIGOL_DATA/state/health.json; when it CHANGES the owner is told
# (Telegram, if configured), and every run pings Healthchecks.io (if configured) - so a server that stops
# running this script is noticed too. A worker whose heartbeat stopped is restarted, at most once an hour.
# Exit 0 no problem (warnings allowed), 1 at least one problem.
set -Euo pipefail
# shellcheck source=bin/lib.sh
. "$(dirname "$0")/lib.sh"

QUIET=0
[[ "${1:-}" == "--quiet" ]] && QUIET=1
problems=()
warnings=()
say() { (( QUIET )) || log "$*"; }
problem() { problems+=("$1"); say "PROBLEM $1"; }
warning() { warnings+=("$1"); say "warning $1"; }

DOMAIN="${PREDIGOL_DOMAIN:?PREDIGOL_DOMAIN}"
CURL=(curl -fsS -m 15 --resolve "$DOMAIN:443:127.0.0.1")
LOCAL_CA="$PREDIGOL_DATA/caddy/data/caddy/pki/authorities/local/root.crt"
# The rehearsal (*.localhost) is signed by Caddy's own authority; production by Let's Encrypt.
[[ "$DOMAIN" == *.localhost && -r "$LOCAL_CA" ]] && CURL+=(--cacert "$LOCAL_CA")

# 1. Containers: running, and not unhealthy.
for svc in postgres api worker web caddy; do
  st="$(docker inspect -f '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' "predigol-$svc" 2> /dev/null || echo missing)"
  case "$st" in
    "running healthy" | "running ") say "ok   $svc running" ;;
    "running starting") warning "$svc starting" ;;
    *) problem "$svc: $st" ;;
  esac
done

# 2. Through the front door, as a visitor: HTTPS, the API's health, the web app.
if body="$("${CURL[@]}" "https://$DOMAIN/health" 2> /dev/null)"; then
  status="$(jq -r .status <<< "$body" 2> /dev/null || echo unreadable)"
  case "$status" in
    ok) say "ok   https://$DOMAIN/health: ok" ;;
    degraded) warning "health degraded: $(jq -r '[to_entries[] | select(.value|type=="object" and .status!="ok") | .key + "=" + .value.status] | join(", ")' <<< "$body")" ;;
    *) problem "health: $status" ;;
  esac
else
  problem "https://$DOMAIN/health does not answer"
fi
if "${CURL[@]}" -o /dev/null "https://$DOMAIN/login"; then say "ok   https://$DOMAIN/login"; else problem "the web app does not answer"; fi

# 3. The worker: its own heartbeat. Silent for too long and running: restart it, at most once an hour.
if compose exec -T worker python -m scripts.worker_alive > /dev/null 2>&1; then
  say "ok   worker alive"
elif deploying; then
  warning "worker not alive while a deploy runs (left alone)"
else
  last="$(cat "$STATE/worker-restarted" 2> /dev/null || echo 0)"
  if (( $(date +%s) - last > 3600 )); then
    date +%s > "$STATE/worker-restarted"
    compose restart worker > /dev/null 2>&1 || true
    problem "worker heartbeat stopped: restarted it"
    notify "el worker dejó de latir; lo reinicié"
  else
    problem "worker heartbeat stopped (already restarted within the hour)"
  fi
fi

# 4. While matches are being played, the in-play capture must be ticking.
playing="$(psql_q "SELECT count(*) FROM core.fixtures WHERE status_group = 'live'" 2> /dev/null || echo "?")"
if [[ "$playing" =~ ^[0-9]+$ ]] && (( playing > 0 )); then
  age="$(psql_q "SELECT coalesce(extract(epoch FROM now() - max(started_at))::int, 999999) FROM raw.ingestion_runs WHERE job_type = 'live_odds_capture'")"
  if (( age > 600 )); then problem "$playing matches in play, last in-play capture ${age}s ago"; else say "ok   in-play capture ${age}s ago ($playing in play)"; fi
fi

# 5. Disk.
used="$(df -P "$PREDIGOL_DATA" | awk 'NR==2 {gsub("%",""); print $5}')"
if (( used >= 92 )); then problem "disk ${used}% used"; elif (( used >= 85 )); then warning "disk ${used}% used"; else say "ok   disk ${used}%"; fi

# 6. Backups: a dump younger than 26 h, and a restore test that passed within 8 days.
newest="$(find "$DB_BACKUPS" -maxdepth 1 -name 'predigol-*.json' -printf '%T@\n' | sort -nr | head -n 1)"
if [[ -z "$newest" ]]; then problem "no backup yet"
elif (( $(date +%s) - ${newest%.*} > 26 * 3600 )); then problem "newest backup older than 26 h"
else say "ok   backup $(( ($(date +%s) - ${newest%.*}) / 3600 )) h old"; fi
if [[ -r "$STATE/restore-test.json" ]]; then
  passed="$(jq -r .passed "$STATE/restore-test.json")"
  tested="$(date -d "$(jq -r .tested_at "$STATE/restore-test.json")" +%s 2> /dev/null || echo 0)"
  if [[ "$passed" != true ]]; then problem "the last restore test failed"
  elif (( $(date +%s) - tested > 8 * 86400 )); then warning "no restore test in 8 days"
  else say "ok   restore test passed"; fi
else
  warning "no restore test yet"
fi

# 7. The certificate (Let's Encrypt renews it from 30 days before; under 14 something is wrong).
if [[ "$DOMAIN" != *.localhost ]]; then
  end="$(echo | openssl s_client -connect 127.0.0.1:443 -servername "$DOMAIN" 2> /dev/null | openssl x509 -noout -enddate 2> /dev/null | cut -d= -f2)"
  if [[ -n "$end" ]]; then
    days=$(( ($(date -d "$end" +%s) - $(date +%s)) / 86400 ))
    if (( days < 7 )); then problem "certificate expires in $days days"; elif (( days < 14 )); then warning "certificate expires in $days days"; else say "ok   certificate $days days"; fi
  else
    problem "no certificate served on 443"
  fi
fi

verdict="ok"
(( ${#warnings[@]} )) && verdict="warning"
(( ${#problems[@]} )) && verdict="problem"
previous="$(jq -r .status "$STATE/health.json" 2> /dev/null || echo unknown)"
jq -n --arg at "$(date -u +%FT%TZ)" --arg status "$verdict" \
  --argjson problems "$(printf '%s\n' "${problems[@]}" | jq -R . | jq -s 'map(select(length > 0))')" \
  --argjson warnings "$(printf '%s\n' "${warnings[@]}" | jq -R . | jq -s 'map(select(length > 0))')" \
  '{checked_at: $at, status: $status, problems: $problems, warnings: $warnings}' > "$STATE/health.json"
if [[ "$verdict" != "$previous" ]]; then
  case "$verdict" in
    problem) notify "PROBLEMA: ${problems[*]}" ;;
    ok) [[ "$previous" == problem ]] && notify "recuperado: todo en orden" ;;
  esac
fi
say "verdict: $verdict"
if (( ${#problems[@]} )); then ping_hc "${HC_PING_HEALTH:-}" fail; exit 1; fi
ping_hc "${HC_PING_HEALTH:-}"
