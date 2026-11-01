"""Probe design of docs/PREREGISTRATION.md section 5 (arms, templates, randomization).

Per probe, independently, from a generator seeded with "<seed>:<window first slot>:<target
identity>" (see runner.probe_rng): the arm (by the target's shares), which of the two payers
carries the high price, and the request position of the high-price transaction.
Arm P: conflicting contrast (shared W), one batch.   Arm E: equal fee, shared W (one tx labelled
"pseudo-high" at random).   Arm D: contrast, separate W per tx.   Arm S: shared W, two requests
`gap_ms` apart; which of the low and the high transaction is sent first is random (50/50,
recorded as `s_low_first`).
"""
from __future__ import annotations

import random

ARMS = ("P", "E", "D", "S")


def probe_rng_key(plan: dict, first_slot: int, leader: str) -> str:
    """Key of the per-window generator. It depends on the window only, so the assignment of a
    window never depends on which earlier windows were skipped."""
    return f"{plan['seed']}:{first_slot}:{leader}"


def probe_rng(plan: dict, first_slot: int, leader: str) -> random.Random:
    return random.Random(probe_rng_key(plan, first_slot, leader))


def pick_arm(rng: random.Random, shares: dict[str, float]) -> str:
    x, acc = rng.random(), 0.0
    tot = sum(shares[a] for a in ARMS)
    for a in ARMS:
        acc += shares[a] / tot
        if x < acc:
            return a
    return ARMS[-1]


def pilot_arm(i: int, plan: dict) -> str:
    """Arm of the i-th pilot probe (0-based) of one target: `pilot_per_target` P probes and
    `pilot_s_per_target` S probes, the S probes spread evenly over the sequence so that a run
    cut short still contains some. Deterministic, never read from outcomes."""
    n_p = int(plan.get("pilot_per_target", 12))
    n_s = int(plan.get("pilot_s_per_target", 2))
    if n_s <= 0:
        return "P"
    period = max(1, (n_p + n_s) // n_s)
    k = (i + 1) // period      # S probes that belong before and at position i
    return "S" if (i + 1) % period == 0 and k <= n_s else "P"


def make_probe(rng: random.Random, plan: dict, target: dict, arm: str | None = None) -> dict:
    shares = target.get("shares") or plan["shares"]
    arm = arm or pick_arm(rng, shares)
    hi_idx = rng.randrange(2)            # which payer slot carries the high price
    hi_pos = rng.randrange(2)            # request position of the high-price transaction
    hi, lo = plan["price_high"], plan["price_low"]
    prices = [lo, lo] if arm == "E" else ([hi, lo] if hi_idx == 0 else [lo, hi])
    txs = [{"label": "high" if (arm != "E" and i == hi_idx) else ("pseudo-high" if (arm == "E" and i == hi_idx) else "low"),
            "cu_price": prices[i], "cu_limit": plan["cu_limit"], "loaded_limit": plan["loaded_limit"],
            "w_index": (i if arm == "D" else 0)} for i in range(2)]
    order = [hi_idx, 1 - hi_idx] if hi_pos == 0 else [1 - hi_idx, hi_idx]
    gap_s = plan["gap_ms"] / 1000.0 if arm == "S" else 0.0
    return {"arm": arm, "condition": arm, "txs": txs, "order": order, "gap_s": gap_s,
            "hi_idx": hi_idx, "hi_pos": order.index(hi_idx),
            "s_low_first": (order[0] != hi_idx) if arm == "S" else None}
