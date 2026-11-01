"""THE ONLY PLACE IN THIS CODEBASE THAT CALLS sendTransaction.

Every transaction that can cost lamports (probes, fee-payer funding, draining, anchors) goes
through send_signed(), which first reserves the worst-case fee in the spend ledger (fsync'ed),
and only then hands the transactions to the RPC provider. tests/test_send_chokepoint.py fails if
the string "sendTransaction" appears in any other source file.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from .rpc import Rpc, TransportError
from .spend import SpendLedger


@dataclass(frozen=True)
class SignedTx:
    signature: str
    wire_b64: str
    max_fee: int


def _sleep_until(t: float) -> None:
    """Return at the first moment time.time() >= t."""
    while True:
        rem = t - time.time()
        if rem <= 0:
            return
        time.sleep(rem)


def send_signed(rpc: Rpc, ledger: SpendLedger, txs: list[SignedTx], *, tag: str, order: list[int] | None = None,
                gap_s: float = 0.0, max_retries: int | None = 0, skip_preflight: bool = True) -> dict:
    """Reserve, then send. All transactions go in ONE JSON-RPC batch (one HTTP request) unless
    gap_s > 0, in which case they are sent one per request, in `order`; request k leaves at
    (START time of request 0) + k x gap_s, NOT gap_s after the previous response, so the spacing
    does not include the first request's round trip (a late request leaves at once and the actual
    start times are recorded in `send_times`).
    Raises SpendCapExceeded before anything is sent if the cap would be exceeded."""
    order = list(range(len(txs))) if order is None else list(order)
    ledger.reserve([(t.signature, t.max_fee) for t in txs], tag=tag)
    opts = {"encoding": "base64", "skipPreflight": skip_preflight, "preflightCommitment": "processed"}
    if max_retries is not None:  # None = the provider's default rebroadcasting (used for funding and anchors)
        opts["maxRetries"] = max_retries
    calls = [("sendTransaction", [txs[i].wire_b64, opts]) for i in order]
    res: list = []
    times: list[tuple[float, float]] = []
    chunks = [calls] if gap_s <= 0 else [[c] for c in calls]
    t_first = None
    for k, chunk in enumerate(chunks):
        if k and gap_s > 0:
            _sleep_until(t_first + k * gap_s)
        t0 = time.time()
        if t_first is None:
            t_first = t0
        try:
            resp = rpc.batch(chunk, retry=False)
            res += [("ok" if "result" in r else r.get("error")) for r in resp]
        except TransportError as e:
            # Outcome unknown: the transactions may or may not have been forwarded. They stay
            # reserved in the ledger and are resolved by the collector like any other.
            res += [f"transport: {e}"] * len(chunk)
        times.append((t0, time.time()))
    return {"send_results": res, "send_times": times, "send_order": order}
