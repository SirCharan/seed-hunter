#!/usr/bin/env python3
"""
SEED HUNTER ASYNC (Optimized version)

This is an optimized, async + batched rewrite of the original seed_hunter.py.

Major improvements for speed:
- AsyncWeb3 + actual RPC batching (eth_getTransactionCount in batches)
- ProcessPoolExecutor for parallel CPU-heavy address derivation (PBKDF2)
- High concurrency for network I/O instead of many blocking processes
- Support for multiple RPC endpoints (load balance / fallback)
- Much better throughput on the same hardware

=== SETUP (first time) ===
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt

  # or manually:
  pip install eth-account mnemonic web3

Then run:
  python seed_hunter_async.py --help
  python seed_hunter_async.py --test

=== RECOMMENDED: Use free Etherscan key for much higher throughput ===
export ETHERSCAN_API_KEY=your_key_here
python seed_hunter_async.py --test

Get free key: https://etherscan.io/apis (no credit card needed)

You can also pass it on command line:
  python seed_hunter_async.py --etherscan-key YOUR_KEY --test

Usage examples:
  python seed_hunter_async.py --test

  # Best: use your free Etherscan key (big speed boost)
  export ETHERSCAN_API_KEY=YOUR_KEY
  python seed_hunter_async.py --test

  # Or pass directly
  python seed_hunter_async.py --etherscan-key YOUR_KEY --test

  # Multiple free RPCs + higher concurrency
  python seed_hunter_async.py --rpc https://rpc.ankr.com/eth,https://cloudflare-eth.com --max-concurrent 300

Keep the original seed_hunter.py if you want the classic multiprocessing version.
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from typing import List, Optional, Tuple

# Suppress harmless "Unclosed client session" warnings from aiohttp on interrupts/exit.
# These are very common with AsyncWeb3 + aiohttp and do not mean anything is broken.
import warnings
warnings.filterwarnings("ignore", category=ResourceWarning)

# === Dependency check (friendly error for new users) ===
try:
    from eth_account import Account
    from mnemonic import Mnemonic
    from web3 import AsyncWeb3
except ImportError as e:
    missing = str(e).split()[-1] if "No module named" in str(e) else "required package"
    print("ERROR: Missing dependency:", missing)
    print("\nThis script requires the following packages:")
    print("  eth-account")
    print("  mnemonic")
    print("  web3")
    print("\nQuick setup (recommended):")
    print("  python3 -m venv .venv")
    print("  source .venv/bin/activate")
    print("  pip install -r requirements.txt")
    print("\nOr one-liner:")
    print("  pip install eth-account mnemonic web3")
    print("\nThen run again:")
    print("  python seed_hunter_async.py --help")
    sys.exit(1)

# Enable unaudited features (called again inside pool workers)
Account.enable_unaudited_hdwallet_features()

MNEMO = Mnemonic("english")
WORDLIST = MNEMO.wordlist
WL_LEN = len(WORDLIST)

# =============================================
# DEFAULTS (tuned for M2 8GB MacBook Air)
# =============================================

DEFAULT_RPCS = [
    # Primary: Your Cloudflare Worker (with KV caching + rotation)
    "https://eth-rpc-proxy.charandeepkapoor3.workers.dev",
    # Fallback free/public endpoints (reliable first)
    "https://ethereum-rpc.publicnode.com",
    "https://1rpc.io/eth",
    "https://eth.drpc.org",
    "https://rpc.flashbots.net",
    "https://rpc.ankr.com/eth",
    "https://cloudflare-eth.com",
]
RESULTS_FILE = "found_wallets.jsonl"
PROGRESS_FILE = "seed_progress.txt"
CHECKSUM_VALID_FILE = "checksum_valid.jsonl"
DEFAULT_PATH = "m/44'/60'/0'/0/0"

DEFAULT_LENGTH = 12
DEFAULT_DERIVE_WORKERS = 6          # CPU workers for derivation (PBKDF2 is expensive)
DEFAULT_BATCH_SIZE = 25
DEFAULT_MAX_CONCURRENT = 200        # Higher with many free RPCs

# BIP39: each mnemonic length maps to a fixed entropy size (checksum is derived from it).
ENTROPY_BITS_BY_LENGTH = {12: 128, 15: 160, 18: 192, 21: 224, 24: 256}
TEST_MNEMONIC_LIMIT = 100_000


@dataclass(frozen=True)
class Config:
    length: int
    path: str
    derive_workers: int
    rpc_urls: List[str]
    batch_size: int
    max_concurrent: int
    results_file: str
    progress_file: str
    checksum_file: str
    start_idx: int
    worker_id: int
    num_workers: int
    test_mode: bool
    random_mode: bool
    derive_only: bool
    etherscan_key: Optional[str] = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed Hunter Async — high-throughput async/batched seed scanner"
    )
    parser.add_argument("--length", type=int, default=DEFAULT_LENGTH,
                        help=f"Mnemonic length in words (default: {DEFAULT_LENGTH})")
    parser.add_argument("--rpc", action="append", default=None,
                        help="RPC URL. Can be passed multiple times or comma-separated.")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                        help=f"Number of addresses per RPC batch request (default: {DEFAULT_BATCH_SIZE})")
    parser.add_argument("--max-concurrent", type=int, default=DEFAULT_MAX_CONCURRENT,
                        help=f"Max concurrent in-flight RPC operations (default: {DEFAULT_MAX_CONCURRENT})")
    parser.add_argument("--derive-workers", type=int, default=DEFAULT_DERIVE_WORKERS,
                        help=f"Number of processes for address derivation (default: {DEFAULT_DERIVE_WORKERS})")
    parser.add_argument("--test", action="store_true",
                        help="TEST_MODE: only scan first 100,000 valid mnemonics")
    parser.add_argument("--random", action="store_true",
                        help="RANDOM MODE: generate random valid seed phrases instead of sequential (useful for sampling)")
    parser.add_argument("--derive-only", action="store_true",
                        help="Phase 1: only derive checksum-valid seeds to --checksum-file (skip RPC/Etherscan)")
    parser.add_argument("--progress-file", default=PROGRESS_FILE)
    parser.add_argument("--results-file", default=RESULTS_FILE)
    parser.add_argument("--checksum-file", default=None,
                        help=f"JSONL file for all checksum-valid seeds (default: {CHECKSUM_VALID_FILE})")
    parser.add_argument("--etherscan-key", default=None,
                        help="Free Etherscan API key (highly recommended for extra free capacity). Get one at https://etherscan.io/apis")
    parser.add_argument("--worker-id", type=int, default=0,
                        help="Worker ID for partitioned scan (0..num-workers-1)")
    parser.add_argument("--num-workers", type=int, default=1,
                        help="Total parallel workers; each scans every Nth entropy index")
    return parser.parse_args()


def align_worker_start(global_frontier: int, worker_id: int, num_workers: int) -> int:
    """Next entropy index for worker_id on the global stride grid."""
    if num_workers <= 1:
        return global_frontier
    rem = global_frontier % num_workers
    if rem <= worker_id:
        return global_frontier + (worker_id - rem)
    return global_frontier + (num_workers - rem + worker_id)


def load_worker_progress(
    progress_file: str,
    worker_id: int,
    num_workers: int,
) -> Tuple[int, bool]:
    """Load per-worker progress, bootstrapping from global progress if needed."""
    if os.path.exists(progress_file):
        try:
            with open(progress_file, encoding="utf-8") as f:
                val = int(f.read().strip() or "0")
            ensure_v2_marker(progress_file)
            return val, val > 0
        except Exception:
            pass

    global_start = 0
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, encoding="utf-8") as f:
                global_start = int(f.read().strip() or "0")
        except Exception:
            global_start = 0

    aligned = align_worker_start(global_start, worker_id, num_workers)
    if aligned > 0:
        write_progress(progress_file, aligned)
    return aligned, aligned > 0


def resolve_config(args: argparse.Namespace) -> Config:
    worker_id = max(0, args.worker_id)
    num_workers = max(1, args.num_workers)
    if worker_id >= num_workers:
        raise ValueError(f"--worker-id ({worker_id}) must be < --num-workers ({num_workers})")

    if args.progress_file == PROGRESS_FILE and num_workers > 1:
        progress_file = f"seed_progress_w{worker_id}.txt"
    else:
        progress_file = args.progress_file

    if args.checksum_file:
        checksum_file = args.checksum_file
    elif num_workers > 1:
        checksum_file = CHECKSUM_VALID_FILE
    else:
        checksum_file = CHECKSUM_VALID_FILE

    # Collect RPCs
    if args.rpc:
        rpcs: List[str] = []
        for item in args.rpc:
            rpcs.extend([x.strip() for x in item.split(",") if x.strip()])
    else:
        rpcs = DEFAULT_RPCS[:]

    # Resume (with one-time migration from legacy word-combination indexing)
    start_idx = 0
    progress_loaded = False
    if not args.test:
        if num_workers > 1:
            start_idx, progress_loaded = load_worker_progress(
                progress_file, worker_id, num_workers
            )
        else:
            start_idx, progress_loaded = load_progress_with_migration(
                progress_file, args.length
            )
    elif os.path.exists(progress_file):
        try:
            with open(progress_file, encoding="utf-8") as f:
                start_idx = int(f.read().strip() or "0")
            progress_loaded = start_idx > 0
        except Exception:
            start_idx = 0

    if args.test:
        if progress_loaded and start_idx > 0:
            print(f"TEST_MODE: ignoring previous progress (was at #{start_idx:,}), starting from 0")
        start_idx = align_worker_start(0, worker_id, num_workers)
    elif progress_loaded and start_idx > 0:
        print(f"Found previous progress → will resume from entropy index #{start_idx:,}")
    elif num_workers > 1 and start_idx > 0:
        print(f"Worker {worker_id}/{num_workers} bootstrapped at entropy index #{start_idx:,}")

    raw_key = args.etherscan_key or os.getenv("ETHERSCAN_API_KEY", "")
    etherscan_keys = [k.strip() for k in raw_key.split(",") if k.strip()] if raw_key else []
    etherscan_key = etherscan_keys[0] if etherscan_keys else None

    # Make multiple keys available for rotation (higher rate)
    global _etherscan_keys
    _etherscan_keys = etherscan_keys

    return Config(
        length=args.length,
        path=DEFAULT_PATH,
        derive_workers=max(1, args.derive_workers),
        rpc_urls=rpcs or DEFAULT_RPCS[:],
        batch_size=max(1, args.batch_size),
        max_concurrent=max(1, args.max_concurrent),
        results_file=args.results_file,
        progress_file=progress_file,
        checksum_file=checksum_file,
        start_idx=start_idx,
        worker_id=worker_id,
        num_workers=num_workers,
        test_mode=bool(args.test),
        random_mode=bool(args.random),
        derive_only=bool(args.derive_only),
        etherscan_key=etherscan_key,
    )


def derive_address_sync(phrase: str, path: str) -> Optional[str]:
    """Executed in ProcessPoolExecutor. Returns checksummed address."""
    try:
        Account.enable_unaudited_hdwallet_features()
        acct = Account.from_mnemonic(phrase, account_path=path)
        return acct.address  # Keep checksummed (modern web3 requires it for many calls)
    except Exception:
        return None


def build_phrase(idx: int, length: int) -> str:
    """Legacy index→phrase mapping (base-2048 word combinations). Used only for migration."""
    words: List[str] = []
    x = idx
    for _ in range(length):
        words.append(WORDLIST[x % WL_LEN])
        x //= WL_LEN
    return " ".join(words)


def entropy_bits_for_length(length: int) -> int:
    try:
        return ENTROPY_BITS_BY_LENGTH[length]
    except KeyError as exc:
        supported = ", ".join(str(n) for n in sorted(ENTROPY_BITS_BY_LENGTH))
        raise ValueError(f"Unsupported mnemonic length {length}. Supported: {supported}") from exc


def valid_mnemonic_space(length: int, test_mode: bool) -> int:
    """Total number of valid BIP39 mnemonics to scan."""
    if test_mode:
        return TEST_MNEMONIC_LIMIT
    return 2 ** entropy_bits_for_length(length)


def entropy_index_to_phrase(idx: int, length: int) -> str:
    """Map entropy index 0..2^bits-1 to a checksum-valid BIP39 mnemonic."""
    bits = entropy_bits_for_length(length)
    if idx < 0 or idx >= (1 << bits):
        raise ValueError(f"Entropy index {idx} out of range for {length}-word mnemonics")
    entropy = idx.to_bytes(bits // 8, byteorder="big")
    return MNEMO.to_mnemonic(entropy)


def count_legacy_valid_through(frontier: int, length: int) -> int:
    """Count checksum-valid phrases in legacy index range [0, frontier)."""
    if frontier <= 0:
        return 0
    print(f"  Scanning legacy range 0..{frontier:,} to count valid mnemonics (one-time)...")
    count = 0
    report_every = max(1, frontier // 50)
    for i in range(frontier):
        if MNEMO.check(build_phrase(i, length)):
            count += 1
        if (i + 1) % report_every == 0:
            pct = 100 * (i + 1) / frontier
            print(f"  migration: {i + 1:,}/{frontier:,} ({pct:.0f}%) — valid so far: {count:,}", end="\r")
            sys.stdout.flush()
    print(f"  migration complete: {count:,} valid mnemonics in legacy range [0, {frontier:,})" + " " * 20)
    return count


def ensure_v2_marker(progress_file: str) -> None:
    """Mark progress file as entropy-index format (distinguishes from legacy runs)."""
    marker = progress_file + ".v2"
    if not os.path.exists(marker):
        with open(marker, "w", encoding="utf-8") as mf:
            mf.write("format=v2_entropy_index\n")


def write_progress(progress_file: str, idx: int) -> None:
    with open(progress_file, "w", encoding="utf-8") as f:
        f.write(str(idx))
    ensure_v2_marker(progress_file)


def load_progress_with_migration(progress_file: str, length: int) -> Tuple[int, bool]:
    """Load entropy-index progress, migrating legacy word-combination counters once."""
    marker = progress_file + ".v2"
    lock_path = progress_file + ".migrate.lock"

    if not os.path.exists(progress_file):
        return 0, False

    try:
        with open(lock_path, "w", encoding="utf-8") as lockf:
            fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
            try:
                with open(progress_file, encoding="utf-8") as f:
                    raw = f.read().strip()
                val = int(raw or "0")
            except Exception:
                return 0, False

            if os.path.exists(marker):
                return val, val > 0

            if val <= 0:
                with open(marker, "w", encoding="utf-8") as mf:
                    mf.write("legacy_frontier=0\nmigrated_to=0\n")
                return 0, False

            legacy_space = WL_LEN ** length
            if val >= legacy_space:
                print(f"WARNING: progress value {val:,} exceeds legacy space; treating as entropy index")
                with open(marker, "w", encoding="utf-8") as mf:
                    mf.write(f"legacy_frontier=skipped\nmigrated_to={val}\n")
                return val, True

            print("Migrating progress file from legacy word-combination index to entropy index...")
            with open(progress_file + ".v1_backup", "w", encoding="utf-8") as bf:
                bf.write(str(val))

            new_idx = count_legacy_valid_through(val, length)
            with open(progress_file, "w", encoding="utf-8") as pf:
                pf.write(str(new_idx))
            with open(marker, "w", encoding="utf-8") as mf:
                mf.write(f"legacy_frontier={val}\nmigrated_to={new_idx}\n")

            print(f"  Legacy frontier {val:,} → entropy index {new_idx:,}")
            print(f"  Backup: {progress_file}.v1_backup   Marker: {marker}")
            return new_idx, True
    except Exception as exc:
        print(f"WARNING: progress migration failed ({exc}); starting from 0")
        return 0, False


class ChecksumWriter:
    """Buffered, process-safe JSONL writer for checksum-valid seeds."""

    def __init__(self, path: str, flush_every: int = 50):
        self.path = path
        self.flush_every = flush_every
        self._buffer: List[dict] = []
        self._lock = asyncio.Lock()
        self.saved = 0

    async def save(
        self,
        phrase: str,
        address: str,
        path: str,
        *,
        index: Optional[int] = None,
        sample: Optional[int] = None,
    ) -> None:
        entry: dict = {
            "phrase": phrase,
            "address": address,
            "path": path,
            "timestamp": time.time(),
        }
        if index is not None:
            entry["index"] = index
        if sample is not None:
            entry["sample"] = sample

        async with self._lock:
            self._buffer.append(entry)
            if len(self._buffer) >= self.flush_every:
                await self._flush_locked()

    async def _flush_locked(self) -> None:
        if not self._buffer:
            return
        lines = [json.dumps(entry) + "\n" for entry in self._buffer]
        self.saved += len(self._buffer)
        self._buffer.clear()
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._write_sync, lines)

    def _write_sync(self, lines: List[str]) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.writelines(lines)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    async def final_flush(self) -> None:
        async with self._lock:
            await self._flush_locked()


def human(n: float) -> str:
    for unit in ("", "K", "M", "B", "T", "Q"):
        if abs(n) < 1000:
            return f"{n:.1f}{unit}"
        n /= 1000
    return f"{n:.1f}P"


async def create_clients(rpc_urls: List[str]) -> List[AsyncWeb3]:
    # Dedup + shuffle for better distribution
    unique = list(dict.fromkeys(rpc_urls))
    random.shuffle(unique)

    clients: List[AsyncWeb3] = []
    connect_tasks = []

    async def try_connect(url: str):
        w3 = None
        try:
            w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(
                url,
                request_kwargs={"timeout": 12}
            ))
            if await w3.is_connected():
                print(f"  RPC connected: {url}")
                return w3
            else:
                print(f"  RPC failed to connect: {url}")
                if w3:
                    await w3.close()
                return None
        except Exception as e:
            print(f"  RPC error {url}: {e}")
            if w3:
                try:
                    await w3.close()
                except:
                    pass
            return None

    # Connect in parallel
    tasks = [try_connect(url) for url in unique]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for res in results:
        if isinstance(res, AsyncWeb3):
            clients.append(res)

    if not clients:
        raise RuntimeError("No working RPC endpoints available!")

    print(f"  Using {len(clients)} RPC endpoint(s) for load balancing")
    return clients


class NoOpBatcher:
    """Phase 1 derive-only: skip on-chain checks."""

    def __init__(self):
        self.hits = 0
        self.pending: List = []

    async def add(self, phrase: str, addr: str, path: str) -> None:
        return

    async def flush(self) -> None:
        return

    async def final_flush(self) -> None:
        return


class Batcher:
    """Batches addresses and performs batched nonce lookups across multiple free RPCs in parallel."""

    def __init__(self, clients: List[AsyncWeb3], batch_size: int, semaphore: asyncio.Semaphore, results_file: str, etherscan_key: Optional[str] = None):
        self.clients = clients
        self.batch_size = batch_size
        self.semaphore = semaphore
        self.results_file = results_file
        self.etherscan_key = etherscan_key
        self.pending: List[Tuple[str, str, str]] = []
        self.client_idx = 0
        self.hits = 0
        self._checked: set[str] = set()   # simple in-run dedup

    def _next_client(self) -> AsyncWeb3:
        if not self.clients:
            raise RuntimeError("No RPC clients")
        c = self.clients[self.client_idx % len(self.clients)]
        self.client_idx += 1
        return c

    async def add(self, phrase: str, addr: str, path: str) -> None:
        if addr in self._checked:
            return
        self._checked.add(addr)
        self.pending.append((phrase, addr, path))
        if len(self.pending) >= self.batch_size:
            await self.flush()

    async def flush(self) -> None:
        if not self.pending:
            return

        pending = self.pending
        self.pending = []

        if self.etherscan_key:
            # === PREFERRED PATH: Use free Etherscan when key is available ===
            # This offloads most work from public RPCs and is often faster for "has history?"
            async def check_etherscan(item):
                phrase, addr, path = item
                has_tx = await has_activity_etherscan(addr, self.etherscan_key)
                if has_tx:
                    # Get balance preferably from Etherscan too
                    balance_eth = await get_balance_etherscan(addr, self.etherscan_key)
                    if balance_eth == 0.0 and self.clients:
                        # Fallback to RPC for balance only on hits
                        try:
                            client = self._next_client()
                            async with self.semaphore:
                                bal = await client.eth.get_balance(addr)
                            balance_eth = round(bal / 10**18, 6)
                        except Exception:
                            pass

                    hit = {
                        "phrase": phrase,
                        "address": addr,
                        "nonce": 0,
                        "balance_eth": balance_eth,
                        "path": path,
                        "timestamp": time.time(),
                        "source": "etherscan",
                    }
                    await self._save_hit(hit)

            # Fire Etherscan checks in parallel (rate limited inside has_activity_etherscan)
            await asyncio.gather(*[check_etherscan(item) for item in pending])
            return

        # === FALLBACK: Pure RPC path (no Etherscan key) ===
        batches = [pending[i:i + self.batch_size] for i in range(0, len(pending), self.batch_size)]

        async def process_one_batch(batch: list):
            if not batch:
                return
            client = self._next_client()
            addresses = [a for _, a, _ in batch]

            nonces: List[int] = []
            try:
                async with self.semaphore:
                    async with client.batch_requests() as b:
                        for a in addresses:
                            b.add(client.eth.get_transaction_count(a))
                        nonces = await b.async_execute()
            except Exception as e:
                print(f"\n[batch warning] {str(e)[:80]}")
                nonces = []
                for a in addresses:
                    try:
                        async with self.semaphore:
                            n = await client.eth.get_transaction_count(a)
                        nonces.append(n)
                    except Exception:
                        nonces.append(0)

            for (phrase, addr, path), nonce in zip(batch, nonces):
                if nonce and nonce > 0:
                    balance_eth = 0.0
                    try:
                        async with self.semaphore:
                            bal = await client.eth.get_balance(addr)
                        balance_eth = round(bal / 10**18, 6)
                    except Exception:
                        pass

                    hit = {
                        "phrase": phrase,
                        "address": addr,
                        "nonce": int(nonce),
                        "balance_eth": balance_eth,
                        "path": path,
                        "timestamp": time.time(),
                        "source": "rpc",
                    }
                    await self._save_hit(hit)

        await asyncio.gather(*[process_one_batch(b) for b in batches])

    async def _save_hit(self, hit: dict) -> None:
        self.hits += 1
        try:
            with open(self.results_file, "a", encoding="utf-8") as f:
                json.dump(hit, f)
                f.write("\n")
        except Exception:
            pass

        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(hit["timestamp"]))
        print(f"\n\n{'='*85}")
        print(f"✅ HIT #{self.hits} @ {ts}")
        print(f"Seed Phrase : {hit['phrase']}")
        print(f"Address     : {hit['address']}")
        print(f"Nonce       : {hit['nonce']}")
        print(f"Balance     : {hit['balance_eth']} ETH")
        print(f"Path        : {hit['path']}")
        print(f"{'='*85}\n")


# ---------- Free Etherscan helper (very useful extra capacity) ----------
try:
    import aiohttp
except ImportError:
    aiohttp = None

_etherscan_sem = asyncio.Semaphore(5)  # ~5 req/sec per key
_etherscan_keys = []  # populated at runtime
_etherscan_key_idx = 0

def _get_next_etherscan_key(preferred_key: str = None) -> str:
    global _etherscan_key_idx
    keys = _etherscan_keys or ([preferred_key] if preferred_key else [])
    if not keys:
        return preferred_key or ""
    key = keys[_etherscan_key_idx % len(keys)]
    _etherscan_key_idx += 1
    return key

async def has_activity_etherscan(address: str, api_key: str = None) -> bool:
    """Free Etherscan tier (V2) — excellent for offloading public RPCs.
    Supports multiple keys for higher rate.
    """
    key = api_key or _get_next_etherscan_key()
    if not aiohttp or not key:
        return False

    # Etherscan V2 endpoint (V1 is deprecated)
    url = "https://api.etherscan.io/v2/api"
    params = {
        "chainid": 1,
        "module": "account",
        "action": "txlist",
        "address": address,
        "startblock": 0,
        "endblock": 99999999,
        "page": 1,
        "offset": 1,
        "sort": "asc",
        "apikey": key,
    }

    async with _etherscan_sem:
        try:
            async with asyncio.timeout(12):
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                        if resp.status != 200:
                            return False
                        data = await resp.json()
                        if data.get("status") == "1":
                            result = data.get("result", [])
                            return isinstance(result, list) and len(result) > 0
                        return False
        except asyncio.TimeoutError:
            return False
        except Exception:
            return False

async def get_balance_etherscan(address: str, api_key: str = None) -> float:
    """Get ETH balance via free Etherscan V2 (saves RPC quota)."""
    key = api_key or _get_next_etherscan_key()
    if not aiohttp or not key:
        return 0.0

    url = "https://api.etherscan.io/v2/api"
    params = {
        "chainid": 1,
        "module": "account",
        "action": "balance",
        "address": address,
        "tag": "latest",
        "apikey": key,
    }

    async with _etherscan_sem:
        try:
            async with asyncio.timeout(10):
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status != 200:
                            return 0.0
                        data = await resp.json()
                        if data.get("status") == "1":
                            bal_wei = int(data.get("result", 0))
                            return round(bal_wei / 10**18, 6)
                        return 0.0
        except Exception:
            return 0.0

    async def final_flush(self) -> None:
        await self.flush()


async def progress_saver(progress_file: str, get_frontier, interval: float = 5.0):
    while True:
        await asyncio.sleep(interval)
        try:
            idx = get_frontier()
            write_progress(progress_file, idx)
        except Exception:
            pass


async def stats_reporter(start_time: float, get_stats, get_hits, interval: float = 0.5):
    while True:
        await asyncio.sleep(interval)
        tried, valid, frontier = get_stats()
        hits = get_hits()
        elapsed = time.time() - start_time
        rate = tried / elapsed if elapsed > 0 else 0.0
        sys.stdout.write(
            f"\rtried={human(tried)}  checksum-ok={human(valid)}  "
            f"rate={human(rate)}/s  elapsed={elapsed:,.0f}s  frontier={human(frontier)}  hits={hits}"
        )
        sys.stdout.flush()


async def scanner(
    cfg: Config,
    executor: ProcessPoolExecutor,
    batcher: Batcher,
    checksum_writer: ChecksumWriter,
    stats: dict,
):
    loop = asyncio.get_running_loop()

    tried = 0
    checksum_ok = 0

    if cfg.random_mode:
        # Random mode: generate random valid phrases (efficiently using entropy + checksum)
        # For --test, limit to 100k samples; otherwise run until stopped
        max_samples = 100_000 if cfg.test_mode else None
        while True:
            if max_samples and tried >= max_samples:
                break
            # Generate random valid 12-word mnemonic
            phrase = MNEMO.generate(128)  # 128 bits -> 12 words, includes checksum
            checksum_ok += 1
            addr = await loop.run_in_executor(executor, derive_address_sync, phrase, cfg.path)
            if addr:
                await checksum_writer.save(phrase, addr, cfg.path, sample=tried + 1)
                await batcher.add(phrase, addr, cfg.path)

            tried += 1

            stats["tried"] = tried
            stats["valid"] = checksum_ok
            stats["frontier"] = tried  # in random, frontier = samples tested

            # Yield to let the event loop process batches and I/O
            if (tried % 300) == 0:
                await asyncio.sleep(0)

            if len(batcher.pending) >= cfg.batch_size:
                await batcher.flush()
    else:
        # Sequential mode: enumerate only valid BIP39 mnemonics (2^entropy_bits of them)
        total_space = valid_mnemonic_space(cfg.length, cfg.test_mode)
        idx = cfg.start_idx
        stride = cfg.num_workers
        while idx < total_space:
            phrase = entropy_index_to_phrase(idx, cfg.length)
            checksum_ok += 1
            addr = await loop.run_in_executor(executor, derive_address_sync, phrase, cfg.path)
            if addr:
                await checksum_writer.save(phrase, addr, cfg.path, index=idx)
                await batcher.add(phrase, addr, cfg.path)

            tried += 1
            next_idx = idx + stride
            stats["tried"] = tried
            stats["valid"] = checksum_ok
            stats["frontier"] = next_idx
            idx = next_idx

            # Yield to let the event loop process batches and I/O
            if (tried % 300) == 0:
                await asyncio.sleep(0)

            if len(batcher.pending) >= cfg.batch_size:
                await batcher.flush()

    await batcher.final_flush()


async def run(cfg: Config) -> int:
    total_space = (
        TEST_MNEMONIC_LIMIT if cfg.test_mode or cfg.random_mode
        else valid_mnemonic_space(cfg.length, cfg.test_mode)
    )

    print(f"TEST MODE: {cfg.test_mode}")
    print(f"RANDOM MODE: {cfg.random_mode}")
    print(f"DERIVE ONLY: {cfg.derive_only}")
    if cfg.derive_only:
        print("Phase 1 mode — saving checksum-valid seeds only (no on-chain checks)")
    else:
        print(f"RPC endpoints: {cfg.rpc_urls}")
        if cfg.etherscan_key:
            print("Using free Etherscan API for activity checks (extra capacity)")
    print(f"Derive workers (CPU pool): {cfg.derive_workers}")
    print(f"Batch size: {cfg.batch_size}   Max concurrent: {cfg.max_concurrent}")
    if cfg.num_workers > 1:
        print(f"Partitioned worker: {cfg.worker_id}/{cfg.num_workers} (stride={cfg.num_workers})")
        print(f"Progress file: {cfg.progress_file}")
    print(f"Checksum-valid seeds → {cfg.checksum_file}")
    if cfg.start_idx > 0 and not cfg.random_mode:
        print(f"✅ RESUMING from entropy index {cfg.start_idx:,}")
    if cfg.random_mode:
        print("Generating random valid phrases (with checksum)")
    else:
        bits = entropy_bits_for_length(cfg.length)
        print(f"Sequential scan: valid {cfg.length}-word mnemonics only (2^{bits} = {total_space:,} total)")
    print("-" * 80)

    if cfg.start_idx >= total_space:
        print(f"Nothing to scan: entropy index ({cfg.start_idx:,}) is already at or past the limit.")
        print("If you want to run TEST_MODE from the beginning, delete or reset the progress file")
        return 0

    print("Starting... (Ctrl+C to stop safely)\n")

    clients: List[AsyncWeb3] = []
    if cfg.derive_only:
        batcher = NoOpBatcher()
    else:
        clients = await create_clients(cfg.rpc_urls)
        semaphore = asyncio.Semaphore(cfg.max_concurrent)
        batcher = Batcher(clients, cfg.batch_size, semaphore, cfg.results_file, cfg.etherscan_key)
    checksum_writer = ChecksumWriter(cfg.checksum_file)
    stats = {"tried": 0, "valid": 0, "frontier": cfg.start_idx}
    start_time = time.time()

    def get_stats():
        return stats["tried"], stats["valid"], stats.get("frontier", cfg.start_idx)

    def get_hits():
        return batcher.hits

    progress_task = asyncio.create_task(
        progress_saver(cfg.progress_file, lambda: stats.get("frontier", cfg.start_idx), 5.0)
    )
    reporter_task = asyncio.create_task(stats_reporter(start_time, get_stats, get_hits, 0.5))

    executor = ProcessPoolExecutor(max_workers=cfg.derive_workers)

    try:
        await scanner(cfg, executor, batcher, checksum_writer, stats)
    except KeyboardInterrupt:
        print("\n\nStopping...")
    except Exception as exc:
        print(f"\n\nFatal scanner error: {exc}")
        raise
    finally:
        # Cancel background tasks
        for task in (progress_task, reporter_task):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        executor.shutdown(wait=True, cancel_futures=True)
        await batcher.final_flush()
        await checksum_writer.final_flush()

        # Close web3 clients to avoid "Unclosed client session" warnings
        for client in clients or []:
            try:
                await client.close()
            except Exception:
                pass

        # Only save progress if we actually advanced past the starting point
        final_frontier = stats.get("frontier", cfg.start_idx)
        if final_frontier > cfg.start_idx:
            try:
                write_progress(cfg.progress_file, final_frontier)
                print(f"\nProgress saved at entropy index: {final_frontier:,}")
            except Exception:
                pass
        else:
            print("\n(No new progress to save)")

    elapsed = time.time() - start_time
    print(f"\n\nFinished. Total hits: {batcher.hits}")
    print(f"Results saved to: {cfg.results_file}")
    print(f"Checksum-valid seeds saved: {checksum_writer.saved:,} → {cfg.checksum_file}")
    print(f"Elapsed: {elapsed:,.1f}s")
    return 0


def main() -> int:
    # Avoid printing banner when user just wants --help
    if not (len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help")):
        print("=== SEED HUNTER ASYNC (OPTIMIZED) STARTING ===")
        print("Python version:", sys.version)

    args = parse_args()
    cfg = resolve_config(args)

    try:
        return asyncio.run(run(cfg))
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        return 1
    except Exception as exc:
        print(f"\nExiting with error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
