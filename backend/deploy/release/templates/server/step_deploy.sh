#!/usr/bin/env bash
# Release __REL__: put EXACTLY the release commits of the released parts on the server and run predigolctl deploy (pre-deploy backup, build,
# migrations if any, grants from the checkout, restart of what changed, health). Before anything moves: hashes, clean checkouts, the quiet check
# (no long write transaction, none of the worker's long jobs, no backup / PITR / maintenance / restore test running or about to start), the bundles
# against the commits they must give, and the model-code guard in mode stop (plan UX, section 4). There is no hour of the day in it: the owner
# dropped the deployment windows on 26-oct-2026, and what keeps the deploy from cutting a job is the lock of the deploy, the quiet check and the
# heavy-job check (quiet.sh). Right before predigolctl runs, the day's picks and decisions are read with a cutoff (day_digest.sh): step_verify.sh
# reads the same cutoff after and the two lines must be equal.
# Exit statuses of its own: 1 a check failed, 2 not quiet (a writer, a long job of the worker, or a heavy job of the server), 4 the guard stops,
# 5 the guard could not look. Anything else is predigolctl's. In 1, 2, 4 and 5 nothing moved. Adapted from the F14 step_deploy.sh.
set -Eeuo pipefail
D=/root/releases/__STAMP__
BE_DIR=/opt/predigol/backend
WEB_DIR=/opt/predigol/web
PARTS="__PARTS__"
BE_FROM=__BE_FROM__
WEB_FROM=__WEB_FROM__
BE_WANT=__BE_WANT__
WEB_WANT=__WEB_WANT__
GUARD_MODE=stop
GUARD="$D/model_code_guard.py"
releases() { case " $PARTS " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }
cd "$D"
sha256sum -c --quiet SHA256SUMS
for dir in "$BE_DIR" "$WEB_DIR"; do
  [ -z "$(git -C "$dir" status --porcelain --untracked-files=no)" ] || { echo "$dir has local changes"; exit 1; }
done
test "$(git -C "$BE_DIR" rev-parse --short=12 HEAD)" = "$BE_FROM" || { echo "backend checkout is not $BE_FROM"; exit 1; }
test "$(git -C "$WEB_DIR" rev-parse --short=12 HEAD)" = "$WEB_FROM" || { echo "web checkout is not $WEB_FROM"; exit 1; }
echo "before: backend $(git -C $BE_DIR rev-parse --short=12 HEAD), web $(git -C $WEB_DIR rev-parse --short=12 HEAD); parts released: $PARTS"
[ -f "$D/quiet.sh" ] || { echo "quiet.sh is not in the package: not starting"; exit 1; }
# shellcheck source=/dev/null
. "$D/quiet.sh"
rc=0
quiet_check || rc=$?
[ "$rc" -eq 0 ] || { echo "not starting: the server is not quiet, or the check could not look (status $rc): the lines above say who or why"; exit 2; }
# a backup, a PITR run, the maintenance or a restore test that runs or starts within HEAVY_LOOKAHEAD_MIN minutes would meet the deploy halfway
rc=0
heavy_check || rc=$?
[ "$rc" -eq 0 ] || { echo "not starting: the server is not quiet, a heavy job (backup, PITR, maintenance, restore test) runs or is about to start, or the check could not look (status $rc): the lines above say which"; exit 2; }
# the bundles are checked against the commits they must give, and read into FETCH_HEAD: nothing is checked out yet
if releases backend; then
  git -C "$BE_DIR" bundle verify "$D/backend___REL__.bundle" > /dev/null
  git -C "$BE_DIR" fetch -q "$D/backend___REL__.bundle" refs/release/backend-__REL__
  test "$(git -C "$BE_DIR" rev-parse --short=12 FETCH_HEAD)" = "$BE_WANT" || { echo "the backend bundle does not give $BE_WANT"; exit 1; }
  AFTER=FETCH_HEAD
else
  test "$BE_WANT" = "$BE_FROM" || { echo "the backend is not released but BE_WANT differs from BE_FROM"; exit 1; }
  AFTER=HEAD
fi
if releases web; then
  git -C "$WEB_DIR" bundle verify "$D/web___REL__.bundle" > /dev/null
  git -C "$WEB_DIR" fetch -q "$D/web___REL__.bundle" refs/release/web-__REL__
  test "$(git -C "$WEB_DIR" rev-parse --short=12 FETCH_HEAD)" = "$WEB_WANT" || { echo "the web bundle does not give $WEB_WANT"; exit 1; }
else
  test "$WEB_WANT" = "$WEB_FROM" || { echo "the web is not released but WEB_WANT differs from WEB_FROM"; exit 1; }
fi
# the model code, still before anything moves: what the tool reads from the two trees must be what the package says it read when it was built
test "$(python3 "$GUARD" fingerprint git=HEAD --git-dir "$BE_DIR")" = "$(jq -r .model_code.before RELEASE.json)"
test "$(python3 "$GUARD" fingerprint git=$AFTER --git-dir "$BE_DIR")" = "$(jq -r .model_code.after RELEASE.json)"
rc=0
python3 "$GUARD" check --before git=HEAD --after git=$AFTER --git-dir "$BE_DIR" --mode "$GUARD_MODE" 2>&1 | tee "$D/model_code_guard.out" || rc=$?
case "$rc" in
  0) echo "model-code guard: the release goes on (mode $GUARD_MODE)" ;;
  4) echo "model-code guard: THE RELEASE STOPS (mode $GUARD_MODE): the model code changes and the ledger does not put it in force"; exit 4 ;;
  *) echo "model-code guard: it could not look (status $rc): not starting"; exit 5 ;;
esac
# the day's picks and decisions, before: the same cutoff is read again by step_verify.sh after the deploy
# ten minutes in the past: a transaction that began before the cutoff and commits after the "before" read would otherwise show up in the "after" read;
# a run longer than that (pick_pipeline took 14 minutes on 27-oct-2026) still can, so the rows of this first read are kept one by one as well: step_verify.sh
# then tells an ADDED row (a run that started before the cutoff and committed after this read) from a row that CHANGED or went
CUTOFF=$(date -u -d '10 minutes ago' +%FT%TZ)
echo "$CUTOFF" > "$D/day_digest.cutoff"
"$D/day_digest.sh" "$CUTOFF" > "$D/day_digest.before" || { echo "the day digest could not be read: not starting"; exit 1; }
"$D/day_digest.sh" --rows "$CUTOFF" > "$D/day_digest.rows.before" || { echo "the rows of the day digest could not be read: not starting"; exit 1; }
echo "day digest before (cutoff $CUTOFF): $(cat "$D/day_digest.before"); $(wc -l < "$D/day_digest.rows.before") row line(s) kept"
if releases backend; then git -C "$BE_DIR" checkout -q --detach FETCH_HEAD; fi
if releases web; then
  git -C "$WEB_DIR" checkout -q --detach FETCH_HEAD || {
    echo "the web checkout failed: putting the backend back at $BE_FROM (nothing else moved)"
    git -C "$BE_DIR" checkout -q --detach "$BE_FROM"
    exit 1
  }
fi
test "$(git -C "$BE_DIR" rev-parse --short=12 HEAD)" = "$BE_WANT"
test "$(git -C "$WEB_DIR" rev-parse --short=12 HEAD)" = "$WEB_WANT"
echo "after: backend $(git -C $BE_DIR rev-parse HEAD), web $(git -C $WEB_DIR rev-parse HEAD)"
date -u +%FT%TZ > "$D/deploy.started"
rc=0
predigolctl deploy > "$D/deploy.log" 2>&1 || rc=$?
date -u +%FT%TZ > "$D/deploy.finished"
echo "deploy rc=$rc"
exit "$rc"
