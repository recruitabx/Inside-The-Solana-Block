#!/usr/bin/env python3
"""Amendment 6 helper (operational only, never reads ordering): for every role whose arm-P usable count
(both tx in one block of the target inside the window, clientId unchanged, no payer conflict) reached the
stop target, set its quota in data/plan.json to its current number of main probes, so the runner stops it."""
import json, sys, collections
import os
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))
from itb.pairs import probe_rows
TARGET = 115
rows = [r for r in probe_rows(os.path.join(ROOT, "data/raw")) if r.get("phase") == "main"]
probes = collections.Counter(r["target_role"] for r in rows)
usable = collections.Counter(r["target_role"] for r in rows if r.get("arm") == "P" and r["n_tx"] == 2 and r["same_slot"]
                             and r.get("target_hit") and r.get("in_window") and not r["claim_changed_in_run"] and not r.get("payer_conflict"))
p = os.path.join(ROOT, "data/plan.json")
plan = json.load(open(p))
changed = []
for t in plan["targets"]:
    role = t["role"]
    if usable[role] >= TARGET and t["quota_per_target"] > probes[role]:
        t["quota_per_target"] = probes[role]; changed.append(role)
if changed:
    json.dump(plan, open(p, "w"), indent=1)
print("stop_roles:", {t["role"]: f"usableP {usable[t['role']]} probes {probes[t['role']]}/{t['quota_per_target']}" for t in plan["targets"]}, "stopped now:", changed)
