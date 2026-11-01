"""Reading blocks. The in-block position of a transaction is its index in the block's
transaction list as returned by getBlock, which follows the order of entries in the block."""
from __future__ import annotations

from typing import Any

from .config import MAX_SUPPORTED_TX_VERSION, VOTE_PROGRAM_ID
from .rpc import Rpc, RpcError

SKIPPED_CODES = {-32007, -32009}  # slot skipped / missing in long-term storage
NOT_AVAILABLE_CODES = {-32004, -32014}  # block not available yet / status not available


def block_signatures(rpc: Rpc, slot: int, commitment: str = "confirmed") -> list[str] | None:
    """First signature of every transaction in block order, or None if the slot was skipped."""
    info = block_info(rpc, slot, commitment)
    return None if info is None else info["signatures"]


def block_info(rpc: Rpc, slot: int, commitment: str = "confirmed") -> dict[str, Any] | None:
    """Signatures in block order plus the block producer.

    The producer is read from the block itself: the single reward of type "Fee" goes to the
    leader that produced the block. This keeps verification possible after RPC nodes stop
    serving old leader schedules (getSlotLeaders history is only ~9 days on public RPC)."""
    try:
        b = rpc.call("getBlock", [slot, {"encoding": "json", "transactionDetails": "signatures", "rewards": True,
                                           "maxSupportedTransactionVersion": MAX_SUPPORTED_TX_VERSION,
                                           "commitment": commitment}])
    except RpcError as e:
        if e.code in SKIPPED_CODES:
            return None
        raise
    if b is None:
        return None
    fee = [r["pubkey"] for r in (b.get("rewards") or []) if r.get("rewardType") == "Fee"]
    return {"signatures": list(b["signatures"]), "leader": fee[0] if len(fee) == 1 else None,
            "block_time": b.get("blockTime"), "block_height": b.get("blockHeight")}


def block_full(rpc: Rpc, slot: int, commitment: str = "confirmed", rewards: bool = False) -> dict[str, Any] | None:
    try:
        return rpc.call("getBlock", [slot, {"encoding": "json", "transactionDetails": "full", "rewards": rewards,
                                              "maxSupportedTransactionVersion": MAX_SUPPORTED_TX_VERSION,
                                              "commitment": commitment}])
    except RpcError as e:
        if e.code in SKIPPED_CODES:
            return None
        raise


def is_vote_tx(tx: dict[str, Any]) -> bool:
    msg = tx["transaction"]["message"]
    keys = msg.get("accountKeys", [])
    keys = [k if isinstance(k, str) else k.get("pubkey") for k in keys]
    return VOTE_PROGRAM_ID in keys


def slot_leader(rpc: Rpc, slot: int) -> str:
    return rpc.call("getSlotLeaders", [slot, 1])[0]


_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_INDEX = {c: i for i, c in enumerate(_B58)}


def b58decode(s: str) -> bytes:
    """Base58 (Bitcoin alphabet) decoding of instruction data as returned by getBlock encoding "json"."""
    n = 0
    for c in s:
        n = n * 58 + _B58_INDEX[c]
    body = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return b"\x00" * (len(s) - len(s.lstrip("1"))) + body


def b58encode(b: bytes) -> str:
    n = int.from_bytes(b, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = _B58[r] + out
    return "1" * (len(b) - len(b.lstrip(b"\x00"))) + out
