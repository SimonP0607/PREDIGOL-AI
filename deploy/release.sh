#!/usr/bin/env bash
# The release pipeline, from the laptop (WSL) to the server - no GitHub, no CI service (FASE 8).
#
#   deploy/release.sh --host predigol            # an ssh host (~/.ssh/config: HostName, User root, IdentityFile)
#   deploy/release.sh --host local               # this machine runs the server (the rehearsal)
#   deploy/release.sh --host predigol --skip-gates   # only after a green run on the same commits
#
# 1. Both checkouts clean, on their branch, and pushed to the local bare repositories (the history of record).
# 2. Gates: backend ruff, mypy (both configurations), pytest; web lint, typecheck, unit tests, production build.
#    Any failure stops here.
# 3. A versioned artefact: releases/<stamp>-<backend>-<web>/ with git bundles of both branches, SHA256SUMS and
#    RELEASE.json (commits, gate results).
# 4. Shipped over ssh, checksums verified on the server, both checkouts moved to EXACTLY these commits.
# 5. `predigolctl deploy` there: backup first, build, migrate (a failed migration stops everything with the old
#    version still running), grants, restart, health.
# 6. Smoke tests through the public address: /health ok, /login 200, the API refuses an anonymous /auth/me (401),
#    HSTS present, /docs closed. A failure prints the rollback command.
set -Eeuo pipefail
HOST=""
SKIP_GATES=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --skip-gates) SKIP_GATES=1; shift ;;
    *) echo "usage: $0 --host <ssh host|local> [--skip-gates]" >&2; exit 2 ;;
  esac
done
[[ -n "$HOST" ]] || { echo "usage: $0 --host <ssh host|local> [--skip-gates]" >&2; exit 2; }
BE="${PREDIGOL_BACKEND_DIR:-$HOME/projects/football-intelligence-v2}"
WEB="${PREDIGOL_WEB_DIR:-$HOME/projects/football-intelligence-hub}"
BRANCH="${PREDIGOL_BRANCH:-feature/predigol-ux-rbac}"
REMOTE_BE="${PREDIGOL_REMOTE_BACKEND:-/opt/predigol/backend}"
REMOTE_WEB="${PREDIGOL_REMOTE_WEB:-/opt/predigol/web}"
CTL="${PREDIGOLCTL:-predigolctl}"
log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*"; }
die() { log "RELEASE STOPPED: $*"; exit 1; }
remote() { if [[ "$HOST" == local ]]; then bash -c "$1"; else ssh -o BatchMode=yes "$HOST" "$1"; fi; }

# 1. Clean, on the branch, pushed.
for repo in "$BE" "$WEB"; do
  [[ -z "$(git -C "$repo" status --porcelain --untracked-files=no)" ]] || die "$repo has uncommitted changes"
  [[ "$(git -C "$repo" branch --show-current)" == "$BRANCH" ]] || die "$repo is not on $BRANCH"
done
[[ "$(git -C "$BE" rev-parse HEAD)" == "$(git -C "$BE" rev-parse "origin/$BRANCH" 2> /dev/null)" ]] \
  || die "backend HEAD is not pushed to its local bare repository (git push origin $BRANCH)"
[[ "$(git -C "$WEB" rev-parse HEAD)" == "$(git -C "$WEB" rev-parse "local/$BRANCH" 2> /dev/null)" ]] \
  || die "web HEAD is not pushed to its local bare repository (git push local $BRANCH)"
be_sha="$(git -C "$BE" rev-parse --short=12 HEAD)"; web_sha="$(git -C "$WEB" rev-parse --short=12 HEAD)"
log "release: backend $be_sha, web $web_sha -> $HOST"

# 2. Gates.
gates="skipped"
if (( ! SKIP_GATES )); then
  log "gates: backend"
  (cd "$BE" && .venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/mypy . && .venv/bin/pytest -q -p no:randomly) \
    || die "backend gates failed"
  log "gates: web"
  (cd "$WEB" && bun run lint && bun run typecheck && bun test src \
    && NITRO_PRESET=node-server VITE_DATA_MODE=live bun run build) || die "web gates failed"
  gates="passed"
fi

# 3. The artefact.
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
REL="${PREDIGOL_RELEASES:-$HOME/releases}/$STAMP-$be_sha-$web_sha"
mkdir -p "$REL"
git -C "$BE" bundle create "$REL/backend.bundle" "$BRANCH" > /dev/null 2>&1
git -C "$WEB" bundle create "$REL/web.bundle" "$BRANCH" > /dev/null 2>&1
jq -n --arg at "$STAMP" --arg be "$(git -C "$BE" rev-parse HEAD)" --arg web "$(git -C "$WEB" rev-parse HEAD)" \
  --arg branch "$BRANCH" --arg gates "$gates" --arg by "$(whoami)@$(hostname)" \
  '{created_at: $at, backend: $be, web: $web, branch: $branch, gates: $gates, by: $by}' > "$REL/RELEASE.json"
(cd "$REL" && sha256sum backend.bundle web.bundle RELEASE.json > SHA256SUMS)
log "artefact: $REL"

# 4. Ship and check out exactly these commits.
REMOTE_REL="/root/releases/$(basename "$REL")"
if [[ "$HOST" != local ]]; then
  remote "mkdir -p $REMOTE_REL"
  scp -q -o BatchMode=yes "$REL"/* "$HOST:$REMOTE_REL/" || die "copy to $HOST failed"
else
  REMOTE_REL="$REL"
fi
remote "cd $REMOTE_REL && sha256sum -c --quiet SHA256SUMS" || die "checksums differ on the server"
remote "set -e
  git -C $REMOTE_BE fetch -q $REMOTE_REL/backend.bundle $BRANCH && git -C $REMOTE_BE checkout -q --detach FETCH_HEAD
  git -C $REMOTE_WEB fetch -q $REMOTE_REL/web.bundle $BRANCH && git -C $REMOTE_WEB checkout -q --detach FETCH_HEAD
  test \"\$(git -C $REMOTE_BE rev-parse --short=12 HEAD)\" = $be_sha
  test \"\$(git -C $REMOTE_WEB rev-parse --short=12 HEAD)\" = $web_sha" || die "could not check out $be_sha / $web_sha on the server"

# 5. Deploy (backup, build, migrate, grants, restart, health).
remote "$CTL deploy" || die "predigolctl deploy failed on the server - the previous version: $CTL rollback"

# 6. Smoke tests through the front door.
domain="$(remote "grep -E '^PREDIGOL_DOMAIN=' \${PREDIGOL_ENV_FILE:-/etc/predigol/predigol.env} | cut -d= -f2 | tr -d '\"'")"
smoke() {
  remote "set -e
    C=\"curl -fsS -m 20 --resolve $domain:443:127.0.0.1\"
    CA=\${PREDIGOL_DATA:-/srv/predigol}/caddy/data/caddy/pki/authorities/local/root.crt
    case $domain in *.localhost) C=\"\$C --cacert \$CA\";; esac
    \$C https://$domain/health | jq -e '.status == \"ok\" or .status == \"degraded\"' > /dev/null
    \$C -o /dev/null https://$domain/login
    \$C -D - -o /dev/null https://$domain/login | grep -qi '^strict-transport-security'
    code=\$(\${C/-fsS/-sS} -o /dev/null -w '%{http_code}' https://$domain/api/v1/auth/me); test \"\$code\" = 401
    code=\$(\${C/-fsS/-sS} -o /dev/null -w '%{http_code}' https://$domain/docs); test \"\$code\" = 404"
}
smoke || die "smoke tests failed on https://$domain - roll back with: $CTL rollback"
log "release $be_sha / $web_sha: deployed and smoke-tested on https://$domain"
