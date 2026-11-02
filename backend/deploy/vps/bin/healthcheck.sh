#!/usr/bin/env bash
# Every 5 minutes (predigol-health.timer): is PrediGol serving, capturing and backed up?
#
#   bin/healthcheck.sh [--quiet]
#
# One line per check. The verdict goes to $PREDIGOL_DATA/state/health.json; when it CHANGES the owner is told
# (Telegram, if configured), and every run pings Healthchecks.io (if configured) - so a server that stops
# running this script is noticed too. A worker whose heartbeat stopped is restarted, at most once an hour.
# Exit 0 no problem (warnings allowed), 1 at least one problem.
# Alerts (security plan S3): each failing check also calls alert_set (alerts_lib.sh); alerts_end sends ONE message per change of state,
# a reminder every hour for a SEV1 that stays open, and keeps the incident register (state/incidents.jsonl).
set -Euo pipefail
# shellcheck source=bin/lib.sh
. "$(dirname "$0")/lib.sh"
# shellcheck source=bin/alerts_lib.sh
. "$(dirname "$0")/alerts_lib.sh"
# shellcheck source=bin/alerts_checks.sh
. "$(dirname "$0")/alerts_checks.sh"

QUIET=0
[[ "${1:-}" == "--quiet" ]] && QUIET=1
problems=()
warnings=()
say() { (( QUIET )) || log "$*"; }
problem() { problems+=("$1"); say "PROBLEM $1"; }
warning() { warnings+=("$1"); say "warning $1"; }
alerts_begin
# A deploy restarts containers on purpose: while one runs, the container and front-door alerts wait (the deploy tells its own failures).
DEPLOYING=0
if deploying; then DEPLOYING=1; fi
alert_unless_deploy() { if (( DEPLOYING )); then return 0; fi; alert_set "$@"; }

DOMAIN="${PREDIGOL_DOMAIN:?PREDIGOL_DOMAIN}"
CURL=(curl -fsS -m 15 --resolve "$DOMAIN:443:127.0.0.1")
# Internal mode (no domain yet) and the rehearsal (*.localhost) are signed by Caddy's own authority (lib.sh);
# production by Let's Encrypt or Cloudflare's origin authority.
if uses_local_ca && [[ -r "$LOCAL_CA" ]]; then CURL+=(--cacert "$LOCAL_CA"); fi

# 1. Containers: running, and not unhealthy.
for svc in postgres api worker web caddy; do
  st="$(docker inspect -f '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' "predigol-$svc" 2> /dev/null || echo missing)"
  case "$st" in
    "running healthy" | "running ") say "ok   $svc running" ;;
    "running starting") warning "$svc starting" ;;
    *) problem "$svc: $st"; alert_unless_deploy "svc.$svc" SEV1 "el contenedor $svc no está sano ($(svc_state_es "$st"))" ;;
  esac
done

# 2. Through the front door, as a visitor: HTTPS, the API's health, the web app.
if body="$("${CURL[@]}" "https://$DOMAIN/health" 2> /dev/null)"; then
  status="$(jq -r .status <<< "$body" 2> /dev/null || echo unreadable)"
  case "$status" in
    ok) say "ok   https://$DOMAIN/health: ok" ;;
    degraded) alert_set web.degraded SEV2 "la API informa salud degradada (detalle en health.json)"; warning "health degraded: $(jq -r '[to_entries[] | select(.value|type=="object" and .status!="ok") | .key + "=" + .value.status] | join(", ")' <<< "$body")" ;;
    *) problem "health: $status"; alert_unless_deploy web.health SEV1 "la web no devuelve ok en /health" ;;
  esac
else
  problem "https://$DOMAIN/health does not answer"
  alert_unless_deploy web.health SEV1 "la web no responde en /health"
fi
if "${CURL[@]}" -o /dev/null "https://$DOMAIN/login"; then say "ok   https://$DOMAIN/login"; else problem "the web app does not answer"; alert_unless_deploy web.login SEV1 "la web no responde en /login"; fi

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
    alert_set worker.heartbeat SEV1 "el worker dejó de latir; lo reinicié"
  else
    problem "worker heartbeat stopped (already restarted within the hour)"
    alert_set worker.heartbeat SEV1 "el worker sigue sin latir (ya se reinició hace menos de una hora)"
  fi
fi

# 4. While matches are being played, the in-play capture must be ticking. "Being played" is what fbi.core.match_state
#    believes: a stored in-play code counts for 3 h 30 min after kick-off (LIVE_STALE_AFTER) and no longer. The provider
#    leaves some matches at INT (interrupted) for days (Rayo Vallecano - Athletic, 10 Oct 2026; two more on 22 Oct); counted
#    as "in play" they kept this verdict at "problem" for days, with nothing to capture, and an alarm that is always on
#    hides the day it is true.
playing="$(psql_q "SELECT count(*) FROM core.fixtures WHERE status_group = 'live' AND kickoff_at > now() - interval '210 minutes'" 2> /dev/null || echo "?")"
if [[ "$playing" =~ ^[0-9]+$ ]] && (( playing > 0 )); then
  age="$(psql_q "SELECT coalesce(extract(epoch FROM now() - max(started_at))::int, 999999) FROM raw.ingestion_runs WHERE job_type = 'live_odds_capture'")"
  if (( age > 600 )); then problem "$playing matches in play, last in-play capture ${age}s ago"
    alert_set ingest.live SEV2 "$playing partido(s) en juego y la última captura en vivo fue hace $(( age / 60 )) min"
  else say "ok   in-play capture ${age}s ago ($playing in play)"; fi
fi

# 5. Disk.
used="$(df -P "$PREDIGOL_DATA" | awk 'NR==2 {gsub("%",""); print $5}')"
if (( used >= 92 )); then problem "disk ${used}% used"; elif (( used >= 85 )); then warning "disk ${used}% used"; else say "ok   disk ${used}%"; fi
if (( used >= 90 )); then alert_set disk.usage SEV1 "el disco está al ${used} %"; elif (( used >= 80 )); then alert_set disk.usage SEV2 "el disco está al ${used} %"; fi

# 6. Backups: a dump younger than 26 h, and a restore test that passed within 8 days.
newest="$(find "$DB_BACKUPS" -maxdepth 1 -name 'predigol-*.json' -printf '%T@\n' | sort -nr | head -n 1)"
if [[ -z "$newest" ]]; then problem "no backup yet"; alert_set backup.local SEV2 "todavía no hay ninguna copia local"
elif (( $(date +%s) - ${newest%.*} > 26 * 3600 )); then problem "newest backup older than 26 h"; alert_set backup.local SEV2 "la copia local más reciente tiene más de 26 h"
else say "ok   backup $(( ($(date +%s) - ${newest%.*}) / 3600 )) h old"; fi
if [[ -r "$STATE/restore-test.json" ]]; then
  passed="$(jq -r .passed "$STATE/restore-test.json")"
  tested="$(date -d "$(jq -r .tested_at "$STATE/restore-test.json")" +%s 2> /dev/null || echo 0)"
  if [[ "$passed" == null ]]; then warning "the last restore test was skipped: $(jq -r '.skipped // "?"' "$STATE/restore-test.json")"
  elif [[ "$passed" != true ]]; then problem "the last restore test failed"; alert_set restore.test SEV2 "el último ensayo de restauración falló"
  elif (( $(date +%s) - tested > 8 * 86400 )); then warning "no restore test in 8 days"; alert_set restore.test SEV2 "hace más de 8 días que no hay un ensayo de restauración correcto"
  else say "ok   restore test passed"; fi
else
  warning "no restore test yet"
fi
# Off the server (only once configured, bin/r2-setup.sh): the newest dump whose copy was VERIFIED there is under 26 h old, the
# RAW store was synced recently, and the bucket's locks held the last time they were proven (bin/r2-lock-check.sh).
if [[ -n "${BACKUP_RCLONE_REMOTE:-}" ]]; then
  last_offsite=""
  for f in $(ls -t "$DB_BACKUPS"/predigol-*.json 2> /dev/null | head -n 30); do
    last_offsite="$(jq -r '.offsite.verified_at // empty' "$f" 2> /dev/null)"
    [[ -n "$last_offsite" ]] && break
  done
  if [[ -z "$last_offsite" ]]; then
    warning "no dump has been copied off the server yet"; alert_set backup.offsite SEV3 "todavía no hay ninguna copia verificada fuera del servidor"
  else
    off_age=$(( $(date +%s) - $(date -d "$last_offsite" +%s 2> /dev/null || echo 0) ))
    if (( off_age > 26 * 3600 )); then problem "the newest dump copied off the server is $(( off_age / 3600 )) h old"; alert_set backup.offsite SEV2 "la copia más reciente fuera del servidor tiene $(( off_age / 3600 )) h"; if (( off_age > 72 * 3600 )); then alert_set backup.offsite SEV1 "la copia más reciente fuera del servidor tiene más de 3 días"; fi
    else say "ok   off-server copy $(( off_age / 3600 )) h old"; fi
  fi
  if [[ -r "$STATE/lock-check.json" ]]; then
    if [[ "$(jq -r .passed "$STATE/lock-check.json" 2> /dev/null)" != true ]]; then
      problem "the last bucket-lock check FAILED: the copies off the server could be erased (bin/r2-lock-check.sh)"; alert_set backup.locks SEV1 "falló la última comprobación de los candados del cubo: las copias fuera del servidor podrían borrarse"
    else
      lock_age=$(( $(date +%s) - $(date -d "$(jq -r .checked_at "$STATE/lock-check.json")" +%s 2> /dev/null || echo 0) ))
      if (( lock_age > 10 * 86400 )); then warning "the bucket locks were last proven $(( lock_age / 86400 )) days ago"; alert_set backup.locks SEV3 "los candados del cubo se comprobaron por última vez hace $(( lock_age / 86400 )) días"
      else say "ok   bucket locks proven $(( lock_age / 86400 )) days ago"; fi
    fi
  else
    warning "the bucket locks have not been proven yet (bin/r2-lock-check.sh)"
  fi
fi
if [[ -n "${RAW_RCLONE_REMOTE:-}" ]]; then
  if [[ -r "$STATE/raw-sync.json" ]]; then
    raw_age=$(( $(date +%s) - $(date -d "$(jq -r .synced_at "$STATE/raw-sync.json")" +%s 2> /dev/null || echo 0) ))
    if (( raw_age > 12 * 3600 )); then problem "the RAW store was last copied off the server $(( raw_age / 3600 )) h ago"; alert_set raw.sync SEV2 "el almacén RAW se copió fuera del servidor por última vez hace $(( raw_age / 3600 )) h"
    elif (( raw_age > 3 * 3600 )); then warning "the RAW sync has not run for $(( raw_age / 3600 )) h"
    else say "ok   RAW synced $(( raw_age / 60 )) min ago"; fi
    raw_empty="$(jq -r '.empty_recent_files // 0' "$STATE/raw-sync.json" 2> /dev/null || echo 0)"
    [[ "$raw_empty" =~ ^[0-9]+$ ]] && (( raw_empty > 0 )) && warning "$raw_empty empty file(s) written to the RAW store in the last 7 days were not copied off the server"
    # The hourly pass looks at today's and yesterday's directories only; the daily FULL pass is what finds anything elsewhere.
    raw_full="$(jq -r '.full_at // empty' "$STATE/raw-sync.json" 2> /dev/null || true)"
    if [[ -z "$raw_full" ]]; then
      warning "no full RAW pass has finished yet (bin/raw-sync.sh --full)"
    else
      full_age=$(( $(date +%s) - $(date -d "$raw_full" +%s 2> /dev/null || echo 0) ))
      if (( full_age > 5 * 86400 )); then problem "the last full RAW pass was $(( full_age / 86400 )) days ago: a file outside today's and yesterday's directories is not being copied"; alert_set raw.full SEV2 "la última pasada completa del RAW fue hace $(( full_age / 86400 )) días"
      elif (( full_age > 36 * 3600 )); then warning "the last full RAW pass was $(( full_age / 3600 )) h ago"
      else say "ok   full RAW pass $(( full_age / 3600 )) h ago"; fi
    fi
  else
    warning "no RAW sync yet (bin/raw-sync.sh)"
  fi
fi

# 7. The certificate (Let's Encrypt renews it from 30 days before; under 14 something is wrong). Caddy's own
# authority issues 12-hour certificates and renews them itself: nothing to count in days there.
if ! uses_local_ca; then
  end="$(echo | openssl s_client -connect 127.0.0.1:443 -servername "$DOMAIN" 2> /dev/null | openssl x509 -noout -enddate 2> /dev/null | cut -d= -f2)"
  if [[ -n "$end" ]]; then
    days=$(( ($(date -d "$end" +%s) - $(date +%s)) / 86400 ))
    if (( days < 7 )); then problem "certificate expires in $days days"; elif (( days < 14 )); then warning "certificate expires in $days days"; else say "ok   certificate $days days"; fi
    if (( days < 7 )); then alert_set tls.origin SEV1 "el certificado caduca en $days días"; elif (( days < 20 )); then alert_set tls.origin SEV2 "el certificado caduca en $days días"; fi
  else
    problem "no certificate served on 443"
    alert_set tls.origin SEV1 "el puerto 443 no sirve ningún certificado"
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
    alert_set host.resources SEV2 "el servidor está sobrecargado: CPU robada al ${steal} % durante $(( streak * 5 )) min"
  elif (( steal >= 15 )); then warning "CPU steal ${steal}%"
  else say "ok   CPU steal ${steal}%"; fi
fi
echo "$total $st" > "$STATE/cpu.prev"
mem_total="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)"; mem_avail="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
swap_total="$(awk '/^SwapTotal:/ {print $2}' /proc/meminfo)"; swap_free="$(awk '/^SwapFree:/ {print $2}' /proc/meminfo)"
mem_pct=$(( 100 * mem_avail / mem_total ))
if (( mem_pct < 8 )); then problem "memory: ${mem_pct}% available"; elif (( mem_pct < 15 )); then warning "memory: ${mem_pct}% available"; else say "ok   memory ${mem_pct}% available"; fi
if (( mem_pct < 8 )); then alert_set host.resources SEV2 "queda un ${mem_pct} % de memoria disponible"; fi
if (( swap_total > 0 )) && (( 100 * (swap_total - swap_free) / swap_total > 50 )); then warning "swap more than half used"; fi
load1="$(cut -d' ' -f1 /proc/loadavg)"
if awk -v l="$load1" -v c="$(nproc)" 'BEGIN { exit !(l > 2 * c) }'; then warning "load $load1 on $(nproc) CPUs"; fi

# 9. PostgreSQL: connections, WAL archiving and the PITR backups (when configured).
conn_pct="$(psql_q "SELECT count(*) * 100 / current_setting('max_connections')::int FROM pg_stat_activity" 2> /dev/null || echo "?")"
if [[ "$conn_pct" =~ ^[0-9]+$ ]]; then
  if (( conn_pct >= 80 )); then warning "PostgreSQL connections at ${conn_pct}% of the maximum"; alert_set db.connections SEV2 "PostgreSQL usa el ${conn_pct} % de las conexiones"; else say "ok   connections ${conn_pct}%"; fi
fi
if [[ -n "${PITR_S3_BUCKET:-}" ]]; then
  arch="$(psql_q "SELECT coalesce(extract(epoch FROM now() - last_archived_time)::int, -1) || ' ' || (coalesce(last_failed_time, 'epoch') > coalesce(last_archived_time, 'epoch'))::text FROM pg_stat_archiver" 2> /dev/null || echo "? ?")"
  arch_age="${arch%% *}"; arch_failing="${arch##* }"
  if [[ "$arch_failing" == true ]]; then problem "WAL archiving to the PITR repository is FAILING"; alert_set pitr.wal SEV1 "el archivado de WAL hacia el repositorio PITR está fallando"
  elif [[ "$arch_age" =~ ^-?[0-9]+$ ]] && (( arch_age < 0 || arch_age > 3600 )); then problem "no WAL archived for over an hour"; alert_set pitr.wal SEV1 "hace más de una hora que no se archiva WAL"
  elif [[ "$arch_age" =~ ^[0-9]+$ ]] && (( arch_age > 900 )); then warning "last WAL archived ${arch_age}s ago"; alert_set pitr.wal SEV1 "el último WAL se archivó hace $(( arch_age / 60 )) min"
  else say "ok   WAL archived ${arch_age}s ago"; fi
  if [[ -r "$STATE/pitr-backup.json" ]]; then
    pitr_at="$(date -d "$(jq -r .backed_up_at "$STATE/pitr-backup.json")" +%s 2> /dev/null || echo 0)"
    if (( $(date +%s) - pitr_at > 26 * 3600 )); then problem "PITR base backup older than 26 h"; alert_set pitr.backup SEV2 "la copia base PITR tiene más de 26 h"; else say "ok   PITR backup $(( ($(date +%s) - pitr_at) / 3600 )) h old"; fi
  else
    warning "no PITR base backup yet (bin/pitr.sh init, then backup)"
  fi
  [[ "$(jq -r .passed "$STATE/pitr-verify.json" 2> /dev/null)" == false ]] && { problem "the last PITR repository verification failed"; alert_set pitr.test SEV2 "falló la última verificación del repositorio PITR"; }
  [[ "$(jq -r .passed "$STATE/pitr-test.json" 2> /dev/null)" == false ]] && { problem "the last PITR restore test failed"; alert_set pitr.test SEV2 "falló el último ensayo de restauración PITR"; }
fi

# 10. The data: API-Football quota, runs stuck or failing.
quota="$(psql_q "SELECT coalesce(max(spent * 100 / budget), 0) FROM raw.provider_quota WHERE quota_date = (now() AT TIME ZONE 'UTC')::date" 2> /dev/null || echo "?")"
if [[ "$quota" =~ ^[0-9]+$ ]]; then
  if (( quota >= 100 )); then problem "API-Football daily budget spent (${quota}%)"; alert_set provider.quota SEV2 "se agotó el presupuesto diario de API-Football"
  elif (( quota >= 90 )); then warning "API-Football daily budget at ${quota}%"; alert_set provider.quota SEV2 "el presupuesto diario de API-Football va por el ${quota} %"
  else say "ok   API-Football budget ${quota}%"; fi
fi
stuck="$(psql_q "SELECT count(*) FROM raw.ingestion_runs WHERE status = 'running' AND started_at < now() - interval '2 hours'" 2> /dev/null || echo "?")"
[[ "$stuck" =~ ^[0-9]+$ ]] && (( stuck > 0 )) && warning "$stuck run(s) running for more than 2 h"
failed="$(psql_q "SELECT count(*) FROM raw.ingestion_runs WHERE status = 'failed' AND started_at > now() - interval '1 hour'" 2> /dev/null || echo "?")"
if [[ "$failed" =~ ^[0-9]+$ ]]; then
  if (( failed >= 20 )); then problem "$failed failed runs in the last hour (provider or network?)"; alert_set ingest.runs SEV2 "$failed ejecuciones de ingesta fallidas en la última hora"
  elif (( failed >= 5 )); then warning "$failed failed runs in the last hour"; fi
fi

# 11. What visitors got: server errors in the last 5 minutes (Caddy's access log).
ACCESS="$PREDIGOL_DATA/caddy/data/access.log"
if [[ -r "$ACCESS" ]]; then
  since=$(( $(date +%s) - 300 ))
  errors="$(tail -n 20000 "$ACCESS" | jq -r --argjson since "$since" 'select((.ts // 0) >= $since and (.status // 0) >= 500) | .status' 2> /dev/null | wc -l)"
  if after_deploy; then
    # The seconds of 502 while a deploy or a rollback recreates the API are in this count for the next five minutes: no problem for the verdict (which pings the
    # outside monitor) and no alert. One that is already open stays as it is; the first pass after the change judges it. A release that really breaks the site is
    # told by web.health and svc.<name> (the deploy itself has finished, so DEPLOYING is 0 by then), not by this count.
    if (( errors >= 10 )); then warning "$errors server errors (5xx) in 5 min (a deploy or a rollback finished in the last few minutes)"
    else say "ok   $errors server errors in 5 min"; fi
    if (( errors > 20 )); then alerts_hold web.errors5xx; fi
  else
    if (( errors >= 50 )); then problem "$errors server errors (5xx) in 5 min"
    elif (( errors >= 10 )); then warning "$errors server errors (5xx) in 5 min"
    else say "ok   $errors server errors in 5 min"; fi
    if (( errors > 20 )); then alert_set web.errors5xx SEV2 "$errors errores 5xx en 5 min"; fi
  fi
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
    if (( days_left < 14 )); then alert_set disk.forecast SEV2 "al ritmo actual el disco llega al 90 % en unos $days_left días (+$(( per_day / 1024 )) MB/día)"; fi
  fi
fi

# 13. What the plan of section 20 adds: restart loops, sign-in enforced, configuration against its baseline.
check_restart_loops
check_auth_me
check_config_drift
check_picks_unsettled
check_db_hold   # last: a database that did not answer keeps the alerts that come from it as they are

verdict="ok"
(( ${#warnings[@]} )) && verdict="warning"
(( ${#problems[@]} )) && verdict="problem"
jq -n --arg at "$(date -u +%FT%TZ)" --arg status "$verdict" \
  --argjson problems "$(printf '%s\n' "${problems[@]}" | jq -R . | jq -s 'map(select(length > 0))')" \
  --argjson warnings "$(printf '%s\n' "${warnings[@]}" | jq -R . | jq -s 'map(select(length > 0))')" \
  '{checked_at: $at, status: $status, problems: $problems, warnings: $warnings}' > "$STATE/health.json"
alerts_end   # replaces the old "tell the owner when the verdict changes": one message per alert, per change of state
say "verdict: $verdict"
if (( ${#problems[@]} )); then ping_hc "${HC_PING_HEALTH:-}" fail; exit 1; fi
ping_hc "${HC_PING_HEALTH:-}"
