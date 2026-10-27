#!/usr/bin/env bash
# The baseline that the alert config.drift compares with (security plan S3, section 20, alert 32): the sha256 of the files whose change must never be a
# surprise (alerts_checks.sh, config_files: Caddyfile, docker-compose.yml, predigol.env, app.env, sshd's configuration and the systemd units of the kit).
# The monitor tells the owner when one of them differs from it. A PLANNED change moves the baseline when it ends; an unplanned one is what the alert is for.
#
#   bin/config-baseline.sh             take it now (predigolctl config-baseline), and say which files it moves over, by name
#   bin/config-baseline.sh --status    change nothing: when it was taken, how many files it holds, and which differ from it now
#
# Who runs it: `predigolctl deploy` and `predigolctl rollback` when they have finished (the files of the new release differ from the old baseline by
# design, and the post-deploy check must not take them for a surprise); and whoever changes an env file, the Caddyfile or sshd's configuration by hand, as
# the LAST step of that change (the checklists of those changes say so). Until the first one is taken the alert says nothing: there is nothing to compare with.
# Exit: taking it 0 (1 if it could not be written) | --status 0 nothing differs, 1 something does, 2 there is no baseline yet | 2 a wrong argument.
# Names and counts only: never a hash and never a line of any file.
set -Eeuo pipefail
HERE="$(dirname "$(readlink -f "$0")")"
# shellcheck source=bin/lib.sh
. "$HERE/lib.sh"
# shellcheck source=bin/alerts_checks.sh
. "$HERE/alerts_checks.sh"

# check_config_drift reports to alert_set: here its text is the answer, and nothing is sent. No deploy is "running" for this script (the lock a deploy holds is
# its own business: it calls this once its work is done).
# shellcheck disable=SC2034  # read by check_config_drift
DEPLOYING=0
differs=""
alert_set() { differs="${3#*: }"; }
alerts_hold() { :; }

base="$STATE/config.sha256"
count() { wc -l < "$base" | tr -d ' '; }

case "${1:-}" in
  "")
    had=0
    if [[ -r "$base" ]]; then
      had=1
      check_config_drift
    fi
    config_baseline_write || { log "config-baseline: could not write $base"; exit 1; }
    if (( ! had )); then
      log "config-baseline: taken for the first time ($(count) files). From now on the monitor tells you when one of them changes"
    elif [[ -n "$differs" ]]; then
      log "config-baseline: taken ($(count) files). It moved over: $differs"
    else
      log "config-baseline: taken ($(count) files); nothing had changed since the last one"
    fi
    ;;
  --status)
    if [[ ! -r "$base" ]]; then
      log "config-baseline: there is no baseline yet, so the alert config.drift says nothing. Take it with: predigolctl config-baseline"
      exit 2
    fi
    check_config_drift
    when="$(date -u -r "$base" +%FT%TZ)"
    if [[ -n "$differs" ]]; then
      log "config-baseline: taken $when ($(count) files). These differ from it now: $differs"
      exit 1
    fi
    log "config-baseline: taken $when ($(count) files). Nothing differs from it now"
    ;;
  *)
    echo "usage: config-baseline.sh [--status]" >&2
    exit 2
    ;;
esac
