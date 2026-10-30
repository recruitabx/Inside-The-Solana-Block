#!/usr/bin/env python3
"""Freeze the target validators (docs/PREREGISTRATION.md section 4) into data/validators.json.

Rule: for every clientId with mainnet stake, the identity with the most leader windows in the
epoch-1073 schedule, excluding identities operated by our RPC provider (HEL1US...). Replacement
candidates: the next identities by windows with the same clientId (same version first).
Inputs are fetched live (leader schedule of epoch 1073 and a gossip snapshot) and saved next to
the output so the selection can be re-derived without network access.
"""
import argparse, json, os, sys, hashlib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from itb.rpc import Rpc  # noqa: E402
from itb.leaders import client_snapshot  # noqa: E402

CLIENTS = ["AgaveBam", "JitoLabs", "HarmonicAgave", "HarmonicFiredancer", "Firedancer", "FireBAM", "Rakurai", "Agave"]
EXCLUDE_PREFIXES = ("HEL1US",)  # validator operated by the RPC provider used for sending


def windows(idx):
    idx = sorted(idx)
    return 1 + sum(1 for a, b in zip(idx, idx[1:]) if b != a + 1) if idx else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rpc", default=os.environ.get("ITB_READ_RPC_URL", "https://api.mainnet-beta.solana.com"))
    ap.add_argument("--epoch", type=int, default=1073)
    ap.add_argument("--out", default="data/validators.json")
    a = ap.parse_args()
    rpc = Rpc(a.rpc, rate_per_s=1.0, burst=1.0, timeout=120)
    snap = client_snapshot(rpc)
    sched = rpc.call("getLeaderSchedule", [a.epoch * 432000, {}])
    os.makedirs("data/selection", exist_ok=True)
    with open(f"data/selection/leader_schedule_epoch{a.epoch}.json", "w") as f:
        json.dump(sched, f, sort_keys=True)
    with open(f"data/selection/clients_{snap['slot']}.json", "w") as f:
        json.dump(snap, f, sort_keys=True)
    rows = []
    for ident, idx in sched.items():
        n = snap["nodes"].get(ident, {})
        rows.append({"identity": ident, "clientId": n.get("clientId"), "version": n.get("version"),
                     "windows_epoch": windows(idx), "stake_share": n.get("stake", 0) / snap["total_stake"]})
    targets = []
    for c in CLIENTS:
        cand = sorted([r for r in rows if r["clientId"] == c and not r["identity"].startswith(EXCLUDE_PREFIXES)],
                      key=lambda r: (-r["windows_epoch"], r["identity"]))
        if not cand:
            continue
        t = cand[0]
        repl = sorted(cand[1:], key=lambda r: (r["version"] != t["version"], -r["windows_epoch"], r["identity"]))[:3]
        targets.append({"role": f"{c}-1", **t, "replacements": repl})
    out = {"rule": "per clientId the identity with the most windows in the epoch schedule, excluding RPC-provider-operated identities",
           "epoch": a.epoch, "snapshot_slot": snap["slot"],
           "schedule_sha256": hashlib.sha256(json.dumps(sched, sort_keys=True).encode()).hexdigest(),
           "targets": targets}
    with open(a.out, "w") as f:
        json.dump(out, f, indent=1)
    for t in targets:
        print(f"{t['role']:22s} {t['identity'][:8]} {t['version']:12s} windows={t['windows_epoch']}")
    print("distinct clientIds:", len({t['clientId'] for t in targets}), "distinct versions:", len({t['version'] for t in targets}))


if __name__ == "__main__":
    main()
