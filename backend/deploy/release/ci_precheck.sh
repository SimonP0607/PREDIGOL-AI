#!/usr/bin/env bash
# CI side of the precheck (plan CI/CD, C4): runs the kit's read-only precheck through the door and, like chain.sh does, WAITS when the only
# thing it says is "somebody else is working / the server is not quiet yet" (a worker's write transaction, a lock, a deploy running); any
# other NOT OK line fails at once. usage: ci_precheck.sh HOST KIT [TRIES=8] [PAUSE=60]
set -uo pipefail
HOST="${1:?host}" KIT="${2:?kit name}" TRIES="${3:-8}" PAUSE="${4:-60}"
# the same list as WAITABLE in templates/server/chain.sh (a test keeps them equal)
WAITABLE='^NOT OK: (lock [a-z-]+ is HELD|processes of a deploy|detached units of the plans|the server is not quiet|the quiet check could not look)'
for i in $(seq 1 "$TRIES"); do
  out="$(ssh -o BatchMode=yes "$HOST" "precheck $KIT" 2>&1)"; rc=$?
  printf '%s\n' "$out"
  grep -q '^PRECHECK: ' <<< "$out" || { echo "ci_precheck: the precheck did not reach its last line (status $rc)"; exit 1; }
  bad="$(grep '^NOT OK' <<< "$out" || true)"
  if [[ -z "$bad" ]]; then
    [[ "$rc" -eq 0 ]] || { echo "ci_precheck: status $rc with no line NOT OK"; exit 1; }
    echo "ci_precheck: every line OK (try $i)"; exit 0
  fi
  fatal="$(grep -vE "$WAITABLE" <<< "$bad" || true)"
  if [[ -n "$fatal" ]]; then echo "ci_precheck: lines NOT OK that waiting does not fix:"; echo "$fatal"; exit 1; fi
  echo "ci_precheck: try $i only waits for somebody else; again in ${PAUSE}s"
  sleep "$PAUSE"
done
echo "ci_precheck: still not ready after $TRIES tries"; exit 1