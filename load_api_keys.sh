#!/bin/bash
# Load Etherscan API keys into ETHERSCAN_API_KEY (comma-separated).
# Search order:
#   1) $SEED_HUNTER_KEYS_FILE
#   2) ~/.seed_hunter_keys
#   3) ./seed_hunter_keys  (repo-bundled free keys)
#   4) ./.seed_hunter_keys
#
# File format: optional # comments; one or more lines of comma-separated keys.

_keys_from_file() {
  local f="$1"
  [[ -f "$f" ]] || return 1
  # strip comments, whitespace, blank lines; join with commas if multi-line
  local raw
  raw=$(grep -v '^[[:space:]]*#' "$f" | tr -d '[:space:]' | tr '\n' ',' | sed 's/,\+/,/g; s/^,//; s/,$//')
  [[ -n "$raw" ]] || return 1
  export ETHERSCAN_API_KEY="$raw"
  return 0
}

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || pwd)"

if [[ -n "${SEED_HUNTER_KEYS_FILE:-}" ]] && _keys_from_file "$SEED_HUNTER_KEYS_FILE"; then
  :
elif _keys_from_file "${HOME}/.seed_hunter_keys"; then
  :
elif _keys_from_file "${_SCRIPT_DIR}/seed_hunter_keys"; then
  :
elif _keys_from_file "${_SCRIPT_DIR}/.seed_hunter_keys"; then
  :
elif _keys_from_file "./seed_hunter_keys"; then
  :
fi

unset -f _keys_from_file 2>/dev/null || true
