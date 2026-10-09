#!/usr/bin/env bash
# The application settings that already exist on the laptop, into the server's /etc/predigol/app.env - cut-over
# step 5 (README "Corte"): API-Football (key, plan, budget, concurrency, base URL), the odds capture windows tuned
# here, the second-factor key (every account's authenticator keeps working after the cut-over) and the AI decision
# layer (mode, models, budget, Anthropic and Exa keys). Run in WSL from the backend checkout.
#
#   deploy/cutover/push-app-env.sh HOST [ENV_FILE]      (HOST: an alias of ~/.ssh/config; ENV_FILE: the laptop's .env)
#
# The values go through ssh's stdin and are written by root on the server (umask 077, then 600 root:root): never on
# a command line, in a log or on the screen. Only the NAMES are printed. Existing names are replaced, others kept.
set -Eeuo pipefail
host="${1:?usage: push-app-env.sh HOST [ENV_FILE]}"
src="${2:-$(cd "$(dirname "$0")/../.." && pwd)/.env}"
pattern='^(FBI_APIFOOTBALL_[A-Z0-9_]+|FBI_ODDS_[A-Z0-9_]+|FBI_AUTH_SECRET_KEY|FBI_AI_[A-Z0-9_]+|EXA_API_KEY)='
lines="$(grep -E "$pattern" "$src" || true)"
[[ -n "$lines" ]] || { echo "nothing to push from $src" >&2; exit 1; }
echo "pushing to $host: $(cut -d= -f1 <<< "$lines" | sort | tr '\n' ' ')"
# shellcheck disable=SC2016
ssh -o BatchMode=yes "$host" 'set -eu
  f=/etc/predigol/app.env
  test -f "$f" || { echo "no $f: run install.sh first" >&2; exit 1; }
  umask 077
  tmp="$(mktemp)"
  cp "$f" "$tmp"
  n=0
  while IFS= read -r line; do
    k="${line%%=*}"
    case "$k" in *[!A-Z0-9_]*|"") echo "skipped a malformed line" >&2; continue;; esac
    grep -v "^${k}=" "$tmp" > "$tmp.n" || true
    mv "$tmp.n" "$tmp"
    printf "%s\n" "$line" >> "$tmp"
    n=$((n + 1))
  done
  install -m 600 -o root -g root "$tmp" "$f"
  rm -f "$tmp"
  echo "app.env on $(hostname): $n written, $(grep -cE "^[A-Z][A-Z0-9_]*=" "$f") settings, mode $(stat -c %a "$f")"' <<< "$lines"
