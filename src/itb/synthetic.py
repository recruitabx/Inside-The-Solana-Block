"""Synthetic raw data with a KNOWN ordering rule, in exactly the on-disk format of real runs.
Used to show that `itb analyze` recovers planted rules and stays silent on random order
(pilot acceptance criterion (i) in docs/PREREGISTRATION.md)."""
from __future__ import annotations

import json
import os
import random


def write_synthetic(raw_dir: str, validators: dict[str, dict], seed: int = 0, arm: str = "primary") -> None:
    """validators: {identity: {"n": pairs, "p_fee": P(high fee first), "p_send": P(first-sent first),
    "client_id": str, "version": str}}. When both rules are present the fee rule wins with
    probability p_fee, else order follows send order with probability p_send."""
    rng = random.Random(seed)
    os.makedirs(raw_dir, exist_ok=True)
    run = f"synthetic-live-{seed}"
    sent = open(os.path.join(raw_dir, f"{run}.sent.jsonl"), "w")
    landed = open(os.path.join(raw_dir, f"{run}.landed.jsonl"), "w")
    slot = 470_000_000
    k = 0
    for ident, v in validators.items():
        for _ in range(v["n"]):
            k += 1; slot += 8
            hi = rng.randrange(2)                 # which tx gets the high fee
            send_first = rng.randrange(2)         # independent send position
            prices = [1_000, 1_000]; prices[hi] = 8_400_000
            if rng.random() < v.get("p_fee", 0.5):
                first = hi
            else:
                first = 1 - hi
            if "p_send" in v and v.get("p_fee", 0.5) == 0.5:
                first = send_first if rng.random() < v["p_send"] else 1 - send_first
            txs = [{"signature": f"S{k}x{i}", "payer": f"P{i}", "cu_limit": 600, "cu_price": prices[i],
                    "memo": "", "max_fee": 5001, "label": "AB"[i], "send_pos": 0 if i == send_first else 1} for i in range(2)]
            sent.write(json.dumps({"record": "probe", "mode": "live", "run_id": run, "probe_id": f"{run}:{k}",
                                   "phase": "synthetic", "condition": arm, "target_leader": ident, "target_role": ident,
                                   "window_first_slot": slot, "planned_send_slot": slot, "txs": txs,
                                   "send_results": ["ok", "ok"]}) + "\n")
            idx = {first: 10, 1 - first: 11}
            for i in range(2):
                landed.write(json.dumps({"record": "landed", "signature": f"S{k}x{i}", "probe_id": f"{run}:{k}",
                                         "slot": slot, "tx_index": idx[i], "block_tx_count": 400, "leader": ident,
                                         "leader_client_id": v.get("client_id"), "leader_version": v.get("version"),
                                         "fee": 5001, "cost_units": 2000}) + "\n")
    sent.close(); landed.close()
