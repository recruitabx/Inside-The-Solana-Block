"""Building the probe transactions.

Each probe transaction is deliberately minimal and independent of the others:
  * its own fee payer (so no two probe transactions share a writable account),
  * SetComputeUnitLimit + SetComputeUnitPrice (the priority-fee knobs under test),
  * one Memo instruction carrying the probe id, so each transaction identifies itself in the
    block without any off-chain lookup. Memo without signer accounts takes no account locks.
No tip accounts, no bundles.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass

from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
from solders.hash import Hash
from solders.instruction import Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction

from .config import MEMO_PROGRAM_ID
from .spend import max_fee_lamports

MEMO = Pubkey.from_string(MEMO_PROGRAM_ID)


@dataclass(frozen=True)
class BuiltTx:
    signature: str
    payer: str
    cu_limit: int
    cu_price: int  # micro-lamports per CU
    memo: str
    max_fee: int
    wire_b64: str


def build_probe_tx(payer: Keypair, blockhash: str, *, cu_limit: int, cu_price: int, memo: str) -> BuiltTx:
    ixs = [set_compute_unit_limit(cu_limit), set_compute_unit_price(cu_price),
           Instruction(MEMO, memo.encode(), [])]
    tx = Transaction([payer], Message(ixs, payer.pubkey()), Hash.from_string(blockhash))
    return BuiltTx(signature=str(tx.signatures[0]), payer=str(payer.pubkey()), cu_limit=cu_limit,
                   cu_price=cu_price, memo=memo, max_fee=max_fee_lamports(1, cu_price, cu_limit),
                   wire_b64=base64.b64encode(bytes(tx)).decode())
