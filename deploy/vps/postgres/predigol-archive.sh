#!/bin/sh
# archive_command: one WAL segment to the PITR repository (pgBackRest, asynchronous push), or - when PITR is not
# configured - accept it and let PostgreSQL recycle it. archive-push-queue-max bounds the local queue: if the
# repository stays unreachable for long, segments are DROPPED from the queue (PITR gets a gap, reported by the
# monitor) instead of filling the disk and stopping the database.
if [ -f /etc/pgbackrest/pgbackrest.conf ]; then
  exec pgbackrest --stanza=predigol archive-push "$1"
fi
exit 0
