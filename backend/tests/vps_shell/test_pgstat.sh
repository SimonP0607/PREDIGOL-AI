#!/usr/bin/env bash
# Tests of pgstat.sh (OPS-001) with the REAL lib.sh and a fake docker that answers by the SQL it is given. No network, no Docker, no production.
# usage: tests/vps_shell/test_pgstat.sh
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$(cd "$HERE/../../deploy/vps/bin" && pwd)   # the script under test: backend/deploy/vps/bin
PASS=0; FAIL=0
ok() { PASS=$((PASS + 1)); echo "ok   $*"; }
no() { FAIL=$((FAIL + 1)); echo "FAIL $*"; }
eq() { if [[ "$1" == "$2" ]]; then ok "$3"; else no "$3: got '$1', expected '$2'"; fi; }
has() { if grep -qF -- "$1" "$T/out"; then ok "$2"; else no "$2: '$1' is not in: $(tr '\n' '|' < "$T/out")"; fi; }
hasnt() { if grep -qF -- "$1" "$T/out"; then no "$2: '$1' is in: $(tr '\n' '|' < "$T/out")"; else ok "$2"; fi; }
sql_has() { if grep -qF -- "$1" "$T/argv" 2> /dev/null; then ok "$2"; else no "$2: '$1' was not sent to psql: $(cat "$T/argv" 2> /dev/null)"; fi; }
sql_hasnt() { if grep -qF -- "$1" "$T/argv" 2> /dev/null; then no "$2: '$1' WAS sent to psql"; else ok "$2"; fi; }

T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin" "$T/data" "$T/etc"
echo 'PREDIGOL_DOMAIN=example.test' > "$T/etc/predigol.env"
cat > "$T/bin/docker" <<'FAKE'
#!/usr/bin/env bash
# every call is recorded; the answer depends on the SQL: FAKE_LIBS is shared_preload_libraries, FAKE_EXT the number of rows in pg_extension
printf '%s\n' "$*" >> "$FAKE_DIR/argv"
all="$*"
case "$all" in
  *"current_setting('shared_preload_libraries')"*) echo "$FAKE_LIBS" ;;
  *"FROM pg_extension WHERE extname = 'pg_stat_statements') THEN"*) if [[ "$FAKE_EXT" == 1 ]]; then echo created; else echo "not created"; fi ;;
  *"SELECT count(*) FROM pg_extension"*) echo "$FAKE_EXT" ;;
  *"auto_explain.log_min_duration"*) echo 5s ;;
  *"SELECT count(*) FROM pg_stat_statements"*) echo 321 ;;
  *"FROM pg_stat_statements WHERE dbid"*) echo "10 | 1200 | 120.0 | 5 | SELECT 1" ;;
esac
exit 0
FAKE
chmod +x "$T/bin/docker"
export FAKE_DIR=$T PATH="$T/bin:$PATH" PREDIGOL_ENV_FILE=$T/etc/predigol.env PREDIGOL_APP_ENV_FILE=$T/etc/app.env PREDIGOL_DATA=$T/data
run() {  # run LIBS EXT args...
  export FAKE_LIBS=$1 FAKE_EXT=$2; shift 2
  rm -f "$T/argv" "$T/out"
  "$SRC/pgstat.sh" "$@" > "$T/out" 2>&1; echo $?
}

# 1. usage
eq "$(run '' 0)" 2 "1 no argument: exit 2"; has "usage: predigolctl pgstat" "1 it prints the usage"
eq "$(run '' 0 nonsense)" 2 "1 an unknown word: exit 2"; [[ ! -e "$T/argv" ]] && ok "1 docker was not called" || no "1 docker was called for bad usage"

# 2. status
eq "$(run 'pg_stat_statements,auto_explain' 1 status)" 0 "2 status with everything in place: exit 0"
has "library: loaded" "2 the library is loaded"; has "extension: created" "2 the extension is created"; has "statements held: 321" "2 it counts the statements"
eq "$(run 'auto_explain' 0 status)" 0 "2 status without the library: still exit 0 (it only reports)"
has "library: NOT loaded" "2 it says the library is not loaded"; has "extension: not created" "2 it says the extension is not created"; hasnt "statements held" "2 it does not read the view that does not exist"
eq "$(run 'pg_stat_statements, auto_explain' 1 status)" 0 "2 a list with a space after the comma is read the same"; has "library: loaded" "2 loaded with spaces in the list"
eq "$(run 'auto_explain, pg_stat_statements' 1 status)" 0 "2 the library second in a list with spaces"; has "library: loaded" "2 loaded when it comes second after a space"
eq "$(run 'auto_explain' 1 status)" 0 "2 extension created but library not loaded (a restart rolled back): exit 0"; has "library: NOT loaded" "2 it says the library is not loaded"; hasnt "statements held" "2 it does not read a view that cannot be read"

# 3. enable
eq "$(run 'auto_explain' 0 enable)" 1 "3 enable before PostgreSQL loaded the library: exit 1"
has "has not started with the compose of OPS-001" "3 it says why"; sql_hasnt "CREATE EXTENSION" "3 no CREATE EXTENSION was sent"
eq "$(run 'pg_stat_statements,auto_explain' 0 enable)" 0 "3 enable with the library loaded: exit 0"
sql_has "CREATE EXTENSION IF NOT EXISTS pg_stat_statements" "3 CREATE EXTENSION IF NOT EXISTS (idempotent)"
eq "$(run 'pg_stat_statements,auto_explain' 1 enable)" 0 "3 enable twice is fine"

# 4. top
eq "$(run 'pg_stat_statements' 1 top 0)" 2 "4 top 0: exit 2"; eq "$(run 'pg_stat_statements' 1 top abc)" 2 "4 top abc: exit 2"
eq "$(run 'pg_stat_statements' 1 top 101)" 2 "4 top 101: exit 2"; eq "$(run 'pg_stat_statements' 1 top '1; DROP TABLE x')" 2 "4 top with SQL in it: exit 2"
[[ ! -e "$T/argv" ]] && ok "4 nothing reached psql for a bad N" || no "4 psql was reached with a bad N"
eq "$(run 'pg_stat_statements' 1 top 5)" 0 "4 top 5: exit 0"
sql_has "LIMIT 5" "4 the limit is the N asked"; sql_has "ORDER BY total_exec_time DESC" "4 ordered by total time"
sql_has "default_transaction_read_only = on" "4 the session is read-only"; sql_has "dbid = (SELECT oid FROM pg_database WHERE datname = current_database())" "4 only this database"
sql_has "left(regexp_replace(query" "4 the query text is cut"; has "SELECT 1" "4 it prints the rows"
eq "$(run 'pg_stat_statements' 1 top)" 0 "4 top without N: exit 0"; sql_has "LIMIT 15" "4 the default is 15"
eq "$(run 'auto_explain' 0 top)" 1 "4 top without the library: exit 1"

# 5. reset
eq "$(run 'auto_explain' 0 reset)" 1 "5 reset without the library: exit 1"; sql_hasnt "pg_stat_statements_reset" "5 nothing was reset"
eq "$(run 'pg_stat_statements' 1 reset)" 0 "5 reset: exit 0"; sql_has "pg_stat_statements_reset()" "5 the counters were emptied"; has "the counters are empty" "5 it says so"

echo "RESULT: $PASS ok, $FAIL failed"
[[ $FAIL -eq 0 ]]