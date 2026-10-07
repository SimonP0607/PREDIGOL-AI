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
# The API (uid 1000) lists the dumps for the Admin Console's System page: it may read the folders, not write.
install -d -m 0750 -o root -g 1000 "$DATA" "$DATA/backups" "$DATA/backups/db"
install -d -m 0700 "$DATA/pgdata"
# The worker writes the RAW store as uid 1000 (the image's user).
install -d -m 0750 -o 1000 -g 1000 "$DATA/raw"

install -d -m 0700 /etc/predigol
if [[ ! -f /etc/predigol/predigol.env ]]; then
  install -m 0600 "$KIT/predigol.env.example" /etc/predigol/predigol.env
  log "fill in /etc/predigol/predigol.env (chmod 600) before the first deploy"
fi

log "systemd units"
for unit in "$KIT"/systemd/*.service "$KIT"/systemd/*.timer; do
  sed "s|/opt/predigol/backend/deploy/vps|$KIT|g" "$unit" > "/etc/systemd/system/$(basename "$unit")"
done
ln -sf "$KIT/bin/predigolctl" /usr/local/bin/predigolctl
systemctl daemon-reload
systemctl enable predigol.service predigol-post-boot.service
systemctl enable --now predigol-health.timer predigol-backup.timer predigol-restore-test.timer predigol-raw-sync.timer

log "done. Next (README.md): fill /etc/predigol/predigol.env, point the domain's DNS here, then: predigolctl deploy"
