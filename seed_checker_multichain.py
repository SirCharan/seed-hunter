#!/usr/bin/env python3
"""
Phase 2 — Multi-chain activity checker for saved checksum-valid EVM addresses.

Reads checksum_valid.jsonl (from Phase 1 derive-only hunters) and checks each
0x address across multiple EVM chains via Etherscan API V2 (chainid parameter).

Same 0x address works on all EVM chains (Ethereum path m/44'/60'/0'/0/0).
Does NOT check Solana — that requires separate ed25519 derivation.

Usage:
  export ETHERSCAN_API_KEY=your_key
  python seed_checker_multichain.py
  python seed_checker_multichain.py --workers 4 --worker-id 0
  python seed_checker_multichain.py --input checksum_valid.jsonl --chains ethereum,polygon,arbitrum,monad
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

try:
    import aiohttp
except ImportError:
    print("ERROR: pip install aiohttp")
    sys.exit(1)

# Etherscan V2 free-tier chains (see https://docs.etherscan.io/supported-chains)
FREE_TIER_CHAINS: Dict[str, int] = {
    "ethereum": 1,
    "polygon": 137,
    "arbitrum": 42161,
    "linea": 59144,
    "monad": 143,
    "gnosis": 100,
    "moonbeam": 1284,
    "blast": 81457,
    "mantle": 5000,
    "taiko": 167000,
    "sonic": 146,
    "berachain": 80094,
}

# Paid-tier only on free API plan (will often return errors without paid key)
PAID_TIER_CHAINS: Dict[str, int] = {
    "base": 8453,
    "bsc": 56,
    "optimism": 10,
    "avalanche": 43114,
}

DEFAULT_INPUT = "checksum_valid.jsonl"
DEFAULT_RESULTS = "found_wallets_multichain.jsonl"
DEFAULT_PROGRESS = "checker_progress.txt"
# Fast core set: 4 chains × 1 API call (tx-only) = 4 calls/addr
DEFAULT_CHAINS = "ethereum,polygon,arbitrum,monad"
ETHERSCAN_V2 = "https://api.etherscan.io/v2/api"

# Clean GitHub-friendly archives (phrase + address always for activity/capital)
ACTIVITY_SEEDS_FILE = "activity_seeds.jsonl"
CAPITAL_SEEDS_FILE = "capital_seeds.jsonl"


@dataclass(frozen=True)
class Config:
    input_file: str
    results_file: str
    progress_file: str
    chains: Dict[str, int]
    api_keys: List[str]
    worker_id: int
    num_workers: int
    max_concurrent: int
    rate_limit: float
    tx_only: bool


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Phase 2 multi-chain EVM address checker")
    p.add_argument("--input", default=DEFAULT_INPUT, help="Phase 1 JSONL output")
    p.add_argument("--results-file", default=DEFAULT_RESULTS)
    p.add_argument("--progress-file", default=None,
                     help="Per-worker progress (default: checker_progress_w{id}.txt)")
    p.add_argument("--chains", default=DEFAULT_CHAINS,
                     help=f"Comma-separated chain names (default: {DEFAULT_CHAINS})")
    p.add_argument("--include-paid-chains", action="store_true",
                     help="Also try Base/BSC/OP/Avalanche (may fail on free API tier)")
    p.add_argument("--etherscan-key", default=None,
                     help="API key(s), comma-separated for rotation")
    p.add_argument("--worker-id", type=int, default=0)
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--max-concurrent", type=int, default=8)
    p.add_argument("--rate-limit", type=float, default=4.5,
                     help="Max Etherscan requests per second (free tier ~5/sec per key)")
    p.add_argument("--tx-only", action=argparse.BooleanOptionalAction, default=True,
                     help="Only txlist per chain (1 call/chain). --no-tx-only checks balance+tx.")
    return p.parse_args()


def resolve_config(args: argparse.Namespace) -> Config:
    if args.worker_id < 0 or args.worker_id >= args.workers:
        raise ValueError(f"--worker-id must be 0..{args.workers - 1}")

    names = [c.strip().lower() for c in args.chains.split(",") if c.strip()]
    chains = {}
    all_chains = {**FREE_TIER_CHAINS, **(PAID_TIER_CHAINS if args.include_paid_chains else {})}
    for name in names:
        if name not in all_chains:
            raise ValueError(f"Unknown chain {name!r}. Known: {', '.join(sorted(all_chains))}")
        chains[name] = all_chains[name]

    raw = args.etherscan_key or os.getenv("ETHERSCAN_API_KEY", "")
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        raise SystemExit("ERROR: Set ETHERSCAN_API_KEY or pass --etherscan-key")

    progress = args.progress_file
    if progress is None:
        progress = (
            f"checker_progress_w{args.worker_id}.txt"
            if args.workers > 1
            else DEFAULT_PROGRESS
        )

    return Config(
        input_file=args.input,
        results_file=args.results_file,
        progress_file=progress,
        chains=chains,
        api_keys=keys,
        worker_id=args.worker_id,
        num_workers=args.workers,
        max_concurrent=args.max_concurrent,
        # rate_limit is per-key; client multiplies capacity by len(keys)
        rate_limit=args.rate_limit,
        tx_only=bool(args.tx_only),
    )


def load_progress(path: str) -> int:
    if not os.path.exists(path):
        return 0
    try:
        return int(open(path, encoding="utf-8").read().strip() or "0")
    except Exception:
        return 0


def save_progress(path: str, line_no: int) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(str(line_no))


def append_hit(path: str, hit: dict) -> None:
    """Append one JSON object as a line (process-safe via flock)."""
    with open(path, "a", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            json.dump(hit, f, ensure_ascii=False)
            f.write("\n")
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def activity_seed_record(hit: dict) -> dict:
    """Clean archive row: phrase + address + activity fields (for GitHub)."""
    rec: Dict[str, Any] = {
        "phrase": hit.get("phrase"),
        "address": hit.get("address"),
        "nonce": hit.get("nonce"),
        "balance_eth": hit.get("balance_eth"),
        "chain": hit.get("chain"),
        "timestamp": hit.get("timestamp"),
    }
    for key in ("chain_id", "hit_type", "entropy_index", "path", "source", "has_tx"):
        if hit.get(key) is not None:
            rec[key] = hit[key]
    return rec


def capital_seed_record(hit: dict) -> dict:
    """Clean archive row: phrase + address + balance (for GitHub)."""
    rec: Dict[str, Any] = {
        "phrase": hit.get("phrase"),
        "address": hit.get("address"),
        "balance_eth": hit.get("balance_eth"),
    }
    for key in ("nonce", "chain", "chain_id", "timestamp", "hit_type", "entropy_index"):
        if hit.get(key) is not None:
            rec[key] = hit[key]
    return rec


def append_activity_hit(
    activity_file: str,
    hit: dict,
    *,
    seeds_file: str = ACTIVITY_SEEDS_FILE,
) -> None:
    """
    Persist a nonce>0 activity hit to BOTH:
      - activity_file (e.g. found_wallets_activity.jsonl) full record
      - activity_seeds.jsonl clean archive (phrase, address, nonce, ...)
    """
    append_hit(activity_file, hit)
    append_hit(seeds_file, activity_seed_record(hit))


def append_capital_hit(
    results_file: str,
    hit: dict,
    *,
    seeds_file: str = CAPITAL_SEEDS_FILE,
) -> None:
    """
    Persist a balance>0 capital hit to BOTH:
      - results_file (e.g. found_wallets_capital.jsonl) full record
      - capital_seeds.jsonl clean archive (phrase, address, balance, ...)
    """
    append_hit(results_file, hit)
    append_hit(seeds_file, capital_seed_record(hit))


class EtherscanClient:
    """Etherscan V2 client with *per-key* rate limiting (keys scale linearly)."""

    def __init__(self, keys: List[str], rate_limit: float):
        """
        rate_limit: max requests per second *per key* (free tier ~3–5/s).
        Total capacity ≈ rate_limit * len(keys).
        """
        self.keys = [k for k in keys if k]
        if not self.keys:
            raise ValueError("EtherscanClient requires at least one API key")
        self.rate_per_key = max(float(rate_limit), 0.1)
        self._min_interval = 1.0 / self.rate_per_key
        # last scheduled start time per key (monotonic)
        self._last_req = {k: 0.0 for k in self.keys}
        self._lock = asyncio.Lock()
        # In-flight cap: a bit above sustained rate so bursts don't stall
        self._sem = asyncio.Semaphore(max(2, len(self.keys) * max(2, int(self.rate_per_key) + 1)))

    async def _acquire_key(self) -> str:
        """Pick the key that is free soonest; reserve its next slot."""
        while True:
            async with self._lock:
                now = time.monotonic()
                best_key = self.keys[0]
                best_ready = self._last_req[best_key] + self._min_interval
                for k in self.keys[1:]:
                    ready_at = self._last_req[k] + self._min_interval
                    if ready_at < best_ready:
                        best_ready = ready_at
                        best_key = k
                wait = best_ready - now
                if wait <= 0:
                    self._last_req[best_key] = now
                    return best_key
                # Reserve the slot so other coroutines take different keys
                self._last_req[best_key] = best_ready
                key = best_key
            await asyncio.sleep(wait)
            return key

    async def _get(self, session: aiohttp.ClientSession, params: dict) -> dict:
        async with self._sem:
            key = await self._acquire_key()
            params = {**params, "apikey": key}
            try:
                async with asyncio.timeout(12):
                    async with session.get(ETHERSCAN_V2, params=params) as resp:
                        if resp.status != 200:
                            return {}
                        data = await resp.json()
                        # Soft-backoff signal: rate message in result
                        result = data.get("result")
                        if isinstance(result, str) and "rate limit" in result.lower():
                            async with self._lock:
                                self._last_req[key] = time.monotonic() + 1.0
                        return data
            except Exception:
                return {}

    async def get_balance(self, session: aiohttp.ClientSession, chain_id: int, address: str) -> float:
        data = await self._get(session, {
            "chainid": chain_id,
            "module": "account",
            "action": "balance",
            "address": address,
            "tag": "latest",
        })
        if data.get("status") == "1":
            try:
                return round(int(data.get("result", 0)) / 10**18, 8)
            except Exception:
                return 0.0
        return 0.0

    async def has_transactions(self, session: aiohttp.ClientSession, chain_id: int, address: str) -> bool:
        data = await self._get(session, {
            "chainid": chain_id,
            "module": "account",
            "action": "txlist",
            "address": address,
            "startblock": 0,
            "endblock": 99999999,
            "page": 1,
            "offset": 1,
            "sort": "asc",
        })
        if data.get("status") == "1":
            result = data.get("result", [])
            return isinstance(result, list) and len(result) > 0
        return False


def _make_hit(entry: dict, chain_name: str, chain_id: int, balance: float, source: str) -> dict:
    return {
        "phrase": entry.get("phrase"),
        "address": entry.get("address", ""),
        "path": entry.get("path"),
        "chain": chain_name,
        "chain_id": chain_id,
        "balance_eth": balance,
        "has_tx": True,
        "entropy_index": entry.get("index"),
        "timestamp": time.time(),
        "source": source,
    }


async def check_address_all_chains(
    client: EtherscanClient,
    session: aiohttp.ClientSession,
    entry: dict,
    chains: Dict[str, int],
    tx_only: bool = True,
    capital_only: bool = False,
    min_balance: float = 0.0,
) -> List[dict]:
    """Check address on chains. If capital_only, only return hits with balance > min_balance.

    Capital path: parallel balance checks across chains (latency ≈ 1 call, not N).
    """
    address = entry.get("address", "")
    if not address:
        return []

    items = list(chains.items())
    if not items:
        return []

    # Capital-only: one balance call per chain, all in parallel
    if capital_only:
        balances = await asyncio.gather(
            *[client.get_balance(session, cid, address) for _, cid in items]
        )
        hits = []
        for (chain_name, chain_id), balance in zip(items, balances):
            if balance > min_balance:
                hits.append(
                    _make_hit(entry, chain_name, chain_id, balance, "etherscan_v2_balance")
                )
        return hits

    hits = []
    for chain_name, chain_id in items:
        if tx_only:
            has_tx = await client.has_transactions(session, chain_id, address)
            if not has_tx:
                continue
            balance = await client.get_balance(session, chain_id, address)
            hits.append(_make_hit(entry, chain_name, chain_id, balance, "etherscan_v2_txlist"))
            continue

        balance = await client.get_balance(session, chain_id, address)
        if balance > min_balance:
            hits.append(_make_hit(entry, chain_name, chain_id, balance, "etherscan_v2_balance"))
            continue

        has_tx = await client.has_transactions(session, chain_id, address)
        if has_tx:
            hits.append(_make_hit(entry, chain_name, chain_id, 0.0, "etherscan_v2_txlist"))

    return hits


async def run_checker(cfg: Config) -> int:
    if not os.path.exists(cfg.input_file):
        print(f"ERROR: input file not found: {cfg.input_file}")
        return 1

    start_line = load_progress(cfg.progress_file)
    calls_per_chain = 1 if cfg.tx_only else 2
    calls_per_addr = len(cfg.chains) * calls_per_chain

    print("=== SEED CHECKER MULTICHAIN (Phase 2) ===")
    print(f"Input: {cfg.input_file}")
    print(f"Results: {cfg.results_file}")
    print(f"Progress: {cfg.progress_file}")
    if cfg.num_workers > 1:
        print(f"Worker: {cfg.worker_id}/{cfg.num_workers} (line stride)")
    print(f"Mode: {'tx-only' if cfg.tx_only else 'balance+tx'}")
    print(f"Chains ({len(cfg.chains)}): {', '.join(cfg.chains)}")
    print(f"API keys: {len(cfg.api_keys)}   Rate limit: ~{cfg.rate_limit:.1f} req/s")
    print(f"Resuming from line: {start_line:,}")
    print(f"API calls per address (worst case): {calls_per_addr}")
    print("-" * 72)

    client = EtherscanClient(cfg.api_keys, cfg.rate_limit)
    sem = asyncio.Semaphore(cfg.max_concurrent)

    checked = 0
    hits_total = 0
    last_line_no = start_line - 1
    t0 = time.time()

    try:
        async with aiohttp.ClientSession() as session:
            with open(cfg.input_file, encoding="utf-8") as f:
                for line_no, line in enumerate(f):
                    if line_no < start_line:
                        continue
                    if (line_no - cfg.worker_id) % cfg.num_workers != 0:
                        continue

                    line = line.strip()
                    if not line:
                        continue

                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    async with sem:
                        hits = await check_address_all_chains(
                            client, session, entry, cfg.chains, tx_only=cfg.tx_only
                        )

                    for hit in hits:
                        bal = float(hit.get("balance_eth") or 0)
                        if bal > 0:
                            append_capital_hit(cfg.results_file, {**hit, "hit_type": "capital"})
                        else:
                            append_activity_hit(
                                "found_wallets_activity.jsonl",
                                {**hit, "hit_type": "activity", "nonce": hit.get("nonce", 1)},
                            )
                        hits_total += 1
                        print(f"\n{'='*80}")
                        print(f"HIT on {hit['chain']}: {hit['address']}  balance={hit['balance_eth']}")
                        print(f"Phrase: {hit['phrase']}")
                        print(f"{'='*80}\n")

                    checked += 1
                    last_line_no = line_no
                    if checked % 10 == 0:
                        save_progress(cfg.progress_file, line_no + 1)

                    elapsed = time.time() - t0
                    rate = checked / elapsed if elapsed > 0 else 0
                    sys.stdout.write(
                        f"\rlines={line_no + 1:,}  checked={checked:,}  "
                        f"rate={rate:.2f} addr/s  hits={hits_total}  elapsed={elapsed:,.0f}s"
                    )
                    sys.stdout.flush()
    except Exception as exc:
        if last_line_no >= 0:
            save_progress(cfg.progress_file, last_line_no + 1)
        print(f"\n\nChecker error: {exc}")
        raise

    if last_line_no >= start_line - 1:
        save_progress(cfg.progress_file, last_line_no + 1)
    elapsed = time.time() - t0
    print(f"\n\nDone. Checked {checked:,} addresses in {elapsed:,.1f}s. Hits: {hits_total}")
    return 0


def main() -> int:
    args = parse_args()
    cfg = resolve_config(args)
    try:
        return asyncio.run(run_checker(cfg))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
