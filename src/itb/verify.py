"""60-second verification for judges.

Takes a random sample of our own transactions from the raw data, re-fetches each block with
getBlock (by default from the public endpoint, no API key needed) and checks that
  1. the signature is in that slot's block,
  2. at the index we recorded,
  3. the slot leader is the identity we recorded.
Prints PASS/FAIL per signature and exits non-zero if anything fails.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import random
import sys

from .blocks import block_signatures, slot_leader
from .rpc import Rpc

PUBLIC_RPC = "https://api.mainnet-beta.solana.com"


def load_landed(raw_glob: str) -> list[dict]:
    out = []
    for path in sorted(glob.glob(raw_glob)):
        with open(path) as f:
            for line in f:
                if not line.strip():
                    continue
                r = json.loads(line)
                if r.get("record") == "landed" and r.get("slot") is not None and r.get("tx_index") is not None:
                    out.append(r)
    return out


def check(rpc: Rpc, rec: dict, cache: dict) -> tuple[bool, str]:
    slot = int(rec["slot"])
    if slot not in cache:
        cache[slot] = (block_signatures(rpc, slot), slot_leader(rpc, slot))
    sigs, leader = cache[slot]
    if sigs is None:
        return False, f"slot {slot} has no block"
    if rec["signature"] not in sigs:
        return False, f"signature not in block {slot}"
    idx = sigs.index(rec["signature"])
    if idx != int(rec["tx_index"]):
        return False, f"index {idx} != recorded {rec['tx_index']}"
    if rec.get("leader") and leader != rec["leader"]:
        return False, f"leader {leader} != recorded {rec['leader']}"
    return True, f"slot {slot} index {idx}/{len(sigs)} leader {leader[:8]}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="itb verify", description=__doc__.splitlines()[0])
    ap.add_argument("--raw", default="data/raw/*.jsonl", help="glob of raw JSONL files")
    ap.add_argument("-n", type=int, default=20, help="sample size")
    ap.add_argument("--seed", type=int, default=None, help="RNG seed (default: random)")
    ap.add_argument("--rpc", default=os.environ.get("VERIFY_RPC_URL") or PUBLIC_RPC,
                    help="RPC endpoint (default: public mainnet endpoint or VERIFY_RPC_URL)")
    ap.add_argument("--all", action="store_true", help="check every landed transaction, not a sample")
    a = ap.parse_args(argv)
    recs = load_landed(a.raw)
    if not recs:
        print(f"no landed records found in {a.raw}")
        return 2
    seed = a.seed if a.seed is not None else random.SystemRandom().randrange(2**32)
    sample = recs if a.all else random.Random(seed).sample(recs, min(a.n, len(recs)))
    rpc = Rpc(a.rpc, rate_per_s=3.0, burst=3.0)
    print(f"verify: {len(sample)} of {len(recs)} landed transactions, seed={seed}, rpc host={rpc.host}")
    cache: dict = {}
    fails = 0
    for r in sample:
        ok, why = check(rpc, r, cache)
        fails += not ok
        print(f"{'PASS' if ok else 'FAIL'} {r['signature']} {why}")
    print(f"RESULT: {'PASS' if fails == 0 else 'FAIL'} ({len(sample) - fails}/{len(sample)} passed)")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
