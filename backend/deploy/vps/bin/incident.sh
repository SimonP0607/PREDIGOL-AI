#!/usr/bin/env bash
# bin/incident.sh - the owner's pen for the incident register (security plan S3, section 21; guide annex E). The checks write the incidents they open and close
# by themselves (state/incidents.jsonl); this is for what only a person knows - cause, impact, how many users, personal data, how it was fixed, how it is prevented
# - and for the incident the server could not see (the outside monitor warned, the machine was off). Every line goes to the same file, so everything here works with
# the database down; bin/incident-dump.sh mirrors the file into the table audit.incident_events (this script asks it to, once, after writing).
#
#   incident.sh list [--all]                               what is open now; --all adds the last ten closed
#   incident.sh show INC-2026-014                          the whole history of one incident, notes included
#   incident.sh note INC-2026-014 cause "texto"            fields: cause evidence impact affected_users personal_data detection repair prevention
#                                                           affected_users: a NUMBER, never names. personal_data: starts with si or no ("si: correos de 12 titulares")
#   incident.sh severity INC-2026-014 SEV1 ["por qué"]     the owner changes the severity
#   incident.sh open <service> <SEV1|SEV2|SEV3> "síntoma" [--at 2026-10-26T15:02Z]    a manual incident (no check opened it)
#   incident.sh close INC-2026-014 ["texto"] [--at ...]    closes a MANUAL incident; an automatic one is closed by the check when the problem is gone
#
# The text is a symptom, a count, a service name: NEVER an e-mail address, a password, a token or a key (the register is copied to the database and to the backups).
# What looks like one is refused. A person's name does not belong either: use counts and ids.
#
# Environment: ALERTS_DRY_RUN=1 (prints the line and the message, writes and sends nothing), INCIDENT_NO_DUMP=1 (does not ask the mirror to run), INCIDENT_NOW (epoch, tests only).
set -Euo pipefail
HERE="$(dirname "$0")"
# shellcheck source=bin/lib.sh
. "$HERE/lib.sh"
# shellcheck source=bin/alerts_lib.sh
. "$HERE/alerts_lib.sh"

FILE="$STATE/incidents.jsonl"
NOW=${INCIDENT_NOW:-$(date +%s)}
FIELDS="cause evidence impact affected_users personal_data detection repair prevention"
SERVICES="web api worker base copias disco proveedor ia login dns seguridad"

die() { echo "incident.sh: $*" >&2; exit 2; }
usage() { sed -n '2,/^set -Euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; }

iso() { date -u -d "@$1" +%FT%TZ; }

# --at: a UTC time like 2026-10-26T15:02Z (seconds optional); not in the future. The result is left in AT_EPOCH: this is NOT called inside $( ), because a
# die there would only end the subshell and the script would go on with an empty time (that wrote an incident numbered "INC--001" in the first test run).
AT_EPOCH=""
parse_at() {
  local s=$1 e
  [[ "$s" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}(:[0-9]{2})?Z$ ]] || die "la hora de --at va así: 2026-10-26T15:02Z (UTC)"
  e="$(date -u -d "$s" +%s 2> /dev/null)" || die "la hora de --at no existe: $s"
  [[ "$e" =~ ^[0-9]+$ ]] || die "la hora de --at no existe: $s"
  (( e <= NOW + 300 )) || die "la hora de --at está en el futuro: $s"
  AT_EPOCH=$e
}

# the text of an event or a note: one line, up to 1500 characters, nothing that looks like an address or a secret
check_text() {
  local t=$1
  [[ -n "${t//[[:space:]]/}" ]] || die "el texto está vacío"
  (( ${#t} <= 1500 )) || die "el texto pasa de 1500 caracteres (${#t}): resúmelo y deja el detalle en tu fichero del portátil"
  [[ "$t" != *$'\n'* && "$t" != *$'\r'* ]] || die "el texto debe ir en una sola línea"
  if [[ "$t" =~ [A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,} ]]; then die "el texto parece llevar una dirección de correo; el registro no las guarda (usa un recuento o un id)"; fi
  if [[ "$t" =~ [A-Za-z0-9_-]{32,} ]]; then die "el texto lleva una cadena larga de letras y números que parece una clave o un token; el registro no los guarda (si es un nombre largo de fichero, acórtalo)"; fi
  if [[ "$t" =~ ([Pp]assword|[Cc]ontrase(ñ|n)a|[Ss]ecret|[Tt]oken|[Cc]lave)[[:space:]]*[:=] ]]; then die "el texto parece decir el valor de una contraseña, clave o token (palabra seguida de : o =); el registro no los guarda. Di qué se hizo, no el valor"; fi
  if [[ "$t" =~ [a-z]+://[^[:space:]/@]+:[^[:space:]/@]+@ ]]; then die "el texto lleva una dirección con usuario y contraseña; el registro no las guarda"; fi
}

event_of() {  # <INC> <event>: the newest line of that kind, as JSON ('' if none)
  incident_lines | jq -c --arg i "$1" --arg e "$2" 'select(.incident == $i and .event == $e)' 2> /dev/null | tail -n 1
}
require_incident() {  # <INC>: leaves OPEN_JSON
  [[ "$1" =~ ^INC-[0-9]{4}-[0-9]{3,}$ ]] || die "el número va así: INC-2026-014"
  OPEN_JSON="$(event_of "$1" open)"
  [[ -n "$OPEN_JSON" ]] || die "$1 no está en el registro de este servidor (usa «list --all» para ver los números)"
}
current_severity() { incident_lines | jq -r --arg i "$1" 'select(.incident == $i and (.event == "open" or .event == "update")) | .severity' | tail -n 1; }

# one line to the register file (under the lock the checks use for alerts.json and incident.seq)
LOCKFD=""
take_lock() { exec {LOCKFD}> "$STATE/alerts.lock"; flock -w 30 "$LOCKFD" || die "no pude tomar $STATE/alerts.lock (otra comprobación lo tiene; repite en un minuto)"; }
drop_lock() { [[ -z "$LOCKFD" ]] || exec {LOCKFD}>&-; LOCKFD=""; }

write_event() {  # <json line>
  if [[ "${ALERTS_DRY_RUN:-0}" == 1 ]]; then echo "WOULD WRITE: $1"; return 0; fi
  _incident_append "$1"
}
send() { _alert_send "$1" || log "incident: el mensaje no llegó al canal (queda en el registro)"; }
mirror() {
  [[ "${INCIDENT_NO_DUMP:-0}" == 1 || "${ALERTS_DRY_RUN:-0}" == 1 ]] && return 0
  timeout 90 "$HERE/incident-dump.sh" > /dev/null 2>&1 || true
  echo "Pedí la copia a la base de datos (si no respondía, el fichero lo conserva y el temporizador lo copia después)."
}

cmd_list() {
  local all=0; [[ "${1:-}" == "--all" ]] && all=1
  [[ -s "$FILE" ]] || { echo "El registro está vacío: no ha habido incidentes en este servidor."; return 0; }
  incident_lines | jq -rs --argjson all "$all" '
    reduce .[] as $e ({};
      if $e.event == "open" then .[$e.incident] = {inc: $e.incident, key: $e.key, sev: $e.severity, opened: $e.at, closed: null, text: $e.text, by: ($e.actor // "system")}
      elif $e.event == "update" and has($e.incident) then .[$e.incident].sev = $e.severity
      elif $e.event == "close" and has($e.incident) then .[$e.incident].closed = $e.at
      else . end)
    | [.[]] | sort_by(.opened) | reverse
    | (map(select(.closed == null)) + (if $all == 1 then (map(select(.closed != null)) | .[0:10]) else [] end))
    | if length == 0 then "Nada abierto." else .[] | "\(.inc)  \(.sev)  \(if .closed == null then "ABIERTO" else "cerrado" end)  desde \(.opened)\(if .closed != null then " hasta \(.closed)" else "" end)  \(.key)  \(.text)" end'
}

cmd_show() {
  local inc=${1:-}; require_incident "$inc"
  incident_lines | jq -r --arg i "$inc" 'select(.incident == $i) | "\(.at)  \(.event | (. + "        ")[0:6])  \(.actor // "system")  \(.severity // "-")  \(.text // .value // "")"'
  echo "---"
  echo "Notas vigentes (la última de cada campo):"
  incident_lines | jq -rs --arg i "$inc" '[.[] | select(.incident == $i and .event == "note")] | group_by(.field) | map(max_by(.at)) | .[] | "  \(.field): \(.value)"'
}

cmd_note() {
  local inc=${1:-} field=${2:-} value=${3:-}
  [[ $# -eq 3 ]] || die "uso: incident.sh note INC-2026-014 <campo> \"texto\"  (campos: $FIELDS)"
  require_incident "$inc"
  [[ " $FIELDS " == *" $field "* ]] || die "el campo «$field» no existe; los hay: $FIELDS"
  check_text "$value"
  case "$field" in
    affected_users) [[ "$value" =~ ^[0-9]{1,9}$ ]] || die "affected_users es un número (cuántos usuarios), nunca nombres" ;;
    personal_data) [[ "$value" =~ ^(si|no)([[:space:]:].*)?$ ]] || die "personal_data empieza por «si» o «no» (por ejemplo: si: correos de 12 titulares). Un «si» activa el protocolo de datos personales (guía 4, plazos legales)" ;;
  esac
  local key service sev line
  key="$(jq -r .key <<< "$OPEN_JSON")"; service="$(jq -r .service <<< "$OPEN_JSON")"; sev="$(current_severity "$inc")"
  line="$(jq -cn --arg at "$(iso "$NOW")" --arg i "$inc" --arg k "$key" --arg s "$service" --arg sev "$sev" --arg f "$field" --arg v "$value" \
    '{at: $at, event: "note", incident: $i, key: $k, service: $s, severity: $sev, text: ($f + ": " + $v), field: $f, value: $v, actor: "owner"}')"
  take_lock; write_event "$line"; drop_lock
  echo "Anotado en $inc: $field."
  if [[ "$field" == personal_data && "$value" =~ ^si ]]; then
    echo "OJO: marcaste datos personales. Sigue la guía 4 (ficha de datos personales y plazos): el reloj de la SIC cuenta desde que lo detectaste. Llama a tu abogado hoy."
    send "[datos personales] $inc marcado con datos personales por el dueño. Plazos legales en marcha (guía 4)."
  fi
  mirror
}

cmd_severity() {
  local inc=${1:-} sev=${2:-} why=${3:-"cambio de severidad por el dueño"}
  [[ $# -ge 2 ]] || die "uso: incident.sh severity INC-2026-014 SEV1 [\"por qué\"]"
  [[ "$sev" =~ ^SEV[123]$ ]] || die "la severidad es SEV1, SEV2 o SEV3"
  require_incident "$inc"
  [[ -z "$(event_of "$inc" close)" ]] || die "$inc ya está cerrado"
  check_text "$why"
  local key service before line
  key="$(jq -r .key <<< "$OPEN_JSON")"; service="$(jq -r .service <<< "$OPEN_JSON")"; before="$(current_severity "$inc")"
  [[ "$before" != "$sev" ]] || die "$inc ya es $sev"
  line="$(jq -cn --arg at "$(iso "$NOW")" --arg i "$inc" --arg k "$key" --arg s "$service" --arg sev "$sev" --arg t "$why (antes $before)" \
    '{at: $at, event: "update", incident: $i, key: $k, service: $s, severity: $sev, text: $t, actor: "owner"}')"
  take_lock; write_event "$line"
  # an automatic incident keeps its entry in alerts.json: the owner's choice is written there and PINNED (alerts_end keeps a pinned severity until the incident closes),
  # so the next pass of the check does not put the old one back and announce a "change"
  if [[ "${ALERTS_DRY_RUN:-0}" != 1 && -r "$STATE/alerts.json" ]] && jq -e --arg k "$key" --arg i "$inc" 'has($k) and .[$k].incident == $i' "$STATE/alerts.json" > /dev/null 2>&1; then
    jq -c --arg k "$key" --arg sev "$sev" '.[$k].sev = $sev | .[$k].pinned = true' "$STATE/alerts.json" > "$STATE/alerts.json.tmp" && mv -f "$STATE/alerts.json.tmp" "$STATE/alerts.json"
  fi
  drop_lock
  echo "$inc pasa de $before a $sev."
  send "[$sev] $key: $why ($inc; antes $before)"
  mirror
}

cmd_open() {
  local service=${1:-} sev=${2:-} text=${3:-} at_epoch=$NOW
  [[ $# -ge 3 ]] || die "uso: incident.sh open <servicio> <SEV1|SEV2|SEV3> \"síntoma\" [--at 2026-10-26T15:02Z]  (servicios: $SERVICES)"
  shift 3
  while [[ $# -gt 0 ]]; do
    case "$1" in --at) [[ $# -ge 2 ]] || die "--at necesita una hora"; parse_at "$2"; at_epoch=$AT_EPOCH; shift 2 ;; *) die "no entiendo «$1»" ;; esac
  done
  [[ " $SERVICES " == *" $service "* ]] || die "el servicio «$service» no está en la lista: $SERVICES"
  [[ "$sev" =~ ^SEV[123]$ ]] || die "la severidad es SEV1, SEV2 o SEV3"
  check_text "$text"
  local key="manual.$service" inc line
  take_lock
  _NOW=$NOW   # the number is the one of today's sequence (the year of the REGISTRATION), whatever --at says: a past --at must not make the yearly sequence go back
  inc="$(_incident_next)"
  line="$(jq -cn --arg at "$(iso "$at_epoch")" --arg i "$inc" --arg k "$key" --arg s "$service" --arg sev "$sev" --arg t "$text" \
    '{at: $at, event: "open", incident: $i, key: $k, service: $s, severity: $sev, text: $t, actor: "owner"}')"
  write_event "$line"
  drop_lock
  echo "Abierto $inc ($sev, $service). Ciérralo con: incident.sh close $inc"
  send "[$sev] $key: $text ($inc; abierto a mano por el dueño)"
  mirror
}

cmd_close() {
  local inc=${1:-} text="cerrado a mano por el dueño" at_epoch=$NOW
  [[ $# -ge 1 ]] || die "uso: incident.sh close INC-2026-014 [\"texto\"] [--at 2026-10-26T15:02Z]"
  shift
  if [[ $# -gt 0 && "$1" != --* ]]; then text=$1; shift; fi
  while [[ $# -gt 0 ]]; do
    case "$1" in --at) [[ $# -ge 2 ]] || die "--at necesita una hora"; parse_at "$2"; at_epoch=$AT_EPOCH; shift 2 ;; *) die "no entiendo «$1»" ;; esac
  done
  require_incident "$inc"
  [[ "$(jq -r '.actor // "system"' <<< "$OPEN_JSON")" == owner ]] || die "$inc lo abrió una comprobación del servidor: la misma comprobación lo cierra cuando el problema desaparece (si ya no es un problema real, arréglalo en el origen o anótalo con «note»)"
  [[ -z "$(event_of "$inc" close)" ]] || die "$inc ya está cerrado"
  check_text "$text"
  local key service sev opened minutes line
  key="$(jq -r .key <<< "$OPEN_JSON")"; service="$(jq -r .service <<< "$OPEN_JSON")"; sev="$(current_severity "$inc")"; opened="$(jq -r .at <<< "$OPEN_JSON")"
  (( at_epoch >= $(date -u -d "$opened" +%s) )) || die "la hora de cierre es anterior a la de apertura ($opened)"
  minutes=$(( (at_epoch - $(date -u -d "$opened" +%s)) / 60 ))
  line="$(jq -cn --arg at "$(iso "$at_epoch")" --arg i "$inc" --arg k "$key" --arg s "$service" --arg sev "$sev" --arg t "$text" --argjson m "$minutes" \
    '{at: $at, event: "close", incident: $i, key: $k, service: $s, severity: $sev, text: $t, minutes: $m, actor: "owner"}')"
  take_lock; write_event "$line"; drop_lock
  echo "Cerrado $inc tras $minutes min."
  send "[recuperado] $key tras $minutes min ($inc; cerrado a mano por el dueño)"
  mirror
}

case "${1:-}" in
  list) shift; cmd_list "$@" ;;
  show) shift; cmd_show "$@" ;;
  note) shift; cmd_note "$@" ;;
  severity) shift; cmd_severity "$@" ;;
  open) shift; cmd_open "$@" ;;
  close) shift; cmd_close "$@" ;;
  help | -h | --help | "") usage ;;
  *) die "no conozco «$1». Ejecuta incident.sh help" ;;
esac
