#!/usr/bin/env bash
# The rule of the front door for TanStack Start server functions (Caddyfile, `handle /_serverFn/*`; security plan R02, S1), probed from outside.
# Each probe states what is EXPECTED:
#   BLOCK = the rule answers (403, empty body, Content-Security-Policy "default-src 'none'")      PASS = the request goes on to the web
# and a few paths the rule must not touch. Sends only GET/POST requests with harmless text; changes nothing on the server.
# Usage: serverfn-matrix.sh <base-url> [curl-extra-args...]
#   from the server:   serverfn-matrix.sh https://$PREDIGOL_DOMAIN --resolve $PREDIGOL_DOMAIN:443:127.0.0.1
#   from the Internet: serverfn-matrix.sh https://<the domain>
#   rehearsal:         serverfn-matrix.sh https://staging.localhost -k
# Exit status 0 when every probe answered as expected.
set -u
BASE=${1:?base url}; shift
bad=0; n=0
probe() {  # expected, label, method, path, curl args...
  local exp=$1 label=$2 method=$3 path=$4; shift 4
  n=$((n+1))
  local hdr out code csp len got=PASS verdict
  hdr=$(mktemp); out=$(mktemp)
  code=$(curl -s -m 10 "$@" -X "$method" -o "$out" -D "$hdr" -w '%{http_code}' "$BASE$path" 2>/dev/null)
  csp=$(grep -i '^content-security-policy:' "$hdr" | head -1 | tr -d '\r' | cut -c1-60)
  len=$(wc -c < "$out" | tr -d ' ')
  if [ "$code" = 403 ] && [ "$len" = 0 ] && echo "$csp" | grep -q "default-src 'none'"; then got=BLOCK; fi
  verdict=ok; [ "$got" = "$exp" ] || { verdict="MISMATCH"; bad=$((bad+1)); }
  printf '%-52s expect=%-5s got=%-5s status=%s bytes=%s csp="%s" -> %s\n' "$label" "$exp" "$got" "$code" "$len" "$csp" "$verdict" | cut -c1-220
  rm -f "$hdr" "$out"
}
ID=eyJmaWxlIjoiL3NyYy94IiwiZXhwb3J0IjoieSJ9
CALL=(-H 'x-tsr-serverFn: true' -H 'Sec-Fetch-Mode: cors' -H 'Sec-Fetch-Site: same-origin' -H 'Accept: application/json')
probe PASS  "legit call (header, cors, json) GET"          GET  "/_serverFn/$ID?payload=x"  "$@" "${CALL[@]}"
probe PASS  "legit call POST"                              POST "/_serverFn/$ID"            "$@" "${CALL[@]}" -H 'content-type: application/json' --data '{}'
probe PASS  "legit call, header name in capitals"          GET  "/_serverFn/$ID"            "$@" -H 'X-TSR-SERVERFN: true' -H 'Sec-Fetch-Mode: cors' -H 'Accept: */*'
probe PASS  "legit call, no Accept at all"                 GET  "/_serverFn/$ID"            "$@" -H 'x-tsr-serverFn: true' -H 'Accept:'
probe BLOCK "no header"                                    GET  "/_serverFn/$ID"            "$@" -H 'Sec-Fetch-Mode: cors' -H 'Accept: application/json'
probe BLOCK "header with another value (false)"           GET  "/_serverFn/$ID"            "$@" -H 'x-tsr-serverFn: false' -H 'Sec-Fetch-Mode: cors'
probe BLOCK "header empty"                                 GET  "/_serverFn/$ID"            "$@" -H 'x-tsr-serverFn;' -H 'Sec-Fetch-Mode: cors'
probe BLOCK "header + document navigation"                 GET  "/_serverFn/$ID"            "$@" -H 'x-tsr-serverFn: true' -H 'Sec-Fetch-Mode: navigate' -H 'Accept: application/json'
probe BLOCK "header + Accept text/html"                    GET  "/_serverFn/$ID"            "$@" -H 'x-tsr-serverFn: true' -H 'Sec-Fetch-Mode: cors' -H 'Accept: text/html,application/xhtml+xml'
probe BLOCK "header + Accept with text/html inside a list" GET  "/_serverFn/$ID"            "$@" -H 'x-tsr-serverFn: true' -H 'Accept: application/json, text/html;q=0.5'
probe BLOCK "typed URL in a browser (no header, navigate)" GET  "/_serverFn/$ID?payload=PGMARKER" "$@" -H 'Sec-Fetch-Mode: navigate' -H 'Sec-Fetch-Dest: document' -H 'Accept: text/html'
probe BLOCK "plain curl, no headers at all"                GET  "/_serverFn/$ID"            "$@"
probe BLOCK "POST without the header"                      POST "/_serverFn/$ID"            "$@" -H 'content-type: application/json' --data '{}'
probe BLOCK "empty id"                                     GET  "/_serverFn/"               "$@" -H 'Sec-Fetch-Mode: navigate' -H 'Accept: text/html'
probe PASS  "encoded dots leave the rule's path (-> /x)"   GET  "/_serverFn/%2e%2e/x"       "$@" -H 'Accept: text/html'
probe BLOCK "path case variant is covered (matcher is case-insensitive)" GET "/_SERVERFN/$ID" "$@" -H 'Accept: text/html'
# paths that must NOT be touched by the rule
probe PASS  "home page (document navigation)"              GET  "/"                         "$@" -H 'Sec-Fetch-Mode: navigate' -H 'Accept: text/html'
probe PASS  "login page"                                   GET  "/login"                    "$@" -H 'Sec-Fetch-Mode: navigate' -H 'Accept: text/html'
probe PASS  "service worker"                               GET  "/sw.js"                    "$@"
probe PASS  "health"                                       GET  "/health"                   "$@"
probe PASS  "API, unauthenticated route"                   GET  "/api/v1/auth/me"           "$@" -H 'Accept: application/json'
probe PASS  "similar prefix is not the rule's path"        GET  "/_serverFnX/$ID"           "$@" -H 'Accept: text/html'
echo "r02_caddy_matrix: $n probes, $bad mismatches"
[ "$bad" -eq 0 ]
