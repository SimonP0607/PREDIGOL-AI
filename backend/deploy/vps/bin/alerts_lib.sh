#!/usr/bin/env bash
# alerts_lib.sh - security plan S3 (sections 20 and 21): ONE message per change of state, an hourly reminder for a SEV1 that stays open,
# and the incident register. Sourced by healthcheck.sh and security-alerts.sh AFTER lib.sh (needs: STATE, log, jq, and notify_ok or notify).
#
#   alerts_begin [owner]                           # forgets what this run saw; reads nothing yet. owner: healthcheck.sh uses the default (main), security-alerts.sh 'security'
#   alert_set web.health SEV1 "https://dominio/health no responde"     # this run saw it failing (as many calls as failures)
#   alerts_hold ingest.runs db.connections                             # this run COULD NOT evaluate these (the database did not answer): if they are open they stay open, untouched
#   alerts_end                                     # compares with state/alerts.json: opens, reminds, closes; writes state + register
#
# A key is a stable dotted name "service.check" (the service is what comes before the first dot). The text may hold service names, counts and
# ids; NEVER an email, an address or a secret (the callers build it from fixed templates). Severity: SEV1 service down, data at risk or suspected
# intrusion; SEV2 degradation or a security signal; SEV3 no impact.
#
# State (STATE = $PREDIGOL_DATA/state):
#   alerts.json     {"<key>": {"sev","text","since","incident","last_sent"[,"pinned"]}}   what is open now; last_sent = epoch of the last message that
#                                                                               REACHED the channel (0 = never: the open message is retried);
#                                                                               pinned = the owner chose the severity (bin/incident.sh): the check no longer changes it
#   incidents.jsonl one line per event, append-only: {"at","event":"open|update|close","incident","key","service","severity","text"[, "minutes"]}; the owner's pen
#                   (bin/incident.sh) adds "actor":"owner" and the events "note" ("field","value"). A line is never edited or removed.
#   incident.seq    "<year> <n>" the last id handed out (INC-<year>-<nnn>)
# The register file is the truth (it works with the database down); bin/incident-dump.sh mirrors it into the table audit.incident_events, idempotently by the
# sha256 of each line.
#
# Environment: ALERT_REMIND_SECS (3600), ALERTS_DRY_RUN=1 (prints what it would send and writes nothing), ALERTS_NOW (epoch, tests only).
# shellcheck disable=SC2034  # the arrays are read by alerts_end

declare -A _A_SEV=() _A_TEXT=() _A_HOLD=()
_A_OWNER=main

alerts_begin() { _A_SEV=(); _A_TEXT=(); _A_HOLD=(); _A_OWNER=${1:-main}; }   # the owner is the checker (main = healthcheck.sh, security = security-alerts.sh): it only ever closes ITS OWN alerts

# A check that could not run is not a check that passed: without this, a database that does not answer closes ("recuperado") every alert that depends on it and
# the next pass opens it again as a new incident. A held key that this run also saw failing is treated as failing (alert_set wins).
alerts_hold() { local k; for k in "$@"; do _A_HOLD[$k]=1; done; }

_sev_rank() { case "$1" in SEV1) echo 1 ;; SEV2) echo 2 ;; SEV3) echo 3 ;; *) echo 9 ;; esac; }

alert_set() {
  local key=$1 sev=$2 text=$3
  [[ "$key" =~ ^[a-z0-9_]+(\.[a-z0-9_-]+)+$ ]] || { log "alerts: refused key '$key' (service.check, lower case)"; return 0; }
  [[ "$sev" =~ ^SEV[123]$ ]] || { log "alerts: refused severity '$sev' for $key"; return 0; }
  # the same key twice in a run: the more severe one wins, the first text stays
  if [[ -n "${_A_SEV[$key]:-}" ]] && (( $(_sev_rank "${_A_SEV[$key]}") <= $(_sev_rank "$sev") )); then return 0; fi
  _A_SEV[$key]=$sev
  _A_TEXT[$key]=${text//$'\n'/ }
}

# One message to the channel. 0 = it reached Telegram (or ALERTS_DRY_RUN printed it), 1 = it did not.
_alert_send() {
  if [[ "${ALERTS_DRY_RUN:-0}" == 1 ]]; then echo "WOULD SEND: $*"; return 0; fi
  if declare -F notify_ok > /dev/null; then notify_ok "$@"; else notify "$@"; fi
}

_incident_next() {  # prints INC-<year>-<nnn>; the sequence restarts every year
  local year seq_year seq_n
  year=$(date -u -d "@${_NOW}" +%Y)
  read -r seq_year seq_n 2> /dev/null < "$STATE/incident.seq" || { seq_year=$year; seq_n=0; }
  [[ "$seq_year" == "$year" ]] || seq_n=0
  seq_n=$(( 10#${seq_n:-0} + 1 ))
  if [[ "${ALERTS_DRY_RUN:-0}" != 1 ]]; then printf '%s %s\n' "$year" "$seq_n" > "$STATE/incident.seq.tmp" && mv -f "$STATE/incident.seq.tmp" "$STATE/incident.seq"; fi
  printf 'INC-%s-%03d\n' "$year" "$seq_n"
}

# One line to the register. If the file does not end in a newline (the machine lost power half way through the previous line) the newline goes first, so the
# torn fragment stays a line of its own instead of swallowing this one (the readers skip a line that is not JSON; the mirror counts it as refused).
_incident_append() {  # <json line>
  local f="$STATE/incidents.jsonl"
  if [[ -s "$f" && -n "$(tail -c 1 "$f" 2> /dev/null)" ]]; then printf '\n' >> "$f"; fi
  printf '%s\n' "$1" >> "$f"
}

# The valid lines of the register, compact, one per line: a line that is not a JSON object (a torn one, a hand edit) is skipped, never fatal. Readers use this:
#   incident_lines | jq -rs '...'
incident_lines() {
  [[ -r "$STATE/incidents.jsonl" ]] || return 0
  jq -cR 'fromjson? | select(type == "object")' "$STATE/incidents.jsonl" 2> /dev/null || true
}

_incident_event() {  # event incident key severity text [minutes]
  [[ "${ALERTS_DRY_RUN:-0}" == 1 ]] && return 0
  local event=$1 inc=$2 key=$3 sev=$4 text=$5 minutes=${6:-} line
  line="$(jq -cn --arg at "$(date -u -d "@${_NOW}" +%FT%TZ)" --arg event "$event" --arg inc "$inc" --arg key "$key" --arg svc "${key%%.*}" \
    --arg sev "$sev" --arg text "$text" --arg minutes "$minutes" \
    '{at: $at, event: $event, incident: $inc, key: $key, service: $svc, severity: $sev, text: $text} + (if $minutes == "" then {} else {minutes: ($minutes | tonumber)} end)')"
  _incident_append "$line"
}

alerts_end() {
  _NOW=${ALERTS_NOW:-$(date +%s)}
  local remind=${ALERT_REMIND_SECS:-3600} file="$STATE/alerts.json" prev new key sev text since inc last hhmm minutes pinned
  local owner=${_A_OWNER:-main} lockfd=""
  if [[ "${ALERTS_DRY_RUN:-0}" != 1 ]]; then   # two checkers share alerts.json: one writes at a time
    exec {lockfd}> "$STATE/alerts.lock"
    flock -w 30 "$lockfd" || { log "alerts: could not take $STATE/alerts.lock"; exec {lockfd}>&-; return 0; }
  fi
  prev='{}'
  if [[ -r "$file" ]] && jq -e 'type == "object"' "$file" > /dev/null 2>&1; then prev=$(< "$file"); fi
  new=$(jq -c --arg o "$owner" 'with_entries(select((.value.owner // "main") != $o))' <<< "$prev")   # what other checkers keep open stays as it is
  # 0. what this run could not evaluate stays exactly as it was
  for key in "${!_A_HOLD[@]}"; do
    [[ -z "${_A_SEV[$key]:-}" ]] || continue
    if jq -e --arg k "$key" --arg o "$owner" 'has($k) and ((.[$k].owner // "main") == $o)' <<< "$prev" > /dev/null; then
      new=$(jq -c --arg k "$key" --argjson p "$prev" '. + {($k): $p[$k]}' <<< "$new")
    fi
  done
  # 1. what this run saw failing: open, or keep (and remind a SEV1 that has been open for a while)
  for key in "${!_A_SEV[@]}"; do
    sev=${_A_SEV[$key]}; text=${_A_TEXT[$key]}; pinned=false
    if jq -e --arg k "$key" 'has($k)' <<< "$prev" > /dev/null; then
      since=$(jq -r --arg k "$key" '.[$k].since' <<< "$prev"); inc=$(jq -r --arg k "$key" '.[$k].incident' <<< "$prev")
      last=$(jq -r --arg k "$key" '.[$k].last_sent // 0' <<< "$prev")
      local prev_sev; prev_sev=$(jq -r --arg k "$key" '.[$k].sev' <<< "$prev")
      pinned=$(jq -r --arg k "$key" '.[$k].pinned // false' <<< "$prev")
      [[ "$pinned" != true ]] || sev=$prev_sev   # the owner chose this severity (bin/incident.sh severity): it stays until the incident closes
      hhmm=$(date -u -d "$since" +%H:%M 2> /dev/null || echo "?")
      if [[ "$prev_sev" != "$sev" ]]; then
        _incident_event update "$inc" "$key" "$sev" "$text"
        if _alert_send "[$sev] $key: $text (antes $prev_sev; $inc)"; then last=$_NOW; fi
      elif (( last == 0 )); then  # the open message never reached the channel: try again
        if _alert_send "[$sev] $key: $text ($inc)"; then last=$_NOW; fi
      elif [[ "$sev" == SEV1 ]] && (( _NOW - last >= remind )); then
        if _alert_send "[SEV1 sigue abierto desde las $hhmm UTC] $key: $text ($inc)"; then last=$_NOW; fi
      fi
    else
      since=$(date -u -d "@${_NOW}" +%FT%TZ); inc=$(_incident_next); last=0
      _incident_event open "$inc" "$key" "$sev" "$text"
      if _alert_send "[$sev] $key: $text ($inc)"; then last=$_NOW; fi
    fi
    new=$(jq -c --arg k "$key" --arg sev "$sev" --arg text "$text" --arg since "$since" --arg inc "$inc" --argjson last "$last" --arg owner "$owner" --arg pinned "$pinned" \
      '. + {($k): ({sev: $sev, text: $text, since: $since, incident: $inc, last_sent: $last, owner: $owner} + (if $pinned == "true" then {pinned: true} else {} end))}' <<< "$new")
  done
  # 2. what was open and is not failing any more: close
  while IFS= read -r key; do
    [[ -n "$key" && -z "${_A_SEV[$key]:-}" && -z "${_A_HOLD[$key]:-}" ]] || continue
    sev=$(jq -r --arg k "$key" '.[$k].sev' <<< "$prev"); inc=$(jq -r --arg k "$key" '.[$k].incident' <<< "$prev")
    since=$(jq -r --arg k "$key" '.[$k].since' <<< "$prev")
    minutes=$(( (_NOW - $(date -u -d "$since" +%s 2> /dev/null || echo "$_NOW")) / 60 ))
    _incident_event close "$inc" "$key" "$sev" "recuperado" "$minutes"
    _alert_send "[recuperado] $key tras $minutes min ($inc)" || true
  done < <(jq -r --arg o "$owner" 'to_entries[] | select((.value.owner // "main") == $o) | .key' <<< "$prev")
  if [[ "${ALERTS_DRY_RUN:-0}" != 1 ]]; then
    printf '%s\n' "$new" > "$file.tmp" && mv -f "$file.tmp" "$file"
  fi
  [[ -z "$lockfd" ]] || exec {lockfd}>&-
  return 0
}
