#!/bin/bash
# Stop all seed_shard workers (not unrelated python).
set -uo pipefail
cd "$(dirname "$0")"
pgrep -f 'seed_shard.py --shard' 2>/dev/null | while read -r pid; do
  kill "$pid" 2>/dev/null || true
done
sleep 1
left=$(pgrep -f 'seed_shard.py --shard' 2>/dev/null | wc -l | tr -d ' ')
echo "seed_shard remaining: ${left}"
