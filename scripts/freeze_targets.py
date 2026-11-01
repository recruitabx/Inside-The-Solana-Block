#!/usr/bin/env python3
"""Freeze the target validators (docs/PREREGISTRATION.md section 4) into data/validators.json.

Eligibility of an identity, all three required:
  1. at least --min-windows (default 400) leader windows in the ranking epoch's schedule (default epoch 1074);
  2. the same clientId in EVERY gossip snapshot of data/selection/snapshots/, where there must be at least
     4 snapshots spanning at least 18 hours (taken_at_unix). The version string may change (it is a covariate,
     not part of the unit of analysis); the version at freeze (newest snapshot) is reported;
  3. not operated by our RPC provider (identity starting HEL1US, a channel confound).
Selection: no clientId is hard-coded. Every clientId that has an eligible identity gets one target (role
<clientId>-1), the eligible identity with the most windows (ties: identity string); targets are ranked by
windows. Replacements: the next 3 eligible identities of the same clientId by windows (the version of the
original only breaks ties); they are the ordered candidate list of the role. The output also lists the
ineligible top identities with the reason.
Exit status 1 (nothing written) if the selection has fewer than 6 targets, fewer than 3 clientIds or fewer
than 3 distinct version strings (at freeze); the preregistered fallback is to rerun with --min-windows 300.
The schedule is cached in data/selection/ next to the snapshots so the selection can be re-derived offline.
"""
import argparse, glob, hashlib, json, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

EXCLUDE_PREFIXES = ("HEL1US",)  # validator operated by the RPC provider used for sending
SLOTS_PER_EPOCH = 432_000
MIN_SNAPSHOTS, MIN_SPAN_HOURS = 4, 18.0
REPLACEMENTS = 3
MIN_TARGETS, MIN_CLIENT_IDS, MIN_VERSIONS = 6, 3, 3


def windows(idx):
    idx = sorted(idx)
    return 1 + sum(1 for a, b in zip(idx, idx[1:]) if b != a + 1) if idx else 0


def load_snapshots(directory):
    snaps = []
    for p in sorted(glob.glob(os.path.join(directory, "*.json"))):
        s = json.load(open(p))
        s["_file"] = os.path.basename(p)
        snaps.append(s)
    return sorted(snaps, key=lambda s: s["taken_at_unix"])


def snapshot_check(snaps, min_snaps=MIN_SNAPSHOTS, min_span_h=MIN_SPAN_HOURS):
    span_h = (snaps[-1]["taken_at_unix"] - snaps[0]["taken_at_unix"]) / 3600 if snaps else 0.0
    ok = len(snaps) >= min_snaps and span_h >= min_span_h
    return ok, span_h


def evaluate(sched, snaps, min_windows=400, min_snaps=MIN_SNAPSHOTS, min_span_h=MIN_SPAN_HOURS):
    """One row per scheduled identity: windows, claim in the newest snapshot, eligible, reasons."""
    snaps_ok, span_h = snapshot_check(snaps, min_snaps, min_span_h)
    last = snaps[-1] if snaps else {"nodes": {}, "total_stake": 1}
    rows = []
    for ident, idx in sched.items():
        n = last["nodes"].get(ident, {})
        why = []
        if ident.startswith(EXCLUDE_PREFIXES):
            why.append("operated by our RPC provider (HEL1US prefix)")
        w = windows(idx)
        if w < min_windows:
            why.append(f"{w} windows < {min_windows}")
        if not snaps_ok:
            why.append(f"snapshots insufficient: {len(snaps)} spanning {span_h:.1f} h (need >= {min_snaps} spanning >= {min_span_h:g} h)")
        else:
            claims = [s["nodes"][ident].get("clientId") if ident in s["nodes"] else None for s in snaps]
            absent = sum(1 for s in snaps if ident not in s["nodes"])
            if absent:
                why.append(f"absent from {absent} of {len(snaps)} snapshots")
            elif len(set(claims)) > 1:
                why.append("clientId changed across snapshots: " + " | ".join(sorted({str(c) for c in claims})))
        rows.append({"identity": ident, "clientId": n.get("clientId"), "version": n.get("version"), "windows_epoch": w,
                     "stake_share": n.get("stake", 0) / last["total_stake"], "eligible": not why, "reason": "; ".join(why) or None})
    return rows


def select_targets(rows, min_windows=400):
    by_client = {}
    for r in rows:
        if r["eligible"]:
            by_client.setdefault(r["clientId"], []).append(r)
    targets = []
    for c, cand in by_client.items():
        cand = sorted(cand, key=lambda r: (-r["windows_epoch"], r["identity"]))
        top = cand[0]
        repl = sorted(cand[1:], key=lambda r: (-r["windows_epoch"], r["version"] != top["version"], r["identity"]))[:REPLACEMENTS]
        targets.append({"role": f"{c}-1", **{k: top[k] for k in ("identity", "clientId", "version", "windows_epoch", "stake_share")},
                        "replacements": [{k: r[k] for k in ("identity", "clientId", "version", "windows_epoch", "stake_share")} for r in repl]})
    targets.sort(key=lambda t: (-t["windows_epoch"], t["identity"]))
    ineligible = []
    for c in sorted({str(r["clientId"]) for r in rows}):
        inel = sorted([r for r in rows if str(r["clientId"]) == c and not r["eligible"]], key=lambda r: (-r["windows_epoch"], r["identity"]))
        keep = inel[:3] + [r for r in inel[3:5] if r["windows_epoch"] >= min_windows]     # the top ineligible per clientId
        ineligible += [{k: r[k] for k in ("identity", "clientId", "version", "windows_epoch", "stake_share", "reason")} for r in keep]
    return targets, ineligible


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--rpc", default=os.environ.get("ITB_READ_RPC_URL", "https://api.mainnet-beta.solana.com"))
    ap.add_argument("--epoch", type=int, default=1074, help="ranking epoch (the one that covers most of the live window)")
    ap.add_argument("--out", default="data/validators.json")
    ap.add_argument("--selection-dir", default="data/selection")
    ap.add_argument("--min-windows", type=int, default=400)
    ap.add_argument("--snapshot-now", action="store_true", help="take one more gossip snapshot into the snapshots directory first")
    ap.add_argument("--refresh-schedule", action="store_true", help="fetch the schedule again even if cached")
    ap.add_argument("--provisional", action="store_true",
                    help="pilot-only selection: snapshot stability over whatever snapshots exist (no 18 h span); output marked provisional")
    a = ap.parse_args(argv)
    snap_dir = os.path.join(a.selection_dir, "snapshots")
    os.makedirs(snap_dir, exist_ok=True)
    rpc = None
    if a.snapshot_now or a.refresh_schedule or not os.path.exists(os.path.join(a.selection_dir, f"leader_schedule_epoch{a.epoch}.json")):
        from itb.rpc import Rpc
        rpc = Rpc(a.rpc, rate_per_s=1.0, burst=1.0, timeout=120)
    if a.snapshot_now:
        from itb.leaders import client_snapshot
        snap = client_snapshot(rpc)
        with open(os.path.join(snap_dir, f"clients_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime(snap['taken_at_unix']))}.json"), "w") as f:
            json.dump(snap, f, sort_keys=True)
    sched_path = os.path.join(a.selection_dir, f"leader_schedule_epoch{a.epoch}.json")
    if a.refresh_schedule or not os.path.exists(sched_path):
        with open(sched_path, "w") as f:
            json.dump(rpc.call("getLeaderSchedule", [a.epoch * SLOTS_PER_EPOCH, {}]), f, sort_keys=True)
    sched = json.load(open(sched_path))
    snaps = load_snapshots(snap_dir)
    min_snaps, min_span = (1, 0.0) if a.provisional else (MIN_SNAPSHOTS, MIN_SPAN_HOURS)
    rows = evaluate(sched, snaps, a.min_windows, min_snaps, min_span)
    targets, ineligible = select_targets(rows, a.min_windows)
    snaps_ok, span_h = snapshot_check(snaps, min_snaps, min_span)
    clients, versions = {t["clientId"] for t in targets}, {t["version"] for t in targets}
    print(f"epoch {a.epoch}: {len(sched)} scheduled identities; {len(snaps)} snapshots spanning {span_h:.1f} h "
          f"({'enough' if snaps_ok else 'NOT enough: need >= 4 spanning >= 18 h'}); {sum(r['eligible'] for r in rows)} eligible identities")
    for t in targets:
        print(f"{t['role']:22s} {t['identity'][:8]} {str(t['version']):12s} windows={t['windows_epoch']} replacements={len(t['replacements'])}")
    for r in ineligible[:12]:
        print(f"  ineligible {str(r['clientId']):20s} {r['identity'][:8]} windows={r['windows_epoch']}: {r['reason']}")
    print("targets:", len(targets), "distinct clientIds:", len(clients), "distinct versions at freeze:", len(versions))
    if len(targets) < MIN_TARGETS or len(clients) < MIN_CLIENT_IDS or len(versions) < MIN_VERSIONS:
        print(f"FAILED: need >= {MIN_TARGETS} targets, >= {MIN_CLIENT_IDS} clientIds and >= {MIN_VERSIONS} version strings at freeze; "
              f"{a.out} not written (preregistered fallback: rerun with --min-windows 300)", file=sys.stderr)
        return 1
    out = {"rule": "per clientId with an eligible identity, the eligible identity with the most windows in the ranking epoch's schedule; "
                   f"eligible: >= {a.min_windows} windows, the same clientId in every one of >= 4 snapshots spanning >= 18 h "
                   "(version is a covariate, reported at freeze), not operated by the RPC provider (HEL1US)",
           "provisional": bool(a.provisional),
           "epoch": a.epoch, "min_windows": a.min_windows,
           "snapshots": [{"file": s["_file"], "slot": s["slot"], "taken_at_unix": s["taken_at_unix"]} for s in snaps],
           "snapshot_span_hours": span_h, "snapshot_slot": snaps[-1]["slot"],
           "schedule_sha256": hashlib.sha256(json.dumps(sched, sort_keys=True).encode()).hexdigest(),
           "targets": targets, "ineligible_top": ineligible}
    with open(a.out, "w") as f:
        json.dump(out, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
