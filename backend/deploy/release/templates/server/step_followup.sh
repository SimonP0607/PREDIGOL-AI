#!/usr/bin/env bash
# Release __REL__, after the deploy: what the services did since (usage: step_followup.sh <label>, written to followup.<label>.log).
# READ-ONLY and generic; a release with checks of its own replaces this file through --extras.
set -uo pipefail
D=/root/releases/__STAMP__
label=${1:?usage: step_followup.sh <label>}
{
  echo "== follow-up $label at $(date -u +%FT%TZ)"
  echo "-- predigolctl status"
  predigolctl status 2>&1 | head -n 40
  echo "-- containers"
  docker ps --format '{{.Names}} {{.Status}}'
  echo "-- errors and tracebacks in the last 15 minutes of each predigol-* container (a count, never the lines)"
  for c in $(docker ps --format '{{.Names}}' | grep '^predigol-' || true); do
    n=$(docker logs --since 15m "$c" 2>&1 | grep -ciE 'traceback|error' || true)
    echo "$c: ${n:-0}"
  done
  echo "-- disk"
  df -h / | tail -n 1
} > "$D/followup.$label.log" 2>&1