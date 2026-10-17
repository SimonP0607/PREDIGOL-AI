#!/usr/bin/env bash
# The owner's daily maintenance (predigol-maint.timer, 05:30 UTC), as the database owner:
#   - odds partitions three months ahead (the worker may not create them: least privilege);
#   - the grants re-applied (idempotent: covers anything a migration added);
#   - retention of operational leftovers ONLY (scripts/db_maintenance.py: old revoked sessions, per-minute
#     request counters) - refused unless a verified backup is younger than 26 h; every removal is recorded;
#   - Cloudflare's ranges refreshed when the site is behind it (PREDIGOL_CLOUDFLARE=1).
#
#   bin/maint.sh            do it
#   bin/maint.sh --dry-run  show what retention would remove
set -Eeuo pipefail
# shellcheck source=bin/lib.sh
. "$(dirname "$0")/lib.sh"
exclusive maint

confirm=--confirm
[[ "${1:-}" == --dry-run ]] && confirm=""
trap 'log "maintenance FAILED"; ping_hc "${HC_PING_MAINT:-}" fail; notify "el mantenimiento diario de la base FALLÓ"' ERR
ping_hc "${HC_PING_MAINT:-}" start
apply_grants
ops python -m scripts.db_maintenance all $confirm --backups /backups | tee "$STATE/maint.log"
if [[ "${PREDIGOL_CLOUDFLARE:-0}" == 1 && -n "$confirm" ]]; then
  "$(dirname "$0")/cloudflare-ips.sh" trust > /dev/null
  [[ -s /etc/predigol/cloudflare-ranges ]] && "$(dirname "$0")/cloudflare-ips.sh" firewall > /dev/null
fi
trap - ERR
log "maintenance done"
ping_hc "${HC_PING_MAINT:-}"
