#!/usr/bin/env bash
# What an AUTOMATIC deploy (plan CI/CD, CI-007) would release, and whether it may release anything at all.
#
#   backend/deploy/release/ci_auto_plan.sh HOST COMMIT        (HOST = predigol-gh in CI; "local" reads $PREDIGOL_APP_DIR, for the tests)
#
# For each part (backend, web) it fetches the commit production runs (read-only, through the door) and checks two things:
#   1. LINEAGE   the release commit says "(monorepo SHA12)": that SHA must be a commit of THIS repository and an ancestor of COMMIT. If it is
#                not, somebody released from outside GitHub (or main lost what production runs) and an automatic deploy would put production
#                back to what main holds: it refuses (exit 1) until that work is merged into main.
#   2. CHANGE    the part's folder at COMMIT differs from the tree production runs.
# Last line of stdout: PARTS=backend,web | PARTS=backend | PARTS=web | PARTS=none. Everything else goes to stderr.
set -Eeuo pipefail
HOST="${1:?host}" HEAD_REF="${2:?commit}"
APP="${PREDIGOL_APP_DIR:-/opt/predigol}"
head="$(git rev-parse --verify "$HEAD_REF^{commit}")"
changed=()
for part in backend web; do
  if [[ "$HOST" == "local" ]]; then git fetch -q "$APP/$part" HEAD; else git fetch -q "$HOST:$APP/$part" HEAD; fi
  prod="$(git rev-parse FETCH_HEAD)"
  subject="$(git log -1 --format=%s "$prod")"
  if [[ ! "$subject" =~ \(monorepo\ ([0-9a-f]{12})\)$ ]]; then
    echo "NOT OK: production's $part ($subject) was not cut by the release kit: cannot tell what it holds" >&2; exit 1
  fi
  src="${BASH_REMATCH[1]}"
  full="$(git rev-parse --verify -q "$src^{commit}" 2> /dev/null)" || {
    echo "NOT OK: production's $part was released from $src, which is not in this repository: merge that work into main before an automatic deploy" >&2; exit 1; }
  git merge-base --is-ancestor "$full" "$head" || {
    echo "NOT OK: production's $part was released from $src, which main (${head:0:12}) does not contain: merge that work into main first" >&2; exit 1; }
  if [[ "$(git rev-parse "$head:$part")" != "$(git rev-parse "$prod^{tree}")" ]]; then changed+=("$part"); fi
  echo "ok: $part runs ${prod:0:12} (from $src, contained in main); changed: $([[ " ${changed[*]:-} " == *" $part "* ]] && echo yes || echo no)" >&2
done
if [[ ${#changed[@]} -eq 0 ]]; then echo "PARTS=none"; else (IFS=,; echo "PARTS=${changed[*]}"); fi
