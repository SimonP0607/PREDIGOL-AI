#!/usr/bin/env bash
# Release __REL__, once the package is on the server and BEFORE anything moves: what the server has. READ-ONLY - it writes nothing in the
# database, restarts nothing, deletes nothing, builds nothing. The lines that start with OK / NOT OK are checked by the script itself, and the last
# line says how many were NOT OK (exit 0 when none). Adapted from the F14 and UX A1 prechecks (claude/PLANTILLAS_DESPLIEGUE_GUARDADO.md); the
# sections that were about A1 (sessions, audit events, Sentry) are replaced by the ones of the IA release: the tables the migrations touch, the
# roles, the AI settings (names only) and the locks the plans share. What is particular to one release - the objects and columns its migrations
# create (they must not exist yet) and the tables they lock - is read from RELEASE.json (.precheck.objects_absent, .columns_absent,
# .tables_measured), so this script is the same for every release of the plan.
set -uo pipefail
D=/root/releases/__STAMP__
BE_DIR=/opt/predigol/backend
WEB_DIR=/opt/predigol/web
ENV_FILE=/etc/predigol/app.env
PARTS="__PARTS__"
MIN_FREE_GB=10
BAD=0
section() { echo; echo "== $*"; }
good() { echo "OK: $*"; }
bad() { BAD=$((BAD + 1)); echo "NOT OK: $*"; }
verdict() { if [ "$1" = "$2" ]; then good "$3 = $1"; else bad "$3 = $1, expected $2"; fi; }
releases() { case " $PARTS " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }
# a read-only session of the owner role (a time limit of 20 s); stdin is never read
ro() { docker exec -e PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=20000' predigol-postgres psql -U fbi -d fbi -At -F ' ' -v ON_ERROR_STOP=1 "$@" < /dev/null; }
cd "$D" || { echo "NOT OK: $D does not exist"; exit 1; }

section "now"; date -u +%FT%TZ; uptime
section "the tools the scripts use"
for tool in python3 jq git docker curl sha256sum flock awk; do
  if command -v "$tool" > /dev/null 2>&1; then good "$tool - $("$tool" --version 2>&1 | head -n 1)"; else bad "$tool is not installed"; fi
done
section "the package on the server (expect both lists to check)"
if sha256sum -c --quiet SHA256SUMS; then good "SHA256SUMS (the bundles, RELEASE.json and the guard)"; else bad "SHA256SUMS"; fi
if sha256sum -c --quiet SCRIPTS.sha256; then good "SCRIPTS.sha256 (the scripts and the guard)"; else bad "SCRIPTS.sha256"; fi
echo "release: $(jq -r '.release + " built " + .created_at + " from " + .source.commit[0:12] + " (parts: " + (.parts | join(", ")) + ")"' RELEASE.json)"
section "the checkouts (expect the releases production runs now, and nothing changed in them)"
verdict "$(git -C "$BE_DIR" rev-parse --short=12 HEAD)" "__BE_FROM__" "backend checkout"
verdict "$(git -C "$WEB_DIR" rev-parse --short=12 HEAD)" "__WEB_FROM__" "web checkout"
verdict "$(git -C "$BE_DIR" status --porcelain --untracked-files=no | grep -c .)" "0" "tracked files changed in the backend checkout"
verdict "$(git -C "$WEB_DIR" status --porcelain --untracked-files=no | grep -c .)" "0" "tracked files changed in the web checkout"
section "the bundles fit the checkouts (git bundle verify reads and writes nothing)"
for part in backend web; do
  releases "$part" || { echo "($part is not released: production keeps its commit)"; continue; }
  dir=$BE_DIR; [ "$part" = web ] && dir=$WEB_DIR
  if git -C "$dir" bundle verify "$D/${part}___REL__.bundle" > /dev/null 2>&1; then good "$part bundle"; else bad "$part bundle"; fi
done
section "the model code (the guard reads the checkout itself; expect the name RELEASE.json says production runs)"
CODE_NOW=$(python3 "$D/model_code_guard.py" fingerprint dir="$BE_DIR" 2>&1)
verdict "$CODE_NOW" "$(jq -r .model_code.before RELEASE.json)" "model code of the backend checkout"
echo "the guard when the package was built (mode $(jq -r .model_code.mode RELEASE.json)): $(jq -r .model_code.status RELEASE.json)"
section "the disk"
FREE=$(df -BG --output=avail / | tail -n 1 | tr -dc '0-9')
if [ "${FREE:-0}" -ge "$MIN_FREE_GB" ]; then good "${FREE} GB free, at least $MIN_FREE_GB"; else bad "${FREE:-?} GB free, at least $MIN_FREE_GB wanted"; fi
df -h / | tail -n 1
section "the services"; predigolctl status 2>&1 | tail -n 9
section "docker compose: step_keys.sh relies on 'config --hash' to know which services a change of app.env would recreate (names and hashes, no value)"
CV=$(docker compose version --short 2> /dev/null < /dev/null | head -n 1)
if [ -n "$CV" ]; then good "docker compose $CV"; else bad "docker compose version could not be read"; fi
FP=$(env -i HOME=/root PATH="$PATH" bash -c ". '$BE_DIR/deploy/vps/bin/lib.sh'; compose config --hash '*'" 2> /dev/null < /dev/null | sort)
HASHED=0
for s in api worker postgres web caddy; do if grep -qE "^$s [0-9a-f]{64}\$" <<< "$FP"; then HASHED=$((HASHED + 1)); fi; done
verdict "$HASHED" "5" "services of the stack for which 'docker compose config --hash' gives a hash (api, worker, postgres, web, caddy)"
for s in api worker postgres web caddy; do
  have=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.config-hash"}}' "predigol-$s" 2> /dev/null < /dev/null || true)
  want=$(awk -v s="$s" '$1 == s { print $2 }' <<< "$FP")
  if [ -n "$have" ] && [ "$have" = "$want" ]; then echo "info: $s runs with the configuration Compose computes now"
  else
    echo "info: $s: the container carries ${have:0:12}, Compose computes ${want:0:12} now (a difference means the next 'up' would recreate it)"
    # api, worker and web are recreated on purpose (their images change with this release); the database and the proxy must not move
    case "$s" in
      postgres | caddy) bad "$s would be recreated by the deploy (its configuration hash differs from the container's) and this release does not touch it: find out why before anything moves" ;;
    esac
  fi
done
section "the timers of the server that could fire while the sequence runs (read only, for information: what the deploy waits for is decided below by heavy_check, from the locks, the services and these same times; no hour of the day decides anything)"
LOOKAHEAD_MIN=${TIMER_LOOKAHEAD_MIN:-120}
LIMIT=$(( $(date +%s) + LOOKAHEAD_MIN * 60 ))
TIMERS=$(systemctl list-unit-files --no-legend --plain 'predigol-*.timer' 2> /dev/null | awk '{ print $1 }')
if [ -z "$TIMERS" ]; then echo "(no predigol-*.timer found)"; fi
for t in $TIMERS; do
  nxt=$(TZ=UTC LC_ALL=C systemctl show -p NextElapseUSecRealtime --value "$t" 2> /dev/null || true)
  if [ -z "$nxt" ] || [ "$nxt" = "n/a" ]; then echo "$t: no next run"; continue; fi
  ep=$(date -u -d "$nxt" +%s 2> /dev/null) || { echo "$t: next run '$nxt' (not read as a date)"; continue; }
  case "$t" in
    predigol-health.timer | predigol-raw-sync.timer) echo "$t: next run $nxt (light)" ;;
    *) if [ "$ep" -le "$LIMIT" ]; then echo "WARNING: $t runs at $nxt, within the next $LOOKAHEAD_MIN minutes"; else echo "$t: next run $nxt"; fi ;;
  esac
done
section "the locks the plans share, and the work of the others (a held lock means somebody is working: wait)"
for lk in deploy restore-test backup pitr maint; do
  f=/srv/predigol/state/$lk.lock
  if [ -e "$f" ]; then
    if flock -n "$f" true 2> /dev/null; then good "lock $lk is free"; else bad "lock $lk is HELD"; fi
  else good "lock $lk: no file (free)"; fi
done
RUNNING_PROCS=$(pgrep -fa 'predigolctl (deploy|backup|restore-test|pitr|maint)|restore-test.sh|backup.sh|pitr.sh|maint.sh' | grep -vc pgrep || true)
verdict "$RUNNING_PROCS" "0" "processes of a deploy, a backup, a restore test, a PITR run or the maintenance"
# IGNORE_UNITS: the units of this release's own sequence (chain.sh runs this script from inside one of them).
# The read-only observers of an EARLIER release of this plan (its follow-ups at 10, 30 and 60 minutes and its lock watcher: they read, write nothing
# and restart nothing) are not "somebody else working": waiting for them would hold the next release for an hour for nothing (owner's order,
# 27-oct-2026: every finished piece is deployed as soon as it is finished). The same goes for the lock watcher of ANY plan (<release>-lockwatch.service): it is
# the F14 template's lockwatch.sh, a read-only session that samples the locks every 3 seconds and writes its own log (the security plan's sec-s3 runs one for
# 50 minutes after its deploy). Everything else named ia-*, and every other unit of the other plans (their chains, their steps), still counts.
RUNNING_UNITS=$(systemctl list-units --no-legend --plain --state=running 's0-*' 'sec-*' 'ux*' 'ia-*' 'f11-*' 2> /dev/null |
  awk -v ignore=" ${IGNORE_UNITS:-} " 'NF > 0 && index(ignore, " " $1 " ") == 0 && $1 !~ /^ia-p[0-9]+-(followups|lockwatch)\.service$/ && $1 !~ /^[a-z0-9]+(-[a-z0-9]+)*-lockwatch\.service$/ { n++ } END { print n + 0 }')
verdict "$RUNNING_UNITS" "0" "detached units of the plans (s0-, sec-, ux, ia-, f11-) running"
section "is the server quiet (the checks step_deploy.sh makes and refuses on; no hour of the day is among them: the owner dropped the deployment window on 26-oct-2026)"
if [ -f "$D/quiet.sh" ]; then
  # shellcheck source=/dev/null
  . "$D/quiet.sh"
  QRC=0
  quiet_check || QRC=$?
  case "$QRC" in
    0) good "the server is quiet" ;;
    2) bad "the server is not quiet (the lines above say who: step_deploy.sh would refuse with status 2)" ;;
    *) bad "the quiet check could not look (status $QRC): step_deploy.sh would refuse with status 2" ;;
  esac
  HRC=0
  heavy_check || HRC=$?
  case "$HRC" in
    0) good "no heavy job of the server runs, and none starts within ${HEAVY_LOOKAHEAD_MIN} minutes" ;;
    2) bad "the server is not quiet: a heavy job (backup, PITR, maintenance, restore test) runs or starts within ${HEAVY_LOOKAHEAD_MIN} minutes (the lines above say which; step_deploy.sh would refuse with status 2 until it has ended)" ;;
    *) bad "the quiet check could not look at the heavy jobs (status $HRC): step_deploy.sh would refuse with status 2" ;;
  esac
else
  bad "quiet.sh is not in the package"
fi
section "the revision the database is at (expect the latest migration of the package; when the release brings migrations, the one before them)"
REV=$(ro -c "select version_num from alembic_version")
echo "$REV"
if [ "$(jq -r '.migrations_new | length' RELEASE.json)" = "0" ]; then
  verdict "${REV:0:4}" "$(jq -r .latest_migration RELEASE.json | cut -c1-4)" "revision of the database"
else
  echo "the release brings: $(jq -r '.migrations_new | join(", ")' RELEASE.json)"
  verdict "${REV:0:4}" "$(jq -r .revision_before RELEASE.json | cut -c1-4)" "revision of the database before the release"
  if [ "${REV:0:4}" = "$(jq -r .revision_before RELEASE.json | cut -c1-4)" ]; then
    section "none of the objects and columns the migrations create exists yet (a count of what exists now; expect 0; the lists are the release's own: RELEASE.json .precheck)"
    OBJS=$(jq -r '(.precheck.objects_absent // []) | map(@sh) | join(",")' RELEASE.json)
    COLS=$(jq -r '(.precheck.columns_absent // []) | map(@sh) | join(",")' RELEASE.json)
    if [ -n "$OBJS" ]; then
      verdict "$(ro -c "select count(*) from unnest(array[$OBJS]) n where to_regclass(n) is not null")" "0" "objects the migrations create that already exist"
    else echo "(the release declares no new table or view)"; fi
    if [ -n "$COLS" ]; then
      verdict "$(ro -c "select count(*) from information_schema.columns where table_schema || '.' || table_name || '.' || column_name in ($COLS)")" "0" "columns the migrations add that already exist"
    else echo "(the release declares no new column)"; fi
  fi
fi
section "the tables the migrations lock or alter (read only: rows and size; each lock is asked for at most 10 s by the migration, and quiet.sh watches these same tables)"
for t in $(jq -r '(.precheck.tables_measured // ["ai.usage", "ai.match_briefs", "ai.cycles", "ai.budget_alerts", "intel.promotions"]) | .[]' RELEASE.json); do
  ro -c "SELECT '$t:', count(*), 'rows,', pg_size_pretty(pg_total_relation_size('$t')), 'with its indexes' FROM $t" || bad "$t could not be measured"
done
verdict "$(ro -c "select pg_get_userbyid(relowner) from pg_class where oid = 'intel.promotions'::regclass")" "fbi" "owner of intel.promotions (the owner is not subject to its row policy)"
section "the roles (read only): the operator's way in as the superuser inside the database container, and the roles db/roles.sql and grants.sql work with"
SU=$(docker exec -e PGOPTIONS='-c default_transaction_read_only=on' predigol-postgres psql -U postgres -d fbi -At -F '|' -c "select current_user, (select rolsuper from pg_roles where rolname = current_user)" < /dev/null 2>&1)
verdict "$SU" "postgres|t" "the superuser path inside the database container (db/roles.sql runs through it)"
ro -c "select rolname, 'super=' || rolsuper, 'login=' || rolcanlogin, 'bypassrls=' || rolbypassrls from pg_roles where rolname in ('fbi','predigol_worker','predigol_api','predigol_rollback','predigol_learning') order by 1"
verdict "$(ro -c "select count(*) from pg_roles where rolname in ('predigol_worker','predigol_api')")" "2" "roles predigol_worker and predigol_api"
echo "predigol_rollback exists now: $(ro -c "select count(*) from pg_roles where rolname = 'predigol_rollback'") (0 before step_roles.sh, 1 after)"
section "the AI settings of the application: NAMES, and a value only where it is not secret (the file is the owner's; this reads it, prints no key)"
if [ -r "$ENV_FILE" ]; then
  awk '
    function safe(n) { return n ~ /^FBI_AI_(MODE|MODEL_[A-Z]+|MONTHLY_BUDGET_USD|LAB_MONTHLY_BUDGET_USD|EXA_MONTHLY_BUDGET_USD|JOINT_CEILING_USD|RESERVE_USD|DAILY_TARGET_USD|DAILY_BUDGET_USD|DAILY_MAX_FACTOR|MAX_[A-Z_]+|HORIZON_HOURS|SEARCH|CACHE|BATCH|NATIVE_SCHEMA|BRIEF_MATERIAL|BUDGET_V3|PACKAGE|PACKAGE_MINUTES|MULTIMODAL|WORKSPACE|WORKSPACE_LAB|KEY_LABEL|KEY_LABEL_LAB|LEGACY_POSTMORTEMS|BATCH_MIN_LEAD_MINUTES|ENGINES|SHADOW_SAMPLE|AGENTS|ORCHESTRATE_MINUTES|PM_REVIEWER|LEARNING_ANALYST)$/ }
    /^(FBI_AI_|FBI_ANALYST_|EXA_API_KEY)/ {
      i = index($0, "="); if (i == 0) next
      n = substr($0, 1, i - 1); v = substr($0, i + 1); gsub(/["\047 \t\r]/, "", v)
      if ((n !~ /KEY_LABEL/ && n ~ /(KEY|TOKEN|SECRET|PASSWORD)/) || !safe(n)) printf "%s: %s\n", n, (length(v) > 0 ? "set" : "empty")
      else printf "%s=%s\n", n, v
    }' "$ENV_FILE" | sort
  MODE_NOW=$(awk -F= '$1 == "FBI_AI_MODE" { v = $2; gsub(/["\047 \t\r]/, "", v); print v }' "$ENV_FILE" | tail -n 1)
  # shadow (empty means shadow) or enforce, the owner's word (8-nov-2026, CI-012): with enforce the AI's decisions reach users only while the
  # latest shadow report of ``combined`` says pass (fbi.ai.gating); until then it behaves as shadow. Any other word is refused.
  case "${MODE_NOW:-shadow}" in
    shadow) good "FBI_AI_MODE (the layer stays in shadow; empty means shadow) = shadow" ;;
    enforce) good "FBI_AI_MODE = enforce (the owner's word: applied to users only while the shadow gate of combined passes, fbi.ai.gating)" ;;
    *) bad "FBI_AI_MODE = $MODE_NOW, expected shadow or enforce" ;;
  esac
  echo "the variables the running worker has (names only):"
  docker exec predigol-worker sh -c "env | cut -d= -f1 | grep -E '^(FBI_AI_|FBI_ANALYST_|EXA_API_KEY)' | sort" < /dev/null || bad "the worker's variable names could not be read"
else
  bad "$ENV_FILE cannot be read"
fi
section "what the AI has spent this month in the ledger (read only; UTC month)"
ro -c "select 'ai.usage this month:', coalesce(provider, 'all providers'), count(*), coalesce(round(sum(cost_usd), 4)::text, '0') from ai.usage where at >= date_trunc('month', now() at time zone 'UTC') at time zone 'UTC' group by rollup (provider) order by provider nulls last" || bad "the month's spend could not be read"
section "the day's picks and decisions now (read only; the deploy compares the same cutoff after)"
"$D/day_digest.sh" "$(date -u +%FT%TZ)" || bad "the day digest could not be read"
echo
if [ "$BAD" -eq 0 ]; then echo "PRECHECK: every line OK"; else echo "PRECHECK: $BAD line(s) NOT OK"; fi
[ "$BAD" -eq 0 ]
