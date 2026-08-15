#!/usr/bin/env python3
"""
JSON-RPC balance / nonce checker for seed hunting.

Hot path: public (or custom) EVM RPCs — no Etherscan quota burned per address.
Optional: Etherscan enrichment only after a capital/activity signal.

Check modes:
  balance  — eth_getBalance only (capital)
  nonce    — eth_getTransactionCount only (outgoing activity)
  both     — balance + nonce in one JSON-RPC batch (recommended)
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    import aiohttp
except ImportError:
    raise SystemExit("ERROR: pip install aiohttp")

# Public RPCs (rotate on failure). Override with env RPC_URLS_<CHAIN> or --rpc.
DEFAULT_RPCS: Dict[str, List[str]] = {
    "ethereum": [
        "https://ethereum.publicnode.com",
        "https://cloudflare-eth.com",
        "https://eth.llamarpc.com",
        "https://rpc.ankr.com/eth",
        "https://1rpc.io/eth",
        "https://eth.drpc.org",
        "https://rpc.flashbots.net",
    ],
    "polygon": [
        "https://polygon-bor.publicnode.com",
        "https://polygon.llamarpc.com",
        "https://polygon.drpc.org",
    ],
    "arbitrum": [
        "https://arbitrum-one.publicnode.com",
        "https://arbitrum.llamarpc.com",
        "https://arbitrum.drpc.org",
    ],
    "base": [
        "https://base.publicnode.com",
        "https://base.llamarpc.com",
        "https://base.drpc.org",
    ],
    "bsc": [
        "https://bsc.publicnode.com",
        "https://bsc.drpc.org",
        "https://1rpc.io/bnb",
    ],
    "optimism": [
        "https://optimism.publicnode.com",
        "https://optimism.drpc.org",
    ],
    "avalanche": [
        "https://avalanche-c-chain-rpc.publicnode.com",
        "https://avalanche.drpc.org",
    ],
}

# Chain id for hit records (Etherscan-compatible)
CHAIN_IDS: Dict[str, int] = {
    "ethereum": 1,
    "polygon": 137,
    "arbitrum": 42161,
    "base": 8453,
    "bsc": 56,
    "optimism": 10,
    "avalanche": 43114,
    "linea": 59144,
    "monad": 143,
}

DEFAULT_CHAINS_RPC = "ethereum"


def parse_rpc_urls(chain: str, override: Optional[str] = None) -> List[str]:
    """Resolve RPC URL list for a chain: CLI/env override, then defaults."""
    if override:
        return [u.strip() for u in override.split(",") if u.strip()]
    env_key = f"RPC_URLS_{chain.upper()}"
    env_val = os.getenv(env_key) or os.getenv("RPC_URLS") if chain == "ethereum" else os.getenv(env_key)
    if env_val:
        return [u.strip() for u in env_val.split(",") if u.strip()]
    return list(DEFAULT_RPCS.get(chain, []))


def _hex_to_int(val: Any) -> int:
    if val is None:
        return 0
    if isinstance(val, int):
        return val
    s = str(val)
    if s.startswith("0x") or s.startswith("0X"):
        return int(s, 16)
    try:
        return int(s)
    except Exception:
        return 0


@dataclass
class AddrSignal:
    """RPC result for one address on one chain."""

    address: str
    chain: str
    chain_id: int
    balance_eth: float = 0.0
    nonce: int = 0
    ok: bool = False
    error: str = ""


@dataclass
class RpcEndpoint:
    url: str
    fails: int = 0
    last_fail: float = 0.0
    cooldown_s: float = 30.0

    def healthy(self) -> bool:
        if self.fails <= 0:
            return True
        return (time.monotonic() - self.last_fail) >= self.cooldown_s

    def mark_ok(self) -> None:
        self.fails = 0

    def mark_fail(self) -> None:
        self.fails += 1
        self.last_fail = time.monotonic()


class RpcChainClient:
    """JSON-RPC client for one chain with endpoint rotation + batching."""

    def __init__(
        self,
        chain: str,
        urls: Sequence[str],
        *,
        max_rps: float = 25.0,
        request_timeout: float = 15.0,
    ):
        self.chain = chain
        self.chain_id = CHAIN_IDS.get(chain, 0)
        self.endpoints = [RpcEndpoint(u) for u in urls if u]
        if not self.endpoints:
            raise ValueError(f"No RPC URLs for chain {chain!r}")
        self._idx = 0
        self._min_interval = 1.0 / max(max_rps, 0.1)
        self._last_req = 0.0
        self._lock = asyncio.Lock()
        self.request_timeout = request_timeout

    def _next_ep(self) -> RpcEndpoint:
        n = len(self.endpoints)
        for _ in range(n):
            ep = self.endpoints[self._idx % n]
            self._idx += 1
            if ep.healthy():
                return ep
        # All cooling down — use least-failed
        return min(self.endpoints, key=lambda e: e.fails)

    async def _throttle(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last_req)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_req = time.monotonic()

    async def _post_batch(
        self,
        session: aiohttp.ClientSession,
        payload: List[dict],
    ) -> Optional[List[dict]]:
        await self._throttle()
        last_err = ""
        for _ in range(min(4, len(self.endpoints) + 1)):
            ep = self._next_ep()
            try:
                async with session.post(
                    ep.url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=self.request_timeout),
                ) as resp:
                    if resp.status in (429, 502, 503, 504):
                        ep.mark_fail()
                        last_err = f"http {resp.status}"
                        await asyncio.sleep(0.2)
                        continue
                    if resp.status != 200:
                        ep.mark_fail()
                        last_err = f"http {resp.status}"
                        continue
                    data = await resp.json(content_type=None)
                    if not isinstance(data, list):
                        # Some nodes return single object for 1-item batch
                        if isinstance(data, dict):
                            data = [data]
                        else:
                            ep.mark_fail()
                            last_err = "bad json shape"
                            continue
                    ep.mark_ok()
                    # Index by id
                    by_id = {}
                    for item in data:
                        if isinstance(item, dict) and "id" in item:
                            by_id[item["id"]] = item
                    return [by_id.get(p["id"], {}) for p in payload]
            except Exception as exc:
                ep.mark_fail()
                last_err = str(exc)
                await asyncio.sleep(0.15)
        return None

    async def check_addresses(
        self,
        session: aiohttp.ClientSession,
        addresses: Sequence[str],
        *,
        mode: str = "both",
    ) -> List[AddrSignal]:
        """
        Batch-check addresses.
        mode: balance | nonce | both
        """
        if not addresses:
            return []

        mode = mode.lower().strip()
        want_bal = mode in ("balance", "both", "bal")
        want_nonce = mode in ("nonce", "both", "activity")

        payload: List[dict] = []
        # id layout: for each addr i: balance id=2*i, nonce id=2*i+1
        for i, addr in enumerate(addresses):
            if want_bal:
                payload.append(
                    {
                        "jsonrpc": "2.0",
                        "id": 2 * i,
                        "method": "eth_getBalance",
                        "params": [addr, "latest"],
                    }
                )
            if want_nonce:
                payload.append(
                    {
                        "jsonrpc": "2.0",
                        "id": 2 * i + 1,
                        "method": "eth_getTransactionCount",
                        "params": [addr, "latest"],
                    }
                )

        # Chunk large batches (many public RPCs cap ~50–100 items)
        chunk_size = 80
        results_by_id: Dict[int, dict] = {}
        for off in range(0, len(payload), chunk_size):
            chunk = payload[off : off + chunk_size]
            # re-id locally for chunk? keep global ids
            resp = await self._post_batch(session, chunk)
            if resp is None:
                # soft-fail: mark all missing
                continue
            for item in resp:
                if isinstance(item, dict) and "id" in item:
                    results_by_id[item["id"]] = item

        out: List[AddrSignal] = []
        for i, addr in enumerate(addresses):
            sig = AddrSignal(
                address=addr,
                chain=self.chain,
                chain_id=self.chain_id,
            )
            ok_any = False
            if want_bal:
                item = results_by_id.get(2 * i, {})
                if "result" in item:
                    wei = _hex_to_int(item["result"])
                    sig.balance_eth = round(wei / 10**18, 8)
                    ok_any = True
                elif "error" in item:
                    sig.error = str(item.get("error"))
            if want_nonce:
                item = results_by_id.get(2 * i + 1, {})
                if "result" in item:
                    sig.nonce = _hex_to_int(item["result"])
                    ok_any = True
                elif "error" in item and not sig.error:
                    sig.error = str(item.get("error"))
            sig.ok = ok_any
            out.append(sig)
        return out


class RpcMultiClient:
    """Multi-chain RPC checker."""

    def __init__(self, chain_urls: Dict[str, List[str]], *, max_rps: float = 25.0):
        self.clients: Dict[str, RpcChainClient] = {
            name: RpcChainClient(name, urls, max_rps=max_rps)
            for name, urls in chain_urls.items()
            if urls
        }
        if not self.clients:
            raise ValueError("No RPC chains configured")

    @property
    def chains(self) -> List[str]:
        return list(self.clients.keys())

    async def check_address(
        self,
        session: aiohttp.ClientSession,
        address: str,
        *,
        mode: str = "both",
    ) -> List[AddrSignal]:
        results = await asyncio.gather(
            *[
                c.check_addresses(session, [address], mode=mode)
                for c in self.clients.values()
            ]
        )
        flat: List[AddrSignal] = []
        for r in results:
            flat.extend(r)
        return flat

    async def check_addresses_batch(
        self,
        session: aiohttp.ClientSession,
        addresses: Sequence[str],
        *,
        mode: str = "both",
    ) -> Dict[str, List[AddrSignal]]:
        """
        Returns {address: [AddrSignal per chain]}.
        """
        if not addresses:
            return {}
        per_chain = await asyncio.gather(
            *[
                c.check_addresses(session, addresses, mode=mode)
                for c in self.clients.values()
            ]
        )
        by_addr: Dict[str, List[AddrSignal]] = {a: [] for a in addresses}
        for chain_sigs in per_chain:
            for sig in chain_sigs:
                by_addr.setdefault(sig.address, []).append(sig)
        return by_addr


def build_rpc_client(
    chains: Sequence[str],
    *,
    rpc_overrides: Optional[Dict[str, str]] = None,
    max_rps: float = 25.0,
) -> RpcMultiClient:
    rpc_overrides = rpc_overrides or {}
    chain_urls: Dict[str, List[str]] = {}
    for name in chains:
        name = name.strip().lower()
        if not name:
            continue
        urls = parse_rpc_urls(name, rpc_overrides.get(name))
        if not urls:
            # Fall back to ethereum public list only for unknown names
            continue
        chain_urls[name] = urls
    return RpcMultiClient(chain_urls, max_rps=max_rps)


def signals_to_hits(
    entry: dict,
    signals: Sequence[AddrSignal],
    *,
    min_balance: float = 0.0,
    save_nonce_activity: bool = True,
    capital_only: bool = True,
) -> Tuple[List[dict], List[dict]]:
    """
    Split signals into capital hits (balance > min) and activity hits (nonce > 0, no capital).
    """
    capital: List[dict] = []
    activity: List[dict] = []
    for sig in signals:
        if not sig.ok and sig.balance_eth <= 0 and sig.nonce <= 0:
            continue
        base = {
            "phrase": entry.get("phrase"),
            "address": entry.get("address") or sig.address,
            "path": entry.get("path"),
            "chain": sig.chain,
            "chain_id": sig.chain_id,
            "balance_eth": sig.balance_eth,
            "nonce": sig.nonce,
            "has_tx": sig.nonce > 0,
            "entropy_index": entry.get("index"),
            "timestamp": time.time(),
            "source": f"rpc_{sig.chain}",
        }
        if sig.balance_eth > min_balance:
            capital.append({**base, "hit_type": "capital"})
        elif save_nonce_activity and sig.nonce > 0 and not capital_only:
            activity.append({**base, "hit_type": "activity"})
        elif save_nonce_activity and sig.nonce > 0 and capital_only:
            # Still record activity separately when capital_only (empty but used)
            activity.append({**base, "hit_type": "activity"})
    return capital, activity


async def enrich_hit_etherscan(
    hit: dict,
    session: aiohttp.ClientSession,
    etherscan_keys: List[str],
) -> dict:
    """Optional: attach explorer balance confirmation (1 call). Does not require multi-chain."""
    if not etherscan_keys:
        return hit
    try:
        from seed_checker_multichain import EtherscanClient

        client = EtherscanClient(etherscan_keys, rate_limit=2.5)
        chain_id = int(hit.get("chain_id") or 1)
        bal = await client.get_balance(session, chain_id, hit.get("address", ""))
        hit = {**hit, "etherscan_balance_eth": bal, "enriched": True}
    except Exception as exc:
        hit = {**hit, "enrich_error": str(exc)}
    return hit
