#!/usr/bin/env bash
# A one-off command in the backend image as the database owner (the `ops` service), the way predigolctl runs its own.
set -Eeuo pipefail
. /opt/predigol/backend/deploy/vps/bin/lib.sh
ops "$@"
