#!/usr/bin/env bash
# Daily maintenance on BOX A (systemd timer, 04:10 UTC).
#   1. archive live-odds months older than the retention window to Parquet, verify, then drop
#   2. logical dump of the database (pg_dump inside the server container: same major version)
#   3. copy archives, dumps and the RAW payload store to Cloudflare R2 (rclone remote "r2")
# set -e: a failed archive or verify stops the run before anything is dropped or copied.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p data/backups data/archive data/raw

docker compose exec -T worker python scripts/live_retention.py archive --drop
docker compose exec -T worker python scripts/live_retention.py verify

stamp=$(date -u +%F)
docker exec fbi-postgres pg_dump -U fbi -d fbi -Fc > "data/backups/fbi-$stamp.dump.part"
# a dump that cannot be listed is not a backup
docker exec -i fbi-postgres pg_restore --list < "data/backups/fbi-$stamp.dump.part" > /dev/null
mv "data/backups/fbi-$stamp.dump.part" "data/backups/fbi-$stamp.dump"
find data/backups -name 'fbi-*.dump' -mtime +7 -delete

if command -v rclone >/dev/null; then
  rclone copy data/archive r2:fbi-archive --immutable --transfers 4
  rclone copy data/raw     r2:fbi-raw     --immutable --transfers 8
  rclone copy data/backups r2:fbi-backups --transfers 2
else
  echo "rclone missing: nothing left the box" >&2
  exit 1
fi
