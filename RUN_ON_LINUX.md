# Run Seed Hunter on Linux (Adaptive VM or any Linux box)

**Copy-paste this entire guide.**  
Repo: https://github.com/SirCharan/seed-hunter  
Defaults: **Preset A** (RPC balance + nonce) + **Preset F** (Etherscan enrich capital hits only).  
Keys: already in repo file `seed_hunter_keys` (11 free Etherscan keys).

---

## Step 0 — Requirements

- Linux machine with internet
- Python 3.10+ recommended
- `git`, `curl` or browser for GitHub

Check:
```bash
python3 --version
git --version
```

If Python is missing (Debian/Ubuntu):
```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git
```

---

## Step 1 — Clone the repo

```bash
cd ~
git clone https://github.com/SirCharan/seed-hunter.git
cd seed-hunter
```

Already cloned? Update instead:
```bash
cd ~/seed-hunter
git pull origin main
```

---

## Step 2 — Create virtualenv and install packages

```bash
cd ~/seed-hunter
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

You should stay in the venv for later commands (`(.venv)` in the prompt).  
Next time you open a new shell:
```bash
cd ~/seed-hunter
source .venv/bin/activate
```

---

## Step 3 — Make scripts executable

```bash
chmod +x start_linux_primary.sh kill_shards.sh status_shards.sh load_api_keys.sh
```

---

## Step 4 — (Optional) Confirm API keys load

Keys ship in `seed_hunter_keys`. Test load:
```bash
source ./load_api_keys.sh
echo "$ETHERSCAN_API_KEY" | tr ',' '\n' | grep -c .
```
Expected: `11` (or more if you add keys).

Optional home copy:
```bash
cp seed_hunter_keys ~/.seed_hunter_keys
chmod 600 ~/.seed_hunter_keys
```

---

## Step 5 — Start all 4 shards (main command)

```bash
cd ~/seed-hunter
source .venv/bin/activate
./start_linux_primary.sh
```

What this starts:
- 4 shards: `low_fwd`, `low_rev`, `high_fwd`, `high_rev`
- Default **4 workers per shard** (16 processes)
- Backend: RPC (`eth_getBalance` + `eth_getTransactionCount`)
- Etherscan only on capital hits (preset F)

---

## Step 6 — Verify it is working

```bash
./status_shards.sh
pgrep -af 'seed_shard.py'
tail -n 30 shard_low_fwd_w0.log
```

Live log:
```bash
tail -f shard_low_fwd_w0.log
```
(Stop watching with `Ctrl+C` — workers keep running.)

Healthy log looks like:
```text
[low_fwd w0] checked=1234 rate=12.34/s capital=0 activity=0 idx=...
```

Hits (if any):
```bash
wc -l found_wallets_capital.jsonl found_wallets_activity.jsonl 2>/dev/null
tail -n 5 found_wallets_capital.jsonl 2>/dev/null
```

---

## Step 7 — Keep running after SSH logout (recommended)

### Option A — tmux
```bash
sudo apt install -y tmux   # once
tmux new -s seed
cd ~/seed-hunter
source .venv/bin/activate
./start_linux_primary.sh
./status_shards.sh
```
Detach: press `Ctrl+b`, then `d`.  
Reattach later:
```bash
tmux attach -t seed
```

### Option B — hourly cron (restarts if dead; skips if already running)
```bash
crontab -e
```
Add this line (fix the path if needed):
```cron
0 * * * * cd /home/YOUR_USER/seed-hunter && /home/YOUR_USER/seed-hunter/.venv/bin/python -c "pass" 2>/dev/null; cd /home/YOUR_USER/seed-hunter && ./start_linux_primary.sh >> shard_cron.log 2>&1
```
Or simpler:
```cron
0 * * * * cd $HOME/seed-hunter && . .venv/bin/activate && ./start_linux_primary.sh >> shard_cron.log 2>&1
```

---

## Stop / restart

Stop all shard workers:
```bash
cd ~/seed-hunter
./kill_shards.sh
```

Hard restart (kill + start):
```bash
cd ~/seed-hunter
source .venv/bin/activate
FORCE_RESTART=1 ./start_linux_primary.sh
```

---

## Common settings (optional env vars)

Run **before** `./start_linux_primary.sh`:

```bash
# Defaults (A + F) — you usually need none of these
export BACKEND=rpc
export CHECK_MODE=both
export CHAINS=ethereum
export BATCH_SIZE=20
export ENRICH_ETHERSCAN=1
export SAVE_ACTIVITY=1
export WORKERS_PER_SHARD=4

# Custom Ethereum RPCs if public ones are slow/banned
export RPC_URLS_ETHEREUM='https://ethereum.publicnode.com,https://cloudflare-eth.com,https://eth.llamarpc.com'

./start_linux_primary.sh
```

**Important:** do **not** change `WORKERS_PER_SHARD` after progress files exist (`shard_*_w*.txt`), or coverage can skip/recheck indices.

---

## One-shot copy-paste (full setup + start)

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

---

## Troubleshooting

| Problem | Commands / fix |
|---------|----------------|
| `Permission denied` on scripts | `chmod +x *.sh` |
| `No module named aiohttp` | `source .venv/bin/activate && pip install -r requirements.txt` |
| `pgrep` shows 0 processes | `FORCE_RESTART=1 ./start_linux_primary.sh` then check log |
| Rate stuck at 0 | set `RPC_URLS_ETHEREUM=...` then restart |
| Disk full | `df -h .` ; delete huge old `*.log` if needed; never delete `shard_*_w*.txt` if you want resume |
| GitHub private clone fails | `gh auth login` or use SSH: `git clone git@github.com:SirCharan/seed-hunter.git` |
| Enrichment warning no keys | keys should load from `seed_hunter_keys`; run `source ./load_api_keys.sh` and check count |

See a log error:
```bash
tail -n 80 shard_low_fwd_w0.log
ls -la shard_*.log
```

---

## What files mean

| File | Purpose |
|------|---------|
| `start_linux_primary.sh` | Start all workers |
| `status_shards.sh` | Rate / progress / hits |
| `kill_shards.sh` | Stop workers |
| `seed_hunter_keys` | Free Etherscan keys |
| `shard_*_w*.txt` | Progress (keep for resume) |
| `shard_*_w*.log` | Per-worker logs |
| `found_wallets_capital.jsonl` | Balance > 0 hits |
| `found_wallets_activity.jsonl` | Nonce > 0 (maybe empty) |

---

## Honest note

Uniform search of all valid 12-word BIP39 seeds is space `2^128`. Expected funded hits ≈ 0. This stack is for **throughput and ops**, not guaranteed finds.

---

## More docs in this repo

- `README.md` — short overview  
- `HANDOFF.md` — agent handoff (Grok / Adaptive VM)  
- `LINUX_DEPLOY.md` — short deploy notes  
