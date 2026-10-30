#!/usr/bin/env python3
"""Write data/plan.json: the frozen run configuration derived from data/validators.json and the
parameters of docs/PREREGISTRATION.md (sections 5, 6, 10). tau0_ms is set after the pilot with
--tau0-ms (the only data-dependent parameter, chosen from operational rates)."""
import argparse, json

LOW_WINDOW_ROLES = {"Rakurai-1", "Agave-1"}

ap = argparse.ArgumentParser()
ap.add_argument("--validators", default="data/validators.json")
ap.add_argument("--out", default="data/plan.json")
ap.add_argument("--seed", type=int, required=True)
ap.add_argument("--tau0-ms", type=int, default=None, help="fixed send offset chosen in the pilot")
a = ap.parse_args()
v = json.load(open(a.validators))
targets = []
for t in v["targets"]:
    low = t["role"] in LOW_WINDOW_ROLES
    targets.append({"role": t["role"], "identity": t["identity"], "clientId": t["clientId"], "version": t["version"],
                    "shares": {"P": 0.85, "E": 0.05, "D": 0.05, "S": 0.05} if low else {"P": 0.70, "E": 0.10, "D": 0.10, "S": 0.10},
                    "quota_per_target": 10_000 if low else 300})
plan = {"seed": a.seed, "targets": targets, "n_payers": 10,
        "price_high": 5_500_000, "price_low": 1_000, "cu_limit": 1_000, "loaded_limit": 4_096, "gap_ms": 200,
        "tau0_grid_ms": [-270, -170, -70], "tau0_ms": a.tau0_ms, "pilot_per_target": 12,
        "min_request_interval_s": 2.0, "send_rate_per_s": 1.0, "send_burst": 2, "max_retries": 0,
        "observe_slot_after_send": True}
json.dump(plan, open(a.out, "w"), indent=1)
print(json.dumps({k: plan[k] for k in plan if k != "targets"}), len(targets), "targets")
