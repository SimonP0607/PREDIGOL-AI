#!/usr/bin/env bash
# Release __REL__, step 1: a verified backup and the restore test of it (plan UX, section 46: BACKUP -> RESTORE TEST before every release with a
# migration, and before A0 as the reference of the level-4 rollback). Same as F2-F14.
set -Eeuo pipefail
D=/root/releases/__STAMP__
cd "$D"
date -u +%FT%TZ > backup.started
predigolctl backup --label __REL__ > backup.log 2>&1
date -u +%FT%TZ > backup.finished
predigolctl restore-test > restore.log 2>&1
date -u +%FT%TZ > restore.finished
tail -n 20 restore.log
