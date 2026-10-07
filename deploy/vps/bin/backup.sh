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

# Rotation on this server: the newest BACKUP_KEEP_DAILY dumps, plus the newest dump of each of the last
# BACKUP_KEEP_WEEKLY ISO weeks. Off-server copies follow the bucket's own retention rules.
keep_daily="${BACKUP_KEEP_DAILY:-3}"
keep_weekly="${BACKUP_KEEP_WEEKLY:-2}"
mapfile -t dumps < <(find "$DB_BACKUPS" -maxdepth 1 -name 'predigol-*.dump' -printf '%f\n' | sort -r)
declare -A keep=() weeks=()
for i in "${!dumps[@]}"; do
  d="${dumps[$i]}"
  (( i < keep_daily )) && keep["$d"]=1
  stamp="${d#predigol-}"; stamp="${stamp:0:8}"
  week="$(date -u -d "$stamp" +%G-W%V)"
  if [[ -z "${weeks[$week]:-}" && ${#weeks[@]} -lt $keep_weekly ]]; then weeks["$week"]=1; keep["$d"]=1; fi
done
for d in "${dumps[@]}"; do
  if [[ -z "${keep[$d]:-}" ]]; then rm -f "$DB_BACKUPS/$d" "$DB_BACKUPS/${d%.dump}.json"; log "rotated out $d"; fi
done

# Off the server, encrypted with the owner's age public key (the private key never touches this machine).
if [[ -n "${BACKUP_RCLONE_REMOTE:-}" && -n "${BACKUP_AGE_RECIPIENT:-}" ]]; then
  age -r "$BACKUP_AGE_RECIPIENT" -o "$DB_BACKUPS/$NAME.dump.age" "$DB_BACKUPS/$NAME.dump"
  rclone copy --immutable "$DB_BACKUPS/$NAME.dump.age" "$BACKUP_RCLONE_REMOTE/db/"
  rclone copy --immutable "$DB_BACKUPS/$NAME.json" "$BACKUP_RCLONE_REMOTE/db/"
  rm -f "$DB_BACKUPS/$NAME.dump.age"
  log "copied off the server to $BACKUP_RCLONE_REMOTE/db/ (age-encrypted)"
else
  log "NOTE: no off-server copy configured (BACKUP_RCLONE_REMOTE + BACKUP_AGE_RECIPIENT): this dump exists only here"
fi
trap - ERR
ping_hc "${HC_PING_BACKUP:-}"
