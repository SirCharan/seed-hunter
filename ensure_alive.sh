#!/bin/bash
# Keep seed_shard workers alive. Safe to run from cron every few minutes.
# - Does NOT delete progress (shard_*_w*.txt)
# - Does NOT use FORCE_RESTART (won't kill healthy workers)
# - Kills only workers whose log mtime is stale (hung-but-alive)
# - start_linux_primary.sh skips workers already running; starts missing ones
#
# Usage:
#   ./ensure_alive.sh
# Cron (every 5 min + after reboot):
#   */5 * * * * /home/ubuntu/seed-hunter/ensure_alive.sh
#   @reboot sleep 60 && /home/ubuntu/seed-hunter/ensure_alive.sh
set -euo pipefail

cd "$(dirname "$0")"
export HOME="${HOME:-/home/ubuntu}"
export PYTHONUNBUFFERED=1

# shellcheck source=/dev/null
source ./load_api_keys.sh 2>/dev/null || true

if [[ -f .venv/bin/activate ]]; then
  # shellcheck source=/dev/null
  source .venv/bin/activate
fi

export PYTHON="${PYTHON:-}"
if [[ -z "$PYTHON" && -x .venv/bin/python ]]; then
  export PYTHON="$(pwd)/.venv/bin/python"
fi

LOG="${ENSURE_ALIVE_LOG:-ensure_alive.log}"
TS="$(date -u '+%Y-%m-%d %H:%M:%S UTC')"
EXPECT="${EXPECT_SHARD_PROCS:-16}"
STALE_SEC="${STALE_LOG_SEC:-900}"
WORKERS="${WORKERS_PER_SHARD:-4}"
SHARDS=(low_fwd low_rev high_fwd high_rev)

# Count python workers only. Do not use pgrep -f (matches the checker / wrappers).
count_procs() {
  ps -C python,python3 -o args= 2>/dev/null | grep -cF -- 'seed_shard.py --shard ' || true
}

worker_pids() {
  local shard="$1" nw="$2" wid="$3"
  ps -C python,python3 -o pid=,args= 2>/dev/null | awk -v s="$shard" -v n="$nw" -v w="$wid" '
    index($0, "seed_shard.py --shard " s " --workers " n " --worker-id " w " ") {print $1}
  '
}

log_age_sec() {
  local f="$1"
  if [[ ! -f "$f" ]]; then
    echo ""
    return 0
  fi
  echo $(( $(date +%s) - $(stat -c %Y "$f") ))
}

kill_stalled=()
for shard in "${SHARDS[@]}"; do
  for wid in $(seq 0 $((WORKERS - 1))); do
    pids="$(worker_pids "$shard" "$WORKERS" "$wid")"
    [[ -z "$pids" ]] && continue
    age="$(log_age_sec "shard_${shard}_w${wid}.log")"
    [[ -z "$age" ]] && continue
    if (( age > STALE_SEC )); then
      echo "$TS STALL ${shard} w${wid} log_age=${age}s — killing hung worker" >> "$LOG"
      # shellcheck disable=SC2086
      kill $pids 2>/dev/null || true
      kill_stalled+=("${shard}:w${wid}")
    fi
  done
done

if ((${#kill_stalled[@]} > 0)); then
  sleep 1
fi

N="$(count_procs)"
if [[ "$N" -ge "$EXPECT" && ${#kill_stalled[@]} -eq 0 ]]; then
  echo "$TS ok procs=$N (want>=$EXPECT)" >> "$LOG"
  exit 0
fi

if ((${#kill_stalled[@]} > 0)); then
  echo "$TS RESTART procs=$N want>=$EXPECT stalled=${kill_stalled[*]} — starting missing workers" >> "$LOG"
else
  echo "$TS RESTART procs=$N want>=$EXPECT — starting missing workers" >> "$LOG"
fi

chmod +x start_linux_primary.sh kill_shards.sh status_shards.sh load_api_keys.sh 2>/dev/null || true

# No FORCE_RESTART: only fill gaps; progress files untouched
if ! ./start_linux_primary.sh >> "$LOG" 2>&1; then
  echo "$TS start_linux_primary FAILED" >> "$LOG"
  exit 1
fi

sleep 2
N2="$(count_procs)"
echo "$TS after procs=$N2" >> "$LOG"

if [[ "$N2" -lt "$EXPECT" ]]; then
  echo "$TS WARN still below expect ($N2 < $EXPECT)" >> "$LOG"
  exit 1
fi
exit 0
