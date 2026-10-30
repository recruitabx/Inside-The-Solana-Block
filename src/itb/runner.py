"""Experiment runner.

DRY-RUN IS THE DEFAULT. In dry-run the runner does everything a live run does (reads the real
leader schedule, picks target windows, waits for the planned send moment, builds and signs the
probe transactions with throw-away keys) except calling sendTransaction. It records where the
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
from .rpc import Rpc, TransportError
from .spend import SpendCapExceeded, SpendLedger
from .txbuild import build_probe_tx

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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="itb run", description="experiment runner (dry-run unless --live and ITB_LIVE=1)")
    ap.add_argument("--live", action="store_true", help="really send transactions (also needs ITB_LIVE=1)")
    ap.add_argument("--plan", default="data/plan.json", help="frozen plan: targets, seed, design parameters")
    ap.add_argument("--minutes", type=float, default=15.0, help="run length (max 20)")
    ap.add_argument("--max-probes", type=int, default=10_000)
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--phase", default="main", help="label stored with every record (e.g. pilot, main)")
    a = ap.parse_args(argv)
    if a.minutes > 20:
        raise SystemExit("--minutes is limited to 20 (short resumable batches)")
    live = live_gate(a)
    plan = json.load(open(a.plan))
    run_id = a.run_id or time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + ("live" if live else "dry") + "-" + uuid.uuid4().hex[:6]
    out = JsonlWriter(f"data/raw/{run_id}.sent.jsonl")

    read = Rpc(rate_per_s=6.0, burst=6.0)
    send = Rpc(rate_per_s=float(plan.get("send_rate_per_s", 1.0)), burst=float(plan.get("send_burst", 4)), retries=0)

    ledger = None
    payers: list[Keypair]
    if live:
        from .wallet import derive_payers, load_wallet
        ledger = SpendLedger(LEDGER_PATH, cap_from_env())
        master = load_wallet()
        payers = derive_payers(master, int(plan["n_payers"]))
    else:
        payers = [Keypair() for _ in range(int(plan["n_payers"]))]

    snap = client_snapshot(read)
    if snap["slot"] < MIN_SLOT:
        raise SystemExit("current slot below MIN_SLOT: refusing (pre-Alpenglow)")
    os.makedirs("data/snapshots", exist_ok=True)
    snap_path = f"data/snapshots/clients_{snap['slot']}.json"
    json.dump(snap, open(snap_path, "w"), sort_keys=True)
    targets = {t["identity"]: t for t in plan["targets"]}
    out.write({"record": "run_start", "run_id": run_id, "mode": "live" if live else "dry", "phase": a.phase,
               "git_commit": git_commit(), "plan_sha256": sha256_file(a.plan), "snapshot": snap_path,
               "snapshot_slot": snap["slot"], "send_host": send.host, "t": time.time(),
               "ledger": ledger.summary() if ledger else None,
               "targets_client_now": {k: snap["nodes"].get(k, {}).get("clientId") for k in targets},
               "targets_version_now": {k: snap["nodes"].get(k, {}).get("version") for k in targets}})

    clock = SlotClock(read)
    clock.sync(); time.sleep(1.0); clock.sync()
    t_end = time.time() + a.minutes * 60
    rng = random.Random(f"{plan['seed']}:{run_id}")
    probes = 0
    bh, bh_t = None, 0.0
    windows = []
    win_refresh = 0.0
    payer_cursor = rng.randrange(len(payers))
    while time.time() < t_end and probes < a.max_probes:
        if time.time() - win_refresh > 60:
            cur = clock.sync()
            windows = [w for w in upcoming_windows(read, cur + 2, 1500) if w.leader in targets]
            win_refresh = time.time()
        now_slot = clock.now()
        nxt = next((w for w in windows if w.first_slot + plan["min_offset_slots"] > now_slot + 1.0), None)
        if nxt is None:
            time.sleep(0.5); continue
        spec = design.make_probe(rng, plan, targets[nxt.leader])
        send_slot = nxt.first_slot + spec["send_offset_slots"]
        t_send = clock.time_of(send_slot)
        if t_send > t_end:
            break
        if time.time() - bh_t > 10 or bh is None:
            bh = read.call("getLatestBlockhash", [{"commitment": "confirmed"}])["value"]["blockhash"]; bh_t = time.time()
        # resync shortly before sending
        if t_send - time.time() > 2.5:
            time.sleep(max(0.0, t_send - time.time() - 2.0)); clock.sync()
            t_send = clock.time_of(send_slot)
        probe_id = f"{run_id}:{probes}"
        txs = []
        for i, tx in enumerate(spec["txs"]):
            p = payers[(payer_cursor + tx.get("payer_offset", i)) % len(payers)]
            memo = f"itb:{probes}:{i}" if plan.get("memo", True) else ""
            txs.append((tx, build_probe_tx(p, bh, cu_limit=tx["cu_limit"], cu_price=tx["cu_price"], memo=memo)))
        payer_cursor = (payer_cursor + len(spec["txs"]) + 1) % len(payers)
        order = list(range(len(txs)))
        rng.shuffle(order)  # send position is randomized independently of treatment
        rec = {"record": "probe", "run_id": run_id, "phase": a.phase, "probe_id": probe_id, "mode": "live" if live else "dry",
               "target_leader": nxt.leader, "target_role": targets[nxt.leader].get("role"),
               "window_first_slot": nxt.first_slot, "window_last_slot": nxt.last_slot,
               "planned_send_slot": send_slot, "condition": spec.get("condition"),
               "txs": [{"signature": b.signature, "payer": b.payer, "cu_limit": b.cu_limit, "cu_price": b.cu_price,
                        "memo": b.memo, "max_fee": b.max_fee, "label": t.get("label"), "send_pos": order.index(i)}
                       for i, (t, b) in enumerate(txs)],
               "blockhash": bh}
        delay = t_send - time.time()
        if delay > 0:
            time.sleep(delay)
        if live:
            try:
                ledger.reserve([(b.signature, b.max_fee) for _, b in txs], tag=probe_id)
            except SpendCapExceeded as e:
                rec["record"] = "probe_aborted_cap"; rec["error"] = str(e); out.write(rec)
                print(f"SPEND CAP REACHED, stopping: {e}", file=sys.stderr)
                break
            calls = [("sendTransaction", [txs[i][1].wire_b64, {"encoding": "base64", "skipPreflight": True,
                                                                 "maxRetries": plan.get("max_retries", 0)}]) for i in order]
            t0 = time.time()
            try:
                resp = send.batch(calls, retry=False)
                rec["send_results"] = [("ok" if "result" in r else r.get("error")) for r in resp]
            except TransportError as e:
                rec["send_results"] = [f"transport: {e}"] * len(calls)
            rec["t_send_start"], rec["t_send_end"] = t0, time.time()
        else:
            rec["t_send_start"] = rec["t_send_end"] = time.time()
        rec["slot_estimate_at_send"] = clock.now()
        out.write(rec)
        probes += 1
        windows = [w for w in windows if w.first_slot > nxt.last_slot]
    out.write({"record": "run_end", "run_id": run_id, "t": time.time(), "probes": probes,
               "ledger": ledger.summary() if ledger else None})
    if ledger:
        ledger.close()
    print(json.dumps({"run_id": run_id, "probes": probes, "mode": "live" if live else "dry"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
