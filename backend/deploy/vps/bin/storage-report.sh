#!/usr/bin/env bash
# Four times a day (predigol-storage.timer): where the disk goes, measured, never changed.
#
#   bin/storage-report.sh [--quiet]
#
# Reads only. Writes $PREDIGOL_DATA/state/storage/report.json (the latest measure: the Admin Console's «Almacenamiento»
# page reads it through a read-only mount) and appends one line a day to $PREDIGOL_DATA/state/storage/history.jsonl.
# It never prints or stores a file's content, a secret or an environment: sizes, counts, names and dates only.
#
# Two alarms, each told to the owner (Telegram, if configured) only when it CHANGES:
#   * the level of the disk: ok < 70 % <= aviso < 80 % <= alto < 90 % <= crítico;
#   * an anomaly of growth: the last day grew more than max(5 x the median of the 14 days before, 2 GiB). A deploy
#     week can do that legitimately; the notice says how much and from which day, the owner decides.
set -Eeuo pipefail
# shellcheck source=bin/lib.sh
. "$(dirname "$0")/lib.sh"

QUIET=0
[[ "${1:-}" == "--quiet" ]] && QUIET=1
say() { (( QUIET )) || log "$*"; }

OUT_DIR="${STORAGE_REPORT_DIR:-$STATE/storage}"  # overridable only to try the script without touching the real report
mkdir -p "$OUT_DIR"
chmod 755 "$OUT_DIR"
REPORT="$OUT_DIR/report.json"
HISTORY="$OUT_DIR/history.jsonl"
GIB=$(( 1024 * 1024 * 1024 ))

bytes_of() { du -sxB1 "$1" 2> /dev/null | awk '{print $1+0}' || echo 0; }
num() { [[ "${1:-}" =~ ^[0-9]+$ ]] && echo "$1" || echo 0; }

# 1. The disk.
read -r size used avail < <(df -PB1 "$PREDIGOL_DATA" | awk 'NR==2 {print $2, $3, $4}')
pct=$(( (used * 100 + used + avail - 1) / (used + avail) ))  # the way df rounds: up, over used + available
if (( pct >= 90 )); then level=critical; elif (( pct >= 80 )); then level=high
elif (( pct >= 70 )); then level=warning; else level=ok; fi

# 2. The parts on the disk (du of each; the database's folder is the files PostgreSQL keeps, WAL included).
pgdata="$(bytes_of "$PREDIGOL_DATA/pgdata")"
raw="$(bytes_of "$PREDIGOL_DATA/raw")"
raw_files="$(find "$PREDIGOL_DATA/raw" -xdev -type f 2> /dev/null | wc -l)"
backups="$(bytes_of "$DB_BACKUPS")"
backup_count="$(find "$DB_BACKUPS" -maxdepth 1 -name '*.dump' 2> /dev/null | wc -l)"
releases="$(bytes_of /root/releases)"
logs=$(( $(bytes_of /var/log) + $(du -cB1 /var/lib/docker/containers/*/*-json.log 2> /dev/null | awk 'END {print $1+0}') ))

# 3. Docker, from its own accounting (sizes in bytes).
docker_json="$(docker system df --format '{{json .}}' 2> /dev/null || true)"
dk() {  # dk TYPE FIELD -> bytes (docker prints "16.02GB" or "3.506GB (21%)")
  jq -r --arg t "$1" --arg f "$2" 'select(.Type == $t) | .[$f]' <<< "$docker_json" | head -1 |
    awk '{v=$1; sub(/\(.*/, "", v); n=v+0; u=v; gsub(/[0-9.]/, "", u);
          m=(u=="kB")?1e3:(u=="MB")?1e6:(u=="GB")?1e9:(u=="TB")?1e12:1; printf "%.0f\n", n*m}'
}
img="$(num "$(dk Images Size)")"; img_rec="$(num "$(dk Images Reclaimable)")"
vol="$(num "$(dk 'Local Volumes' Size)")"; vol_rec="$(num "$(dk 'Local Volumes' Reclaimable)")"
cache="$(num "$(dk 'Build Cache' Size)")"; cache_rec="$(num "$(dk 'Build Cache' Reclaimable)")"
images_total="$(docker images -q 2> /dev/null | sort -u | wc -l)"
orphans="$(docker volume ls -q -f dangling=true 2> /dev/null | wc -l)"

# 4. The database, as PostgreSQL counts it (read-only).
db_bytes="$(num "$(psql_q "SELECT pg_database_size('fbi')" 2> /dev/null || true)")"
top_tables="$(compose exec -T postgres psql -U fbi -d fbi -v ON_ERROR_STOP=1 -qAtX -c "SET default_transaction_read_only = on" \
  -c "SELECT coalesce(jsonb_agg(t), '[]') FROM (SELECT n.nspname || '.' || c.relname AS name, pg_total_relation_size(c.oid) AS bytes
      FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.relkind IN ('r', 'p', 'm')
      AND n.nspname NOT IN ('pg_catalog', 'information_schema') AND n.nspname NOT LIKE 'pg_toast%'
      ORDER BY pg_total_relation_size(c.oid) DESC LIMIT 12) t" < /dev/null 2> /dev/null | tail -n 1 || true)"
jq -e 'type == "array"' <<< "$top_tables" > /dev/null 2>&1 || top_tables='[]'

# 5. The copies: the newest manifest (size, sha256, off-server copy) and the last restore test.
latest_manifest="$(ls -t "$DB_BACKUPS"/predigol-*.json 2> /dev/null | head -1 || true)"
latest='null'
if [[ -n "$latest_manifest" ]]; then
  latest="$(jq -c --arg name "$(basename "$latest_manifest" .json)" --arg at "$(date -u -r "$latest_manifest" +%FT%TZ)" \
    '{name: $name, at: $at, bytes: (.bytes // null), sha256: (.sha256 // null), offsite: (.offsite // null)}' \
    "$latest_manifest" 2> /dev/null || echo null)"
fi
last_offsite="$(for m in $(ls -t "$DB_BACKUPS"/predigol-*.json 2> /dev/null | head -60); do
  jq -r '.offsite.verified_at // empty' "$m" 2> /dev/null; done | sort | tail -1)"
restore='null'
[[ -r "$STATE/restore-test.json" ]] && restore="$(jq -c '{dump: (.dump // null), at: (.tested_at // .at // null), passed: (.passed // null),
  seconds: (.seconds // null)}' "$STATE/restore-test.json" 2> /dev/null || echo null)"
offsite_configured=false
[[ -n "${BACKUP_RCLONE_REMOTE:-}" ]] && offsite_configured=true
# The last cleanup, when the deploy's prune writes one ({at, freed_bytes, items: [..]}; see POLITICA_ALMACENAMIENTO.md).
cleanup='null'
[[ -r "$STATE/prune.json" ]] && cleanup="$(jq -c '{at: (.at // null), freed_bytes: (.freed_bytes // null),
  items: ((.items // []) | .[:50])}' "$STATE/prune.json" 2> /dev/null || echo null)"

# 6. Growth: one line a day (with the largest tables, so that which table grows can be read later); the anomaly compares
#    the last day with the median of the 14 before it.
today="$(date -u +%F)"
line="$(jq -cn --arg date "$today" --argjson used "$used" --argjson db "$db_bytes" --argjson raw "$raw" \
  --argjson docker "$(( img + vol + cache ))" --argjson backups "$backups" --argjson top "$top_tables" \
  '{date: $date, used_bytes: $used, db_bytes: $db, raw_bytes: $raw, docker_bytes: $docker, backups_bytes: $backups,
    tables: ($top | map({(.name): .bytes}) | add // {})}')"
if grep -q "\"date\":\"$today\"" "$HISTORY" 2> /dev/null; then
  grep -v "\"date\":\"$today\"" "$HISTORY" > "$HISTORY.new" || true
  echo "$line" >> "$HISTORY.new"; mv "$HISTORY.new" "$HISTORY"
else
  echo "$line" >> "$HISTORY"
fi
growth="$(tail -n 16 "$HISTORY" | jq -sc --argjson floor "$(( 2 * GIB ))" '
  [range(1; length) as $i | {date: .[$i].date, delta: (.[$i].used_bytes - .[$i - 1].used_bytes)}] as $d
  | if ($d | length) < 2 then {last_delta_bytes: ($d[-1].delta // null), median_delta_bytes: null, anomaly: false, days: ($d | length)}
    else ($d[:-1] | map(.delta) | sort) as $s
      | ($s[(($s | length) / 2 | floor)]) as $median
      | {last_day: $d[-1].date, last_delta_bytes: $d[-1].delta, median_delta_bytes: $median, days: ($d | length),
         anomaly: ($d[-1].delta > ([5 * ([$median, 0] | max), $floor] | max))}
    end')"

jq -n --arg at "$(date -u +%FT%TZ)" --arg host "$(hostname)" --argjson size "$size" --argjson used "$used" \
  --argjson avail "$avail" --argjson pct "$pct" --arg level "$level" \
  --argjson pgdata "$pgdata" --argjson raw "$raw" --argjson raw_files "$raw_files" --argjson backups "$backups" \
  --argjson backup_count "$backup_count" --argjson releases "$releases" --argjson logs "$logs" \
  --argjson img "$img" --argjson img_rec "$img_rec" --argjson images_total "$images_total" \
  --argjson vol "$vol" --argjson vol_rec "$vol_rec" --argjson orphans "$orphans" \
  --argjson cache "$cache" --argjson cache_rec "$cache_rec" \
  --argjson db "$db_bytes" --argjson top "$top_tables" --argjson latest "$latest" --arg last_offsite "$last_offsite" \
  --argjson restore "$restore" --argjson offsite "$offsite_configured" --argjson cleanup "$cleanup" \
  --argjson growth "$growth" --argjson keep_daily "$(num "${BACKUP_KEEP_DAILY:-3}")" \
  --argjson keep_weekly "$(num "${BACKUP_KEEP_WEEKLY:-2}")" '
  {version: "storage-report-v1", measured_at: $at, host: $host,
   disk: {size_bytes: $size, used_bytes: $used, avail_bytes: $avail, pct: $pct, level: $level},
   parts: {pgdata_bytes: $pgdata, raw_bytes: $raw, raw_files: $raw_files, backups_bytes: $backups,
           backups_count: $backup_count, releases_bytes: $releases, logs_bytes: $logs},
   docker: {images_bytes: $img, images_reclaimable_bytes: $img_rec, images_count: $images_total,
            volumes_bytes: $vol, volumes_orphan_bytes: $vol_rec, volumes_orphan_count: $orphans,
            build_cache_bytes: $cache, build_cache_reclaimable_bytes: $cache_rec},
   database: {bytes: $db, top_tables: $top},
   backups: {latest: $latest, last_offsite_at: (if $last_offsite == "" then null else $last_offsite end),
             offsite_configured: $offsite, restore_test: $restore, keep_daily: $keep_daily, keep_weekly: $keep_weekly},
   cleanup: $cleanup, growth: $growth}' > "$REPORT.new"
chmod 644 "$REPORT.new"
mv "$REPORT.new" "$REPORT"
say "storage: disk ${pct}% ($level), db $(( db_bytes / 1048576 )) MiB, raw $(( raw / 1048576 )) MiB, docker $(( (img + vol + cache) / 1048576 )) MiB"

# 7. Tell the owner when the level or the anomaly changes (not every run).
anomaly="$(jq -r .anomaly <<< "$growth")"
prev_level="$(cat "$OUT_DIR/level" 2> /dev/null || echo ok)"
if [[ "$level" != "$prev_level" ]]; then
  case "$level" in
    critical) notify "DISCO CRÍTICO: ${pct}% usado ($(( avail / GIB )) GB libres)" ;;
    high) notify "disco alto: ${pct}% usado ($(( avail / GIB )) GB libres)" ;;
    warning) notify "aviso de disco: ${pct}% usado" ;;
    ok) notify "disco de nuevo bajo el 70 % (${pct}%)" ;;
  esac
  echo "$level" > "$OUT_DIR/level"
fi
prev_anomaly="$(cat "$OUT_DIR/anomaly" 2> /dev/null || echo false)"
if [[ "$anomaly" != "$prev_anomaly" ]]; then
  if [[ "$anomaly" == true ]]; then
    notify "crecimiento anómalo del disco: +$(( $(jq -r .last_delta_bytes <<< "$growth") / 1048576 )) MB el $(jq -r .last_day <<< "$growth") (mediana de 14 días: $(( $(jq -r '.median_delta_bytes // 0' <<< "$growth") / 1048576 )) MB)"
  fi
  echo "$anomaly" > "$OUT_DIR/anomaly"
fi
