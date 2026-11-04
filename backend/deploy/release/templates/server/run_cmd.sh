#!/usr/bin/env bash
# usage: run_cmd.sh <name> <module> <arguments ...>: one backend command in the ops container; <name>.out / <name>.err beside it (exit status last).
D=/root/releases/__STAMP__
name=$1; module=$2; shift 2
cd "$D" || exit 9
rm -f "$name.out" "$name.err"
date -u > "$name.err"
./ops.sh python -m "$module" "$@" > "$name.out" 2>> "$name.err"
echo "exit=$?" >> "$name.err"
date -u >> "$name.err"
