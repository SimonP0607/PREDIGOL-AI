#!/usr/bin/env bash
# Who holds (or waits for) a write lock on the tables the deploy steps could meet, and which long jobs hold their advisory lock. Read-only (a
# read-only session), a sample every 3 seconds, written to lockwatch.log beside this script. (F14 template.)
OUT="$(dirname "$(readlink -f "$0")")/lockwatch.log"
read -r -d '' SQL_LOCKS <<'SQLEND'
SELECT to_char(clock_timestamp(), 'HH24:MI:SS') AS t,
       n.nspname || '.' || c.relname AS rel, l.mode, l.granted, l.pid,
       coalesce((SELECT a.usename FROM pg_stat_activity a WHERE a.pid = l.pid), '?') AS role,
       coalesce((SELECT min(x.transactionid::text::bigint)::text FROM pg_locks x WHERE x.pid = l.pid AND x.locktype = 'transactionid' AND x.mode = 'ExclusiveLock' AND x.granted), '-') AS xid,
       coalesce((SELECT string_agg(b::text, ',') FROM unnest(pg_blocking_pids(l.pid)) b), '-') AS blocked_by
  FROM pg_locks l
  JOIN pg_class c ON c.oid = l.relation
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE (n.nspname, c.relname) IN (('core', 'fixtures'), ('models', 'model_registry'), ('models', 'model_versions'), ('models', 'match_forecasts'), ('auth', 'users'), ('auth', 'sessions'), ('ai', 'usage'), ('ai', 'match_briefs'), ('ai', 'cycles'), ('ai', 'feature_gates'), ('ai', 'evidence'), ('ai', 'research_cache'), ('intel', 'promotions'))
   AND l.mode IN ('RowExclusiveLock', 'ShareUpdateExclusiveLock', 'ShareLock', 'ShareRowExclusiveLock', 'ExclusiveLock', 'AccessExclusiveLock')
   AND l.pid <> pg_backend_pid()
   AND (NOT l.granted OR EXISTS (SELECT 1 FROM pg_locks x WHERE x.pid = l.pid AND x.locktype = 'transactionid' AND x.mode = 'ExclusiveLock' AND x.granted))
 ORDER BY 2, 5
SQLEND
read -r -d '' SQL_ADVISORY <<'SQLEND'
SELECT to_char(clock_timestamp(), 'HH24:MI:SS') AS t, 'adv' AS what, l.objid AS key, l.pid,
       coalesce((SELECT a.usename FROM pg_stat_activity a WHERE a.pid = l.pid), '?') AS role
  FROM pg_locks l
 WHERE l.locktype = 'advisory' AND l.granted AND l.classid = 0 AND l.objsubid = 1 AND l.objid IN (7310076, 7310077, 7310078, 7310079) AND l.pid <> pg_backend_pid()
 ORDER BY 3, 4
SQLEND
end=$(( $(date +%s) + ${1:-1800} ))
echo "start $(date -u +%FT%TZ) for ${1:-1800}s" >> "$OUT"
while [ "$(date +%s)" -lt "$end" ]; do
  docker exec -e PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=10000' predigol-postgres \
    psql -U fbi -d fbi -At -F '|' -c "$SQL_LOCKS" -c "$SQL_ADVISORY" < /dev/null >> "$OUT" 2>&1
  sleep 3
done
echo "done $(date -u +%FT%TZ)" >> "$OUT"
