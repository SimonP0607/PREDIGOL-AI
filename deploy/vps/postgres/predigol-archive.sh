#!/bin/sh
# archive_command: one WAL segment to the PITR repository (pgBackRest, asynchronous push), or - when PITR is not
# configured - accept it and let PostgreSQL recycle it. archive-push-queue-max bounds the local queue: if the
# repository stays unreachable for long, segments are DROPPED from the queue (PITR gets a gap, reported by the
# monitor) instead of filling the disk and stopping the database.
#
# While bin/import.sh restores the old machine's dump into a fresh database it leaves archive-paused in the spool
# folder: that WAL is worth nothing (the full backup taken right after the import starts the recovery window) and
# pushing the whole database through the archive would only cost hours. Segments are accepted and recycled.
if [ -f /var/spool/pgbackrest/archive-paused ]; then
  exit 0
fi
if [ -f /etc/pgbackrest/pgbackrest.conf ]; then
  exec pgbackrest --stanza=predigol archive-push "$1"
fi
exit 0
