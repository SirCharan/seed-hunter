# Seed Hunter

Multi-shard BIP39 enumerator with **RPC-first** Ethereum checks.

## Defaults: presets A + F

| Preset | Role |
|--------|------|
| **A** | Hot path: JSON-RPC `eth_getBalance` + `eth_getTransactionCount` (batched) |
| **F** | Cold path: Etherscan balance confirm **only on capital hits** (keys optional) |

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Free Etherscan keys ship in seed_hunter_keys (preset F enrichment)
./start_linux_primary.sh
./status_shards.sh
```

Bundled keys: `seed_hunter_keys` (loaded automatically). Override with `~/.seed_hunter_keys` or `SEED_HUNTER_KEYS_FILE`.

## Docs

- **[HANDOFF.md](./HANDOFF.md)** — full handoff for Grok / Adaptive VM Linux
- **[LINUX_DEPLOY.md](./LINUX_DEPLOY.md)** — short deploy notes

## Honest EV

Uniform search over `2^128` valid 12-word BIP39 phrases has effectively **zero** expected funded hits. This project optimizes throughput and ops, not miracle odds.

## License

Private research tooling. Do not commit API keys or found phrases.
