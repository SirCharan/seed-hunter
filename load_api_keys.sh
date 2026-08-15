#!/bin/bash
# Load Etherscan API keys from ~/.seed_hunter_keys (comma-separated).
KEYS_FILE="${SEED_HUNTER_KEYS_FILE:-$HOME/.seed_hunter_keys}"
if [[ -f "$KEYS_FILE" ]]; then
  export ETHERSCAN_API_KEY=$(grep -v '^#' "$KEYS_FILE" | tr -d '[:space:]' | head -1)
fi