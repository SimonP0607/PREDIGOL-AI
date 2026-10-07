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
  if [[ "$passed" == null ]]; then warning "the last restore test was skipped: $(jq -r '.skipped // "?"' "$STATE/restore-test.json")"
  elif [[ "$passed" != true ]]; then problem "the last restore test failed"
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

# 8. The machine: CPU steal (a noisy neighbour on a shared host), load, memory, swap.
read -r _ u n sy id io irq sirq st _ < /proc/stat
total=$(( u + n + sy + id + io + irq + sirq + st ))
if [[ -r "$STATE/cpu.prev" ]] && read -r ptotal psteal < "$STATE/cpu.prev" && (( total > ptotal )); then
  steal=$(( 100 * (st - psteal) / (total - ptotal) ))
  streak="$(cat "$STATE/steal.streak" 2> /dev/null || echo 0)"
  if (( steal >= 15 )); then streak=$(( streak + 1 )); else streak=0; fi
  echo "$streak" > "$STATE/steal.streak"
  if (( streak >= 3 )); then problem "CPU steal ${steal}% for $(( streak * 5 )) min: the host is overloaded (INFRA_DECISION: plan B)"
  elif (( steal >= 15 )); then warning "CPU steal ${steal}%"
  else say "ok   CPU steal ${steal}%"; fi
fi
echo "$total $st" > "$STATE/cpu.prev"
mem_total="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)"; mem_avail="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
swap_total="$(awk '/^SwapTotal:/ {print $2}' /proc/meminfo)"; swap_free="$(awk '/^SwapFree:/ {print $2}' /proc/meminfo)"
mem_pct=$(( 100 * mem_avail / mem_total ))
if (( mem_pct < 8 )); then problem "memory: ${mem_pct}% available"; elif (( mem_pct < 15 )); then warning "memory: ${mem_pct}% available"; else say "ok   memory ${mem_pct}% available"; fi
if (( swap_total > 0 )) && (( 100 * (swap_total - swap_free) / swap_total > 50 )); then warning "swap more than half used"; fi
load1="$(cut -d' ' -f1 /proc/loadavg)"
if awk -v l="$load1" -v c="$(nproc)" 'BEGIN { exit !(l > 2 * c) }'; then warning "load $load1 on $(nproc) CPUs"; fi

# 9. PostgreSQL: connections, WAL archiving and the PITR backups (when configured).
conn_pct="$(psql_q "SELECT count(*) * 100 / current_setting('max_connections')::int FROM pg_stat_activity" 2> /dev/null || echo "?")"
if [[ "$conn_pct" =~ ^[0-9]+$ ]]; then
  if (( conn_pct >= 80 )); then warning "PostgreSQL connections at ${conn_pct}% of the maximum"; else say "ok   connections ${conn_pct}%"; fi
fi
if [[ -n "${PITR_S3_BUCKET:-}" ]]; then
  arch="$(psql_q "SELECT coalesce(extract(epoch FROM now() - last_archived_time)::int, -1) || ' ' || (coalesce(last_failed_time, 'epoch') > coalesce(last_archived_time, 'epoch'))::text FROM pg_stat_archiver" 2> /dev/null || echo "? ?")"
  arch_age="${arch%% *}"; arch_failing="${arch##* }"
  if [[ "$arch_failing" == true ]]; then problem "WAL archiving to the PITR repository is FAILING"
  elif [[ "$arch_age" =~ ^-?[0-9]+$ ]] && (( arch_age < 0 || arch_age > 3600 )); then problem "no WAL archived for over an hour"
  elif [[ "$arch_age" =~ ^[0-9]+$ ]] && (( arch_age > 900 )); then warning "last WAL archived ${arch_age}s ago"
  else say "ok   WAL archived ${arch_age}s ago"; fi
  if [[ -r "$STATE/pitr-backup.json" ]]; then
    pitr_at="$(date -d "$(jq -r .backed_up_at "$STATE/pitr-backup.json")" +%s 2> /dev/null || echo 0)"
    if (( $(date +%s) - pitr_at > 26 * 3600 )); then problem "PITR base backup older than 26 h"; else say "ok   PITR backup $(( ($(date +%s) - pitr_at) / 3600 )) h old"; fi
  else
    warning "no PITR base backup yet (bin/pitr.sh init, then backup)"
  fi
  [[ "$(jq -r .passed "$STATE/pitr-verify.json" 2> /dev/null)" == false ]] && problem "the last PITR repository verification failed"
  [[ "$(jq -r .passed "$STATE/pitr-test.json" 2> /dev/null)" == false ]] && problem "the last PITR restore test failed"
fi

# 10. The data: API-Football quota, runs stuck or failing.
quota="$(psql_q "SELECT coalesce(max(spent * 100 / budget), 0) FROM raw.provider_quota WHERE quota_date = (now() AT TIME ZONE 'UTC')::date" 2> /dev/null || echo "?")"
if [[ "$quota" =~ ^[0-9]+$ ]]; then
  if (( quota >= 100 )); then problem "API-Football daily budget spent (${quota}%)"
  elif (( quota >= 90 )); then warning "API-Football daily budget at ${quota}%"
  else say "ok   API-Football budget ${quota}%"; fi
fi
stuck="$(psql_q "SELECT count(*) FROM raw.ingestion_runs WHERE status = 'running' AND started_at < now() - interval '2 hours'" 2> /dev/null || echo "?")"
[[ "$stuck" =~ ^[0-9]+$ ]] && (( stuck > 0 )) && warning "$stuck run(s) running for more than 2 h"
failed="$(psql_q "SELECT count(*) FROM raw.ingestion_runs WHERE status = 'failed' AND started_at > now() - interval '1 hour'" 2> /dev/null || echo "?")"
if [[ "$failed" =~ ^[0-9]+$ ]]; then
  if (( failed >= 20 )); then problem "$failed failed runs in the last hour (provider or network?)"
  elif (( failed >= 5 )); then warning "$failed failed runs in the last hour"; fi
fi

# 11. What visitors got: server errors in the last 5 minutes (Caddy's access log).
ACCESS="$PREDIGOL_DATA/caddy/data/access.log"
if [[ -r "$ACCESS" ]]; then
  since=$(( $(date +%s) - 300 ))
  errors="$(tail -n 20000 "$ACCESS" | jq -r --argjson since "$since" 'select((.ts // 0) >= $since and (.status // 0) >= 500) | .status' 2> /dev/null | wc -l)"
  if (( errors >= 50 )); then problem "$errors server errors (5xx) in 5 min"
  elif (( errors >= 10 )); then warning "$errors server errors (5xx) in 5 min"
  else say "ok   $errors server errors in 5 min"; fi
fi

# 12. Disk forecast: one sample a day; warn when 90% is under 30 days away at the last week's pace.
today="$(date -u +%F)"
used_kb="$(df -Pk "$PREDIGOL_DATA" | awk 'NR==2 {print $3}')"; size_kb="$(df -Pk "$PREDIGOL_DATA" | awk 'NR==2 {print $2}')"
grep -q "^$today " "$STATE/disk.history" 2> /dev/null || echo "$today $used_kb" >> "$STATE/disk.history"
if (( $(wc -l < "$STATE/disk.history") >= 8 )); then
  read -r d0 u0 < <(tail -n 8 "$STATE/disk.history" | head -n 1)
  per_day=$(( (used_kb - u0) / 7 ))
  if (( per_day > 0 )); then
    days_left=$(( (size_kb * 9 / 10 - used_kb) / per_day ))
    if (( days_left < 30 )); then warning "disk at 90% in about $days_left days (+$(( per_day / 1024 )) MB/day since $d0)"
    else say "ok   disk 90% in about $days_left days"; fi
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
