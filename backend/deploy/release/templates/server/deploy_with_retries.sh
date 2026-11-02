#!/usr/bin/env bash
# Runs the packaged step_deploy.sh and, ONLY when it refuses because the server is not quiet (its own words and status 2: nothing has moved), waits
# and tries again, at most TRIES times. Any other outcome ends the wrapper with the status of step_deploy.sh. (F14 template.)
D=${D:-/root/releases/__STAMP__}
export QUIET_GAP=${QUIET_GAP:-60}
TRIES=${TRIES:-8}
WAIT=${WAIT:-45}
echo "wrapper start $(date -u +%FT%TZ): at most $TRIES attempts, quiet gap ${QUIET_GAP} s, wait ${WAIT} s between attempts"
for i in $(seq 1 "$TRIES"); do
  out=$(mktemp)
  echo "== attempt $i of $TRIES, $(date -u +%FT%TZ)"
  "$D/step_deploy.sh" < /dev/null 2>&1 | tee "$out"
  rc=${PIPESTATUS[0]}
  if [ "$rc" -eq 2 ] && grep -q "^not starting: the server is not quiet" "$out"; then
    rm -f "$out"
    echo "== attempt $i: the server was not quiet and nothing moved; waiting ${WAIT} s"
    sleep "$WAIT"
    continue
  fi
  rm -f "$out"
  echo "== wrapper end $(date -u +%FT%TZ): step_deploy.sh status $rc"
  exit "$rc"
done
echo "== wrapper end $(date -u +%FT%TZ): still not quiet after $TRIES attempts; nothing moved"
exit 2
