#!/usr/bin/env bash
# The server's own secrets, packed for the OWNER and encrypted so that only the owner can open them (plan section 17,
# "Copia de los secretos"). The values are never printed, not even a hash of one; what is printed is a path and a size.
#
#   bin/secrets-export.sh [--out DIR] [--recipient age1...]
#
# It writes ONE file, DIR/secrets-<UTC time>.tar.age (DIR is /root by default; mode 600): a tar of the two environment
# files (predigol.env, app.env) and the rclone configuration, encrypted with the owner's age PUBLIC key (BACKUP_AGE_RECIPIENT,
# the one the dumps use, or --recipient). The private key is on the owner's computer only, so without it the file is noise:
# it may travel, sit in the password manager as an attachment and go to the offline copy. It holds what no other copy has and
# a restoration cannot do without - PITR_CIPHER_PASS (lose it and the PITR repository cannot be read), FBI_AUTH_SECRET_KEY
# (lose it and every TOTP secret is unreadable), the database passwords, the provider keys and the R2 "copias" token.
#
# Inside, next to the files, MANIFEST.txt lists the NAMES of the settings (which are set and which are empty), never a value.
# Nothing is written in plain text on the disk: tar goes straight into age.
#
# After it: copy the file to the owner's computer, keep it with the offline copy, and delete it from the server (what it holds
# is already on the server in clear, so keeping it here protects nothing). Run it again whenever a secret is rotated.
# Exit 0 done, 1 refused or failed (nothing left behind), 2 usage.
set -Eeuo pipefail
# shellcheck source=bin/lib.sh
. "$(dirname "$0")/lib.sh"

usage() { echo "usage: $0 [--out DIR] [--recipient age1...]" >&2; exit 2; }
OUT_DIR=/root
RECIPIENT="${BACKUP_AGE_RECIPIENT:-}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) OUT_DIR="${2:-}"; [[ -n "$OUT_DIR" ]] || usage; shift 2 ;;
    --recipient) RECIPIENT="${2:-}"; [[ -n "$RECIPIENT" ]] || usage; shift 2 ;;
    *) usage ;;
  esac
done

fail() { log "secrets-export: $*"; exit 1; }
for tool in age tar jq; do command -v "$tool" > /dev/null || fail "$tool is required"; done
[[ -n "$RECIPIENT" ]] || fail "no recipient: BACKUP_AGE_RECIPIENT is empty (bin/r2-setup.sh sets it) and --recipient was not given"
[[ "$RECIPIENT" != AGE-SECRET-KEY-* ]] || fail "that is an age PRIVATE key. It must never be on this server: give the PUBLIC key (age1...)"
[[ "$RECIPIENT" == age1* ]] || fail "the recipient must be an age PUBLIC key (age1...)"
printf 'x' | age -r "$RECIPIENT" > /dev/null 2>&1 || fail "age does not accept that recipient (a typo would encrypt the secrets to nobody)"
[[ -d "$OUT_DIR" ]] || fail "$OUT_DIR is not a folder"

RCLONE_FILE="${RCLONE_CONFIG:-/root/.config/rclone/rclone.conf}"
files=()
for f in "$PREDIGOL_ENV_FILE" "$PREDIGOL_APP_ENV_FILE" "$RCLONE_FILE"; do
  [[ -r "$f" ]] && files+=("$f")
done
(( ${#files[@]} > 0 )) || fail "no file to pack"
for f in "${files[@]}"; do
  if grep -q 'AGE-SECRET-KEY-' "$f"; then fail "$f contains an age PRIVATE key (AGE-SECRET-KEY-...): that key must never be on this server. Remove it first"; fi
done

umask 077
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="$OUT_DIR/secrets-$stamp.tar.age"
[[ ! -e "$out" ]] || fail "$out already exists"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"; [[ -z "${partial:-}" ]] || rm -f "$partial"' EXIT

# The manifest: names, never values.
names() {  # names FILE: "<n> set: A B C | empty: D E" for NAME=value lines
  awk -F= '
    /^[A-Za-z_][A-Za-z0-9_]*=/ { n = $1; v = substr($0, length(n) + 2); gsub(/^["'\'']|["'\'']$/, "", v)
                                  if (v == "") e = e " " n; else s = s " " n; c++ }
    END { printf "%d settings. set:%s | empty:%s\n", c, (s == "" ? " -" : s), (e == "" ? " -" : e) }' "$1"
}
{
  echo "PrediGol secrets bundle - names only, no value is written here"
  echo "made: $(date -u +%FT%TZ) on $(hostname)"
  echo "checkout: $(git -C "$KIT/../.." rev-parse --short=12 HEAD 2> /dev/null || echo unknown)"
  echo "encrypted for: ${RECIPIENT:0:16}... (age public key; the private key is not on this server)"
  echo
  for f in "${files[@]}"; do
    echo "== ${f#/}"
    if [[ "$f" == "$RCLONE_FILE" ]]; then
      echo "rclone remotes: $(sed -n 's/^\[\(.*\)\]$/\1/p' "$f" | tr '\n' ' ')"
    else
      names "$f"
    fi
  done
  echo
  echo "To open it (on the computer that has the private key; nothing needs typing):"
  echo "  age -d -i <private key file> secrets-<time>.tar.age > secrets.tar"
  echo "  tar -xf secrets.tar        (the files come out under bundle/, with the paths they have on the server)"
} > "$tmp/MANIFEST.txt"

partial="$out.partial"
# tar goes straight into age: no plain copy of a secret is ever written to the disk. Paths inside are the server's own,
# below bundle/, so that a restoration is `tar -xf secrets.tar --strip-components=1 -C /`.
rel=()
for f in "${files[@]}"; do rel+=("${f#/}"); done
tar --transform 's,^,bundle/,' -cf - -C / "${rel[@]}" -C "$tmp" MANIFEST.txt \
  | age -r "$RECIPIENT" -o "$partial"
[[ "$(head -c 21 "$partial")" == "age-encryption.org/v1" ]] || fail "the result is not an age file; nothing was kept"
size="$(stat -c %s "$partial")"
(( size > 200 )) || fail "the result is too small to hold the files ($size bytes); nothing was kept"
mv "$partial" "$out"
partial=""
chmod 600 "$out"
log "secrets-export: wrote $out ($size bytes), ${#files[@]} files, encrypted for ${RECIPIENT:0:16}... Copy it to the owner's computer, keep it with the offline copy, then delete it from the server."
