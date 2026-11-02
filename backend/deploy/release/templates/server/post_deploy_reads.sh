#!/usr/bin/env bash
# After the deploy, the read-only commands of the release: the promotion ledger of the model code (expect "1 of 2", as since 24 Oct: this release
# does not touch the model code), Gate A as the ledger sees it today (a verdict that writes nothing without --record: on the first day it can only
# be PENDIENTE POR TIEMPO REAL) and the LAB probe's status (no call to any provider: what is missing, by NAME, and where each gate stands).
# Each command runs in the ops container as the database owner (run_cmd.sh), its output in <name>.out and its exit status in <name>.err.
# Each is judged: a status outside the ones the command documents, a Python traceback or no output at all is a NOT OK line and the exit status
# of this script (it used to exit 0 whatever happened, so chain.status said "post_reads=0" even when a read had crashed).
D=${D:-/root/releases/__STAMP__}
cd "$D" || exit 9
BAD=0
judge() { # <name> <the statuses its command may end with>
  local name=$1 ok=$2 st
  st=$(grep '^exit=' "$name.err" 2> /dev/null | tail -n 1 | cut -d= -f2)
  if grep -q 'Traceback (most recent call last)' "$name.err" "$name.out" 2> /dev/null; then BAD=$((BAD + 1)); echo "NOT OK: $name printed a Python traceback"
  elif [ ! -s "$name.out" ]; then BAD=$((BAD + 1)); echo "NOT OK: $name gave no output (exit status ${st:-?})"
  else
    case " $ok " in
      *" ${st:-?} "*) echo "OK: $name ended with status $st (accepted: $ok)" ;;
      *) BAD=$((BAD + 1)); echo "NOT OK: $name ended with status ${st:-?} (accepted: $ok)" ;;
    esac
  fi
}
echo "===== post_trace: python -m scripts.promotion_trace show  ($(date -u +%FT%TZ))"
./run_cmd.sh post_trace scripts.promotion_trace show < /dev/null
tail -n 3 post_trace.err; head -n 60 post_trace.out
judge post_trace "0"
echo
echo "===== post_gate: python -m scripts.ia_gate evaluate  (Gate A today; no --record: nothing is written)"
./run_cmd.sh post_gate scripts.ia_gate evaluate < /dev/null
tail -n 3 post_gate.err; head -n 90 post_gate.out
# 0 PASA, 1 NO PASA, 3 pending (the first day: PENDIENTE POR TIEMPO REAL); 2 is "could not run"
judge post_gate "0 1 3"
echo
echo "===== post_probe: python -m scripts.ia_probe status  (no call to any provider)"
./run_cmd.sh post_probe scripts.ia_probe status < /dev/null
tail -n 3 post_probe.err; head -n 80 post_probe.out
# 0 ready, 2 something is missing, by name (until the LAB key is in the server: expected today)
judge post_probe "0 2"
echo; echo "done $(date -u +%FT%TZ): $BAD read(s) NOT OK"
[ "$BAD" -eq 0 ]
