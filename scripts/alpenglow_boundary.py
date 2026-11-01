#!/usr/bin/env python3
"""Reproduce the Alpenglow boundary used as MIN_SLOT: find the last block that still contains
vote transactions and the first block after it without any, by binary search over getBlock.
Usage: python scripts/alpenglow_boundary.py [--rpc URL] [--lo SLOT_WITH_VOTES] [--hi SLOT_WITHOUT_VOTES]
"""
import argparse, datetime, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from itb.rpc import Rpc, RpcError  # noqa: E402
from itb.blocks import block_full, is_vote_tx  # noqa: E402


def votes(rpc, slot):
    b = block_full(rpc, slot, commitment="finalized")
    if b is None:
        return None, None
    return sum(is_vote_tx(t) for t in b["transactions"]), b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rpc", default=os.environ.get("VERIFY_RPC_URL", "https://api.mainnet-beta.solana.com"))
    ap.add_argument("--lo", type=int, default=459_648_010)
    ap.add_argument("--hi", type=int, default=459_660_000)
    a = ap.parse_args()
    rpc = Rpc(a.rpc, rate_per_s=2.0, burst=2.0, timeout=60)
    lo, hi = a.lo, a.hi
    assert (votes(rpc, lo)[0] or 0) > 0, "lo must contain votes"
    while hi - lo > 1:
        mid = (lo + hi) // 2
        s, v = mid, None
        while v is None and s < hi:
            v, _ = votes(rpc, s)
            if v is None:
                s += 1
        if v is None or s >= hi:
            hi = mid
        elif v > 0:
            lo = s
        else:
            hi = mid
    # lo = last slot with votes; report the next produced block
    v, b = votes(rpc, lo)
    print(f"last block with vote transactions: slot {lo} ({v} vote tx, blockTime "
          f"{datetime.datetime.fromtimestamp(b['blockTime'], datetime.timezone.utc).isoformat()})")
    s = lo + 1
    while True:
        v, b = votes(rpc, s)
        if v is None:
            print(f"slot {s}: skipped"); s += 1; continue
        print(f"first block after it: slot {s}, vote tx = {v}, blockTime "
              f"{datetime.datetime.fromtimestamp(b['blockTime'], datetime.timezone.utc).isoformat()}")
        break


if __name__ == "__main__":
    main()
