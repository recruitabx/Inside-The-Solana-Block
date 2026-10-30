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
import random
import subprocess
import sys
import time
import uuid

from solders.keypair import Keypair

from . import design
from .config import HARD_SPEND_CEILING_LAMPORTS, MIN_SLOT
from .leaders import SlotClock, client_snapshot, upcoming_windows
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


def count_existing(phase: str) -> dict[str, int]:
    """Probes already sent per target in this phase (all earlier live runs): quotas span runs."""
    import glob
    n: dict[str, int] = {}
    for path in glob.glob("data/raw/*-live-*.sent.jsonl"):
        for line in open(path):
            r = json.loads(line)
            if r.get("record") == "probe" and r.get("phase") == phase and r.get("send_results"):
                n[r["target_leader"]] = n.get(r["target_leader"], 0) + 1
    return n


class PayerPool:
    """Least-recently-used payers; a payer is reused only after its previous transaction has a
    status on chain or `expiry_s` has passed (so a payer never has two transactions in flight)."""

    def __init__(self, payers: list[Keypair], read: Rpc, expiry_s: float = 35.0):
        self.payers, self.read, self.expiry = payers, read, expiry_s
        self.last: dict[int, tuple[float, str | None]] = {i: (0.0, None) for i in range(len(payers))}

    def take(self, k: int) -> list[int] | None:
        now = time.time()
        cand = sorted(self.last, key=lambda i: self.last[i][0])
        pending = [(i, self.last[i][1]) for i in cand if self.last[i][1] and now - self.last[i][0] < self.expiry]
        landed = set()
        if pending:
            try:
                st = self.read.call("getSignatureStatuses", [[s for _, s in pending]])["value"]
                landed = {i for (i, _), v in zip(pending, st) if v is not None}
            except Exception:
                pass
        free = [i for i in cand if self.last[i][1] is None or now - self.last[i][0] >= self.expiry or i in landed]
        return free[:k] if len(free) >= k else None

    def mark(self, i: int, sig: str) -> None:
        self.last[i] = (time.time(), sig)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="itb run", description="experiment runner (dry-run unless --live and ITB_LIVE=1)")
    ap.add_argument("--live", action="store_true", help="really send transactions (also needs ITB_LIVE=1)")
    ap.add_argument("--plan", default="data/plan.json", help="frozen plan: targets, seed, design parameters")
    ap.add_argument("--minutes", type=float, default=15.0, help="run length (max 20)")
    ap.add_argument("--max-probes", type=int, default=10_000)
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--phase", default="main", choices=["pilot", "main"], help="pilot: arm P only, tau0 grid")
    ap.add_argument("--no-anchor", action="store_true", help="skip the per-run config anchor (live)")
    a = ap.parse_args(argv)
    if a.minutes > 20:
        raise SystemExit("--minutes is limited to 20 (short resumable batches)")
    live = live_gate(a)
    plan = json.load(open(a.plan))
    run_id = a.run_id or time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + ("live" if live else "dry") + "-" + uuid.uuid4().hex[:6]
    out = JsonlWriter(f"data/{'raw' if live else 'dryrun'}/{run_id}.sent.jsonl")

    # Reads go to a separate endpoint (public RPC by default) so they never eat the send rate limit.
    read = Rpc(os.environ.get("ITB_READ_RPC_URL", "https://api.mainnet-beta.solana.com"), rate_per_s=3.0, burst=3.0)
    send = Rpc(rate_per_s=float(plan.get("send_rate_per_s", 1.0)), burst=float(plan.get("send_burst", 2)), retries=0)

    ledger = None
    master = None
    if live:
        from .wallet import derive_payers, load_wallet
        ledger = SpendLedger(LEDGER_PATH, cap_from_env())
        master = load_wallet()
        payers = derive_payers(master, int(plan["n_payers"]))
    else:
        payers = [Keypair() for _ in range(int(plan["n_payers"]))]
    pool = PayerPool(payers, read)

    snap = client_snapshot(read)
    if snap["slot"] < MIN_SLOT:
        raise SystemExit("current slot below MIN_SLOT: refusing (pre-Alpenglow)")
    os.makedirs("data/snapshots", exist_ok=True)
    snap_path = f"data/snapshots/clients_{snap['slot']}.json"
    with open(snap_path, "w") as f:
        json.dump(snap, f, sort_keys=True)
    targets = {t["identity"]: t for t in plan["targets"]}
    quota_key = "pilot_per_target" if a.phase == "pilot" else "quota_per_target"
    done = count_existing(a.phase) if live else {}
    quota = {k: int(t.get(quota_key, plan[quota_key])) for k, t in targets.items()}
    config = {"plan_sha256": sha256_file(a.plan), "snapshot_sha256": sha256_file(snap_path), "phase": a.phase,
              "run_id": run_id, "git_commit": git_commit()}
    config_sha = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    start_rec = {"record": "run_start", "run_id": run_id, "mode": "live" if live else "dry", "phase": a.phase,
                 **config, "config_sha256": config_sha, "snapshot": snap_path, "snapshot_slot": snap["slot"],
                 "send_host": send.host, "read_host": read.host, "t": time.time(),
                 "ledger": ledger.summary() if ledger else None, "already_sent": done, "quota": quota,
                 "targets_client_now": {k: snap["nodes"].get(k, {}).get("clientId") for k in targets},
                 "targets_version_now": {k: snap["nodes"].get(k, {}).get("version") for k in targets}}
    if live and not a.no_anchor:
        from .funds import memo_tx
        bh0 = read.call("getLatestBlockhash", [{"commitment": "confirmed"}])["value"]["blockhash"]
        t = memo_tx(master, f"itb-run:{run_id}:{config_sha}", bh0)
        start_rec["anchor"] = {"signature": t.signature, **send_signed(send, ledger, [t], tag=f"anchor:{run_id}")}
    out.write(start_rec)

    clock = SlotClock(read)
    clock.sync(); time.sleep(1.0); clock.sync()
    t_end = time.time() + a.minutes * 60
    rng = random.Random(f"{plan['seed']}:{run_id}")
    probes, last_request = 0, 0.0
    bh, bh_t = None, 0.0
    windows: list = []
    win_refresh = 0.0
    tau_grid = plan.get("tau0_grid_ms", [plan.get("tau0_ms", -170)])
    tau_cycle: dict[str, int] = {}
    min_gap = float(plan.get("min_request_interval_s", 2.0))
    while time.time() < t_end and probes < a.max_probes:
        if time.time() - win_refresh > 60:
            cur = clock.sync()
            windows = [w for w in upcoming_windows(read, cur + 2, 1500) if w.leader in targets]
            win_refresh = time.time()
        windows = [w for w in windows if done.get(w.leader, 0) < quota[w.leader]]
        now_slot = clock.now()
        nxt = next((w for w in windows if clock.time_of(w.first_slot) - time.time() > 1.5), None)
        if nxt is None:
            if not windows and time.time() - win_refresh > 5:
                win_refresh = 0.0
            time.sleep(0.3); continue
        target = targets[nxt.leader]
        if a.phase == "pilot":
            spec = design.make_probe(rng, plan, target, arm="P")
            i = tau_cycle.get(nxt.leader, 0); tau_cycle[nxt.leader] = i + 1
            tau0 = tau_grid[i % len(tau_grid)]
        else:
            spec = design.make_probe(rng, plan, target)
            tau0 = plan["tau0_ms"]
        t_window = clock.time_of(nxt.first_slot)
        t_send = t_window + tau0 / 1000.0 - spec["gap_s"]
        if t_send > t_end:
            break
        if t_send < last_request + min_gap:
            out.write({"record": "window_skipped", "run_id": run_id, "target_leader": nxt.leader,
                       "window_first_slot": nxt.first_slot, "reason": "min request interval"})
            windows = [w for w in windows if w.first_slot > nxt.last_slot]
            continue
        sel = pool.take(2)
        if sel is None:
            out.write({"record": "window_skipped", "run_id": run_id, "target_leader": nxt.leader,
                       "window_first_slot": nxt.first_slot, "reason": "no free payer"})
            windows = [w for w in windows if w.first_slot > nxt.last_slot]
            continue
        if time.time() - bh_t > 10 or bh is None:
            bh = read.call("getLatestBlockhash", [{"commitment": "confirmed"}])["value"]["blockhash"]; bh_t = time.time()
        if t_send - time.time() > 2.5:
            time.sleep(max(0.0, t_send - time.time() - 2.0)); clock.sync()
            t_window = clock.time_of(nxt.first_slot); t_send = t_window + tau0 / 1000.0 - spec["gap_s"]
        probe_id = f"{run_id}:{probes}"
        built = []
        for i, tx in enumerate(spec["txs"]):
            w = fresh_address(str(plan["seed"]), probe_id, tx["w_index"])
            built.append(build_probe_tx(payers[sel[i]], bh, cu_limit=tx["cu_limit"], cu_price=tx["cu_price"],
                                        shared=w, loaded_limit=tx["loaded_limit"]))
        rec = {"record": "probe", "run_id": run_id, "phase": a.phase, "probe_id": probe_id, "mode": "live" if live else "dry",
               "arm": spec["arm"], "condition": spec["arm"], "target_leader": nxt.leader, "target_role": target.get("role"),
               "window_first_slot": nxt.first_slot, "window_last_slot": nxt.last_slot, "tau0_ms": tau0,
               "planned_send_slot": nxt.first_slot + (tau0 / 1000.0 - spec["gap_s"]) / clock.slot_s,
               "planned_send_time": t_send, "estimated_window_start_time": t_window, "slot_s_estimate": clock.slot_s,
               "hi_idx": spec["hi_idx"], "hi_pos": spec["hi_pos"], "gap_s": spec["gap_s"], "send_order": spec["order"],
               "txs": [{"signature": b.signature, "payer": b.payer, "cu_limit": b.cu_limit, "cu_price": b.cu_price,
                        "loaded_limit": b.loaded_limit, "shared_account": b.shared_account, "max_fee": b.max_fee,
                        "label": t["label"], "send_pos": spec["order"].index(i)}
                       for i, (t, b) in enumerate(zip(spec["txs"], built))],
               "blockhash": bh}
        delay = t_send - time.time()
        if delay > 0:
            time.sleep(delay)
        if live:
            try:
                r = send_signed(send, ledger, [SignedTx(b.signature, b.wire_b64, b.max_fee) for b in built],
                                tag=probe_id, order=spec["order"], gap_s=spec["gap_s"],
                                max_retries=int(plan.get("max_retries", 0)))
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
        done[nxt.leader] = done.get(nxt.leader, 0) + 1
        windows = [w for w in windows if w.first_slot > nxt.last_slot]
    out.write({"record": "run_end", "run_id": run_id, "t": time.time(), "probes": probes, "sent_per_target": done,
               "ledger": ledger.summary() if ledger else None})
    if ledger:
        ledger.close()
    print(json.dumps({"run_id": run_id, "probes": probes, "mode": "live" if live else "dry"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
