#!/usr/bin/env bash
# Which database dumps the server keeps (called by backup.sh after every dump; testable on its own).
#
#   bin/rotate-dumps.sh DIR KEEP_DAILY KEEP_WEEKLY OFFSITE(0|1) [KEEP_UNVERIFIED]
#
# Kept: the newest KEEP_DAILY dumps (a day of several deploys keeps each one's pre-deploy dump), the newest dump of
# each of the last KEEP_DAILY calendar days, and the newest of each of the last KEEP_WEEKLY ISO weeks. With an
# off-server copy configured (OFFSITE=1), a dump whose copy was never checked is kept too - the local file may be the
# only one - but only while nothing newer has been copied off the server (a newer checked copy supersedes it) and only the
# newest KEEP_UNVERIFIED (6) of them: a bucket that stays unreachable for weeks must not fill the disk with 1.4 GB
# dumps (healthcheck.sh raises the alarm after 26 h). Prints one line per dump removed or kept for that reason.
# Until 13 Oct 2026 the calendar days were not kept: three deploys in one morning rotated out the previous day's dumps
# and that day's own daily one.
set -Eeuo pipefail
dir="$1"; keep_daily="$2"; keep_weekly="$3"; offsite="$4"; keep_unverified="${5:-6}"
mapfile -t dumps < <(find "$dir" -maxdepth 1 -name 'predigol-*.dump' -printf '%f\n' | sort -r)
declare -A keep=() weeks=() days=()
for i in "${!dumps[@]}"; do
  d="${dumps[$i]}"
  (( i < keep_daily )) && keep["$d"]=1
  stamp="${d#predigol-}"; stamp="${stamp:0:8}"
  if [[ -z "${days[$stamp]:-}" && ${#days[@]} -lt $keep_daily ]]; then days["$stamp"]=1; keep["$d"]=1; fi
  week="$(date -u -d "$stamp" +%G-W%V)"
  if [[ -z "${weeks[$week]:-}" && ${#weeks[@]} -lt $keep_weekly ]]; then weeks["$week"]=1; keep["$d"]=1; fi
done
verified_newer=0; unverified_kept=0
for d in "${dumps[@]}"; do  # newest first
  manifest="$dir/${d%.dump}.json"
  checked=0; why=""
  if jq -e '.offsite.verified_at' "$manifest" > /dev/null 2>&1; then checked=1; fi
  newer_is_copied=$verified_newer
  if (( checked )); then verified_newer=1; fi
  [[ -n "${keep[$d]:-}" ]] && continue
  if (( offsite && ! checked )); then
    if (( newer_is_copied )); then why=" (never copied off the server, but a newer dump was)"
    elif (( unverified_kept >= keep_unverified )); then why=" (never copied off the server, beyond the newest $keep_unverified)"
    else unverified_kept=$(( unverified_kept + 1 )); echo "kept $d: its off-server copy was never checked"; continue
    fi
  fi
  rm -f "$dir/$d" "$manifest"; echo "rotated out $d$why"
done
