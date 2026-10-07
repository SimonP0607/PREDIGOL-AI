#!/usr/bin/env bash
# Hourly: the RAW payloads off the server, as they are. `rclone copy --immutable` only ever ADDS files: one
# already copied is never modified or deleted there, whatever happens here. Nothing happens unless
# RAW_RCLONE_REMOTE is set.
set -Eeuo pipefail
# shellcheck source=bin/lib.sh
. "$(dirname "$0")/lib.sh"
exclusive raw-sync

if [[ -z "${RAW_RCLONE_REMOTE:-}" ]]; then
  log "raw-sync: RAW_RCLONE_REMOTE is not set - the RAW store exists only on this server"
  exit 0
fi
trap 'log "raw-sync FAILED"; ping_hc "${HC_PING_RAW_SYNC:-}" fail' ERR
ping_hc "${HC_PING_RAW_SYNC:-}" start
rclone copy --immutable --transfers 4 --checkers 8 --log-level NOTICE "$PREDIGOL_DATA/raw" "$RAW_RCLONE_REMOTE/raw"
log "raw-sync: copied to $RAW_RCLONE_REMOTE/raw"
ping_hc "${HC_PING_RAW_SYNC:-}"
