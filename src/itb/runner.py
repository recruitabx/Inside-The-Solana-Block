"""Experiment runner.

DRY-RUN IS THE DEFAULT. In dry-run the runner does everything a live run does (reads the real
leader schedule, picks target windows, waits for the planned send moment, builds and signs the
probe transactions with throw-away keys) except handing them to the RPC. It records where the
current slot actually was at the planned send moment, which measures our timing accuracy.

LIVE sending requires ALL of: the --live flag, the environment variable ITB_LIVE=1, a mounted
wallet, and a spend ledger whose cap (ITB_SPEND_CAP_LAMPORTS, <= 0.05 SOL) still has room for the
worst-case fee of every transaction in the probe. The reservation is written to disk before the
HTTP request leaves. Runs are short (default 15 min) and resumable: all state is in files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid

from solders.keypair import Keypair

from . import design
from .config import HARD_SPEND_CEILING_LAMPORTS, MIN_SLOT
from .leaders import SlotClock, client_snapshot, upcoming_windows
from .roles import assign_roles
from .rpc import Rpc
from .send import SignedTx, send_signed
from .spend import SpendCapExceeded, SpendLedger
from .txbuild import build_probe_tx, fresh_address

LEDGER_PATH = "data/ledger/spend.jsonl"


def git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5).stdout.strip() or None
    except Exception:
        return None


def sha256_file(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class JsonlWriter:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.f = open(path, "a")

    def write(self, rec: dict) -> None:
        self.f.write(json.dumps(rec, sort_keys=True) + "\n")
        self.f.flush()
        os.fsync(self.f.fileno())


def live_gate(args) -> bool:
    if not args.live:
        return False
    if os.environ.get("ITB_LIVE") != "1":
        raise SystemExit("refusing to send: --live given but ITB_LIVE is not 1 (dry-run is the default)")
    return True


def cap_from_env() -> int:
    cap = int(os.environ.get("ITB_SPEND_CAP_LAMPORTS", HARD_SPEND_CEILING_LAMPORTS))
    if cap > HARD_SPEND_CEILING_LAMPORTS:
        raise SystemExit(f"ITB_SPEND_CAP_LAMPORTS={cap} is above the hard ceiling {HARD_SPEND_CEILING_LAMPORTS}")
    return cap


def count_existing_arms(phase: str, raw_glob: str = "data/raw/*-live-*.sent.jsonl") -> dict[str, dict[str, int]]:
    """Probes already sent per ROLE and arm in this phase: quotas span runs and identities (a replacement
    inherits the role's remaining quota). Only live send logs of the same phase count; any file whose name
    starts with "synthetic" and any record marked `synthetic` is ignored; records without a role are ignored."""
    import glob
    n: dict[str, dict[str, int]] = {}
    for path in sorted(glob.glob(raw_glob)):
        if os.path.basename(path).startswith("synthetic"):
            continue
        with open(path) as f:
            for line in f:
                if not line.strip():
                    continue
                r = json.loads(line)
                if (r.get("record") != "probe" or r.get("synthetic") or r.get("mode") != "live"
                        or r.get("phase") != phase or not r.get("send_results") or not r.get("target_role")):
                    continue
                a = n.setdefault(r["target_role"], {})
                a[r.get("arm") or "?"] = a.get(r.get("arm") or "?", 0) + 1
    return n


def count_existing(phase: str) -> dict[str, int]:
    return {k: sum(v.values()) for k, v in count_existing_arms(phase).items()}


SYNC_EVERY_S = 2.0   # the slot clock is re-read at least this often while waiting


def wait_until(clock: SlotClock, t_fn, *, sync_every: float = SYNC_EVERY_S, no_sync_last_s: float = 0.5) -> None:
    """Sleep until t_fn() (a unix time that moves whenever the clock is refitted). The clock is
    synced at least every `sync_every` seconds, also inside long waits, but not in the last
    `no_sync_last_s` seconds, where an RPC round trip would make us late. SlotClock.sync() itself
    never calls the RPC more than about once per second."""
    while True:
        rem = t_fn() - time.time()
        if rem <= 0:
            return
        if clock.since_sync() >= sync_every and rem > no_sync_last_s:
            clock.sync()
            continue
        time.sleep(min(rem, 0.25))


class PayerPool:
    """Least-recently-used payers; a payer is reused only after its previous transaction has a
    status on chain or `expiry_s` has passed (so a payer never has two transactions in flight)."""

    def __init__(self, payers: list[Keypair], read: Rpc, expiry_s: float = 35.0, dry: bool = False,
                 dry_land_s: float = 1.5):
        # In dry-run nothing lands, so a payer is treated as landed `dry_land_s` after use; this
        # keeps the dry-run's probe rate equal to a live run's (typical confirmation ~1 s).
        self.payers, self.read, self.expiry = payers, read, expiry_s
        self.dry, self.dry_land_s = dry, dry_land_s
        self.last: dict[int, tuple[float, str | None]] = {i: (0.0, None) for i in range(len(payers))}

    def take(self, k: int) -> list[int] | None:
        now = time.time()
        cand = sorted(self.last, key=lambda i: self.last[i][0])
        pending = [(i, self.last[i][1]) for i in cand if self.last[i][1] and now - self.last[i][0] < self.expiry]
        landed = set()
        if pending and self.dry:
            landed = {i for i, _ in pending if now - self.last[i][0] >= self.dry_land_s}
        elif pending:
            try:
                st = self.read.call("getSignatureStatuses", [[s for _, s in pending]])["value"]
                landed = {i for (i, _), v in zip(pending, st) if v is not None}
            except Exception:
                pass
        free = [i for i in cand if self.last[i][1] is None or now - self.last[i][0] >= self.expiry or i in landed]
        return free[:k] if len(free) >= k else None

    def mark(self, i: int, sig: str) -> None:
        self.last[i] = (time.time(), sig)


def save_snapshot(snap: dict, end: bool = False) -> str:
    os.makedirs("data/snapshots", exist_ok=True)
    path = f"data/snapshots/clients_{snap['slot']}.json"
    if end and os.path.exists(path):   # never overwrite the start snapshot whose hash is in the run config
        path = f"data/snapshots/clients_{snap['slot']}_end.json"
    with open(path, "w") as f:
        json.dump(snap, f, sort_keys=True)
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="itb run", description="experiment runner (dry-run unless --live and ITB_LIVE=1)")
    ap.add_argument("--live", action="store_true", help="really send transactions (also needs ITB_LIVE=1)")
    ap.add_argument("--plan", default="data/plan.json", help="frozen plan: roles, seed, design parameters")
    ap.add_argument("--minutes", type=float, default=15.0, help="run length (max 20)")
    ap.add_argument("--max-probes", type=int, default=10_000)
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--phase", default="main", choices=["pilot", "main"],
                    help="pilot: per role pilot_per_target arm-P probes cycling tau0 over the grid plus pilot_s_per_target arm-S probes")
    ap.add_argument("--no-anchor", action="store_true", help="skip the per-run config anchor (live)")
    a = ap.parse_args(argv)
    if a.minutes > 20:
        raise SystemExit("--minutes is limited to 20 (short resumable batches)")
    live = live_gate(a)
    plan = json.load(open(a.plan))
    if a.phase == "main" and plan.get("tau0_ms") is None:
        raise SystemExit("plan has no tau0_ms: choose it from the pilot (itb pilot-report) and rerun scripts/make_plan.py --tau0-ms")
    run_id = a.run_id or (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + ("live" if live else "dry") + "-"
                          + ("pilot-" if a.phase == "pilot" else "") + uuid.uuid4().hex[:6])
    out = JsonlWriter(f"data/{'raw' if live else 'dryrun'}/{run_id}.sent.jsonl")

    # Reads go to a separate endpoint (public RPC by default) so they never eat the send rate limit.
    read = Rpc(os.environ.get("ITB_READ_RPC_URL", "https://api.mainnet-beta.solana.com"), rate_per_s=3.0, burst=3.0)
    send = Rpc(rate_per_s=float(plan.get("send_rate_per_s", 1.0)), burst=float(plan.get("send_burst", 2)), retries=0)

    ledger = None
    master = None
    n_payers = int(plan["n_payers"])
    if live:
        from .wallet import derive_payers, load_wallet
        ledger = SpendLedger(LEDGER_PATH, cap_from_env())
        master = load_wallet()
        payers = derive_payers(master, n_payers)
    else:
        payers = [Keypair() for _ in range(n_payers)]
    pool = PayerPool(payers, read, dry=not live)

    snap = client_snapshot(read)
    if snap["slot"] < MIN_SLOT:
        raise SystemExit("current slot below MIN_SLOT: refusing (pre-Alpenglow)")
    snap_path = save_snapshot(snap)
    # Roles, not identities, are the plan's targets: each role gets its first valid candidate (same clientId,
    # not delinquent) from this run's start snapshot; quotas and counts belong to the role.
    roles = {t["role"]: t for t in plan["targets"]}
    assignment = assign_roles(plan["targets"], snap)
    chosen = {role: asg["identity"] for role, asg in assignment.items() if asg["identity"]}
    leader_role = {ident: role for role, ident in chosen.items()}     # identity -> role, for the identities of this run
    for role, asg in assignment.items():
        if asg["identity"] is None:
            print(f"role {role} skipped in this run: {asg['skipped']} ({len(asg['rejected'])} candidates rejected)", file=sys.stderr)
    if a.phase == "pilot":
        quota = {r: int(t.get("pilot_per_target", plan["pilot_per_target"])) + int(plan.get("pilot_s_per_target", 2))
                 for r, t in roles.items()}
    else:
        quota = {r: int(t.get("quota_per_target", plan.get("quota_per_target", 0))) for r, t in roles.items()}
    done_arm = count_existing_arms(a.phase) if live else {}
    done = {k: sum(v.values()) for k, v in done_arm.items()}
    config = {"plan_sha256": sha256_file(a.plan), "snapshot_sha256": sha256_file(snap_path), "phase": a.phase,
              "run_id": run_id, "git_commit": git_commit()}
    config_sha = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    claims_start = {ident: (snap["nodes"][ident].get("clientId"), snap["nodes"][ident].get("version")) for ident in leader_role}
    start_rec = {"record": "run_start", "run_id": run_id, "mode": "live" if live else "dry", "phase": a.phase,
                 **config, "config_sha256": config_sha, "snapshot": snap_path, "snapshot_slot": snap["slot"],
                 "send_host": send.host, "read_host": read.host, "t": time.time(),
                 "ledger": ledger.summary() if ledger else None, "already_sent": done, "quota": quota,
                 "role_assignment": assignment,
                 "targets_client_now": {k: v[0] for k, v in claims_start.items()},
                 "targets_version_now": {k: v[1] for k, v in claims_start.items()}}
    if live and not a.no_anchor:
        from .funds import memo_tx
        bh0 = read.call("getLatestBlockhash", [{"commitment": "confirmed"}])["value"]["blockhash"]
        t = memo_tx(master, f"itb-run:{run_id}:{config_sha}", bh0)
        start_rec["anchor"] = {"signature": t.signature, **send_signed(send, ledger, [t], tag=f"anchor:{run_id}", max_retries=None)}
    out.write(start_rec)

    probes = 0
    error = None
    try:
        clock = SlotClock(read)
        clock.sync(); time.sleep(1.0); clock.sync()
        t_end = time.time() + a.minutes * 60
        last_request = 0.0
        bh, bh_t = None, 0.0
        windows: list = []
        win_refresh = 0.0
        tau_grid = plan.get("tau0_grid_ms", [plan.get("tau0_ms", -170)])
        min_gap = float(plan.get("min_request_interval_s", 2.0))
        gap_max_s = float(plan.get("gap_ms", 200)) / 1000.0   # longest possible spacing of one probe (arm S)
        while leader_role and time.time() < t_end and probes < a.max_probes:
            if clock.since_sync() >= SYNC_EVERY_S:
                clock.sync()
            if time.time() - win_refresh > 60:
                cur = clock.sync()
                windows = [w for w in upcoming_windows(read, cur + 2, 1500) if w.leader in leader_role]
                win_refresh = time.time()
            windows = [w for w in windows if done.get(leader_role[w.leader], 0) < quota[leader_role[w.leader]]]
            nxt = next((w for w in windows if clock.time_of(w.first_slot) - time.time() > 1.5), None)
            if nxt is None:
                if not windows and time.time() - win_refresh > 5:
                    win_refresh = 0.0
                time.sleep(0.3); continue
            role = leader_role[nxt.leader]
            target = roles[role]
            # Arm and send offset that do not come from the random draw: in the pilot, the arm follows the
            # probe count of the role and tau0 cycles over the grid; in the main phase tau0 is the plan constant.
            pilot_arm = None
            if a.phase == "pilot":
                arms_done = done_arm.setdefault(role, {})
                pilot_arm = design.pilot_arm(done.get(role, 0), plan)
                if pilot_arm == "S":
                    n_s = sum(v.get("S", 0) for v in done_arm.values())
                    tau0 = tau_grid[(n_s + 1) % len(tau_grid)]
                else:
                    tau0 = tau_grid[arms_done.get("P", 0) % len(tau_grid)]
            else:
                tau0 = plan["tau0_ms"]
            t_window = clock.time_of(nxt.first_slot)
            if t_window + tau0 / 1000.0 > t_end:
                break
            # Skip checks. They must not depend on the arm, which is drawn only afterwards: the
            # request interval is checked for the earliest possible first request (arm S, gap earlier).
            if t_window + tau0 / 1000.0 - gap_max_s < last_request + min_gap:
                out.write({"record": "window_skipped", "run_id": run_id, "target_leader": nxt.leader, "target_role": role,
                           "window_first_slot": nxt.first_slot, "reason": "min request interval"})
                windows = [w for w in windows if w.first_slot > nxt.last_slot]
                continue
            sel = pool.take(2)
            if sel is None:
                out.write({"record": "window_skipped", "run_id": run_id, "target_leader": nxt.leader, "target_role": role,
                           "window_first_slot": nxt.first_slot, "reason": "no free payer"})
                windows = [w for w in windows if w.first_slot > nxt.last_slot]
                continue
            # All skip checks passed: draw from the generator keyed by the window itself, so the assignment
            # never depends on which earlier windows were skipped or on the run.
            rng_key = design.probe_rng_key(plan, nxt.first_slot, nxt.leader)
            spec = design.make_probe(design.probe_rng(plan, nxt.first_slot, nxt.leader), plan, target, arm=pilot_arm)

            def t_send_fn() -> float:
                return clock.time_of(nxt.first_slot) + tau0 / 1000.0 - spec["gap_s"]
            wait_until(clock, lambda: t_send_fn() - 2.0)      # long wait, clock synced at least every 2 s
            if time.time() - bh_t > 10 or bh is None:
                bh = read.call("getLatestBlockhash", [{"commitment": "confirmed"}])["value"]["blockhash"]; bh_t = time.time()
            probe_id = f"{run_id}:{probes}"
            built = []
            for i, tx in enumerate(spec["txs"]):
                w = fresh_address(str(plan["seed"]), probe_id, tx["w_index"])
                built.append(build_probe_tx(payers[sel[i]], bh, cu_limit=tx["cu_limit"], cu_price=tx["cu_price"],
                                            shared=w, loaded_limit=tx["loaded_limit"]))
            wait_until(clock, t_send_fn)
            t_send, t_window = t_send_fn(), clock.time_of(nxt.first_slot)
            rec = {"record": "probe", "run_id": run_id, "phase": a.phase, "probe_id": probe_id, "mode": "live" if live else "dry",
                   "arm": spec["arm"], "condition": spec["arm"], "target_leader": nxt.leader, "target_role": role,
                   "target_client_id": claims_start[nxt.leader][0], "target_version": claims_start[nxt.leader][1],
                   "window_first_slot": nxt.first_slot, "window_last_slot": nxt.last_slot, "tau0_ms": tau0,
                   "rng_key": rng_key, "s_low_first": spec["s_low_first"],
                   "planned_send_slot": nxt.first_slot + (tau0 / 1000.0 - spec["gap_s"]) / clock.slot_s,
                   "planned_send_time": t_send, "estimated_window_start_time": t_window, "slot_s_estimate": clock.slot_s,
                   "hi_idx": spec["hi_idx"], "hi_pos": spec["hi_pos"], "gap_s": spec["gap_s"], "send_order": spec["order"],
                   "txs": [{"signature": b.signature, "payer": b.payer, "cu_limit": b.cu_limit, "cu_price": b.cu_price,
                            "loaded_limit": b.loaded_limit, "shared_account": b.shared_account, "max_fee": b.max_fee,
                            "label": t["label"], "send_pos": spec["order"].index(i)}
                           for i, (t, b) in enumerate(zip(spec["txs"], built))],
                   "blockhash": bh}
            if live:
                try:
                    # pilot reservations are tagged "pilot:<probe id>" so that itb.spend.settled_total(path, "pilot:")
                    # gives the settled pilot spend that scripts/make_plan.py subtracts from the fee room
                    r = send_signed(send, ledger, [SignedTx(b.signature, b.wire_b64, b.max_fee) for b in built],
                                    tag=(f"pilot:{probe_id}" if a.phase == "pilot" else probe_id), order=spec["order"],
                                    gap_s=spec["gap_s"], max_retries=int(plan.get("max_retries", 0)))
                except SpendCapExceeded as e:
                    rec["record"] = "probe_aborted_cap"; rec["error"] = str(e); out.write(rec)
                    print(f"SPEND CAP REACHED, stopping: {e}", file=sys.stderr)
                    break
                rec.update(r)
                rec["t_send_start"], rec["t_send_end"] = r["send_times"][0][0], r["send_times"][-1][1]
            else:
                rec["t_send_start"] = rec["t_send_end"] = time.time()
            last_request = rec["t_send_end"]
            for i, b in zip(sel, built):
                pool.mark(i, b.signature)
            rec["slot_estimate_at_send"] = clock.now()
            if plan.get("observe_slot_after_send", True):
                # independent check of the slot clock: a fresh processed-slot read right after sending
                t0 = time.time()
                try:
                    rec["observed_slot_after_send"] = read.call("getSlot", [{"commitment": "processed"}])
                    rec["observed_slot_rtt_s"] = time.time() - t0
                except Exception as e:  # observation only; never blocks the experiment
                    rec["observed_slot_error"] = type(e).__name__
            out.write(rec)
            probes += 1
            done[role] = done.get(role, 0) + 1
            done_arm.setdefault(role, {})[spec["arm"]] = done_arm.setdefault(role, {}).get(spec["arm"], 0) + 1
            windows = [w for w in windows if w.first_slot > nxt.last_slot]
    except BaseException as e:   # also KeyboardInterrupt and SystemExit: the run_end below is written in every case
        error = f"{type(e).__name__}: {str(e)[:300]}"
        raise
    finally:
        end_rec = {"record": "run_end", "run_id": run_id, "t": time.time(), "probes": probes, "sent_per_role": done,
                   "ledger": ledger.summary() if ledger else None}
        if error:
            end_rec["error"] = error
        # Second gossip snapshot: a target whose clientId claim differs from the start leaves the primary cell
        # (a changed version is kept and reported as a covariate).
        try:
            snap_end = client_snapshot(read)
            end_path = save_snapshot(snap_end, end=True)
            claims_end = {k: (snap_end["nodes"].get(k, {}).get("clientId"), snap_end["nodes"].get(k, {}).get("version")) for k in claims_start}
            end_rec.update({"snapshot_end": end_path, "snapshot_end_slot": snap_end["slot"],
                            "targets_client_end": {k: v[0] for k, v in claims_end.items()},
                            "targets_version_end": {k: v[1] for k, v in claims_end.items()},
                            "claim_changed": {k: claims_end[k] != claims_start[k] for k in claims_start},
                            "client_changed": {k: claims_end[k][0] != claims_start[k][0] for k in claims_start}})
        except Exception as e:  # the run's data stays; analysis then treats the end claim as unknown and says so
            end_rec["snapshot_end_error"] = type(e).__name__
        out.write(end_rec)
        if ledger:
            ledger.close()
    print(json.dumps({"run_id": run_id, "probes": probes, "mode": "live" if live else "dry"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
