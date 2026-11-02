#!/usr/bin/env bash
# The bucket locks, PROVEN instead of trusted. For each tier a small canary is uploaded under the tier's prefix, and then
# the check tries what an intruder with this server's token would try: to DELETE it and to OVERWRITE it. Both must be
# refused, and the canary must come out byte for byte as it went in. A lock that is not there (a rule never created, one
# removed by mistake, a prefix typed wrong) is found by this check, not by the day the backups are needed.
#
#   bin/r2-lock-check.sh [--tier daily|weekly|monthly|raw|all] [--remote r2:<bucket>]
#
#   daily | weekly | monthly   dumps/<tier>/_lockcheck-<UTC time>-<tier>.txt
#   raw                        raw/_lockcheck/_lockcheck-<UTC time>-raw.txt     (RAW_RCLONE_REMOTE, else <remote>/raw)
# A canary stays in the bucket until its lock expires (the lifecycle rule then removes the dumps/ ones; the raw/ ones stay,
# a few bytes each): that is what "locked" means. Run by backup.sh on the Sunday copy, by r2-setup.sh before it changes
# anything, and by hand. The verdict is state/lock-check.json (healthcheck.sh reads it).
# Exit 0 every tier locked, 1 at least one NOT locked (or not provably locked), 2 usage or not configured.
set -Eeuo pipefail
# shellcheck source=bin/lib.sh
. "$(dirname "$0")/lib.sh"

usage() { echo "usage: $0 [--tier daily|weekly|monthly|raw|all] [--remote r2:<bucket>]" >&2; exit 2; }
TIER=all
REMOTE_ARG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tier) TIER="${2:-}"; shift 2 ;;
    --remote) REMOTE_ARG="${2:-}"; shift 2 ;;
    *) usage ;;
  esac
done
case "$TIER" in
  all) tiers=(daily weekly monthly raw) ;;
  daily | weekly | monthly | raw) tiers=("$TIER") ;;
  *) usage ;;
esac
# --remote wins over predigol.env: r2-setup.sh checks the bucket BEFORE it writes the remote into that file.
[[ -z "$REMOTE_ARG" ]] || { BACKUP_RCLONE_REMOTE="$REMOTE_ARG"; RAW_RCLONE_REMOTE="$REMOTE_ARG/raw"; }
if [[ -z "${BACKUP_RCLONE_REMOTE:-}" ]]; then
  log "r2-lock-check: BACKUP_RCLONE_REMOTE is not set - nothing to check"
  exit 2
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
# What a refused delete or overwrite looks like in rclone's words. R2's exact text is not known in advance; an error that
# matches none of these but leaves the canary in place is reported as "inconclusive", never as locked.
REFUSAL="${LOCKCHECK_REFUSAL_PATTERN:-AccessDenied|Forbidden|\\b403\\b|[Ll]ocked|[Rr]etention|[Ii]mmutable|[Nn]ot allowed|[Dd]enied|\\b409\\b|[Cc]onflict}"
RC=(rclone --retries 1 --low-level-retries 1 --contimeout 20s --timeout 60s)
results=()
overall=0

same_as_original() { "${RC[@]}" cat "$1" 2> /dev/null | cmp -s - "$TMP/one"; }
# Does rclone's error read like a refusal? The canary's own name (a time stamp: ...T140359Z...) is taken out first, so that
# its digits can never pass for an HTTP status.
refused() { sed -E 's/_lockcheck-[0-9]{8}T[0-9]{6}Z-[a-z]+\.txt//g' "$1" | grep -Eq "$REFUSAL"; }

check_tier() {
  local tier="$1" base canary msg="" write=failed del=skipped over=skipped same=false passed=false
  case "$tier" in
    raw) base="${RAW_RCLONE_REMOTE:-$BACKUP_RCLONE_REMOTE/raw}/_lockcheck" ;;
    *) base="$BACKUP_RCLONE_REMOTE/dumps/$tier" ;;
  esac
  canary="$base/_lockcheck-$STAMP-$tier.txt"
  printf 'lock check %s (%s)\n' "$STAMP" "$tier" > "$TMP/one"
  printf 'lock check %s (%s) OVERWRITTEN - this must never be there\n' "$STAMP" "$tier" > "$TMP/two"

  if "${RC[@]}" copyto "$TMP/one" "$canary" 2> "$TMP/err"; then
    write=ok
    # A delete must be REFUSED, and the canary must still be there afterwards.
    if "${RC[@]}" deletefile "$canary" 2> "$TMP/err"; then
      del=succeeded
    else
      msg="$(tr '\n' ' ' < "$TMP/err" | cut -c1-240)"
      if [[ -z "$("${RC[@]}" lsf "$canary" 2> /dev/null)" ]]; then
        del=succeeded   # the command reported an error, but the object is gone
      elif refused "$TMP/err"; then
        del=refused
      else
        del=inconclusive
      fi
    fi
    # An overwrite (a different size, so that rclone really sends it) must be refused as well.
    if [[ "$del" == refused ]]; then
      if "${RC[@]}" copyto "$TMP/two" "$canary" 2> "$TMP/err"; then
        over=succeeded
      else
        [[ -n "$msg" ]] || msg="$(tr '\n' ' ' < "$TMP/err" | cut -c1-240)"
        if refused "$TMP/err"; then over=refused; else over=inconclusive; fi
      fi
    fi
    if same_as_original "$canary"; then same=true; fi
    [[ "$del" == refused && "$over" == refused && "$same" == true ]] && passed=true
  else
    msg="$(tr '\n' ' ' < "$TMP/err" | cut -c1-240)"
  fi

  if [[ "$passed" == true ]]; then
    log "r2-lock-check PASS $tier: write ok, delete refused, overwrite refused, content unchanged"
  else
    overall=1
    log "r2-lock-check FAIL $tier: write=$write delete=$del overwrite=$over unchanged=$same${msg:+ ($msg)}"
    case "$del" in
      succeeded) log "r2-lock-check: $tier is NOT LOCKED - anyone with this server's token can delete what is stored there" ;;
      inconclusive) log "r2-lock-check: $tier - the delete failed with an error that does not look like a lock refusal; read it above" ;;
    esac
  fi
  results+=("$(jq -n --arg tier "$tier" --arg canary "$canary" --arg write "$write" --arg del "$del" --arg over "$over" \
    --arg msg "$msg" --argjson same "$same" --argjson passed "$passed" \
    '{tier: $tier, canary: $canary, write: $write, delete: $del, overwrite: $over, unchanged: $same, passed: $passed, message: $msg}')")
}

for t in "${tiers[@]}"; do check_tier "$t"; done

json="$(printf '%s\n' "${results[@]}" | jq -s --arg at "$(date -u +%FT%TZ)" '{checked_at: $at, passed: (all(.[]; .passed)), tiers: .}')"
printf '%s\n' "$json" > "$STATE/lock-check.json.new"
mv "$STATE/lock-check.json.new" "$STATE/lock-check.json"
exit "$overall"
