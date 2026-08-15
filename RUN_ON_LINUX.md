# Run Seed Hunter on Linux (Adaptive VM)

**Single source of truth** for humans on Adaptive VM / any Linux box.  
Copy-paste ready. Ordered steps. Full error section at the bottom.

| | |
|--|--|
| **Repo** | https://github.com/SirCharan/seed-hunter (private) |
| **Branch** | `main` |
| **Defaults** | Presets **A + F** |
| **Keys** | Repo file `seed_hunter_keys` (free Etherscan keys; auto-loaded) |

Assume install path `~/seed-hunter`. Adjust if you cloned elsewhere.

---

## 1. What this setup is

Four parity-split shards walk the BIP39 index space once (full `2^128` coverage when all workers run). Each worker derives ETH address `m/44'/60'/0'/0/0` and checks it on-chain.

| Preset | Role |
|--------|------|
| **A (hot path)** | Public JSON-RPC batch: `eth_getBalance` (capital) + `eth_getTransactionCount` (nonce / past activity). Default chain: `ethereum`. |
| **F (cold path)** | Etherscan balance confirm **only when balance > 0** (capital hit). Keys from `seed_hunter_keys`. |

| Output | Meaning |
|--------|---------|
| `found_wallets_capital.jsonl` | Bulk: `balance > 0` (+ optional Etherscan fields) |
| `found_wallets_activity.jsonl` | Bulk: `nonce > 0` (may be empty balance) — includes phrase |
| `capital_seeds.jsonl` | Clean capital archive (phrase + address + balance) |
| `activity_seeds.jsonl` | Clean activity archive (phrase + address + nonce) |
| `shard_*_w*.txt` | Progress only — **never delete** if you want resume |
| `shard_*_w*.log` | Per-worker logs |

Default launch: **4 shards × 4 workers = 16 processes** (`WORKERS_PER_SHARD=4`).  
**Do not change `WORKERS_PER_SHARD` after progress files exist** (stripe reshuffle → gaps/duplicates).

---

## 2. One-shot first install

Run once on a fresh Adaptive VM / Linux box:

```bash
# Requirements check
python3 --version
git --version

# If Python/git missing (Debian/Ubuntu):
# sudo apt update && sudo apt install -y python3 python3-venv python3-pip git

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
tail -n 30 shard_low_fwd_w0.log
```

**Private repo auth:** if `git clone` fails, see [ERROR HANDLING → git clone/pull auth](#git-clonepull-auth-fails-private-repo).

Optional — confirm keys load (expect ~11):

```bash
source ./load_api_keys.sh
echo "$ETHERSCAN_API_KEY" | tr ',' '\n' | grep -c .
```

---

## 3. Daily / after reboot

```bash
cd ~/seed-hunter
source .venv/bin/activate

./status_shards.sh

# If SHARD_PROCS is 0 (or less than expected), start again:
./start_linux_primary.sh

# Confirm
./status_shards.sh
pgrep -af 'seed_shard.py' | head
tail -n 20 shard_low_fwd_w0.log
```

`./start_linux_primary.sh` is **idempotent**: skips workers already running. Safe to re-run after reboot or SSH reconnect.

---

## 4. Pull latest code from GitHub

```bash
cd ~/seed-hunter
source .venv/bin/activate

# Prefer stopping workers only if you know code changed under the workers:
# ./kill_shards.sh

git pull origin main

# Reinstall deps if requirements.txt changed
pip install -r requirements.txt

chmod +x start_linux_primary.sh kill_shards.sh status_shards.sh load_api_keys.sh
```

### When to use `FORCE_RESTART`

| Situation | Action |
|-----------|--------|
| Only docs changed / no worker code change | `./start_linux_primary.sh` (fills any missing processes) |
| `seed_shard.py`, `rpc_checker.py`, `start_linux_primary.sh`, or defaults changed | **Hard restart:** `FORCE_RESTART=1 ./start_linux_primary.sh` |
| Env vars changed (`RPC_URLS_*`, `BATCH_SIZE`, `BACKEND`, …) | **Hard restart** so new env applies |
| Progress files exist and you only rebooted | Soft start is enough: `./start_linux_primary.sh` |

```bash
FORCE_RESTART=1 ./start_linux_primary.sh
./status_shards.sh
```

---

## 5. Migrate & push activity/capital hits to GitHub

Hits write **phrase + address** (and nonce/balance) into tracked jsonl files so you can archive them on GitHub.

| File | Purpose |
|------|---------|
| `found_wallets_activity.jsonl` | Full bulk activity records |
| `activity_seeds.jsonl` | Clean activity archive |
| `found_wallets_capital.jsonl` | Full bulk capital records |
| `capital_seeds.jsonl` | Clean capital archive |

### Migrate (backfill clean archives from bulk files)

Safe to re-run (idempotent by address/chain/nonce or balance):

```bash
cd ~/seed-hunter
source .venv/bin/activate

python export_activity_summary.py --migrate --capital
python export_activity_summary.py
```

### Commit and push

```bash
cd ~/seed-hunter
source .venv/bin/activate

python export_activity_summary.py --migrate --capital

git pull origin main

git add found_wallets_activity.jsonl found_wallets_capital.jsonl \
        activity_seeds.jsonl capital_seeds.jsonl

git status
git commit -m "chore: archive activity/capital seed hits from Linux VM"
git push origin main
```

### One-liner (after workers are already running)

```bash
cd ~/seed-hunter && source .venv/bin/activate && \
python export_activity_summary.py --migrate --capital && \
git pull origin main && \
git add found_wallets_activity.jsonl found_wallets_capital.jsonl \
        activity_seeds.jsonl capital_seeds.jsonl && \
git commit -m "chore: archive activity/capital seed hits from Linux VM" && \
git push origin main
```

If commit says **nothing to commit**, there are no new lines (see [ERROR HANDLING](#nothing-to-commit-when-migrating-hits)).

**Do not commit:** `shard_*.txt`, `shard_*.log`, `.venv/` (gitignored).  
**Do commit hit archives** when you have new rows (owner preference).

---

## 6. View hits

```bash
cd ~/seed-hunter
source .venv/bin/activate

# Counts
wc -l found_wallets_capital.jsonl found_wallets_activity.jsonl \
      activity_seeds.jsonl capital_seeds.jsonl 2>/dev/null

# Raw tails
tail -n 5 found_wallets_activity.jsonl 2>/dev/null
tail -n 5 found_wallets_capital.jsonl 2>/dev/null
cat activity_seeds.jsonl 2>/dev/null
cat capital_seeds.jsonl 2>/dev/null

# Human table (phrase + address) from activity_seeds.jsonl
python export_activity_summary.py

# Status script also prints hit counts
./status_shards.sh
```

**Normal:** activity can be non-zero while capital stays empty (used wallets with zero balance). See [ERROR HANDLING](#activity-hits-but-capital-empty-normal).

---

## 7. Keep alive

Workers are started with `nohup` and survive SSH logout. Still useful:

### A) tmux (recommended for interactive ops)

```bash
# Once
sudo apt install -y tmux

tmux new -s seed
cd ~/seed-hunter
source .venv/bin/activate
./start_linux_primary.sh
./status_shards.sh
```

- **Detach:** `Ctrl+b` then `d`
- **Reattach:** `tmux attach -t seed`
- **List sessions:** `tmux ls`

### B) Optional hourly cron (restarts dead workers; skips if already running)

```bash
crontab -e
```

Add (replace path if needed):

```cron
0 * * * * cd $HOME/seed-hunter && . .venv/bin/activate && ./start_linux_primary.sh >> shard_cron.log 2>&1
```

Check cron log:

```bash
tail -n 50 ~/seed-hunter/shard_cron.log
```

---

## 8. Stop / restart

```bash
cd ~/seed-hunter
source .venv/bin/activate

# Stop all seed_shard workers
./kill_shards.sh
pgrep -af 'seed_shard.py' || echo "all stopped"

# Soft start (only missing workers)
./start_linux_primary.sh

# Hard restart (kill everything, then start)
FORCE_RESTART=1 ./start_linux_primary.sh

./status_shards.sh
```

---

## 9. Config env vars

Export **before** `./start_linux_primary.sh`. Existing workers keep old env until hard restart.

| Env | Default | Meaning |
|-----|---------|---------|
| `BACKEND` | `rpc` | Hot path: `rpc` or `etherscan` |
| `CHECK_MODE` | `both` | `balance` \| `nonce` \| `both` (A = both) |
| `CHAINS` | `ethereum` | Comma list, e.g. `ethereum,polygon` |
| `BATCH_SIZE` | `20` | Addresses per JSON-RPC batch |
| `ENRICH_ETHERSCAN` | `1` | Preset F: Etherscan on capital hits (`0` = off) |
| `WORKERS_PER_SHARD` | `4` | Workers per shard — **keep fixed after first run** |
| `RPC_URLS_ETHEREUM` | public list | Comma-separated ETH RPC endpoints |
| `FORCE_RESTART` | `0` | `1` = kill all shards then start |

Also useful (less common):

| Env | Default | Meaning |
|-----|---------|---------|
| `SAVE_ACTIVITY` | `1` | Write `nonce > 0` to activity files |
| `MAX_CONCURRENT` | `8` | Concurrent RPC work per worker |
| `RPC_RPS` | `20` | Soft RPC rate target |
| `RATE_PER_KEY` | `2.5` | Etherscan per-key rate (backend/enrich) |

Example custom RPC + hard restart:

```bash
cd ~/seed-hunter
source .venv/bin/activate

export RPC_URLS_ETHEREUM='https://ethereum.publicnode.com,https://cloudflare-eth.com,https://eth.llamarpc.com'
export BATCH_SIZE=20
export WORKERS_PER_SHARD=4

FORCE_RESTART=1 ./start_linux_primary.sh
./status_shards.sh
```

---

## 10. ERROR HANDLING

Symptom → cause → exact fix. Run from `~/seed-hunter` unless noted.

---

### git clone/pull auth fails (private repo)

**Symptom:** `Repository not found`, `Authentication failed`, `could not read Username`.

**Cause:** Private repo; no GitHub credentials on the VM.

**Fix (pick one):**

```bash
# A) GitHub CLI (recommended)
# sudo apt install -y gh   # if needed
gh auth login
# follow prompts: HTTPS, login via browser/token

cd ~
git clone https://github.com/SirCharan/seed-hunter.git

# B) SSH (if you have a key on the VM added to GitHub)
git clone git@github.com:SirCharan/seed-hunter.git

# C) HTTPS with personal access token when prompted
# Username: your GitHub user
# Password: paste PAT (not account password)
```

Pull later:

```bash
cd ~/seed-hunter
git pull origin main
```

---

### Permission denied on scripts

**Symptom:** `bash: ./start_linux_primary.sh: Permission denied`

**Cause:** Scripts not executable.

**Fix:**

```bash
cd ~/seed-hunter
chmod +x start_linux_primary.sh kill_shards.sh status_shards.sh load_api_keys.sh
./start_linux_primary.sh
```

---

### ModuleNotFoundError / no aiohttp

**Symptom:** `ModuleNotFoundError: No module named 'aiohttp'` (or `eth_account`, `mnemonic`).

**Cause:** venv not activated, or deps not installed.

**Fix:**

```bash
cd ~/seed-hunter
source .venv/bin/activate
which python
# should show .../seed-hunter/.venv/bin/python

pip install -U pip
pip install -r requirements.txt

# If .venv is broken, recreate:
# rm -rf .venv
# python3 -m venv .venv
# source .venv/bin/activate
# pip install -r requirements.txt

FORCE_RESTART=1 ./start_linux_primary.sh
```

---

### No such file seed-hunter

**Symptom:** `cd: seed-hunter: No such file or directory`

**Cause:** Wrong directory or never cloned.

**Fix:**

```bash
# Find it
ls -d ~/seed-hunter /tmp/seed-hunter 2>/dev/null
find ~ -maxdepth 3 -type d -name 'seed-hunter' 2>/dev/null

# Or clone fresh
cd ~
git clone https://github.com/SirCharan/seed-hunter.git
cd seed-hunter
```

---

### start script does nothing / 0 processes

**Symptom:** `./start_linux_primary.sh` prints `started=0` / `already_running=…`, or `status_shards.sh` shows `SHARD_PROCS: 0`.

**Cause:** Workers crash immediately, wrong Python, or start skipped wrongly.

**Fix:**

```bash
cd ~/seed-hunter
source .venv/bin/activate

# See if anything is running
pgrep -af 'seed_shard.py' || echo "none"

# Read first errors
ls -la shard_*.log 2>/dev/null | head
tail -n 80 shard_low_fwd_w0.log

# Hard restart with venv python
FORCE_RESTART=1 ./start_linux_primary.sh
sleep 3
./status_shards.sh
pgrep -af 'seed_shard.py' | wc -l
```

If still 0, run one worker in foreground to see the error:

```bash
source .venv/bin/activate
source ./load_api_keys.sh
.venv/bin/python seed_shard.py \
  --shard low_fwd --workers 4 --worker-id 0 \
  --backend rpc --check-mode both --chains ethereum \
  --batch-size 20 --capital-only --save-activity --enrich-etherscan
```

---

### rate = 0 stuck

**Symptom:** Log shows `rate=0.00/s` for minutes; `AGG_RATE: 0.00` in status.

**Cause:** All public RPCs failing, rate-limited, or network blocked.

**Fix:**

```bash
cd ~/seed-hunter
source .venv/bin/activate

# Check logs for RPC errors
grep -iE 'error|limit|timeout|429|403' shard_low_fwd_w0.log | tail -n 30

# Override with better public endpoints (or your Alchemy/Infura URL)
export RPC_URLS_ETHEREUM='https://ethereum.publicnode.com,https://cloudflare-eth.com,https://eth.llamarpc.com,https://rpc.ankr.com/eth'

FORCE_RESTART=1 ./start_linux_primary.sh
sleep 15
./status_shards.sh
tail -n 5 shard_low_fwd_w0.log
```

---

### rate limit / RPC errors in log

**Symptom:** Log lines with `429`, `rate limit`, `too many requests`, connection errors, empty results.

**Cause:** Public RPC throttling or bad endpoint.

**Fix:**

```bash
cd ~/seed-hunter
source .venv/bin/activate

# Lower pressure slightly + rotate endpoints
export RPC_URLS_ETHEREUM='https://ethereum.publicnode.com,https://cloudflare-eth.com'
export BATCH_SIZE=10
export RPC_RPS=10

FORCE_RESTART=1 ./start_linux_primary.sh
sleep 20
./status_shards.sh
```

Prefer a free Alchemy/Infura HTTP URL in `RPC_URLS_ETHEREUM` for 24/7 stability.

---

### enrichment warn no keys

**Symptom:** `WARN: no ETHERSCAN_API_KEY — enrichment off (preset A RPC still runs).`

**Cause:** Keys not loaded; preset F off, but **RPC hot path still works**.

**Fix:**

```bash
cd ~/seed-hunter
source .venv/bin/activate

# Keys ship in repo
ls -la seed_hunter_keys
source ./load_api_keys.sh
echo "$ETHERSCAN_API_KEY" | tr ',' '\n' | grep -c .

# Optional home override
cp seed_hunter_keys ~/.seed_hunter_keys
chmod 600 ~/.seed_hunter_keys

FORCE_RESTART=1 ./start_linux_primary.sh
# start script should print etherscan_keys=N (N > 0)
```

---

### git push rejected / need pull first

**Symptom:** `Updates were rejected because the remote contains work that you do not have locally`.

**Cause:** Remote `main` moved (e.g. another machine pushed).

**Fix:**

```bash
cd ~/seed-hunter
git pull origin main
# resolve conflicts if any (hit jsonl: usually keep both lines / accept merge)

git add found_wallets_activity.jsonl found_wallets_capital.jsonl \
        activity_seeds.jsonl capital_seeds.jsonl
git commit -m "chore: archive activity/capital seed hits from Linux VM" || true
git push origin main
```

If pull creates a merge commit and hit files conflict, prefer keeping **all unique lines** from both sides (append-only logs).

---

### nothing to commit when migrating hits

**Symptom:** `nothing to commit, working tree clean` after migrate.

**Cause:** Clean archives already match bulk files, or no hits exist yet.

**Fix:**

```bash
cd ~/seed-hunter
source .venv/bin/activate

# Are there any hits at all?
wc -l found_wallets_activity.jsonl found_wallets_capital.jsonl \
      activity_seeds.jsonl capital_seeds.jsonl 2>/dev/null

python export_activity_summary.py --migrate --capital
git status

# If files have lines but git says clean, they are already committed.
# If all counts are 0, there is nothing to push yet — keep hunting.
```

---

### disk full

**Symptom:** `No space left on device`; workers die; cannot write logs.

**Cause:** Large logs or leftover dumps.

**Fix:**

```bash
cd ~/seed-hunter
df -h .

# Safe to truncate/delete logs (progress is in .txt, not .log)
# NEVER delete shard_*_w*.txt if you want resume
du -sh shard_*.log 2>/dev/null | sort -h | tail
: > shard_low_fwd_w0.log   # example truncate one log
# or: rm -f shard_*.log

# Remove accidental huge dumps if present
rm -f checksum_valid*.jsonl 2>/dev/null

df -h .
FORCE_RESTART=1 ./start_linux_primary.sh
```

---

### OOM / workers dying

**Symptom:** `SHARD_PROCS` drops over time; `dmesg` shows OOM killer; free RAM near 0.

**Cause:** Too many workers for VM RAM.

**Fix (short term — restart with fewer workers only if you accept re-stripe):**

```bash
free -h
dmesg -T 2>/dev/null | tail -n 30 | grep -i -E 'oom|killed' || true

cd ~/seed-hunter
source .venv/bin/activate
./kill_shards.sh

# Only lower WORKERS_PER_SHARD on a FRESH install, or accept gaps/duplicates.
# If progress files already exist with workers=4, prefer keeping 4 and
# reducing BATCH_SIZE / MAX_CONCURRENT instead:

export BATCH_SIZE=10
export MAX_CONCURRENT=4
FORCE_RESTART=1 ./start_linux_primary.sh
```

If you **must** change `WORKERS_PER_SHARD` after progress exists, understand coverage will reshuffle — see next item.

---

### changed WORKERS_PER_SHARD by mistake

**Symptom:** You ran with `WORKERS_PER_SHARD=8` (or 2) after already having `shard_*_w*.txt` from 4.

**Cause:** Stripe step = `2 * workers`; changing workers remaps which indices each process covers → gaps and duplicates.

**Fix:**

```bash
cd ~/seed-hunter
source .venv/bin/activate
./kill_shards.sh

# Go back to the original worker count (default 4) and hard restart
export WORKERS_PER_SHARD=4
FORCE_RESTART=1 ./start_linux_primary.sh
./status_shards.sh
```

Do **not** delete progress files unless you intentionally want a full restart from index 0.

---

### log shows Traceback

**Symptom:** Python stack trace in `shard_*.log`.

**Cause:** Bug, bad env, missing dep, or RPC parse error.

**Fix:**

```bash
cd ~/seed-hunter
source .venv/bin/activate

# Collect evidence
tail -n 120 shard_low_fwd_w0.log
grep -n 'Traceback\|Error\|Exception' shard_*.log | tail -n 40

# Common recovery
pip install -r requirements.txt
git pull origin main
FORCE_RESTART=1 ./start_linux_primary.sh
sleep 5
tail -n 30 shard_low_fwd_w0.log
```

If Traceback persists after pull + reinstall, paste the traceback from one log when asking for help.

---

### activity hits but capital empty (normal)

**Symptom:** `ACTIVITY_HITS > 0` but `CAPITAL_HITS: 0`.

**Cause:** **Normal.** Activity = `nonce > 0` (wallet sent txs sometime). Capital = `balance > 0` now. Many used wallets are drained.

**What to do:**

```bash
# Inspect activity (phrase + address + nonce)
python export_activity_summary.py
tail -n 5 found_wallets_activity.jsonl

# Still push activity archives to GitHub if you want them saved
python export_activity_summary.py --migrate --capital
git add found_wallets_activity.jsonl activity_seeds.jsonl
git commit -m "chore: archive activity seed hits from Linux VM" || true
git push origin main
```

No fix required for “empty capital.”

---

### tmux session lost

**Symptom:** `tmux attach -t seed` → `no sessions` / `can't find session`.

**Cause:** VM reboot or tmux server killed. **Workers may still be running** via nohup.

**Fix:**

```bash
# Are workers still alive?
pgrep -af 'seed_shard.py' || echo "none"

cd ~/seed-hunter
source .venv/bin/activate
./status_shards.sh

# If 0 processes, start again
./start_linux_primary.sh

# New tmux for ops
tmux new -s seed
```

---

### venv not activated

**Symptom:** Wrong Python; missing packages; `python` is system Python.

**Cause:** New shell after SSH; forgot `source .venv/bin/activate`.

**Fix:**

```bash
cd ~/seed-hunter
source .venv/bin/activate
# prompt should show (.venv)
which python
# .../seed-hunter/.venv/bin/python

# Start script also prefers .venv/bin/python even if you forget,
# but export_activity_summary.py and pip need the venv.
```

---

## 11. Health checklist

What “good” looks like after `./status_shards.sh` and a log peek:

| Check | Healthy |
|-------|---------|
| `SHARD_PROCS` | **16** with default `WORKERS_PER_SHARD=4` (4 shards × 4) |
| `AGG_RATE` | **> 0** addr/s (tens aggregate is a solid small-VM target; public RPC varies) |
| Log line | `[low_fwd w0] checked=… rate=…/s capital=… activity=… idx=…` with rising `checked` / `idx` |
| Disk | `df -h .` shows free space |
| Progress | `PROGRESS low_fwd: n=4 …` (and other shards) advancing over time |
| Keys (optional F) | start banner `etherscan_keys` > 0 |

Quick verify:

```bash
cd ~/seed-hunter
source .venv/bin/activate
./status_shards.sh
pgrep -af 'seed_shard.py' | wc -l
tail -n 5 shard_low_fwd_w0.log
```

Live watch (Ctrl+C stops watch only; workers keep running):

```bash
tail -f shard_low_fwd_w0.log
```

---

## 12. Honest EV note

Uniform search over all valid 12-word BIP39 phrases is space **2^128**. Expected funded hits for a uniform scan is effectively **zero**. This stack optimizes **throughput, resume, and ops reliability** on a Linux Adaptive VM — not miracle odds of finding capital. Treat any hit as extremely rare and secret; push hit archives only to your private repo as intended.

---

## Quick reference — files that matter

| Path | Role |
|------|------|
| `start_linux_primary.sh` | Launch presets A+F |
| `status_shards.sh` | Rate / progress / hit counts |
| `kill_shards.sh` | Stop all shard workers |
| `seed_shard.py` | Main worker |
| `rpc_checker.py` | JSON-RPC batch client |
| `export_activity_summary.py` | Table + migrate bulk → archive |
| `seed_hunter_keys` | Free Etherscan keys |
| `activity_seeds.jsonl` | Clean activity archive (tracked) |
| `capital_seeds.jsonl` | Clean capital archive (tracked) |

## Other docs

- **[README.md](./README.md)** — short overview; points here for full commands  
- **[HANDOFF.md](./HANDOFF.md)** — agent handoff (Grok / Adaptive VM)  
- **[LINUX_DEPLOY.md](./LINUX_DEPLOY.md)** — short deploy notes  
