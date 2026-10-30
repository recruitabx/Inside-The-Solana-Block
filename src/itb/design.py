"""Probe design: which transactions a probe contains and when it is sent.
PLACEHOLDER until docs/PREREGISTRATION.md is frozen; replaced by the preregistered design."""
from __future__ import annotations

import random


def make_probe(rng: random.Random, plan: dict, target: dict) -> dict:
    lo, hi = plan["cu_price_levels"][0], plan["cu_price_levels"][-1]
    labels = ["A", "B"]
    prices = [lo, hi]
    rng.shuffle(prices)
    return {"condition": "contrast", "send_offset_slots": rng.choice(plan["send_offsets_slots"]),
            "txs": [{"label": labels[i], "cu_price": prices[i], "cu_limit": plan["cu_limit"]} for i in range(2)]}
