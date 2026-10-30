"""Synthetic raw data with a KNOWN ordering rule, in exactly the on-disk format of real runs
(phase "main", flagged `"synthetic": true`, so that `itb analyze` accepts it without --final).
Used to show that `itb analyze` recovers planted rules and stays silent on random order
(pilot acceptance criterion 1 in docs/PREREGISTRATION.md) and to test every secondary table."""
from __future__ import annotations

import json
import math
import os
import random

HIGH_PRICE, LOW_PRICE = 5_500_000, 1_000
HIGH_FEE, LOW_FEE = 10_500, 5_001


def _cells(v: dict, arm: str) -> list[dict]:
    """The probe groups planted for one validator. Flat form: n pairs of `arm` with p_fee / p_send.
    Extended form: v["cells"] = [{"arm": "S", "n": 40, "p_send": 1.0, ...}, ...]."""
    if "cells" in v:
        return [dict(c) for c in v["cells"]]
    return [{"arm": arm, "n": v["n"], **{k: v[k] for k in ("p_fee", "p_send") if k in v}}]


def write_synthetic(raw_dir: str, validators: dict[str, dict], seed: int = 0, arm: str = "P") -> None:
    """validators: {identity: {"n": pairs, "p_fee": P(high fee first), "p_send": P(first-sent first),
    "client_id": str, "version": str, "role": str, "claim_end_version": str, "cells": [...]}}.
    A cell may also carry: p_miss, p_one (landing outcomes), p_diff_slot, p_other_leader, p_err (per pair),
    p_copresent (share of pairs whose provider slot was before the window), p_fee_co (p_fee for those
    pairs when they land in the first slot), strategy (Harmonic memo label of the window's first block).
    b_fee / b_send give a logistic mixture of both rules. When p_send is given and p_fee is 0.5, order follows send order with probability p_send, else the
    fee rule wins with probability p_fee."""
    rng = random.Random(seed)
    os.makedirs(raw_dir, exist_ok=True)
    run = f"synthetic-live-{seed}"
    sent = open(os.path.join(raw_dir, f"{run}.sent.jsonl"), "w")
    landed = open(os.path.join(raw_dir, f"{run}.landed.jsonl"), "w")
    blocks = open(os.path.join(raw_dir, f"{run}.blocks.jsonl"), "w")
    sent.write(json.dumps({"record": "run_start", "run_id": run, "mode": "live", "phase": "main",
                           "targets_client_now": {i: v.get("client_id") for i, v in validators.items()},
                           "targets_version_now": {i: v.get("version") for i, v in validators.items()}}) + "\n")
    slot = 470_000_000
    k = 0
    for ident, v in validators.items():
        role = v.get("role", ident)
        for cell in (c for c in _cells(v, arm)):
            carm = cell["arm"]
            for _ in range(cell["n"]):
                k += 1; slot += 8
                first_slot, last_slot = slot, slot + 3
                hi = rng.randrange(2)                 # which tx gets the high fee (E: the pseudo-high one)
                send_first = rng.randrange(2)         # independent send position
                prices = [LOW_PRICE, LOW_PRICE]
                if carm != "E":
                    prices[hi] = HIGH_PRICE
                labels = ["low", "low"]
                labels[hi] = "pseudo-high" if carm == "E" else "high"
                copresent = rng.random() < cell.get("p_copresent", 0.5)
                observed = first_slot - 1 if copresent else first_slot
                u = rng.random()
                outcome = ("miss" if u < cell.get("p_miss", 0.0) else
                           "one" if u < cell.get("p_miss", 0.0) + cell.get("p_one", 0.0) else "both")
                where = "target"
                if outcome == "both":
                    w = rng.random()
                    if w < cell.get("p_diff_slot", 0.0):
                        where = "diff_slot"
                    elif w < cell.get("p_diff_slot", 0.0) + cell.get("p_other_leader", 0.0):
                        where = "other"
                land_slot = first_slot if rng.random() < cell.get("p_first_slot", 0.5) else first_slot + rng.randrange(1, 4)
                p_fee = cell.get("p_fee", 0.5)
                if "p_fee_co" in cell and copresent and land_slot == first_slot:
                    p_fee = cell["p_fee_co"]
                if "b_fee" in cell or "b_send" in cell:
                    # both rules at once: P(tx 0 first) = sigmoid(score_0 - score_1), score = b_fee [high] + b_send [sent first]
                    d = cell.get("b_fee", 0.0) * ((hi == 0) - (hi == 1)) + cell.get("b_send", 0.0) * ((send_first == 0) - (send_first == 1))
                    first = 0 if rng.random() < 1 / (1 + math.exp(-d)) else 1
                elif "p_send" in cell and p_fee == 0.5:
                    first = send_first if rng.random() < cell["p_send"] else 1 - send_first
                else:
                    first = hi if rng.random() < p_fee else 1 - hi
                s_low_first = None
                if carm == "S":
                    s_low_first = send_first != hi    # the first-sent transaction is the low one
                err_tx = rng.randrange(2) if rng.random() < cell.get("p_err", 0.0) else None
                txs = [{"signature": f"S{k}x{i}", "payer": f"P{i}", "cu_limit": 1000, "cu_price": prices[i],
                        "max_fee": HIGH_FEE if prices[i] == HIGH_PRICE else LOW_FEE, "label": labels[i],
                        "send_pos": 0 if i == send_first else 1} for i in range(2)]
                sent.write(json.dumps({"record": "probe", "mode": "live", "run_id": run, "probe_id": f"{run}:{k}",
                                       "phase": "main", "synthetic": True, "arm": carm, "condition": carm,
                                       "target_leader": ident, "target_role": role,
                                       "target_client_id": v.get("client_id"), "target_version": v.get("version"),
                                       "window_first_slot": first_slot, "window_last_slot": last_slot,
                                       "planned_send_slot": first_slot, "tau0_ms": -170,
                                       "observed_slot_after_send": observed, "s_low_first": s_low_first,
                                       "hi_idx": hi, "txs": txs, "send_results": ["ok", "ok"]}) + "\n")
                if cell.get("strategy"):
                    blocks.write(json.dumps({"record": "block", "slot": first_slot, "producer": ident, "tx_count": 400,
                                             "strategy": cell["strategy"], "strategy_tx_index": 0}) + "\n")
                other = f"OTHER{rng.randrange(3)}"
                for i in range(2):
                    gone = outcome == "miss" or (outcome == "one" and i != send_first)
                    if gone:
                        landed.write(json.dumps({"record": "not_landed", "signature": f"S{k}x{i}", "probe_id": f"{run}:{k}",
                                                 "reason": "unknown to cluster at collection time"}) + "\n")
                        continue
                    idx = 10 if i == first else 11
                    sl, leader, cid, ver = land_slot, ident, v.get("client_id"), v.get("version")
                    if where == "diff_slot":
                        sl, idx = land_slot + (0 if i == first else 1), 10
                    elif where == "other":
                        leader, cid, ver = other, "Agave", "4.3.2"
                    landed.write(json.dumps({"record": "landed", "signature": f"S{k}x{i}", "probe_id": f"{run}:{k}",
                                             "slot": sl, "tx_index": idx, "block_tx_count": 400, "leader": leader,
                                             "leader_client_id": cid, "leader_version": ver,
                                             "fee": HIGH_FEE if prices[i] == HIGH_PRICE else LOW_FEE, "cost_units": 2000,
                                             "err": ({"InstructionError": [0, "Custom"]} if err_tx == i else None)}) + "\n")
    ends = {i: v.get("claim_end_version", v.get("version")) for i, v in validators.items()}
    sent.write(json.dumps({"record": "run_end", "run_id": run, "targets_client_end": {i: v.get("client_id") for i, v in validators.items()},
                           "targets_version_end": ends}) + "\n")
    sent.close(); landed.close(); blocks.close()
