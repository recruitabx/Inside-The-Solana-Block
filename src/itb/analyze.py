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
from .stats import binom_two_sided_p, holm, wilson_ci

DEFAULTS = {"primary_arm": "primary", "alpha": 0.05, "equiv_lo": 0.35, "equiv_hi": 0.65, "rule_min_p": 0.5,
            "min_n": 90}


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
    lo95, hi95 = wilson_ci(k, n, 0.95)
    lo90, hi90 = wilson_ci(k, n, 0.90)
    return {"n": n, "k": k, "p": p, "ci95": [lo95, hi95], "ci90": [lo90, hi90], "p_value": binom_two_sided_p(k, n)}


def verdict(est: dict, p_adj: float | None, cfg: dict, what: str) -> str:
    if est.get("n", 0) == 0:
        return "no data"
    if est["n"] < cfg["min_n"] and not (p_adj is not None and p_adj < cfg["alpha"]):
        return f"insufficient data (n={est['n']} < {cfg['min_n']})"
    if p_adj is not None and p_adj < cfg["alpha"]:
        direction = "first" if est["p"] > 0.5 else "LAST"
        return f"{what} decides order: higher-{what} tx lands {direction} in {est['p']:.0%} of pairs"
    lo, hi = est["ci90"]
    if cfg["equiv_lo"] <= lo and hi <= cfg["equiv_hi"]:
        return f"no detectable {what} rule (90% CI {lo:.2f}-{hi:.2f} inside [{cfg['equiv_lo']}, {cfg['equiv_hi']}])"
    return "insufficient data (inconclusive)"


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
    for what in ("fee", "send"):
        ps = [t[what].get("p_value", 1.0) for t in table]
        for t, pa in zip(table, holm(ps) if ps else []):
            t[what]["p_holm"] = pa
            t[what]["verdict"] = verdict(t[what], pa, cfg, what)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "verdicts.json"), "w") as f:
        json.dump({"config": cfg, "validators": table}, f, indent=1, sort_keys=True)
    with open(os.path.join(out_dir, "verdicts.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["leader", "client_id", "version", "n_same_slot", "p_fee_first", "ci95_lo", "ci95_hi", "p_holm_fee",
                    "verdict_fee", "q_sent_first", "q_ci95_lo", "q_ci95_hi", "verdict_send"])
        for t in table:
            fe, se = t["fee"], t["send"]
            w.writerow([t["leader"], t.get("client_id"), t.get("version"), t["n_same_slot"], fe.get("p"),
                        *(fe.get("ci95") or [None, None]), fe.get("p_holm"), fe.get("verdict"), se.get("p"),
                        *(se.get("ci95") or [None, None]), se.get("verdict")])
    return {"n_rows": len(rows), "validators": len(table)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="itb analyze")
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--out", default="results")
    a = ap.parse_args(argv)
    print(json.dumps(analyze(a.raw, a.out, dict(DEFAULTS))))
    return 0
