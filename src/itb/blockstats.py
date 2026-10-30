"""Supplementary (secondary) evidence: how ALL transactions in a leader's block are ordered.

For every non-vote transaction in a block we compute the quantities a fee-priority scheduler
would sort on, from getBlock alone:
  priority_fee  = meta.fee - 5000 * signatures            (lamports)
  cost_units    = meta.costUnits                           (cost-model units, all tx versions)
  reward_per_cu = priority_fee / cost_units
and then the rank correlation between block position and reward_per_cu. A strongly negative
Spearman rho means "higher reward per cost unit earlier". This is not the primary evidence of
the study (other people's transactions arrive at unknown times); it describes competition
inside the block.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from scipy import stats

from .blocks import is_vote_tx
from .config import BASE_FEE_PER_SIGNATURE

# Jito tip payment accounts (transactions paying them are bundle/tip related: out of scope).
JITO_TIP_ACCOUNTS = {
    "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5", "HFqU5x63VTqvQss8hp11i4wVV8bD44PvwucfZ2bU7gRe",
    "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY", "ADaUMid9yfUytqMBgopwjb2DTLSokTSzL1zt6iGPaS49",
    "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh", "ADuUkR4vqLUMWXxW9gh6D6L8pMSawimctcNZ5pGwDcEt",
    "DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL2KRL", "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnizKZ6jT",
}


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
        pf = max(0, fee - BASE_FEE_PER_SIGNATURE * nsig)
        rows.append({"index": i, "version": t.get("version"), "vote": is_vote_tx(t),
                     "jito_tip": bool(JITO_TIP_ACCOUNTS.intersection(all_keys)),
                     "failed": meta.get("err") is not None, "nsig": nsig, "fee": fee,
                     "priority_fee": pf, "cost_units": cost,
                     "reward_per_cu": (pf / cost) if cost else None, "signature": t["transaction"]["signatures"][0]})
    return rows


def order_stats(rows: list[dict], exclude_tips: bool = True) -> dict:
    r = [x for x in rows if not x["vote"] and x["reward_per_cu"] is not None and not (exclude_tips and x["jito_tip"])]
    out = {"n_tx": len(rows), "n_used": len(r), "n_tip": sum(x["jito_tip"] for x in rows),
           "share_zero_priority": (sum(x["priority_fee"] == 0 for x in r) / len(r)) if r else None}
    if len(r) >= 10 and len({x["reward_per_cu"] for x in r}) > 1:
        idx = np.array([x["index"] for x in r], float)
        rpc = np.array([x["reward_per_cu"] for x in r], float)
        rho, p = stats.spearmanr(idx, rpc)
        out.update({"spearman_rho_index_vs_reward_per_cu": float(rho), "p": float(p)})
        # fraction of adjacent (in block order) pairs where the earlier one has >= reward per CU
        conc = np.mean(rpc[:-1] >= rpc[1:])
        out["adjacent_nonincreasing_share"] = float(conc)
    return out
