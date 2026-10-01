#!/usr/bin/env bash
# One-off, on BOX B: seed the replica volume from the primary (pg_basebackup),
# then start it as a hot standby. Re-running wipes the replica volume only.
set -euo pipefail
cd "$(dirname "$0")"
set -a; . ./.env; set +a
: "${PRIMARY_PRIVATE_IP:?}" "${REPLICATION_PASSWORD:?}"

docker compose down replica 2>/dev/null || true
docker volume rm -f fbi-api_replica_data >/dev/null
docker run --rm -v fbi-api_replica_data:/var/lib/postgresql/data \
  -e PGPASSWORD="$REPLICATION_PASSWORD" postgres:16-alpine \
  sh -c "pg_basebackup -h $PRIMARY_PRIVATE_IP -U replicator -D /var/lib/postgresql/data -R -X stream -P \
         && chown -R postgres:postgres /var/lib/postgresql/data && chmod 700 /var/lib/postgresql/data"
docker compose up -d replica
echo "replica seeded; check: docker exec fbi-replica psql -U fbi -d fbi -c 'select pg_is_in_recovery()'"
