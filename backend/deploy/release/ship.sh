#!/usr/bin/env bash
# Puts a kit (build_kit.sh) on the server, checks its hashes THERE, and prints the command that starts the chain. It starts the chain only
# with --start AND --owner-ok: a release goes to production when the owner says so, never because a script could.
#
#   ship.sh --host predigol --kit ../releases/20261102T1200Z-f11            # copy + check, prints the start command
#   ship.sh --host predigol --kit ... --start --owner-ok                   # and starts the chain, detached (systemd-run)
set -Eeuo pipefail
HOST="" KIT="" START=0 OK=0
die() { echo "ship: $*" >&2; exit 1; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;; --kit) KIT="$2"; shift 2 ;; --start) START=1; shift ;; --owner-ok) OK=1; shift ;;
    *) die "unknown argument $1" ;;
  esac
done
[[ -n "$HOST" && -d "$KIT" ]] || die "usage: ship.sh --host HOST --kit DIR [--start --owner-ok]"
KIT="$(cd "$KIT" && pwd)"; name="$(basename "$KIT")"; remote="/root/releases/$name"
(cd "$KIT" && sha256sum -c --quiet SHA256SUMS && sha256sum -c --quiet SCRIPTS.sha256) || die "the kit does not match its own hashes"
ssh -o BatchMode=yes "$HOST" "test ! -e '$remote'" || die "$remote already exists on $HOST"
ssh -o BatchMode=yes "$HOST" "mkdir -p '$remote' && chmod 700 '$remote'"
scp -q -o BatchMode=yes "$KIT"/* "$HOST:$remote/"
ssh -o BatchMode=yes "$HOST" "cd '$remote' && chmod 755 *.sh && sha256sum -c --quiet SHA256SUMS && sha256sum -c --quiet SCRIPTS.sha256" || die "the hashes differ on the server"
echo "shipped: $HOST:$remote (hashes checked there)"
cmd="systemd-run --unit=$(jq -r .release "$KIT/RELEASE.json")-chain --collect --quiet --working-directory=$remote /bin/bash -c '$remote/chain.sh < /dev/null > $remote/chain.out 2>&1'"
if (( START )); then
  (( OK )) || die "--start needs --owner-ok: the owner's word is what releases"
  ssh -o BatchMode=yes "$HOST" "$cmd"
  echo "chain started; follow it with: ssh $HOST tail -f $remote/chain.log"
else
  echo "to start it (with the owner's word):  ssh $HOST \"$cmd\""
fi