#!/usr/bin/env bash
# Security plan R02 (S1), the harmless marker test (W1): a document navigation to /_serverFn/... carrying a marker text (never a script), written
# in several ways. PASS for the target = no response that is HTML AND contains the marker. Sends only GET/POST requests with that text.
# Usage: serverfn-probe.sh <base-url> [curl-extra-args...]      (same forms as serverfn-matrix.sh)
# Exit status 0 when no probe was answered with HTML that carries the marker.
set -u
BASE=${1:?base url}; shift
M="PGMARKER$(date +%s)zq"
ID1=$(printf '%s' '{"file":"/src/routes/index.tsx","export":"fn_createServerFn_handler"}' | base64 -w0 | tr '+/' '-_' | tr -d '=')
fail=0; n=0
probe() {  # label, method, path, extra curl args...
  local label=$1 method=$2 path=$3; shift 3
  n=$((n+1))
  local out hdr code ctype
  out=$(mktemp); hdr=$(mktemp)
  code=$(curl -s -m 10 "$@" -X "$method" -o "$out" -D "$hdr" -w '%{http_code}' "$BASE$path" 2>/dev/null)
  ctype=$(grep -i '^content-type:' "$hdr" | head -1 | tr -d '\r' | cut -c15-80)
  local reflected=no html=no
  grep -q "$M" "$out" && reflected=yes
  { echo "$ctype" | grep -qi 'text/html'; } && html=yes
  local verdict=ok
  if [ "$reflected" = yes ] && [ "$html" = yes ]; then verdict=FAIL; fail=$((fail+1)); fi
  printf '%-44s %-4s %-30s status=%s type=%-30s html=%s marker_in_body=%s -> %s\n' "$label" "$method" "$path" "$code" "${ctype:-none}" "$html" "$reflected" "$verdict" | cut -c1-230
  rm -f "$out" "$hdr"
}
NAV=(-H 'Sec-Fetch-Mode: navigate' -H 'Sec-Fetch-Dest: document' -H 'Accept: text/html,application/xhtml+xml,*/*;q=0.8')
probe "typed URL (Sec-Fetch-Site none)"       GET  "/_serverFn/$ID1?payload=$M"            "$@" "${NAV[@]}" -H 'Sec-Fetch-Site: none'
probe "link from another site (cross-site)"   GET  "/_serverFn/$ID1?payload=$M"            "$@" "${NAV[@]}" -H 'Sec-Fetch-Site: cross-site'
probe "link, unknown id"                      GET  "/_serverFn/$M?payload=$M"              "$@" "${NAV[@]}" -H 'Sec-Fetch-Site: cross-site'
probe "no fetch-metadata headers (plain curl)" GET "/_serverFn/$ID1?payload=$M"            "$@"
probe "json payload with the header"          POST "/_serverFn/$ID1"                       "$@" -H 'x-tsr-serverFn: true' -H 'content-type: application/json' --data "{\"data\":\"$M\",\"context\":{\"result\":\"$M\"}}"
probe "json payload without the header"       POST "/_serverFn/$ID1"                       "$@" -H 'content-type: application/json' --data "{\"data\":\"$M\"}"
probe "empty id with marker query"            GET  "/_serverFn/?x=$M"                      "$@" "${NAV[@]}" -H 'Sec-Fetch-Site: cross-site'
# the same document navigation written in other ways, to see that no spelling of the path reaches a server function through the front door unfiltered
probe "variant: encoded underscore"           GET  "/%5fserverFn/$ID1?payload=$M"          "$@" "${NAV[@]}" -H 'Sec-Fetch-Site: cross-site'
probe "variant: double slash at the start"    GET  "//_serverFn/$ID1?payload=$M"           "$@" "${NAV[@]}" -H 'Sec-Fetch-Site: cross-site' --path-as-is
probe "variant: dot segment before"           GET  "/./_serverFn/$ID1?payload=$M"          "$@" "${NAV[@]}" -H 'Sec-Fetch-Site: cross-site' --path-as-is
probe "variant: parent segment before"        GET  "/x/../_serverFn/$ID1?payload=$M"       "$@" "${NAV[@]}" -H 'Sec-Fetch-Site: cross-site' --path-as-is
probe "variant: encoded slash after the name" GET  "/_serverFn%2f$ID1?payload=$M"          "$@" "${NAV[@]}" -H 'Sec-Fetch-Site: cross-site' --path-as-is
probe "variant: lower-case name"              GET  "/_serverfn/$ID1?payload=$M"            "$@" "${NAV[@]}" -H 'Sec-Fetch-Site: cross-site'
probe "variant: upper-case name"              GET  "/_SERVERFN/$ID1?payload=$M"            "$@" "${NAV[@]}" -H 'Sec-Fetch-Site: cross-site'
probe "variant: backslash after the slash"    GET  "/\\_serverFn/$ID1?payload=$M"          "$@" "${NAV[@]}" -H 'Sec-Fetch-Site: cross-site' --path-as-is
probe "variant: encoded backslash"            GET  "/%5C_serverFn/$ID1?payload=$M"         "$@" "${NAV[@]}" -H 'Sec-Fetch-Site: cross-site' --path-as-is
probe "variant: encoded dot in the name"      GET  "/_serverFn/%2e/$ID1?payload=$M"        "$@" "${NAV[@]}" -H 'Sec-Fetch-Site: cross-site' --path-as-is
probe "variant: trailing dot segment"         GET  "/_serverFn/$ID1/.?payload=$M"          "$@" "${NAV[@]}" -H 'Sec-Fetch-Site: cross-site' --path-as-is
echo "r02_marker: $n probes, $fail reflected-as-html; marker=$M"
[ "$fail" -eq 0 ]
