#!/usr/bin/env python3
"""
Human-readable summary of activity seed hits.

Default: print a table of phrase + address from activity_seeds.jsonl.

Migrate existing bulk hits into the clean archive (idempotent by address+chain+nonce):
  python export_activity_summary.py --migrate
  python export_activity_summary.py --migrate --capital

Usage:
  python export_activity_summary.py
  python export_activity_summary.py --file activity_seeds.jsonl
  python export_activity_summary.py --migrate
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


DEFAULT_ACTIVITY_SEEDS = "activity_seeds.jsonl"
DEFAULT_ACTIVITY_BULK = "found_wallets_activity.jsonl"
DEFAULT_CAPITAL_SEEDS = "capital_seeds.jsonl"
DEFAULT_CAPITAL_BULK = "found_wallets_capital.jsonl"


def _load_jsonl(path: str) -> List[dict]:
    if not os.path.exists(path):
        return []
    out: List[dict] = []
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"WARN: skip {path}:{line_no}: {exc}", file=sys.stderr)
                continue
            if isinstance(obj, dict):
                out.append(obj)
    return out


def _activity_record(hit: dict) -> dict:
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


def _capital_record(hit: dict) -> dict:
    rec: Dict[str, Any] = {
        "phrase": hit.get("phrase"),
        "address": hit.get("address"),
        "balance_eth": hit.get("balance_eth"),
    }
    for key in ("nonce", "chain", "chain_id", "timestamp", "hit_type", "entropy_index"):
        if hit.get(key) is not None:
            rec[key] = hit[key]
    return rec


def _key_activity(hit: dict) -> Tuple[Any, ...]:
    return (
        hit.get("address"),
        hit.get("chain"),
        hit.get("nonce"),
        hit.get("phrase"),
    )


def _key_capital(hit: dict) -> Tuple[Any, ...]:
    return (
        hit.get("address"),
        hit.get("chain"),
        hit.get("balance_eth"),
        hit.get("phrase"),
    )


def _append_jsonl(path: str, records: Iterable[dict]) -> int:
    n = 0
    with open(path, "a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    return n


def migrate_activity(
    bulk_path: str = DEFAULT_ACTIVITY_BULK,
    seeds_path: str = DEFAULT_ACTIVITY_SEEDS,
) -> int:
    existing = {_key_activity(h) for h in _load_jsonl(seeds_path)}
    bulk = _load_jsonl(bulk_path)
    new_recs = []
    for hit in bulk:
        if not hit.get("phrase") or not hit.get("address"):
            continue
        rec = _activity_record(hit)
        k = _key_activity(rec)
        if k in existing:
            continue
        existing.add(k)
        new_recs.append(rec)
    if new_recs:
        _append_jsonl(seeds_path, new_recs)
    print(f"Migrated {len(new_recs)} activity hit(s) → {seeds_path}")
    print(f"  bulk={bulk_path} ({len(bulk)} lines)  archive now has {len(existing)} unique keys")
    return len(new_recs)


def migrate_capital(
    bulk_path: str = DEFAULT_CAPITAL_BULK,
    seeds_path: str = DEFAULT_CAPITAL_SEEDS,
) -> int:
    existing = {_key_capital(h) for h in _load_jsonl(seeds_path)}
    bulk = _load_jsonl(bulk_path)
    new_recs = []
    for hit in bulk:
        if not hit.get("phrase") or not hit.get("address"):
            continue
        rec = _capital_record(hit)
        k = _key_capital(rec)
        if k in existing:
            continue
        existing.add(k)
        new_recs.append(rec)
    if new_recs:
        _append_jsonl(seeds_path, new_recs)
    print(f"Migrated {len(new_recs)} capital hit(s) → {seeds_path}")
    print(f"  bulk={bulk_path} ({len(bulk)} lines)  archive now has {len(existing)} unique keys")
    return len(new_recs)


def print_table(path: str) -> int:
    rows = _load_jsonl(path)
    if not rows:
        print(f"(no rows in {path})")
        return 0

    # Column widths
    phrases = [str(r.get("phrase") or "") for r in rows]
    addrs = [str(r.get("address") or "") for r in rows]
    nonces = [str(r.get("nonce") if r.get("nonce") is not None else "") for r in rows]
    bals = [str(r.get("balance_eth") if r.get("balance_eth") is not None else "") for r in rows]
    chains = [str(r.get("chain") or "") for r in rows]

    w_i = max(3, len(str(len(rows))))
    w_p = max(6, max((len(p) for p in phrases), default=6))
    w_a = max(7, max((len(a) for a in addrs), default=7))
    w_n = max(5, max((len(n) for n in nonces), default=5))
    w_b = max(7, max((len(b) for b in bals), default=7))
    w_c = max(5, max((len(c) for c in chains), default=5))

    # Cap phrase width for terminal readability (full phrase still in file)
    w_p_show = min(w_p, 72)

    header = (
        f"{'#':>{w_i}}  "
        f"{'PHRASE':<{w_p_show}}  "
        f"{'ADDRESS':<{w_a}}  "
        f"{'NONCE':>{w_n}}  "
        f"{'BAL_ETH':>{w_b}}  "
        f"{'CHAIN':<{w_c}}"
    )
    print(header)
    print("-" * len(header))
    for i, r in enumerate(rows, 1):
        phrase = phrases[i - 1]
        if len(phrase) > w_p_show:
            phrase = phrase[: w_p_show - 3] + "..."
        print(
            f"{i:>{w_i}}  "
            f"{phrase:<{w_p_show}}  "
            f"{addrs[i - 1]:<{w_a}}  "
            f"{nonces[i - 1]:>{w_n}}  "
            f"{bals[i - 1]:>{w_b}}  "
            f"{chains[i - 1]:<{w_c}}"
        )
    print("-" * len(header))
    print(f"Total: {len(rows)}  file: {path}")
    return len(rows)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Summarize / migrate activity seed hits")
    p.add_argument(
        "--file",
        default=DEFAULT_ACTIVITY_SEEDS,
        help=f"JSONL to summarize (default: {DEFAULT_ACTIVITY_SEEDS})",
    )
    p.add_argument(
        "--migrate",
        action="store_true",
        help=f"Copy {DEFAULT_ACTIVITY_BULK} → {DEFAULT_ACTIVITY_SEEDS} (deduped)",
    )
    p.add_argument(
        "--capital",
        action="store_true",
        help=f"With --migrate, also copy {DEFAULT_CAPITAL_BULK} → {DEFAULT_CAPITAL_SEEDS}",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.migrate:
        migrate_activity()
        if args.capital:
            migrate_capital()
        # After migrate, still print the activity table if file exists
        if os.path.exists(args.file):
            print()
            print_table(args.file)
        return 0
    print_table(args.file)
    return 0


if __name__ == "__main__":
    sys.exit(main())
