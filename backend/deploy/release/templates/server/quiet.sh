#!/usr/bin/env bash
# Sourced by step_precheck.sh and step_deploy.sh (not run on its own): is the server quiet enough to restart the worker and the api?
# (F14 template: claude/PLANTILLAS_DESPLIEGUE_GUARDADO.md. IA release: the tables 0110 and 0111 lock - ai.usage, ai.match_briefs, intel.promotions -
# and the one 0112 alters - ai.cycles - are watched too, so a migration never waits for a long writer: it would fail at its 10 s lock timeout;
# 0114 alters ai.evidence and ai.research_cache, which are watched as well.)
#
# THE CLOCK DECIDES NOTHING (owner's order, 26-oct-2026: no deployment windows; every finished piece is deployed as soon as it is finished). What
# keeps a deploy from cutting a job of the server is what this file reads - the jobs themselves, never an hour of the day: quiet_check (a long write
# transaction, the long jobs of the worker) and heavy_check (a backup, a PITR run, the maintenance or a restore test running or about to start).
#
# The deploy restarts the containers, so it must not cut a long write transaction (fixtures_sync keeps one open for 24 to 57 minutes) and it
# must not leave behind a query that goes on running in Postgres after its client is gone (the nightly run holds an advisory lock while it
# lives, and a statement that is still running holds it after the worker is stopped). The role these scripts use (fbi) cannot see the
# state of the sessions of the other roles in pg_stat_activity, so a test on the age of their transactions finds nothing, always. pg_locks is
# shown in full to every role, so the check reads that:
#   1. the sessions that have WRITTEN something in their transaction (they hold a transactionid lock) and hold a write lock on one of the
#      tables the release could meet, sampled twice, QUIET_GAP seconds apart; the same transaction in both samples has been open that long;
#   2. the advisory locks of the long jobs of the worker: 7310077 (the nightly run and the calibration), 7310078 (the weekly run) and
#      7310079 (the backfills and the manual runs).
# quiet_check prints what it sees and returns 0 (quiet), 2 (not quiet) or 3 (it could not look: the caller treats it as not quiet).

QUIET_GAP=${QUIET_GAP:-20}
QUIET_TABLES="('core','fixtures'),('raw','ingestion_payloads'),('intel','postmortems'),('intel','entity_memory'),('ai','usage'),('ai','match_briefs'),('ai','cycles'),('intel','promotions'),('ai','evidence'),('ai','research_cache'),('ai','feature_gates')"
QUIET_WRITE_MODES="'RowExclusiveLock','ShareUpdateExclusiveLock','ShareLock','ShareRowExclusiveLock','ExclusiveLock','AccessExclusiveLock'"

quiet_sql() {
  docker exec -e PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=20000' predigol-postgres \
    psql -U fbi -d fbi -At -F '|' -v ON_ERROR_STOP=1 -c "$1" < /dev/null
}

quiet_writers() {
  quiet_sql "SELECT x.pid || ':' || x.transactionid FROM pg_locks x
              WHERE x.locktype = 'transactionid' AND x.mode = 'ExclusiveLock' AND x.granted AND x.pid <> pg_backend_pid()
                AND EXISTS (SELECT 1 FROM pg_locks l JOIN pg_class c ON c.oid = l.relation JOIN pg_namespace n ON n.oid = c.relnamespace
                             WHERE l.pid = x.pid AND l.granted AND l.mode IN ($QUIET_WRITE_MODES) AND (n.nspname, c.relname) IN ($QUIET_TABLES))
              ORDER BY 1"
}

quiet_check() {
  local first second both tx pid role tables held line rc=0
  first=$(quiet_writers) || { echo "quiet check: could not read pg_locks"; return 3; }
  sleep "$QUIET_GAP"
  second=$(quiet_writers) || { echo "quiet check: could not read pg_locks"; return 3; }
  both=$(comm -12 <(printf '%s\n' "$first" | sort) <(printf '%s\n' "$second" | sort) | grep . || true)
  held=$(quiet_sql "SELECT 'pid ' || l.pid || ' holds the advisory lock ' || l.objid || CASE l.objid WHEN 7310077 THEN ' (the nightly run)' WHEN 7310078 THEN ' (the weekly run)' ELSE ' (a backfill or a manual run)' END
                      FROM pg_locks l WHERE l.locktype = 'advisory' AND l.granted AND l.classid = 0 AND l.objsubid = 1 AND l.objid IN (7310077, 7310078, 7310079) ORDER BY l.pid") \
    || { echo "quiet check: could not read the advisory locks"; return 3; }
  for tx in $both; do
    rc=2
    pid=${tx%%:*}
    role=$(quiet_sql "SELECT coalesce(usename, '?') FROM pg_stat_activity WHERE pid = $pid") || role="?"
    tables=$(quiet_sql "SELECT string_agg(DISTINCT n.nspname || '.' || c.relname, ', ') FROM pg_locks l JOIN pg_class c ON c.oid = l.relation JOIN pg_namespace n ON n.oid = c.relnamespace
                         WHERE l.pid = $pid AND l.granted AND l.mode IN ($QUIET_WRITE_MODES) AND (n.nspname, c.relname) IN ($QUIET_TABLES)") || tables="?"
    echo "not quiet: pid $pid (role ${role:-?}) has had the same write transaction open for at least ${QUIET_GAP} s (transaction id ${tx#*:}) with a write lock on: ${tables:-?}"
  done
  if [ -n "$held" ]; then
    rc=2
    while IFS= read -r line; do echo "not quiet: $line"; done <<< "$held"
  fi
  if [ "$rc" -eq 0 ]; then
    echo "quiet: no write transaction open for ${QUIET_GAP} s on the tables of the release, and none of the long jobs (nightly, weekly, backfill) holds its advisory lock"
  fi
  return "$rc"
}

# heavy_check: no heavy job of the server runs, and none is about to start. These jobs - the daily backup, the PITR base backup, the daily
# maintenance, the weekly restore test, the PITR verification and test - are what a deploy must not meet: its own pre-deploy backup finds the backup
# lock taken and the deploy stops halfway, and a migration that asks for a lock on a table finds pg_dump holding it. So the deploy waits until the job
# has ended, and starts at once outside of that. Three things are read, none of them a clock window:
#   1. the locks these jobs take (state/backup.lock, restore-test.lock, pitr.lock, maint.lock);
#   2. their services (a oneshot service is "activating" while it runs, so ActiveState is read, not is-active);
#   3. when their timers elapse next: within HEAVY_LOOKAHEAD_MIN minutes (40 by default: a bit more than what a deploy needs) counts as about to start.
# Prints what it sees; returns 0 (free), 2 (busy) or 3 (it could not look: the caller treats it as busy).
HEAVY_LOOKAHEAD_MIN=${HEAVY_LOOKAHEAD_MIN:-40}
HEAVY_LOCKS="backup restore-test pitr maint"
HEAVY_SERVICES="predigol-backup predigol-pitr predigol-maint predigol-restore-test predigol-pitr-test predigol-pitr-verify"

heavy_check() {
  local rc=0 lk f u state t timers nxt ep now limit look=$HEAVY_LOOKAHEAD_MIN
  now=$(date +%s)
  limit=$((now + look * 60))
  for lk in $HEAVY_LOCKS; do
    f=/srv/predigol/state/$lk.lock
    if [ -e "$f" ] && ! flock -n "$f" true 2> /dev/null; then
      echo "not quiet: the lock $lk is held, so a heavy job of the server is running"
      rc=2
    fi
  done
  for u in $HEAVY_SERVICES; do
    state=$(systemctl show -p ActiveState --value "$u.service" 2> /dev/null < /dev/null) || state=""
    case "$state" in
      active | activating | reloading | deactivating) echo "not quiet: $u.service is $state"; rc=2 ;;
    esac
  done
  timers=$(systemctl list-unit-files --no-legend --plain 'predigol-*.timer' 2> /dev/null < /dev/null | awk '{ print $1 }') || timers=""
  if [ -z "$timers" ]; then echo "heavy check: no predigol-*.timer is installed, so there is no job to meet"; fi
  for t in $timers; do
    case "$t" in predigol-health.timer | predigol-raw-sync.timer) continue ;; esac # every 5 minutes and hourly, light: they never block
    nxt=$(TZ=UTC LC_ALL=C systemctl show -p NextElapseUSecRealtime --value "$t" 2> /dev/null < /dev/null || true)
    if [ -z "$nxt" ] || [ "$nxt" = "n/a" ]; then continue; fi
    ep=$(date -u -d "$nxt" +%s 2> /dev/null) || { echo "heavy check: the next run of $t ('$nxt') is not read as a date"; return 3; }
    if [ "$ep" -lt $((now - 900)) ]; then
      echo "heavy check: $t shows a next run ($nxt) more than 15 minutes in the past: systemd would have started it, so it is not counted"
    elif [ "$ep" -le "$limit" ]; then
      echo "not quiet: $t elapses at $nxt, within the next $look minutes, and a deploy would overlap it"
      rc=2
    fi
  done
  if [ "$rc" -eq 0 ]; then
    echo "quiet: no heavy job of the server (backup, PITR, maintenance, restore test) runs, and none starts within $look minutes"
  fi
  return "$rc"
}
