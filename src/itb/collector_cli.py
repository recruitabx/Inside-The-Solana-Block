"""`itb collect`: resolve every sent transaction of one or more runs to a landed / not_landed
record and reconcile the spend ledger with on-chain fees.

Input : data/raw/<run>.sent.jsonl (append-only log written by the runner)
Output: data/raw/<run>.landed.jsonl (rewritten atomically; re-running is idempotent)
        data/raw/<run>.blocks.jsonl (block summaries, appended; slots already summarized are skipped)
Ledger: settle(actual on-chain fee) for landed tx; release() only for tx unknown to the cluster
        more than EXPIRY_MARGIN_S after sending (blockhash validity is ~150 blocks, ~32 s).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import time

from .collect import BlockCache, landed_records
from .enrich import enrich_run
from .rpc import Rpc
from .spend import SpendLedger

PUBLIC_RPC = "https://api.mainnet-beta.solana.com"
EXPIRY_MARGIN_S = 180


def collect_run(sent_path: str, rpc: Rpc, ledger: SpendLedger | None, enrich: bool = True) -> dict:
    recs = [json.loads(x) for x in open(sent_path) if x.strip()]
    start = next((r for r in recs if r["record"] == "run_start"), {})
    end = next((r for r in recs if r["record"] == "run_end"), {})
    clients, clients_end = {}, None
    if start.get("snapshot") and os.path.exists(start["snapshot"]):
        clients = json.load(open(start["snapshot"]))["nodes"]
    if end.get("snapshot_end") and os.path.exists(end["snapshot_end"]):
        clients_end = json.load(open(end["snapshot_end"]))["nodes"]
    sent, t_sent = [], {}
    for r in recs:
        if r["record"] == "probe" and r.get("mode") == "live" and r.get("send_results"):
            for t in r["txs"]:
                sent.append({"signature": t["signature"], "probe_id": r["probe_id"]})
                t_sent[t["signature"]] = r.get("t_send_start", 0)
    out = landed_records(rpc, sent, clients, BlockCache(rpc), clients_end) if sent else []
    now = time.time()
    if ledger:
        for o in out:
            sig = o["signature"]
            if sig not in ledger.entries:
                continue
            if o["record"] == "landed" and o.get("fee") is not None:
                ledger.settle(sig, int(o["fee"]))
            elif o["record"] == "not_landed" and o["reason"].startswith("unknown") and now - t_sent.get(sig, now) > EXPIRY_MARGIN_S:
                ledger.release(sig, f"unknown to cluster {int(now - t_sent[sig])} s after send (blockhash expired)")
    dst = sent_path.replace(".sent.jsonl", ".landed.jsonl")
    tmp = dst + ".tmp"
    with open(tmp, "w") as f:
        for o in out:
            f.write(json.dumps(o, sort_keys=True) + "\n")
    os.replace(tmp, dst)
    n_l = sum(o["record"] == "landed" for o in out)
    rep = {"run": os.path.basename(sent_path), "sent": len(sent), "landed": n_l, "not_landed": len(out) - n_l}
    if enrich and sent:
        try:
            rep["blocks"] = enrich_run(sent_path.replace(".sent.jsonl", ".blocks.jsonl"), recs, out, rpc)
        except Exception as e:   # enrichment is supplementary: never lose the landing records over it
            rep["blocks"] = {"error": type(e).__name__}
    return rep


def reconcile_ledger(rpc: Rpc, ledger: SpendLedger, ledger_path: str, min_age_s: float = EXPIRY_MARGIN_S) -> dict:
    """Settle or release EVERY open reservation (probes, funding, anchors): landed -> settle with the
    on-chain fee; unknown to the cluster and reserved more than min_age_s ago -> release."""
    ts = {}
    with open(ledger_path) as f:
        for line in f:
            r = json.loads(line)
            if r["kind"] == "reserve":
                ts[r["sig"]] = r.get("ts", 0)
    open_sigs = [s for s, e in ledger.entries.items() if e.state == "open"]
    settled = released = 0
    now = time.time()
    for i in range(0, len(open_sigs), 200):
        chunk = open_sigs[i:i + 200]
        vals = rpc.call("getSignatureStatuses", [chunk, {"searchTransactionHistory": True}])["value"]
        for sig, v in zip(chunk, vals):
            if v is not None:
                t = rpc.call("getTransaction", [sig, {"encoding": "json", "commitment": "confirmed",
                                                      "maxSupportedTransactionVersion": 1}])
                if t is not None:
                    ledger.settle(sig, int(t["meta"]["fee"])); settled += 1
            elif now - ts.get(sig, now) > min_age_s:
                ledger.release(sig, f"unknown to cluster {int(now - ts[sig])} s after reservation (blockhash expired)")
                released += 1
    return {"open_before": len(open_sigs), "settled": settled, "released": released, "ledger": ledger.summary()}


def main(argv: list[str] | None = None) -> int:
    from .runner import LEDGER_PATH, cap_from_env
    ap = argparse.ArgumentParser(prog="itb collect")
    ap.add_argument("runs", nargs="*", help="run ids (default: every live run in data/raw)")
    ap.add_argument("--rpc", default=os.environ.get("ITB_READ_RPC_URL", PUBLIC_RPC))
    ap.add_argument("--no-ledger", action="store_true", help="do not touch the spend ledger")
    ap.add_argument("--ledger-only", action="store_true", help="only reconcile every open ledger reservation (incl. funding and anchors)")
    ap.add_argument("--no-enrich", action="store_true", help="do not fetch full blocks for the block summaries")
    a = ap.parse_args(argv)
    paths = [f"data/raw/{r}.sent.jsonl" for r in a.runs] if a.runs else sorted(glob.glob("data/raw/*-live-*.sent.jsonl"))
    rpc = Rpc(a.rpc, rate_per_s=3.0, burst=3.0, timeout=60)
    ledger = None if a.no_ledger or not os.path.exists(LEDGER_PATH) else SpendLedger(LEDGER_PATH, cap_from_env())
    try:
        if not a.ledger_only:
            for p in paths:
                print(json.dumps(collect_run(p, rpc, ledger, enrich=not a.no_enrich)))
        if ledger:
            print(json.dumps({"reconcile": reconcile_ledger(rpc, ledger, LEDGER_PATH)}))
    finally:
        if ledger:
            ledger.close()
    return 0
