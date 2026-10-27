#!/usr/bin/env bash
# Hourly: the RAW payloads off the server, as they are. `rclone copy --immutable` only ever ADDS files: one already
# copied is never modified or deleted there, whatever happens here - and the bucket's lock on raw/ (indefinite) says
# the same from the other side. Nothing happens unless RAW_RCLONE_REMOTE is set (r2-setup.sh sets it to r2:<bucket>/raw).
#
#   bin/raw-sync.sh [--full]
#
# Two kinds of pass, so that what R2 bills does not grow with the age of the store. rclone lists the destination once per
# directory it copies (one request per 1,000 files, a class A operation) and the store gains ~12,000 files a day:
#   recent  the day directories of TODAY and YESTERDAY (UTC) of every provider: the hourly pass. The store writes
#           <provider>/<yyyy>/<mm>/<dd>/<file> by the UTC day of the fetch (fbi.storage.payload_store), so a file is born in
#           one of the two; yesterday's stays in because a file written at 23:59 is renamed into place after midnight.
#   full    the whole store: --full, and the first pass that finds the last full one older than RAW_SYNC_FULL_HOURS (24).
#           It is the net under the recent pass: a file that turns up anywhere else (an import of an older store,
#           bin/predigolctl ... raw_transfer; a provider with another layout) is found by it, at most a day late.
# The first pass is a full one and takes a while (about 290,000 files): RAW_SYNC_TRANSFERS=16 bin/raw-sync.sh --full.
# A pass still running when the next one is due (the first one) is not a failure: the next one skips itself.
#
# What it copies: $PREDIGOL_DATA/raw/<provider>/<yyyy>/<mm>/<dd>/<endpoint>__<hash>.json.gz  ->  $RAW_RCLONE_REMOTE/<same path>
#   --size-only      the file's name carries its content hash, so size is enough to call it the same - and it spares R2 one
#                    metadata read (a class B operation) per file on every run
#   --min-size 1B    an empty file is a write that never finished, not evidence; copying it would leave a 0-byte object that
#                    the lock then forbids replacing with the real one
#   --exclude *.tmp  the store writes <name>.tmp and renames it (fbi.storage.payload_store): a half-written file is never copied
# A file that exists in both places with a DIFFERENT size is reported by rclone as an error ("immutable file modified"):
# the pass fails, loudly, and the rest of the files are still copied (the log is kept in state/raw-sync.last-failure.log).
# The verdict of the last good pass is state/raw-sync.json (healthcheck.sh reads it): when, which kind, when the last FULL
# one was, how many files it copied and how many empty files the store gained in the last 7 days.
set -Eeuo pipefail
# shellcheck source=bin/lib.sh
. "$(dirname "$0")/lib.sh"

FULL=0
case "${1:-}" in
  "") ;;
  --full) FULL=1 ;;
  *) echo "usage: $0 [--full]" >&2; exit 2 ;;
esac

# Not `exclusive`: a pass that is still running when the next is due is not a failure of the next one.
exec 9> "$STATE/raw-sync.lock"
flock -n 9 || { log "raw-sync: the previous pass is still running - skipped"; exit 0; }

if [[ -z "${RAW_RCLONE_REMOTE:-}" ]]; then
  log "raw-sync: RAW_RCLONE_REMOTE is not set - the RAW store exists only on this server"
  exit 0
fi
RAW="$PREDIGOL_DATA/raw"
sync_log="$STATE/raw-sync.log"
trap 'cp -f "$sync_log" "$STATE/raw-sync.last-failure.log" 2> /dev/null || true; log "raw-sync FAILED (see $STATE/raw-sync.last-failure.log)"; ping_hc "${HC_PING_RAW_SYNC:-}" fail' ERR
ping_hc "${HC_PING_RAW_SYNC:-}" start
now=$(date +%s)
started_at="$(date -u -d "@$now" +%FT%TZ)"

# When was the last FULL pass that succeeded, and when was the last one STARTED (a failed one counts: it must not be retried
# every hour for ever)? A full pass is due when none ever succeeded, or the last attempt is old enough.
full_at="$(jq -r '.full_at // empty' "$STATE/raw-sync.json" 2> /dev/null || true)"
attempt_at="$(cat "$STATE/raw-sync.full-attempt" 2> /dev/null || true)"
if (( ! FULL )); then
  if [[ -z "$full_at" ]]; then
    FULL=1
  else
    last="${attempt_at:-$full_at}"
    last_ts="$(date -d "$last" +%s 2> /dev/null || echo 0)"
    if (( now - last_ts >= ${RAW_SYNC_FULL_HOURS:-24} * 3600 )); then FULL=1; fi
  fi
fi

: > "$sync_log"
failed=0
copy_tree() {  # copy_tree SOURCE DESTINATION: a failure is remembered, the other files still go
  rclone copy --immutable --size-only --min-size 1B --exclude '*.tmp' --transfers "${RAW_SYNC_TRANSFERS:-4}" --checkers 8 \
    --log-level INFO --stats 0 --log-file "$sync_log" "$1" "$2" || failed=1
}
if (( FULL )); then
  mode=full
  printf '%s\n' "$started_at" > "$STATE/raw-sync.full-attempt"
  copy_tree "$RAW" "$RAW_RCLONE_REMOTE"
else
  mode=recent
  today="$(date -u -d "@$now" +%Y/%m/%d)"
  yesterday="$(date -u -d "@$(( now - 86400 ))" +%Y/%m/%d)"
  for provider in "$RAW"/*/; do
    for day in "$today" "$yesterday"; do
      if [[ -d "$provider$day" ]]; then copy_tree "$provider$day" "$RAW_RCLONE_REMOTE/$(basename "$provider")/$day"; fi
    done
  done
fi
(( ! failed )) || { log "raw-sync: some files could not be copied (see $sync_log)"; false; }

copied="$(grep -c ': Copied (new)' "$sync_log" || true)"
# An empty file is a payload whose bytes never reached the disk (the 4 October 2026 incident, fixed in the store since). One
# from long ago is history and is not announced again every hour; one written in the last 7 days is news. Only directories
# touched in that time can hold one, so this costs a handful of directories however large the store is.
empty="$({ find "$RAW" -type d -mtime -8 -exec find {} -maxdepth 1 -type f -size 0 -mtime -7 ! -name '*.tmp' \; 2> /dev/null || true; } | wc -l)"
seconds=$(( $(date +%s) - now ))
[[ "$mode" == full ]] && full_at="$started_at"
jq -n --arg at "$(date -u +%FT%TZ)" --arg mode "$mode" --arg full_at "$full_at" --arg remote "$RAW_RCLONE_REMOTE" \
  --argjson seconds "$seconds" --argjson copied "$copied" --argjson empty "$empty" \
  '{synced_at: $at, mode: $mode, full_at: $full_at, remote: $remote, seconds: $seconds, copied: $copied, empty_recent_files: $empty}' \
  > "$STATE/raw-sync.json.new"
mv "$STATE/raw-sync.json.new" "$STATE/raw-sync.json"
note=""
(( empty > 0 )) && note=", $empty empty file(s) of the last 7 days left out"
log "raw-sync ($mode): $copied new file(s) to $RAW_RCLONE_REMOTE in ${seconds}s$note"
trap - ERR
ping_hc "${HC_PING_RAW_SYNC:-}"
