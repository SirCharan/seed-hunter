# Seed Hunter

Multi-shard BIP39 enumerator — **RPC-first** Ethereum checks.

## Defaults: presets A + F

| Preset | Role |
|--------|------|
| **A** | Hot path: JSON-RPC `eth_getBalance` + `eth_getTransactionCount` (batched) |
| **F** | Cold path: Etherscan balance confirm **only on capital hits** |

Free Etherscan keys ship in **`seed_hunter_keys`** (auto-loaded).

---

## Full commands (start here)

**→ [RUN_ON_LINUX.md](./RUN_ON_LINUX.md)** — every step and copy-paste command to run on Linux / Adaptive VM.

### One-shot
```bash
cd ~
git clone https://github.com/SirCharan/seed-hunter.git
cd seed-hunter
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
chmod +x start_linux_primary.sh kill_shards.sh status_shards.sh load_api_keys.sh
./start_linux_primary.sh
./status_shards.sh
tail -f shard_low_fwd_w0.log
```

### Daily ops
```bash
cd ~/seed-hunter && source .venv/bin/activate
./status_shards.sh
./kill_shards.sh
FORCE_RESTART=1 ./start_linux_primary.sh
```

---

## Other docs

- **[RUN_ON_LINUX.md](./RUN_ON_LINUX.md)** — complete terminal runbook  
- **[HANDOFF.md](./HANDOFF.md)** — handoff for Grok / Adaptive VM  
- **[LINUX_DEPLOY.md](./LINUX_DEPLOY.md)** — short deploy notes  

## Honest EV

Uniform search over `2^128` valid 12-word BIP39 phrases has effectively **zero** expected funded hits. This project optimizes throughput and ops, not miracle odds.

## License

Private research tooling. Runtime hits/logs are gitignored; free-tier keys are intentionally in-repo.
