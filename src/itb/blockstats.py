"""Supplementary (secondary) evidence: how ALL transactions in a leader's block are ordered.

For every non-vote transaction in a block we compute the quantities a fee-priority scheduler
would sort on, from getBlock alone:
  priority_fee  = meta.fee - 5000 * signatures            (lamports)
  cost_units    = meta.costUnits                           (cost-model units, all tx versions)
  reward_per_cost_units_consumed = priority_fee / cost_units   (the first, simple key)
and the scheduler key, which the schedulers compute from the REQUESTED limits at admission:
  reward     = priority_fee + 2,500 x signatures           (priority fee + the non-burned half of the base fee)
  requested  = the SetComputeUnitLimit instruction (ComputeBudget program, data[0] == 2, little-endian
               u32), or a v1 message's transactionConfig.computeUnitLimit; else the runtime default
               of 200,000 per non-ComputeBudget instruction, capped at 1,400,000
  cost_sched = costUnits - computeUnitsConsumed + requested
  sched_key  = reward / cost_sched
and then the rank correlation between block position and each key. A strongly negative Spearman
rho means "higher key earlier". This is not the primary evidence of the study (other people's
transactions arrive at unknown times); it describes competition inside the block.

Two approximations, both stated in the results: (1) the runtime default limit ignores that builtin
programs may get a smaller default on newer runtimes; (2) cost_sched swaps the consumed CU inside
meta.costUnits for the requested limit and keeps every other term (signatures, write locks,
instruction data, loaded-accounts data), which is how the cost model builds the admission cost,
but meta.costUnits does not expose its parts.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from scipy import stats

from .blocks import b58decode, is_vote_tx
from .config import BASE_FEE_PER_SIGNATURE, COMPUTE_BUDGET_PROGRAM_ID

DEFAULT_CU_PER_INSTRUCTION = 200_000
MAX_CU_LIMIT = 1_400_000

# Jito tip payment accounts (transactions paying them are bundle/tip related: out of scope).
JITO_TIP_ACCOUNTS = {
    "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5", "HFqU5x63VTqvQss8hp11i4wVV8bD44PvwucfZ2bU7gRe",
    "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY", "ADaUMid9yfUytqMBgopwjb2DTLSokTSzL1zt6iGPaS49",
    "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh", "ADuUkR4vqLUMWXxW9gh6D6L8pMSawimctcNZ5pGwDcEt",
    "DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL2KRL", "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnizKZ6jT",
}


def instructions(t: dict[str, Any], all_keys: list[str]) -> list[tuple[str | None, str]]:
    """(program id, base58 data) of every top-level instruction of a getBlock transaction (encoding json)."""
    out = []
    for ix in t["transaction"]["message"].get("instructions", []):
        if "programIdIndex" in ix:
            pid = all_keys[ix["programIdIndex"]] if ix["programIdIndex"] < len(all_keys) else None
        else:
            pid = ix.get("programId")
        out.append((pid, ix.get("data") if isinstance(ix.get("data"), str) else ""))
    return out


def requested_cu_limit(t: dict[str, Any], all_keys: list[str]) -> tuple[int, str]:
    """Requested compute-unit limit and where it came from: "instruction", "v1_config" or "default"."""
    ixs = instructions(t, all_keys)
    for pid, data in ixs:
        if pid == COMPUTE_BUDGET_PROGRAM_ID:
            try:
                raw = b58decode(data)
            except KeyError:
                continue
            if len(raw) >= 5 and raw[0] == 2:
                return min(int.from_bytes(raw[1:5], "little"), MAX_CU_LIMIT), "instruction"
    cfg = t["transaction"]["message"].get("transactionConfig") or {}
    if cfg.get("computeUnitLimit") is not None:
        return min(int(cfg["computeUnitLimit"]), MAX_CU_LIMIT), "v1_config"
    n = sum(1 for pid, _ in ixs if pid != COMPUTE_BUDGET_PROGRAM_ID)
    return min(DEFAULT_CU_PER_INSTRUCTION * n, MAX_CU_LIMIT), "default"


def tx_rows(block: dict[str, Any]) -> list[dict]:
    rows = []
    for i, t in enumerate(block["transactions"]):
        msg, meta = t["transaction"]["message"], t["meta"]
        keys = [k if isinstance(k, str) else k.get("pubkey") for k in msg.get("accountKeys", [])]
        la = meta.get("loadedAddresses") or {}
        all_keys = keys + la.get("writable", []) + la.get("readonly", [])
        nsig = len(t["transaction"]["signatures"])
        fee = int(meta.get("fee") or 0)
        cost = meta.get("costUnits")
        consumed = meta.get("computeUnitsConsumed")
        pf = max(0, fee - BASE_FEE_PER_SIGNATURE * nsig)
        req, req_src = requested_cu_limit(t, all_keys)
        reward = pf + (BASE_FEE_PER_SIGNATURE // 2) * nsig
        cost_sched = (cost - consumed + req) if cost is not None and consumed is not None else None
        rows.append({"index": i, "version": t.get("version"), "vote": is_vote_tx(t),
                     "jito_tip": bool(JITO_TIP_ACCOUNTS.intersection(all_keys)),
                     "failed": meta.get("err") is not None, "nsig": nsig, "fee": fee,
                     "priority_fee": pf, "cost_units": cost, "cu_consumed": consumed,
                     "requested_cu_limit": req, "requested_cu_limit_source": req_src,
                     "reward": reward, "cost_sched": cost_sched,
                     "sched_key": (reward / cost_sched) if cost_sched and cost_sched > 0 else None,
                     "reward_per_cost_units_consumed": (pf / cost) if cost else None,
                     "signature": t["transaction"]["signatures"][0]})
    return rows


def _rank_stats(r: list[dict], field: str, suffix: str) -> dict:
    out: dict = {}
    if len(r) >= 10 and len({x[field] for x in r}) > 1:
        idx = np.array([x["index"] for x in r], float)
        key = np.array([x[field] for x in r], float)
        rho, p = stats.spearmanr(idx, key)
        out[f"spearman_rho_index_vs_{suffix}"] = float(rho)
        out[f"p_{suffix}"] = float(p)
        # fraction of adjacent (in block order) pairs where the earlier one has >= key
        out[f"adjacent_nonincreasing_share_{suffix}"] = float(np.mean(key[:-1] >= key[1:]))
    return out


def order_stats(rows: list[dict], exclude_tips: bool = True) -> dict:
    ok = [x for x in rows if not x["vote"] and not (exclude_tips and x["jito_tip"])]
    r = [x for x in ok if x["reward_per_cost_units_consumed"] is not None]
    rs = [x for x in ok if x["sched_key"] is not None]
    out = {"n_tx": len(rows), "n_used": len(r), "n_used_sched_key": len(rs), "n_tip": sum(x["jito_tip"] for x in rows),
           "share_zero_priority": (sum(x["priority_fee"] == 0 for x in r) / len(r)) if r else None,
           "share_requested_limit_default": (sum(x["requested_cu_limit_source"] == "default" for x in rs) / len(rs)) if rs else None}
    out.update(_rank_stats(r, "reward_per_cost_units_consumed", "reward_per_cost_units_consumed"))
    out.update(_rank_stats(rs, "sched_key", "sched_key"))
    return out
