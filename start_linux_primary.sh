#!/bin/bash
# Linux primary hunter — Presets A + F (default):
#   A: RPC eth_getBalance + eth_getTransactionCount (batched), ethereum
#   F: Etherscan confirm only on capital hits (when keys present)
#
# Usage:
#   ./start_linux_primary.sh
#
# Optional env:
#   WORKERS_PER_SHARD=4     # stable stripe size (keep fixed after first run)
#   CHAINS=ethereum         # or ethereum,polygon,arbitrum,base
#   CHECK_MODE=both         # balance | nonce | both  (A = both)
#   BATCH_SIZE=20
#   BACKEND=rpc             # rpc | etherscan
#   ENRICH_ETHERSCAN=1      # F = confirm capital hits via Etherscan (default 1)
#   FORCE_RESTART=1         # kill existing shards before start
#   SAVE_ACTIVITY=1         # write nonce>0 empty wallets to activity file
set -euo pipefail
cd "$(dirname "$0")"
# shellcheck source=/dev/null
source ./load_api_keys.sh 2>/dev/null || true

export PYTHONUNBUFFERED=1
PY="${PYTHON:-.venv/bin/python}"
if [[ ! -x "$PY" ]]; then
  PY=python3
fi

# --- Preset A (RPC hot path) + F (enrich hits) ---
BACKEND="${BACKEND:-rpc}"
CHECK_MODE="${CHECK_MODE:-both}"
CHAINS="${CHAINS:-ethereum}"
BATCH_SIZE="${BATCH_SIZE:-20}"
MAX_CONCURRENT="${MAX_CONCURRENT:-8}"
RPC_RPS="${RPC_RPS:-20}"
RESULTS="${RESULTS:-found_wallets_capital.jsonl}"
ACTIVITY="${ACTIVITY:-found_wallets_activity.jsonl}"
SAVE_ACTIVITY="${SAVE_ACTIVITY:-1}"
ENRICH="${ENRICH_ETHERSCAN:-1}"
RATE="${RATE_PER_KEY:-2.5}"

# Stable worker count: do NOT change WORKERS_PER_SHARD after progress files exist
# (stripe step = 2 * workers; changing it reshuffles coverage).
WORKERS_PER_SHARD="${WORKERS_PER_SHARD:-4}"
if [[ "$WORKERS_PER_SHARD" -lt 1 ]]; then
  WORKERS_PER_SHARD=1
fi

# Keys only needed for etherscan backend or enrichment
NKEYS=0
if [[ -n "${ETHERSCAN_API_KEY:-}" ]]; then
  NKEYS=$(echo "$ETHERSCAN_API_KEY" | tr ',' '\n' | grep -c . || echo 0)
fi

if [[ "$BACKEND" == "etherscan" && "$NKEYS" -lt 1 ]]; then
  echo "ERROR: BACKEND=etherscan requires keys in ~/.seed_hunter_keys"
  exit 1
fi

# Stop legacy pipelines (not shards unless FORCE_RESTART)
pkill -f 'seed_hunter_random.py' 2>/dev/null || true
pkill -f 'seed_stream.py --workers' 2>/dev/null || true

if [[ "${FORCE_RESTART:-0}" == "1" ]]; then
  pkill -f 'seed_shard.py --shard' 2>/dev/null || true
  sleep 1
fi

SHARDS=(low_fwd low_rev high_fwd high_rev)
started=0
skipped=0

for SHARD in "${SHARDS[@]}"; do
  NW="$WORKERS_PER_SHARD"
  for W in $(seq 0 $((NW - 1))); do
    LOG="shard_${SHARD}_w${W}.log"
    if [[ "${TRUNCATE_LOGS:-0}" == "1" ]]; then
      : > "$LOG"
    fi
    if pgrep -f "seed_shard.py --shard ${SHARD} --workers ${NW} --worker-id ${W} " >/dev/null 2>&1; then
      echo "already running ${SHARD} w${W}"
      skipped=$((skipped + 1))
      continue
    fi

    EXTRA=()
    if [[ "$SAVE_ACTIVITY" == "1" ]]; then
      EXTRA+=(--save-activity)
    else
      EXTRA+=(--no-save-activity)
    fi
    if [[ "$ENRICH" == "1" ]]; then
      EXTRA+=(--enrich-etherscan)
    else
      EXTRA+=(--no-enrich-etherscan)
    fi

    # Pass keys only if present (enrich / etherscan backend)
    ENV_ARGS=()
    if [[ -n "${ETHERSCAN_API_KEY:-}" ]]; then
      ENV_ARGS=(env "ETHERSCAN_API_KEY=${ETHERSCAN_API_KEY}")
    fi

    nohup "${ENV_ARGS[@]}" "$PY" seed_shard.py \
      --shard "$SHARD" \
      --workers "$NW" \
      --worker-id "$W" \
      --backend "$BACKEND" \
      --check-mode "$CHECK_MODE" \
      --chains "$CHAINS" \
      --batch-size "$BATCH_SIZE" \
      --max-concurrent "$MAX_CONCURRENT" \
      --rpc-rps "$RPC_RPS" \
      --capital-only \
      --min-balance 0 \
      --rate-limit "$RATE" \
      --results-file "$RESULTS" \
      --activity-file "$ACTIVITY" \
      "${EXTRA[@]}" \
      >> "$LOG" 2>&1 &
    echo "started ${SHARD} w${W} pid $!  backend=$BACKEND mode=$CHECK_MODE"
    started=$((started + 1))
  done
done

sleep 2
echo ""
echo "=== Linux primary launched (RPC-first) ==="
echo "shards: ${SHARDS[*]}  workers_per_shard=$WORKERS_PER_SHARD"
echo "backend=$BACKEND  check_mode=$CHECK_MODE  chains=$CHAINS  batch=$BATCH_SIZE"
echo "etherscan_keys=$NKEYS  enrich=$ENRICH  save_activity=$SAVE_ACTIVITY"
echo "capital:  $RESULTS"
echo "activity: $ACTIVITY  (nonce>0, may be empty balance)"
echo "started=$started  already_running=$skipped"
echo "running: $(pgrep -f 'seed_shard.py --shard' 2>/dev/null | wc -l | tr -d ' ')"
echo ""
echo "Monitor:  tail -f shard_low_fwd_w0.log"
echo "Status:   ./status_shards.sh"
echo "Restart:  FORCE_RESTART=1 ./start_linux_primary.sh"
