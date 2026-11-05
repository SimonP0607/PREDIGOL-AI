#!/usr/bin/env bash
# CI side of the deploy door (plan CI/CD, C4): puts the deploy key and the pinned host key where ssh looks, and names the host `predigol-gh`.
# Reads three values from the environment (the `production` environment of GitHub: a secret and two variables); prints none of them.
#   DEPLOY_SSH_KEY      private key (secret). On the server it is bound to predigol-gh-deploy, which accepts a handful of commands.
#   DEPLOY_HOST         the server's address (variable)
#   DEPLOY_KNOWN_HOSTS  the server's host key line, as in known_hosts (variable): the connection is refused if the server shows another
set -Eeuo pipefail
for v in DEPLOY_SSH_KEY DEPLOY_HOST DEPLOY_KNOWN_HOSTS; do [[ -n "${!v:-}" ]] || { echo "ci_ssh_setup: $v is empty (set it in the production environment)" >&2; exit 1; }; done
[[ "$DEPLOY_HOST" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "ci_ssh_setup: DEPLOY_HOST is not a plain host name or address" >&2; exit 1; }
H="${SSH_HOME:-$HOME}/.ssh"
umask 077
mkdir -p "$H"
# A key saved from Windows or into a one-line field arrives mangled (CR at the end of every line, a UTF-8 BOM in front, tabs or spaces
# where the line breaks were) and ssh then fails with "error in libcrypto". Take the mess out and write the key the way ssh-keygen does:
# the header, the base64 body in lines of 70 characters, the footer. A key that is already well formed comes out byte for byte the same.
KEY_FILE="$H/predigol_gh_deploy"
raw="$(printf '%s' "$DEPLOY_SSH_KEY" | LC_ALL=C sed '1s/^\xef\xbb\xbf//' | tr -d '\r')"
flat="${raw//$'\n'/ }"
flat="${flat//$'\t'/ }"
header="$(printf '%s' "$flat" | LC_ALL=C grep -o -m1 -e '-----BEGIN [A-Z ]*-----' || true)"
footer="${header/BEGIN/END}"
has_header=no
has_footer=no
body=''
[[ -n "$header" ]] && has_header=yes
if [[ "$has_header" == yes && "$flat" == *"$footer"* ]]; then has_footer=yes; fi
if [[ "$has_footer" == yes ]]; then
  body="${flat#*"$header"}"
  body="${body%%"$footer"*}"
  body="${body//[[:space:]]/}"
  { printf '%s\n' "$header"; printf '%s' "$body" | fold -w 70; printf '\n%s\n' "$footer"; } > "$KEY_FILE"
else
  printf '%s\n' "$raw" > "$KEY_FILE"
fi
chmod 600 "$KEY_FILE"
# Say what is wrong with the key now, here, instead of a "Permission denied" two steps later. Only facts are printed, never the key.
if command -v ssh-keygen > /dev/null 2>&1 && ! why="$(ssh-keygen -y -P '' -f "$KEY_FILE" 2>&1 > /dev/null)"; then
  echo "ci_ssh_setup: the deploy key does not load (header=$has_header footer=$has_footer lines=$(wc -l < "$KEY_FILE") body_chars=${#body}): ${why##*: }" >&2
  echo "ci_ssh_setup: save DEPLOY_SSH_KEY again in the environment, the whole private key, with no passphrase." >&2
  exit 1
fi
printf '%s\n' "$DEPLOY_KNOWN_HOSTS" | tr -d '\r' > "$H/known_hosts_predigol"
cat > "$H/config" <<EOF
Host predigol-gh
  HostName $DEPLOY_HOST
  User root
  IdentityFile $H/predigol_gh_deploy
  IdentitiesOnly yes
  UserKnownHostsFile $H/known_hosts_predigol
  StrictHostKeyChecking yes
  BatchMode yes
  ServerAliveInterval 30
  ConnectTimeout 20
EOF
chmod 600 "$H/config"
echo "ssh host predigol-gh ready"