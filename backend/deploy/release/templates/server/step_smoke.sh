#!/usr/bin/env bash
# The smoke tests through the public address: /health, /login, HSTS, /auth/me -> 401, /docs -> 404, the routes of F7, F9 and F12.3 and the
# routes of the IA release (Operación -> Agentes, the state file of a match, the costs) -> 401 without a session, and the R02 probe. (F14 template,
# IA release.)
set -Eeuo pipefail
. /opt/predigol/backend/deploy/vps/bin/lib.sh
domain="$PREDIGOL_DOMAIN"
C="curl -fsS -m 20 --resolve $domain:443:127.0.0.1"
$C https://$domain/health | jq -c '{status, version: .version}' || $C https://$domain/health | head -c 400
# Every check is a command of its own. "check && echo ok" does NOT stop the script when the check fails (set -e ignores the left side of a &&
# list), which is how these three once passed whatever the server answered; and a pipe into "grep -q" can make curl fail on a closed pipe, so the
# answers are read into variables first. /health gets a few tries: the services were restarted a moment ago.
health=""
for _ in 1 2 3 4 5 6; do
  if health=$($C https://$domain/health) && jq -e '.status == "ok" or .status == "degraded"' <<< "$health" > /dev/null; then break; fi
  health=""
  sleep 10
done
[ -n "$health" ] || { echo "health: NOT ok after 6 tries"; exit 1; }
echo "health: ok"
$C -o /dev/null https://$domain/login
echo "login: 200"
hdrs=$($C -D - -o /dev/null https://$domain/login)
grep -qi '^strict-transport-security' <<< "$hdrs"
echo "hsts: present"
code=$(${C/-fsS/-sS} -o /dev/null -w '%{http_code}' https://$domain/api/v1/auth/me); echo "auth/me: $code"; test "$code" = 401
code=$(${C/-fsS/-sS} -o /dev/null -w '%{http_code}' https://$domain/docs); echo "docs: $code"; test "$code" = 404
code=$(${C/-fsS/-sS} -o /dev/null -w '%{http_code}' https://$domain/api/v1/matches/1/knowledge); echo "matches/1/knowledge (no session): $code"; test "$code" = 401
code=$(${C/-fsS/-sS} -o /dev/null -w '%{http_code}' "https://$domain/api/v1/admin/intelligence/market-matrix"); echo "admin/intelligence/market-matrix (no session): $code"; test "$code" = 401
code=$(${C/-fsS/-sS} -o /dev/null -w '%{http_code}' "https://$domain/api/v1/admin/evolution/code-promotions"); echo "admin/evolution/code-promotions (no session): $code"; test "$code" = 401
for route in ai/agents ai/matches/1/state ai/costs ai/overview; do
  code=$(${C/-fsS/-sS} -o /dev/null -w '%{http_code}' "https://$domain/api/v1/admin/$route"); echo "admin/$route (no session): $code"; test "$code" = 401
done
# R02 (plan UX A0, security plan W1): a document navigation to the server-function path with a harmless marker (never a script) must not come
# back as HTML that carries the marker unescaped. Through Caddy, as a browser would ask for it.
MARK="predigol-r02-probe-$(date +%s)"
HDRS=$(mktemp)
body=$(${C/-fsS/-sS} -D "$HDRS" -H 'sec-fetch-mode: navigate' -H 'sec-fetch-dest: document' -H 'accept: text/html' "https://$domain/_serverFn/predigol-probe?payload=%3Cb%3E$MARK%3C%2Fb%3E" || true)
status=$(head -n 1 "$HDRS" | tr -d '\r')
if grep -qi '^content-type: *text/html' "$HDRS" && grep -qF "<b>$MARK</b>" <<< "$body"; then echo "serverFn probe: REFLECTED ($status)"; rm -f "$HDRS"; exit 1; fi
echo "serverFn probe: the marker does not come back as HTML ($status, $(grep -i '^content-type' "$HDRS" | tr -d '\r' || echo 'no content-type'))"
rm -f "$HDRS"
echo "SMOKE OK"
