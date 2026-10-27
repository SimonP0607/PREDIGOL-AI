#!/usr/bin/env bash
# The off-server copy to Cloudflare R2, in one run, once the owner has created the bucket, its token and its locks.
#
#   bin/r2-setup.sh /root/r2.env [--check-only]
#
# /root/r2.env (chmod 600, written by the owner, never committed, never pasted in a chat):
#   R2_ACCOUNT_ID=<the 32-character account id>        (the endpoint is https://<id>.r2.cloudflarestorage.com)
#   R2_ACCESS_KEY_ID=<the "copias" token's Access Key ID>
#   R2_SECRET_ACCESS_KEY=<that token's Secret Access Key>
#   R2_BUCKET=predigol-backups                          (the token: Object Read & Write on THIS bucket only)
#   AGE_RECIPIENT=age1...                               (the owner's PUBLIC age key; the private key never comes here)
#   R2_ENDPOINT=https://...                             (optional: a rehearsal's stand-in; the account's own by default)
#   R2_PITR_ACCESS_KEY_ID / R2_PITR_SECRET_ACCESS_KEY   (optional: the PITR token, used later by bin/pitr-enable.sh;
#                                                        ignored here)
#
# What it does, stopping at the first failure and changing nothing in predigol.env before its checks pass:
#   1. an rclone remote "r2" (S3, provider Cloudflare) in root's rclone config, written straight to the file (600): the
#      keys never appear on a command line, where `ps` would show them. `no_head = true` is NOT optional: rclone 1.60.x
#      (Ubuntu 24.04 ships 1.60.1) follows every upload with HEAD <object>?versionId=..., R2 answers that with 501
#      NotImplemented and rclone calls a stored object a failed upload (seen on the real bucket, 2026-10-26). The size
#      and the hash of what was uploaded are checked below (steps 2, 5 and 6), by reading it back;
#   2. proves the bucket: writes a probe object, reads it back byte for byte, deletes it;
#   3. proves the LOCKS (bin/r2-lock-check.sh): in each tier a canary is uploaded, and neither its deletion nor its
#      overwrite may succeed. No dump goes to a bucket that would let this server's own token erase it;
#   4. (not with --check-only) sets BACKUP_RCLONE_REMOTE=r2:<bucket>, BACKUP_AGE_RECIPIENT and
#      RAW_RCLONE_REMOTE=r2:<bucket>/raw in predigol.env (the previous file kept as predigol.env.before-r2-<stamp>);
#   5. runs bin/backup.sh --label r2-first: the dump is encrypted with the owner's public key and copied to R2, and
#      the copy's size is checked there before anything is rotated;
#   6. streams that copy back and compares its hash with the one the backup recorded: the object is there, whole, and
#      an age file (decrypting it needs the owner's private key, see below).
# The RAW store is copied by bin/raw-sync.sh (hourly timer); its first pass (--full) takes a while and is started by hand.
#
# The full restore of an off-server copy needs the PRIVATE key, which by design is not on this server: the owner's
# machine runs deploy/vps/bin/r2-restore-drill.sh (download, decrypt, pg_restore into a throwaway database, counts).
# Cost: Cloudflare R2 bills storage above 10 GB a month (US$0.015/GB-month); the tiers kept (about 14 daily, 8 weekly
# and 12 monthly dumps) are measured in the README, "Copias fuera del servidor" - the owner authorises it by creating
# the bucket.
set -Eeuo pipefail
# shellcheck source=bin/lib.sh
. "$(dirname "$0")/lib.sh"

ENV_FILE="${1:-}"
CHECK_ONLY="${2:-}"
[[ -n "$ENV_FILE" && -f "$ENV_FILE" ]] || { echo "usage: $0 /root/r2.env [--check-only]" >&2; exit 2; }
[[ -z "$CHECK_ONLY" || "$CHECK_ONLY" == "--check-only" ]] || { echo "usage: $0 /root/r2.env [--check-only]" >&2; exit 2; }
[[ "$(stat -c %a "$ENV_FILE")" == "600" ]] || { echo "$ENV_FILE must be chmod 600" >&2; exit 2; }
# The one thing that must never be here. Whatever else this file holds, a PRIVATE age key is refused before it is read.
if grep -q 'AGE-SECRET-KEY-' "$ENV_FILE"; then
  echo "$ENV_FILE contains an age PRIVATE key (AGE-SECRET-KEY-...): that key must never be on this server. Remove it and use the public key (age1...)." >&2
  exit 2
fi
# A file written on Windows has CRLF line endings and perhaps a BOM; neither belongs in a value.
# shellcheck disable=SC1090
. <(sed -e '1s/^\xEF\xBB\xBF//' -e 's/\r$//' "$ENV_FILE")
for v in R2_ACCOUNT_ID R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY R2_BUCKET AGE_RECIPIENT; do
  [[ -n "${!v:-}" ]] || { echo "$v is missing in $ENV_FILE" >&2; exit 2; }
done
[[ "$AGE_RECIPIENT" == age1* ]] || { echo "AGE_RECIPIENT must be an age PUBLIC key (age1...)" >&2; exit 2; }
[[ "$R2_BUCKET" =~ ^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$ ]] || { echo "R2_BUCKET is not a valid bucket name" >&2; exit 2; }
[[ -n "${R2_ENDPOINT:-}" || "$R2_ACCOUNT_ID" =~ ^[0-9a-f]{32}$ ]] || { echo "R2_ACCOUNT_ID must be the 32-character account id" >&2; exit 2; }
for tool in rclone age jq; do command -v "$tool" > /dev/null || { echo "$tool is required" >&2; exit 2; }; done
# The recipient must be one age accepts: a typo would encrypt every dump to nobody.
printf 'x' | age -r "$AGE_RECIPIENT" > /dev/null 2>&1 || { echo "AGE_RECIPIENT is not a valid age public key" >&2; exit 2; }

REMOTE="r2:$R2_BUCKET"
ENDPOINT="${R2_ENDPOINT:-https://$R2_ACCOUNT_ID.r2.cloudflarestorage.com}"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
log "r2-setup: remote r2 -> bucket $R2_BUCKET at $ENDPOINT (credentials not printed)"
rclone_conf="$(rclone config file | tail -n 1)"
mkdir -p "$(dirname "$rclone_conf")"
if [[ -f "$rclone_conf" ]]; then cp -p "$rclone_conf" "$rclone_conf.before-r2-$stamp"; fi
(
  umask 077
  tmp="$rclone_conf.new.$$"
  {
    if [[ -f "$rclone_conf" ]]; then awk '/^\[r2\]/ {skip = 1; next} /^\[/ {skip = 0} !skip' "$rclone_conf"; fi
    cat <<CONF
[r2]
type = s3
provider = Cloudflare
env_auth = false
access_key_id = $R2_ACCESS_KEY_ID
secret_access_key = $R2_SECRET_ACCESS_KEY
endpoint = $ENDPOINT
acl = private
no_check_bucket = true
no_head = true
CONF
  } > "$tmp"
  mv "$tmp" "$rclone_conf"
)
chmod 600 "$rclone_conf"

probe="$(mktemp)"; back="$(mktemp)"
trap 'rm -f "$probe" "$back"' EXIT
head -c 65536 /dev/urandom > "$probe"
name="probe-$stamp"
rclone copyto "$probe" "$REMOTE/_probe/$name"
rclone copyto "$REMOTE/_probe/$name" "$back"
cmp -s "$probe" "$back" || { log "r2-setup FAILED: the probe did not come back byte for byte"; exit 1; }
rclone deletefile "$REMOTE/_probe/$name"
log "r2-setup: bucket proven (write, read back identical, delete)"

"$(dirname "$0")/r2-lock-check.sh" --remote "$REMOTE" || { log "r2-setup FAILED: the bucket is not locked as it must be (see r2-lock-check above); nothing was configured"; exit 1; }
[[ "$CHECK_ONLY" == "--check-only" ]] && { log "r2-setup: --check-only, predigol.env untouched"; exit 0; }

conf="$PREDIGOL_ENV_FILE"
cp -p "$conf" "$conf.before-r2-$stamp"
set_key() {  # set_key NAME VALUE in predigol.env (replace the line, or append it); the file keeps its owner and mode
  local tmp="$conf.new.$$"
  K="$1" V="$2" awk 'BEGIN { k = ENVIRON["K"]; v = ENVIRON["V"] } index($0, k "=") == 1 { print k "=" v; done = 1; next } { print } END { if (!done) print k "=" v }' "$conf" > "$tmp"
  cat "$tmp" > "$conf"
  rm -f "$tmp"
}
set_key BACKUP_RCLONE_REMOTE "$REMOTE"
set_key BACKUP_AGE_RECIPIENT "$AGE_RECIPIENT"
set_key RAW_RCLONE_REMOTE "$REMOTE/raw"
log "r2-setup: predigol.env now copies dumps and RAW to $REMOTE"

"$(dirname "$0")/backup.sh" --label r2-first
manifest="$(ls -t "$DB_BACKUPS"/predigol-*-r2-first.json 2> /dev/null | head -1)"
[[ -n "$manifest" ]] || { log "r2-setup FAILED: no manifest for the first off-server dump"; exit 1; }
remote="$(jq -r '.offsite.remote // empty' "$manifest")"
bytes="$(jq -r '.offsite.bytes // -1' "$manifest")"
want_sha="$(jq -r '.offsite.age_sha256 // empty' "$manifest")"
[[ -n "$remote" && -n "$want_sha" ]] || { log "r2-setup FAILED: the dump was not copied off the server"; exit 1; }
[[ "$(rclone lsjson "$remote" | jq -r '.[0].Size // -1')" == "$bytes" ]] || { log "r2-setup FAILED: size on R2 differs from the backup's record"; exit 1; }
[[ "$(rclone cat "$remote" | sha256sum | cut -d' ' -f1)" == "$want_sha" ]] || { log "r2-setup FAILED: the copy on R2 is not the file that was uploaded (hash)"; exit 1; }
rclone cat --count 64 "$remote" | head -c 21 | grep -aq "age-encryption.org/v1" || { log "r2-setup FAILED: not an age file"; exit 1; }
log "r2-setup PASSED: $remote is on R2 ($bytes bytes, hash checked, age-encrypted). Next: the first RAW pass (RAW_SYNC_TRANSFERS=16 bin/raw-sync.sh --full), then bin/r2-lock-check.sh; run r2-restore-drill.sh on the owner's machine"
