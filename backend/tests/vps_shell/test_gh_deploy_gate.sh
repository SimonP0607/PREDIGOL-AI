#!/usr/bin/env bash
# Tests of predigol-gh-deploy (plan CI/CD C4): the forced command of the GitHub deploy key. Fakes for git, systemd-run and systemctl. No network, no root.
# usage: tests/vps_shell/test_gh_deploy_gate.sh [path/to/predigol-gh-deploy]
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
GATE=${1:-$HERE/../../deploy/release/templates/gate/predigol-gh-deploy}
PASS=0; FAIL=0
ok() { PASS=$((PASS + 1)); echo "ok   $*"; }
no() { FAIL=$((FAIL + 1)); echo "FAIL $*"; }
eq() { if [[ "$1" == "$2" ]]; then ok "$3"; else no "$3: got '$1', expected '$2'"; fi; }

T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin" "$T/rel" "$T/kits"
cat > "$T/bin/git" <<'FAKE'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_DIR/git.argv"
[[ "$*" == *rev-parse* ]] && echo "abc123def456"
exit 0
FAKE
cat > "$T/bin/systemd-run" <<'FAKE'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_DIR/systemd-run.argv"
exit "${FAKE_SYSTEMD_RC:-0}"
FAKE
cat > "$T/bin/systemctl" <<'FAKE'
#!/usr/bin/env bash
[[ "${FAKE_CHAIN_ACTIVE:-0}" == 1 ]] && echo "other-chain.service loaded active running"
exit 0
FAKE
chmod +x "$T/bin/"*
export FAKE_DIR=$T PATH="$T/bin:$PATH" PREDIGOL_RELEASES="$T/rel" PREDIGOL_GH_LOG="$T/log" PREDIGOL_APP_DIR=/opt/predigol SSH_CLIENT="203.0.113.9 5555 22"

# run the gate as sshd would: $1 = the original command, $2 = a file for stdin; leaves the output in $OUT and the status in $RC
gate() { local in=${2:-/dev/null}; OUT=$(SSH_ORIGINAL_COMMAND="$1" bash "$GATE" < "$in" 2>&1); RC=$?; }

# a kit the way ship.sh --gate sends it: a flat tar
make_kit() { # <name> [release]
  local n=$1 r=${2:-t1} d="$T/kits/$1"
  rm -rf "$d"; mkdir -p "$d"
  printf '{"release":"%s"}\n' "$r" > "$d/RELEASE.json"
  printf '#!/usr/bin/env bash\nD=/root/releases/%s\nexit 0\n' "$n" > "$d/chain.sh"
  printf '#!/usr/bin/env bash\necho "PRECHECK: every line OK"\n' > "$d/step_precheck.sh"
  printf '#!/usr/bin/env bash\nexit 0\n' > "$d/step_deploy.sh"
  (cd "$d" && sha256sum RELEASE.json > SHA256SUMS && sha256sum chain.sh step_precheck.sh step_deploy.sh > SCRIPTS.sha256)
  (cd "$d" && tar -cf "$T/kits/$n.tar" *)
}
N1=20261103T1000Z-t1
N2=20261103T1010Z-t2

# 1. what is refused
gate ""; eq "$RC" 126 "1 no command (a shell) is refused"
gate "bash"; eq "$RC" 126 "1 bash is refused"
gate "ls /root"; eq "$RC" 126 "1 ls is refused"
gate "receive $N1; id"; eq "$RC" 126 "1 a semicolon is refused"
gate 'receive $(id)'; eq "$RC" 126 "1 a command substitution is refused"
gate "status $N1 | cat"; eq "$RC" 126 "1 a pipe is refused"
gate "git-upload-pack '/etc'"; eq "$RC" 126 "1 git-upload-pack of any other folder is refused"
gate "git-upload-pack '/opt/predigol/backend/../../etc'"; eq "$RC" 126 "1 git-upload-pack with .. is refused"
gate "git -C /root rev-parse --short=12 HEAD"; eq "$RC" 126 "1 git -C of another folder is refused"
gate "receive ../x"; eq "$RC" 126 "1 a kit name with .. is refused"
gate "receive foo"; eq "$RC" 126 "1 a kit name without a stamp is refused"
gate "start"; eq "$RC" 126 "1 start without a name is refused"
gate "$(printf 'x%.0s' {1..250})"; eq "$RC" 126 "1 a very long command is refused"
grep -q "REFUSED.*client=203.0.113.9" "$T/log" && ok "1 refusals are logged with the client" || no "1 refusals not logged"

# 2. what production runs, and the read-only fetch
gate "git -C /opt/predigol/backend rev-parse --short=12 HEAD"; eq "$OUT" abc123def456 "2 the backend commit is read"
gate "git -C /opt/predigol/web rev-parse --short=12 HEAD"; eq "$OUT" abc123def456 "2 the web commit is read"
gate "git-upload-pack '/opt/predigol/backend'"; eq "$RC" 0 "2 upload-pack of the backend checkout is served"
gate "git-upload-pack /opt/predigol/web"; eq "$RC" 0 "2 upload-pack of the web checkout is served (unquoted)"
grep -q '^upload-pack /opt/predigol/backend$' "$T/git.argv" && ok "2 git upload-pack ran on the backend folder" || no "2 upload-pack backend not run"
grep -q '^upload-pack /opt/predigol/web$' "$T/git.argv" && ok "2 git upload-pack ran on the web folder" || no "2 upload-pack web not run"

# 3. receive
make_kit "$N1"
gate "receive $N1" "$T/kits/$N1.tar"; eq "$RC" 0 "3 a good kit is received"
[[ -d "$T/rel/$N1" ]] && ok "3 the folder exists" || no "3 no folder"
[[ -f "$T/rel/$N1/.gh-received" ]] && ok "3 the mark of this door is there" || no "3 no mark"
eq "$(stat -c %a "$T/rel/$N1")" 700 "3 the folder is 700"
[[ -x "$T/rel/$N1/chain.sh" ]] && ok "3 the scripts are executable" || no "3 chain.sh not executable"
gate "receive $N1" "$T/kits/$N1.tar"; eq "$RC" 1 "3 the same name again is refused"
ls "$T/rel" | grep -q '^\.incoming' && no "3 temp folder left behind" || ok "3 no temp folder left behind"

make_kit "$N2"
cp "$T/kits/$N2.tar" "$T/good2.tar"
# 3b. a kit whose scripts were changed after the hashes were made
mkdir -p "$T/bad" && rm -rf "$T/bad"/* && cp "$T/kits/$N2"/* "$T/bad/" && echo 'rm -rf /' >> "$T/bad/step_deploy.sh" && (cd "$T/bad" && tar -cf "$T/bad.tar" *)
gate "receive $N2" "$T/bad.tar"; eq "$RC" 1 "3 a kit whose script differs from its hash is refused"
[[ ! -e "$T/rel/$N2" ]] && ok "3 nothing was installed" || no "3 a bad kit was installed"
# a kit built for another folder
make_kit 20261103T1020Z-other; mv "$T/kits/20261103T1020Z-other.tar" "$T/other.tar"
gate "receive $N2" "$T/other.tar"; eq "$RC" 1 "3 a kit built for another folder is refused"
# a tar with a directory, a link, a .. name
mkdir -p "$T/d1" && rm -rf "$T/d1"/* && cp "$T/kits/$N2"/* "$T/d1/" && mkdir "$T/d1/sub" && (cd "$T/d1" && tar -cf "$T/d1.tar" *)
gate "receive $N2" "$T/d1.tar"; eq "$RC" 1 "3 a tar with a directory is refused"
mkdir -p "$T/d2" && rm -rf "$T/d2"/* && cp "$T/kits/$N2"/* "$T/d2/" && ln -s /etc/passwd "$T/d2/link" && (cd "$T/d2" && tar -cf "$T/d2.tar" *)
gate "receive $N2" "$T/d2.tar"; eq "$RC" 1 "3 a tar with a symbolic link is refused"
(cd "$T/kits/$N2" && tar -cf "$T/d3.tar" --transform='s,^chain.sh$,../chain.sh,' *)
gate "receive $N2" "$T/d3.tar"; eq "$RC" 1 "3 a tar with a .. name is refused"
echo "not a tar" > "$T/d4.tar"; gate "receive $N2" "$T/d4.tar"; eq "$RC" 1 "3 something that is not a tar is refused"
: > "$T/empty.tar"; gate "receive $N2" "$T/empty.tar"; eq "$RC" 1 "3 an empty stream is refused"
PREDIGOL_GH_MAX_BYTES=2000 gate "receive $N2" "$T/good2.tar"; eq "$RC" 1 "3 a kit over the size limit is refused"
[[ ! -e "$T/rel/$N2" ]] && ok "3 none of the refused kits was installed" || no "3 a refused kit was installed"

# 4. precheck
gate "precheck $N1"; eq "$RC" 0 "4 the precheck of a received kit runs"
[[ "$OUT" == *"PRECHECK: every line OK"* ]] && ok "4 its output comes back" || no "4 no output: $OUT"
mkdir -p "$T/rel/$N2"; gate "precheck $N2"; eq "$RC" 126 "4 a folder that this door did not receive is refused"
gate "precheck 20261103T1030Z-nope"; eq "$RC" 1 "4 a kit that does not exist fails"
rm -rf "$T/rel/$N2"

# 5. start
gate "start $N1"; eq "$RC" 0 "5 start of a received kit"
grep -q -- '--unit=t1-chain' "$T/systemd-run.argv" && ok "5 systemd-run got the unit t1-chain" || no "5 wrong unit: $(cat "$T/systemd-run.argv" 2> /dev/null)"
grep -q "$T/rel/$N1/chain.sh" "$T/systemd-run.argv" && ok "5 it runs that kit's chain.sh" || no "5 wrong chain.sh"
echo "2026 chain start" > "$T/rel/$N1/chain.log"
gate "start $N1"; eq "$RC" 126 "5 a kit that already started is not started again"
make_kit "$N2"; gate "receive $N2" "$T/kits/$N2.tar"
FAKE_CHAIN_ACTIVE=1 gate "start $N2"; eq "$RC" 126 "5 start is refused while another chain runs"
FAKE_SYSTEMD_RC=1 gate "start $N2"; eq "$RC" 1 "5 a failing systemd-run is a failure"
mkdir -p "$T/rel/20261103T1040Z-x"; gate "start 20261103T1040Z-x"; eq "$RC" 126 "5 a folder not received here is not started"
rm -rf "$T/rel/20261103T1040Z-x"

# 6. status
gate "status $N2"; eq "$RC" 0 "6 status of a kit not started"; [[ "$OUT" == "STATE: not-started"* ]] && ok "6 not-started" || no "6 $OUT"
gate "status $N1"; [[ "$OUT" == "STATE: running"* ]] && ok "6 running (a log and no status)" || no "6 $OUT"
echo "deployed; smoke=0 roles=0 verify=0 verify_not_ok=0 post_reads=0" > "$T/rel/$N1/chain.status"
gate "status $N1"; [[ "$OUT" == "STATE: deployed"* ]] && ok "6 deployed" || no "6 $OUT"
echo "stopped: the precheck has lines NOT OK" > "$T/rel/$N1/chain.status"
gate "status $N1"; [[ "$OUT" == "STATE: stopped"* ]] && ok "6 stopped" || no "6 $OUT"
[[ "$OUT" == *"2026 chain start"* ]] && ok "6 the tail of chain.log comes with it" || no "6 no tail"

# 7. discard
gate "discard $N1"; eq "$RC" 126 "7 a started kit is not discarded"
gate "discard $N2"; eq "$RC" 0 "7 a kit that never started is discarded"
[[ ! -e "$T/rel/$N2" ]] && ok "7 its folder is gone" || no "7 still there"
[[ -d "$T/rel/$N1" ]] && ok "7 the started one is untouched" || no "7 the started kit vanished"

# 8. the log
grep -q "OK client=203.0.113.9 receive $N1" "$T/log" && ok "8 the receive is logged" || no "8 receive not logged"
grep -q "OK client=203.0.113.9 start $N1" "$T/log" && ok "8 the start is logged" || no "8 start not logged"

echo "RESULT: $PASS ok, $FAIL failed"
[[ $FAIL -eq 0 ]]