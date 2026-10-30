"""Join the runner's send log with the collector's landing records into one row per probe.

Everything here is a pure function of files under data/raw/, so `itb analyze` can be rerun by
anyone from the committed data without network access."""
from __future__ import annotations

import glob
import json
import math
import os

from .config import BASE_FEE_PER_SIGNATURE


def scheduler_priority(cu_price: int, cu_limit: int, cost_units: int, n_sig: int = 1) -> float:
    """Agave/Firedancer-style priority key: reward per cost unit.
    reward = priority fee (ceil(price x limit / 1e6)) + the non-burned half of the signature fee.
    Agave computes reward * 1_000_000 / (cost + 1) (integer); the ratio is what matters here."""
    prio_fee = math.ceil(cu_price * cu_limit / 1_000_000)
    reward = prio_fee + n_sig * BASE_FEE_PER_SIGNATURE // 2
    return reward * 1_000_000 / (cost_units + 1)


def load_jsonl(pattern: str) -> list[dict]:
    out = []
    for p in sorted(glob.glob(pattern)):
        with open(p) as f:
            out += [json.loads(x) for x in f if x.strip()]
    return out


def probe_rows(raw_dir: str = "data/raw") -> list[dict]:
    sent = [r for r in load_jsonl(os.path.join(raw_dir, "*.sent.jsonl")) if r["record"] == "probe" and r.get("mode") == "live"]
    landed = {r["signature"]: r for r in load_jsonl(os.path.join(raw_dir, "*.landed.jsonl"))}
    rows = []
    for p in sent:
        txs = []
        for t in p["txs"]:
            L = landed.get(t["signature"], {})
            txs.append({**t, "landed": L.get("record") == "landed", "slot": L.get("slot"), "tx_index": L.get("tx_index"),
                        "leader": L.get("leader"), "client_id": L.get("leader_client_id"), "version": L.get("leader_version"),
                        "fee": L.get("fee"), "cost_units": L.get("cost_units"), "err": L.get("err"),
                        "block_tx_count": L.get("block_tx_count")})
        all_landed = all(t["landed"] for t in txs)
        same_slot = all_landed and len({t["slot"] for t in txs}) == 1
        row = {"probe_id": p["probe_id"], "run_id": p["run_id"], "phase": p.get("phase"), "condition": p.get("condition"),
               "target_leader": p["target_leader"], "target_role": p.get("target_role"),
               "window_first_slot": p["window_first_slot"], "planned_send_slot": p["planned_send_slot"],
               "t_send_start": p.get("t_send_start"), "send_results": p.get("send_results"),
               "n_tx": len(txs), "all_landed": all_landed, "same_slot": same_slot, "txs": txs}
        if same_slot:
            row["slot"] = txs[0]["slot"]
            row["leader"] = txs[0]["leader"]
            row["client_id"], row["version"] = txs[0]["client_id"], txs[0]["version"]
            row["target_hit"] = row["leader"] == p["target_leader"]
            row["slot_in_window"] = row["slot"] - p["window_first_slot"] if row["target_hit"] else None
            order = sorted(range(len(txs)), key=lambda i: txs[i]["tx_index"])
            row["landing_order"] = order  # tx positions (in the probe's tx list) from earliest to latest
            row["first_sent"] = min(range(len(txs)), key=lambda i: txs[i]["send_pos"])
            row["first_landed"] = order[0]
            row["index_gap"] = abs(txs[0]["tx_index"] - txs[1]["tx_index"]) if len(txs) == 2 else None
        rows.append(row)
    return rows
