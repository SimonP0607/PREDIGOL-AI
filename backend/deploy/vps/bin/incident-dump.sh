#!/usr/bin/env bash
# Every 10 minutes (predigol-incident-dump.timer): copies state/incidents.jsonl into the table audit.incident_events, so that the register of incidents is inside
# the dumps and the point-in-time copies like the rest of the database. The FILE is the truth (it works with the database down, and the checks write to it);
# the table is its mirror, filled in whenever the database answers. Idempotent: every line is stored once, keyed by the sha256 of the line itself, so running
# this a hundred times, or after the database was restored from an older copy, only adds what is missing.
#
#   bin/incident-dump.sh [--dry-run] [--force]
#   --dry-run   says how many lines there are and what it would do; touches nothing
#   --force     does not skip when the file is the same one that was mirrored last time
#
# It runs as the database OWNER (the only role that may write the register; db/grants.sql keeps the API and the worker out of it). Nothing of the lines
# is printed: counts only. A line the table refuses (not JSON, an id of another shape, a note without its field...: a data error or a constraint of the table) is
# counted as rejected, the rest go in, and the alert incidents.dump (SEV3) says so (for NEW refused lines; the next pass closes it). Anything else that goes wrong
# (the table is not there, a column is, a lock does not give way, a privilege is missing...) is not the fault of a line: the whole copy is undone and it is a FAILED
# mirror, which says nothing for a day (counted from its last good copy, or from its first failed attempt when it has never worked) and then says so.
#
# State: state/incident-dump.json {"at","ok_at","file_sha256","lines","added","already","rejected"; "first_try_at" while it has never worked}, state/incident-dump.lock.
# Environment: INCIDENT_PSQL (tests only: the psql command to use instead of the compose one, e.g. "psql -h 127.0.0.1 -U fbi -d scratch"),
#              INCIDENT_DUMP_MAX_LINES (50000: the newest lines of the file), INCIDENT_DUMP_NOW (epoch, tests only).
set -Euo pipefail
HERE="$(dirname "$0")"
# shellcheck source=bin/lib.sh
. "$HERE/lib.sh"
# shellcheck source=bin/alerts_lib.sh
. "$HERE/alerts_lib.sh"

DRY=0; FORCE=0
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    --force) FORCE=1 ;;
    *) echo "usage: incident-dump.sh [--dry-run] [--force]" >&2; exit 2 ;;
  esac
done

FILE="$STATE/incidents.jsonl"; MARK="$STATE/incident-dump.json"
NOW=${INCIDENT_DUMP_NOW:-$(date +%s)}
[[ -s "$FILE" ]] || exit 0
exec 8> "$STATE/incident-dump.lock"
flock -n 8 || { log "incident-dump: another run holds the lock"; exit 0; }

# one snapshot of the file: what is hashed is what is sent (the checks may append meanwhile)
snap="$(mktemp "$STATE/incident-dump.XXXXXX")"; err="$(mktemp "$STATE/incident-dump.XXXXXX")"
trap 'rm -f "$snap" "$err"' EXIT
tail -n "${INCIDENT_DUMP_MAX_LINES:-50000}" "$FILE" > "$snap"
sha="$(sha256sum "$snap" | cut -c1-64)"
lines="$(grep -c . "$snap" || true)"

# nothing new since the last good run (unless the alert of this script is open: then one more pass is what closes it)
alert_open=0; jq -e 'has("incidents.dump")' "$STATE/alerts.json" > /dev/null 2>&1 && alert_open=1
if (( FORCE == 0 && alert_open == 0 )) && [[ -r "$MARK" ]] && [[ "$(jq -r '.file_sha256 // ""' "$MARK" 2> /dev/null)" == "$sha" ]]; then exit 0; fi
prev_rejected="$(jq -r '.rejected // 0' "$MARK" 2> /dev/null || echo 0)"; [[ "$prev_rejected" =~ ^[0-9]+$ ]] || prev_rejected=0
if (( DRY )); then echo "incident-dump: $lines line(s) in the register file; would copy them to audit.incident_events (nothing written)"; exit 0; fi

psql_owner() {
  if [[ -n "${INCIDENT_PSQL:-}" ]]; then
    # shellcheck disable=SC2086  # the test's command is several words on purpose
    $INCIDENT_PSQL -X -q -v ON_ERROR_STOP=1 -v VERBOSITY=verbose "$@"
  else
    compose exec -T postgres psql -U fbi -d fbi -X -q -v ON_ERROR_STOP=1 -v VERBOSITY=verbose "$@"
  fi
}

# The lines travel as COPY data, never as part of the SQL text: a backslash, a tab or a "$" in a note cannot become SQL. COPY's text format needs \ \t \r
# escaped; with every backslash doubled no line can be the terminator "\." either. jq reads the lines as text, so the hash below is that of the line
# as jq saw it (a byte that is not UTF-8 becomes U+FFFD, the same way every time).
payload_lines() { jq -Rrs 'split("\n") | map(select(length > 0)) | .[] | gsub("\\\\"; "\\\\") | gsub("\t"; "\\t") | gsub("\r"; "\\r")' "$snap"; }

IFS= read -r -d '' SQL_HEAD <<'SQL' || true
SET lock_timeout = '5s';
SET statement_timeout = '120s';
BEGIN;
CREATE TEMP TABLE _lines (n bigserial, line text NOT NULL) ON COMMIT DROP;
COPY _lines (line) FROM STDIN;
SQL
IFS= read -r -d '' SQL_TAIL <<'SQL' || true
DO $dump$
DECLARE r record; j jsonb; added int := 0; seen int := 0; bad int := 0;
BEGIN
  FOR r IN SELECT n, line FROM _lines ORDER BY n LOOP
    BEGIN
      j := r.line::jsonb;
      INSERT INTO audit.incident_events (line_sha256, incident_id, event, at, alert_key, service, severity, body, field, minutes, actor, raw)
      VALUES (encode(sha256(convert_to(r.line, 'UTF8')), 'hex'), j->>'incident', j->>'event', (j->>'at')::timestamptz, j->>'key', j->>'service',
              j->>'severity', coalesce(CASE WHEN j->>'event' = 'note' THEN j->>'value' ELSE j->>'text' END, ''), j->>'field',
              (j->>'minutes')::int, coalesce(j->>'actor', 'system'), j)
      ON CONFLICT (line_sha256) DO NOTHING;
      IF FOUND THEN added := added + 1; ELSE seen := seen + 1; END IF;
    EXCEPTION WHEN data_exception OR integrity_constraint_violation THEN
      -- this line is the problem (not JSON, not a date, an id of another shape, a missing field): count it and go on. Any other error (class 42: no table, no column,
      -- no privilege; 25: read only; 55: a lock; 53: no resources...) is the database's, the same for every line: it is not caught, the copy is undone and the run fails
      bad := bad + 1;   -- the state code only: the message of a failed row quotes the row
      RAISE NOTICE 'incident-dump: line % refused (%)', r.n, SQLSTATE;
    END;
  END LOOP;
  RAISE NOTICE 'incident-dump: added=% already=% rejected=%', added, seen, bad;
END
$dump$;
COMMIT;
SQL

rc=0
# (the two heredocs above already end in a newline: one more would be an EMPTY row of COPY data, refused by the jsonb cast at every run)
{ printf '%s' "$SQL_HEAD"; payload_lines; printf '\\.\n%s' "$SQL_TAIL"; } | psql_owner -f - > /dev/null 2> "$err" || rc=$?

added=0; already=0; rejected=0; counted=0
if (( rc == 0 )) && grep -q 'incident-dump: added=' "$err"; then
  counted=1
  read -r added already rejected < <(sed -n 's/.*incident-dump: added=\([0-9]*\) already=\([0-9]*\) rejected=\([0-9]*\).*/\1 \2 \3/p' "$err" | tail -n 1)
fi

mark_json() {  # at ok_at sha
  jq -cn --arg at "$(date -u -d "@$NOW" +%FT%TZ)" --arg ok "$1" --arg sha "$2" --argjson lines "$lines" --argjson added "$added" --argjson already "$already" \
    --argjson rejected "$rejected" '{at: $at, ok_at: $ok, file_sha256: $sha, lines: $lines, added: $added, already: $already, rejected: $rejected}'
}

alerts_begin incidents
if (( counted == 1 )); then
  log "incident-dump: $lines line(s): $added added, $already already there, $rejected refused"
  mark_json "$(date -u -d "@$NOW" +%FT%TZ)" "$sha" > "$MARK.tmp" && mv -f "$MARK.tmp" "$MARK"
  # a refused line stays in the file for good and is refused again by every pass: the alert is for NEW ones (the next pass, seeing no more, closes it)
  if (( rejected > prev_rejected )); then
    alert_set incidents.dump SEV3 "$(( rejected - prev_rejected )) línea(s) nueva(s) del registro de incidentes no se pudieron copiar a la base (el fichero state/incidents.jsonl las conserva; log: incident-dump)"
  fi
else
  # the state code of the error the database gave, if it gave one (VERBOSITY=verbose prints it: "ERROR:  42P01: ..."); the code only, never the message, which can quote a row
  code="$(grep -m1 -oE 'ERROR:  [0-9A-Z]{5}:' "$err" 2> /dev/null | cut -c9-13 || true)"
  log "incident-dump: the database did not take the register (exit $rc${code:+, SQLSTATE $code}); the file keeps every line, the next run tries again"
  now_iso="$(date -u -d "@$NOW" +%FT%TZ)"
  # Since when it has not been working: the last good copy or, for a mirror that has never worked (the table is missing, a role is wrong...), the first attempt
  # that failed. Without that second reference such a mirror would hold in silence for ever, and the register would never travel with the database copies.
  since_iso="$(jq -r 'def good: type == "string" and ((try fromdate catch null) != null); first(([.ok_at, .first_try_at][] | select(good)), "")' "$MARK" 2> /dev/null || true)"
  since=0; [[ -z "$since_iso" ]] || since="$(date -u -d "$since_iso" +%s 2> /dev/null || echo 0)"
  # the register file is the truth, so one failure is not worth a message; a day without a copy is
  if (( since > 0 )) && (( NOW - since > 86400 )); then
    alert_set incidents.dump SEV3 "el registro de incidentes lleva más de 24 h sin copiarse a la base de datos (el fichero lo conserva)"
  else
    alerts_hold incidents.dump
  fi
  # The mark of the last good run stays (its sha is that of that run); the time of this attempt is recorded, and the first failed attempt of a mirror that has not worked yet.
  # A mark that says neither (an empty one, a date that is not a date) starts its day now, and one that cannot be read is made again.
  if [[ -r "$MARK" ]] && jq -c --arg at "$now_iso" 'def good: type == "string" and ((try fromdate catch null) != null);
       (if (.ok_at | good) then . else .first_try_at |= (if good then . else $at end) end) | .at = $at' "$MARK" > "$MARK.tmp" 2> /dev/null; then :
  else jq -cn --arg at "$now_iso" '{at: $at, first_try_at: $at}' > "$MARK.tmp"; fi
  mv -f "$MARK.tmp" "$MARK"
fi
alerts_end
exit 0
