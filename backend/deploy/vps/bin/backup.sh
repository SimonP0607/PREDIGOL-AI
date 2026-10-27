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
AGE_FILE="$DB_BACKUPS/$NAME.dump.age"
# The encrypted copy is removed on failure too: it is as big as the dump and would otherwise stay until the next disk cleanup.
trap 'rm -f "$PARTIAL" "$AGE_FILE" "$DB_BACKUPS/$NAME.json.up" "$DB_BACKUPS/$NAME.json.new"; log "backup FAILED"; ping_hc "${HC_PING_BACKUP:-}" fail; notify "la copia diaria de la base FALLÓ ($NAME)"' ERR

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

# Off the server, encrypted with the owner's age public key (the private key never touches this machine), then CHECKED
# there (each object exists with the size just written) before anything local may be rotated out.
#
# The bucket keeps three tiers, each under its own prefix with its own bucket lock and lifecycle rule (the owner sets
# them in R2; README, "Copias fuera del servidor"):
#   dumps/daily/    every dump - the timer's and each deploy's;
#   dumps/weekly/   the timer's dump of a Sunday;
#   dumps/monthly/  the timer's dump of the 1st of a month.            (bin/offsite-tiers.sh decides, from the name alone)
# Nothing in this script ever deletes anything there: the lock would refuse it, and the lifecycle rule ages the copies
# out by itself. The remote must be the bucket itself (r2:<bucket>): the locks are by prefix from the bucket's root.
offsite=0
if [[ -n "${BACKUP_RCLONE_REMOTE:-}" && -n "${BACKUP_AGE_RECIPIENT:-}" ]]; then
  offsite=1
  mapfile -t tiers < <("$KIT/bin/offsite-tiers.sh" "$NAME")
  age -r "$BACKUP_AGE_RECIPIENT" -o "$AGE_FILE" "$DB_BACKUPS/$NAME.dump"
  age_bytes="$(stat -c %s "$AGE_FILE")"
  # The encrypted file's own hash goes into the manifest the bucket receives: whoever downloads the copy (the restore drill,
  # r2-setup.sh) can prove it is bit for bit what was uploaded BEFORE decrypting it, which needs the private key.
  age_sha="$(sha256sum "$AGE_FILE" | cut -d' ' -f1)"
  tiers_json="$(printf '%s\n' "${tiers[@]}" | jq -R . | jq -sc .)"
  jq --arg remote "$BACKUP_RCLONE_REMOTE/dumps/daily/$NAME.dump.age" --argjson bytes "$age_bytes" --arg sha "$age_sha" \
    --argjson tiers "$tiers_json" '. + {offsite: {remote: $remote, bytes: $bytes, age_sha256: $sha, tiers: $tiers}}' \
    "$DB_BACKUPS/$NAME.json" > "$DB_BACKUPS/$NAME.json.up"
  for tier in "${tiers[@]}"; do
    dest="$BACKUP_RCLONE_REMOTE/dumps/$tier"
    rclone copyto --immutable --s3-chunk-size 32M --s3-upload-concurrency 4 "$AGE_FILE" "$dest/$NAME.dump.age"
    remote_bytes="$(rclone lsjson "$dest/$NAME.dump.age" | jq -r '.[0].Size // -1')"
    if [[ "$remote_bytes" != "$age_bytes" ]]; then
      log "off-server copy NOT verified in $tier ($remote_bytes bytes there, $age_bytes here)"; false
    fi
    # The manifest travels with it: a restore on another machine compares its counts with these.
    rclone copyto --immutable "$DB_BACKUPS/$NAME.json.up" "$dest/$NAME.json"
    log "copied off the server to $dest/ (age-encrypted, $age_bytes bytes, checked)"
  done
  # Only now, with every tier in place and its size checked, is the copy "verified" - rotate-dumps.sh looks for this mark.
  jq --arg at "$(date -u +%FT%TZ)" '.offsite.verified_at = $at' "$DB_BACKUPS/$NAME.json.up" > "$DB_BACKUPS/$NAME.json.new"
  mv "$DB_BACKUPS/$NAME.json.new" "$DB_BACKUPS/$NAME.json"
  rm -f "$AGE_FILE" "$DB_BACKUPS/$NAME.json.up"
else
  log "NOTE: no off-server copy configured (BACKUP_RCLONE_REMOTE + BACKUP_AGE_RECIPIENT): this dump exists only here"
fi

# Rotation on this server (bin/rotate-dumps.sh): the newest BACKUP_KEEP_DAILY dumps, the newest of each of the last
# BACKUP_KEEP_DAILY days and of each of the last BACKUP_KEEP_WEEKLY ISO weeks. With an off-server copy configured, a
# dump whose copy was never checked is KEPT - until a newer dump has been copied, and for the newest BACKUP_KEEP_UNVERIFIED
# (6) only: it may be the only one, but the disk is not unlimited.
rotated="$("$KIT/bin/rotate-dumps.sh" "$DB_BACKUPS" "${BACKUP_KEEP_DAILY:-3}" "${BACKUP_KEEP_WEEKLY:-2}" "$offsite" "${BACKUP_KEEP_UNVERIFIED:-6}")"
while IFS= read -r line; do [[ -n "$line" ]] && log "$line"; done <<< "$rotated"

# Off the server there is no retention loop any more: the bucket's lifecycle rules age the copies out (daily 15 days,
# weekly 57, monthly 396) and its locks forbid anything else. What this script CAN do is notice that a rule is missing:
# a copy far past its tier's keep is a copy R2 would bill for, for ever. A warning only; the backup itself succeeded.
if (( offsite )); then
  stale_check() {  # stale_check TIER DAYS
    local n
    n="$(rclone lsf --use-server-modtime --min-age "${2}d" --include 'predigol-*.dump.age' "$BACKUP_RCLONE_REMOTE/dumps/$1/" 2> /dev/null | wc -l || true)"
    if (( n > 0 )); then
      log "WARNING off-server: $n copy(ies) in dumps/$1/ older than ${2} days - is the lifecycle rule missing?"
      notify "R2: hay $n copia(s) en dumps/$1/ de más de ${2} días; revisa la regla de caducidad del cubo"
    fi
  }
  stale_check daily $(( ${BACKUP_REMOTE_DAYS:-14} + 4 ))
  stale_check weekly $(( 7 * (${BACKUP_REMOTE_WEEKS:-8} + 1) + 4 ))
  stale_check monthly $(( 31 * (${BACKUP_REMOTE_MONTHS:-12} + 1) + 4 ))
  # Once a week, on the Sunday copy: the locks still refuse a delete and an overwrite (bin/r2-lock-check.sh). Its verdict
  # lands in state/lock-check.json, which healthcheck.sh reads; a failing check never fails the backup.
  if [[ -z "$LABEL" && " ${tiers[*]} " == *" weekly "* ]]; then
    "$KIT/bin/r2-lock-check.sh" || { log "WARNING off-server: the bucket-lock check FAILED"; notify "R2: el candado del cubo NO impide borrar o sobrescribir; revisa bin/r2-lock-check.sh"; }
  fi
fi
trap - ERR
ping_hc "${HC_PING_BACKUP:-}"
