#!/usr/bin/env bash
# The off-server restore drill, on the OWNER'S machine (the one that holds the age private key): the newest dump on
# R2 is downloaded, decrypted and restored into a throwaway PostgreSQL container with no network; the schema
# revision and the key tables' counts are checked against the manifest the backup wrote. Nothing is uploaded,
# nothing on the server is touched.
#
#   r2-restore-drill.sh ~/.fbi/r2.env ~/.fbi/predigol-backup.agekey [DUMP_NAME]
#
# Needs docker, rclone, age and jq on this machine; ~/.fbi/r2.env as on the server (R2_ACCOUNT_ID,
# R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET).
set -Eeuo pipefail
ENV_FILE="${1:?usage: $0 r2.env age.key [DUMP_NAME]}"
KEY="${2:?usage: $0 r2.env age.key [DUMP_NAME]}"
# shellcheck disable=SC1090
. "$ENV_FILE"
work="$(mktemp -d)"; box="predigol-r2-drill"
trap 'docker rm -f "$box" > /dev/null 2>&1 || true; rm -rf "$work"' EXIT
export RCLONE_CONFIG_DRILL_TYPE=s3 RCLONE_CONFIG_DRILL_PROVIDER=Cloudflare \
  RCLONE_CONFIG_DRILL_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" RCLONE_CONFIG_DRILL_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" \
  RCLONE_CONFIG_DRILL_ENDPOINT="https://$R2_ACCOUNT_ID.r2.cloudflarestorage.com"
name="${3:-$(rclone lsf "drill:$R2_BUCKET/db/" --include 'predigol-*.dump.age' | sort | tail -1)}"
name="${name%.dump.age}"
echo "drill: $name"
rclone copyto "drill:$R2_BUCKET/db/$name.dump.age" "$work/$name.dump.age"
rclone copyto "drill:$R2_BUCKET/db/$name.json" "$work/$name.json"
age -d -i "$KEY" -o "$work/$name.dump" "$work/$name.dump.age"
[[ "$(sha256sum "$work/$name.dump" | cut -d' ' -f1)" == "$(jq -r .sha256 "$work/$name.json")" ]] \
  || { echo "drill FAILED: the decrypted dump's sha256 is not the one the backup recorded"; exit 1; }
docker run -d --name "$box" --network none -e POSTGRES_PASSWORD=drill -e POSTGRES_DB=restore \
  -v "$work:/dump:ro" postgres:16 > /dev/null
for _ in $(seq 60); do docker exec "$box" pg_isready -U postgres -d restore -q 2> /dev/null && break; sleep 2; done
started=$(date +%s)
docker exec "$box" pg_restore -U postgres -d restore --no-owner --no-privileges --jobs=2 "/dump/$name.dump" \
  > "$work/restore.log" 2>&1 || true
q() { docker exec "$box" psql -U postgres -d restore -qAtX -c "$1"; }
revision="$(q "SELECT version_num FROM public.alembic_version")"
[[ "$revision" == "$(jq -r .alembic_revision "$work/$name.json")" ]] \
  || { echo "drill FAILED: revision $revision, expected $(jq -r .alembic_revision "$work/$name.json")"; exit 1; }
fail=0
for t in $(jq -r '.counts_before | keys[]' "$work/$name.json"); do
  n="$(q "SELECT count(*) FROM $t")"
  lo="$(jq -r --arg t "$t" '.counts_before[$t]' "$work/$name.json")"; hi="$(jq -r --arg t "$t" '.counts_after[$t]' "$work/$name.json")"
  if (( n < lo || n > hi )); then echo "  $t: $n outside [$lo, $hi]"; fail=1; else echo "  $t: $n ok"; fi
done
(( fail == 0 )) || { echo "drill FAILED: counts"; exit 1; }
echo "drill PASSED in $(( $(date +%s) - started ))s: $name restored from R2, revision $revision"
