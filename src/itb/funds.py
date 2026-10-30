"""Moving SOL between the funding wallet and the derived fee payers, and on-chain anchors.
Every transaction here goes through send.send_signed (spend ledger reservation first).

  itb fund   --live --lamports-each N   fund every derived payer up to N lamports
  itb drain  --live                      move everything from the payers back to the wallet
  itb anchor --live --sha256 HEX --label TEXT   write "itb-anchor:<label>:<sha256>" in a Memo
All three are live-only operations: they need --live and ITB_LIVE=1 like the runner.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

from solders.hash import Hash
from solders.instruction import Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction
import base64

from .config import BASE_FEE_PER_SIGNATURE, MEMO_PROGRAM_ID
from .rpc import Rpc
from .send import SignedTx, send_signed
from .spend import SpendLedger

LEDGER_PATH = "data/ledger/spend.jsonl"
PUBLIC_RPC = "https://api.mainnet-beta.solana.com"


def _signed(tx: Transaction, nsig: int = 1) -> SignedTx:
    return SignedTx(str(tx.signatures[0]), base64.b64encode(bytes(tx)).decode(), nsig * BASE_FEE_PER_SIGNATURE)


def transfer_tx(src: Keypair, dst: Pubkey, lamports: int, blockhash: str) -> SignedTx:
    ix = transfer(TransferParams(from_pubkey=src.pubkey(), to_pubkey=dst, lamports=lamports))
    return _signed(Transaction([src], Message([ix], src.pubkey()), Hash.from_string(blockhash)))


def memo_tx(payer: Keypair, text: str, blockhash: str) -> SignedTx:
    ix = Instruction(Pubkey.from_string(MEMO_PROGRAM_ID), text.encode(), [])
    return _signed(Transaction([payer], Message([ix], payer.pubkey()), Hash.from_string(blockhash)))


def _confirm(read: Rpc, sigs: list[str], timeout_s: float = 60) -> dict:
    t0 = time.time()
    st = {}
    while time.time() - t0 < timeout_s:
        vals = read.call("getSignatureStatuses", [sigs, {"searchTransactionHistory": True}])["value"]
        st = dict(zip(sigs, vals))
        if all(v and v.get("confirmationStatus") in ("confirmed", "finalized") for v in vals):
            break
        time.sleep(2)
    return {s: (v or {}).get("confirmationStatus") for s, v in st.items()}


def main_for(cmd: str, argv: list[str] | None = None) -> int:
    from .runner import cap_from_env, live_gate
    from .wallet import derive_payers, load_wallet
    ap = argparse.ArgumentParser(prog=f"itb {cmd}")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--plan", default="data/plan.json")
    ap.add_argument("--lamports-each", type=int, default=0)
    ap.add_argument("--sha256", default="")
    ap.add_argument("--label", default="")
    a = ap.parse_args(argv)
    if not live_gate(a):
        raise SystemExit(f"`itb {cmd}` moves SOL: it needs --live and ITB_LIVE=1")
    plan = json.load(open(a.plan))
    send = Rpc(rate_per_s=1.0, burst=2.0, retries=0)
    read = Rpc(os.environ.get("ITB_READ_RPC_URL", PUBLIC_RPC), rate_per_s=3.0, burst=3.0)
    master = load_wallet()
    payers = derive_payers(master, int(plan["n_payers"]))
    log = []
    with SpendLedger(LEDGER_PATH, cap_from_env()) as ledger:
        bh = read.call("getLatestBlockhash", [{"commitment": "confirmed"}])["value"]["blockhash"]
        txs: list[SignedTx] = []
        if cmd == "fund":
            if a.lamports_each <= 0:
                raise SystemExit("--lamports-each is required")
            bals = read.call("getMultipleAccounts", [[str(p.pubkey()) for p in payers], {"encoding": "base64"}])["value"]
            for p, acc in zip(payers, bals):
                have = (acc or {}).get("lamports", 0)
                if have < a.lamports_each:
                    txs.append(transfer_tx(master, p.pubkey(), a.lamports_each - have, bh))
        elif cmd == "drain":
            bals = read.call("getMultipleAccounts", [[str(p.pubkey()) for p in payers], {"encoding": "base64"}])["value"]
            for p, acc in zip(payers, bals):
                have = (acc or {}).get("lamports", 0)
                if have > BASE_FEE_PER_SIGNATURE:
                    txs.append(transfer_tx(p, master.pubkey(), have - BASE_FEE_PER_SIGNATURE, bh))
        elif cmd == "anchor":
            if len(a.sha256) != 64 or not a.label:
                raise SystemExit("--sha256 (64 hex chars) and --label are required")
            txs.append(memo_tx(master, f"itb-anchor:{a.label}:{a.sha256}", bh))
        for i, t in enumerate(txs):
            r = send_signed(send, ledger, [t], tag=f"{cmd}:{i}")
            log.append({"signature": t.signature, **r})
            time.sleep(1.1)
        status = _confirm(read, [t.signature for t in txs]) if txs else {}
        rec = {"record": cmd, "t": time.time(), "txs": log, "status": status, "ledger": ledger.summary()}
    os.makedirs("data/ledger", exist_ok=True)
    with open("data/accounts.json", "w") as f:  # public keys only, used by `itb audit`
        json.dump({"wallet": str(master.pubkey()), "payers": [str(p.pubkey()) for p in payers]}, f, indent=1)
    with open("data/ledger/operations.jsonl", "a") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")
    print(json.dumps({"cmd": cmd, "n_tx": len(txs), "status": status}, indent=1))
    return 0


class _Cmd:
    def __init__(self, name):
        self.name = name

    def main(self, argv):
        return main_for(self.name, argv)


fund, drain, anchor = _Cmd("fund"), _Cmd("drain"), _Cmd("anchor")
