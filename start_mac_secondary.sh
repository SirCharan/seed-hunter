#!/bin/bash
# Mac secondary: OPTIONAL. Prefer leaving Mac off when Linux is primary.
# If used, give Mac DIFFERENT keys than Linux (do not share rate limit).
# Default: only high_rev shard so it does not fight Linux low half.
set -euo pipefail
cd "$(dirname "$0")"
# shellcheck source=/dev/null
source ./load_api_keys.sh

if [[ -z "${ETHERSCAN_API_KEY:-}" ]]; then
  echo "ERROR: keys in ~/.seed_hunter_keys"
  exit 1
fi

export PYTHONUNBUFFERED=1
PY="${PYTHON:-.venv/bin/python}"
KEY_COUNT=$(echo "$ETHERSCAN_API_KEY" | tr ',' '\n' | grep -c . || echo 1)
# Lighter on Mac: 1 worker per key, single shard
SHARD="${SHARD:-high_rev}"
NW="${NUM_WORKERS:-$KEY_COUNT}"
CHAINS="${CHAINS:-ethereum,polygon,arbitrum,monad}"
RATE="${RATE_PER_KEY:-2.5}"

echo "WARNING: Only run Mac secondary with keys NOT used on Linux."
echo "Starting shard=$SHARD workers=$NW"

IFS=',' read -r -a KEYS <<< "$ETHERSCAN_API_KEY"
CLEAN=()
for k in "${KEYS[@]}"; do
  k=$(echo "$k" | tr -d '[:space:]')
  [[ -n "$k" ]] && CLEAN+=("$k")
done

for W in $(seq 0 $((NW - 1))); do
  KEY="${CLEAN[$((W % ${#CLEAN[@]}))]}"
  if pgrep -f "seed_shard.py --shard ${SHARD} --workers ${NW} --worker-id ${W} " >/dev/null 2>&1; then
    echo "already ${SHARD} w${W}"
    continue
  fi
  nohup env ETHERSCAN_API_KEY="$KEY" "$PY" seed_shard.py \
    --shard "$SHARD" \
    --workers "$NW" \
    --worker-id "$W" \
    --chains "$CHAINS" \
    --capital-only \
    --rate-limit "$RATE" \
    --results-file found_wallets_capital.jsonl \
    >> "shard_${SHARD}_w${W}.log" 2>&1 &
  echo "started ${SHARD} w${W} pid $!"
done
echo "done. status: ./status_shards.sh"
