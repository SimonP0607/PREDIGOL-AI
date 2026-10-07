#!/bin/sh
# predigol-pitr <pgbackrest command> [options] - pgBackRest on the 'predigol' stanza, as postgres. Used by the
# host's bin/pitr.sh (docker exec -u postgres predigol-postgres predigol-pitr backup --type=diff, ...).
if [ ! -f /etc/pgbackrest/pgbackrest.conf ]; then
  echo "predigol-pitr: PITR is not configured (PITR_S3_BUCKET is empty in the env file)" >&2
  exit 3
fi
exec pgbackrest --stanza=predigol "$@"
