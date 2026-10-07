#!/usr/bin/env bash
# Cloudflare in front of the server (FASE 11; README "Cloudflare"). Run AFTER the site works with Cloudflare's
# proxy on (orange cloud) and SSL/TLS mode "Full (strict)" - with PREDIGOL_TLS_MODE=origin for the certificate.
#
#   bin/cloudflare-ips.sh trust      Caddy believes CF-Connecting-IP only from Cloudflare's published ranges
#                                    (PREDIGOL_TRUSTED_PROXIES in the env file); restarts Caddy
#   bin/cloudflare-ips.sh firewall   80/443 accept ONLY Cloudflare's ranges: nobody can bypass the proxy and its
#                                    protections by calling the server's IP. SSH is not touched.
#   bin/cloudflare-ips.sh open       80/443 open to everyone again (before turning the proxy off)
#   bin/cloudflare-ips.sh apply      re-apply the saved firewall at boot (predigol-firewall.service)
#   bin/cloudflare-ips.sh show       the ranges Cloudflare publishes now
#
# Docker publishes Caddy's ports through its own iptables chains, which ufw does not see: the restriction lives in
# DOCKER-USER (iptables/ip6tables), the place Docker leaves for it, and is re-applied at every boot.
# The ranges come from https://www.cloudflare.com/ips-v4 and ips-v6 and are saved in /etc/predigol/cloudflare-ranges.
set -Eeuo pipefail
# shellcheck source=bin/lib.sh
. "$(dirname "$0")/lib.sh"
SAVED=/etc/predigol/cloudflare-ranges
CHAIN=PREDIGOL-CF

ranges() {
  local v4 v6
  v4="$(curl -fsS -m 20 https://www.cloudflare.com/ips-v4)"
  v6="$(curl -fsS -m 20 https://www.cloudflare.com/ips-v6)"
  printf '%s\n%s\n' "$v4" "$v6" | grep -E '^[0-9a-f:.]+/[0-9]+$' > /tmp/cf-ranges.$$ || true
  (( $(grep -c '\.' /tmp/cf-ranges.$$) >= 5 )) || { rm -f /tmp/cf-ranges.$$; log "unexpected answer from cloudflare.com/ips"; exit 1; }
  cat /tmp/cf-ranges.$$; rm -f /tmp/cf-ranges.$$
}

set_env() {  # set_env NAME VALUE in the env file (replaced, or appended)
  local file="$PREDIGOL_ENV_FILE" tmp
  tmp="$(mktemp)"
  grep -v "^$1=" "$file" > "$tmp" || true
  printf '%s="%s"\n' "$1" "$2" >> "$tmp"
  cat "$tmp" > "$file" && rm -f "$tmp"
}

hook() {  # hook <iptables|ip6tables> <add|del>
  local ipt=$1 op=$2 rule
  for rule in "-p tcp -m multiport --dports 80,443" "-p udp --dport 443"; do
    # shellcheck disable=SC2086
    if $ipt -C DOCKER-USER $rule -j "$CHAIN" 2> /dev/null; then
      [[ "$op" == del ]] && $ipt -D DOCKER-USER $rule -j "$CHAIN"
    else
      [[ "$op" == add ]] && $ipt -I DOCKER-USER $rule -j "$CHAIN"
    fi
  done
  return 0
}

apply_firewall() {
  [[ -s "$SAVED" ]] || { log "no saved ranges ($SAVED): run 'firewall' first"; exit 1; }
  local ipt family
  for ipt in iptables ip6tables; do
    $ipt -L DOCKER-USER -n > /dev/null 2>&1 || continue
    family='\.'; [[ "$ipt" == ip6tables ]] && family=':'
    $ipt -N "$CHAIN" 2> /dev/null || $ipt -F "$CHAIN"
    # Answers to connections the server opened itself, and established ones, pass.
    $ipt -A "$CHAIN" -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
    grep "$family" "$SAVED" | while read -r cidr; do $ipt -A "$CHAIN" -s "$cidr" -j RETURN; done
    $ipt -A "$CHAIN" -j DROP
    hook "$ipt" add
  done
  log "firewall: 80/443 only from Cloudflare ($(wc -l < "$SAVED") ranges)"
}

case "${1:-}" in
  trust)
    list="$(ranges | tr '\n' ' ' | sed 's/ $//')"
    set_env PREDIGOL_TRUSTED_PROXIES "$list"
    log "trusted proxies: $(wc -w <<< "$list") Cloudflare ranges"
    PREDIGOL_TRUSTED_PROXIES="$list" compose up -d --no-deps --force-recreate caddy
    ;;
  firewall)
    ranges > "$SAVED.new" && mv "$SAVED.new" "$SAVED"
    chmod 644 "$SAVED"
    apply_firewall
    systemctl enable predigol-firewall.service > /dev/null 2>&1 || true
    ;;
  apply) apply_firewall ;;
  open)
    for ipt in iptables ip6tables; do
      $ipt -L DOCKER-USER -n > /dev/null 2>&1 || continue
      hook "$ipt" del
      $ipt -F "$CHAIN" 2> /dev/null || true
      $ipt -X "$CHAIN" 2> /dev/null || true
    done
    rm -f "$SAVED"
    systemctl disable predigol-firewall.service > /dev/null 2>&1 || true
    log "firewall: 80/443 open to everyone again"
    ;;
  show) ranges ;;
  *) sed -n '2,16p' "$0"; exit 2 ;;
esac
