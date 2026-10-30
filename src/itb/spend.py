"""Hard spend cap.

Every transaction the live runner sends must first be RESERVED here at its worst-case fee
(base fee for every signature + compute-unit price x compute-unit limit). The reservation is
appended to an append-only JSONL ledger and fsync'ed BEFORE the transaction leaves the
process. If the reservation would push the committed total over the cap, SpendCapExceeded is
raised and nothing is written and nothing is sent.

Committed total = worst-case fees of reservations that are still open
                + actual fees of reservations that were settled from on-chain metadata.
A reservation is released (counted as zero) only when the transaction provably cannot land
(its blockhash expired and getSignatureStatuses does not know it).

The ledger survives crashes and restarts: the committed total is recomputed from the file on
every start, so a resumed run can never "forget" earlier spend.
"""
from __future__ import annotations

import fcntl
import json
import math
import os
import time
from dataclasses import dataclass

from .config import BASE_FEE_PER_SIGNATURE, HARD_SPEND_CEILING_LAMPORTS


class SpendCapExceeded(RuntimeError):
    pass


def max_fee_lamports(num_signatures: int, cu_price_microlamports: int, cu_limit: int) -> int:
    """Worst-case fee of one transaction: base fee per signature plus the full priority fee
    for the requested compute-unit limit (rounded up, as the runtime does)."""
    if num_signatures < 1 or cu_price_microlamports < 0 or cu_limit < 0:
        raise ValueError("invalid fee parameters")
    return num_signatures * BASE_FEE_PER_SIGNATURE + math.ceil(cu_price_microlamports * cu_limit / 1_000_000)


@dataclass
class _Entry:
    max_fee: int
    state: str  # open | settled | released
    actual: int = 0


class SpendLedger:
    def __init__(self, path: str, cap_lamports: int):
        if not isinstance(cap_lamports, int) or cap_lamports <= 0:
            raise ValueError("cap must be a positive integer number of lamports")
        if cap_lamports > HARD_SPEND_CEILING_LAMPORTS:
            raise ValueError(
                f"cap {cap_lamports} exceeds the hard ceiling {HARD_SPEND_CEILING_LAMPORTS} lamports (0.05 SOL)")
        self.path = path
        self.cap = cap_lamports
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._lockf = open(path + ".lock", "w")
        try:
            fcntl.flock(self._lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("another process holds the spend ledger lock") from None
        self.entries: dict[str, _Entry] = {}
        if os.path.exists(path):
            with open(path) as f:
                for line in f:
                    if line.strip():
                        self._apply(json.loads(line))

    def close(self) -> None:
        try:
            fcntl.flock(self._lockf, fcntl.LOCK_UN)
        finally:
            self._lockf.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ledger state ---------------------------------------------------------------------------
    def _apply(self, rec: dict) -> None:
        k, sig = rec["kind"], rec["sig"]
        if k == "reserve":
            if sig in self.entries:
                raise ValueError(f"duplicate reservation for {sig}")
            self.entries[sig] = _Entry(int(rec["max_fee"]), "open")
        elif k == "settle":
            e = self.entries[sig]
            e.state, e.actual = "settled", int(rec["actual_fee"])
        elif k == "release":
            self.entries[sig].state = "released"
        else:
            raise ValueError(f"unknown ledger record kind {k}")

    def committed(self) -> int:
        tot = 0
        for e in self.entries.values():
            if e.state == "open":
                tot += e.max_fee
            elif e.state == "settled":
                tot += e.actual
        return tot

    def remaining(self) -> int:
        return self.cap - self.committed()

    def _append(self, recs: list[dict]) -> None:
        with open(self.path, "a") as f:
            for r in recs:
                f.write(json.dumps(r, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())

    # API -------------------------------------------------------------------------------------
    def reserve(self, items: list[tuple[str, int]], *, tag: str = "") -> None:
        """Atomically reserve worst-case fees for a group of transactions (signature, max_fee).
        Raises SpendCapExceeded (and records nothing) if the group does not fit under the cap."""
        need = sum(int(m) for _, m in items)
        if any(m <= 0 for _, m in items):
            raise ValueError("max_fee must be positive")
        if self.committed() + need > self.cap:
            raise SpendCapExceeded(
                f"reservation of {need} lamports would exceed cap: committed {self.committed()} + {need} > {self.cap}")
        now = time.time()
        recs = [{"kind": "reserve", "sig": s, "max_fee": int(m), "tag": tag, "ts": now} for s, m in items]
        for r in recs:
            if r["sig"] in self.entries:
                raise ValueError(f"duplicate reservation for {r['sig']}")
        self._append(recs)
        for r in recs:
            self._apply(r)

    def settle(self, sig: str, actual_fee: int) -> None:
        e = self.entries[sig]
        if e.state != "open":
            return
        if actual_fee > e.max_fee:
            # Should be impossible; keep the larger number so the cap stays conservative.
            actual_fee = int(actual_fee)
        rec = {"kind": "settle", "sig": sig, "actual_fee": int(actual_fee), "ts": time.time()}
        self._append([rec]); self._apply(rec)

    def release(self, sig: str, reason: str) -> None:
        e = self.entries[sig]
        if e.state != "open":
            return
        rec = {"kind": "release", "sig": sig, "reason": reason, "ts": time.time()}
        self._append([rec]); self._apply(rec)

    def summary(self) -> dict:
        st = {"open": 0, "settled": 0, "released": 0}
        for e in self.entries.values():
            st[e.state] += 1
        return {"cap": self.cap, "committed": self.committed(), "remaining": self.remaining(),
                "settled_actual": sum(e.actual for e in self.entries.values() if e.state == "settled"), **st}
