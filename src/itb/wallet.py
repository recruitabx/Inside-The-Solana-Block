"""Key handling.

Only ONE secret exists: the funding wallet (Solana CLI JSON format, 64 bytes), mounted read-only
into the container (default /secrets/wallet.json, override with ITB_WALLET). The fee payers used
by probe transactions are derived deterministically from it, so no further key files are written
and the payers can always be re-derived to drain their balances back.
Nothing in this module ever prints or logs secret material.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat

from solders.keypair import Keypair

DEFAULT_WALLET_PATH = "/secrets/wallet.json"


def load_wallet(path: str | None = None) -> Keypair:
    path = path or os.environ.get("ITB_WALLET", DEFAULT_WALLET_PATH)
    if not os.path.exists(path):
        raise SystemExit(f"wallet file not found at {path} (live mode needs a mounted wallet, see .env.example)")
    mode = stat.S_IMODE(os.stat(path).st_mode)
    if mode & 0o077 and os.environ.get("ITB_ALLOW_LOOSE_WALLET_PERMS") != "1":
        raise SystemExit(f"wallet file {path} is readable by group/others (mode {oct(mode)}); chmod 600 it")
    with open(path) as f:
        raw = json.load(f)
    if not (isinstance(raw, list) and len(raw) == 64):
        raise SystemExit("wallet file must be a Solana CLI keypair JSON array of 64 bytes")
    return Keypair.from_bytes(bytes(raw))


def derive_payer(master: Keypair, index: int) -> Keypair:
    seed = hashlib.sha256(bytes(master)[:32] + b"itb-fee-payer-v1" + index.to_bytes(4, "little")).digest()
    return Keypair.from_seed(seed)


def derive_payers(master: Keypair, n: int) -> list[Keypair]:
    return [derive_payer(master, i) for i in range(n)]
