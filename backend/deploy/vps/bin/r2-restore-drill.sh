#!/usr/bin/env bash
# The off-server restore drill, on a machine that is NOT the server - the OWNER'S (it holds the age private key): the newest
# dump of a tier is downloaded from R2, proven to be the file that was uploaded, decrypted, and restored into a throwaway
# PostgreSQL container with no network; the schema revision and the key tables' counts are checked against the manifest the
# backup wrote. Every phase is timed: the report is the minutes of the recovery plan's RTO, measured. Nothing is uploaded,
# nothing on the server is touched, and the throwaway container and its files are removed at the end.
#
#   r2-restore-drill.sh R2_ENV AGE_KEY [DUMP_NAME] [--tier daily|weekly|monthly] [--report FILE] [--keep]
#                       [--ca-cert FILE] [--jobs N] [--save-encrypted DIR]
#
# Needs docker, rclone, age, jq and tar on this machine. R2_ENV has what the server's r2.env has (R2_ACCOUNT_ID, R2_ACCESS_KEY_ID,
# R2_SECRET_ACCESS_KEY, R2_BUCKET; R2_ENDPOINT only for a rehearsal's stand-in) - a token that can only READ is enough.
# AGE_KEY is the private key file (AGE-SECRET-KEY-...), which never leaves this machine.
# --save-encrypted DIR keeps the downloaded dump (still encrypted, its hash proven) and its manifest in DIR: that is the file for
# the monthly copy on the owner's external disk. The plain dump never leaves the throwaway container.
# The dump goes into the container as a tar stream, never as a bind mount, so any docker works - the Windows one reached from WSL too.
# Exit 0 passed, 1 failed, 2 usage.
set -Eeuo pipefail
usage() { sed -n '2,/^# Exit 0/p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }

TIER=daily; REPORT=""; KEEP=0; JOBS=""; SAVE_DIR=""; positional=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tier) TIER="${2:-}"; shift 2 ;;
    --report) REPORT="${2:-}"; shift 2 ;;
    --keep) KEEP=1; shift ;;
    --ca-cert) export RCLONE_CA_CERT="${2:-}"; shift 2 ;;
    --jobs) JOBS="${2:-}"; shift 2 ;;
    --save-encrypted) SAVE_DIR="${2:-}"; [[ -n "$SAVE_DIR" ]] || usage; shift 2 ;;
    -h | --help) usage ;;
    *) positional+=("$1"); shift ;;
  esac
done
(( ${#positional[@]} >= 2 && ${#positional[@]} <= 3 )) || usage
ENV_FILE="${positional[0]}"; KEY="${positional[1]}"; NAME_ARG="${positional[2]:-}"
case "$TIER" in daily | weekly | monthly) ;; *) usage ;; esac
[[ -f "$ENV_FILE" && -f "$KEY" ]] || { echo "drill: $ENV_FILE or $KEY not found" >&2; exit 2; }
for tool in docker rclone age jq tar sha256sum; do command -v "$tool" > /dev/null || { echo "drill: $tool is required" >&2; exit 2; }; done
# shellcheck disable=SC1090
. <(sed -e '1s/^\xEF\xBB\xBF//' -e 's/\r$//' "$ENV_FILE")
for v in R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY R2_BUCKET; do [[ -n "${!v:-}" ]] || { echo "drill: $v is missing in $ENV_FILE" >&2; exit 2; }; done
ENDPOINT="${R2_ENDPOINT:-https://${R2_ACCOUNT_ID:?R2_ACCOUNT_ID or R2_ENDPOINT in $ENV_FILE}.r2.cloudflarestorage.com}"
[[ -n "$JOBS" ]] || JOBS="$(( $(nproc) > 8 ? 8 : $(nproc) ))"

work="$(mktemp -d)"; box="predigol-r2-drill"
# -v: the postgres image's data folder is an anonymous volume; without it every drill left its restored copy behind.
cleanup() { if (( KEEP )); then echo "drill: --keep: container $box and $work left in place"; else docker rm -f -v "$box" > /dev/null 2>&1 || true; rm -rf "$work"; fi; }
trap cleanup EXIT
export RCLONE_CONFIG_DRILL_TYPE=s3 RCLONE_CONFIG_DRILL_PROVIDER=Cloudflare RCLONE_CONFIG_DRILL_ENV_AUTH=false \
  RCLONE_CONFIG_DRILL_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" RCLONE_CONFIG_DRILL_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" \
  RCLONE_CONFIG_DRILL_ENDPOINT="$ENDPOINT" RCLONE_CONFIG_DRILL_NO_CHECK_BUCKET=true
SRC="drill:$R2_BUCKET/dumps/$TIER"
now() { date +%s; }
fail() { echo "drill FAILED: $*"; exit 1; }

t0="$(now)"
name="${NAME_ARG:-$(rclone lsf "$SRC/" --include 'predigol-*.dump.age' | sort | tail -1)}"
name="${name%.dump.age}"
[[ -n "$name" ]] || fail "no dump in $SRC/"
echo "drill: $name  (tier $TIER, bucket $R2_BUCKET)"

# 1. Download. The manifest first: it names the hash the encrypted file must have.
rclone copyto "$SRC/$name.json" "$work/$name.json"
rclone copyto --s3-chunk-size 32M --transfers 4 "$SRC/$name.dump.age" "$work/$name.dump.age"
t_download="$(now)"
age_bytes="$(stat -c %s "$work/$name.dump.age")"
want_age_sha="$(jq -r '.offsite.age_sha256 // empty' "$work/$name.json")"
if [[ -n "$want_age_sha" ]]; then
  [[ "$(sha256sum "$work/$name.dump.age" | cut -d' ' -f1)" == "$want_age_sha" ]] || fail "the downloaded file is not the one the server uploaded (hash of the encrypted file)"
  echo "drill: downloaded $age_bytes bytes in $(( t_download - t0 ))s; hash of the encrypted file matches the upload"
else
  echo "drill: downloaded $age_bytes bytes in $(( t_download - t0 ))s (this manifest has no hash of the encrypted file: an older dump)"
fi
if [[ -n "$SAVE_DIR" ]]; then  # the encrypted file is safe to keep; the plain one is not, and never leaves the container
  { mkdir -p "$SAVE_DIR" && cp "$work/$name.dump.age" "$work/$name.json" "$SAVE_DIR/"; } || fail "could not save the encrypted dump in $SAVE_DIR"
  echo "drill: the encrypted dump and its manifest are in $SAVE_DIR"
fi

# 2. Decrypt with the private key, and prove the plain dump is the one pg_dump wrote.
age -d -i "$KEY" -o "$work/$name.dump" "$work/$name.dump.age" || fail "the private key does not open this dump (or the file is damaged)"
rm -f "$work/$name.dump.age"
[[ "$(sha256sum "$work/$name.dump" | cut -d' ' -f1)" == "$(jq -r .sha256 "$work/$name.json")" ]] \
  || fail "the decrypted dump's sha256 is not the one the backup recorded"
t_decrypt="$(now)"
dump_bytes="$(stat -c %s "$work/$name.dump")"
echo "drill: decrypted ($dump_bytes bytes) in $(( t_decrypt - t_download ))s; sha256 matches the backup's record"

# 3. Restore into a throwaway PostgreSQL with no network. The dump goes in as a tar stream (docker cp -), never as a bind mount: a bind
#    mount needs the Docker daemon to see THIS machine's folders, and it does not when docker is the Windows one reached from WSL.
docker rm -f -v "$box" > /dev/null 2>&1 || true
docker run -d --name "$box" --network none -e POSTGRES_PASSWORD=drill -e POSTGRES_DB=restore postgres:16 > /dev/null
ready=0
# (over TCP on the container's own loopback: the image first runs a temporary server that listens on the socket only, stops it and starts the real one)
for _ in $(seq 90); do docker exec "$box" pg_isready -h 127.0.0.1 -U postgres -d restore -q 2> /dev/null && { ready=1; break; }; sleep 2; done
(( ready )) || fail "the throwaway PostgreSQL did not start"
t_ready="$(now)"
docker exec "$box" mkdir -p /dump
tar -C "$work" -cf - "$name.dump" | docker cp - "$box:/dump" || fail "the dump could not be copied into the throwaway PostgreSQL"
rm -f "$work/$name.dump"
t_restore0="$(now)"
echo "drill: dump loaded into the container in $(( t_restore0 - t_ready ))s"
docker exec "$box" pg_restore -U postgres -d restore --no-owner --no-privileges --jobs="$JOBS" "/dump/$name.dump" \
  > "$work/restore.log" 2>&1 || true
t_restore="$(now)"
restore_errors="$(grep -c 'error' "$work/restore.log" || true)"
echo "drill: restored in $(( t_restore - t_restore0 ))s with $JOBS jobs ($restore_errors line(s) mentioning errors in pg_restore's output)"

# 4. The schema revision and the key tables' counts: each between the figure before the dump and the one after it.
q() { docker exec "$box" psql -U postgres -d restore -qAtX -c "$1"; }
revision="$(q "SELECT version_num FROM public.alembic_version")" || fail "no alembic_version in the restored database"
[[ "$revision" == "$(jq -r .alembic_revision "$work/$name.json")" ]] \
  || fail "revision $revision, expected $(jq -r .alembic_revision "$work/$name.json")"
fail_counts=0
counts_json='{}'
while read -r t; do
  n="$(q "SELECT count(*) FROM $t")" || n=-1
  lo="$(jq -r --arg t "$t" '.counts_before[$t]' "$work/$name.json")"; hi="$(jq -r --arg t "$t" '.counts_after[$t]' "$work/$name.json")"
  if (( n < lo || n > hi )); then echo "  $t: $n outside [$lo, $hi]"; fail_counts=1; else echo "  $t: $n ok"; fi
  counts_json="$(jq -c --arg t "$t" --argjson n "$n" --argjson lo "$lo" --argjson hi "$hi" '. + {($t): {restored: $n, before: $lo, after: $hi}}' <<< "$counts_json")"
done < <(jq -r '.counts_before | keys[]' "$work/$name.json")
t_end="$(now)"
passed=true; (( fail_counts == 0 )) || passed=false

# 5. The report: the minutes of the recovery plan's RTO, measured on this machine.
[[ -n "$REPORT" ]] || REPORT="./r2-drill-$name.json"
jq -n --arg name "$name" --arg tier "$TIER" --arg bucket "$R2_BUCKET" --arg at "$(date -u +%FT%TZ)" --arg host "$(hostname)" \
  --arg cpus "$(nproc)" --arg mem_kb "$(awk '/^MemTotal:/ {print $2}' /proc/meminfo 2> /dev/null || echo 0)" \
  --arg docker "$(docker version -f '{{.Server.Version}}' 2> /dev/null || echo '?')" --arg revision "$revision" \
  --argjson age_bytes "$age_bytes" --argjson dump_bytes "$dump_bytes" --argjson jobs "$JOBS" --argjson errors "$restore_errors" \
  --argjson download_s "$(( t_download - t0 ))" --argjson decrypt_s "$(( t_decrypt - t_download ))" \
  --argjson start_s "$(( t_ready - t_decrypt ))" --argjson load_s "$(( t_restore0 - t_ready ))" \
  --argjson restore_s "$(( t_restore - t_restore0 ))" --argjson verify_s "$(( t_end - t_restore ))" --argjson total_s "$(( t_end - t0 ))" \
  --argjson counts "$counts_json" --argjson passed "$passed" \
  '{drill_at: $at, passed: $passed, dump: $name, tier: $tier, bucket: $bucket, alembic_revision: $revision, machine: {host: $host, cpus: ($cpus|tonumber), memory_kb: ($mem_kb|tonumber), docker: $docker},
    sizes: {encrypted_bytes: $age_bytes, dump_bytes: $dump_bytes},
    seconds: {download: $download_s, decrypt: $decrypt_s, start: $start_s, load: $load_s, restore: $restore_s, verify: $verify_s, total: $total_s},
    pg_restore: {jobs: $jobs, error_lines: $errors}, counts: $counts}' > "$REPORT"
echo "drill: report in $REPORT"
(( fail_counts == 0 )) || fail "counts"
echo "drill PASSED in $(( t_end - t0 ))s (download $(( t_download - t0 ))s, decrypt $(( t_decrypt - t_download ))s, start $(( t_ready - t_decrypt ))s, load $(( t_restore0 - t_ready ))s, restore $(( t_restore - t_restore0 ))s, verify $(( t_end - t_restore ))s): $name restored from R2, revision $revision"
