#!/usr/bin/env bash
# May a deploy skip its own pre-deploy dump because the release chain has just made one AND proved it restores?
# (OPS-005; called by predigolctl deploy, testable on its own.)
#
#   bin/reuse-dump.sh DIR RESTORE_TEST_JSON CURRENT_REVISION HEAD_REVISION MAX_AGE_MIN [NOW_EPOCH]
#
# Exit 0 and the dump's name on stdout when EVERY one of these holds; exit 1 and the first reason otherwise - the caller
# then makes its own dump, as it always did:
#   - the last restore test passed, with no failure and not skipped, and names a dump that is still on the disk with its
#     manifest;
#   - that file is the one that was tested: its size and its sha256 are the manifest's;
#   - no migration is pending: the database's revision, the manifest's and the head of the code about to run are the same
#     one (a release with a migration always gets a fresh dump of its own);
#   - the dump started at most MAX_AGE_MIN minutes ago, and the test is not older than the dump. MAX_AGE_MIN=0 switches
#     the reuse off.
# The pre-deploy dump was never restore-tested; the one reused here is. What a restore from it loses is what was written
# since it started - at most MAX_AGE_MIN minutes - and a deploy without a migration does not write to the data.
set -Eeuo pipefail
dir="$1"; result="$2"; current="$3"; head="$4"; max_min="$5"; now="${6:-$(date -u +%s)}"
no() { echo "$*"; exit 1; }
[[ "$max_min" =~ ^[0-9]+$ ]] || no "the maximum age is not a number of minutes"
(( max_min > 0 )) || no "reuse is switched off (maximum age 0)"
[[ -f "$result" ]] || no "no restore test on record"
jq -e '.passed == true and ((.failures // []) | length == 0) and (has("skipped") | not)' "$result" > /dev/null 2>&1 \
  || no "the last restore test did not pass"
name="$(jq -r '.dump // empty' "$result")"
[[ "$name" =~ ^predigol-([0-9]{8})T([0-9]{6})Z(-[A-Za-z0-9._-]+)?$ ]] || no "the restore test names no dump of this server"
day="${BASH_REMATCH[1]}"; clock="${BASH_REMATCH[2]}"
dump="$dir/$name.dump"; manifest="$dir/$name.json"
[[ -f "$dump" && -f "$manifest" ]] || no "the tested dump ($name) is no longer on the disk"
started="$(date -u -d "${day:0:4}-${day:4:2}-${day:6:2} ${clock:0:2}:${clock:2:2}:${clock:4:2}" +%s)" || no "the dump's name carries no date"
age=$(( now - started ))
(( age >= 0 )) || no "the tested dump is dated in the future"
(( age <= max_min * 60 )) || no "the tested dump is $(( age / 60 )) minutes old (more than $max_min)"
tested="$(date -u -d "$(jq -r '.tested_at // empty' "$result")" +%s 2> /dev/null)" || no "the restore test carries no date"
(( tested >= started )) || no "the restore test is older than the dump it names"
revision="$(jq -r '.alembic_revision // empty' "$manifest")"
[[ -n "$current" && -n "$head" && -n "$revision" ]] || no "a schema revision could not be read"
[[ "$revision" == "$current" ]] || no "the database moved to revision $current since the dump ($revision)"
[[ "$head" == "$current" ]] || no "a migration is pending ($current -> $head): this release gets its own dump"
bytes="$(jq -r '.bytes // empty' "$manifest")"
[[ "$(stat -c %s "$dump")" == "$bytes" ]] || no "the tested dump's size is not its manifest's"
sha="$(jq -r '.sha256 // empty' "$manifest")"
[[ -n "$sha" && "$(sha256sum "$dump" | cut -d' ' -f1)" == "$sha" ]] || no "the tested dump's sha256 is not its manifest's"
echo "$name"
