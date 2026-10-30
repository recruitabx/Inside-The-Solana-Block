"""Block summaries for the collector: `data/raw/<run>.blocks.jsonl`.

For every slot in which any of our transactions landed, and for the first slot of every targeted
window of a Harmonic target (clientId starting with "Harmonic"), the full block is fetched once and a
compact record is appended: slot, producer (Fee reward), transaction count, total computeUnitsConsumed,
the Harmonic strategy label if a memo in the block matches the format documented in
docs/research/bam_harmonic_forks.md (the crank memo "FBA", "MRV" or "FIF", the whole memo text), and,
for a deterministic 10% sample of slots (slot % 10 == 0), one row per transaction for the supplementary
analysis (docs/PREREGISTRATION.md section 12). Idempotent: slots already summarized are skipped.
The memo string alone is not unique (a Firedancer block carried "FBA" at transaction 415), so the label
is only used for the first block of a Harmonic target's window and the index of the memo is recorded.
"""
from __future__ import annotations

import json
import os
from typing import Any

from .blocks import b58decode, block_full
from .blockstats import instructions, tx_rows
from .config import MEMO_PROGRAM_ID
from .rpc import Rpc, RpcError

MEMO_PROGRAMS = {MEMO_PROGRAM_ID, "Memo1UhkJRfHyvLMcVucJwxXeuD728EqVDDwQDxFMNo"}
STRATEGY_LABELS = ("FBA", "MRV", "FIF")
SAMPLE_MOD = 10
TX_COLS = ["index", "version", "vote", "jito_tip", "nsig", "fee", "cost_units", "cu_consumed", "requested_cu_limit"]


def _all_keys(t: dict[str, Any]) -> list[str]:
    msg, meta = t["transaction"]["message"], t["meta"]
    keys = [k if isinstance(k, str) else k.get("pubkey") for k in msg.get("accountKeys", [])]
    la = meta.get("loadedAddresses") or {}
    return keys + la.get("writable", []) + la.get("readonly", [])


def strategy_memo(block: dict[str, Any]) -> tuple[str | None, int | None]:
    """First memo (in block order) whose text is exactly FBA, MRV or FIF: (label, transaction index)."""
    for i, t in enumerate(block.get("transactions", [])):
        for pid, data in instructions(t, _all_keys(t)):
            if pid in MEMO_PROGRAMS and data:
                try:
                    text = b58decode(data).decode("utf-8")
                except (KeyError, UnicodeDecodeError):
                    continue
                if text in STRATEGY_LABELS:
                    return text, i
    return None, None


def summarize_block(block: dict[str, Any], slot: int) -> dict:
    fee = [r["pubkey"] for r in (block.get("rewards") or []) if r.get("rewardType") == "Fee"]
    txs = block.get("transactions", [])
    label, idx = strategy_memo(block)
    rec = {"record": "block", "slot": slot, "producer": fee[0] if len(fee) == 1 else None, "tx_count": len(txs),
           "cu_consumed_total": sum(int(t["meta"].get("computeUnitsConsumed") or 0) for t in txs),
           "block_time": block.get("blockTime"), "strategy": label, "strategy_tx_index": idx,
           "sampled": slot % SAMPLE_MOD == 0}
    if rec["sampled"]:
        rec["tx_cols"] = TX_COLS
        rec["tx_rows"] = [[r[c] for c in TX_COLS] for r in tx_rows(block)]
    return rec


def slots_to_summarize(sent_recs: list[dict], landed_recs: list[dict]) -> list[int]:
    """Slots where any of our transactions landed + first slot of every targeted window of a Harmonic target."""
    slots = {int(o["slot"]) for o in landed_recs if o.get("record") == "landed"}
    start = next((r for r in sent_recs if r.get("record") == "run_start"), {})
    now = start.get("targets_client_now") or {}
    for r in sent_recs:
        if r.get("record") == "probe" and r.get("mode") == "live":
            client = r.get("target_client_id") or now.get(r["target_leader"]) or ""
            if client.startswith("Harmonic"):
                slots.add(int(r["window_first_slot"]))
    return sorted(slots)


def summarized_slots(path: str) -> set[int]:
    if not os.path.exists(path):
        return set()
    out = set()
    for line in open(path):
        if line.strip():
            out.add(json.loads(line)["slot"])
    return out


def enrich_run(blocks_path: str, sent_recs: list[dict], landed_recs: list[dict], rpc: Rpc) -> dict:
    """Append a summary for every slot of this run that has none yet. A skipped slot gets a record with
    `skipped: true` (nothing to fetch again); a block that is not available yet is retried next time."""
    done = summarized_slots(blocks_path)
    todo = [s for s in slots_to_summarize(sent_recs, landed_recs) if s not in done]
    n_new = n_skipped = n_err = 0
    if todo:
        os.makedirs(os.path.dirname(os.path.abspath(blocks_path)), exist_ok=True)
        with open(blocks_path, "a") as f:
            for slot in todo:
                try:
                    block = block_full(rpc, slot, rewards=True)
                except RpcError:
                    n_err += 1
                    continue
                rec = {"record": "block", "slot": slot, "skipped": True, "producer": None} if block is None else summarize_block(block, slot)
                n_skipped += block is None
                n_new += block is not None
                f.write(json.dumps(rec, sort_keys=True) + "\n")
                f.flush()
    return {"blocks_file": os.path.basename(blocks_path), "slots": len(done) + n_new + n_skipped, "new": n_new,
            "skipped_slots": n_skipped, "errors": n_err}
