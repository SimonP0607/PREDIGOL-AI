#!/usr/bin/env bash
# Move PrediGol's data onto this server: ONCE, into an EMPTY database, from a backup folder made on the old
# machine with `python -m scripts.backup create` (db.dump, raw.tar, manifest.json). README.md, "Corte".
#
#   bin/import.sh /root/import/<stamp>       (then: predigolctl deploy)
#
# Refuses unless: the two files match the manifest's sha256; the worker is not running here; this database holds
# no table at all (a fresh server). Then pg_restore, every table's row count compared with the manifest, the
# RAW payloads extracted without overwriting anything, their number compared with the manifest.
# Exit 0 imported and verified, 1 refused or failed (nothing half-done is left running).
set -Eeuo pipefail
# shellcheck source=bin/lib.sh
. "$(dirname "$0")/lib.sh"
exclusive deploy

SRC="${1:?usage: import.sh <backup folder with db.dump, raw.tar, manifest.json>}"
MANIFEST="$SRC/manifest.json"
for f in db.dump raw.tar manifest.json; do [[ -f "$SRC/$f" ]] || { log "import: $SRC/$f is missing"; exit 1; }; done
for f in db.dump raw.tar; do
  want="$(jq -r --arg f "$f" '.files[$f].sha256' "$MANIFEST")"
  got="$(sha256sum "$SRC/$f" | cut -d' ' -f1)"
  [[ "$want" == "$got" ]] || { log "import: $f does not match the manifest (sha256)"; exit 1; }
done
log "import: files match the manifest (revision $(jq -r .alembic_revision "$MANIFEST"), $(jq -r .rows_total "$MANIFEST") rows)"

if [[ "$(docker inspect -f '{{.State.Status}}' predigol-worker 2> /dev/null || true)" == running ]]; then
  log "import: the worker is running here - stop it first (predigolctl stop)"; exit 1
fi
compose up -d postgres
for _ in $(seq 1 60); do
  [[ "$(docker inspect -f '{{.State.Health.Status}}' predigol-postgres 2> /dev/null)" == healthy ]] && break
  sleep 5
done
tables="$(psql_q "SELECT count(*) FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog', 'information_schema')")"
[[ "$tables" == 0 ]] || { log "import: this database already holds $tables tables - refusing (import is for a fresh server)"; exit 1; }

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
cp "$SRC/db.dump" "$DB_BACKUPS/import-$stamp.dump"
trap 'rm -f "$DB_BACKUPS/import-$stamp.dump"' EXIT
log "import: pg_restore (this takes a while)"
compose exec -T postgres pg_restore -U fbi -d fbi --exit-on-error --jobs=4 "/backups/import-$stamp.dump"

log "import: comparing every table's row count with the manifest"
bad=0
while IFS=$'\t' read -r table rows; do
  got="$(psql_q "SELECT count(*) FROM $table")"
  if [[ "$got" != "$rows" ]]; then
    if jq -e --arg t "$table" '.changed_during_dump | index($t)' "$MANIFEST" > /dev/null; then
      log "  $table: $got rows, manifest $rows (written during the dump: expected to differ)"
    else
      log "  MISMATCH $table: $got rows, manifest $rows"; bad=1
    fi
  fi
done < <(jq -r '.tables | to_entries[] | [.key, .value.rows] | @tsv' "$MANIFEST")
(( bad == 0 )) || { log "import FAILED: row counts differ (the database is left as restored, for inspection)"; exit 1; }

log "import: RAW payloads into $PREDIGOL_DATA/raw (nothing existing is overwritten)"
tar -xf "$SRC/raw.tar" -C "$PREDIGOL_DATA/raw" --keep-old-files
chown -R 1000:1000 "$PREDIGOL_DATA/raw"
want_files="$(jq -r .raw_store.files "$MANIFEST")"
got_files="$(find "$PREDIGOL_DATA/raw" -type f | wc -l)"
(( got_files >= want_files )) || { log "import FAILED: $got_files RAW files, manifest $want_files"; exit 1; }
jq -n --arg at "$(date -u +%FT%TZ)" --arg src "$SRC" --arg rev "$(jq -r .alembic_revision "$MANIFEST")" \
  --argjson rows "$(jq .rows_total "$MANIFEST")" --argjson raw "$got_files" \
  '{imported_at: $at, source: $src, alembic_revision: $rev, rows: $rows, raw_files: $raw}' > "$STATE/import.json"
log "import: done and verified ($(jq -r .rows_total "$MANIFEST") rows, $got_files RAW files). Next: predigolctl deploy"
