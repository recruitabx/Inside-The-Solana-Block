"""Turn sent transactions into landed records: slot, index in block, leader, fee, CU used.

Everything here is read-only and idempotent; re-running it on the same inputs produces the
same records (except for transactions that land/expire in between)."""
from __future__ import annotations

from typing import Any, Iterable

from .blocks import block_info
from .config import MAX_SUPPORTED_TX_VERSION, MIN_SLOT
from .rpc import Rpc


def signature_statuses(rpc: Rpc, sigs: list[str]) -> dict[str, dict | None]:
    out: dict[str, dict | None] = {}
    for i in range(0, len(sigs), 256):
        chunk = sigs[i:i + 256]
        vals = rpc.call("getSignatureStatuses", [chunk, {"searchTransactionHistory": True}])["value"]
        out.update(dict(zip(chunk, vals)))
    return out


class BlockCache:
    def __init__(self, rpc: Rpc):
        self.rpc = rpc
        self.info: dict[int, dict | None] = {}

    def get(self, slot: int) -> dict | None:
        if slot not in self.info:
            self.info[slot] = block_info(self.rpc, slot)
        return self.info[slot]

    def signatures(self, slot: int) -> list[str] | None:
        i = self.get(slot)
        return None if i is None else i["signatures"]

    def leader(self, slot: int) -> str | None:
        i = self.get(slot)
        return None if i is None else i["leader"]


def tx_meta(rpc: Rpc, sig: str) -> dict[str, Any] | None:
    t = rpc.call("getTransaction", [sig, {"encoding": "json", "commitment": "confirmed",
                                          "maxSupportedTransactionVersion": MAX_SUPPORTED_TX_VERSION}])
    if t is None:
        return None
    m = t["meta"]
    return {"fee": m.get("fee"), "cu_consumed": m.get("computeUnitsConsumed"), "cost_units": m.get("costUnits"), "err": m.get("err"),
            "block_time": t.get("blockTime"), "slot": t.get("slot")}


def landed_records(rpc: Rpc, sent: Iterable[dict], clients: dict | None = None,
                   cache: BlockCache | None = None, clients_end: dict | None = None) -> list[dict]:
    """sent: dicts with at least signature and probe_id. clients: client snapshot nodes map (run start);
    clients_end: the same at run end, to flag a producer whose claim changed during the run."""
    sent = list(sent)
    cache = cache or BlockCache(rpc)
    st = signature_statuses(rpc, [s["signature"] for s in sent])
    out = []
    for s in sent:
        sig = s["signature"]
        v = st.get(sig)
        if v is None:
            out.append({"record": "not_landed", "signature": sig, "probe_id": s.get("probe_id"),
                        "reason": "unknown to cluster at collection time"})
            continue
        slot = int(v["slot"])
        if slot < MIN_SLOT:
            raise ValueError(f"slot {slot} is below MIN_SLOT {MIN_SLOT}: refusing to mix pre-Alpenglow data")
        sigs = cache.signatures(slot)
        if sigs is None or sig not in sigs:
            out.append({"record": "not_landed", "signature": sig, "probe_id": s.get("probe_id"),
                        "reason": f"status says slot {slot} but block not readable yet"})
            continue
        leader = cache.leader(slot)
        meta = tx_meta(rpc, sig) or {}
        c = (clients or {}).get(leader, {})
        extra = {}
        if clients_end is not None:
            ce = clients_end.get(leader, {})
            extra = {"leader_client_id_end": ce.get("clientId"), "leader_version_end": ce.get("version"),
                     "leader_claim_changed_in_run": (ce.get("clientId"), ce.get("version")) != (c.get("clientId"), c.get("version"))}
        out.append({"record": "landed", "signature": sig, "probe_id": s.get("probe_id"), "slot": slot,
                    "tx_index": sigs.index(sig), "block_tx_count": len(sigs), "leader": leader,
                    "leader_source": "block Fee reward",
                    "leader_client_id": c.get("clientId"), "leader_version": c.get("version"),
                    "confirmation_status": v.get("confirmationStatus"), "status_err": v.get("err"), **extra, **meta})
    return out
