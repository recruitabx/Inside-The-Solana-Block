"""`itb analyze`: every table, verdict and figure of the report, from data/raw only.

Primary estimands (per block producer, primary arm, same-slot pairs only), fixed in
docs/PREREGISTRATION.md:
  p  = P(the transaction with the higher scheduler priority (reward per cost unit) lands first)
  q  = P(the transaction that was sent first lands first)
  pi = 2p - 1, read as "share of pairs decided by fee".
Fee contrast and send position are randomized independently, so p and q are estimated from the
same pairs without confounding each other.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from collections import defaultdict

from .pairs import probe_rows, scheduler_priority
from .stats import binom_two_sided_p, clopper_pearson, holm

# Section 9 of docs/PREREGISTRATION.md
DEFAULTS = {"primary_arm": "P", "alpha": 0.05, "equiv_lo": 0.35, "equiv_hi": 0.65, "strict_lb": 0.90,
            "strong_lb": 0.75, "min_n": 100}


def pair_outcomes(row: dict) -> dict | None:
    """For a same-slot 2-tx probe: which landed first, by fee and by send order."""
    if not row.get("same_slot") or row["n_tx"] != 2:
        return None
    a, b = row["txs"]
    pa = scheduler_priority(a["cu_price"], a["cu_limit"], a.get("cost_units") or 0)
    pb = scheduler_priority(b["cu_price"], b["cu_limit"], b.get("cost_units") or 0)
    first = row["first_landed"]
    out = {"first_sent_first": int(first == row["first_sent"]), "fee_contrast": pa != pb}
    if pa != pb:
        hi = 0 if pa > pb else 1
        out["high_fee_first"] = int(first == hi)
        out["high_fee_sent_first"] = int(row["first_sent"] == hi)
    return out


def estimate(k: int, n: int, cfg: dict) -> dict:
    if n == 0:
        return {"n": 0}
    p = k / n
    lo95, hi95 = clopper_pearson(k, n, 0.95)
    lo90, hi90 = clopper_pearson(k, n, 0.90)
    return {"n": n, "k": k, "p": p, "ci95": [lo95, hi95], "ci90": [lo90, hi90], "p_value": binom_two_sided_p(k, n)}


def rule_strength(est: dict, p_adj: float, cfg: dict) -> str | None:
    """None if p = 0.5 is not rejected; else strict / strong / partial, by the 95% lower bound of
    max(p, 1 - p) (a rule may also run in the reverse direction, which is reported as such)."""
    if est.get("n", 0) == 0 or p_adj >= cfg["alpha"]:
        return None
    lo, hi = est["ci95"]
    lb = lo if est["p"] >= 0.5 else 1 - hi
    return "strict" if lb >= cfg["strict_lb"] else "strong" if lb >= cfg["strong_lb"] else "partial"


def inside_equivalence(est: dict, cfg: dict) -> bool:
    lo, hi = est["ci90"]
    return cfg["equiv_lo"] <= lo and hi <= cfg["equiv_hi"]


def verdict(fee: dict, send: dict, cfg: dict) -> str:
    """Decision rules of PREREGISTRATION.md section 9 for one validator (primary cell)."""
    if fee.get("n", 0) == 0:
        return "no data"
    sf, ss = rule_strength(fee, fee["p_holm"], cfg), rule_strength(send, send["p_holm"], cfg)
    rev = lambda e: "" if e["p"] >= 0.5 else " (REVERSED: lower-priority/later-sent first)"
    if sf and ss:
        return f"mixed: fee rule {sf}{rev(fee)} and send-order rule {ss}{rev(send)}"
    if sf:
        return f"fee rule holds, {sf}{rev(fee)}"
    if ss:
        return f"send-order rule holds, {ss}{rev(send)}"
    if fee["n"] >= cfg["min_n"] and inside_equivalence(fee, cfg) and inside_equivalence(send, cfg):
        return "no detectable rule"
    return f"insufficient data (n={fee['n']})"


def analyze(raw_dir: str, out_dir: str, cfg: dict) -> dict:
    rows = probe_rows(raw_dir)
    by = defaultdict(lambda: defaultdict(lambda: {"fee": [0, 0], "send": [0, 0], "n_probes": 0, "n_same": 0}))
    meta = {}
    for r in rows:
        key = r.get("leader") if r.get("same_slot") else r["target_leader"]
        arm = r.get("condition") or "?"
        cell = by[key][arm]
        cell["n_probes"] += 1
        o = pair_outcomes(r)
        if o is None:
            continue
        cell["n_same"] += 1
        meta[key] = {"client_id": r.get("client_id"), "version": r.get("version")}
        cell["send"][0] += o["first_sent_first"]; cell["send"][1] += 1
        if o["fee_contrast"]:
            cell["fee"][0] += o["high_fee_first"]; cell["fee"][1] += 1
    table = []
    for leader, arms in by.items():
        c = arms.get(cfg["primary_arm"])
        if not c:
            continue
        table.append({"leader": leader, **meta.get(leader, {}), "n_probes": c["n_probes"], "n_same_slot": c["n_same"],
                      "fee": estimate(*c["fee"], cfg), "send": estimate(*c["send"], cfg)})
    for what in ("fee", "send"):  # Holm within each family across validators
        ps = [t[what].get("p_value", 1.0) for t in table]
        for t, pa in zip(table, holm(ps) if ps else []):
            t[what]["p_holm"] = pa
    for t in table:
        t["verdict"] = verdict(t["fee"], t["send"], cfg)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "verdicts.json"), "w") as f:
        json.dump({"config": cfg, "validators": table}, f, indent=1, sort_keys=True)
    with open(os.path.join(out_dir, "verdicts.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["leader", "client_id", "version", "n_usable", "p_fee_first", "p_ci95_lo", "p_ci95_hi", "p_holm",
                    "q_sent_first", "q_ci95_lo", "q_ci95_hi", "q_holm", "verdict"])
        for t in table:
            fe, se = t["fee"], t["send"]
            w.writerow([t["leader"], t.get("client_id"), t.get("version"), fe.get("n"), fe.get("p"),
                        *(fe.get("ci95") or [None, None]), fe.get("p_holm"), se.get("p"),
                        *(se.get("ci95") or [None, None]), se.get("p_holm"), t["verdict"]])
    return {"n_rows": len(rows), "validators": len(table)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="itb analyze")
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--out", default="results")
    a = ap.parse_args(argv)
    print(json.dumps(analyze(a.raw, a.out, dict(DEFAULTS))))
    return 0
