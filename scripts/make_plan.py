#!/usr/bin/env python3
"""Write data/plan.json: the frozen run configuration derived from data/validators.json and the
parameters of docs/PREREGISTRATION.md (sections 4, 5, 6, 10, 11). tau0_ms is set after the pilot with
--tau0-ms and the quotas with --u-pilot (the usable fraction u of `itb pilot-report`): the only
data-dependent parameters, chosen from operational rates.

Plan targets are ROLES. Each role has a clientId and an ordered candidate list [primary identity,
replacement 1, 2, 3] taken from data/validators.json; the runner picks the first valid candidate at the
start of every run (itb.roles). Quotas are per role and span runs and identities.

Quotas (section 5): quota = ceil(115 / (share_P x u)); Rakurai-1 and Agave-1 (85/5/5/5) are capped
at 330. Without --u-pilot u = 0.48, which gives 343 (shares 70/10/10/10) and 282 (85/5/5/5).
--shares-all-85 is the pre-declared fallback for u < 0.48: every role gets 85/5/5/5 and quota
ceil(115 / (0.85 u)), the two low-window roles still capped at 330.

Budget. The ceiling is the FUNDED fee room, passed in with --fee-room (lamports; the funded balance minus
the rent reserves of the payers and of the funding wallet). Planned fees =
  pilot_spent + operations (500,000) + sum over roles of quota x share-weighted mean pair fee
(pairs P, D, S 15,501 lamports, pair E 10,002). --pilot-spent is what the pilot actually settled
(`--pilot-spent ledger` reads it from the spend ledger with itb.spend.settled_total(path, "pilot:");
before the pilot pass the planned pilot cost as a number). The plan is refused (nothing written, exit 1)
if planned fees exceed the fee room. --scale-to-room instead scales all quotas down proportionally
(floor) so that planned fees fit, and prints the roles projected below 100 usable probes
(quota x share_P x u < 100).
"""
import argparse, json, math, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from itb.spend import max_fee_lamports, settled_total  # noqa: E402

LOW_WINDOW_ROLES = {"Rakurai-1", "Agave-1"}
SHARES_HIGH = {"P": 0.70, "E": 0.10, "D": 0.10, "S": 0.10}
SHARES_85 = {"P": 0.85, "E": 0.05, "D": 0.05, "S": 0.05}
TARGET_USABLE = 115            # usable primary probes aimed at per role (100 plus margin)
MIN_USABLE = 100               # the N rule
DEFAULT_U = 0.48               # the u the preregistered quotas 343 and 282 assume
LOW_WINDOW_CAP = 330
OPERATIONS_LAMPORTS = 500_000  # 10 fundings + 10 drains + 80 anchors at 5,000
N_PAYERS = 6
PRICE_HIGH, PRICE_LOW, CU_LIMIT = 5_500_000, 1_000, 1_000
PILOT_P, PILOT_S = 12, 2
LEDGER_PATH = "data/ledger/spend.jsonl"
PILOT_TAG_PREFIX = "pilot:"    # the runner tags pilot probe reservations "pilot:<probe id>"


def pair_fees() -> dict:
    hi, lo = max_fee_lamports(1, PRICE_HIGH, CU_LIMIT), max_fee_lamports(1, PRICE_LOW, CU_LIMIT)
    return {"contrast": hi + lo, "equal": 2 * lo}      # 15,501 and 10,002


def mean_pair_fee(shares: dict) -> float:
    f = pair_fees()
    return (shares["P"] + shares["D"] + shares["S"]) * f["contrast"] + shares["E"] * f["equal"]


def quota_for(role: str, shares: dict, u: float) -> int:
    q = math.ceil(TARGET_USABLE / (shares["P"] * u))
    return min(LOW_WINDOW_CAP, q) if role in LOW_WINDOW_ROLES else q


def main_fees(targets: list) -> int:
    return round(sum(t["quota_per_target"] * mean_pair_fee(t["shares"]) for t in targets))


def planned_total(targets: list, pilot_spent: int) -> int:
    return pilot_spent + OPERATIONS_LAMPORTS + main_fees(targets)


def scale_quotas(targets: list, fee_room: int, pilot_spent: int) -> float:
    """Scale every quota by one factor f (floor) so that planned fees <= fee_room. Returns f (<= 1)."""
    room_main = fee_room - pilot_spent - OPERATIONS_LAMPORTS
    unscaled = sum(t["quota_per_target"] * mean_pair_fee(t["shares"]) for t in targets)
    f = max(0.0, min(1.0, room_main / unscaled)) if unscaled else 1.0
    for t in targets:
        t["quota_per_target"] = int(math.floor(t["quota_per_target"] * f))
    while f > 0 and planned_total(targets, pilot_spent) > fee_room:      # float guard: the floor makes this a no-op in practice
        biggest = max(targets, key=lambda t: t["quota_per_target"])
        biggest["quota_per_target"] -= 1
    return f


def build_plan(validators: dict, seed: int, tau0_ms, u_pilot, all85: bool, fee_room: int, pilot_spent: int,
               scale_to_room: bool = False) -> tuple[dict, dict]:
    u = DEFAULT_U if u_pilot is None else u_pilot
    targets = []
    for t in validators["targets"]:
        low = t["role"] in LOW_WINDOW_ROLES
        shares = dict(SHARES_85 if (low or all85) else SHARES_HIGH)
        cands = [t["identity"]] + [r["identity"] for r in t.get("replacements", []) if r["identity"] != t["identity"]]
        targets.append({"role": t["role"], "clientId": t["clientId"], "version": t["version"], "identity": t["identity"],
                        "candidates": cands, "shares": shares, "quota_per_target": quota_for(t["role"], shares, u)})
    total_unscaled = planned_total(targets, pilot_spent)
    scale = 1.0
    if scale_to_room and total_unscaled > fee_room:
        scale = scale_quotas(targets, fee_room, pilot_spent)
    total = planned_total(targets, pilot_spent)
    usable = {t["role"]: t["quota_per_target"] * t["shares"]["P"] * u for t in targets}
    report = {"u_used": u, "fee_room": fee_room, "pilot_spent": pilot_spent, "main_run_fees": main_fees(targets),
              "operations": OPERATIONS_LAMPORTS, "planned_fee_total": total, "planned_fee_total_unscaled": total_unscaled,
              "scaled_to_room": scale < 1.0, "scale_factor": scale, "projected_usable": usable,
              "roles_below_100_usable": sorted(r for r, x in usable.items() if x < MIN_USABLE)}
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
    ap.add_argument("--seed", type=int, required=True, help="the frozen seed")
    ap.add_argument("--fee-room", type=int, required=True, help="funded fee room in lamports (the ceiling of planned fees)")
    ap.add_argument("--pilot-spent", required=True,
                    help="lamports settled for the pilot: an integer, or 'ledger' to read it from the spend ledger (tag prefix 'pilot:')")
    ap.add_argument("--ledger", default=LEDGER_PATH, help="spend ledger read by --pilot-spent ledger")
    ap.add_argument("--tau0-ms", type=int, default=None, help="fixed send offset chosen in the pilot")
    ap.add_argument("--u-pilot", type=float, default=None, help=f"pooled usable fraction u from the pilot (default {DEFAULT_U})")
    ap.add_argument("--shares-all-85", action="store_true", help="fallback for u < 0.48: shares 85/5/5/5 for every role")
    ap.add_argument("--scale-to-room", action="store_true",
                    help="if planned fees exceed the fee room, scale all quotas down proportionally (floor) instead of refusing")
    a = ap.parse_args(argv)
    if a.u_pilot is not None and not 0 < a.u_pilot <= 1:
        raise SystemExit("--u-pilot must be in (0, 1]")
    if a.fee_room <= 0:
        raise SystemExit("--fee-room must be positive")
    pilot_spent = settled_total(a.ledger, PILOT_TAG_PREFIX) if a.pilot_spent == "ledger" else int(a.pilot_spent)
    if pilot_spent < 0:
        raise SystemExit("--pilot-spent must not be negative")
    plan, rep = build_plan(json.load(open(a.validators)), a.seed, a.tau0_ms, a.u_pilot, a.shares_all_85, a.fee_room, pilot_spent,
                           a.scale_to_room)
    print("quotas:", {t["role"]: t["quota_per_target"] for t in plan["targets"]})
    print(f"planned fee total = {rep['planned_fee_total']:,} lamports (pilot spent {rep['pilot_spent']:,} + main run "
          f"{rep['main_run_fees']:,} + operations {rep['operations']:,}), fee room {rep['fee_room']:,}")
    if rep["scaled_to_room"]:
        print(f"quotas scaled by {rep['scale_factor']:.4f} (floor) to fit the fee room; unscaled planned total "
              f"{rep['planned_fee_total_unscaled']:,}")
    if a.scale_to_room or rep["roles_below_100_usable"]:
        low = rep["roles_below_100_usable"]
        print(f"projected usable probes at u = {rep['u_used']:.2f} (quota x share_P x u): "
              + ", ".join(f"{r} {x:.0f}" for r, x in rep["projected_usable"].items()))
        print("roles projected below 100 usable: " + (", ".join(low) if low else "none"))
    if rep["planned_fee_total"] > a.fee_room:
        print(f"REFUSED: planned fee total {rep['planned_fee_total']:,} exceeds the fee room {a.fee_room:,} lamports; plan not written "
              f"(use --scale-to-room to scale the quotas down)", file=sys.stderr)
        return 1
    json.dump(plan, open(a.out, "w"), indent=1)
    print(json.dumps({k: plan[k] for k in plan if k not in ("targets", "planned_fees")}), len(plan["targets"]), "roles")
    return 0


if __name__ == "__main__":
    sys.exit(main())
