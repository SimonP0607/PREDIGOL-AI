#!/usr/bin/env bash
# alerts_checks.sh - security plan S3: the checks that healthcheck.sh did not have. Sourced by healthcheck.sh AFTER lib.sh and alerts_lib.sh,
# between alerts_begin and alerts_end. Each function only calls alert_set (and writes its own state files): it never sends, never exits.
# Needs: STATE, log, alert_set, alerts_hold, alert_unless_deploy (healthcheck.sh), psql_q (lib.sh) for the two database checks, and for
# check_auth_me the CURL array and DOMAIN of healthcheck.sh.
#
#   check_restart_loops   svc.<name>.loop  SEV1  a container restarted 3 times or more within 15 minutes (Docker's RestartCount)
#   check_auth_me         api.login        SEV1  /api/v1/auth/me WITHOUT a session must answer 401 (a 2xx means sign-in is not being enforced)
#   check_config_drift    config.drift     SEV2  the sha256 of the configuration files differs from the baseline (config_baseline_write; bin/config-baseline.sh takes it
#                                                at the end of every deploy and rollback, and by hand with `predigolctl config-baseline`)
#   check_picks_unsettled picks.unsettled  SEV2  picks of matches that finished more than 3 h ago are still not settled (the settlement job is not running)
#                         picks.review     SEV3  ... or they wait with a recorded reason (a result that is missing or cannot be derived)
#   check_db_hold         -                the database did not answer: the alerts that come from it stay as they are (alerts_hold), they do not close
#   svc_state_es          -                (helper) the state of a container in Spanish for the svc.<name> alert text: "missing" -> "no existe"
#   after_deploy [secs]   -                (helper) true while the newest line of state/deploys.log (a deploy or a rollback) is younger than that (360 s by default)
#
# Never a file's content in a message or a state file: names and hashes only.

# --- the state of a container, in words the owner reads ---------------------------------------------------------------------------------------
# healthcheck.sh keeps "docker inspect" as the state: "running healthy", "running unhealthy", "exited ", "missing" (no such container, or Docker does not answer)...
# The text of the alert says it in Spanish and never carries stray spaces ("( missing)"). Anything not listed is shown as Docker wrote it, trimmed.
svc_state_es() {
  local t
  t="$(tr -s '[:space:]' ' ' <<< "$1" | sed 's/^ //; s/ $//')"
  case "$t" in
    "" | missing) echo "no existe o Docker no responde" ;;
    "running unhealthy") echo "en marcha, pero su comprobación de salud falla" ;;
    "running starting") echo "arrancando" ;;
    restarting*) echo "reiniciándose sin parar" ;;
    exited* | dead*) echo "parado" ;;
    created*) echo "creado, pero sin arrancar" ;;
    paused*) echo "en pausa" ;;
    *) echo "estado: $t" ;;
  esac
}

# --- a deploy or a rollback ran a moment ago ----------------------------------------------------------------------------------------------
# A deploy recreates the API (a rollback too): for those seconds Caddy answers 502, and they stay in the count of server errors of the last 5 minutes for the
# next five. They are expected: they are not a reason to tell the owner and not a problem for the verdict (which also pings the outside monitor). The line of
# state/deploys.log is written when the deploy has finished (a rollback writes it right after starting the containers), so the window is the 5 minutes of the
# count plus one more for the seconds a rollback still needs and for the timer's jitter. A date that is not a date, one in the future, or no file: not a deploy.
after_deploy() {
  local last t now=${CHECKS_NOW:-$(date +%s)}
  last="$(tail -n 1 "$STATE/deploys.log" 2> /dev/null | cut -f1)"
  [[ -n "$last" ]] || return 1
  t="$(date -u -d "$last" +%s 2> /dev/null)" || return 1
  (( now >= t && now - t < ${1:-360} ))
}

# --- picks that were not settled --------------------------------------------------------------------------------------------------------------
# The product settles a finished match within minutes (picks.settlement_latency). Hours later it means the settlement job is not running (SEV2), or the
# match carries a recorded reason to wait (picks.pick_results.review_reason: "finished, but no regulation score is recorded"...; SEV3).
# What counts: a match with status FT, AET or PEN and its result stored (core.fixture_results.settled_at) more than UNSETTLED_AFTER_H hours ago, whose picks are
# not 'settled' (the same test as OPEN_PICKS_SQL in fbi/picks/engine.py). Postponed, suspended and abandoned matches wait on purpose (void 72 h after kick-off)
# and a cancelled one is void at once: none of them is counted. Only kick-offs of the last UNSETTLED_WINDOW_D days are read (index on kickoff_at, then the
# index on picks.fixture_id). Counts only: no pick, no match name.
UNSETTLED_AFTER_H=${UNSETTLED_AFTER_H:-3}
UNSETTLED_WINDOW_D=${UNSETTLED_WINDOW_D:-7}
sql_picks_unsettled() {  # "stuck_picks stuck_matches review_picks review_matches oldest_stuck_hours"
  local after=$UNSETTLED_AFTER_H win=$UNSETTLED_WINDOW_D
  [[ "$after" =~ ^[0-9]+$ && "$win" =~ ^[0-9]+$ ]] || return 1
  cat << SQL
SET statement_timeout = '20s'; SELECT
       count(*) FILTER (WHERE coalesce(pr.review_reason, '') = '') || ' ' ||
       count(DISTINCT p.fixture_id) FILTER (WHERE coalesce(pr.review_reason, '') = '') || ' ' ||
       count(*) FILTER (WHERE coalesce(pr.review_reason, '') <> '') || ' ' ||
       count(DISTINCT p.fixture_id) FILTER (WHERE coalesce(pr.review_reason, '') <> '') || ' ' ||
       coalesce((extract(epoch FROM now() - min(greatest(r.settled_at, p.created_at)) FILTER (WHERE coalesce(pr.review_reason, '') = '')) / 3600)::int, 0)
  FROM core.fixtures f
  JOIN core.fixture_results r ON r.fixture_id = f.id
  JOIN picks.picks p ON p.fixture_id = f.id
  LEFT JOIN picks.pick_results pr ON pr.pick_id = p.id
 WHERE f.kickoff_at > now() - interval '$win days'
   AND upper(f.status_short) IN ('FT', 'AET', 'PEN')
   AND p.status <> 'settled'
   AND greatest(r.settled_at, p.created_at) < now() - interval '$after hours'
SQL
}
check_picks_unsettled() {
  local sql out stuck stuck_m review review_m oldest
  sql="$(sql_picks_unsettled)" || return 0
  out="$(psql_q "$sql" 2> /dev/null)" || return 0     # no answer: check_db_hold keeps what is open
  read -r stuck stuck_m review review_m oldest <<< "$out"
  [[ "$stuck" =~ ^[0-9]+$ && "$stuck_m" =~ ^[0-9]+$ && "$review" =~ ^[0-9]+$ && "$review_m" =~ ^[0-9]+$ && "$oldest" =~ ^[0-9]+$ ]] || return 0
  if (( stuck > 0 )); then
    alert_set picks.unsettled SEV2 "$stuck pick(s) de $stuck_m partido(s) terminados hace más de ${UNSETTLED_AFTER_H} h siguen sin liquidar (el más antiguo espera $oldest h)"
  fi
  if (( review > 0 )); then
    alert_set picks.review SEV3 "$review pick(s) de $review_m partido(s) terminados esperan revisión (el motivo está en picks.pick_results.review_reason)"
  fi
}

# --- a database that does not answer ----------------------------------------------------------------------------------------------------------
# A check that could not run is not a check that passed. The alerts whose source is the database stay exactly as they are when it does not answer
# (the container and front-door alerts tell that news): no false "recuperado" now and no new incident when it is back.
DB_ALERT_KEYS=(ingest.live ingest.runs provider.quota db.connections pitr.wal picks.unsettled picks.review)
check_db_hold() {
  psql_q "SELECT 1" > /dev/null 2>&1 || alerts_hold "${DB_ALERT_KEYS[@]}"
}

RESTART_WINDOW=${RESTART_WINDOW:-960}      # 15 min + 60 s of timer jitter
RESTART_MIN=${RESTART_MIN:-3}

check_restart_loops() {
  local svc now count file first_t first_c
  now=${CHECKS_NOW:-$(date +%s)}
  for svc in postgres api worker web caddy; do
    count="$(docker inspect -f '{{.RestartCount}}' "predigol-$svc" 2> /dev/null)" || continue
    [[ "$count" =~ ^[0-9]+$ ]] || continue
    file="$STATE/restarts.$svc"
    printf '%s %s\n' "$now" "$count" >> "$file"
    tail -n 6 "$file" > "$file.tmp" && mv -f "$file.tmp" "$file"
    first_t=""; first_c=""
    read -r first_t first_c < <(awk -v n="$now" '$1 >= n - '"$RESTART_WINDOW"' { print; exit }' "$file") || true
    [[ "$first_c" =~ ^[0-9]+$ ]] || continue
    if (( count - first_c >= RESTART_MIN )); then
      alert_unless_deploy "svc.$svc.loop" SEV1 "el contenedor $svc se ha reiniciado $(( count - first_c )) veces en $(( (now - first_t) / 60 )) min"
    fi
  done
}

check_auth_me() {
  local code
  code="$("${CURL[@]}" -o /dev/null -w '%{http_code}' "https://$DOMAIN/api/v1/auth/me" 2> /dev/null || true)"
  case "$code" in
    2??) alert_set api.login SEV1 "/auth/me responde $code sin sesión: el inicio de sesión no se está exigiendo" ;;
    404) alert_set api.login SEV3 "la comprobación de /auth/me no encuentra la ruta (¿cambió la API?)" ;;
  esac  # 401 is the answer we want; 5xx or no answer is web.health's job
}

# The files whose change must never be a surprise (section 20, alert 32: sshd, Caddyfile, compose; and the env files and the units, which are the other places
# where a hand edit changes what the server does). Paths are overridable for the tests.
config_files() {
  local vps=${VPS_DIR:-/opt/predigol/backend/deploy/vps} etc=${PREDIGOL_ETC:-/etc/predigol} ssh=${SSHD_DIR:-/etc/ssh}
  printf '%s\n' "$vps/Caddyfile" "$vps/docker-compose.yml" "$etc/predigol.env" "$etc/app.env" "$ssh/sshd_config" "$ssh"/sshd_config.d/*.conf \
    "$vps"/systemd/*.service "$vps"/systemd/*.timer
}
_config_hashes() {  # "<sha256>  <file>" per readable file, sorted by name; the content never leaves sha256sum
  local f
  # `if`, not `&&`: a name that is not a file (a glob that matched nothing, a file that is not there) must not make the whole list fail when it is the last one
  while IFS= read -r f; do
    if [[ -r "$f" && -f "$f" ]]; then sha256sum -- "$f"; fi
  done < <(config_files) | LC_ALL=C sort -k2
}
config_baseline_write() {  # run at the END of every planned change (deploy, rotation, a change by hand): the new state becomes the baseline
  _config_hashes > "$STATE/config.sha256.tmp" && mv -f "$STATE/config.sha256.tmp" "$STATE/config.sha256"
}
check_config_drift() {
  local base="$STATE/config.sha256" changed=() line f
  [[ -r "$base" ]] || return 0   # no baseline yet: nothing to compare with (not an incident)
  # While a deploy or a rollback runs, the checkout may already hold the new release and the baseline is taken only when it ends: no moment to judge. What was
  # open stays open (alerts_hold); the first pass after the change judges.
  if (( ${DEPLOYING:-0} )); then alerts_hold config.drift; return 0; fi
  local now_hashes; now_hashes="$(_config_hashes)"
  while IFS= read -r f; do
    [[ -n "$f" ]] || continue
    changed+=("$(basename -- "$f")")
  done < <(
    {
      # shellcheck disable=SC2001
      sed 's/^[0-9a-f]*  //' "$base"; sed 's/^[0-9a-f]*  //' <<< "$now_hashes"
    } | LC_ALL=C sort -u | while IFS= read -r line; do
      [[ -n "$line" ]] || continue
      # `|| true`: a file that is only in one of the two lists makes grep fail, and with `set -e` that would end this loop (and the list of changes) right there
      a="$(grep -F -- "  $line" "$base" | head -n 1 | cut -d' ' -f1)" || true
      b="$(grep -F -- "  $line" <<< "$now_hashes" | head -n 1 | cut -d' ' -f1)" || true
      [[ "$a" == "$b" ]] || echo "$line"
    done
  )
  if (( ${#changed[@]} )); then
    alert_set config.drift SEV2 "cambió la configuración respecto a la línea base: $(printf '%s, ' "${changed[@]}" | sed 's/, $//')"
  fi
}
