#!/usr/bin/env bash
# The LAST copy of the old machine (the laptop), for the server's `predigolctl import` - cut-over step 3 (README
# "Corte"). Run in WSL from the backend checkout, with the worker STOPPED (one worker at a time, ever).
#
#   deploy/cutover/export.sh [--out ~/cutover] [--force]
#
# Writes <out>/<stamp>/: db.dump (pg_dump -Fc, made INSIDE the postgres container and copied out - nothing streams
# through docker.exe), raw.tar (the RAW store), manifest.json (row count of every table before and after the
# dump, which tables changed meanwhile, revision, sha256 of both files) and SHA256SUMS. Changes nothing.
# Exit 0 done, 1 refused or failed.
set -Eeuo pipefail
OUT="${HOME}/cutover"
FORCE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    --force) FORCE=1; shift ;;
    *) echo "usage: $0 [--out DIR] [--force]" >&2; exit 2 ;;
  esac
done
REPO="${FBI_REPO:-$(cd "$(dirname "$0")/../.." && pwd)}"
PY="${FBI_PYTHON:-$REPO/.venv/bin/python}"
CONTAINER="${FBI_PG_CONTAINER:-fbi-postgres}"
DB_USER="${FBI_PG_USER:-fbi}"
log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*"; }
# Docker in WSL: Docker Desktop's docker.exe works without the WSL integration; a `docker` that is only the
# "could not be found in this WSL 2 distro" stub does not (the laptop's first real cut-over, 9 Oct 2026).
if command -v docker > /dev/null && docker version > /dev/null 2>&1; then D="$(command -v docker)"
else D="$(command -v docker.exe || true)"; fi
[[ -n "$D" ]] || { log "REFUSED: neither a working docker nor docker.exe"; exit 1; }
dexec() { "$D" exec "$CONTAINER" sh -c "$1" < /dev/null; }

cd "$REPO"
# 1. The worker must be stopped: no process, and its last heartbeat older than two minutes.
if pgrep -f "apps.worker" > /dev/null && (( ! FORCE )); then log "REFUSED: the worker is running here - stop it first"; exit 1; fi
beat="$(PYTHONPATH=src:. "$PY" - <<'PY'
import psycopg
from fbi.core.config import settings
with psycopg.connect(settings.database.psycopg_url) as c:
    r = c.execute("SELECT coalesce(extract(epoch FROM now() - max(last_beat_at))::int, 999999) FROM raw.worker_heartbeats WHERE stopped_at IS NULL").fetchone()
    print(r[0] if r else 999999)
PY
)"
if (( beat < 120 )) && (( ! FORCE )); then log "REFUSED: a worker beat ${beat}s ago - stop it and wait two minutes"; exit 1; fi
# From here the worker belongs to the server: scripts/dev-up will not start it on this machine again (one worker,
# ever). Going back (README §4, vuelta atrás) is deleting this marker.
RUN_DIR="${FBI_RUN_DIR:-$HOME/.fbi}"
mkdir -p "$RUN_DIR"
printf 'since %s (cut-over export)\n' "$(date -u +%FT%TZ)" > "$RUN_DIR/worker-moved-to-server"
log "marker $RUN_DIR/worker-moved-to-server written: scripts/dev-up no longer starts a worker here"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="$OUT/$STAMP"
mkdir -p "$DEST"
counts() {
  PYTHONPATH=src:. "$PY" - "$1" <<'PY'
import json, sys
import psycopg
from fbi.core.config import settings
with psycopg.connect(settings.database.psycopg_url) as conn:
    conn.read_only = True
    rev = conn.execute("SELECT version_num FROM public.alembic_version").fetchone()[0]
    tables = conn.execute(
        "SELECT n.nspname, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE c.relkind IN ('r','p') AND NOT c.relispartition AND n.nspname NOT IN ('pg_catalog','information_schema') "
        "AND n.nspname NOT LIKE 'pg_t%' ORDER BY 1, 2").fetchall()
    counts = {f"{s}.{t}": conn.execute(f'SELECT count(*) FROM "{s}"."{t}"').fetchone()[0] for s, t in tables}
json.dump({"revision": rev, "counts": counts}, open(sys.argv[1], "w"))
PY
}
log "export $STAMP: counting every table"
counts "$DEST/.before.json"
log "dumping inside $CONTAINER (detached)"
NAME="cutover-$STAMP.dump"
dexec "rm -f /tmp/cut.rc /tmp/cut.err; nohup sh -c 'pg_dump -U $DB_USER -Fc -f /tmp/$NAME fbi 2>/tmp/cut.err; echo \$? > /tmp/cut.rc' >/dev/null 2>&1 &"
started=$SECONDS
while :; do
  sleep 5
  # (no rc file yet is not an error: under pipefail a failing cat would end the script here)
  rc="$(dexec "cat /tmp/cut.rc 2>/dev/null || true" | tr -d '\r\n ')"
  [[ -n "$rc" ]] && break
  (( SECONDS - started > 7200 )) && { log "FAILED: the dump did not finish in 2 h"; exit 1; }
done
[[ "$rc" == 0 ]] || { log "FAILED: pg_dump exit $rc: $(dexec 'head -c 400 /tmp/cut.err')"; exit 1; }
seconds=$(( SECONDS - started ))
counts "$DEST/.after.json"
inside="$(dexec "sha256sum /tmp/$NAME" | awk '{print $1}')"
dest_native="$DEST/db.dump"; [[ "$D" == *.exe ]] && dest_native="$(wslpath -w "$DEST/db.dump")"
"$D" cp "$CONTAINER:/tmp/$NAME" "$dest_native" < /dev/null
dexec "rm -f /tmp/$NAME"
dump_sha="$(sha256sum "$DEST/db.dump" | awk '{print $1}')"
[[ "$dump_sha" == "$inside" ]] || { log "FAILED: the copied dump's sha256 differs from the container's"; exit 1; }
log "dump: $(stat -c %s "$DEST/db.dump") bytes in ${seconds}s, sha256 ${dump_sha:0:16}"

RAW_DIR="$("$PY" -c 'from fbi.core.config import settings; print(settings.runtime.raw_store_dir)')"
[[ "$RAW_DIR" = /* ]] || RAW_DIR="$REPO/$RAW_DIR"
log "RAW store: $RAW_DIR"
tar -cf "$DEST/raw.tar" -C "$RAW_DIR" .
raw_files="$(find "$RAW_DIR" -type f | wc -l)"; raw_bytes="$(du -sb "$RAW_DIR" | cut -f1)"
raw_sha="$(sha256sum "$DEST/raw.tar" | awk '{print $1}')"

"$PY" - "$DEST" "$dump_sha" "$raw_sha" "$raw_files" "$raw_bytes" <<'PY'
import json, os, sys
dest, dump_sha, raw_sha, raw_files, raw_bytes = sys.argv[1:6]
before = json.load(open(f"{dest}/.before.json")); after = json.load(open(f"{dest}/.after.json"))
changed = sorted(t for t in after["counts"] if before["counts"].get(t) != after["counts"][t])
manifest = {
    "kind": "predigol-cutover-export", "created_at": os.path.basename(dest),
    "alembic_revision": after["revision"], "rows_total": sum(after["counts"].values()),
    "tables": {t: {"rows": n} for t, n in after["counts"].items()},
    "counts_before": before["counts"], "changed_during_dump": changed,
    "files": {"db.dump": {"sha256": dump_sha, "bytes": os.path.getsize(f"{dest}/db.dump")},
              "raw.tar": {"sha256": raw_sha, "bytes": os.path.getsize(f"{dest}/raw.tar")}},
    "raw_store": {"files": int(raw_files), "bytes": int(raw_bytes)},
}
json.dump(manifest, open(f"{dest}/manifest.json", "w"), indent=1)
os.remove(f"{dest}/.before.json"); os.remove(f"{dest}/.after.json")
print(f"manifest: revision {manifest['alembic_revision']}, {len(manifest['tables'])} tables, "
      f"{manifest['rows_total']} rows, changed during the dump: {changed or 'none'}")
PY
(cd "$DEST" && sha256sum db.dump raw.tar manifest.json > SHA256SUMS)
log "export done: $DEST (copy the whole folder to the server: /root/import/$STAMP)"
