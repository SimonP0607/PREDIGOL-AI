#!/usr/bin/env bash
# Docker's disk use, kept bounded: old application images and the build cache, after every deploy (predigolctl deploy
# calls this) and by hand. Every deploy builds a backend and a web image of ~1 GB each and nothing removed the old ones.
#
#   bin/prune.sh [--dry-run]                          images and build cache
#   bin/prune.sh --volumes NAME[,NAME...] --confirm   ORPHAN volumes, named one by one (see below)
#
# Images (predigol-backend, predigol-web, predigol-postgres) - KEPT, whatever their age:
#   - the ones any container, running or stopped, uses;
#   - the versions state/versions.env names (what `predigolctl up` starts after a reboot);
#   - the versions of the last three deploys, new and previous (state/deploys.log): `predigolctl rollback` needs the
#     previous ones to still be there;
#   - the newest PRUNE_KEEP_IMAGES (3) of each application repository and the newest 2 postgres images.
# Everything else of those repositories is removed, then untagged leftovers (dangling) older than 24 h, then the BuildKit
# cache beyond PRUNE_BUILD_CACHE (4GB). Base images (caddy, python, bun...) are not touched: the next build needs them.
# A prune never runs while a deploy, a rollback or an import holds state/deploy.lock.
#
# What a prune leaves behind: state/prune.json, {"at": "<UTC ISO>", "freed_bytes": N, "items": ["image predigol-web:abc",
# "volume xyz", "build cache beyond 4GB", ...], ...}. The storage report reads those three and the console shows them as "Last
# prune"; the other keys are detail for people. freed_bytes is the drop in USED disk (df) around the prune, so it is
# approximate (other processes write meanwhile) and never below 0. A --dry-run writes nothing. If the record cannot be written
# prune.sh says so, leaves no temporary file and exits 1 (what was cleaned stays cleaned).
#
# Volumes are never pruned by rule. --volumes removes exactly the volumes NAMED, and only when each one is (1) not used by
# any container, (2) not attached to this compose project, and (3) the newest dump has a VERIFIED copy off the server less
# than 26 h old: what is lost is lost for good. The owner has seen the list (README, "Podar Docker").
# Exit 0 done (or nothing to do), 1 refused or failed.
set -Eeuo pipefail
# shellcheck source=bin/lib.sh
. "$(dirname "$0")/lib.sh"

DRY=0; CONFIRM=0; VOLUMES=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY=1; shift ;;
    --confirm) CONFIRM=1; shift ;;
    --volumes) VOLUMES="${2:-}"; shift 2 ;;
    *) echo "usage: $0 [--dry-run] | --volumes NAME[,NAME...] --confirm" >&2; exit 2 ;;
  esac
done
exclusive prune 7
# predigolctl deploy calls this itself, holding deploy.lock (and having just recorded the deploy): that one proceeds.
if [[ -z "${PREDIGOL_PRUNE_AFTER_DEPLOY:-}" ]] && deploying; then
  log "prune: a deploy, rollback or import is running - left for later"; exit 0
fi

disk_now() { df -Pk "$PREDIGOL_DATA" | awk 'NR==2 {gsub("%", "", $5); print $3, $5}'; }  # "<used KiB> <used %>", from ONE df call
disk_used() { disk_now | cut -d' ' -f2; }
docker_used() { docker system df --format '{{.Type}} {{.Size}} (reclaimable {{.Reclaimable}})' 2> /dev/null | paste -sd';' - || true; }
json_list() { printf '%s\n' "$@" | jq -R . | jq -sc 'map(select(length > 0))'; }  # the non-empty arguments as a JSON array

removed=(); gone_volumes=(); extras=()
before_kb=0; before_disk=0; before_docker=""
record_prune() {  # state/prune.json, written whole and moved into place (the storage report may be reading it). 1: it could not, and says so
  local after_kb after_disk freed after_docker="${1:-}" tmp="$STATE/prune.json.tmp.$$"
  read -r after_kb after_disk <<< "$(disk_now)"
  freed=$(( (before_kb - after_kb) * 1024 )); (( freed > 0 )) || freed=0
  # (mv -T: the record is a file or nothing; if something else sits there, mv would put the new file INSIDE it and the old record would stay)
  if jq -n --arg at "$(date -u +%FT%TZ)" --argjson freed "$freed" \
    --argjson images "$(json_list "${removed[@]:-}")" --argjson volumes "$(json_list "${gone_volumes[@]:-}")" \
    --argjson extras "$(json_list "${extras[@]:-}")" --argjson bp "$before_disk" --argjson ap "$after_disk" \
    --arg bd "$before_docker" --arg ad "$after_docker" \
    '{at: $at, freed_bytes: $freed, items: (($images | map("image " + .)) + ($volumes | map("volume " + .)) + $extras),
      images_removed: $images, volumes_removed: $volumes, disk_used_percent: {before: $bp, after: $ap}}
     + (if $bd == "" and $ad == "" then {} else {docker_before: $bd, docker_after: $ad} end)' > "$tmp" \
    && mv -fT "$tmp" "$STATE/prune.json"; then
    return 0
  fi
  rm -f "$tmp"
  log "prune: could not write $STATE/prune.json (what was cleaned stays cleaned; the record of it is missing)"
  return 1
}
note_reclaimed() {  # note_reclaimed "<output of docker ... prune>" "<item>": the item goes in the record when Docker reported reclaiming something.
  # Docker ends with "Total reclaimed space: 1.2GB" (images) or "Total:  1.2GB" (build cache); 0B means nothing went.
  if grep -Eq '^Total( reclaimed space)?:[[:space:]]*[0-9.]+[A-Za-z]*[[:space:]]*$' <<< "$1" \
    && ! grep -Eq '^Total( reclaimed space)?:[[:space:]]*0B[[:space:]]*$' <<< "$1"; then
    extras+=("$2")
  fi
}

# ---- Volumes: only the ones named, only when it is safe -------------------------------------------------------------
if [[ -n "$VOLUMES" ]]; then
  (( CONFIRM )) || { log "prune: --volumes needs --confirm"; exit 1; }
  newest="$(ls -t "$DB_BACKUPS"/predigol-*.json 2> /dev/null | head -n 1 || true)"
  verified="$(jq -r '.offsite.verified_at // empty' "$newest" 2> /dev/null || true)"
  fresh=0
  if [[ -n "$verified" ]] && (( $(date +%s) - $(date -d "$verified" +%s) < 26 * 3600 )); then fresh=1; fi
  (( fresh )) || { log "prune: refused - the newest dump has no verified copy off the server from the last 26 h (nothing was removed)"; exit 1; }
  IFS=',' read -r -a names <<< "$VOLUMES"
  for v in "${names[@]}"; do
    docker volume inspect "$v" > /dev/null 2>&1 || { log "prune: refused - no such volume $v"; exit 1; }
    [[ -z "$(docker ps -a -q --filter "volume=$v")" ]] || { log "prune: refused - $v is used by a container"; exit 1; }
    [[ "$(docker volume inspect -f '{{index .Labels "com.docker.compose.project"}}' "$v")" != predigol ]] \
      || { log "prune: refused - $v belongs to the predigol compose project"; exit 1; }
  done
  read -r before_kb before_disk <<< "$(disk_now)"; rc=0
  for v in "${names[@]}"; do
    if (( DRY )); then log "prune: would remove volume $v"
    elif docker volume rm "$v" > /dev/null 2>&1; then gone_volumes+=("$v"); log "prune: removed volume $v"
    else log "prune: could not remove volume $v"; rc=1; fi
  done
  (( DRY )) || record_prune || rc=1
  log "prune: disk $(disk_used)% used"
  exit "$rc"
fi

# ---- Images ------------------------------------------------------------------------------------------------------------
declare -A keep=()
mark() { [[ -n "${1:-}" && "${1#*:}" != "" && "${1#*:}" != "<none>" ]] && keep["$1"]=1 || true; }
while read -r img; do mark "$img"; done < <(docker ps -a --format '{{.Image}}')
mark "predigol-backend:${PREDIGOL_VERSION:-}"; mark "predigol-web:${PREDIGOL_WEB_VERSION:-}"; mark "predigol-postgres:${PREDIGOL_PG_VERSION:-}"
if [[ -r "$STATE/deploys.log" ]]; then
  while IFS=$'\t' read -r _ be web old_be old_web _; do
    mark "predigol-backend:$be"; mark "predigol-web:$web"
    [[ "$old_be" != none && "$old_be" != - ]] && { mark "predigol-backend:$old_be"; mark "predigol-web:$old_web"; }
  done < <(tail -n 3 "$STATE/deploys.log")
fi
newest_tags() {  # newest_tags REPO N: the N newest tags of REPO, by creation time (UTC, from inspect: never a local-time string)
  local repo="$1" n="$2" t
  docker image ls "$repo" --format '{{.Tag}}' | grep -v '^<none>$' | while read -r t; do
    printf '%s %s\n' "$(docker image inspect -f '{{.Created}}' "$repo:$t")" "$t"
  done | sort -r | head -n "$n" | cut -d' ' -f2
}
for repo in predigol-backend predigol-web; do
  while read -r t; do mark "$repo:$t"; done < <(newest_tags "$repo" "${PRUNE_KEEP_IMAGES:-3}")
done
while read -r t; do mark "predigol-postgres:$t"; done < <(newest_tags predigol-postgres 2)

read -r before_kb before_disk <<< "$(disk_now)"; before_docker="$(docker_used)"
for repo in predigol-backend predigol-web predigol-postgres; do
  while read -r t; do
    [[ -n "$t" && "$t" != "<none>" ]] || continue
    [[ -z "${keep[$repo:$t]:-}" ]] || continue
    if (( DRY )); then log "prune: would remove image $repo:$t"
    elif docker image rm "$repo:$t" > /dev/null 2>&1; then log "prune: removed image $repo:$t"; removed+=("$repo:$t")
    else log "prune: kept $repo:$t (Docker refused: in use)"; fi
  done < <(docker image ls "$repo" --format '{{.Tag}}')
done
if (( DRY )); then
  log "prune: dry run - dangling images and the build cache not touched; disk ${before_disk}% used"
  exit 0
fi
note_reclaimed "$(docker image prune -f --filter "until=24h" 2> /dev/null || true)" "dangling images older than 24 h"
# --reserved-space is the flag since buildx 0.17 (Docker 27); --keep-storage, its old name, is still accepted as a deprecated alias.
cache_out="$(docker builder prune -f --reserved-space "${PRUNE_BUILD_CACHE:-4GB}" 2> /dev/null)" \
  || cache_out="$(docker builder prune -f --keep-storage "${PRUNE_BUILD_CACHE:-4GB}" 2> /dev/null)" \
  || { cache_out=""; log "prune: the build cache could not be pruned (the images were)"; }
note_reclaimed "$cache_out" "build cache beyond ${PRUNE_BUILD_CACHE:-4GB}"
rec=0; record_prune "$(docker_used)" || rec=1
log "prune: ${#removed[@]} image(s) removed; disk ${before_disk}% -> $(disk_used)% used"
exit "$rec"
