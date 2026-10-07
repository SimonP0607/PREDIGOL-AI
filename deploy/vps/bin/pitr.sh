#!/usr/bin/env bash
# Point-in-time recovery (PITR) with pgBackRest: WAL archived continuously, encrypted, to S3-compatible storage
# (Cloudflare R2), plus base backups - so the database can be put back as it was at any moment of the retention
# window, not only at the last nightly dump.
#
#   bin/pitr.sh init                 once, after PITR_* is set in the env file and the stack is up: stanza + check
#   bin/pitr.sh backup               (predigol-pitr.timer, daily) full on Sundays or when none exists, else diff
#   bin/pitr.sh verify               (weekly) every backup and WAL file in the repository re-read and checked
#   bin/pitr.sh test                 (monthly) a REAL restore to a restore point, in a throwaway container: the
#                                    revision and the key tables' rows must land where the database was
#   bin/pitr.sh status               what the repository holds (JSON)
#   bin/pitr.sh restore --time "2026-10-08 12:00:00+00" | --name NAME
#                                    restore into a NEW throwaway server (port 127.0.0.1:55432) to inspect or copy
#                                    data from; the live database is never touched (README: "Recuperación")
#
# Results go to $PREDIGOL_DATA/state/pitr-*.json; failures ping Healthchecks.io (HC_PING_PITR) and Telegram.
# Exit 0 good, 1 failed, 3 PITR not configured.
set -Eeuo pipefail
# shellcheck source=bin/lib.sh
. "$(dirname "$0")/lib.sh"

[[ -n "${PITR_S3_BUCKET:-}" ]] || { log "pitr: not configured (PITR_S3_BUCKET is empty)"; exit 3; }
PG=predigol-postgres
IMAGE="$(docker inspect -f '{{.Config.Image}}' "$PG")"
BOX=predigol-pitr-test
VOL=predigol-pitr-test-data
pgbr() { docker exec -u postgres "$PG" predigol-pitr "$@"; }
sql() { docker exec -u postgres "$PG" psql -d fbi -qAtX -v ON_ERROR_STOP=1 -c "$1"; }

KEY_TABLES=(core.fixtures core.fixture_results core.fixture_events market.odds_snapshots market.final_prematch_odds
  models.predictions picks.picks raw.ingestion_payloads auth.users)
counts() {
  local parts=() t
  for t in "${KEY_TABLES[@]}"; do parts+=("'$t', (SELECT count(*) FROM $t)"); done
  sql "SELECT json_build_object($(IFS=,; echo "${parts[*]}"))"
}

cmd_init() {
  if pgbr info --output=json | jq -e '.[0].status.code == 0' > /dev/null 2>&1; then
    log "pitr: stanza already exists"
  else
    pgbr stanza-create
  fi
  pgbr check
  log "pitr: WAL archiving works; first full backup next: bin/pitr.sh backup"
}

cmd_backup() {
  exclusive pitr
  local type=diff
  if [[ "$(date -u +%u)" == 7 ]] || ! pgbr info --output=json | jq -e '.[0].backup | map(select(.type == "full")) | length > 0' > /dev/null; then
    type=full
  fi
  trap 'log "pitr backup FAILED"; ping_hc "${HC_PING_PITR:-}" fail; notify "la copia PITR ($type) FALLÓ"' ERR
  ping_hc "${HC_PING_PITR:-}" start
  local started=$SECONDS
  log "pitr: $type backup"
  pgbr backup --type="$type"
  pgbr info --output=json > "$STATE/pitr-info.json"
  jq -n --arg at "$(date -u +%FT%TZ)" --arg type "$type" --argjson seconds $(( SECONDS - started )) \
    --slurpfile info "$STATE/pitr-info.json" \
    '{backed_up_at: $at, type: $type, seconds: $seconds,
      backups: ($info[0][0].backup | length),
      oldest_restore_point: ($info[0][0].backup[0].timestamp.start // null),
      archive_max: ($info[0][0].archive[0].max // null)}' > "$STATE/pitr-backup.json"
  trap - ERR
  log "pitr: $type backup done in $(( SECONDS - started ))s"
  ping_hc "${HC_PING_PITR:-}"
}

cmd_verify() {
  exclusive pitr
  local rc=0 started=$SECONDS
  pgbr verify > "$STATE/pitr-verify.log" 2>&1 || rc=$?
  jq -n --arg at "$(date -u +%FT%TZ)" --argjson ok "$([[ $rc == 0 ]] && echo true || echo false)" \
    --argjson seconds $(( SECONDS - started )) '{verified_at: $at, passed: $ok, seconds: $seconds}' > "$STATE/pitr-verify.json"
  if (( rc )); then
    log "pitr verify FAILED (see $STATE/pitr-verify.log)"
    notify "la verificación del repositorio PITR FALLÓ"
    return 1
  fi
  log "pitr verify passed"
}

wait_promoted() {
  local deadline=$(( SECONDS + ${1:-3600} ))
  while (( SECONDS < deadline )); do
    if [[ "$(docker exec -u postgres "$BOX" psql -qAtX -c 'SELECT pg_is_in_recovery()' 2> /dev/null)" == f ]]; then return 0; fi
    [[ "$(docker inspect -f '{{.State.Status}}' "$BOX" 2> /dev/null)" == running ]] || return 1
    sleep 5
  done
  return 1
}

throwaway() {  # throwaway <pgbackrest restore options...>: restore into a new volume and start a server on it
  docker rm -f "$BOX" > /dev/null 2>&1 || true
  docker volume rm -f "$VOL" > /dev/null 2>&1 || true
  local env=() v
  for v in $(compgen -v PITR_); do env+=(-e "$v"); done
  docker run -d --name "$BOX" --network "${PITR_TEST_NETWORK:-bridge}" "${env[@]}" -v "$VOL:/var/lib/postgresql/data" \
    ${PITR_TEST_PUBLISH:+-p "$PITR_TEST_PUBLISH"} \
    --entrypoint sh "$IMAGE" -c "
      set -e
      predigol-entrypoint true
      su-exec postgres pgbackrest --stanza=predigol restore --archive-mode=off --target-action=promote $*
      exec su-exec postgres postgres -c listen_addresses='*'
    " > /dev/null
}

cmd_test() {
  exclusive pitr
  local stamp name before after failures=() started=$SECONDS need free
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"; name="predigol-pitr-test-$stamp"
  # A restore needs the database's size again on this disk, plus room to breathe (PITR_TEST_MARGIN_GB, default 5).
  need=$(( $(sql "SELECT pg_database_size('fbi')") * 12 / 10 / 1024 + ${PITR_TEST_MARGIN_GB:-5} * 1024 * 1024 ))
  free=$(df -Pk "$PREDIGOL_DATA" | awk 'NR==2 {print $4}')
  if (( free < need )); then
    log "pitr test SKIPPED: $(( free / 1024 / 1024 )) GB free, $(( need / 1024 / 1024 )) GB needed"
    jq -n --arg at "$(date -u +%FT%TZ)" '{tested_at: $at, passed: null, skipped: "not enough disk"}' > "$STATE/pitr-test.json"
    notify "prueba PITR omitida: no hay espacio en disco para restaurar aquí"
    return 0
  fi
  trap 'docker rm -f "$BOX" > /dev/null 2>&1 || true; docker volume rm -f "$VOL" > /dev/null 2>&1 || true' RETURN
  ping_hc "${HC_PING_PITR_TEST:-}" start
  log "pitr test: restore point $name"
  before="$(counts)"
  docker exec -u postgres "$PG" psql -d fbi -qAtX -c "SELECT pg_create_restore_point('$name')" > /dev/null
  after="$(counts)"
  docker exec -u postgres "$PG" psql -d fbi -qAtX -c "SELECT pg_switch_wal()" > /dev/null
  pgbr check > /dev/null   # waits until the WAL holding the restore point is in the repository
  log "pitr test: restoring into a throwaway server"
  throwaway --type=name "--target=$name"
  if wait_promoted "${PITR_TEST_TIMEOUT:-5400}"; then
    log "  recovered to $name and promoted"
  else
    failures+=("the throwaway server did not recover (docker logs $BOX)")
    docker logs --tail 40 "$BOX" > "$STATE/pitr-test.log" 2>&1 || true
  fi
  if (( ${#failures[@]} == 0 )); then
    local want got t lo hi n
    want="$(sql "SELECT version_num FROM public.alembic_version")"
    got="$(docker exec -u postgres "$BOX" psql -d fbi -qAtX -c "SELECT version_num FROM public.alembic_version")"
    [[ "$want" == "$got" ]] || failures+=("revision $got, expected $want")
    for t in "${KEY_TABLES[@]}"; do
      lo="$(jq -r --arg t "$t" '.[$t]' <<< "$before")"; hi="$(jq -r --arg t "$t" '.[$t]' <<< "$after")"
      n="$(docker exec -u postgres "$BOX" psql -d fbi -qAtX -c "SELECT count(*) FROM $t")"
      if (( n < lo || n > hi )); then failures+=("$t: $n rows, expected $lo..$hi"); else log "  $t: $n rows"; fi
    done
  fi
  local passed; passed=$([[ ${#failures[@]} -eq 0 ]] && echo true || echo false)
  jq -n --arg at "$(date -u +%FT%TZ)" --arg target "$name" --argjson passed "$passed" \
    --argjson seconds $(( SECONDS - started )) --args \
    '{tested_at: $at, target: $target, passed: $passed, seconds: $seconds, failures: $ARGS.positional}' \
    "${failures[@]}" > "$STATE/pitr-test.json"
  if [[ "$passed" == true ]]; then
    log "pitr test PASSED in $(( SECONDS - started ))s"
    ping_hc "${HC_PING_PITR_TEST:-}"
  else
    log "pitr test FAILED: ${failures[*]}"
    ping_hc "${HC_PING_PITR_TEST:-}" fail
    notify "la prueba de recuperación PITR FALLÓ: ${failures[*]}"
    return 1
  fi
}

cmd_restore() {
  local target=()
  case "${1:-}" in
    --time) target=(--type=time "--target=${2:?time}") ;;
    --name) target=(--type=name "--target=${2:?name}") ;;
    *) echo "usage: pitr.sh restore --time 'YYYY-MM-DD HH:MM:SS+00' | --name NAME" >&2; exit 2 ;;
  esac
  BOX=predigol-pitr-restore VOL=predigol-pitr-restore-data PITR_TEST_PUBLISH="127.0.0.1:55432:5432" throwaway "${target[@]}"
  if wait_promoted 7200; then
    log "restored and promoted: docker exec -it -u postgres $BOX psql -d fbi   (or 127.0.0.1:55432)"
    log "when done: docker rm -f $BOX && docker volume rm $VOL"
  else
    log "restore did not finish: docker logs $BOX"; exit 1
  fi
}

case "${1:-}" in
  init) cmd_init ;;
  backup) cmd_backup ;;
  verify) cmd_verify ;;
  test) cmd_test ;;
  status) pgbr info --output=json | jq . ;;
  restore) shift; cmd_restore "$@" ;;
  *) sed -n '2,20p' "$0"; exit 2 ;;
esac
