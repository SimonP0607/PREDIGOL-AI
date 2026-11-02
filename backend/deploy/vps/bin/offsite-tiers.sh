#!/usr/bin/env bash
# Which tiers of the off-server copy a dump belongs to, from its name alone (called by backup.sh; testable on its own).
#
#   bin/offsite-tiers.sh predigol-20261025T041950Z[-label]
#
# Prints one tier per line. `daily` always. `weekly` and `monthly` only for a dump the timer took (no label) on a Sunday
# or on the 1st of a month, UTC: so the bucket holds about 14 daily, 8 weekly and 12 monthly copies - not one more per
# deploy (a deploy's own dump, which carries a label, goes to `daily` only). The plan's section 16: the bucket's lock and
# its lifecycle rule are set per tier prefix (dumps/daily/, dumps/weekly/, dumps/monthly/).
set -Eeuo pipefail
name="${1:?usage: $0 predigol-YYYYMMDDTHHMMSSZ[-label]}"
if [[ ! "$name" =~ ^predigol-([0-9]{8})T([0-9]{6})Z(-[A-Za-z0-9_-]+)?$ ]]; then
  echo "not a dump name: $name" >&2
  exit 2
fi
day="${BASH_REMATCH[1]}"
label="${BASH_REMATCH[3]:-}"
echo daily
[[ -z "$label" ]] || exit 0
if [[ "$(date -u -d "$day" +%u)" == 7 ]]; then echo weekly; fi
if [[ "${day:6:2}" == 01 ]]; then echo monthly; fi
exit 0
