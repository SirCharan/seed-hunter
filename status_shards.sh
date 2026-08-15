#!/bin/bash
set -uo pipefail
cd "$(dirname "$0")"
echo "TIME: $(date '+%Y-%m-%d %H:%M %Z')"
echo "DISK: $(df -h . | awk 'NR==2 {print $4}') free"
echo "SHARD_PROCS: $(pgrep -f 'seed_shard.py --shard' 2>/dev/null | wc -l | tr -d ' ')"
echo "OLD_STREAM: $(pgrep -f 'seed_stream.py --workers' 2>/dev/null | wc -l | tr -d ' ')"
echo "RANDOM: $(pgrep -f 'seed_hunter_random.py' 2>/dev/null | wc -l | tr -d ' ')"
if [[ -f found_wallets_capital.jsonl ]]; then
  echo "CAPITAL_HITS: $(wc -l < found_wallets_capital.jsonl | tr -d ' ')"
else
  echo "CAPITAL_HITS: 0"
fi
if [[ -f found_wallets_activity.jsonl ]]; then
  echo "ACTIVITY_HITS: $(wc -l < found_wallets_activity.jsonl | tr -d ' ')"
else
  echo "ACTIVITY_HITS: 0"
fi
python3 - <<'PY'
import os, re, subprocess
from collections import defaultdict
rates = defaultdict(float)
for name in os.listdir("."):
    if not name.startswith("shard_") or not name.endswith(".log"):
        continue
    try:
        o = subprocess.check_output(["tail", "-c", "400", name])
        m = re.findall(rb"rate=([0-9.]+)", o)
        if m:
            rates[name.split("_w")[0]] += float(m[-1])
    except Exception:
        pass
total = sum(rates.values())
print(f"AGG_RATE: {total:.2f} addr/s")
for k in sorted(rates):
    print(f"  {k}: {rates[k]:.2f}/s")
# progress samples
for shard in ("low_fwd", "low_rev", "high_fwd", "high_rev"):
    vals = []
    for i in range(64):
        p = f"shard_{shard}_w{i}.txt"
        if os.path.exists(p):
            try:
                vals.append(int(open(p).read().strip()))
            except Exception:
                pass
    if vals:
        print(f"PROGRESS {shard}: n={len(vals)} min={min(vals):,} max={max(vals):,}")
PY
