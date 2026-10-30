"""Building the probe transactions (template of docs/PREREGISTRATION.md section 5).

Every probe transaction is legacy, one signature, four instructions:
  SetComputeUnitLimit(cu_limit), SetComputeUnitPrice(cu_price),
  SetLoadedAccountsDataSizeLimit(loaded_limit), SystemProgram.Transfer(payer -> W, 0 lamports)
Writable accounts: the payer and W. W is a fresh never-funded address; two transactions that use
the same W conflict (the scheduler must serialize them), two that use different W do not (their
payers always differ). No memo (it costs ~370 CU per byte), no tip accounts, no bundles.
"""
from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass

from solders.compute_budget import (set_compute_unit_limit, set_compute_unit_price,
                                    set_loaded_accounts_data_size_limit)
from solders.hash import Hash
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction

from .spend import max_fee_lamports


@dataclass(frozen=True)
class BuiltTx:
    signature: str
    payer: str
    cu_limit: int
    cu_price: int  # micro-lamports per CU
    loaded_limit: int
    shared_account: str
    max_fee: int
    wire_b64: str
    memo: str = ""


def fresh_address(seed: str, probe_no: int | str, k: int = 0) -> Pubkey:
    """Deterministic, never-funded address for the write lock W of probe `probe_no`."""
    return Pubkey(hashlib.sha256(f"itb-W:{seed}:{probe_no}:{k}".encode()).digest())


def build_probe_tx(payer: Keypair, blockhash: str, *, cu_limit: int, cu_price: int, shared: Pubkey,
                   loaded_limit: int = 4096) -> BuiltTx:
    ixs = [set_compute_unit_limit(cu_limit), set_compute_unit_price(cu_price),
           set_loaded_accounts_data_size_limit(loaded_limit),
           transfer(TransferParams(from_pubkey=payer.pubkey(), to_pubkey=shared, lamports=0))]
    tx = Transaction([payer], Message(ixs, payer.pubkey()), Hash.from_string(blockhash))
    return BuiltTx(signature=str(tx.signatures[0]), payer=str(payer.pubkey()), cu_limit=cu_limit, cu_price=cu_price,
                   loaded_limit=loaded_limit, shared_account=str(shared),
                   max_fee=max_fee_lamports(1, cu_price, cu_limit), wire_b64=base64.b64encode(bytes(tx)).decode())
