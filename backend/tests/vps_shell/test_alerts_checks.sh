#!/usr/bin/env bash
# Tests of alerts_checks.sh with a fake docker, a fake curl and temporary files. No network, no Docker, no production.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$(cd "$HERE/../../deploy/vps/bin" && pwd)   # the scripts under test: backend/deploy/vps/bin
PASS=0; FAIL=0
ok() { PASS=$((PASS + 1)); echo "ok   $*"; }
no() { FAIL=$((FAIL + 1)); echo "FAIL $*"; }
eq() { if [[ "$1" == "$2" ]]; then ok "$3"; else no "$3: got '$1', expected '$2'"; fi; }
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
STATE="$T/state"; mkdir -p "$STATE"
log() { :; }
CALLS="$T/calls"; : > "$CALLS"
alert_set() { printf '%s|%s|%s\n' "$1" "$2" "$3" >> "$CALLS"; }
alerts_hold() { printf 'HOLD|%s\n' "$*" >> "$CALLS"; }
psql_q() { printf '%s' "$1" > "$T/last_sql"; echo x >> "$T/psql_calls"; if [[ -n "${FAKE_PSQL_FAIL:-}" ]]; then return 1; fi; printf '%s' "${FAKE_PSQL:-}"; }   # command substitutions run it in a subshell: files, not variables
: > "$T/psql_calls"; psql_calls() { wc -l < "$T/psql_calls" | tr -d ' '; }
DEPLOYING=0
alert_unless_deploy() { if (( DEPLOYING )); then return 0; fi; alert_set "$@"; }
docker() { cat "$T/count.${*: -1}" 2> /dev/null || return 1; }   # docker inspect -f ... predigol-<svc>
fake_curl() { printf '%s' "${FAKE_CODE:-}"; }
CURL=(fake_curl); DOMAIN=example.test
# shellcheck source=../../deploy/vps/bin/alerts_checks.sh
. "$SRC/alerts_checks.sh"
calls() { wc -l < "$CALLS" | tr -d ' '; }
reset() { : > "$CALLS"; }
setc() { for s in postgres api worker web caddy; do echo 0 > "$T/count.predigol-$s"; done; }
setc
t0=1000000

# 1. restart loop: +3 within 15 minutes
for i in 0 1 2 3; do
  echo "$i" > "$T/count.predigol-api"
  CHECKS_NOW=$((t0 + i * 300)) check_restart_loops
  case $i in 0|1|2) eq "$(calls)" 0 "1 no alert at +$i restarts" ;; esac
done
eq "$(cat "$CALLS")" "svc.api.loop|SEV1|el contenedor api se ha reiniciado 3 veces en 15 min" "1 +3 restarts in 15 min opens svc.api.loop"
reset
# 2. a deploy in progress waits
DEPLOYING=1; echo 6 > "$T/count.predigol-api"; CHECKS_NOW=$((t0 + 1200)) check_restart_loops
eq "$(calls)" 0 "2 nothing while a deploy runs"
DEPLOYING=0
# 3. slow restarts (1 per 10 min) are not a loop; a recreate (count drops to 0) is not a loop
setc; rm -f "$STATE"/restarts.*; reset
for i in 0 1 2 3 4 5; do echo "$i" > "$T/count.predigol-web"; CHECKS_NOW=$((t0 + 5000 + i * 600)) check_restart_loops; done
eq "$(calls)" 0 "3 one restart every 10 min is not a loop"
echo 0 > "$T/count.predigol-web"; CHECKS_NOW=$((t0 + 9000)) check_restart_loops
eq "$(calls)" 0 "3 a recreated container (count back to 0) is not a loop"
# 4. a container that does not exist is skipped without an error
rm -f "$T/count.predigol-caddy"; CHECKS_NOW=$((t0 + 9300)) check_restart_loops; eq "$?" 0 "4 a missing container is skipped"

# 5. auth/me
reset
for c in 401 500 000 ""; do FAKE_CODE=$c check_auth_me; done
eq "$(calls)" 0 "5 401, 5xx, no answer: no api.login alert"
FAKE_CODE=200 check_auth_me; eq "$(tail -n 1 "$CALLS")" "api.login|SEV1|/auth/me responde 200 sin sesión: el inicio de sesión no se está exigiendo" "5 200 without a session is SEV1"
reset; FAKE_CODE=404 check_auth_me; eq "$(cut -d'|' -f1,2 "$CALLS")" "api.login|SEV3" "5 404 is a SEV3 about the probe"

# 6. configuration drift
export VPS_DIR="$T/vps" PREDIGOL_ETC="$T/etc" SSHD_DIR="$T/ssh"; mkdir -p "$VPS_DIR/systemd" "$PREDIGOL_ETC"
echo 'caddy a' > "$VPS_DIR/Caddyfile"; echo 'compose a' > "$VPS_DIR/docker-compose.yml"
echo 'SECRET=hunter2-should-never-appear' > "$PREDIGOL_ETC/app.env"; echo 'X=1' > "$PREDIGOL_ETC/predigol.env"
echo '[Unit]' > "$VPS_DIR/systemd/predigol-a.service"
reset; check_config_drift; eq "$(calls)" 0 "6 no baseline: no alert"
config_baseline_write
eq "$(wc -l < "$STATE/config.sha256" | tr -d ' ')" 5 "6 baseline holds 5 hashes"
if grep -q 'hunter2' "$STATE/config.sha256"; then no "6 baseline leaks content"; else ok "6 baseline holds hashes only"; fi
check_config_drift; eq "$(calls)" 0 "6 unchanged: no alert"
echo 'caddy b' > "$VPS_DIR/Caddyfile"; check_config_drift
eq "$(cat "$CALLS")" "config.drift|SEV2|cambió la configuración respecto a la línea base: Caddyfile" "6 a changed Caddyfile is named"
reset; echo 'SECRET=other-hunter3' > "$PREDIGOL_ETC/app.env"; check_config_drift
case "$(cat "$CALLS")" in *"app.env"*"Caddyfile"*|*"Caddyfile"*"app.env"*) ok "6 two changed files are both named" ;; *) no "6 two files: $(cat "$CALLS")" ;; esac
if grep -q 'hunter' "$CALLS"; then no "6 alert text leaks content"; else ok "6 alert text holds names only"; fi
reset; rm -f "$VPS_DIR/systemd/predigol-a.service"; check_config_drift
case "$(cat "$CALLS")" in *"predigol-a.service"*) ok "6 a removed file is named" ;; *) no "6 removed: $(cat "$CALLS")" ;; esac
reset; echo '[Unit]' > "$VPS_DIR/systemd/predigol-new.timer"; check_config_drift
case "$(cat "$CALLS")" in *"predigol-new.timer"*) ok "6 an added file is named" ;; *) no "6 added: $(cat "$CALLS")" ;; esac
config_baseline_write; reset; check_config_drift; eq "$(calls)" 0 "6 re-baselined: quiet again"
# 6b. sshd's configuration is in the list too (the plan names sshd, the Caddyfile and compose)
mkdir -p "$SSHD_DIR/sshd_config.d"; echo 'PasswordAuthentication no' > "$SSHD_DIR/sshd_config"; echo 'Port 22' > "$SSHD_DIR/sshd_config.d/50-x.conf"
reset; check_config_drift
case "$(cat "$CALLS")" in *"sshd_config"*"50-x.conf"*|*"50-x.conf"*"sshd_config"*) ok "6 a new sshd_config and its drop-in are named" ;; *) no "6 sshd new: $(cat "$CALLS")" ;; esac
config_baseline_write; reset; check_config_drift; eq "$(calls)" 0 "6 sshd: re-baselined, quiet"
eq "$(wc -l < "$STATE/config.sha256" | tr -d ' ')" 7 "6 the baseline now holds 7 hashes (5 + sshd_config + its drop-in)"
echo 'PasswordAuthentication yes' > "$SSHD_DIR/sshd_config"; check_config_drift
eq "$(cat "$CALLS")" "config.drift|SEV2|cambió la configuración respecto a la línea base: sshd_config" "6 a changed sshd_config is named"
reset; echo 'Port 2222' > "$SSHD_DIR/sshd_config.d/50-x.conf"; check_config_drift
case "$(cat "$CALLS")" in *"50-x.conf"*) ok "6 a changed drop-in of sshd is named" ;; *) no "6 drop-in: $(cat "$CALLS")" ;; esac
config_baseline_write
# 6c. while a deploy or a rollback runs there is no judgement, and what was open stays open
DEPLOYING=1; reset; echo 'caddy c' > "$VPS_DIR/Caddyfile"; check_config_drift
eq "$(cat "$CALLS")" "HOLD|config.drift" "6 while a deploy runs the alert is held and nothing is raised"
DEPLOYING=0; reset; check_config_drift
eq "$(cut -d'|' -f1,2 "$CALLS")" "config.drift|SEV2" "6 once it is over the drift is raised"
config_baseline_write; reset; DEPLOYING=1; check_config_drift; eq "$(cat "$CALLS")" "HOLD|config.drift" "6 a deploy with nothing changed holds it too (it is not judged either way)"; DEPLOYING=0
# 6d. as the scripts run (set -e and pipefail) a list whose LAST name is not a file (no timer: the glob matches nothing) still hashes the rest
rm -f "$VPS_DIR"/systemd/*.timer
( set -Eeuo pipefail; config_baseline_write ); eq "$?" 0 "6 the last name of the list is not a file: the baseline is still taken"
eq "$(wc -l < "$STATE/config.sha256" | tr -d ' ')" 6 "6 ... with the 6 files that exist (the timer is gone)"
( set -Eeuo pipefail; _config_hashes > /dev/null ); eq "$?" 0 "6 ... and the list of hashes does not fail either"
# 6e. under set -e (config-baseline.sh runs like that) a file that is only in ONE of the two lists (removed, added) does not cut the list of changes short
config_baseline_write
echo 'caddy z' > "$VPS_DIR/Caddyfile"; rm -f "$VPS_DIR/docker-compose.yml"; echo '[Timer]' > "$VPS_DIR/systemd/predigol-q.timer"; echo 'Port 22222' > "$SSHD_DIR/sshd_config"
reset; ( set -Eeuo pipefail; check_config_drift )
for name in sshd_config Caddyfile docker-compose.yml predigol-q.timer; do
  case "$(cat "$CALLS")" in *"$name"*) ok "6 under set -e the change of $name is named (changed, removed and added files together)" ;; *) no "6 under set -e $name is missing: $(cat "$CALLS")" ;; esac
done
config_baseline_write; rm -f "$VPS_DIR/systemd/predigol-q.timer"; echo 'compose a' > "$VPS_DIR/docker-compose.yml"; config_baseline_write


# 7. picks of finished matches that are still not settled
reset
FAKE_PSQL="0 0 0 0 0" check_picks_unsettled; eq "$(calls)" 0 "7 nothing waiting: no alert"
FAKE_PSQL="12 3 0 0 7" check_picks_unsettled
eq "$(cat "$CALLS")" "picks.unsettled|SEV2|12 pick(s) de 3 partido(s) terminados hace más de 3 h siguen sin liquidar (el más antiguo espera 7 h)" "7 stuck picks are SEV2 with counts and age"
reset; FAKE_PSQL="0 0 4 2 0" check_picks_unsettled
eq "$(cat "$CALLS")" "picks.review|SEV3|4 pick(s) de 2 partido(s) terminados esperan revisión (el motivo está en picks.pick_results.review_reason)" "7 picks with a recorded reason are SEV3"
reset; FAKE_PSQL="5 1 2 1 4" check_picks_unsettled
eq "$(cut -d'|' -f1,2 "$CALLS" | tr '\n' ' ')" "picks.unsettled|SEV2 picks.review|SEV3 " "7 both at once: two alerts"
reset; FAKE_PSQL="not numbers" check_picks_unsettled; eq "$(calls)" 0 "7 an answer that is not five numbers opens nothing"
FAKE_PSQL="" check_picks_unsettled; eq "$(calls)" 0 "7 an empty answer opens nothing"
FAKE_PSQL_FAIL=1 check_picks_unsettled; eq "$?" 0 "7 a database that fails does not stop the run"; eq "$(calls)" 0 "7 and opens nothing (check_db_hold keeps what is open)"
unset FAKE_PSQL_FAIL
FAKE_PSQL="0 0 0 0 0" check_picks_unsettled; LAST_SQL=$(cat "$T/last_sql")
case "$LAST_SQL" in *"interval '7 days'"*"IN ('FT', 'AET', 'PEN')"*"interval '3 hours'"*) ok "7 the query reads 7 days of kick-offs, FT/AET/PEN, 3 hours" ;; *) no "7 query: $LAST_SQL" ;; esac
case "$LAST_SQL" in *"p.status <> 'settled'"*) ok "7 open means status <> 'settled', like the product's own query" ;; *) no "7 query status test" ;; esac
case "$LAST_SQL" in *"SET statement_timeout = '20s'"*) ok "7 the query has a time limit" ;; *) no "7 no time limit" ;; esac
if grep -qiE '\b(insert|update|delete|drop|alter|create|truncate|grant)\b' <<< "$LAST_SQL"; then no "7 the query writes"; else ok "7 the query only reads"; fi
if grep -qiE 'email|name|ip\b|user_agent|password' <<< "$LAST_SQL"; then no "7 the query selects personal columns"; else ok "7 the query selects counts only"; fi
UNSETTLED_AFTER_H=5 UNSETTLED_WINDOW_D=2 FAKE_PSQL="0 0 0 0 0" check_picks_unsettled; LAST_SQL=$(cat "$T/last_sql")
case "$LAST_SQL" in *"interval '2 days'"*"interval '5 hours'"*) ok "7 thresholds can be changed" ;; *) no "7 thresholds: $LAST_SQL" ;; esac
n=$(psql_calls); UNSETTLED_AFTER_H="3'; DROP TABLE x; --" check_picks_unsettled
eq "$(psql_calls)" "$n" "7 a threshold that is not a number never reaches the database"

# 8. a database that does not answer: what comes from it is held, not closed
reset; FAKE_PSQL="1" check_db_hold; eq "$(calls)" 0 "8 the database answers: nothing is held"
FAKE_PSQL_FAIL=1 check_db_hold
eq "$(cat "$CALLS")" "HOLD|ingest.live ingest.runs provider.quota db.connections pitr.wal picks.unsettled picks.review" "8 no answer: the database-fed alerts are held"
unset FAKE_PSQL_FAIL

# 9. the state of a container in words the owner reads (no stray spaces, no raw docker text for the usual cases)
eq "$(svc_state_es "missing")" "no existe o Docker no responde" "9 missing"
eq "$(svc_state_es " missing")" "no existe o Docker no responde" "9 missing with a leading space gives the same text"
eq "$(svc_state_es "")" "no existe o Docker no responde" "9 empty state"
eq "$(svc_state_es "running unhealthy")" "en marcha, pero su comprobación de salud falla" "9 running unhealthy"
eq "$(svc_state_es "exited ")" "parado" "9 exited (docker leaves a trailing space when there is no health check)"
eq "$(svc_state_es "restarting ")" "reiniciándose sin parar" "9 restarting"
eq "$(svc_state_es "created ")" "creado, pero sin arrancar" "9 created"
eq "$(svc_state_es "paused ")" "en pausa" "9 paused"
eq "$(svc_state_es $'\nweird  state\n')" "estado: weird state" "9 anything else is shown trimmed and on one line"

# 10. a deploy or a rollback ran a moment ago (state/deploys.log, the newest line, its first column)
dl="$STATE/deploys.log"; rm -f "$dl"
iso() { date -u -d "@$1" +%FT%TZ; }
after() { CHECKS_NOW=$t0 after_deploy "$@" && echo yes || echo no; }
eq "$(after)" no "10 no deploys.log: no deploy"
: > "$dl"; eq "$(after)" no "10 an empty deploys.log: no deploy"
printf '%s\tnew\tweb\told\tweb\n' "$(iso $((t0 - 100)))" > "$dl"; eq "$(after)" yes "10 a deploy 100 s ago"
printf '%s\tnew\tweb\told\tweb\n' "$(iso $((t0 - 359)))" > "$dl"; eq "$(after)" yes "10 a deploy 359 s ago is still inside the window (5 min of the count + 1)"
printf '%s\tnew\tweb\told\tweb\n' "$(iso $((t0 - 361)))" > "$dl"; eq "$(after)" no "10 a deploy 361 s ago is over"
printf '%s\tnew\tweb\told\tweb\n' "$(iso $((t0 - 100)))" > "$dl"; eq "$(after 60)" no "10 the window can be given: 100 s is over for 60"
printf '%s\told\tweb\t-\t-\trollback\n' "$(iso $((t0 - 100)))" > "$dl"; eq "$(after)" yes "10 a rollback line (6 columns) counts too"
{ printf '%s\tnew\tweb\told\tweb\n' "$(iso $((t0 - 5000)))"; printf '%s\tnewer\tweb\tnew\tweb\n' "$(iso $((t0 - 100)))"; } > "$dl"
eq "$(after)" yes "10 the LAST line decides (the file is only ever appended to): an old deploy and then a recent one"
{ printf '%s\tnew\tweb\told\tweb\n' "$(iso $((t0 - 100)))"; printf '%s\tnewer\tweb\tnew\tweb\n' "$(iso $((t0 - 5000)))"; } > "$dl"
eq "$(after)" no "10 ... and a recent line followed by an old one is read as the old one (the last), not as the best of the two"
printf '%s\tnew\tweb\told\tweb\n' "$(iso $((t0 + 600)))" > "$dl"; eq "$(after)" no "10 a line dated in the future is not a deploy (a wrong clock must not silence the alert for ever)"
printf 'not a date\tnew\tweb\told\tweb\n' > "$dl"; eq "$(after)" no "10 a date that is not a date: not a deploy"
printf '\tnew\tweb\told\tweb\n' > "$dl"; eq "$(after)" no "10 an empty date: not a deploy"
rm -f "$dl"

echo; echo "RESULT: $PASS ok, $FAIL failed"; exit $(( FAIL > 0 ))
