#!/usr/bin/env bash
# Weekly proof that the newest dump restores: into a THROWAWAY PostgreSQL container with no network, never the
# live server (a restore test on the live server once held it for five hours and stopped the capture).
#
#   bin/restore-test.sh [DUMP_NAME]          (default: the newest predigol-*.dump)
#
# Checks: the file's sha256 is the one recorded at backup time; pg_restore succeeds; the schema revision comes
# back; every key table holds between the smaller and the larger of what it held when the dump started and when it
# ended (OPS-011); every schema and every append-only trigger the backup named came back (AD-A07). The result goes to $PREDIGOL_DATA/state/restore-test.json. Exit 0 passed, 1 failed.
set -Eeuo pipefail
# shellcheck source=bin/lib.sh
. "$(dirname "$0")/lib.sh"
exclusive restore-test

NAME="${1:-$(find "$DB_BACKUPS" -maxdepth 1 -name 'predigol-*.dump' -printf '%f\n' | sort -r | head -n 1)}"
NAME="${NAME%.dump}"
DUMP="$DB_BACKUPS/$NAME.dump"
MANIFEST="$DB_BACKUPS/$NAME.json"
[[ -f "$DUMP" && -f "$MANIFEST" ]] || { log "restore-test: no dump with its manifest ($NAME)"; exit 1; }
BOX="predigol-restore-test"
RESULT="$STATE/restore-test.json"
failures=()
fail() { failures+=("$1"); log "  FAIL $1"; }
# -v: the postgres image declares its data folder a VOLUME, so `docker rm -f` alone left every restored copy behind as
# an anonymous volume - seven of them, 78 GB, 40 % of the server's disk between 9 and 13 Oct 2026.
cleanup() { docker rm -f -v "$BOX" > /dev/null 2>&1 || true; }
trap cleanup EXIT

ping_hc "${HC_PING_RESTORE_TEST:-}" start
started=$(date +%s)
log "restore-test $NAME"
want_sha="$(jq -r .sha256 "$MANIFEST")"
got_sha="$(sha256sum "$DUMP" | cut -d' ' -f1)"
[[ "$want_sha" == "$got_sha" ]] || fail "sha256 differs from the backup's record"

# The restored copy needs about the live database's size on this disk: skip (and say so) rather than fill it.
need_kb=$(( $(psql_q "SELECT pg_database_size('fbi')") * 11 / 10 / 1024 + 5 * 1024 * 1024 ))
free_kb="$(df -Pk /var/lib/docker | awk 'NR==2 {print $4}')"
if (( free_kb < need_kb )); then
  log "restore-test SKIPPED: $(( free_kb / 1048576 )) GB free, $(( need_kb / 1048576 )) GB needed"
  jq -n --arg dump "$NAME" --arg at "$(date -u +%FT%TZ)" '{dump: $dump, tested_at: $at, passed: null, skipped: "not enough disk"}' > "$RESULT"
  notify "prueba de restauración omitida: falta espacio en disco"
  exit 0
fi

cleanup
pw="$(openssl rand -hex 16)"
docker run -d --name "$BOX" --network none --shm-size 256m -e POSTGRES_PASSWORD="$pw" -e POSTGRES_DB=restore \
  -v "$DB_BACKUPS:/backups:ro" postgres:16-alpine > /dev/null
ready=0
for _ in $(seq 1 90); do
  # The image starts a temporary server to initialise, then the real one: wait for the real one.
  if docker exec "$BOX" pg_isready -U postgres -d restore -q 2> /dev/null &&
     docker logs "$BOX" 2>&1 | grep -q "PostgreSQL init process complete"; then ready=1; break; fi
  sleep 2
done
(( ready )) || fail "the throwaway server did not start"
q() { docker exec "$BOX" psql -U postgres -d restore -qAtX -v ON_ERROR_STOP=1 -c "$1"; }

if [[ ${#failures[@]} -eq 0 ]]; then
  if docker exec "$BOX" pg_restore -U postgres -d restore --no-owner --no-privileges --jobs=2 \
       "/backups/$NAME.dump" > "$STATE/restore-test.log" 2>&1; then
    log "  pg_restore ok"
  else
    fail "pg_restore failed (see $STATE/restore-test.log)"
  fi
fi
if [[ ${#failures[@]} -eq 0 ]]; then
  want_rev="$(jq -r .alembic_revision "$MANIFEST")"
  got_rev="$(q "SELECT version_num FROM public.alembic_version")"
  if [[ "$want_rev" == "$got_rev" ]]; then log "  revision $got_rev"; else fail "revision $got_rev, expected $want_rev"; fi
  while IFS=$'\t' read -r table lo hi; do
    # OPS-011: the bounds are the smaller and the larger of the two counts. A table can LOSE rows while the dump runs (a purge, a
    # prune: core.fixture_events went 3279639 -> 3279638 on 19 Nov 2026) and "between 3279639 and 3279638" failed a good restore.
    if [[ "$lo" =~ ^[0-9]+$ && "$hi" =~ ^[0-9]+$ ]] && (( hi < lo )); then swap=$lo; lo=$hi; hi=$swap; fi
    n="$(q "SELECT count(*) FROM $table")"
    if (( n < lo || n > hi )); then fail "$table: $n rows, expected between $lo and $hi"; else log "  $table: $n rows"; fi
  done < <(jq -r '.counts_before | to_entries[] | [.key, .value] | @tsv' "$MANIFEST" |
           while IFS=$'\t' read -r t lo; do printf '%s\t%s\t%s\n' "$t" "$lo" "$(jq -r --arg t "$t" '.counts_after[$t]' "$MANIFEST")"; done)
  # AD-A07: every schema and every append-only trigger the backup named came back. A manifest written before this check existed has
  # no "catalog": nothing more is checked for it.
  if jq -e '.catalog | type == "object"' "$MANIFEST" > /dev/null 2>&1; then
    got_schemas="$(q "SELECT nspname FROM pg_namespace ORDER BY 1")"
    got_triggers="$(q "SELECT n.nspname || '.' || c.relname || ':' || t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
                       JOIN pg_namespace n ON n.oid = c.relnamespace WHERE NOT t.tgisinternal AND t.tgname LIKE '%append_only%' ORDER BY 1")"
    lost_schemas="$(comm -23 <(jq -r '.catalog.schemas[]' "$MANIFEST" | sort -u) <(printf '%s\n' "$got_schemas" | sort -u) | paste -sd, -)"
    lost_triggers="$(comm -23 <(jq -r '.catalog.append_only[]' "$MANIFEST" | sort -u) <(printf '%s\n' "$got_triggers" | sort -u) | paste -sd, -)"
    if [[ -n "$lost_schemas" ]]; then fail "schemas missing after the restore: $lost_schemas"
    else log "  schemas: $(jq -r '.catalog.schemas | length' "$MANIFEST") back"; fi
    if [[ -n "$lost_triggers" ]]; then fail "append-only triggers missing after the restore: ${lost_triggers:0:300}"
    else log "  append-only triggers: $(jq -r '.catalog.append_only | length' "$MANIFEST") back"; fi
  else
    log "  (the manifest names no schemas: a backup from before AD-A07)"
  fi
fi
seconds=$(( $(date +%s) - started ))
passed=$([[ ${#failures[@]} -eq 0 ]] && echo true || echo false)
jq -n --arg dump "$NAME" --arg at "$(date -u +%FT%TZ)" --argjson seconds "$seconds" --argjson passed "$passed" \
  --args '{dump: $dump, tested_at: $at, seconds: $seconds, passed: $passed, failures: $ARGS.positional}' \
  "${failures[@]}" > "$RESULT"
if [[ "$passed" == true ]]; then
  log "restore-test PASSED in ${seconds}s"
  ping_hc "${HC_PING_RESTORE_TEST:-}"
else
  log "restore-test FAILED: ${failures[*]}"
  ping_hc "${HC_PING_RESTORE_TEST:-}" fail
  notify "la prueba de restauración FALLÓ ($NAME): ${failures[*]}"
  exit 1
fi
