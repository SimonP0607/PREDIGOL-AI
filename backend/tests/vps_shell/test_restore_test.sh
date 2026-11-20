#!/usr/bin/env bash
# Tests of restore-test.sh (OPS-011) with the REAL lib.sh and a fake docker that plays the throwaway server: the key tables' counts are
# checked between the smaller and the larger of the two counts the backup recorded. No network, no Docker, no production.
# usage: tests/vps_shell/test_restore_test.sh
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$(cd "$HERE/../../deploy/vps/bin" && pwd)   # the script under test: backend/deploy/vps/bin
PASS=0; FAIL=0
ok() { PASS=$((PASS + 1)); echo "ok   $*"; }
no() { FAIL=$((FAIL + 1)); echo "FAIL $*"; }
eq() { if [[ "$1" == "$2" ]]; then ok "$3"; else no "$3: got '$1', expected '$2'"; fi; }
has() { if grep -qF -- "$1" "$T/out"; then ok "$2"; else no "$2: '$1' is not in: $(tr '\n' '|' < "$T/out")"; fi; }
hasnt() { if grep -qF -- "$1" "$T/out"; then no "$2: '$1' is in: $(tr '\n' '|' < "$T/out")"; else ok "$2"; fi; }

T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin" "$T/data/backups/db" "$T/etc"
echo 'PREDIGOL_DOMAIN=example.test' > "$T/etc/predigol.env"
cat > "$T/bin/docker" <<'FAKE'
#!/usr/bin/env bash
# The throwaway server: it starts, restores and answers the count of each table from $FAKE_DIR/counts ("table n" lines).
printf '%s\n' "$*" >> "$FAKE_DIR/argv"
all="$*"
case "$all" in
  *"pg_database_size"*) echo 1000 ;;
  *"logs "*) echo "PostgreSQL init process complete; ready for start up." ;;
  *"SELECT version_num FROM public.alembic_version"*) echo 0168 ;;
  *"SELECT count(*) FROM "*) t="${all##*SELECT count(*) FROM }"; awk -v t="$t" '$1 == t {print $2}' "$FAKE_DIR/counts" ;;
esac
exit 0
FAKE
cat > "$T/bin/df" <<'FAKE'
#!/usr/bin/env bash
printf 'Filesystem 1024-blocks Used Available Capacity Mounted\n/dev/x 100000000 1 99999999 1%% /\n'
FAKE
cat > "$T/bin/openssl" <<'FAKE'
#!/usr/bin/env bash
echo 0123456789abcdef0123456789abcdef
FAKE
chmod +x "$T/bin/docker" "$T/bin/df" "$T/bin/openssl"
export FAKE_DIR=$T PATH="$T/bin:$PATH" PREDIGOL_ENV_FILE=$T/etc/predigol.env PREDIGOL_APP_ENV_FILE=$T/etc/app.env PREDIGOL_DATA=$T/data
DUMPS=$T/data/backups/db
NAME=predigol-20261119T231300Z
echo "a dump" > "$DUMPS/$NAME.dump"
SHA=$(sha256sum "$DUMPS/$NAME.dump" | cut -d' ' -f1)
run() {  # run BEFORE AFTER RESTORED [BEFORE2 AFTER2 RESTORED2]: core.fixture_events (and core.fixtures) counted at the start and end of the dump
  jq -n --arg sha "$SHA" --argjson b "$1" --argjson a "$2" --argjson b2 "${4:-10}" --argjson a2 "${5:-10}" \
    '{sha256: $sha, alembic_revision: "0168", counts_before: {"core.fixture_events": $b, "core.fixtures": $b2},
      counts_after: {"core.fixture_events": $a, "core.fixtures": $a2}}' > "$DUMPS/$NAME.json"
  printf 'core.fixture_events %s\ncore.fixtures %s\n' "$3" "${6:-10}" > "$T/counts"
  rm -f "$T/argv" "$T/out" "$T/data/state/restore-test.json"
  "$SRC/restore-test.sh" "$NAME" > "$T/out" 2>&1; echo $?
}
passed() { jq -r .passed "$T/data/state/restore-test.json"; }

# 1. a table that grew while the dump ran: the restored count between the two
eq "$(run 100 105 103)" 0 "1 grew 100 -> 105, restored 103: exit 0"; eq "$(passed)" true "1 the result says passed"
has "core.fixture_events: 103 rows" "1 it logs the count"; has "restore-test PASSED" "1 it says PASSED"
eq "$(run 100 105 100)" 0 "1 restored at the lower bound: exit 0"
eq "$(run 100 105 105)" 0 "1 restored at the upper bound: exit 0"
eq "$(run 100 105 106)" 1 "1 one row more than the end of the dump: exit 1"; has "expected between 100 and 105" "1 it says the bounds"
eq "$(passed)" false "1 the result says failed"
eq "$(run 100 105 99)" 1 "1 one row fewer than the start: exit 1"

# 2. OPS-011: a table that LOST rows while the dump ran (19 Nov 2026, chain 20261119T2313Z-auto-5af94de)
eq "$(run 3279639 3279638 3279639)" 0 "2 lost one row, restored the count of the start: exit 0"
hasnt "expected between 3279639 and 3279638" "2 the inverted bounds no longer fail it"; eq "$(passed)" true "2 the result says passed"
eq "$(run 3279639 3279638 3279638)" 0 "2 restored the count of the end: exit 0"
eq "$(run 3279639 3279638 3279640)" 1 "2 above the larger of the two: exit 1"; has "expected between 3279638 and 3279639" "2 it says the bounds, smaller first"
eq "$(run 3279639 3279638 3279637)" 1 "2 below the smaller of the two: exit 1"
eq "$(run 50 40 45)" 0 "2 a bigger loss (50 -> 40), restored in between: exit 0"

# 3. the same count at both ends, and every table checked (one bad table among good ones fails the test)
eq "$(run 7 7 7)" 0 "3 unchanged and restored exactly: exit 0"
eq "$(run 7 7 8)" 1 "3 unchanged and one more restored: exit 1"
eq "$(run 100 105 103 10 10 11)" 1 "3 a second table out of bounds fails it too"; has "core.fixtures: 11 rows, expected between 10 and 10" "3 it names the second table"
eq "$(run 100 105 103 12 10 11)" 0 "3 the second table lost rows and is restored in between: exit 0"

# 4. what the fix does not change: the throwaway server only, never the live one, and it is removed
run 100 105 103 > /dev/null
if grep -q -- "--network none" "$T/argv"; then ok "4 the throwaway server has no network"; else no "4 no --network none"; fi
if grep -q -- "rm -f -v predigol-restore-test" "$T/argv"; then ok "4 the throwaway server is removed with its volume"; else no "4 not removed"; fi

echo "RESULT: $PASS ok, $FAIL failed"
[[ $FAIL -eq 0 ]]
