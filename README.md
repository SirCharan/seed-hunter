# Seed Hunter

Multi-shard BIP39 enumerator — **RPC-first** Ethereum checks.

## Defaults: presets A + F

| Preset | Role |
|--------|------|
| **A** | Hot path: JSON-RPC `eth_getBalance` + `eth_getTransactionCount` (batched) |
| **F** | Cold path: Etherscan balance confirm **only on capital hits** |

Free Etherscan keys ship in **`seed_hunter_keys`** (auto-loaded).

### Hit archives (committed)

| File | When |
|------|------|
| `found_wallets_activity.jsonl` + **`activity_seeds.jsonl`** | `nonce > 0` (phrase + address always) |
| `found_wallets_capital.jsonl` + `capital_seeds.jsonl` | `balance > 0` (phrase + address + balance) |

```bash
python export_activity_summary.py              # table of phrase + address
python export_activity_summary.py --migrate --capital   # backfill archives
```

---

## Full commands (start here)

**→ [RUN_ON_LINUX.md](./RUN_ON_LINUX.md)** — **main guide** for Adaptive VM / Linux: install, daily ops, git pull, migrate & push hits, keep-alive, config env table, **large ERROR HANDLING** section, health checklist.

**→ [CHECK_PROGRESS.md](./CHECK_PROGRESS.md)** — after 1 day (or anytime): status, rate, progress files, hits, cron, push to GitHub.

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

### Keep alive forever (repo script + cron)
```bash
cd ~/seed-hunter
git pull origin main
chmod +x ensure_alive.sh
./ensure_alive.sh
# crontab -e  →  see RUN_ON_LINUX.md section 7
# */5 * * * * /home/ubuntu/seed-hunter/ensure_alive.sh
# @reboot sleep 60 && /home/ubuntu/seed-hunter/ensure_alive.sh
```

---

## Other docs

- **[RUN_ON_LINUX.md](./RUN_ON_LINUX.md)** — complete terminal runbook (commands + errors)  
- **[HANDOFF.md](./HANDOFF.md)** — handoff for Grok / Adaptive VM  
- **[LINUX_DEPLOY.md](./LINUX_DEPLOY.md)** — short deploy notes  

## Honest EV

Uniform search over `2^128` valid 12-word BIP39 phrases has effectively **zero** expected funded hits. This project optimizes throughput and ops, not miracle odds.

## License

Private research tooling. Progress/logs are gitignored; activity/capital hit archives are intentionally tracked. Free-tier keys are intentionally in-repo.
