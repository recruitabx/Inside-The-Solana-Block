"""Join the runner's send log with the collector's landing records into one row per probe.

Everything here is a pure function of files under data/raw/, so `itb analyze` can be rerun by
anyone from the committed data without network access."""
from __future__ import annotations

import glob
import json
import math
import os

from .config import BASE_FEE_PER_SIGNATURE


def scheduler_priority(cu_price: int, cu_limit: int, cost_units: int, n_sig: int = 1) -> float:
    """Agave/Firedancer-style priority key: reward per cost unit.
    reward = priority fee (ceil(price x limit / 1e6)) + the non-burned half of the signature fee.
    Agave computes reward * 1_000_000 / (cost + 1) (integer); the ratio is what matters here."""
    prio_fee = math.ceil(cu_price * cu_limit / 1_000_000)
    reward = prio_fee + n_sig * BASE_FEE_PER_SIGNATURE // 2
    return reward * 1_000_000 / (cost_units + 1)


def load_jsonl(pattern: str) -> list[dict]:
    out = []
    for p in sorted(glob.glob(pattern)):
        with open(p) as f:
            out += [json.loads(x) for x in f if x.strip()]
    return out


def run_claims(raw_dir: str) -> dict[str, dict]:
    """Gossip claims of every target at the start and at the end of each run, from the send logs:
    {run_id: {"start": {target: (clientId, version)}, "end": {target: (clientId, version)} | None}}."""
    out: dict[str, dict] = {}
    for r in load_jsonl(os.path.join(raw_dir, "*.sent.jsonl")):
        if r.get("record") == "run_start":
            c, v = r.get("targets_client_now") or {}, r.get("targets_version_now") or {}
            out.setdefault(r["run_id"], {"start": None, "end": None})["start"] = {k: (c.get(k), v.get(k)) for k in c}
        elif r.get("record") == "run_end" and r.get("targets_client_end") is not None:
            c, v = r["targets_client_end"], r.get("targets_version_end") or {}
            out.setdefault(r["run_id"], {"start": None, "end": None})["end"] = {k: (c.get(k), v.get(k)) for k in c}
    return out


def sent_probes(raw_dir: str) -> list[dict]:
    """Live probe records of the send logs. A probe is marked `synthetic` if the record says so or if
    its file name starts with "synthetic" (synthetic data are never confirmatory)."""
    sent = []
    for path in sorted(glob.glob(os.path.join(raw_dir, "*.sent.jsonl"))):
        synthetic_file = os.path.basename(path).startswith("synthetic")
        with open(path) as f:
            for x in f:
                if not x.strip():
                    continue
                r = json.loads(x)
                if r.get("record") == "probe" and r.get("mode") == "live":
                    r["synthetic"] = bool(r.get("synthetic")) or synthetic_file
                    sent.append(r)
    return sent


def probe_rows(raw_dir: str = "data/raw") -> list[dict]:
    """One row per live probe. The unit of analysis is (target_role, identity, clientId); the version is a covariate.
    claim_changed_in_run: the target's clientId differs between the start and the end snapshot (the probe leaves the
    primary cell). version_changed_in_run: only the version string differs (kept; reported in the descriptive split).
    claim_end_unknown: the run has no end snapshot (kept and counted)."""
    sent = sent_probes(raw_dir)
    landed = {r["signature"]: r for r in load_jsonl(os.path.join(raw_dir, "*.landed.jsonl"))}
    claims = run_claims(raw_dir)
    rows = []
    for p in sent:
        txs = []
        for t in p["txs"]:
            L = landed.get(t["signature"], {})
            txs.append({**t, "landed": L.get("record") == "landed", "slot": L.get("slot"), "tx_index": L.get("tx_index"),
                        "leader": L.get("leader"), "client_id": L.get("leader_client_id"), "version": L.get("leader_version"),
                        "fee": L.get("fee"), "cost_units": L.get("cost_units"), "err": L.get("err"),
                        "status_err": L.get("status_err"), "block_tx_count": L.get("block_tx_count")})
        all_landed = all(t["landed"] for t in txs)
        same_slot = all_landed and len({t["slot"] for t in txs}) == 1
        tgt, rc = p["target_leader"], claims.get(p["run_id"], {})
        start = (rc.get("start") or {}).get(tgt, (None, None))
        claim = (p["target_client_id"], p.get("target_version")) if "target_client_id" in p else start
        end = (rc.get("end") or {}).get(tgt)
        row = {"probe_id": p["probe_id"], "run_id": p["run_id"], "phase": p.get("phase"), "synthetic": bool(p.get("synthetic")),
               "condition": p.get("condition"), "arm": p.get("arm") or p.get("condition"),
               "target_leader": tgt, "target_role": p.get("target_role"),
               "claim_client_id": claim[0], "claim_version": claim[1],
               "claim_version_end": end[1] if end is not None else None,
               "claim_changed_in_run": end is not None and end[0] != claim[0],
               "version_changed_in_run": end is not None and end[0] == claim[0] and end[1] != claim[1],
               "claim_end_unknown": end is None,
               "window_first_slot": p["window_first_slot"],
               "window_last_slot": p.get("window_last_slot", p["window_first_slot"] + 3),
               "planned_send_slot": p.get("planned_send_slot"), "tau0_ms": p.get("tau0_ms"),
               "observed_slot_after_send": p.get("observed_slot_after_send"), "s_low_first": p.get("s_low_first"),
               "t_send_start": p.get("t_send_start"), "send_results": p.get("send_results"),
               "n_tx": len(txs), "all_landed": all_landed, "same_slot": same_slot, "txs": txs}
        if all_landed and not same_slot and len(txs) == 2:
            # order by (slot, index): the transaction that landed in the earlier slot is first
            row["first_landed_any"] = min(range(2), key=lambda i: (txs[i]["slot"], txs[i]["tx_index"]))
        if same_slot:
            row["slot"] = txs[0]["slot"]
            row["leader"] = txs[0]["leader"]
            row["client_id"], row["version"] = txs[0]["client_id"], txs[0]["version"]
            row["target_hit"] = row["leader"] == tgt
            row["in_window"] = row["window_first_slot"] <= row["slot"] <= row["window_last_slot"]
            row["slot_in_window"] = row["slot"] - p["window_first_slot"] if row["target_hit"] else None
            order = sorted(range(len(txs)), key=lambda i: txs[i]["tx_index"])
            row["landing_order"] = order  # tx positions (in the probe's tx list) from earliest to latest
            row["first_sent"] = min(range(len(txs)), key=lambda i: txs[i]["send_pos"])
            row["first_landed"] = order[0]
            row["index_gap"] = abs(txs[0]["tx_index"] - txs[1]["tx_index"]) if len(txs) == 2 else None
        rows.append(row)
    return rows


def load_block_summaries(raw_dir: str = "data/raw") -> dict[int, dict]:
    """Block summaries written by the collector (data/raw/<run>.blocks.jsonl), by slot."""
    return {r["slot"]: r for r in load_jsonl(os.path.join(raw_dir, "*.blocks.jsonl")) if r.get("record") == "block"}
