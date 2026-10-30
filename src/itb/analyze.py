"""`itb analyze`: every table, verdict and figure of the report, from data/raw only.

Confirmatory part (docs/PREREGISTRATION.md sections 7 to 9). Estimands per unit
(target_role, identity, clientId, version), taken from the primary cell:
  p  = P(the transaction with the higher reward per cost unit lands first)
  q  = P(the transaction that was sent first lands first)
  pi = 2p - 1, read as "share of pairs decided by fee".
Primary cell: main-phase arm-P probes with both transactions in ONE block whose producer (the Fee
reward pubkey of the block) is the target, in a slot of the targeted window, from a run in which
the target's (clientId, version) claim did not change between the start and the end snapshot.
Fee contrast and request position are randomized independently, so p and q come from the same pairs.

`itb analyze` refuses to read main-phase data unless run with --final (run once, after the last
main run). Without it only pilot and synthetic data are analysed (never confirmatory).
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
from collections import defaultdict

import numpy as np
from scipy import stats as sp_stats

from .pairs import load_block_summaries, probe_rows
from .stats import binom_two_sided_p, clopper_pearson, holm

# Sections 8 and 9 of docs/PREREGISTRATION.md
DEFAULTS = {"primary_arm": "P", "alpha": 0.05, "equiv_lo": 0.35, "equiv_hi": 0.65, "strict_lb": 0.90,
            "strong_lb": 0.75, "min_n": 100, "min_n_s": 30}

NO_RULE = "no fee or request-position rule detected (|pi| <= 0.30)"
FIFO_NOTE = "; arrival order (FIFO) not excluded"


# ---- selection of rows ----------------------------------------------------------------------------

def select_rows(rows: list[dict], final: bool) -> tuple[list[dict], int]:
    """Rows to analyse and the number of main-phase rows refused.
    final: only phase == "main". Not final: only pilot and synthetic data; real main-phase rows are refused."""
    if final:
        return [r for r in rows if r.get("phase") == "main"], 0
    keep = [r for r in rows if r.get("synthetic") or r.get("phase") == "pilot"]
    refused = sum(1 for r in rows if r.get("phase") == "main" and not r.get("synthetic"))
    return keep, refused


# ---- per-pair outcomes ----------------------------------------------------------------------------

def high_index(row: dict) -> int | None:
    """Position (in the probe's tx list) of the higher-fee transaction (arm E: the pseudo-high one)."""
    a, b = row["txs"][0], row["txs"][1]
    if a["cu_price"] != b["cu_price"]:
        return 0 if a["cu_price"] > b["cu_price"] else 1
    for i, t in enumerate(row["txs"]):
        if t.get("label") == "pseudo-high":
            return i
    return None


def in_cell(row: dict, arm: str) -> bool:
    """Both transactions in one block produced by the target, in the targeted window, claim unchanged."""
    return (row.get("arm") == arm and row["n_tx"] == 2 and row["same_slot"] and row.get("target_hit") is True
            and row.get("in_window") is True and not row["claim_changed_in_run"])


def outcomes(row: dict) -> dict:
    """For a same-slot 2-tx probe: Y_fee (high lands first), Y_send (first-sent lands first)."""
    hi = high_index(row)
    out = {"y_send": int(row["first_landed"] == row["first_sent"]), "hi": hi}
    if hi is not None:
        out["y_fee"] = int(row["first_landed"] == hi)
        out["high_sent_first"] = int(row["first_sent"] == hi)
    return out


def unit_key(row: dict) -> tuple:
    return (row.get("target_role"), row["target_leader"], row.get("claim_client_id"), row.get("claim_version"))


# ---- estimates and verdicts -----------------------------------------------------------------------

def estimate(k: int, n: int) -> dict:
    if n == 0:
        return {"n": 0}
    lo95, hi95 = clopper_pearson(k, n, 0.95)
    lo90, hi90 = clopper_pearson(k, n, 0.90)
    return {"n": n, "k": k, "p": k / n, "ci95": [lo95, hi95], "ci90": [lo90, hi90], "p_value": binom_two_sided_p(k, n)}


def rule_strength(est: dict, p_adj: float | None, cfg: dict) -> tuple[str, bool] | None:
    """None if p = 0.5 is not rejected (Holm-adjusted p >= alpha); else (strict | strong | partial, reverse),
    by the 95% lower bound L of p, or of 1 - p for a reverse rule."""
    if est.get("n", 0) == 0 or p_adj is None or p_adj >= cfg["alpha"]:
        return None
    lo, hi = est["ci95"]
    reverse = est["p"] < 0.5
    lb = 1 - hi if reverse else lo
    return ("strict" if lb >= cfg["strict_lb"] else "strong" if lb >= cfg["strong_lb"] else "partial"), reverse


def inside_equivalence(est: dict | None, cfg: dict) -> bool:
    if not est or est.get("n", 0) == 0:
        return False
    lo, hi = est["ci90"]
    return cfg["equiv_lo"] <= lo and hi <= cfg["equiv_hi"]


def verdict(fee: dict, send: dict, cfg: dict, s_pooled: dict | None = None) -> str:
    """Decision rules of PREREGISTRATION.md section 9 for one unit (primary cell).
    s_pooled: estimate of the pooled arm-S q_S of the unit's clientId (for the FIFO remark)."""
    n = fee.get("n", 0)
    if n < cfg["min_n"]:
        return f"insufficient data (n={n})"
    sf, ss = rule_strength(fee, fee.get("p_holm"), cfg), rule_strength(send, send.get("p_holm"), cfg)

    def label(base: str, s: tuple[str, bool]) -> str:
        return ("reverse " if s[1] else "") + base
    if sf and ss:
        return f"mixed: {label('fee rule', sf)} {sf[0]} and {label('send-order rule', ss)} {ss[0]}"
    if sf:
        return f"{label('fee rule', sf)} holds, {sf[0]}"
    if ss:
        return f"{label('send-order rule', ss)} holds, {ss[0]}"
    if inside_equivalence(fee, cfg) and inside_equivalence(send, cfg):
        fifo_open = s_pooled is None or s_pooled.get("n", 0) < cfg["min_n_s"] or not inside_equivalence(s_pooled, cfg)
        return NO_RULE + (FIFO_NOTE if fifo_open else "")
    return f"insufficient data (n={n})"


# ---- logistic sensitivity model -------------------------------------------------------------------

LOGIT_TERMS = ["intercept", "A_is_high", "A_sent_first"]


def logit_irls(X: np.ndarray, y: np.ndarray, max_iter: int = 100, tol: float = 1e-10, ridge: float = 1e-9) -> dict:
    """Logistic regression by iteratively reweighted least squares (numpy only).
    Returns coefficients, standard errors (inverse Fisher information), convergence flags."""
    n, m = X.shape
    if n < m or np.linalg.matrix_rank(X) < m:
        return {"n": int(n), "error": "design matrix is rank deficient"}
    beta, dev_old, converged = np.zeros(m), np.inf, False
    for _ in range(max_iter):
        eta = np.clip(X @ beta, -30, 30)
        mu = 1 / (1 + np.exp(-eta))
        w = np.maximum(mu * (1 - mu), 1e-12)
        z = eta + (y - mu) / w
        xtwx = X.T @ (w[:, None] * X) + ridge * np.eye(m)
        beta = np.linalg.solve(xtwx, X.T @ (w * z))
        mu2 = 1 / (1 + np.exp(-np.clip(X @ beta, -30, 30)))
        dev = -2 * float(np.sum(y * np.log(np.clip(mu2, 1e-15, 1)) + (1 - y) * np.log(np.clip(1 - mu2, 1e-15, 1))))
        if abs(dev_old - dev) < tol * (abs(dev) + 0.1):
            converged = True
            break
        dev_old = dev
    eta = np.clip(X @ beta, -30, 30)
    mu = 1 / (1 + np.exp(-eta))
    w = np.maximum(mu * (1 - mu), 1e-12)
    cov = np.linalg.inv(X.T @ (w[:, None] * X) + ridge * np.eye(m))
    se = np.sqrt(np.diag(cov))
    return {"n": int(n), "coef": dict(zip(LOGIT_TERMS, map(float, beta))), "se": dict(zip(LOGIT_TERMS, map(float, se))),
            "converged": bool(converged), "separation": bool(np.max(np.abs(beta)) > 12 or np.max(se) > 50)}


def unit_logit(cell_rows: list[dict]) -> dict:
    """Y = transaction A (the first of the probe's two transactions) landed first, on (A is high) and (A sent first)."""
    X, y = [], []
    for r in cell_rows:
        o = outcomes(r)
        if o["hi"] is None:
            continue
        X.append([1.0, float(o["hi"] == 0), float(r["txs"][0]["send_pos"] == 0)])
        y.append(float(r["first_landed"] == 0))
    if not y:
        return {"n": 0, "error": "no pairs"}
    return logit_irls(np.array(X), np.array(y))


def table_2x2(cell_rows: list[dict]) -> dict:
    """High-fee transaction sent first (yes/no) by high-fee transaction landed first (yes/no)."""
    t = {"sent_first_landed_first": 0, "sent_first_landed_second": 0, "sent_second_landed_first": 0, "sent_second_landed_second": 0}
    for r in cell_rows:
        o = outcomes(r)
        if o["hi"] is None:
            continue
        t[f"sent_{'first' if o['high_sent_first'] else 'second'}_landed_{'first' if o['y_fee'] else 'second'}"] += 1
    return t


# ---- helpers --------------------------------------------------------------------------------------

def _pooled(rows: list[dict], arm: str, extra=None) -> dict:
    """Counts of Y_fee and Y_send over the cell rows of one arm (optionally restricted by `extra`)."""
    kf = nf = ks = ns = 0
    for r in rows:
        if not in_cell(r, arm) or (extra and not extra(r)):
            continue
        o = outcomes(r)
        ks += o["y_send"]; ns += 1
        if "y_fee" in o:
            kf += o["y_fee"]; nf += 1
    return {"fee": estimate(kf, nf), "send": estimate(ks, ns)}


def _secondary_holm(ests: list[dict]) -> None:
    """Holm over the binomial tests of the secondary family (separate from the confirmatory family)."""
    idx = [i for i, e in enumerate(ests) if e.get("n", 0) > 0]
    for i, pa in zip(idx, holm([ests[i]["p_value"] for i in idx]) if idx else []):
        ests[i]["p_holm"] = pa


def _strength_label(est: dict, cfg: dict, base: str) -> str | None:
    s = rule_strength(est, est.get("p_holm"), cfg)
    return None if s is None else f"{'reverse ' if s[1] else ''}{base} {s[0]}"


def fisher(k1: int, n1: int, k2: int, n2: int) -> dict:
    if n1 == 0 or n2 == 0:
        return {"n1": n1, "n2": n2}
    odds, p = sp_stats.fisher_exact([[k1, n1 - k1], [k2, n2 - k2]])
    return {"k1": k1, "n1": n1, "k2": k2, "n2": n2, "odds_ratio": None if math.isinf(odds) else float(odds), "p_value": float(p)}


# ---- the analysis ---------------------------------------------------------------------------------

def analyze_rows(rows: list[dict], blocks: dict[int, dict], cfg: dict) -> dict:
    arm_p = cfg["primary_arm"]
    by_unit: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        by_unit[unit_key(r)].append(r)

    units = []
    for key in sorted(by_unit, key=lambda k: tuple(str(x) for x in k)):
        urows = by_unit[key]
        prow = [r for r in urows if r.get("arm") == arm_p]
        cell = [r for r in prow if in_cell(r, arm_p)]
        excl = {"claim_changed_in_run": 0, "none_landed": 0, "one_landed": 0, "different_slots": 0,
                "other_producer": 0, "target_outside_window": 0, "primary": len(cell), "primary_with_execution_error": 0,
                "claim_end_unknown": 0}
        for r in prow:
            n_l = sum(t["landed"] for t in r["txs"])
            if r["claim_changed_in_run"]:
                excl["claim_changed_in_run"] += 1
            elif n_l == 0:
                excl["none_landed"] += 1
            elif n_l < r["n_tx"]:
                excl["one_landed"] += 1
            elif not r["same_slot"]:
                excl["different_slots"] += 1
            elif not r["target_hit"]:
                excl["other_producer"] += 1
            elif not r["in_window"]:
                excl["target_outside_window"] += 1
            excl["claim_end_unknown"] += int(r["claim_end_unknown"])
        for r in cell:
            excl["primary_with_execution_error"] += int(any(t.get("err") or t.get("status_err") for t in r["txs"]))
        kf = sum(outcomes(r).get("y_fee", 0) for r in cell)
        ks = sum(outcomes(r)["y_send"] for r in cell)
        nf = sum("y_fee" in outcomes(r) for r in cell)
        units.append({"target_role": key[0], "identity": key[1], "client_id": key[2], "version": key[3],
                      "n_probes_arm_P": len(prow), "n_probes_all_arms": len(urows), "exclusions": excl,
                      "n_primary": len(cell), "fee": estimate(kf, nf), "send": estimate(ks, len(cell)),
                      "table_2x2": table_2x2(cell), "logit": unit_logit(cell)})
    # one Holm family over all p and q tests of all units
    tests = [(u, w) for u in units for w in ("fee", "send") if u[w].get("n", 0) > 0]
    for (u, w), pa in zip(tests, holm([u[w]["p_value"] for u, w in tests]) if tests else []):
        u[w]["p_holm"] = pa
    # pooled arm-S q_S per clientId, for the FIFO remark
    s_by_client = {}
    for c in sorted({str(r.get("claim_client_id")) for r in rows}):
        s_by_client[c] = _pooled([r for r in rows if str(r.get("claim_client_id")) == c], "S")["send"]
    for u in units:
        u["pi"] = 2 * u["fee"]["p"] - 1 if u["fee"].get("n") else None
        u["verdict"] = verdict(u["fee"], u["send"], cfg, s_by_client.get(str(u["client_id"])))
    return {"units": units, "holm_family_size": len(tests), "secondary": secondary(rows, blocks, cfg, s_by_client)}


def secondary(rows: list[dict], blocks: dict[int, dict], cfg: dict, s_by_client: dict) -> dict:
    """Pooled-by-clientId secondary results (descriptive; arm D vs P and the Harmonic strategy are exploratory)."""
    arm_p = cfg["primary_arm"]
    clients = sorted({str(r.get("claim_client_id")) for r in rows})
    groups = {c: [r for r in rows if str(r.get("claim_client_id")) == c] for c in clients}
    groups["ALL"] = rows
    out: dict = {"note": "pooled by the target's clientId claim; confirmatory family is separate; Holm below is within each table",
                 "arm_E": {}, "arm_S": {}, "arm_D_vs_P": {}, "copresence_p_co": {}, "harmonic_strategy": {}}
    for name, arm in (("arm_E", "E"), ("arm_S", "S")):
        ests = []
        for c, g in groups.items():
            pl = _pooled(g, arm)
            row = {"client_id": c, "q": pl["send"], "p": pl["fee"]}   # arm E: p is the placebo p_E (pseudo-high label)
            out[name][c] = row
            ests += [pl["send"], pl["fee"]]
        _secondary_holm(ests)
        for row in out[name].values():
            row["q_rule"] = _strength_label(row["q"], cfg, "send-order rule")
            row["p_rule"] = _strength_label(row["p"], cfg, "fee rule")
    for c, g in groups.items():
        d, pp = _pooled(g, "D")["fee"], _pooled(g, arm_p)["fee"]
        out["arm_D_vs_P"][c] = {"label": "exploratory", "p_D": d, "p_P": pp,
                                "fisher_fee_first": fisher(d.get("k", 0), d.get("n", 0), pp.get("k", 0), pp.get("n", 0))}
        co = _pooled(g, arm_p, lambda r: r.get("observed_slot_after_send") is not None
                     and r["observed_slot_after_send"] <= r["window_first_slot"] - 1 and r["slot"] == r["window_first_slot"])
        out["copresence_p_co"][c] = {"p_co": co["fee"], "q_co": co["send"]}
    _secondary_holm([v["p_co"] for v in out["copresence_p_co"].values()])
    for v in out["copresence_p_co"].values():
        v["rule"] = _strength_label(v["p_co"], cfg, "fee rule")
    # Harmonic strategy memo of the window's first block (exploratory)
    hk: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        if in_cell(r, arm_p) and str(r.get("claim_client_id")).startswith("Harmonic"):
            b = blocks.get(r["window_first_slot"])
            lab = "no block summary" if b is None else (b.get("strategy") or "no memo")
            hk[lab][0] += outcomes(r)["y_fee"]; hk[lab][1] += 1
    labs = sorted(l for l in hk if l in ("FBA", "MRV", "FIF"))
    out["harmonic_strategy"] = {"label": "exploratory", "by_label": {l: estimate(*hk[l]) for l in sorted(hk)},
                                "fisher_pairs": {f"{a}_vs_{b}": fisher(hk[a][0], hk[a][1], hk[b][0], hk[b][1])
                                                 for i, a in enumerate(labs) for b in labs[i + 1:]}}
    # different-slot pairs: share where the high-fee transaction landed in the earlier slot
    ds: dict = {}
    for arm in ("P", "D", "S"):
        for c, g in groups.items():
            both = [r for r in g if r.get("arm") == arm and r["all_landed"] and r["n_tx"] == 2 and not r["claim_changed_in_run"]]
            diff = [r for r in both if not r["same_slot"]]
            k = sum(1 for r in diff if high_index(r) == r["first_landed_any"])
            ds[f"{arm}/{c}"] = {"n_both_landed": len(both), "n_different_slots": len(diff), "high_fee_earlier_slot": estimate(k, len(diff))}
    out["different_slot_pairs"] = ds
    # untargeted landings per actual producer (descriptive, never pooled into a primary cell)
    prod: dict[str, dict] = {}
    for r in rows:
        if r["claim_changed_in_run"]:
            continue
        for t in r["txs"]:
            if t["landed"] and t["leader"] != r["target_leader"]:
                d = prod.setdefault(t["leader"], {"producer": t["leader"], "client_id": t.get("client_id"), "version": t.get("version"),
                                                  "n_tx": 0, "n_same_slot_pairs_arm_P": 0, "high_fee_first_arm_P": 0, "sent_first_first_arm_P": 0})
                d["n_tx"] += 1
        if r["same_slot"] and r["n_tx"] == 2 and not r["target_hit"] and r.get("arm") == arm_p:
            d = prod.get(r["leader"])
            if d is not None:
                o = outcomes(r)
                d["n_same_slot_pairs_arm_P"] += 1
                d["high_fee_first_arm_P"] += o.get("y_fee", 0); d["sent_first_first_arm_P"] += o["y_send"]
    out["untargeted_landings"] = sorted(prod.values(), key=lambda d: (-d["n_tx"], d["producer"]))
    # transactions with an execution error
    errs = {"n_tx_landed": 0, "n_tx_with_error": 0, "by_arm": defaultdict(int), "by_target": defaultdict(int)}
    for r in rows:
        for t in r["txs"]:
            if t["landed"]:
                errs["n_tx_landed"] += 1
                if t.get("err") or t.get("status_err"):
                    errs["n_tx_with_error"] += 1
                    errs["by_arm"][r.get("arm")] += 1
                    errs["by_target"][r["target_leader"]] += 1
    errs["by_arm"], errs["by_target"] = dict(errs["by_arm"]), dict(errs["by_target"])
    out["execution_errors"] = errs
    out["arm_S_pooled_q_for_fifo_remark"] = s_by_client
    return out


def _flat(est: dict) -> list:
    ci = est.get("ci95") or [None, None]
    return [est.get("k"), est.get("p"), ci[0], ci[1], est.get("p_value"), est.get("p_holm")]


def write_outputs(res: dict, out_dir: str, meta: dict) -> None:
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "verdicts.json"), "w") as f:
        json.dump({**meta, **res}, f, indent=1, sort_keys=True, default=str)
    ident = ["target_role", "identity", "client_id", "version"]
    with open(os.path.join(out_dir, "verdicts.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(ident + ["n_probes_arm_P", "n_primary", "k_fee_first", "p_fee_first", "p_ci95_lo", "p_ci95_hi", "p_value", "p_holm",
                            "k_sent_first", "q_sent_first", "q_ci95_lo", "q_ci95_hi", "q_value", "q_holm", "pi", "verdict"])
        for u in res["units"]:
            w.writerow([u[c] for c in ident] + [u["n_probes_arm_P"], u["n_primary"], *_flat(u["fee"]),
                                                 *_flat(u["send"]), u["pi"], u["verdict"]])
    with open(os.path.join(out_dir, "table_2x2.csv"), "w", newline="") as f:
        w = csv.writer(f)
        keys = ["sent_first_landed_first", "sent_first_landed_second", "sent_second_landed_first", "sent_second_landed_second"]
        w.writerow(ident + keys)
        for u in res["units"]:
            w.writerow([u[c] for c in ident] + [u["table_2x2"][k] for k in keys])
    with open(os.path.join(out_dir, "logit.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(ident + ["n"] + [f"coef_{t}" for t in LOGIT_TERMS] + [f"se_{t}" for t in LOGIT_TERMS] + ["converged", "separation", "error"])
        for u in res["units"]:
            lg = u["logit"]
            w.writerow([u[c] for c in ident] + [lg.get("n")] + [lg.get("coef", {}).get(t) for t in LOGIT_TERMS]
                       + [lg.get("se", {}).get(t) for t in LOGIT_TERMS] + [lg.get("converged"), lg.get("separation"), lg.get("error")])
    with open(os.path.join(out_dir, "secondary.json"), "w") as f:
        json.dump(res["secondary"], f, indent=1, sort_keys=True, default=str)


def analyze(raw_dir: str, out_dir: str, cfg: dict, final: bool = False) -> dict:
    all_rows = probe_rows(raw_dir)
    rows, refused = select_rows(all_rows, final)
    res = analyze_rows(rows, load_block_summaries(raw_dir), cfg)
    meta = {"config": cfg, "final": final, "confirmatory": final, "n_rows_read": len(all_rows), "n_rows_analysed": len(rows),
            "n_main_rows_refused": refused}
    write_outputs(res, out_dir, meta)
    return {"final": final, "n_rows": len(all_rows), "n_rows_analysed": len(rows), "n_main_rows_refused": refused,
            "units": len(res["units"])}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="itb analyze")
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--out", default="results")
    ap.add_argument("--final", action="store_true",
                    help="analyse the confirmatory main-phase data (run once, after the last main run); "
                         "without it main-phase data is refused and only pilot and synthetic data are analysed")
    a = ap.parse_args(argv)
    summary = analyze(a.raw, a.out, dict(DEFAULTS), final=a.final)
    if summary["n_main_rows_refused"]:
        print(f"refusing to include {summary['n_main_rows_refused']} main-phase probes without --final "
              f"(confirmatory data are analysed once, after the last main run); analysed pilot/synthetic data only")
    if not a.final:
        print("NOT FINAL: results are not confirmatory")
    print(json.dumps(summary))
    return 0
