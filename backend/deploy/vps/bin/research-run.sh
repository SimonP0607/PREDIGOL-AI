#!/usr/bin/env bash
# The weekly research V2 (and any experiment listed in fbi/research/launcher.py) OUTSIDE the worker (plan RP-1.6, finding H30):
# predigol-research.timer, Monday 04:20 Bogotá. The launcher runs in the operations container, one experiment at a time (database lock),
# under a ceiling of memory and of time, outside match hours, and leaves its row in the book of runs (job experiment_run).
# It runs only when the research loop says it is due (new model code, new dataset or four weeks old) and never while it is frozen.
#
#   bin/research-run.sh                       research V2 if it is due
#   bin/research-run.sh --dry-run             say what it would do
#   bin/research-run.sh --force               run even if it is not due (a freeze still stops it)
#   bin/research-run.sh --allow-match-hours   the owner's order to run while a match is on
# Exit status: the launcher's (0 done or not due, 1 failed, 3 refused by the lock or match hours).
set -Eeuo pipefail
# shellcheck source=bin/lib.sh
. "$(dirname "$0")/lib.sh"
exclusive research

JOB=research_v2
trap 'log "research run FAILED"; notify "la investigación semanal (research_v2) FALLÓ: mira el libro de ejecuciones (experiment_run)"' ERR
rc=0
ops python -m scripts.experiment_run "$JOB" "$@" | tee "$STATE/research.log" || rc=$?
trap - ERR
if [[ $rc -eq 3 ]]; then log "research run refused (another experiment, or match hours): it tries again next Monday"; exit 0; fi
[[ $rc -eq 0 ]] || { log "research run failed (exit $rc)"; notify "la investigación semanal (research_v2) FALLÓ (salida $rc)"; exit "$rc"; }
log "research run done"
