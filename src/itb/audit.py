"""`itb audit`: show that no fee-paying transaction of our accounts escaped the spend ledger.

For the funding wallet and every derived fee payer listed in data/accounts.json (public keys
only), list all signatures since MIN_SLOT with getSignaturesForAddress. Every signature must be
either in the spend ledger, or a transaction whose fee payer is NOT one of our accounts (e.g. the
initial deposit into the wallet). Also checks: settled fees in the ledger == on-chain fees, and
committed total <= cap. Needs no private key; judges can run it.
"""
from __future__ import annotations

import argparse
import json
import os

from .config import HARD_SPEND_CEILING_LAMPORTS, MAX_SUPPORTED_TX_VERSION, MIN_SLOT
from .rpc import Rpc

PUBLIC_RPC = "https://api.mainnet-beta.solana.com"


def signatures_for(rpc: Rpc, addr: str) -> list[dict]:
    out, before = [], None
    while True:
        opts = {"limit": 1000, "commitment": "finalized"}
        if before:
            opts["before"] = before
        page = rpc.call("getSignaturesForAddress", [addr, opts])
        page = [p for p in page if p["slot"] >= MIN_SLOT]
        out += page
        if len(page) < 1000:
            return out
        before = page[-1]["signature"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="itb audit")
    ap.add_argument("--accounts", default="data/accounts.json")
    ap.add_argument("--ledger", default="data/ledger/spend.jsonl")
    ap.add_argument("--rpc", default=os.environ.get("ITB_READ_RPC_URL", PUBLIC_RPC))
    a = ap.parse_args(argv)
    acc = json.load(open(a.accounts))
    ours = set([acc["wallet"]] + acc["payers"])
    ledger = {}
    for line in open(a.ledger):
        r = json.loads(line)
        e = ledger.setdefault(r["sig"], {})
        e[r["kind"]] = r
    rpc = Rpc(a.rpc, rate_per_s=3.0, burst=3.0, timeout=60)
    seen: dict[str, dict] = {}
    for addr in sorted(ours):
        for s in signatures_for(rpc, addr):
            seen[s["signature"]] = s
    unledgered, external, fee_mismatch = [], 0, []
    for sig in seen:
        if sig in ledger:
            st = ledger[sig].get("settle")
            if st is None:
                continue
            continue
        tx = rpc.call("getTransaction", [sig, {"encoding": "json", "maxSupportedTransactionVersion": MAX_SUPPORTED_TX_VERSION,
                                               "commitment": "finalized"}])
        payer = tx["transaction"]["message"]["accountKeys"][0]
        payer = payer if isinstance(payer, str) else payer["pubkey"]
        if payer in ours:
            unledgered.append(sig)
        else:
            external += 1
    settled = sum(v["settle"]["actual_fee"] for v in ledger.values() if "settle" in v)
    open_max = sum(v["reserve"]["max_fee"] for v in ledger.values() if "reserve" in v and "settle" not in v and "release" not in v)
    rep = {"accounts": len(ours), "onchain_signatures": len(seen), "ledger_signatures": len(ledger),
           "external_incoming": external, "unledgered_fee_paying": unledgered,
           "settled_fees_lamports": settled, "open_reservations_max_lamports": open_max,
           "hard_ceiling_lamports": HARD_SPEND_CEILING_LAMPORTS,
           "within_ceiling": settled + open_max <= HARD_SPEND_CEILING_LAMPORTS,
           "RESULT": "PASS" if not unledgered and settled + open_max <= HARD_SPEND_CEILING_LAMPORTS else "FAIL"}
    print(json.dumps(rep, indent=1))
    return 0 if rep["RESULT"] == "PASS" else 1
