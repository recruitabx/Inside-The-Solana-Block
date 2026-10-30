#!/usr/bin/env python3
"""Write data/plan.json: the frozen run configuration derived from data/validators.json and the
parameters of docs/PREREGISTRATION.md (sections 5, 6, 10, 11). tau0_ms is set after the pilot with
--tau0-ms and the quotas with --u-pilot (the usable fraction u of `itb pilot-report`): the only
data-dependent parameters, chosen from operational rates.

Quotas (section 5): quota = ceil(115 / (share_P x u)); Rakurai-1 and Agave-1 (85/5/5/5) are capped
at 330. Without --u-pilot u = 0.48, which gives 343 (shares 70/10/10/10) and 282 (85/5/5/5).
--shares-all-85 is the pre-declared fallback for u < 0.48: every target gets 85/5/5/5 and quota
ceil(115 / (0.85 u)), the two low-window targets still capped at 330.

The plan is refused (nothing written, exit status 1) if the planned fee total exceeds 46,000,000
lamports: sum over targets of quota x share-weighted mean pair fee (pairs P, D, S 15,501 lamports,
pair E 10,002), plus the pilot (twice, one possible re-pilot) and operations (10 fundings, 10 drains,
80 anchors at 5,000 lamports).
"""
import argparse, json, math, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from itb.spend import max_fee_lamports  # noqa: E402

LOW_WINDOW_ROLES = {"Rakurai-1", "Agave-1"}
SHARES_HIGH = {"P": 0.70, "E": 0.10, "D": 0.10, "S": 0.10}
SHARES_85 = {"P": 0.85, "E": 0.05, "D": 0.05, "S": 0.05}
TARGET_USABLE = 115            # usable primary probes aimed at per unit (100 plus margin)
DEFAULT_U = 0.48               # the u the preregistered quotas 343 and 282 assume
LOW_WINDOW_CAP = 330
FEE_CEILING = 46_000_000       # refuse a plan whose planned fees exceed this
OPERATIONS_LAMPORTS = 500_000  # 10 fundings + 10 drains + 80 anchors at 5,000
PAYER_RENT_LAMPORTS = 890_880  # rent deposit per payer account (recoverable)
N_PAYERS = 6
PRICE_HIGH, PRICE_LOW, CU_LIMIT = 5_500_000, 1_000, 1_000
PILOT_P, PILOT_S = 12, 2
PILOT_REPILOTS = 2             # the pilot and one possible re-pilot


def pair_fees() -> dict:
    hi, lo = max_fee_lamports(1, PRICE_HIGH, CU_LIMIT), max_fee_lamports(1, PRICE_LOW, CU_LIMIT)
    return {"contrast": hi + lo, "equal": 2 * lo}      # 15,501 and 10,002


def mean_pair_fee(shares: dict) -> float:
    f = pair_fees()
    return (shares["P"] + shares["D"] + shares["S"]) * f["contrast"] + shares["E"] * f["equal"]


def quota_for(role: str, shares: dict, u: float) -> int:
    q = math.ceil(TARGET_USABLE / (shares["P"] * u))
    return min(LOW_WINDOW_CAP, q) if role in LOW_WINDOW_ROLES else q


def build_plan(validators: dict, seed: int, tau0_ms, u_pilot, all85: bool) -> tuple[dict, dict]:
    u = DEFAULT_U if u_pilot is None else u_pilot
    targets, main_fees = [], 0.0
    for t in validators["targets"]:
        low = t["role"] in LOW_WINDOW_ROLES
        shares = dict(SHARES_85 if (low or all85) else SHARES_HIGH)
        quota = quota_for(t["role"], shares, u)
        main_fees += quota * mean_pair_fee(shares)
        targets.append({"role": t["role"], "identity": t["identity"], "clientId": t["clientId"], "version": t["version"],
                        "shares": shares, "quota_per_target": quota})
    pilot = PILOT_REPILOTS * len(targets) * (PILOT_P + PILOT_S) * pair_fees()["contrast"]
    total = round(main_fees) + pilot + OPERATIONS_LAMPORTS
    report = {"u_used": u, "main_run_fees": round(main_fees), "pilot_fees_with_repilot": pilot, "operations": OPERATIONS_LAMPORTS,
              "planned_fee_total": total, "peak_funding_need": total + N_PAYERS * PAYER_RENT_LAMPORTS,
              "fee_ceiling": FEE_CEILING}
    plan = {"seed": seed, "targets": targets, "n_payers": N_PAYERS,
            "price_high": PRICE_HIGH, "price_low": PRICE_LOW, "cu_limit": CU_LIMIT, "loaded_limit": 4_096, "gap_ms": 200,
            "tau0_grid_ms": [-270, -170, -70], "tau0_ms": tau0_ms, "pilot_per_target": PILOT_P, "pilot_s_per_target": PILOT_S,
            "min_request_interval_s": 2.0, "send_rate_per_s": 1.0, "send_burst": 2, "max_retries": 0,
            "observe_slot_after_send": True, "u_pilot": u_pilot, "shares_all_85": all85, "planned_fees": report}
    return plan, report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--validators", default="data/validators.json")
    ap.add_argument("--out", default="data/plan.json")
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--tau0-ms", type=int, default=None, help="fixed send offset chosen in the pilot")
    ap.add_argument("--u-pilot", type=float, default=None, help=f"pooled usable fraction u from the pilot (default {DEFAULT_U})")
    ap.add_argument("--shares-all-85", action="store_true", help="fallback for u < 0.48: shares 85/5/5/5 for every target")
    a = ap.parse_args(argv)
    if a.u_pilot is not None and not 0 < a.u_pilot <= 1:
        raise SystemExit("--u-pilot must be in (0, 1]")
    plan, rep = build_plan(json.load(open(a.validators)), a.seed, a.tau0_ms, a.u_pilot, a.shares_all_85)
    print("quotas:", {t["role"]: t["quota_per_target"] for t in plan["targets"]})
    print(f"planned fee total = {rep['planned_fee_total']:,} lamports (main run {rep['main_run_fees']:,} + pilot incl. re-pilot "
          f"{rep['pilot_fees_with_repilot']:,} + operations {rep['operations']:,}), ceiling {rep['fee_ceiling']:,}")
    print(f"peak funding need = fee total + {N_PAYERS} x {PAYER_RENT_LAMPORTS:,} rent = {rep['peak_funding_need']:,} lamports")
    if rep["planned_fee_total"] > FEE_CEILING:
        print(f"REFUSED: planned fee total {rep['planned_fee_total']:,} exceeds {FEE_CEILING:,} lamports; plan not written", file=sys.stderr)
        return 1
    json.dump(plan, open(a.out, "w"), indent=1)
    print(json.dumps({k: plan[k] for k in plan if k not in ("targets", "planned_fees")}), len(plan["targets"]), "targets")
    return 0


if __name__ == "__main__":
    sys.exit(main())
