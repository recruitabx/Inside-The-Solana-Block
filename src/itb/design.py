"""Probe design of docs/PREREGISTRATION.md section 5 (arms, templates, randomization).

Per probe, independently, from the seeded generator: the arm (by the target's shares), which of
the two payers carries the high price, and the batch position of the high-price transaction.
Arm P: conflicting contrast (shared W), one batch.   Arm E: equal fee, shared W (one tx labelled
"pseudo-high" at random).   Arm D: contrast, separate W per tx.   Arm S: shared W, low sent alone,
high sent alone `gap_ms` later.
"""
from __future__ import annotations

import random

ARMS = ("P", "E", "D", "S")


def pick_arm(rng: random.Random, shares: dict[str, float]) -> str:
    x, acc = rng.random(), 0.0
    tot = sum(shares[a] for a in ARMS)
    for a in ARMS:
        acc += shares[a] / tot
        if x < acc:
            return a
    return ARMS[-1]


def make_probe(rng: random.Random, plan: dict, target: dict, arm: str | None = None) -> dict:
    shares = target.get("shares") or plan["shares"]
    arm = arm or pick_arm(rng, shares)
    hi_idx = rng.randrange(2)            # which payer slot carries the high price
    hi_pos = rng.randrange(2)            # batch position of the high-price transaction
    hi, lo = plan["price_high"], plan["price_low"]
    prices = [lo, lo] if arm == "E" else ([hi, lo] if hi_idx == 0 else [lo, hi])
    txs = [{"label": "high" if (arm != "E" and i == hi_idx) else ("pseudo-high" if (arm == "E" and i == hi_idx) else "low"),
            "cu_price": prices[i], "cu_limit": plan["cu_limit"], "loaded_limit": plan["loaded_limit"],
            "w_index": (i if arm == "D" else 0)} for i in range(2)]
    if arm == "S":
        order = [1 - hi_idx, hi_idx]     # low first, high gap_ms later
        gap_s = plan["gap_ms"] / 1000.0
    else:
        order = [hi_idx, 1 - hi_idx] if hi_pos == 0 else [1 - hi_idx, hi_idx]
        gap_s = 0.0
    return {"arm": arm, "condition": arm, "txs": txs, "order": order, "gap_s": gap_s,
            "hi_idx": hi_idx, "hi_pos": order.index(hi_idx)}
