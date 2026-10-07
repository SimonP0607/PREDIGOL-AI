#!/usr/bin/env bash
# Prepare a FRESH Ubuntu 24.04 LTS server for PrediGol. Run once, as root, from the backend checkout:
#
#   sudo /opt/predigol/backend/deploy/vps/bin/install.sh
#
# Installs Docker Engine (Docker's own repository), the firewall (SSH, HTTP, HTTPS only), automatic security
# updates (without automatic reboots: a reboot is planned outside live matches), swap, the tools the scripts use
# (jq, age, rclone, openssl), the data folders, an env file to fill in, and the systemd units that start the
# stack at boot and run the health checks, backups and restore tests. It starts nothing: see README.md.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 2; }
KIT="$(cd "$(dirname "$0")/.." && pwd)"
DATA="${PREDIGOL_DATA:-/srv/predigol}"
log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*"; }

. /etc/os-release
[[ "${ID:-}" == ubuntu ]] || log "WARNING: written for Ubuntu 24.04; this is ${PRETTY_NAME:-unknown}"

log "packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get -y -q upgrade
apt-get -y -q install ca-certificates curl gnupg git jq age rclone openssl ufw fail2ban unattended-upgrades

if ! command -v docker > /dev/null; then
  log "Docker Engine"
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -q
  apt-get -y -q install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker

log "firewall: SSH, HTTP, HTTPS (and HTTP/3)"
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable

log "automatic security updates, no automatic reboot"
cat > /etc/apt/apt.conf.d/52predigol-unattended <<'CONF'
Unattended-Upgrade::Automatic-Reboot "false";
Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
CONF
systemctl enable --now unattended-upgrades fail2ban

if ! swapon --show | grep -q .; then
  log "swap: 4 GB"
  fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile > /dev/null && swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  sysctl -q -w vm.swappiness=10 && echo 'vm.swappiness=10' > /etc/sysctl.d/60-predigol.conf
fi

log "folders under $DATA"
install -d -m 0750 "$DATA" "$DATA/caddy" "$DATA/caddy/data" "$DATA/caddy/config" "$DATA/state"
# pgBackRest's local queue for WAL on its way to the repository (the postgres image's uid 70).
install -d -m 0750 -o 70 -g 70 "$DATA/pgbackrest-spool"
# The API (uid 1000) lists the dumps for the Admin Console's System page: it may read the folders, not write.
install -d -m 0750 -o root -g 1000 "$DATA" "$DATA/backups" "$DATA/backups/db"
install -d -m 0700 "$DATA/pgdata"
# The worker writes the RAW store as uid 1000 (the image's user).
install -d -m 0750 -o 1000 -g 1000 "$DATA/raw"

install -d -m 0700 /etc/predigol /etc/predigol/origin
# Two env files, both root 600: the server's (passwords per database role, PITR, backups, monitors) and the
# application's (FBI_*). Every password and key is GENERATED here, never typed or shown: the owner copies them to
# a password manager from these files.
fill() {  # fill FILE NAME VALUE: set NAME only where it is still empty
  local file=$1 name=$2 value=$3
  if grep -q "^$name=$" "$file"; then
    sed -i "s|^$name=$|$name=$value|" "$file"
    log "generated $name in $file"
  fi
}
for f in predigol app; do
  [[ -f "/etc/predigol/$f.env" ]] || install -m 0600 "$KIT/$f.env.example" "/etc/predigol/$f.env"
  chmod 600 "/etc/predigol/$f.env"
done
for name in POSTGRES_ADMIN_PASSWORD POSTGRES_PASSWORD POSTGRES_WORKER_PASSWORD POSTGRES_API_PASSWORD; do
  fill /etc/predigol/predigol.env "$name" "$(openssl rand -hex 24)"
done
fill /etc/predigol/predigol.env PITR_CIPHER_PASS "$(openssl rand -base64 48 | tr -d '\n/+=' | cut -c1-48)"
fill /etc/predigol/app.env FBI_AUTH_SECRET_KEY "$(openssl rand -base64 32)"
# Docker refuses a CPU cap above the machine's vCPUs: cap the defaults at nproc (a 4-vCPU plan, a rehearsal box).
cpus="$(nproc)"
for name in PG_CPUS WORKER_CPUS API_CPUS; do
  v="$(grep -E "^$name=" /etc/predigol/predigol.env | cut -d= -f2)"
  if [[ -n "$v" ]] && awk -v v="$v" -v c="$cpus" 'BEGIN { exit !(v > c) }'; then
    sed -i "s|^$name=.*|$name=$cpus|" /etc/predigol/predigol.env
    log "$name lowered to $cpus (this machine's vCPUs)"
  fi
done
log "fill in the rest of /etc/predigol/predigol.env and /etc/predigol/app.env before the first deploy"

log "journald: at most 500 MB of logs"
install -d /etc/systemd/journald.conf.d
printf '[Journal]\nSystemMaxUse=500M\n' > /etc/systemd/journald.conf.d/60-predigol.conf
systemctl restart systemd-journald

log "systemd units"
for unit in "$KIT"/systemd/*.service "$KIT"/systemd/*.timer; do
  sed "s|/opt/predigol/backend/deploy/vps|$KIT|g" "$unit" > "/etc/systemd/system/$(basename "$unit")"
done
ln -sf "$KIT/bin/predigolctl" /usr/local/bin/predigolctl
systemctl daemon-reload
systemctl enable predigol.service predigol-post-boot.service
systemctl enable --now predigol-health.timer predigol-backup.timer predigol-restore-test.timer predigol-raw-sync.timer \
  predigol-pitr.timer predigol-pitr-verify.timer predigol-pitr-test.timer predigol-maint.timer

log "done. Next (README.md): fill /etc/predigol/predigol.env, point the domain's DNS here, then: predigolctl deploy"
