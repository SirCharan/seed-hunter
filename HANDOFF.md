# Handoff: Seed Hunter → Grok on Adaptive VM (Linux)

**Audience:** Grok (or any coding agent) continuing work on a **Linux Adaptive VM**.  
**Owner GitHub:** [SirCharan](https://github.com/SirCharan)  
**Repo:** `https://github.com/SirCharan/seed-hunter` (clone this first)  
**Date context:** 2026-08-15  

---

## Mission (what “done” looks like)

1. Repo cloned on the Adaptive VM Linux box.
2. venv + deps installed; optional Etherscan keys for **preset F**.
3. **4 shard workers** running 24/7 with **preset A + F**:
   - **A:** RPC `eth_getBalance` + `eth_getTransactionCount` (batched), chain default `ethereum`
   - **F:** Etherscan enrichment **only when capital hit** (balance > 0)
4. Progress resumes from `shard_*_w*.txt`; capital hits in `found_wallets_capital.jsonl`.
5. Agent can diagnose stalls (RPC rate limits, dead processes) and restart safely.

**Not the mission:** promise of finding funded wallets. Space is `2^128` valid 12-word BIP39 phrases — EV ≈ 0 for uniform search. Optimize **throughput and reliability**.

---

## Architecture (current, do not reintroduce old pipelines)

```
seed_shard.py  ×  4 shards × WORKERS_PER_SHARD
       │
       ├─ derive m/44'/60'/0'/0/0  (seed_hunter_async helpers)
       ├─ rpc_checker.py  JSON-RPC batch  [HOT PATH — A]
       │     eth_getBalance + eth_getTransactionCount
       └─ Etherscan V2 balance  [COLD PATH — F, capital hits only]

DO NOT start: seed_stream.py, seed_hunter_random.py, seed_hunter_async derive-only,
              seed_checker_multichain as bulk hot path, or dump checksum_valid.jsonl.
```

| Shard | Range | Dir | Parity |
|-------|--------|-----|--------|
| `low_fwd` | [0, mid) | + | even |
| `low_rev` | [0, mid) | − | odd |
| `high_fwd` | [mid, end) | + | even |
| `high_rev` | [mid, end) | − | odd |

**Stripe stability:** `WORKERS_PER_SHARD` must stay **constant** after first run (default `4`). Changing it reshuffles indices → gaps/duplicates.

---

## Bootstrap on Adaptive VM (run these)

```bash
# 1) Clone
git clone https://github.com/SirCharan/seed-hunter.git
cd seed-hunter

# 2) Python env
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt

# 3) Optional but recommended (preset F)
#    Free keys: https://etherscan.io/apis  — 10–20 keys ideal for enrichment + future use
mkdir -p "$HOME"
# Put comma-separated keys in one line (NO quotes in file content issues):
#   key1,key2,key3
nano ~/.seed_hunter_keys
chmod 600 ~/.seed_hunter_keys

# 4) Launch primary (A+F defaults)
chmod +x start_linux_primary.sh kill_shards.sh status_shards.sh load_api_keys.sh
./start_linux_primary.sh

# 5) Verify
./status_shards.sh
tail -f shard_low_fwd_w0.log
```

### Expected healthy log line
```text
[low_fwd w0] checked=… rate=…/s capital=0 activity=0 idx=…
```
Rate depends on public RPC quality; tens of addr/s aggregate is a good target on a small VM.

### If processes die after SSH logout
Use `nohup` (already in start script) or:
```bash
# optional: keep session with tmux
tmux new -s seed
./start_linux_primary.sh
# Ctrl-b d to detach
```

### Cron re-start (idempotent — skips already running)
```bash
crontab -e
# every hour
0 * * * * cd /path/to/seed-hunter && ./start_linux_primary.sh >> shard_cron.log 2>&1
```

---

## Config reference (env)

| Env | Default (A+F) | Meaning |
|-----|----------------|---------|
| `BACKEND` | `rpc` | Hot path |
| `CHECK_MODE` | `both` | balance + nonce |
| `CHAINS` | `ethereum` | RPC chains |
| `BATCH_SIZE` | `20` | Addrs per JSON-RPC batch |
| `SAVE_ACTIVITY` | `1` | Write nonce>0 to activity file |
| `ENRICH_ETHERSCAN` | `1` | Preset F on capital hits |
| `WORKERS_PER_SHARD` | `4` | **Do not change after start** |
| `FORCE_RESTART` | `0` | `1` = kill all shards then start |
| `RPC_URLS_ETHEREUM` | public list | Override ETH RPCs |

Keys file: `~/.seed_hunter_keys` (or `SEED_HUNTER_KEYS_FILE`) — loaded by `load_api_keys.sh`.

---

## Ops cheatsheet

```bash
./status_shards.sh          # rates, progress, hit counts
./kill_shards.sh            # stop all seed_shard workers
FORCE_RESTART=1 ./start_linux_primary.sh

# Hits
wc -l found_wallets_capital.jsonl found_wallets_activity.jsonl
tail -n 5 found_wallets_capital.jsonl
```

| Symptom | Likely cause | Action |
|---------|--------------|--------|
| rate ≈ 0 | RPC ban / all endpoints down | Set `RPC_URLS_ETHEREUM`, restart |
| processes = 0 | OOM / crash | `dmesg` / free -h; lower `WORKERS_PER_SHARD` only on **fresh** progress or accept re-stripe |
| enrich warn | no keys | Add `~/.seed_hunter_keys` for F |
| disk full | old jsonl dumps | Delete `checksum_valid*.jsonl` / huge logs only |

---

## Files that matter

| Path | Role |
|------|------|
| `seed_shard.py` | Main worker |
| `rpc_checker.py` | JSON-RPC batch client |
| `seed_checker_multichain.py` | Etherscan client + `append_hit` |
| `seed_hunter_async.py` | BIP39 index → phrase → address helpers |
| `start_linux_primary.sh` | Launch A+F |
| `kill_shards.sh` / `status_shards.sh` | Ops |
| `LINUX_DEPLOY.md` | Short deploy notes |
| `HANDOFF.md` | This file |

**Never commit:** `~/.seed_hunter_keys`, `found_wallets_*.jsonl`, `shard_*.txt`, `shard_*.log`, `.venv/`

---

## Suggested next improvements (if agent has time)

Priority order:

1. **RPC health metrics** in status (fail counts per endpoint).
2. **Alchemy/Infura free RPC** via env for stable 24/7 (better than pure public).
3. **Multicall3** balance batch for multi-chain preset C.
4. **Alert on capital hit** (telegram/webhook) — only if user wants.
5. Do **not** re-enable phrase dumps or random workers unless user asks.

---

## Security / ethics notes for the agent

- Treat found phrases as **extreme secrets**; never print to public logs or commit.
- Do not exfiltrate keys or hits off the VM except where the user directs.
- This tool is for the owner’s research; do not help weaponize against third parties.

---

## One-shot resume prompt (paste to Grok on the VM)

```text
Continue Seed Hunter handoff from SirCharan/seed-hunter HANDOFF.md.
Presets A+F: RPC balance+nonce hot path, Etherscan enrich capital hits only.
Clone/pull latest, ensure 4 shards running on this Linux Adaptive VM,
do not change WORKERS_PER_SHARD if progress files exist, no phrase dumps,
report status_shards + any blockers.
```
