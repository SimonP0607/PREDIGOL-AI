#!/usr/bin/env bash
# The off-server copy to Cloudflare R2, in one run, once the owner has created the bucket and its token.
#
#   bin/r2-setup.sh /root/r2.env [--check-only]
#
# /root/r2.env (chmod 600, written by the owner, never committed, never pasted in a chat):
#   R2_ACCOUNT_ID=<the 32-character account id>        (the endpoint is https://<id>.r2.cloudflarestorage.com)
#   R2_ACCESS_KEY_ID=<the token's Access Key ID>
#   R2_SECRET_ACCESS_KEY=<the token's Secret Access Key>
#   R2_BUCKET=predigol-backups                          (an API token with Object Read & Write on THIS bucket only)
#   AGE_RECIPIENT=age1...                               (the owner's PUBLIC age key; the private key never comes here)
#
# What it does, stopping at the first failure and changing nothing before its checks pass:
#   1. an rclone remote "r2" (S3, provider Cloudflare) in root's rclone config;
#   2. proves the bucket: writes a probe object, reads it back byte for byte, deletes it;
#   3. sets BACKUP_RCLONE_REMOTE=r2:<bucket>, BACKUP_AGE_RECIPIENT and RAW_RCLONE_REMOTE=r2:<bucket>/raw in
#      /etc/predigol/predigol.env (the previous file kept as predigol.env.before-r2-<stamp>);
#   4. runs bin/backup.sh --label r2-first: the dump is encrypted with the owner's public key and copied to R2, and
#      the copy's size is checked there before anything is rotated;
#   5. downloads that copy back: the size the backup recorded and the age header - the copy is there and whole (rclone
#      already checked its hash on upload; decrypting it needs the owner's private key, see below).
#
# The full restore of an off-server copy needs the PRIVATE key, which by design is not on this server: the owner's
# machine runs deploy/vps/bin/r2-restore-drill.sh (download, decrypt, pg_restore into a throwaway database, counts).
# Cost: Cloudflare R2 bills storage above 10 GB a month (US$0.015/GB-month); the retention configured here keeps
# about 34 dumps of ~0.7 GB (≈ 23 GB, about US$0.20 a month) - the owner authorises it by creating the bucket.
set -Eeuo pipefail
# shellcheck source=bin/lib.sh
. "$(dirname "$0")/lib.sh"

ENV_FILE="${1:-}"
CHECK_ONLY="${2:-}"
[[ -n "$ENV_FILE" && -f "$ENV_FILE" ]] || { echo "usage: $0 /root/r2.env [--check-only]" >&2; exit 2; }
[[ "$(stat -c %a "$ENV_FILE")" == "600" ]] || { echo "$ENV_FILE must be chmod 600" >&2; exit 2; }
# shellcheck disable=SC1090
. "$ENV_FILE"
for v in R2_ACCOUNT_ID R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY R2_BUCKET AGE_RECIPIENT; do
  [[ -n "${!v:-}" ]] || { echo "$v is missing in $ENV_FILE" >&2; exit 2; }
done
[[ "$AGE_RECIPIENT" == age1* ]] || { echo "AGE_RECIPIENT must be an age PUBLIC key (age1...)" >&2; exit 2; }
command -v rclone > /dev/null && command -v age > /dev/null || { echo "rclone and age are required" >&2; exit 2; }

REMOTE="r2:$R2_BUCKET"
log "r2-setup: remote r2 -> bucket $R2_BUCKET (credentials not printed)"
rclone config create r2 s3 provider Cloudflare env_auth false access_key_id "$R2_ACCESS_KEY_ID" \
  secret_access_key "$R2_SECRET_ACCESS_KEY" endpoint "https://$R2_ACCOUNT_ID.r2.cloudflarestorage.com" \
  acl private no_check_bucket true > /dev/null

probe="$(mktemp)"; back="$(mktemp)"
trap 'rm -f "$probe" "$back"' EXIT
head -c 65536 /dev/urandom > "$probe"
name="probe-$(date -u +%Y%m%dT%H%M%SZ)"
rclone copyto "$probe" "$REMOTE/_probe/$name"
rclone copyto "$REMOTE/_probe/$name" "$back"
cmp -s "$probe" "$back" || { log "r2-setup FAILED: the probe did not come back byte for byte"; exit 1; }
rclone deletefile "$REMOTE/_probe/$name"
log "r2-setup: bucket proven (write, read back identical, delete)"
[[ "$CHECK_ONLY" == "--check-only" ]] && { log "r2-setup: --check-only, nothing configured"; exit 0; }

conf=/etc/predigol/predigol.env
cp -p "$conf" "$conf.before-r2-$(date -u +%Y%m%dT%H%M%SZ)"
set_key() {  # set_key NAME VALUE in predigol.env (replace the line, or append it)
  if grep -q "^$1=" "$conf"; then sed -i "s|^$1=.*|$1=$2|" "$conf"; else echo "$1=$2" >> "$conf"; fi
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
[[ -n "$remote" ]] || { log "r2-setup FAILED: the dump was not copied off the server"; exit 1; }
rclone copyto "$remote" "$back"
[[ "$(stat -c %s "$back")" == "$bytes" ]] || { log "r2-setup FAILED: size on R2 differs from the backup's record"; exit 1; }
head -c 21 "$back" | grep -q "age-encryption.org/v1" || { log "r2-setup FAILED: not an age file"; exit 1; }
log "r2-setup PASSED: $remote is on R2 ($bytes bytes, age-encrypted); run r2-restore-drill.sh on the owner's machine"
