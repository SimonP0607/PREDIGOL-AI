#!/usr/bin/env bash
# Tests of config-baseline.sh (security plan S3, alert 32) with the REAL lib.sh and alerts_checks.sh, on temporary files. No network, no Docker, no production.
# usage: tests/vps_shell/test_config_baseline.sh
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$(cd "$HERE/../../deploy/vps/bin" && pwd)   # the scripts under test: backend/deploy/vps/bin
PASS=0; FAIL=0
ok() { PASS=$((PASS + 1)); echo "ok   $*"; }
no() { FAIL=$((FAIL + 1)); echo "FAIL $*"; }
eq() { if [[ "$1" == "$2" ]]; then ok "$3"; else no "$3: got '$1', expected '$2'"; fi; }
has() { if grep -qF -- "$1" "$T/out"; then ok "$2"; else no "$2: '$1' is not in: $(tr '\n' '|' < "$T/out")"; fi; }
hasnt() { if grep -qF -- "$1" "$T/out"; then no "$2: '$1' is in: $(tr '\n' '|' < "$T/out")"; else ok "$2"; fi; }

T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
export PREDIGOL_ENV_FILE=$T/etc/predigol.env PREDIGOL_APP_ENV_FILE=$T/etc/app.env PREDIGOL_DATA=$T/data
export VPS_DIR=$T/vps PREDIGOL_ETC=$T/etc SSHD_DIR=$T/ssh
STATE=$T/data/state; BASE=$STATE/config.sha256
mkdir -p "$T/etc" "$VPS_DIR/systemd" "$SSHD_DIR/sshd_config.d"
echo 'PREDIGOL_DOMAIN=example.test' > "$PREDIGOL_ENV_FILE"
echo 'FBI_SECRET=hunter2-should-never-appear' > "$PREDIGOL_APP_ENV_FILE"
echo 'caddy a' > "$VPS_DIR/Caddyfile"; echo 'compose a' > "$VPS_DIR/docker-compose.yml"
echo '[Unit]' > "$VPS_DIR/systemd/predigol-a.service"; echo '[Timer]' > "$VPS_DIR/systemd/predigol-a.timer"
echo 'PasswordAuthentication no' > "$SSHD_DIR/sshd_config"; echo 'Port 22' > "$SSHD_DIR/sshd_config.d/50-x.conf"
run() { "$SRC/config-baseline.sh" "$@" > "$T/out" 2>&1; echo $?; }
sum() { sha256sum "$BASE" 2> /dev/null | cut -d' ' -f1; }
nothing_secret() {  # nothing_secret CASE: neither the output nor the baseline holds a value of a file, and the output holds no hash
  if grep -q 'hunter2' "$T/out" "$BASE" 2> /dev/null; then no "$1 A VALUE OF A FILE IS IN THE OUTPUT OR THE BASELINE"; else ok "$1 no value of any file in the output or the baseline"; fi
  if grep -qE '[0-9a-f]{64}' "$T/out"; then no "$1 the output holds a hash"; else ok "$1 the output holds no hash"; fi
}

# 1. there is no baseline yet
eq "$(run --status)" 2 "1 --status without a baseline: exit 2"
has "there is no baseline yet" "1 it says so"
has "predigolctl config-baseline" "1 it says how to take it"
[[ ! -e "$BASE" ]] && ok "1 --status wrote nothing" || no "1 --status wrote a baseline"

# 2. the first one
eq "$(run)" 0 "2 taking it for the first time: exit 0"
has "taken for the first time (8 files)" "2 it says it is the first, and how many files it holds"
eq "$(wc -l < "$BASE" | tr -d ' ')" 8 "2 the baseline holds 8 hashes: Caddyfile, compose, the two env files, sshd_config and its drop-in, a unit and a timer"
nothing_secret "2"
has "config-baseline:" "2 the line says who speaks"

# 3. --status right after: nothing differs, and it changes nothing
before=$(sum)
eq "$(run --status)" 0 "3 --status when nothing changed: exit 0"
has "Nothing differs from it now" "3 it says nothing differs"
nothing_secret "3"
has "taken 20" "3 it says when the baseline was taken (a UTC date)"
eq "$(sum)" "$before" "3 --status left the baseline as it was"

# 4. a changed file: named by --status, which still changes nothing
echo 'caddy b' > "$VPS_DIR/Caddyfile"
eq "$(run --status)" 1 "4 --status with a changed Caddyfile: exit 1"
has "These differ from it now: Caddyfile" "4 it names the file"
eq "$(sum)" "$before" "4 --status did not move the baseline"
nothing_secret "4"

# 5. several changes at once, of every kind: changed, removed, added; the names only
echo 'FBI_SECRET=other-hunter3-value' > "$PREDIGOL_APP_ENV_FILE"; echo 'PasswordAuthentication yes' > "$SSHD_DIR/sshd_config"
rm -f "$VPS_DIR/systemd/predigol-a.service"; echo '[Timer]' > "$VPS_DIR/systemd/predigol-b.timer"; echo 'Port 2222' > "$SSHD_DIR/sshd_config.d/50-x.conf"
eq "$(run --status)" 1 "5 --status with many changes: exit 1"
for name in Caddyfile app.env sshd_config 50-x.conf predigol-a.service predigol-b.timer; do has "$name" "5 it names $name"; done
hasnt "docker-compose.yml" "5 it does not name a file that did not change"
nothing_secret "5"

# 6. taking it again moves the baseline and says over which files
eq "$(run)" 0 "6 taking it again: exit 0"
has "It moved over:" "6 it says it moved"
for name in Caddyfile app.env sshd_config predigol-a.service predigol-b.timer; do has "$name" "6 it names $name"; done
[[ "$(sum)" != "$before" ]] && ok "6 the baseline is now another one" || no "6 the baseline did not move"
eq "$(wc -l < "$BASE" | tr -d ' ')" 8 "6 and holds the 8 files that exist now"
nothing_secret "6"
eq "$(run --status)" 0 "6 --status after taking it: nothing differs"

# 7. taking it when nothing changed says so
after=$(sum)
eq "$(run)" 0 "7 taking it with nothing changed: exit 0"
has "nothing had changed since the last one" "7 it says nothing changed"
nothing_secret "7"
eq "$(sum)" "$after" "7 the same baseline"

# 8. a wrong argument touches nothing
eq "$(run --bogus)" 2 "8 an argument it does not know: exit 2"
has "usage: config-baseline.sh [--status]" "8 it says how to use it"
eq "$(sum)" "$after" "8 the baseline is as it was"

# 9. a baseline that cannot be written is an error, and the old one stays
mkdir "$BASE.tmp"
echo 'caddy c' > "$VPS_DIR/Caddyfile"
eq "$(run)" 1 "9 it cannot write: exit 1"
has "could not write" "9 it says so"
eq "$(sum)" "$after" "9 the old baseline is intact"
rmdir "$BASE.tmp"
eq "$(run)" 0 "9 once it can, it works"

# 10. a deploy holds the lock while it calls this script: the script does not wait for it and does not take it for "a deploy is running" (it would hold, not move)
echo 'caddy d' > "$VPS_DIR/Caddyfile"
exec 9> "$STATE/deploy.lock"; flock -n 9
eq "$(run)" 0 "10 with the deploy lock held (as a deploy calls it): exit 0"
has "It moved over: Caddyfile" "10 it still says what it moved over"
exec 9>&-

# 11. the last name of the list is not a file (no timer, no unit: the glob matches nothing): the rest is still hashed
rm -f "$VPS_DIR"/systemd/*.timer
echo 'caddy e' > "$VPS_DIR/Caddyfile"
eq "$(run)" 0 "11 no timer in the list: exit 0"
eq "$(wc -l < "$BASE" | tr -d ' ')" 6 "11 the 6 files that exist (both timers are gone)"
eq "$(run --status)" 0 "11 --status agrees"

# 12. nothing to read at all besides the env file: still a baseline, of what there is
rm -rf "$VPS_DIR" "$SSHD_DIR"
eq "$(run)" 0 "12 almost nothing on the server: exit 0"
has "files)" "12 it says how many files"
eq "$(wc -l < "$BASE" | tr -d ' ')" 2 "12 the two env files"

echo; echo "RESULT: $PASS ok, $FAIL failed"; exit $(( FAIL > 0 ))
