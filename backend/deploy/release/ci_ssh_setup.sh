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
printf '%s\n' "$DEPLOY_SSH_KEY" > "$H/predigol_gh_deploy"
chmod 600 "$H/predigol_gh_deploy"
printf '%s\n' "$DEPLOY_KNOWN_HOSTS" > "$H/known_hosts_predigol"
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