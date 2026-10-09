#!/usr/bin/env bash
# The load test of the rehearsal (FASE 12), on the server, through its own front door. README "Ensayo".
#
#   predigolctl loadtest [--users 100,200] [--minutes 5] [--think 3:10] [--ramp 60]
#
# 1. Load-test accounts (scripts/loadtest_accounts.py): USER role, @loadtest.predigol.local, one generated
#    password in a 0700 folder under $STATE.
# 2. Every simulated person comes from this one machine, so the API's PER-IP limits (requests and sign-ins) are
#    raised for the test only - the per-USER limit stays as in production - and put back afterwards, whatever
#    happens.
# 3. bin/loadtest.py with the server sampled (CPU, memory, PostgreSQL connections, IOPS); the result is
#    $STATE/loadtest-<stamp>.json.
# 4. The accounts are disabled and their sessions ended; the credentials file is removed.
#
# Before the cut-over only: the cut-over imports into an EMPTY database, so nothing of this reaches production.
set -Eeuo pipefail
# shellcheck source=bin/lib.sh
. "$(dirname "$0")/lib.sh"
exclusive deploy
args=("$@")
users="100,200"
for (( i = 0; i < ${#args[@]}; i++ )); do [[ "${args[i]}" == --users ]] && users="${args[i+1]:-}"; done
count="$(tr ',' '\n' <<< "$users" | sort -n | tail -n 1)"
[[ "$count" =~ ^[0-9]+$ ]] || { echo "usage: predigolctl loadtest [--users 100,200] [--minutes 5] [--think 3:10]" >&2; exit 2; }
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
dir="$STATE/loadtest"
install -d -m 0700 -o 1000 -g 1000 "$dir"

# shellcheck disable=SC2317  # called by the EXIT trap
restore() {
  log "loadtest: putting the API's limits back and disabling the test accounts"
  compose up -d --no-build api > /dev/null 2>&1 || log "loadtest: WARNING - could not restart the API with its normal limits"
  compose --profile ops run --rm --no-deps -T ops python -m scripts.loadtest_accounts disable --confirm \
    || log "loadtest: WARNING - disable the accounts by hand: predigolctl accounts disable --domain loadtest.predigol.local --confirm"
  rm -f "$dir/accounts.txt"
}
trap restore EXIT

log "loadtest: $count accounts"
compose --profile ops run --rm --no-deps -T -v "$dir:/out" ops \
  python -m scripts.loadtest_accounts create --count "$count" --out /out/accounts.txt --confirm
log "loadtest: raising the API's per-IP limits for the test"
PREDIGOL_API_RATE_LIMIT=1000000 PREDIGOL_API_LOGIN_RATE_LIMIT=100000 compose up -d --no-build api > /dev/null
for _ in $(seq 1 60); do
  [[ "$(docker inspect -f '{{.State.Health.Status}}' predigol-api 2> /dev/null)" == healthy ]] && break
  sleep 3
done

cacert=()
if uses_local_ca; then
  cacert=(--cacert "$LOCAL_CA")
fi
rc=0
python3 "$KIT/bin/loadtest.py" --base "https://$PREDIGOL_DOMAIN" --resolve 127.0.0.1 "${cacert[@]}" \
  --accounts "$dir/accounts.txt" --sample-docker --out "$STATE/loadtest-$stamp.json" "$@" || rc=$?
log "loadtest: result in $STATE/loadtest-$stamp.json (exit $rc)"
exit "$rc"
