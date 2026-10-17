#!/usr/bin/env bash
# Daily backup of the database: one consistent pg_dump, verified, described, rotated, and - when configured -
# encrypted and copied off the server. The RAW store is not in it: it is append-only evidence, copied off the
# server as it is by bin/raw-sync.sh.
#
#   bin/backup.sh [--label NAME]
#
# The dump is written by pg_dump INSIDE the postgres container straight to the backups folder (bind-mounted at
# /backups): nothing streams through docker. Then:
#   - pg_restore --list reads the whole table of contents back;
#   - sha256 and size go into <name>.json, with the schema revision and the row counts of the key tables
#     taken just before and just after the dump (a restore must land between the two: bin/restore-test.sh);
#   - only then is the file renamed from .partial to .dump.
# Exit 0 good, 1 failed (the partial file is removed, the previous dumps are untouched).
set -Eeuo pipefail
# shellcheck source=bin/lib.sh
. "$(dirname "$0")/lib.sh"
exclusive backup

LABEL=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --label) LABEL="-${2//[^A-Za-z0-9_-]/}"; shift 2 ;;
    *) echo "usage: $0 [--label NAME]" >&2; exit 2 ;;
  esac
done

KEY_TABLES=(core.fixtures core.fixture_results core.fixture_events core.fixture_live_states
  market.odds_snapshots market.final_prematch_odds market.historical_odds market.market_consensus
  raw.ingestion_payloads picks.picks picks.pick_results auth.users)

counts() {
  local parts=() t
  for t in "${KEY_TABLES[@]}"; do parts+=("'$t', (SELECT count(*) FROM $t)"); done
  psql_q "SELECT json_build_object($(IFS=,; echo "${parts[*]}"))"
}

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
NAME="predigol-${STAMP}${LABEL}"
PARTIAL="$DB_BACKUPS/$NAME.dump.partial"
trap 'rm -f "$PARTIAL"; log "backup FAILED"; ping_hc "${HC_PING_BACKUP:-}" fail; notify "la copia diaria de la base FALLÓ ($NAME)"' ERR

ping_hc "${HC_PING_BACKUP:-}" start
log "backup $NAME: counting, dumping"
revision="$(psql_q "SELECT version_num FROM public.alembic_version")"
before="$(counts)"
started=$(date +%s)
compose exec -T postgres pg_dump -U fbi -d fbi --format=custom --compress=6 --file="/backups/$NAME.dump.partial"
seconds=$(( $(date +%s) - started ))
after="$(counts)"
compose exec -T postgres pg_restore --list "/backups/$NAME.dump.partial" > /dev/null
sha="$(sha256sum "$PARTIAL" | cut -d' ' -f1)"
bytes="$(stat -c %s "$PARTIAL")"
version="$(compose exec -T postgres pg_dump --version | tr -d '\r')"
mv "$PARTIAL" "$DB_BACKUPS/$NAME.dump"
cat > "$DB_BACKUPS/$NAME.json" <<JSON
{"name": "$NAME", "file": "$NAME.dump", "created_at": "$(date -u +%FT%TZ)", "seconds": $seconds,
 "bytes": $bytes, "sha256": "$sha", "alembic_revision": "$revision", "pg_dump": "$version",
 "counts_before": $before, "counts_after": $after}
JSON
log "backup $NAME: $bytes bytes in ${seconds}s, sha256 ${sha:0:16}, revision $revision"

# Off the server, encrypted with the owner's age public key (the private key never touches this machine), then
# CHECKED there (the object exists with the size just written) before anything local may be rotated out.
offsite=0
if [[ -n "${BACKUP_RCLONE_REMOTE:-}" && -n "${BACKUP_AGE_RECIPIENT:-}" ]]; then
  offsite=1
  age -r "$BACKUP_AGE_RECIPIENT" -o "$DB_BACKUPS/$NAME.dump.age" "$DB_BACKUPS/$NAME.dump"
  age_bytes="$(stat -c %s "$DB_BACKUPS/$NAME.dump.age")"
  rclone copy --immutable "$DB_BACKUPS/$NAME.dump.age" "$BACKUP_RCLONE_REMOTE/db/"
  rclone copy --immutable "$DB_BACKUPS/$NAME.json" "$BACKUP_RCLONE_REMOTE/db/"
  remote_bytes="$(rclone lsjson "$BACKUP_RCLONE_REMOTE/db/$NAME.dump.age" | jq -r '.[0].Size // -1')"
  rm -f "$DB_BACKUPS/$NAME.dump.age"
  if [[ "$remote_bytes" != "$age_bytes" ]]; then
    log "off-server copy NOT verified ($remote_bytes bytes there, $age_bytes here)"; false
  fi
  jq --arg remote "$BACKUP_RCLONE_REMOTE/db/$NAME.dump.age" --argjson bytes "$age_bytes" --arg at "$(date -u +%FT%TZ)" \
    '. + {offsite: {remote: $remote, bytes: $bytes, verified_at: $at}}' "$DB_BACKUPS/$NAME.json" > "$DB_BACKUPS/$NAME.json.new"
  mv "$DB_BACKUPS/$NAME.json.new" "$DB_BACKUPS/$NAME.json"
  log "copied off the server to $BACKUP_RCLONE_REMOTE/db/ (age-encrypted, $age_bytes bytes, checked)"
else
  log "NOTE: no off-server copy configured (BACKUP_RCLONE_REMOTE + BACKUP_AGE_RECIPIENT): this dump exists only here"
fi

# Rotation on this server (bin/rotate-dumps.sh): the newest BACKUP_KEEP_DAILY dumps, the newest of each of the last
# BACKUP_KEEP_DAILY days and of each of the last BACKUP_KEEP_WEEKLY ISO weeks. With an off-server copy configured, a
# dump whose copy was never checked is KEPT.
rotated="$("$KIT/bin/rotate-dumps.sh" "$DB_BACKUPS" "${BACKUP_KEEP_DAILY:-3}" "${BACKUP_KEEP_WEEKLY:-2}" "$offsite")"
while IFS= read -r line; do [[ -n "$line" ]] && log "$line"; done <<< "$rotated"

# Retention off the server: daily copies for BACKUP_REMOTE_DAYS days, the Sunday ones for BACKUP_REMOTE_WEEKS
# weeks, the first of each month for BACKUP_REMOTE_MONTHS months. Nothing else is ever deleted there.
if (( offsite )); then
  now_s="$(date -u +%s)"
  while read -r remote_name; do
    stamp="${remote_name#predigol-}"; stamp="${stamp:0:8}"
    [[ "$stamp" =~ ^[0-9]{8}$ ]] || continue
    age_days=$(( (now_s - $(date -u -d "$stamp" +%s)) / 86400 ))
    keep_it=0
    (( age_days < ${BACKUP_REMOTE_DAYS:-14} )) && keep_it=1
    [[ "$(date -u -d "$stamp" +%u)" == 7 ]] && (( age_days < 7 * ${BACKUP_REMOTE_WEEKS:-8} )) && keep_it=1
    [[ "${stamp:6:2}" == 01 ]] && (( age_days < 31 * ${BACKUP_REMOTE_MONTHS:-12} )) && keep_it=1
    if (( ! keep_it )); then
      rclone deletefile "$BACKUP_RCLONE_REMOTE/db/$remote_name" && log "off-server retention: removed $remote_name"
      rclone deletefile "$BACKUP_RCLONE_REMOTE/db/${remote_name%.dump.age}.json" 2> /dev/null || true
    fi
  done < <(rclone lsf "$BACKUP_RCLONE_REMOTE/db/" --include 'predigol-*.dump.age')
fi
trap - ERR
ping_hc "${HC_PING_BACKUP:-}"
