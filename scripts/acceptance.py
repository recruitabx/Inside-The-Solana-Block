#!/usr/bin/env python3
"""Acceptance criteria of docs/PREREGISTRATION.md section 10 that can be checked before the main run.
Prints PASS or FAIL per criterion and exits 1 if any fails. Sends nothing; the only network call is a
read-only simulateTransaction (criterion 3).

  1  synthetic recovery (the SAME decision code as `itb analyze`: exact Clopper-Pearson, one Holm family, verdict):
     1a  coverage of the 95% Clopper-Pearson interval >= 94% at N = 100 for planted p in {1.0, 0.75, 0.5} and
         q in {1.0, 0.5} (scenarios (p, q) = (1, .5), (.75, .5), (.5, .5), (.5, 1): the unplanted one is 0.5;
         request position and fee contrast are randomized independently, so one of the two is 0.5 whenever the other is planted)
     1b  false "rule holds" in <= 5% of replicates across 8 simulated null units, one Holm family over their 16 p and q tests
     1c  power >= 0.80 to call a fee rule at p = 0.70 (one unit with p = 0.70 among 8, Holm over the 16 tests)
  2  controls: the localnet calibration pairs (data/calibration/localnet_*_final.jsonl), converted to the analysis'
     pair format, through the same verdict function with min_n = 0 (control exemption from the N rule):
     condition A (arrival known) must give "request-position rule holds", condition B (priority known) "fee rule holds"
  3  templates: both probe templates (high and low price) built with the funding wallet PUBLIC key as payer, unsigned,
     simulateTransaction with sigVerify false and replaceRecentBlockhash true on the public mainnet RPC:
     unitsConsumed <= 700 and loadedAccountsDataSize <= 4096
"""
from __future__ import annotations

import argparse
import functools
import glob
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from itb.analyze import DEFAULTS, cell_estimates, decide, estimate, in_cell  # noqa: E402
from itb.simulate import PUBLIC_RPC, funding_pubkey, render as render_simulation, simulate_templates, template_params  # noqa: E402
from itb.stats import clopper_pearson  # noqa: E402

N = 100
COVERAGE_MIN, FALSE_RULE_MAX, POWER_MIN, POWER_P = 0.94, 0.05, 0.80, 0.70
SCENARIOS = [(1.0, 0.5), (0.75, 0.5), (0.5, 0.5), (0.5, 1.0)]       # planted (p, q)
SEED = 20261030
CALIBRATION_GLOB = "data/calibration/localnet_*_final.jsonl"


# ---- criterion 1: synthetic recovery -------------------------------------------------------------

@functools.lru_cache(maxsize=None)
def _est(k: int, n: int) -> dict:
    return estimate(k, n)


def simulate_counts(rng: np.random.Generator, n: int, p: float, q: float) -> tuple[int, int]:
    """(k_fee, k_send) of n usable pairs with a planted rule. The high-fee transaction is sent first with
    probability 1/2, independently of everything else. Planted fee rule (q = 0.5): the high-fee transaction lands first
    with probability p. Planted request-position rule (p = 0.5): the first-sent lands first with probability q."""
    high_first = rng.random(n) < 0.5
    if q != 0.5:
        y_send = rng.random(n) < q
        y_fee = np.where(high_first, y_send, ~y_send)
    else:
        y_fee = rng.random(n) < p
        y_send = np.where(high_first, y_fee, ~y_fee)
    return int(y_fee.sum()), int(y_send.sum())


def _unit(k_fee: int, k_send: int, n: int = N) -> dict:
    return {"fee": dict(_est(k_fee, n)), "send": dict(_est(k_send, n))}


def claims_rule(verdict: str) -> bool:
    return "rule holds" in verdict or verdict.startswith("mixed")


def check_coverage(reps: int, rng: np.random.Generator) -> dict:
    rows = []
    for p, q in SCENARIOS:
        cov_p = cov_q = 0
        for _ in range(reps):
            kf, ks = simulate_counts(rng, N, p, q)
            lo, hi = clopper_pearson(kf, N, 0.95)
            cov_p += lo <= p <= hi
            lo, hi = clopper_pearson(ks, N, 0.95)
            cov_q += lo <= q <= hi
        rows.append({"p": p, "q": q, "coverage_p": cov_p / reps, "coverage_q": cov_q / reps})
    low = min(min(r["coverage_p"], r["coverage_q"]) for r in rows)
    return {"rows": rows, "min_coverage": low, "ok": low >= COVERAGE_MIN}


def check_false_rule(reps: int, rng: np.random.Generator, cfg: dict) -> dict:
    hits = 0
    for _ in range(reps):
        units = [_unit(*simulate_counts(rng, N, 0.5, 0.5)) for _ in range(8)]
        decide(units, cfg, None)
        hits += any(claims_rule(u["verdict"]) for u in units)
    return {"rate": hits / reps, "ok": hits / reps <= FALSE_RULE_MAX}


def check_power(reps: int, rng: np.random.Generator, cfg: dict) -> dict:
    hits = 0
    for _ in range(reps):
        units = [_unit(*simulate_counts(rng, N, POWER_P, 0.5))] + [_unit(*simulate_counts(rng, N, 0.5, 0.5)) for _ in range(7)]
        decide(units, cfg, None)
        hits += units[0]["verdict"].startswith("fee rule holds")
    return {"power": hits / reps, "ok": hits / reps >= POWER_MIN}


def check_synthetic(reps: int, seed: int = SEED) -> dict:
    rng = np.random.default_rng(seed)
    cfg = dict(DEFAULTS)
    cov, fr, pw = check_coverage(reps, rng), check_false_rule(reps, rng, cfg), check_power(reps, rng, cfg)
    return {"replicates": reps, "coverage": cov, "false_rule": fr, "power": pw, "ok": cov["ok"] and fr["ok"] and pw["ok"]}


# ---- criterion 2: controls ------------------------------------------------------------------------

def calibration_rows(records: list[dict], condition: str, client_id: str = "Agave", version: str | None = None) -> list[dict]:
    """Pairs of one calibration condition ("A" or "B") in the analysis' pair format (arm P, one block, target hit,
    in window, claim unchanged). A pair whose two transactions did not both land in one slot is left out, as in the
    analysis (it has no in-block order). Transaction 0 is label 1, transaction 1 is label 2."""
    rows = []
    for rec in records:
        if rec.get("record", "pair") != "pair" or rec.get("condition") != condition:
            continue
        by = {t["label"]: t for t in rec["txs"]}
        a, b = by[1], by[2]
        if any(t.get("slot") is None or t.get("index") is None for t in (a, b)) or a["slot"] != b["slot"]:
            continue
        txs = [{"signature": t["sig"], "cu_price": t["cu_price"], "send_pos": t["send_pos"], "landed": True, "slot": t["slot"],
                "tx_index": t["index"], "leader": t.get("leader"), "err": t.get("err"),
                "label": "high" if t["cu_price"] == max(a["cu_price"], b["cu_price"]) and a["cu_price"] != b["cu_price"] else "low"}
               for t in (a, b)]
        rows.append({"arm": "P", "n_tx": 2, "all_landed": True, "same_slot": True, "target_hit": True, "in_window": True,
                     "claim_changed_in_run": False, "claim_end_unknown": False, "txs": txs,
                     "first_landed": min(range(2), key=lambda i: (txs[i]["slot"], txs[i]["tx_index"])),
                     "first_sent": min(range(2), key=lambda i: txs[i]["send_pos"]),
                     "target_leader": "localnet", "target_role": f"control-{condition}", "claim_client_id": client_id,
                     "claim_version": version})
    return rows


def check_controls(path: str | None = None) -> dict:
    path = path or (sorted(glob.glob(CALIBRATION_GLOB)) or [None])[-1]
    if not path or not os.path.exists(path):
        return {"ok": False, "error": f"no calibration file ({CALIBRATION_GLOB})"}
    records, version = [], None
    with open(path) as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                records.append(r)
                if r.get("record") == "meta":
                    version = (r.get("validator") or {}).get("solana-core")
    cfg = {**DEFAULTS, "min_n": 0}        # the controls are exempt from the N rule
    units, expected = [], {"A": "request-position rule holds", "B": "fee rule holds"}
    for cond in ("A", "B"):
        rows = calibration_rows(records, cond, version=version)
        cell = [r for r in rows if in_cell(r, "P")]
        fee, send = cell_estimates(cell)
        units.append({"condition": cond, "n_pairs": sum(1 for r in records if r.get("record") == "pair" and r.get("condition") == cond),
                      "fee": fee, "send": send})
    decide(units, cfg, None)               # one Holm family over the 4 control tests
    out = []
    for u in units:
        out.append({"condition": u["condition"], "n_pairs": u["n_pairs"], "n_same_slot": u["fee"].get("n", 0), "k_fee_first": u["fee"].get("k"),
                    "k_sent_first": u["send"].get("k"), "verdict": u["verdict"], "expected": expected[u["condition"]],
                    "ok": u["verdict"].startswith(expected[u["condition"]])})
    return {"file": path, "units": out, "ok": all(x["ok"] for x in out)}


# ---- criterion 3: templates -----------------------------------------------------------------------

def check_templates(rpc_url: str, payer: str | None = None) -> dict:
    from itb.rpc import Rpc
    payer = payer or funding_pubkey()
    if not payer:
        return {"ok": False, "error": "no funding wallet public key (data/accounts.json, ~/ops/wallet.pub or --payer)", "templates": {}}
    return simulate_templates(Rpc(rpc_url, rate_per_s=2.0, burst=2.0, timeout=30), payer, template_params())


# ---- report ---------------------------------------------------------------------------------------

def _pf(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--replicates", type=int, default=1000, help="replicates per synthetic scenario (1000 for the real check)")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--calibration", default=None, help="calibration file (default: the newest data/calibration/localnet_*_final.jsonl)")
    ap.add_argument("--payer", default=None, help="payer public key for the template simulation (default: the funding wallet's)")
    ap.add_argument("--rpc", default=os.environ.get("ITB_READ_RPC_URL", PUBLIC_RPC))
    a = ap.parse_args(argv)

    syn = check_synthetic(a.replicates, a.seed)
    c, fr, pw = syn["coverage"], syn["false_rule"], syn["power"]
    mc = " (reduced replicates: indicative only)" if a.replicates < 1000 else ""
    print(f"CRITERION 1 synthetic recovery, {a.replicates} replicates at N = {N}, seed {a.seed}{mc}")
    for r in c["rows"]:
        print(f"    planted p = {r['p']:.2f}, q = {r['q']:.2f}: 95% Clopper-Pearson coverage p {100 * r['coverage_p']:.1f}%, q {100 * r['coverage_q']:.1f}%")
    print(f"  {_pf(c['ok'])} 1a coverage >= {100 * COVERAGE_MIN:.0f}% in every scenario: minimum {100 * c['min_coverage']:.1f}%")
    print(f"  {_pf(fr['ok'])} 1b false \"rule holds\" across 8 null units (one Holm family of 16 tests): {100 * fr['rate']:.1f}% of replicates, need <= {100 * FALSE_RULE_MAX:.0f}%")
    print(f"  {_pf(pw['ok'])} 1c power vs p = {POWER_P:.2f} (one unit among 8, Holm over 16 tests): {100 * pw['power']:.1f}%, need >= {100 * POWER_MIN:.0f}%")
    print(f"CRITERION 1: {_pf(syn['ok'])}")

    ctl = check_controls(a.calibration)
    print("CRITERION 2 controls through the analysis' verdict function with min_n = 0 (exempt from the N rule)")
    if "error" in ctl:
        print(f"  FAIL {ctl['error']}")
    else:
        print(f"    file {ctl['file']}")
        for u in ctl["units"]:
            print(f"  {_pf(u['ok'])} condition {u['condition']}: {u['n_same_slot']} same-slot pairs of {u['n_pairs']}, fee-first {u['k_fee_first']}, "
                  f"sent-first {u['k_sent_first']}: \"{u['verdict']}\" (expected \"{u['expected']}...\")")
    print(f"CRITERION 2: {_pf(ctl['ok'])}")

    tpl = check_templates(a.rpc, a.payer)
    print("CRITERION 3 templates")
    print(render_simulation(tpl) if tpl["templates"] else f"  FAIL {tpl.get('error')}")
    print(f"CRITERION 3: {_pf(tpl['ok'])}")

    ok = syn["ok"] and ctl["ok"] and tpl["ok"]
    print(f"ACCEPTANCE: {_pf(ok)}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
