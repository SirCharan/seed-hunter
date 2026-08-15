#!/bin/bash
# Keep seed_shard workers alive. Safe to run from cron every few minutes.
# - Does NOT delete progress (shard_*_w*.txt)
# - Does NOT use FORCE_RESTART (won't kill healthy workers)
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

# Prefer venv python if present (start script uses this too)
export PYTHON="${PYTHON:-}"
if [[ -z "$PYTHON" && -x .venv/bin/python ]]; then
  export PYTHON="$(pwd)/.venv/bin/python"
fi

LOG="${ENSURE_ALIVE_LOG:-ensure_alive.log}"
TS="$(date -u '+%Y-%m-%d %H:%M:%S UTC')"
EXPECT="${EXPECT_SHARD_PROCS:-16}"

count_procs() {
  pgrep -f 'seed_shard.py --shard' 2>/dev/null | wc -l | tr -d ' ' || echo 0
}

N="$(count_procs)"
if [[ "$N" -ge "$EXPECT" ]]; then
  echo "$TS ok procs=$N (want>=$EXPECT)" >> "$LOG"
  exit 0
fi

echo "$TS RESTART procs=$N want>=$EXPECT — starting missing workers" >> "$LOG"
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
