#!/bin/sh
# Writes pgBackRest's configuration from the environment (PITR_*), readable only by postgres, then hands over to
# the official entrypoint. Without PITR_S3_BUCKET nothing is written and WAL is not archived (predigol-archive
# then accepts and drops each segment, so pg_wal never fills up): logical dumps remain the only backups.
set -eu
CONF=/etc/pgbackrest/pgbackrest.conf
if [ -n "${PITR_S3_BUCKET:-}" ]; then
  : "${PITR_S3_ENDPOINT:?PITR_S3_ENDPOINT}" "${PITR_S3_KEY:?PITR_S3_KEY}" "${PITR_S3_KEY_SECRET:?PITR_S3_KEY_SECRET}"
  : "${PITR_CIPHER_PASS:?PITR_CIPHER_PASS}"
  umask 077
  cat > "$CONF.new" <<CONF
[global]
repo1-type=s3
repo1-path=${PITR_S3_PATH:-/pgbackrest}
repo1-s3-bucket=${PITR_S3_BUCKET}
repo1-s3-endpoint=${PITR_S3_ENDPOINT}
repo1-storage-port=${PITR_S3_PORT:-443}
repo1-s3-region=${PITR_S3_REGION:-auto}
repo1-s3-key=${PITR_S3_KEY}
repo1-s3-key-secret=${PITR_S3_KEY_SECRET}
repo1-s3-uri-style=${PITR_S3_URI_STYLE:-path}
repo1-storage-verify-tls=${PITR_S3_VERIFY_TLS:-y}
repo1-cipher-type=aes-256-cbc
repo1-cipher-pass=${PITR_CIPHER_PASS}
repo1-retention-full=${PITR_RETENTION_FULL:-4}
repo1-retention-full-type=count
compress-type=zst
compress-level=3
process-max=${PITR_PROCESS_MAX:-2}
archive-async=y
archive-push-queue-max=${PITR_QUEUE_MAX:-4GiB}
spool-path=/var/spool/pgbackrest
log-path=/var/log/pgbackrest
log-level-console=info
log-level-file=detail
start-fast=y
delta=y

[predigol]
pg1-path=/var/lib/postgresql/data
pg1-socket-path=/var/run/postgresql
pg1-user=postgres
CONF
  if [ -n "${PITR_S3_CA_FILE:-}" ]; then echo "repo1-storage-ca-file=${PITR_S3_CA_FILE}" >> "$CONF.new"; fi
  mv "$CONF.new" "$CONF"
  chown postgres:postgres "$CONF"
  chmod 0600 "$CONF"
else
  rm -f "$CONF"
fi
chown postgres:postgres /var/spool/pgbackrest /var/log/pgbackrest
exec docker-entrypoint.sh "$@"
