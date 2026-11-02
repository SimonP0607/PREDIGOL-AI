#!/usr/bin/env bash
# Release __REL__: the whole sequence, unattended, so that no step waits for anybody's laptop. It runs the package's own scripts in their order and
# STOPS at the first failure; it never rolls anything back by itself (a roll-back is a decision of the owner and of whoever runs the release).
# Modelled on the UX A1 chain (claude/PLANTILLAS_DESPLIEGUE_UX.md). THERE IS NO WINDOW AND NO HOUR OF THE DAY IN IT (owner's order, 26-oct-2026: every
# finished piece is deployed as soon as it is finished): the chain starts when it is launched. What it waits for is somebody else's work, never a clock.
#   0. refuses unless the lists of hashes check and nothing of an earlier attempt is in the folder (a package built for another state of the server
#      cannot go: step_deploy.sh checks that production still runs the exact commits the package was cut from);
#   1. step_precheck.sh (read-only), again and again until no line is NOT OK; it waits ONLY for what means "somebody else is working" or "the server
#      is not quiet yet" (a lock held, a backup, a PITR run, the maintenance or a deploy running, a heavy job about to start, a long write
#      transaction); anything else it stops for;
#   2. step_backup.sh (the backup, then its restore test): exit 0, and a restore test that is newer than this backup, passed, has no failures and
#      is of THIS dump ("Backup before the first migration with a proven restore": the existence of a file proves nothing);
#   3. lockwatch.sh (read-only) beside the deploy; deploy_with_retries.sh (QUIET_GAP=60), and again while the only reason is "not quiet yet";
#   4. with the deploy at status 0: step_smoke.sh; step_roles.sh only if the smoke test passed (idempotent; the role of the automatic roll-back
#      that only the database superuser can create, and its proof); step_verify.sh and post_deploy_reads.sh (read-only);
#   5. starts followups.sh (10, 30 and 60 minutes after the deploy, read-only).
# The most it waits for somebody else is MAX_WAIT_MIN minutes of waiting (180 by default), in the precheck and again before the deploy; then it
# stops, with nothing moved. The keys of the AI are NOT here: step_keys.sh is the owner's, with hidden prompts (no key ever travels through a chat,
# a log or a command line). Every line of its own goes to chain.log; the outcome to chain.status. Started detached (systemd-run) by op_bg.sh.
set -uo pipefail
D=/root/releases/__STAMP__
REL=__REL__
MAX_WAIT_MIN=${MAX_WAIT_MIN:-180}
LOG=$D/chain.log
cd "$D" || exit 9
exec 7> "$D/chain.lock"
flock -n 7 || { echo "REFUSED: another chain runs"; exit 1; }
[ ! -e "$D/chain.status" ] || { echo "REFUSED: chain.status exists ($(cat "$D/chain.status")): look at what it says before running again"; exit 1; }
log() { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG"; }
stop() { log "STOP: $1"; echo "stopped: $1" > "$D/chain.status"; exit 1; }
# minutes of waiting since $1 (a value of bash's SECONDS), not an hour of the day
waited_since() { echo $(((SECONDS - $1) / 60)); }
STAMP=${D##*/}
OWN_UNITS="$REL-chain.service $REL-lockwatch.service $REL-followups.service"
log "chain start: package $STAMP, no window: it goes on as soon as the server lets it (at most $MAX_WAIT_MIN minutes of waiting for somebody else)"
{ sha256sum -c --quiet SHA256SUMS && sha256sum -c --quiet SCRIPTS.sha256; } || stop "the lists of hashes do not check"
[ ! -e "$D/deploy.started" ] || stop "deploy.started exists: an earlier attempt began to deploy; decide by hand what is the state"

# 1. the precheck, read-only, until nothing is NOT OK; only the lines that mean "wait" are waited for
WAITABLE='^NOT OK: (lock [a-z-]+ is HELD|processes of a deploy|detached units of the plans|the server is not quiet|the quiet check could not look)'
T_PRE=$SECONDS
i=0
while :; do
  i=$((i + 1))
  log "precheck $i"
  IGNORE_UNITS="$OWN_UNITS" QUIET_GAP=60 "$D/step_precheck.sh" < /dev/null > "$D/precheck.log" 2>&1
  prc=$?
  grep -q '^PRECHECK: ' "$D/precheck.log" || stop "the precheck did not reach its last line (status $prc): precheck.log"
  bad=$(grep '^NOT OK' "$D/precheck.log" || true)
  if [ -z "$bad" ]; then
    [ "$prc" -eq 0 ] || stop "the precheck ended with status $prc and no line NOT OK: precheck.log"
    log "precheck $i: every line OK"
    break
  fi
  fatal=$(grep -vE "$WAITABLE" <<< "$bad" || true)
  if [ -n "$fatal" ]; then
    while IFS= read -r l; do log "precheck: $l"; done <<< "$fatal"
    stop "the precheck has lines NOT OK that waiting does not fix (precheck.log)"
  fi
  [ "$(waited_since "$T_PRE")" -lt "$MAX_WAIT_MIN" ] || stop "the precheck has waited $(waited_since "$T_PRE") minutes (the most: $MAX_WAIT_MIN) for somebody else and still waits: $(head -n 1 <<< "$bad")"
  while IFS= read -r l; do log "precheck $i: $l"; done <<< "$bad"
  cp "$D/precheck.log" "$D/precheck.$i.log"
  log "precheck $i: it only waits (somebody else is working, or the server is not quiet yet); again in 60 s (precheck.$i.log keeps what it saw)"
  sleep 60
done

# 2. the backup and its restore test
log "step_backup.sh start: the backup, then its restore test (about 25 minutes)"
"$D/step_backup.sh" < /dev/null > "$D/step_backup.out" 2>&1
rc=$?
log "step_backup.sh status $rc"
[ "$rc" -eq 0 ] || stop "step_backup.sh exit $rc (backup.log, restore.log, step_backup.out)"
RT=/srv/predigol/state/restore-test.json
[ -f "$RT" ] || stop "no restore-test.json"
[ "$(stat -c %Y "$RT")" -ge "$(date -d "$(cat "$D/backup.started")" +%s)" ] || stop "restore-test.json is older than this backup"
jq -e '.passed == true and (.failures | length) == 0 and (.dump | endswith("-'"$REL"'"))' "$RT" > /dev/null \
  || stop "the restore test did not pass, or it tested another dump than this release's (restore-test.json)"
grep -q "revision $(jq -r .revision_before "$D/RELEASE.json" | cut -c1-4)\$" "$D/backup.log" || stop "the backup was not taken at the revision the release starts from (backup.log)"
log "backup and restore test OK: $(jq -c 'del(.counts) | del(.tables)' "$RT" 2> /dev/null | head -c 600)"

# 3. the deploy
if systemd-run --unit="$REL-lockwatch" --collect --quiet --working-directory="$D" /bin/bash -c "'$D/lockwatch.sh' 3000 < /dev/null > /dev/null 2>&1"; then
  log "lockwatch started"
else
  log "lockwatch could not start (read-only aid; the deploy does not depend on it)"
fi
T_DEPLOY=$SECONDS
while :; do
  log "deploy_with_retries.sh start"
  "$D/deploy_with_retries.sh" < /dev/null >> "$D/deploy_with_retries.log" 2>&1
  rc=$?
  log "deploy_with_retries.sh status $rc"
  if [ "$rc" -eq 2 ] && tail -n 1 "$D/deploy_with_retries.log" | grep -q "still not quiet"; then
    if [ "$(waited_since "$T_DEPLOY")" -ge "$MAX_WAIT_MIN" ]; then
      log "the deploy has waited $(waited_since "$T_DEPLOY") minutes (the most: $MAX_WAIT_MIN) for the server to be quiet; nothing moved"
      break
    fi
    log "still not quiet after the tries (nothing moved): again in 60 s"
    sleep 60
    continue
  fi
  break
done
if [ "$rc" -ne 0 ]; then
  if [ -e "$D/deploy.started" ]; then
    log "the deploy moved something and did not end well. predigolctl prints 'roll back with: predigolctl rollback', but that command reads the LAST line of deploys.log, which a failed deploy does not write: it would go back to the release BEFORE the one production ran. versions.env still names the release production ran, so 'predigolctl up' starts it again (the database stays at the new revision; the migrations are additive)"
    stop "deploy status $rc AFTER deploy.started: the way back is 'predigolctl up', NOT 'predigolctl rollback' (chain.log, deploy.log)"
  fi
  stop "deploy status $rc, nothing moved (deploy_with_retries.log)"
fi
log "deployed: finished $(cat "$D/deploy.finished" 2> /dev/null || echo '?')"

# 4. after the deploy
"$D/step_smoke.sh" < /dev/null > "$D/smoke.log" 2>&1
s=$?
log "step_smoke.sh status $s"
if [ ! -x "$D/step_roles.sh" ]; then
  r=0
  log "step_roles.sh: this release carries none (it is an extra of the release, see deploy/release/extras)"
elif [ "$s" -eq 0 ]; then
  "$D/step_roles.sh" < /dev/null > "$D/roles.log" 2>&1
  r=$?
  log "step_roles.sh status $r: $(head -c 200 "$D/roles.status" 2> /dev/null | tr '\n' ' ')"
else
  r=skipped
  log "step_roles.sh skipped: the smoke test did not pass"
fi
"$D/step_verify.sh" < /dev/null > "$D/verify.log" 2>&1
v=$?
VN=$(grep -c '^NOT OK' "$D/verify.log" 2> /dev/null || true)
log "step_verify.sh status $v, lines NOT OK: ${VN:-?}"
"$D/post_deploy_reads.sh" < /dev/null > "$D/post_reads.log" 2>&1
p=$?
log "post_deploy_reads.sh status $p"
echo "deployed; smoke=$s roles=$r verify=$v verify_not_ok=${VN:-?} post_reads=$p" > "$D/chain.status"

# 5. the follow-ups, detached (read-only)
if systemd-run --unit="$REL-followups" --collect --quiet --working-directory="$D" /bin/bash -c "'$D/followups.sh' < /dev/null > '$D/followups.out' 2>&1"; then
  log "followups started (10, 30 and 60 minutes after the deploy)"
else
  log "followups could not start: run step_followup.sh by hand"
fi
log "chain end"
[ "$s" = 0 ] && [ "$r" = 0 ] && [ "$v" = 0 ] && [ "${VN:-1}" = 0 ] && [ "$p" = 0 ]
