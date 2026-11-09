#!/usr/bin/env bash
# Which queries cost the most, from pg_stat_statements (OPS-001). For the owner and for whoever tunes the database; nothing here changes data.
#
#   predigolctl pgstat status        is the library loaded, is the extension created, how many statements it holds
#   predigolctl pgstat enable        CREATE EXTENSION IF NOT EXISTS pg_stat_statements (once, after PostgreSQL started with the library; idempotent)
#   predigolctl pgstat top [N]       the N statements (default 15, at most 100) that took the most total time: calls, total and mean ms, rows
#   predigolctl pgstat reset         empty the counters (to measure a change from zero)
#
# pg_stat_statements stores the shape of each query with its constants replaced by $1, $2...: no value a user typed is in it. `top` cuts the text at
# 160 characters. Exit 0 ok | 1 the library is not loaded (PostgreSQL has not been restarted with the compose that names it) | 2 bad usage.
set -Eeuo pipefail
# shellcheck source=bin/lib.sh
. "$(dirname "$0")/lib.sh"

q() { compose exec -T postgres psql -U fbi -d fbi -v ON_ERROR_STOP=1 -qAtX "$@" < /dev/null; }
loaded() { q -c "SELECT current_setting('shared_preload_libraries')" | tr -d ' ' | tr ',' '\n' | grep -qx 'pg_stat_statements'; }
need_loaded() { loaded || { log "pgstat: pg_stat_statements is not in shared_preload_libraries: PostgreSQL has not started with the compose of OPS-001 yet"; exit 1; }; }

case "${1:-}" in
  status)
    if loaded; then echo "library: loaded"; else echo "library: NOT loaded"; fi
    echo "extension: $(q -c "SELECT CASE WHEN EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements') THEN 'created' ELSE 'not created' END")"
    echo "auto_explain.log_min_duration: $(q -c "SELECT coalesce(current_setting('auto_explain.log_min_duration', true), 'not loaded')")"
    if loaded && [[ "$(q -c "SELECT count(*) FROM pg_extension WHERE extname = 'pg_stat_statements'")" == 1 ]]; then
      echo "statements held: $(q -c "SELECT count(*) FROM pg_stat_statements")"
    fi
    ;;
  enable)
    need_loaded
    q -c "CREATE EXTENSION IF NOT EXISTS pg_stat_statements"
    log "pgstat: pg_stat_statements is created in the database fbi"
    ;;
  top)
    n="${2:-15}"
    [[ "$n" =~ ^[0-9]+$ ]] && (( n >= 1 && n <= 100 )) || { echo "usage: predigolctl pgstat top [N]   (N from 1 to 100)" >&2; exit 2; }
    need_loaded
    q -c "SET default_transaction_read_only = on" -F ' | ' -c "SELECT calls, round(total_exec_time::numeric, 0) AS total_ms, round(mean_exec_time::numeric, 1) AS mean_ms, rows, left(regexp_replace(query, '\s+', ' ', 'g'), 160) AS query FROM pg_stat_statements WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database()) ORDER BY total_exec_time DESC LIMIT $n"
    ;;
  reset)
    need_loaded
    q -c "SELECT pg_stat_statements_reset()" > /dev/null
    log "pgstat: the counters are empty"
    ;;
  *) echo "usage: predigolctl pgstat status|enable|top [N]|reset" >&2; exit 2 ;;
esac