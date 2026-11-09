#!/usr/bin/env bash
# CI-015. Lints the migrations a pull request ADDS: renders each new revision to SQL without a database (`alembic upgrade <down>:<rev> --sql`)
# and runs squawk on it. Only added files are read: the 120+ revisions already in production were written under their own rules (lock_timeout, small
# tables, additive changes) and are not re-judged. Usage: lint_new_migrations.sh <base-sha> [<head-sha>]. Exit 0 = no findings; 1 = findings;
# 2 = a new revision could not be rendered offline (it must be, so that it can be read).
set -euo pipefail
base="${1:?base sha}"
head="${2:-HEAD}"
cd "$(dirname "$0")/.."
export FBI_DATABASE_URL="${FBI_DATABASE_URL:-postgresql+psycopg://lint@localhost/lint}" # alembic's env.py needs a URL; offline mode never connects
out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT
mapfile -t added < <(git diff --diff-filter=A --name-only "$base" "$head" -- 'migrations/versions/*.py')
if [[ ${#added[@]} -eq 0 ]]; then echo "No new migrations in this change."; exit 0; fi
status=0
for file in "${added[@]}"; do
  file="${file#backend/}"
  rev="$(sed -n 's/^revision = "\(.*\)"$/\1/p' "$file" | head -n 1)"
  down="$(sed -n 's/^down_revision = "\(.*\)"$/\1/p' "$file" | head -n 1)"
  [[ -n "$rev" && -n "$down" ]] || { echo "::error file=backend/$file::no revision/down_revision found"; exit 2; }
  echo "== $file ($down -> $rev)"
  if ! alembic upgrade "$down:$rev" --sql > "$out/$rev.sql" 2> "$out/$rev.err"; then
    cat "$out/$rev.err"; echo "::error file=backend/$file::cannot be rendered to SQL offline"; exit 2
  fi
  squawk "$out/$rev.sql" || status=1
done
exit $status
