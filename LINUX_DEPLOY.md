# Seed Hunter — Linux primary (Presets A + F)

## Default pipeline (A + F)
1. Enumerate BIP39 indices in **4 parity-split shards** (full `2^128` once).
2. Derive ETH address `m/44'/60'/0'/0/0`.
3. **Preset A — hot path:** public JSON-RPC batch  
   - `eth_getBalance` → capital  
   - `eth_getTransactionCount` → past outgoing activity (nonce)
4. **Preset F — cold path:** Etherscan **only on capital hits** (`balance > 0`) to confirm explorer balance.

## Outputs
| File | Contents |
|------|----------|
| `found_wallets_capital.jsonl` | `balance > 0` (+ optional `etherscan_balance_eth` if F) |
| `found_wallets_activity.jsonl` | `nonce > 0` (may be drained) |
| `shard_*_w*.txt` | Progress only — **keep for resume** |

## Quick start
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Keys: seed_hunter_keys in repo (auto-loaded). Optional home override:
#   cp seed_hunter_keys ~/.seed_hunter_keys && chmod 600 ~/.seed_hunter_keys

chmod +x start_linux_primary.sh kill_shards.sh status_shards.sh
./start_linux_primary.sh
./status_shards.sh
```

## Env knobs
```bash
# Defaults = A + F
BACKEND=rpc CHECK_MODE=both CHAINS=ethereum ENRICH_ETHERSCAN=1 SAVE_ACTIVITY=1

# Custom ETH RPCs
export RPC_URLS_ETHEREUM='https://ethereum.publicnode.com,https://cloudflare-eth.com'

# Hard restart
FORCE_RESTART=1 ./start_linux_primary.sh
```

**Keep `WORKERS_PER_SHARD` fixed** after first run (default `4`).

## Honest EV
Uniform search over `2^128` valid phrases has effectively zero expected funded hits.  
This stack optimizes **throughput**, not miracle odds.

For Adaptive VM handoff, see **[HANDOFF.md](./HANDOFF.md)**.
