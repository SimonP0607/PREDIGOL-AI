#!/usr/bin/env bash
# A drill of the alerts (security plan S3.5, docs/owner/SIMULACROS_AVISOS.md): the message of one alert, sent to the owner's phone through the very channel and the very
# state machine every alert uses, WITHOUT the alert being true. Run by the session during the drills; the owner only looks at his phone.
#
#   bin/alert-drill.sh --list                          every alert it can send, with its severity and its text, and the record that --all sends
#   bin/alert-drill.sh KEY [SEV] [options]             one alert: the opening message and, after --hold seconds, the "recuperado" one
#   bin/alert-drill.sh --all [options]                 the record: the opening message of each alert in it, one every --pause seconds, each on its own (no recovery messages)
#   bin/alert-drill.sh --healthchecks NAME [options]   the /fail ping of one Healthchecks check and, after --hold seconds, the ping that recovers it
#   bin/alert-drill.sh --evidence                      what was sent so far (state/drills.jsonl), as the rows of the drill record
#     options: --hold SECONDS (default 20) | --reminder (SEV1 only: also the reminder of a SEV1 that stays open) | --open-only (the opening message alone, no recovery one) |
#              --pause SECONDS (--all only, default 3: Telegram takes about 20 messages a minute from one bot into one chat) | --dry-run (print, send nothing, write nothing)
#     KEY is a key of the table below (--list); SEV picks one of its severities, the most severe one by default.
#     NAME is one of health backup restore-test raw-sync pitr pitr-test maint (the HC_PING_* variables of predigol.env); its URL is never printed.
#
# It runs on a scratch state directory: state/alerts.json and state/incidents.jsonl are never touched (no incident is opened in the real register, and the INC number in
# the message comes from a scratch counter that starts at 900), and no check runs. Every message starts with "SIMULACRO". What it proves is what only production can
# prove - the message reaches the owner's phone with its severity and its words, and the open / remind / recover cycle works through the real bot. That the REAL check
# raises the alert is proven on Staging v2, with the real stack (the table of docs/owner/SIMULACROS_AVISOS.md says how, alert by alert).
# Every message it sends is a line of state/drills.jsonl, with the UTC time of the trigger and the stages Telegram took (--evidence prints them as the rows of the drill record).
# Exit 0 every message was taken (the Healthchecks pings were answered) | 1 one was not | 2 usage, an alert it does not know, or no channel is configured.
set -Eeuo pipefail
# shellcheck source=bin/lib.sh
. "$(dirname "$0")/lib.sh"
# shellcheck source=bin/alerts_lib.sh
. "$(dirname "$0")/alerts_lib.sh"

# One line per (key, severity) that the scripts can raise, with the text they would send and sample values in place of the counts. tests/unit/test_owner_simulacros_doc.py
# keeps this table in step with the alert_set calls of healthcheck.sh, alerts_checks.sh, security-alerts.sh and incident-dump.sh: a key or a severity that the scripts
# raise and this table lacks, or a text that the scripts would not send, fails that test. "<nombre>" and "{nombre}" are the five services.
drill_table() {
  cat << 'TABLE'
admin.denied|SEV2|34 respuestas 401/403 en rutas de administrador en 10 min
api.login|SEV1|/auth/me responde 200 sin sesión: el inicio de sesión no se está exigiendo
api.login|SEV3|la comprobación de /auth/me no encuentra la ruta (¿cambió la API?)
auth.bruteforce|SEV2|34 inicios de sesión fallidos en 5 min
auth.locked|SEV3|2 cuenta(s) en espera en la última hora (id 0,0)
auth.newdevice|SEV2|inicio de sesión de administrador desde un navegador nuevo (id 0)
auth.privileged|SEV1|1 cambio(s) de rol, MFA o contraseña, 1 hecho(s) por otra cuenta que no es la del dueño (id 0)
auth.privileged|SEV2|1 cambio(s) de rol, MFA o contraseña (id 0)
backup.local|SEV2|la copia local más reciente tiene más de 26 h
backup.locks|SEV1|falló la última comprobación de los candados del cubo: las copias fuera del servidor podrían borrarse
backup.locks|SEV3|los candados del cubo se comprobaron por última vez hace 12 días
backup.offsite|SEV1|la copia más reciente fuera del servidor tiene más de 3 días
backup.offsite|SEV2|la copia más reciente fuera del servidor tiene 30 h
backup.offsite|SEV3|todavía no hay ninguna copia verificada fuera del servidor
config.drift|SEV2|cambió la configuración respecto a la línea base: Caddyfile
db.connections|SEV2|PostgreSQL usa el 85 % de las conexiones
disk.forecast|SEV2|al ritmo actual el disco llega al 90 % en unos 9 días (+4600 MB/día)
disk.usage|SEV1|el disco está al 91 %
disk.usage|SEV2|el disco está al 83 %
host.resources|SEV2|el servidor está sobrecargado: CPU robada al 22 % durante 15 min
incidents.dump|SEV3|3 línea(s) nueva(s) del registro de incidentes no se pudieron copiar a la base (el fichero state/incidents.jsonl las conserva; log: incident-dump)
ingest.live|SEV2|3 partido(s) en juego y la última captura en vivo fue hace 14 min
ingest.runs|SEV2|25 ejecuciones de ingesta fallidas en la última hora
picks.review|SEV3|2 pick(s) de 1 partido(s) terminados esperan revisión (el motivo está en picks.pick_results.review_reason)
picks.unsettled|SEV2|3 pick(s) de 2 partido(s) terminados hace más de 3 h siguen sin liquidar (el más antiguo espera 25 h)
pitr.backup|SEV2|la copia base PITR tiene más de 26 h
pitr.test|SEV2|falló la última verificación del repositorio PITR
pitr.wal|SEV1|el archivado de WAL hacia el repositorio PITR está fallando
provider.quota|SEV2|el presupuesto diario de API-Football va por el 93 %
raw.full|SEV2|la última pasada completa del RAW fue hace 6 días
raw.sync|SEV2|el almacén RAW se copió fuera del servidor por última vez hace 14 h
restore.test|SEV2|el último ensayo de restauración falló
svc.<nombre>|SEV1|el contenedor {nombre} no está sano (parado)
svc.<nombre>.loop|SEV1|el contenedor {nombre} se ha reiniciado 4 veces en 12 min
tls.origin|SEV1|el certificado caduca en 5 días
tls.origin|SEV2|el certificado caduca en 15 días
web.degraded|SEV2|la API informa salud degradada (detalle en health.json)
web.errors5xx|SEV2|31 errores 5xx en 5 min
web.health|SEV1|la web no responde en /health
web.login|SEV1|la web no responde en /login
worker.heartbeat|SEV1|el worker dejó de latir; lo reinicié
TABLE
}
SERVICES=(postgres api worker web caddy)
HC_NAMES=(health backup restore-test raw-sync pitr pitr-test maint)
# The record of the drill: what --all sends, in this order. One line of the table per alert of the plan's catalogue, at the severity the catalogue gives it (an alert with
# two severities is here at both when the catalogue names both); a service stands for the five. docs/owner/SIMULACROS_AVISOS.md marks these rows with a dot, and
# tests/unit/test_owner_simulacros_doc.py keeps the two in step. The rows left out are the other severities of an alert: bin/alert-drill.sh KEY SEV sends any of them.
RECORD=(
  admin.denied:SEV2 api.login:SEV1 auth.bruteforce:SEV2 auth.locked:SEV3 auth.newdevice:SEV2 auth.privileged:SEV1 auth.privileged:SEV2
  backup.local:SEV2 backup.locks:SEV1 backup.offsite:SEV2 config.drift:SEV2 db.connections:SEV2 disk.forecast:SEV2 disk.usage:SEV1 disk.usage:SEV2
  host.resources:SEV2 incidents.dump:SEV3 ingest.live:SEV2 ingest.runs:SEV2 picks.review:SEV3 picks.unsettled:SEV2 pitr.backup:SEV2 pitr.test:SEV2
  pitr.wal:SEV1 provider.quota:SEV2 raw.full:SEV2 raw.sync:SEV2 restore.test:SEV2 svc.api:SEV1 svc.api.loop:SEV1 tls.origin:SEV2
  web.degraded:SEV2 web.errors5xx:SEV2 web.health:SEV1 web.login:SEV1 worker.heartbeat:SEV1
)

expanded_table() {  # the table with "<nombre>" turned into each of the five services
  local key sev text svc
  while IFS='|' read -r key sev text; do
    [[ -n "$key" ]] || continue
    if [[ "$key" == *'<nombre>'* ]]; then
      for svc in "${SERVICES[@]}"; do printf '%s|%s|%s\n' "${key//<nombre>/$svc}" "$sev" "${text//\{nombre\}/$svc}"; done
    else
      printf '%s|%s|%s\n' "$key" "$sev" "$text"
    fi
  done < <(drill_table)
}

usage() { sed -n '2,/^set -/{/^set -/!p}' "$0" | sed 's/^# \{0,1\}//'; }
die_usage() { echo "alert-drill: $*" >&2; echo "alert-drill: bin/alert-drill.sh --list shows what it can send; --help the options" >&2; exit 2; }

MODE=drill KEY="" SEV="" HOLD="" PAUSE="" REMINDER=0 OPENONLY=0 DRY=0 HCNAME=""
setmode() { [[ "$MODE" == drill ]] || die_usage "--list, --evidence, --all and --healthchecks are four different things: one at a time"; MODE=$1; }
while (( $# )); do
  case "$1" in
    --list) setmode list ;;
    --evidence) setmode evidence ;;
    --all) setmode all ;;
    --healthchecks) [[ $# -ge 2 ]] || die_usage "--healthchecks needs the name of a check (${HC_NAMES[*]})"; setmode hc; HCNAME=$2; shift ;;
    --hold) [[ $# -ge 2 ]] || die_usage "--hold needs a number of seconds"; HOLD=$2; shift ;;
    --pause) [[ $# -ge 2 ]] || die_usage "--pause needs a number of seconds"; PAUSE=$2; shift ;;
    --reminder) REMINDER=1 ;;
    --open-only) OPENONLY=1 ;;
    --dry-run) DRY=1 ;;
    -h | --help) usage; exit 0 ;;
    SEV[123]) SEV=$1 ;;
    -*) die_usage "unknown option $1" ;;
    *) [[ -z "$KEY" ]] || die_usage "one alert at a time ($KEY and $1)"; KEY=$1 ;;
  esac
  shift
done
seconds() {  # <option> <value> <largest>: a whole number of seconds
  [[ "$2" =~ ^[0-9]{1,4}$ ]] && (( 10#$2 <= $3 )) || die_usage "$1 is a number of seconds, 0 to $3"
}
[[ -z "$HOLD" ]] || seconds --hold "$HOLD" 600
[[ -z "$PAUSE" ]] || seconds --pause "$PAUSE" 60
# which options go with which mode: a combination that means nothing is a mistake the session should hear about before anything is sent
if [[ "$MODE" == all ]]; then
  [[ -z "$KEY$SEV$HOLD" ]] && (( ! REMINDER && ! OPENONLY )) \
    || die_usage "--all sends the opening message of every alert of the record: it takes no alert, no severity, no --hold, no --reminder and no --open-only (only --pause and --dry-run)"
else
  [[ -z "$PAUSE" ]] || die_usage "--pause is for --all (the pause between its messages)"
fi
if (( OPENONLY )); then
  (( ! REMINDER )) || die_usage "--open-only and --reminder together: the reminder comes after the opening message and before the recovery one"
  [[ "$MODE" != hc ]] || die_usage "--open-only is for the alerts of the table: a Healthchecks check must always be recovered after its /fail"
fi
HOLD=$((10#${HOLD:-20})) PAUSE=$((10#${PAUSE:-3}))

# --- what was sent so far ------------------------------------------------------------------------------------------------------------------------
if [[ "$MODE" == evidence ]]; then
  if [[ ! -s "$STATE/drills.jsonl" ]]; then echo "alert-drill: nothing was sent yet ($STATE/drills.jsonl does not exist)"; exit 0; fi
  echo "| Disparo (UTC) | Qué | Clave o check | Gravedad | Mensajes | Canal | Resultado |"
  echo "|---|---|---|---|---|---|---|"
  jq -r 'def es($m): $m[.] // .;
    ({open: "apertura", remind: "recordatorio", close: "recuperado", fail: "/fail", up: "recuperación"}) as $stage
    | ({alert: "aviso", healthchecks: "Healthchecks"}) as $kind
    | ({server: "bot del servidor", app: "bot de la aplicación", healthchecks: "Healthchecks", none: "ninguno"}) as $channel
    | "| \(.at) | \(.kind | es($kind)) | \(.key // .name) | \(.severity // "-") | \((.sent // []) | if length == 0 then "-" else map(es($stage)) | join(" + ") end) | \(.channel | es($channel)) | \(if .ok then "enviado" else "FALLÓ: " + (.failed // "?") end) |"' "$STATE/drills.jsonl"
  exit 0
fi

# --- what it can send ----------------------------------------------------------------------------------------------------------------------------
if [[ "$MODE" == list ]]; then
  printf '%-24s %-5s %s\n' KEY SEV TEXT
  while IFS='|' read -r key sev text; do printf '%-24s %-5s %s\n' "$key" "$sev" "$text"; done < <(expanded_table)
  echo
  echo "Healthchecks checks (--healthchecks NAME): ${HC_NAMES[*]}"
  echo
  echo "The record (--all sends the opening message of each, in this order, one every --pause seconds): ${#RECORD[@]} messages"
  for entry in "${RECORD[@]}"; do printf '  %s %s\n' "${entry%%:*}" "${entry##*:}"; done
  exit 0
fi

# --- the channel ---------------------------------------------------------------------------------------------------------------------------------
# (A Healthchecks drill needs no bot of ours: Healthchecks tells the phone through its own Telegram integration.)
CHANNEL="$(alert_channel)"
if [[ "$MODE" == drill || "$MODE" == all ]] && (( ! DRY )) && [[ -z "$CHANNEL" ]]; then
  log "alert-drill: no channel is configured. PREDIGOL_ALERT_BOT_TOKEN and PREDIGOL_ALERT_CHAT_ID (predigol.env) need a value each, both of them (bin/alert-test.sh says the same)"
  exit 2
fi
case "$CHANNEL" in
  server) via="the server's alert bot (PREDIGOL_ALERT_* in predigol.env)" ;;
  app) via="the application's bot (FBI_TELEGRAM_* in app.env)" ;;
  *) via="nobody (dry run)"; [[ "$MODE" != drill && "$MODE" != all ]] || log "alert-drill: dry run, and no channel is configured: a real run would stop here with exit 2 (bin/alert-test.sh checks the channel)" ;;
esac
REAL_STATE=$STATE
SENT=""   # the stages that Telegram (or Healthchecks) took so far in the drill under way, separated by spaces: open remind close | fail up
evidence() {  # <kind: alert|healthchecks> <key-or-name> <severity> <ok true|false> <what failed, or empty>
  (( DRY )) && return 0
  local channel=${CHANNEL:-none}
  [[ "$1" != healthchecks ]] || channel=healthchecks
  jq -cn --arg at "$T0" --arg kind "$1" --arg key "$2" --arg sev "$3" --arg channel "$channel" --arg sent "$SENT" --argjson ok "$4" --arg failed "$5" \
    '{at: $at, kind: $kind} + (if $kind == "alert" then {key: $key} else {name: $key} end) + (if $sev == "" then {} else {severity: $sev} end)
      + {channel: $channel, sent: ($sent | split(" ") | map(select(. != ""))), ok: $ok} + (if $failed == "" then {} else {failed: $failed} end)' \
    >> "$REAL_STATE/drills.jsonl"
}
refused() {  # what the owner is told when Telegram or Healthchecks said no
  log "alert-drill: $1 was NOT taken (through $via). For Telegram, 401 or 404 above = the token is wrong or was revoked; 400 or 403 = the bot may not write to that chat. bin/alert-test.sh checks the channel alone"
}

# --- a Healthchecks check ------------------------------------------------------------------------------------------------------------------------
if [[ "$MODE" == hc ]]; then
  [[ " ${HC_NAMES[*]} " == *" $HCNAME "* ]] || die_usage "'$HCNAME' is not a check (${HC_NAMES[*]})"
  var="HC_PING_${HCNAME^^}"; var="${var//-/_}"
  url="${!var:-}"
  [[ -n "$url" ]] || { log "alert-drill: $var is empty in predigol.env: that check is not configured yet"; exit 2; }
  if (( DRY )); then echo "WOULD PING: $var /fail, then after $HOLD s the ping that recovers it"; exit 0; fi
  ping_one() { curl -fsS -m 10 --retry 3 -o /dev/null "${url}${1:+/$1}" < /dev/null 2> /dev/null; }   # stderr is dropped: the URL is a secret and curl may name it
  T0="$(date -u +%FT%TZ)"
  failed=""
  if ping_one fail; then
    SENT="fail"
    log "alert-drill: the /fail ping of '$HCNAME' was answered at $(date -u +%H:%M:%S) UTC. Healthchecks tells the phone through its own Telegram integration: note the time it arrives"
  else
    failed="the /fail ping"
  fi
  [[ -n "$failed" ]] || sleep "$HOLD"   # if the /fail never arrived there is nothing to wait for: the recovery ping still goes, so no check is left failed
  if ping_one; then
    SENT+="${SENT:+ }up"
    log "alert-drill: the ping that recovers '$HCNAME' was answered at $(date -u +%H:%M:%S) UTC"
  else
    failed+="${failed:+ and }the recovery ping"
  fi
  if [[ -z "$failed" ]]; then
    evidence healthchecks "$HCNAME" "" true ""
    log "alert-drill: done. The record of this drill is in $REAL_STATE/drills.jsonl (bin/alert-drill.sh --evidence)"
    exit 0
  fi
  evidence healthchecks "$HCNAME" "" false "$failed"
  log "alert-drill: Healthchecks did not answer $failed of '$HCNAME': is the URL in $var the check's ping URL, without /start or /fail? (it is not printed here: it is a secret)"
  exit 1
fi

# --- the alerts of the table ---------------------------------------------------------------------------------------------------------------------
resolve() {  # <key> [severity] -> ROW, "key|SEV|text": the row of that severity, or the most severe one of the key when none is given
  local rows
  rows="$(expanded_table | awk -F'|' -v k="$1" '$1 == k')"
  if [[ -z "$rows" ]]; then
    echo "alert-drill: '$1' is not an alert the scripts raise. They are:" >&2
    expanded_table | cut -d'|' -f1 | sort -u | tr '\n' ' ' >&2; echo >&2
    exit 2
  fi
  if [[ -n "${2:-}" ]]; then
    ROW="$(awk -F'|' -v s="$2" '$2 == s' <<< "$rows")"
    [[ -n "$ROW" ]] || die_usage "$1 is never raised at $2; it is raised at: $(cut -d'|' -f2 <<< "$rows" | sort | tr '\n' ' ')"
  else
    ROW="$(sort -t'|' -k2,2 <<< "$rows" | head -n 1)"
  fi
}
if [[ "$MODE" == drill ]]; then
  [[ -n "$KEY" ]] || die_usage "which alert? (--list shows them, --all sends the whole record)"
  resolve "$KEY" "$SEV"
  IFS='|' read -r key sev text <<< "$ROW"
  (( ! REMINDER )) || [[ "$sev" == SEV1 ]] || die_usage "--reminder is for a SEV1 (the others are never repeated); $key at $sev is not"
fi

# The scratch state: alerts_lib.sh reads and writes $STATE, so the real register and the open alerts stay as they are.
SCRATCH="$(mktemp -d)"
trap 'rm -rf "$SCRATCH"' EXIT
STATE="$SCRATCH"
REFUSED=0 FAILED=0 QUIET=0 T0=""
_alert_send() {   # what alerts_lib.sh calls to speak: every message is a drill, the text goes to the log (it has no secret), and Telegram's answer decides the exit code
  local rc=0
  if (( DRY )); then echo "WOULD SEND: SIMULACRO · $*"; return 0; fi
  notify_ok "SIMULACRO · $*" || rc=$?
  if (( rc == 0 )); then log "alert-drill: sent at $(date -u +%H:%M:%S) UTC: SIMULACRO · $*"; else REFUSED=1; fi
  return "$rc"
}
passed() {  # <stage> <what that pass sent>: the first message Telegram did not take ends that drill (FAILED) - nothing is left to clean, the scratch state goes with the script
  if (( REFUSED )); then refused "$2"; evidence alert "$key" "$sev" false "$2"; FAILED=1; return 0; fi
  SENT+="${SENT:+ }$1"
}

drill_one() {  # <key> <severity> <text> <number of the INC the messages carry, 901...> <full|reminder|open-only>: FAILED=1 when Telegram did not take a message
  local key=$1 sev=$2 text=$3 inc=$4 plan=$5
  rm -rf "${SCRATCH:?}"/*
  printf '%s %s\n' "$(date -u +%Y)" "$((inc - 1))" > "$STATE/incident.seq"
  REFUSED=0 FAILED=0 SENT=""
  T0="$(date -u +%FT%TZ)"
  alerts_begin drill
  alert_set "$key" "$sev" "$text"
  alerts_end
  passed open "the opening message"
  (( ! FAILED )) || return 0
  (( DRY || QUIET )) || log "alert-drill: look at the phone: that message should be there, through $via. Note the time it arrives"
  if [[ "$plan" == reminder ]]; then
    sleep 1   # a reminder needs the alert to be at least ALERT_REMIND_SECS=1 old
    alerts_begin drill
    alert_set "$key" "$sev" "$text"
    ALERT_REMIND_SECS=1 alerts_end
    passed remind "the reminder of the SEV1 that stays open"
    (( ! FAILED )) || return 0
  fi
  if [[ "$plan" != open-only ]]; then
    (( DRY )) || sleep "$HOLD"
    alerts_begin drill
    alerts_end
    passed close "the recovery message"
    (( ! FAILED )) || return 0
  fi
  evidence alert "$key" "$sev" true ""
}

# --- the record: the opening message of each alert, one after the other -------------------------------------------------------------------------------
if [[ "$MODE" == all ]]; then
  total=${#RECORD[@]} n=0 streak=0 taken=0 bad=() QUIET=1
  for entry in "${RECORD[@]}"; do
    n=$((n + 1))
    resolve "${entry%%:*}" "${entry##*:}"
    IFS='|' read -r key sev text <<< "$ROW"
    echo "[$n/$total] $key $sev"
    drill_one "$key" "$sev" "$text" $((900 + n)) open-only
    if (( FAILED )); then
      bad+=("$key $sev"); streak=$((streak + 1))
      if (( streak >= 3 )); then log "alert-drill: --all: three in a row were refused: the channel is not working, so it stops here (bin/alert-test.sh checks it alone)"; break; fi
    else
      taken=$((taken + 1)); streak=0
    fi
    (( n == total || DRY )) || sleep "$PAUSE"
  done
  if (( DRY )); then log "alert-drill: --all: dry run, $total messages shown and none sent"; exit 0; fi
  summary="--all: $taken of $total opening messages taken"
  (( ${#bad[@]} == 0 )) || summary+="; NOT taken: $(IFS=,; echo "${bad[*]}")"
  (( n == total )) || summary+="; $((total - n)) more were not even tried"
  if (( taken == total )); then
    log "alert-drill: $summary. The record of this drill is in $REAL_STATE/drills.jsonl (bin/alert-drill.sh --evidence)"
    exit 0
  fi
  log "alert-drill: $summary"
  exit 1
fi

# --- one alert -------------------------------------------------------------------------------------------------------------------------------------
plan=full
(( ! REMINDER )) || plan=reminder
(( ! OPENONLY )) || plan=open-only
drill_one "$key" "$sev" "$text" 901 "$plan"
(( ! FAILED )) || exit 1
(( DRY )) || log "alert-drill: done. The record of this drill is in $REAL_STATE/drills.jsonl (bin/alert-drill.sh --evidence)"
