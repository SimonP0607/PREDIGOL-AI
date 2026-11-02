#!/usr/bin/env bash
# Release __REL__, after the deploy: the read-only follow-ups at 10, 30 and 60 minutes after deploy.finished (step_followup.sh <label>; each one
# writes followup.<label>.log). Started detached by chain.sh, or by hand. A follow-up whose time is already past runs at once. Writes nothing in the
# database and restarts nothing. Its own line for each follow-up goes to followups.log.
set -uo pipefail
D=/root/releases/__STAMP__
cd "$D" || exit 9
exec 8> "$D/followups.lock"
flock -n 8 || { echo "REFUSED: the follow-ups already run"; exit 1; }
FIN=$(cat "$D/deploy.finished" 2> /dev/null) || { echo "REFUSED: no deploy.finished"; exit 1; }
T0=$(date -d "$FIN" +%s) || { echo "REFUSED: deploy.finished is not a date ($FIN)"; exit 1; }
echo "$(date -u +%FT%TZ) follow-ups of the deploy that finished at $FIN" >> "$D/followups.log"
for spec in 10min:600 30min:1800 60min:3600; do
  label=${spec%%:*}
  secs=${spec##*:}
  due=$((T0 + ${FOLLOWUP_SCALE:-1} * secs)) # FOLLOWUP_SCALE=0 only in the rehearsal on the cloud machine
  now=$(date +%s)
  if [ "$now" -lt "$due" ]; then sleep $((due - now)); fi
  "$D/step_followup.sh" "$label" < /dev/null > /dev/null 2>&1
  echo "$(date -u +%FT%TZ) follow-up $label: step_followup.sh status $?" >> "$D/followups.log"
done
echo "$(date -u +%FT%TZ) follow-ups done" >> "$D/followups.log"
