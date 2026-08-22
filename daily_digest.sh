#!/bin/bash
# Daily health digest + heal. Safe: never FORCE_RESTART.
# Prints a report for the Grok Task / human. Exit 1 if still unhealthy after heal.
set -euo pipefail
cd "$(dirname "$0")"

echo "=== seed-hunter digest $(date -u '+%Y-%m-%d %H:%M:%S UTC') ==="

chmod +x ensure_alive.sh status_shards.sh 2>/dev/null || true
healed=0
if ! ./ensure_alive.sh; then
  healed=1
fi
# ensure_alive exits 0 on ok or successful fill; 1 if still short.
# Detect whether this run restarted by looking at the last line.
last="$(tail -n 1 ensure_alive.log 2>/dev/null || true)"
case "$last" in
  *RESTART*|*STALL*|*WARN*|*FAILED*) healed=1 ;;
esac

echo
status_out="$(./status_shards.sh)"
echo "$status_out"
echo
echo "ENSURE_LAST: $last"
echo "HEALED_THIS_RUN: $healed"
echo "CRON: $(crontab -l 2>/dev/null | grep -c 'ensure_alive.sh' || true) ensure_alive line(s)"

# Stale-log scan (informational; ensure_alive already killed >15min)
stale=0
now=$(date +%s)
for f in shard_*_w*.log; do
  [[ -f "$f" ]] || continue
  age=$(( now - $(stat -c %Y "$f") ))
  if (( age > 900 )); then
    echo "STALE_LOG: $f age=${age}s"
    stale=1
  fi
done

rate="$(printf '%s\n' "$status_out" | awk '/^AGG_RATE:/ {print $2}')"
echo "AGG_RATE_PARSED: ${rate:-?}"

unhealthy=0
procs="$(ps -C python,python3 -o args= 2>/dev/null | grep -cF -- 'seed_shard.py --shard ' || true)"
echo "PROCS_PYTHON: $procs"
if [[ "$procs" -lt "${EXPECT_SHARD_PROCS:-16}" ]]; then
  echo "UNHEALTHY: proc count"
  unhealthy=1
fi
if [[ "$stale" -eq 1 ]]; then
  echo "UNHEALTHY: stale logs remain"
  unhealthy=1
fi
if [[ -n "${rate:-}" ]]; then
  awk -v r="$rate" 'BEGIN { if (r+0 == 0) exit 1; exit 0 }' || {
    echo "UNHEALTHY: AGG_RATE is 0 (RPC likely dead — not FORCE_RESTART)"
    unhealthy=1
  }
fi

if [[ "$unhealthy" -eq 1 ]]; then
  exit 1
fi
echo "HEALTH: ok"
exit 0
