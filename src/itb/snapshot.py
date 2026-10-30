"""`itb snapshot`: save the self-reported client id and version of every staked node, with
stake, at this moment (getClusterNodes + getVoteAccounts). These values cannot be queried
for the past, so the runner saves one at the start of every batch, and this command can be
used to take extra ones."""
from __future__ import annotations

import argparse
import json
import os

from .leaders import client_snapshot
from .rpc import Rpc

PUBLIC_RPC = "https://api.mainnet-beta.solana.com"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="itb snapshot")
    ap.add_argument("--rpc", default=os.environ.get("ITB_READ_RPC_URL", PUBLIC_RPC))
    ap.add_argument("--out-dir", default="data/snapshots")
    a = ap.parse_args(argv)
    snap = client_snapshot(Rpc(a.rpc, rate_per_s=2.0, burst=2.0, timeout=60))
    os.makedirs(a.out_dir, exist_ok=True)
    path = os.path.join(a.out_dir, f"clients_{snap['slot']}.json")
    with open(path, "w") as f:
        json.dump(snap, f, sort_keys=True)
    print(json.dumps({"path": path, "slot": snap["slot"], "staked_nodes": len(snap["nodes"])}))
    return 0
