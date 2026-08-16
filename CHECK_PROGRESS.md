# Check progress (after 1 day or anytime)

Copy-paste on Adaptive VM / Linux.  
Path assumed: `~/seed-hunter`.

Hits write **on the VM automatically**. GitHub only updates when you `git push` (manual).

---

## One-liner summary

```bash
cd ~/seed-hunter && source .venv/bin/activate && ./status_shards.sh && echo "procs=$(pgrep -af 'seed_shard.py' | wc -l | tr -d ' ')" && wc -l activity_seeds.jsonl found_wallets_activity.jsonl capital_seeds.jsonl found_wallets_capital.jsonl 2>/dev/null
```

---

## Full health check

```bash
cd ~/seed-hunter
source .venv/bin/activate

./status_shards.sh
pgrep -af 'seed_shard.py' | wc -l
tail -n 20 ensure_alive.log
```

### What healthy looks like

| Check | Good |
|--------|------|
| Process count | **16** (`SHARD_PROCS: 16`) |
| `AGG_RATE` | > 0 (often hundreds of addr/s) |
| `ensure_alive.log` | recent `ok procs=16` lines |
| Disk free | not full |
| `CAPITAL_HITS` | funded wallets (`balance > 0`) |
| `ACTIVITY_HITS` / `ACTIVITY_SEEDS` | wallets with past txs (`nonce > 0`) |

---

## Progress indices (how far shards moved)

```bash
cd ~/seed-hunter

# All progress files (never delete these)
ls -la shard_*_w*.txt

# Print each resume index
for f in shard_*_w*.txt; do echo -n "$f: "; cat "$f"; echo; done
```

`./status_shards.sh` also prints:

```text
PROGRESS low_fwd: ...
PROGRESS low_rev: ...
PROGRESS high_fwd: ...
PROGRESS high_rev: ...
```

Min/max are entropy indices, not “percent done.” Space is huge (`2^128`); after one day you will still be near the start of each stripe.

---

## Live log

```bash
cd ~/seed-hunter
tail -n 40 shard_low_fwd_w0.log

# Watch live (Ctrl+C stops watch only, not workers)
tail -f shard_low_fwd_w0.log
```

Healthy line looks like:

```text
[low_fwd w0] checked=… rate=…/s capital=0 activity=… idx=…
```

---

## Hits after 1 day

```bash
cd ~/seed-hunter
source .venv/bin/activate

wc -l found_wallets_activity.jsonl activity_seeds.jsonl \
      found_wallets_capital.jsonl capital_seeds.jsonl 2>/dev/null

# Newest activity (phrase + address + nonce)
tail -n 10 activity_seeds.jsonl 2>/dev/null

# Human table
python export_activity_summary.py

# Capital (funded) — often still 0
cat found_wallets_capital.jsonl 2>/dev/null || echo "no capital hits yet"
cat capital_seeds.jsonl 2>/dev/null || echo "no capital_seeds yet"
```

| File | Meaning |
|------|---------|
| `found_wallets_activity.jsonl` | Bulk activity hits |
| `activity_seeds.jsonl` | Clean archive (phrase + address + nonce) |
| `found_wallets_capital.jsonl` | Bulk capital hits |
| `capital_seeds.jsonl` | Clean capital archive |

**Activity ≠ money.** `nonce > 0` can be drained (balance 0). Only capital files mean funds found.

---

## Is it still writing? (quick liveness)

```bash
cd ~/seed-hunter
stat shard_low_fwd_w0.log
stat shard_low_fwd_w0.txt
sleep 15
stat shard_low_fwd_w0.log
stat shard_low_fwd_w0.txt
```

If mtime/size changes, workers are still progressing.

---

## Cron / keep-alive check

```bash
crontab -l
# expect:
# */5 * * * * /home/ubuntu/seed-hunter/ensure_alive.sh
# @reboot sleep 60 && /home/ubuntu/seed-hunter/ensure_alive.sh

systemctl is-active cron || systemctl is-active crond

tail -n 15 ~/seed-hunter/ensure_alive.log
```

Cron should produce `ok procs=16` around every 5 minutes when healthy.

---

## If something looks dead

```bash
cd ~/seed-hunter
source .venv/bin/activate

./ensure_alive.sh
./status_shards.sh
tail -n 50 shard_low_fwd_w0.log
pgrep -af 'seed_shard.py'
```

Still dead:

```bash
FORCE_RESTART=1 ./start_linux_primary.sh
./status_shards.sh
```

Progress resumes from `shard_*_w*.txt` (do **not** delete those).

---

## Push new hits to GitHub (manual — not automatic)

```bash
cd ~/seed-hunter
source .venv/bin/activate

git pull origin main
git add -f activity_seeds.jsonl found_wallets_activity.jsonl \
         capital_seeds.jsonl found_wallets_capital.jsonl
git status
git commit -m "chore: update hits after progress check" || true
git push origin main
```

---

## Related docs

- [RUN_ON_LINUX.md](./RUN_ON_LINUX.md) — full install, cron, errors  
- [HANDOFF.md](./HANDOFF.md) — agent handoff  
