#!/usr/bin/env bash
# After the server starts (predigol-post-boot.service): wait for the stack to come up on its own, check it,
# and tell the owner what came back. The worker's catch-up, anchored on the run ledger, recovers what fell due
# while the server was down; nothing here re-runs anything.
set -Euo pipefail
# shellcheck source=bin/lib.sh
. "$(dirname "$0")/lib.sh"

log "post-boot: waiting for the stack (up to 10 min)"
for _ in $(seq 1 60); do
  healthy=1
  for svc in postgres api web caddy; do
    st="$(docker inspect -f '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' "predigol-$svc" 2> /dev/null || echo missing)"
    [[ "$st" == "running healthy" || "$st" == "running " ]] || healthy=0
  done
  (( healthy )) && break
  sleep 10
done
"$(dirname "$0")/healthcheck.sh"
rc=$?
status="$(jq -r .status "$STATE/health.json" 2> /dev/null || echo unknown)"
notify "el servidor arrancó ($(uptime -p)); estado: $status$( (( rc )) && echo " - $(jq -r '.problems | join("; ")' "$STATE/health.json")")"
exit 0
