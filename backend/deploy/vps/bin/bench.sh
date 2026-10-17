#!/usr/bin/env bash
# Is THIS machine good enough for PrediGol? Run it on a freshly bought VPS, BEFORE installing anything else
# (README §0; docs/owner/INFRA_DECISION_2026-10-07.md). About 6 minutes. Needs root, internet and ~4 GB free.
#
#   sudo deploy/vps/bin/bench.sh [--out FILE]
#
# Measures, and compares with the minimums (each overridable with BENCH_MIN_* / BENCH_MAX_*):
#   CPU         sysbench single-thread and all-threads events/s; CPU STEAL under full load (a noisy neighbour)
#   disk        fio 4k random read and write IOPS at queue depth 32, 1 MB sequential MB/s; size
#   fsync       pg_test_fsync (PostgreSQL's own commit path), ops/s
#   memory      total RAM
#   network     download speed (Cloudflare's speed test), connect time to API-Football
# Prints PASS/FAIL per line and writes everything to a JSON file. Exit 0 all pass, 1 at least one failure.
# A FAIL on a monthly contract means: cancel it and take plan B (Contabo Cloud VPS Plus 4, or OVH VPS-3).
set -Euo pipefail
[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 2; }
OUT="bench-$(date -u +%Y%m%dT%H%M%SZ).json"
[[ "${1:-}" == --out ]] && OUT="${2:?--out FILE}"
DIR="${BENCH_DIR:-/var/tmp/predigol-bench}"
mkdir -p "$DIR"
log() { printf '%s %s\n' "$(date -u +%T)" "$*"; }

# One sysbench thread (prime 20000): 1053 events/s on the rehearsal machine (Xeon 2.8 GHz). Published Geekbench 6
# single-core scores put Contabo's Cloud VPS at 840-1170 and OVH's VPS-2 at 700, i.e. roughly 600-1000 events/s.
# Half the rehearsal machine is the floor: below it the host is oversold or throttled.
MIN_CPU1="${BENCH_MIN_CPU1:-500}"
MAX_STEAL="${BENCH_MAX_STEAL:-10}"         # % of CPU time taken by the host, under full load
MIN_READ_IOPS="${BENCH_MIN_READ_IOPS:-5000}"
MIN_WRITE_IOPS="${BENCH_MIN_WRITE_IOPS:-2500}"
MIN_SEQ_MBS="${BENCH_MIN_SEQ_MBS:-150}"
MIN_FSYNC="${BENCH_MIN_FSYNC:-400}"        # fdatasync ops/s (2.5 ms each)
MIN_RAM_GB="${BENCH_MIN_RAM_GB:-7.5}"
MIN_DISK_GB="${BENCH_MIN_DISK_GB:-90}"
MIN_DOWN_MBIT="${BENCH_MIN_DOWN_MBIT:-100}"
# Tried in order, 200 MB each (a byte range), the best one counts. Cloudflare's speed test answers 403 to some
# datacenter addresses (Contabo US-east, 9 Oct 2026): Ubuntu's release server and a university mirror follow.
DOWN_URLS="${BENCH_DOWN_URL:-https://speed.cloudflare.com/__down?bytes=200000000 https://releases.ubuntu.com/24.04/ubuntu-24.04.3-live-server-amd64.iso https://mirror.math.princeton.edu/pub/ubuntu-iso/24.04/ubuntu-24.04.3-live-server-amd64.iso}"

if ! command -v fio > /dev/null || ! command -v sysbench > /dev/null; then
  log "installing fio and sysbench"
  DEBIAN_FRONTEND=noninteractive apt-get -qq update && DEBIAN_FRONTEND=noninteractive apt-get -qq -y install fio sysbench jq curl > /dev/null
fi

results=()
fails=0
check() {  # check NAME VALUE OP LIMIT UNIT
  local ok
  ok=$(awk -v v="$2" -v l="$4" -v op="$3" 'BEGIN { print (op == ">=" ? (v >= l) : (v <= l)) }')
  if [[ "$ok" == 1 ]]; then log "PASS $1: $2 $5 (needed $3 $4)"; else log "FAIL $1: $2 $5 (needed $3 $4)"; fails=$(( fails + 1 )); fi
  results+=("$(jq -nc --arg n "$1" --arg v "$2" --arg op "$3" --arg l "$4" --arg u "$5" --argjson ok "$ok" \
    '{name: $n, value: ($v | tonumber? // $v), needed: ($op + " " + $l), unit: $u, pass: ($ok == 1)}')")
}

cpus="$(nproc)"
model="$(awk -F: '/model name/ {gsub(/^ /, "", $2); print $2; exit}' /proc/cpuinfo)"
ram_gb="$(awk '/MemTotal/ {printf "%.1f", $2 / 1048576}' /proc/meminfo)"
disk_gb="$(df -Pk "$DIR" | awk 'NR==2 {printf "%.0f", $2 / 1048576}')"
log "machine: $cpus vCPU ($model), ${ram_gb} GB RAM, ${disk_gb} GB disk"
check "memory" "$ram_gb" ">=" "$MIN_RAM_GB" "GB"
check "disk size" "$disk_gb" ">=" "$MIN_DISK_GB" "GB"

log "CPU (single thread, 20 s)"
cpu1="$(sysbench cpu --cpu-max-prime=20000 --threads=1 --time=20 run | awk '/events per second/ {print $4}')"
check "CPU single thread" "$cpu1" ">=" "$MIN_CPU1" "events/s"

log "CPU (all threads, 60 s) - and the steal it suffers meanwhile"
read -r _ u n s i w q sq st _ < /proc/stat; t0=$(( u + n + s + i + w + q + sq + st )); st0=$st
cpun="$(sysbench cpu --cpu-max-prime=20000 --threads="$cpus" --time=60 run | awk '/events per second/ {print $4}')"
read -r _ u n s i w q sq st _ < /proc/stat; t1=$(( u + n + s + i + w + q + sq + st ))
steal="$(awk -v a=$(( st - st0 )) -v b=$(( t1 - t0 )) 'BEGIN { printf "%.1f", (b > 0 ? 100 * a / b : 0) }')"
log "CPU all threads: $cpun events/s ($(awk -v a="$cpun" -v b="$cpu1" 'BEGIN { printf "%.1f", a / b }')x one thread)"
results+=("$(jq -nc --arg v "$cpun" '{name: "CPU all threads", value: ($v | tonumber), unit: "events/s"}')")
check "CPU steal under load" "$steal" "<=" "$MAX_STEAL" "%"

log "disk (fio, 4k random, queue depth 32, 45 s each)"
fiojob() { fio --name=bench --filename="$DIR/fio.dat" --size=2G --direct=1 --ioengine=libaio --runtime=45 \
  --time_based --group_reporting --output-format=json "$@" 2> /dev/null; }
rr="$(fiojob --rw=randread --bs=4k --iodepth=32 --numjobs=2 | jq '.jobs[0].read.iops | floor')"
check "disk 4k random read" "$rr" ">=" "$MIN_READ_IOPS" "IOPS"
rw="$(fiojob --rw=randwrite --bs=4k --iodepth=32 --numjobs=2 | jq '.jobs[0].write.iops | floor')"
check "disk 4k random write" "$rw" ">=" "$MIN_WRITE_IOPS" "IOPS"
seq="$(fiojob --rw=read --bs=1M --iodepth=8 --numjobs=1 | jq '.jobs[0].read.bw / 1024 | floor')"
check "disk 1 MB sequential read" "$seq" ">=" "$MIN_SEQ_MBS" "MB/s"
rm -f "$DIR/fio.dat"

log "fsync (pg_test_fsync, as PostgreSQL commits)"
if command -v docker > /dev/null; then
  fsync="$(docker run --rm -v "$DIR:/b" postgres:16-alpine pg_test_fsync -f /b/fsync.test -s 5 2> /dev/null |
    awk '/fdatasync/ && /ops\/sec/ {print $(NF-3); exit}')"
else
  fsync="$(fio --name=fsync --filename="$DIR/fsync.dat" --size=64M --rw=write --bs=8k --fdatasync=1 \
    --runtime=20 --time_based --output-format=json 2> /dev/null | jq '.jobs[0].write.iops | floor')"
fi
rm -f "$DIR/fsync.test" "$DIR/fsync.dat"
check "fsync (commit)" "${fsync:-0}" ">=" "$MIN_FSYNC" "ops/s"

log "network"
down=0
for url in $DOWN_URLS; do
  if speed="$(curl -fsS -m 60 -r 0-199999999 -o /dev/null -w '%{speed_download}' "$url" 2> /dev/null)"; then
    d="$(awk -v b="$speed" 'BEGIN { printf "%.0f", b * 8 / 1000000 }')"
    log "download from ${url%%\?*}: $d Mbit/s"
    (( d > down )) && down=$d
    (( down >= MIN_DOWN_MBIT )) && break
  else
    # Unreachable is not yet a failure: the next source is tried; none answering is (BENCH_DOWN_URL to point elsewhere).
    log "the download test could not reach ${url%%\?*}"
  fi
done
check "download" "$down" ">=" "$MIN_DOWN_MBIT" "Mbit/s"
apif="$(curl -sS -m 20 -o /dev/null -w '%{time_connect}' https://v3.football.api-sports.io/status 2> /dev/null || echo 9)"
results+=("$(jq -nc --arg v "$apif" '{name: "connect to API-Football", value: ($v | tonumber), unit: "s"}')")
log "connect to API-Football: ${apif}s"

printf '%s\n' "${results[@]}" | jq -s --arg at "$(date -u +%FT%TZ)" --arg host "$(hostname)" --arg model "$model" \
  --argjson cpus "$cpus" --argjson fails "$fails" \
  '{measured_at: $at, host: $host, cpu_model: $model, vcpus: $cpus, passed: ($fails == 0), checks: .}' > "$OUT"
log "written $OUT"
if (( fails )); then log "RESULT: $fails check(s) FAILED - see docs/owner/INFRA_DECISION_2026-10-07.md (plan B)"; exit 1; fi
log "RESULT: all checks passed"
