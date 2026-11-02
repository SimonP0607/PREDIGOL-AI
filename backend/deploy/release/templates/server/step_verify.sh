#!/usr/bin/env bash
# Release __REL__, after the deploy: what the database and the services say. READ-ONLY. The lines OK / NOT OK are checked by the script.
# IA release: the AI layer's own checks replace the sessions of A1. Plan UX, section 45: "picks y decisiones del día idénticos antes y después, huella de modelos mc9a7bec97ca igual" - the day digest with the
# cutoff step_deploy.sh read before predigolctl ran must be the same now. Adapted from the F14 step_verify.sh.
set -uo pipefail
D=/root/releases/__STAMP__
PARTS="__PARTS__"
PSQL() { docker exec -i -e PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=0' predigol-postgres psql -U fbi -d fbi -At -F '|' "$@"; }
section() { echo; echo "== $*"; }
verdict() { if [ "$1" = "$2" ]; then echo "OK: $3 = $1"; else echo "NOT OK: $3 = $1, expected $2"; fi; }
releases() { case " $PARTS " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }

section "now"; date -u +%FT%TZ
section "checkouts (expect the release commits)"
BE=$(git -C /opt/predigol/backend rev-parse --short=12 HEAD); WEB=$(git -C /opt/predigol/web rev-parse --short=12 HEAD)
echo "backend $BE web $WEB"
verdict "$BE" "__BE_WANT__" "backend checkout"; verdict "$WEB" "__WEB_WANT__" "web checkout"
section "revision (expect the latest migration of the release)"
REV=$(PSQL -c "select version_num from alembic_version" < /dev/null); echo "$REV"
verdict "${REV:0:4}" "$(jq -r .latest_migration "$D/RELEASE.json" | cut -c1-4)" "revision"
section "services"; predigolctl status 2>&1 | tail -n 9
section "the containers that run and their images"
docker ps --format '{{.Names}} {{.Image}} {{.Status}}' < /dev/null
if releases backend; then
  section "the libraries of the image against constraints.txt (pip freeze of each container, read only; expect no difference)"
  WANT_LIBS=$(grep -v '^#' /opt/predigol/backend/constraints.txt | grep .)
  for c in predigol-worker predigol-api; do
    HAVE_LIBS=$(docker exec "$c" pip freeze --exclude-editable 2>&1 < /dev/null)
    DIFF=$(diff <(printf '%s\n' "$HAVE_LIBS") <(printf '%s\n' "$WANT_LIBS") || true)
    verdict "$(printf '%s' "$DIFF" | grep -c '^[<>]')" "0" "lines that differ between the pip freeze of $c and constraints.txt"
  done
fi
section "model code (the guard): the checkout and the forecasts written since the deploy"
CODE_NOW=$(python3 "$D/model_code_guard.py" fingerprint dir=/opt/predigol/backend)
verdict "$CODE_NOW" "$(jq -r .model_code.after "$D/RELEASE.json")" "model code of the checkout"
verdict "$CODE_NOW" "__MODEL_FP__" "model code fingerprint"
SINCE=$(cat "$D/deploy.finished" 2>/dev/null || echo "")
if [ -n "$SINCE" ]; then
  OTHER=$(PSQL -c "select count(*) from models.predictions p join models.model_versions v on v.id = p.model_version_id where p.backtest_session_id is null and p.created_at >= '$SINCE' and v.version ~ '@mc[0-9a-f]{10}\$' and v.version !~ '@${CODE_NOW}\$'" < /dev/null)
  verdict "$OTHER" "0" "rows written since the deploy by another model code than the checkout's"
fi
section "the day's picks and decisions: the same cutoff before and after (plan UX, section 45)"
CUTOFF=$(cat "$D/day_digest.cutoff" 2>/dev/null || echo "")
if [ -n "$CUTOFF" ]; then
  "$D/day_digest.sh" "$CUTOFF" > "$D/day_digest.after"
  echo "before: $(cat "$D/day_digest.before")"
  echo "after:  $(cat "$D/day_digest.after")"
  if [ "$(cat "$D/day_digest.after")" = "$(cat "$D/day_digest.before")" ]; then
    verdict "$(cat "$D/day_digest.after")" "$(cat "$D/day_digest.before")" "picks and decisions of the day written before the deploy (cutoff $CUTOFF)"
  else
    # The lines differ. What the deploy must not do is change what was already decided; a writer that had started before the cutoff and committed after the
    # first read ADDS rows stamped before the cutoff (pick_pipeline stamps its picks with the moment it starts). So: every row of the first read must be
    # in the second one with the same fields (nothing changed, nothing went); the rows that are new are counted and said.
    # (the rows of the first read must have been kept: an empty file is only believable when the first read itself had no picks and no decisions)
    if [ -s "$D/day_digest.rows.before" ] || { [ "$(cut -d' ' -f2 "$D/day_digest.before")" = 0 ] && [ "$(cut -d' ' -f6 "$D/day_digest.before")" = 0 ]; }; then
      "$D/day_digest.sh" --rows "$CUTOFF" > "$D/day_digest.rows.after"
      LC_ALL=C sort "$D/day_digest.rows.before" > "$D/day_digest.rows.before.sorted"; LC_ALL=C sort "$D/day_digest.rows.after" > "$D/day_digest.rows.after.sorted"
      CHANGED=$(LC_ALL=C comm -23 "$D/day_digest.rows.before.sorted" "$D/day_digest.rows.after.sorted" | wc -l)
      ADDED_PICKS=$(LC_ALL=C comm -13 "$D/day_digest.rows.before.sorted" "$D/day_digest.rows.after.sorted" | grep -c '^pick ' || true)
      ADDED_DECISIONS=$(LC_ALL=C comm -13 "$D/day_digest.rows.before.sorted" "$D/day_digest.rows.after.sorted" | grep -c '^decision ' || true)
      echo "the two lines differ; rows of the first read that are not, identical, in the second: $CHANGED; rows only in the second: $ADDED_PICKS pick(s), $ADDED_DECISIONS decision(s)"
      verdict "$CHANGED" "0" "rows of the day's picks and decisions read before the deploy (cutoff $CUTOFF) that changed or went (rows ADDED by a run that started before the cutoff and committed after the first read: $ADDED_PICKS picks, $ADDED_DECISIONS decisions, are not a change)"
    else
      echo "NOT OK: picks and decisions of the day written before the deploy (cutoff $CUTOFF) differ and the rows of the first read were not kept: $(cat "$D/day_digest.after") against $(cat "$D/day_digest.before")"
    fi
  fi
else
  echo "NOT OK: no cutoff recorded by step_deploy.sh"
fi
section "the checks this release carries (RELEASE.json .verify_checks, each a read-only query and the answer it must give)"
N=$(jq -r '.verify_checks | length' "$D/RELEASE.json" 2>/dev/null || echo 0)
if [ "${N:-0}" -eq 0 ]; then echo "(none)"; fi
STARTED=$(cat "$D/deploy.started" 2>/dev/null || date -u +%FT%TZ)
for i in $(seq 0 $(( ${N:-0} - 1 ))); do
  NAME=$(jq -r ".verify_checks[$i].name" "$D/RELEASE.json"); SQL=$(jq -r ".verify_checks[$i].sql" "$D/RELEASE.json")
  WANT=$(jq -r ".verify_checks[$i].expect" "$D/RELEASE.json")
  SQL=${SQL//@DEPLOY_STARTED@/$STARTED} # a check may ask about what happened since the deploy started
  verdict "$(PSQL -c "$SQL" < /dev/null 2>&1 | tr '\n' ' ' | sed 's/ *$//')" "$WANT" "$NAME"
done
section "the settings this release carries (RELEASE.json .verify_env: a variable that is not a secret, in a running container, and the value it must have - or one of several, written a|b; UNSET is absent or empty)"
NE=$(jq -r '(.verify_env // []) | length' "$D/RELEASE.json" 2>/dev/null || echo 0)
if [ "${NE:-0}" -eq 0 ]; then echo "(none)"; fi
for i in $(seq 0 $(( ${NE:-0} - 1 ))); do
  EC=$(jq -r ".verify_env[$i].container" "$D/RELEASE.json"); EN=$(jq -r ".verify_env[$i].name" "$D/RELEASE.json"); EW=$(jq -r ".verify_env[$i].expect" "$D/RELEASE.json")
  case "$EN" in *[!A-Z0-9_]* | "") verdict "bad name '$EN'" "a variable name" "verify_env[$i]"; continue ;; esac
  case "$EC" in predigol-api | predigol-worker) ;; *) verdict "bad container '$EC'" "predigol-api or predigol-worker" "verify_env[$i]"; continue ;; esac
  EG=$(docker exec "$EC" sh -c "printenv $EN" < /dev/null 2>/dev/null || true)
  EGV=${EG:-UNSET}
  case "|$EW|" in
    *"|$EGV|"*) echo "OK: $EN in $EC = $EGV (allowed: $EW)" ;;
    *) echo "NOT OK: $EN in $EC = $EGV, expected one of: $EW" ;;
  esac
done
section "the AI layer after the deploy (read only; names and counts, never a value)"
echo "the AI variables the running containers have (names only):"
for c in predigol-api predigol-worker; do
  echo "$c: $(docker exec "$c" sh -c "env | cut -d= -f1 | grep -E '^(FBI_AI_|FBI_ANALYST_|EXA_API_KEY)' | sort | tr '\n' ' '" < /dev/null)"
done
if jq -e '(.migrations_new // []) | any(startswith("0110"))' "$D/RELEASE.json" > /dev/null 2>&1; then
  verdict "$(PSQL -c "select count(*) from ai.usage where at < '$STARTED' and (cache_write_tokens is not null or cache_write_1h_tokens is not null or cache_ttl is not null or thinking_tokens is not null or batch_id is not null or custom_id is not null or workspace is not null or key_label is not null or run_id is not null or agent is not null)" < /dev/null)" "0" "ai.usage rows written before the deploy that carry a value in the new columns of 0110 (the old rows keep NULL)"
fi
PSQL -c "select 'model calls in ai.usage since the deploy started:', count(*), coalesce(round(sum(cost_usd), 4)::text, '0') from ai.usage where at >= '$STARTED'" < /dev/null
PSQL -c "select 'agent promotions:', count(*) from intel.promotions where entity = 'agent'" < /dev/null
PSQL -c "select 'ai.match_runs rows (the state job writes one per match and pass, every 10 minutes):', count(*) from ai.match_runs" < /dev/null
section "the forecasts go on (forecast-v1 and family-v1 rows known in the last 6 hours)"
PSQL -c "select version, count(*), max(known_at) from models.match_forecasts where known_at >= now() - interval '6 hours' group by 1 order by 1" < /dev/null
section "recent runs of the ingestion in the last 3 hours (expect no new failures)"
PSQL -c "select job_type, status, count(*) from raw.ingestion_runs where started_at > now() - interval '3 hours' group by 1, 2 order by 3 desc limit 14" < /dev/null
section "errors in the logs since the deploy (api, web, worker)"
for c in predigol-api predigol-web predigol-worker; do
  since=$(docker inspect -f '{{.State.StartedAt}}' "$c" < /dev/null)
  echo "$c started $since: $(docker logs --since "$since" "$c" 2>&1 < /dev/null | grep -ciE '"level": ?"(error|critical)"|traceback|unhandled') lines with error/traceback"
done
