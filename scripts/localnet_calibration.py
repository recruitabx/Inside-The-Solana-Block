#!/usr/bin/env python3
"""Localnet calibration: can the ordering analysis recover a KNOWN answer?

Runs against a LOCAL solana-test-validator only (the script refuses any non-loopback endpoint).
Three conditions, each pair has a fee contrast and a send order drawn independently by a seeded RNG:

  A  arrival-known    two txs, DISJOINT fee payers, sent through the local RPC 50 ms apart.
                      Known answer: the tx sent first lands first (fee is irrelevant).
  B  priority-known   two CONFLICTING txs (both write one shared account W) written back-to-back
                      on ONE QUIC connection straight into the local TPU, optionally preceded by K
                      zero-priority-fee filler txs that also write W. Known answer: higher reward per
                      cost first. A configuration sweep runs first (K, CU limits, filler weight, lead
                      time) and the configuration with the highest Wilson lower bound is used for B.
                      Why fillers (hypothesis from reading Agave 4.3.2, not isolated by instrumentation):
                      the greedy scheduler schedules a tx as soon as it reaches the container, so
                      without a pause the order is arrival order. Fillers with a 1.4M CU limit that
                      are slow to execute (ed25519 precompile entries) occupy the W thread and the
                      scheduling budget for a few ms, so both txs of the pair wait in the container
                      and leave it in priority order. The sweep records what actually works.
  C  placebo          like B but with EQUAL fees. The label of each tx is a coin, so P(label 1 first)
                      must be about 0.5.

Output: one JSON line per pair (see `run_pair` for the fields) plus a printed summary
(n pairs, n same-slot, k first-sent-first, k higher-fee-first, Wilson 95% CI, exact binomial p).

Usage:
  python scripts/localnet_calibration.py --rpc http://127.0.0.1:8899 \
      --out data/calibration/localnet_$(date -u +%F).jsonl --pairs 60 --seed 1
Extra dependency (not in pyproject.toml): aioquic (only needed for conditions B and C).
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import datetime as dt
import json
import os
import random
import socket
import ssl
import struct
import sys
import time
import urllib.parse
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price  # noqa: E402
from solders.hash import Hash  # noqa: E402
from solders.instruction import Instruction  # noqa: E402
from solders.keypair import Keypair  # noqa: E402
from solders.message import Message  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402
from solders.system_program import TransferParams, transfer  # noqa: E402
from solders.transaction import Transaction  # noqa: E402

from itb.blocks import block_info  # noqa: E402
from itb.rpc import Rpc, RpcError, TransportError  # noqa: E402
from itb.stats import binom_two_sided_p, wilson_ci  # noqa: E402
from itb.txbuild import build_probe_tx  # noqa: E402

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
SCHEMA = 1
HI_PRICE, LO_PRICE = 1_000_000, 1_000  # micro-lamports per CU, as in the earlier ad-hoc runs


# --------------------------------------------------------------------------------------------
# Configuration and records
# --------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Cfg:
    """One send configuration. k = number of low-fee filler txs written before the pair."""
    transport: str = "quic"          # "rpc" (condition A) or "quic" (B, C)
    k: int = 0
    cu_limit: int = 200_000
    price_lo: int = LO_PRICE
    price_hi: int = HI_PRICE
    filler_price: int = 0
    filler_cu_limit: int = 0         # 0 = same as cu_limit; a large limit makes a filler "expensive" for the scheduler
    filler_sigs: int = 0             # 0 = plain filler; N > 0 = filler also verifies N ed25519 signatures (slow to execute)
    gap_ms: float = 50.0             # A only: gap between the two RPC sends
    lead_ms: float = 0.0             # B/C only: pause between flushing the fillers and the pair

    def key(self) -> str:
        if self.transport == "rpc":
            return f"rpc gap={self.gap_ms:g}ms cu={self.cu_limit} lo={self.price_lo} hi={self.price_hi}"
        s = f"K={self.k} cu={self.cu_limit} lo={self.price_lo} hi={self.price_hi}"
        if self.k:
            s += f" filler_cu={self.filler_cu_limit or self.cu_limit} filler_sigs={self.filler_sigs}"
        return s + (f" lead={self.lead_ms:g}ms" if self.lead_ms else "")


def cfg_from_dict(d: dict[str, Any]) -> Cfg:
    return Cfg(**{k: d[k] for k in Cfg.__dataclass_fields__ if k in d})


# --------------------------------------------------------------------------------------------
# Record parsing and summary (pure functions, unit-tested without a network)
# --------------------------------------------------------------------------------------------
def load_records(path: str) -> list[dict[str, Any]]:
    out = []
    with open(path, encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{ln}: invalid JSON ({e})") from None
            if rec.get("record") == "pair":
                out.append(rec)
    return out


def pair_outcome(rec: dict[str, Any]) -> dict[str, Any] | None:
    """Ordering facts of one pair, or None when a tx did not land / has no block index."""
    txs = {t["label"]: t for t in rec["txs"]}
    a, b = txs[1], txs[2]
    for t in (a, b):
        if t.get("slot") is None or t.get("index") is None:
            return None
    first = 1 if (a["slot"], a["index"]) < (b["slot"], b["index"]) else 2
    hi = rec.get("hi_label")
    return {
        "same_slot": a["slot"] == b["slot"],
        "first_label": first,
        "first_sent_first": first == rec["first_label"],
        "hi_first": None if hi is None else first == hi,
        "label1_first": first == 1,
    }


def group_name(rec: dict[str, Any]) -> str:
    cond = rec["condition"]
    return f"{cond} {cfg_from_dict(rec['cfg']).key()}" if cond == "B-sweep" else cond


def summarize(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per group (A, B, C, then every B-sweep configuration ordered by K, filler weight, lead).

    The ordering statistics use SAME-SLOT pairs only (the in-block position is only comparable
    inside one block). For C there is no fee contrast, so the 'higher-fee' column holds the
    placebo statistic P(label 1 first)."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        if r.get("record", "pair") == "pair":
            groups.setdefault(group_name(r), []).append(r)
    rows = []
    for name, recs in groups.items():
        outs = [pair_outcome(r) for r in recs]
        landed = [o for o in outs if o is not None]
        same = [o for o in landed if o["same_slot"]]
        placebo = recs[0].get("hi_label") is None
        n = len(same)
        k_first = sum(o["first_sent_first"] for o in same)
        k_hi = sum(o["label1_first"] if placebo else o["hi_first"] for o in same)
        row = {"group": name, "condition": recs[0]["condition"], "placebo_label": placebo, "cfg": recs[0]["cfg"],
               "n_pairs": len(recs), "n_landed": len(landed), "n_same_slot": n,
               "k_first_sent": k_first, "k_hi": k_hi,
               "ci_first_sent": wilson_ci(k_first, n), "ci_hi": wilson_ci(k_hi, n),
               "p_first_sent": binom_two_sided_p(k_first, n), "p_hi": binom_two_sided_p(k_hi, n)}
        rows.append(row)
    order = {"A": 0, "B": 1, "C": 2}
    rows.sort(key=lambda r: (order.get(r["condition"], 3),
                             (lambda c: (c.k, c.filler_sigs, c.filler_cu_limit, c.lead_ms, c.cu_limit))(cfg_from_dict(r["cfg"]))))
    return rows


def _fmt_stat(k: int, n: int, ci: tuple[float, float], p: float) -> str:
    if n == 0:
        return "n/a (no same-slot pairs)"
    return f"{k}/{n} = {k / n:.3f}  Wilson95 [{ci[0]:.3f}, {ci[1]:.3f}]  exact p = {p:.2e}"


def format_summary(rows: list[dict[str, Any]]) -> str:
    lines = []
    for r in rows:
        hi_name = "label-1-first (placebo)" if r["placebo_label"] else "higher-fee-first"
        lines.append(f"{r['group']}")
        lines.append(f"    pairs={r['n_pairs']}  landed={r['n_landed']}  same-slot={r['n_same_slot']}")
        lines.append("    first-sent-first : " + _fmt_stat(r["k_first_sent"], r["n_same_slot"], r["ci_first_sent"], r["p_first_sent"]))
        lines.append(f"    {hi_name:<17}: " + _fmt_stat(r["k_hi"], r["n_same_slot"], r["ci_hi"], r["p_hi"]))
    return "\n".join(lines)


def format_markdown(rows: list[dict[str, Any]]) -> str:
    def cell(k: int, n: int, ci: tuple[float, float], p: float) -> str:
        return "n/a" if n == 0 else f"{k}/{n} ({k / n:.3f}) [{ci[0]:.3f}, {ci[1]:.3f}] p={p:.1e}"
    out = ["| group | pairs | landed | same-slot | first-sent-first | higher-fee-first (C: label-1-first) |",
           "|---|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['group']} | {r['n_pairs']} | {r['n_landed']} | {r['n_same_slot']} | "
                   f"{cell(r['k_first_sent'], r['n_same_slot'], r['ci_first_sent'], r['p_first_sent'])} | "
                   f"{cell(r['k_hi'], r['n_same_slot'], r['ci_hi'], r['p_hi'])} |")
    return "\n".join(out)


def pick_best_sweep(rows: list[dict[str, Any]], min_same_frac: float = 0.5) -> dict[str, Any] | None:
    """Sweep row with the highest Wilson lower bound of higher-fee-first (needs enough same-slot pairs)."""
    ok = [r for r in rows if r["condition"] == "B-sweep" and r["n_pairs"] and r["n_same_slot"] >= min_same_frac * r["n_pairs"]]
    # highest Wilson lower bound; ties go to the simpler configuration (fewer fillers, shorter lead)
    return max(ok, key=lambda r: (round(r["ci_hi"][0], 6), -cfg_from_dict(r["cfg"]).k, -cfg_from_dict(r["cfg"]).lead_ms), default=None)


# --------------------------------------------------------------------------------------------
# Transactions
# --------------------------------------------------------------------------------------------
ED25519_PROGRAM = Pubkey.from_string("Ed25519SigVerify111111111111111111111111111")


def ed25519_burn_ix(kp: Keypair, n: int) -> Instruction:
    """One ed25519 precompile instruction with n entries that all point at the same valid
    (signature, pubkey, message) triple inside the instruction data. The validator verifies it n
    times, which makes the transaction slow to execute without needing any custom program."""
    msg = b"itb-calibration-filler"
    sig, pub = bytes(kp.sign_message(msg)), bytes(kp.pubkey())
    pub_off = 2 + 14 * n
    sig_off, msg_off = pub_off + 32, pub_off + 32 + 64
    entry = struct.pack("<7H", sig_off, 0xFFFF, pub_off, 0xFFFF, msg_off, len(msg), 0xFFFF)
    return Instruction(ED25519_PROGRAM, bytes([n, 0]) + entry * n + pub + sig + msg, [])


def build_tx(payer: Keypair, blockhash: Hash, *, cu_limit: int, cu_price: int, w: Pubkey,
             burn_sigs: int = 0) -> tuple[str, bytes]:
    """Priority fee + a 0-lamport system transfer payer -> w. `w` is locked writable by the tx, so
    two txs with the same `w` conflict; a tx with its own private `w` conflicts with nobody."""
    ixs = [set_compute_unit_limit(cu_limit), set_compute_unit_price(cu_price),
           transfer(TransferParams(from_pubkey=payer.pubkey(), to_pubkey=w, lamports=0))]
    if burn_sigs:
        ixs.append(ed25519_burn_ix(payer, burn_sigs))
    tx = Transaction([payer], Message(ixs, payer.pubkey()), blockhash)
    return str(tx.signatures[0]), bytes(tx)


def send_rpc(rpc: Rpc, wire: bytes) -> str:
    return rpc.call("sendTransaction", [base64.b64encode(wire).decode(),
                                        {"encoding": "base64", "skipPreflight": True, "maxRetries": 0}])


def wait_statuses(rpc: Rpc, sigs: list[str], timeout_s: float) -> dict[str, dict[str, Any]]:
    deadline = time.monotonic() + timeout_s
    got: dict[str, dict[str, Any]] = {}
    while True:
        pending = [s for s in sigs if s not in got]
        if not pending:
            return got
        for chunk in (pending[i:i + 200] for i in range(0, len(pending), 200)):
            res = rpc.call("getSignatureStatuses", [chunk, {"searchTransactionHistory": False}])["value"]
            for s, st in zip(chunk, res):
                if st and st.get("confirmationStatus") in ("confirmed", "finalized"):
                    got[s] = st
        if time.monotonic() > deadline:
            return got
        time.sleep(0.1)


def latest_blockhash(rpc: Rpc) -> Hash:
    return Hash.from_string(rpc.call("getLatestBlockhash", [{"commitment": "confirmed"}])["value"]["blockhash"])


def fund(rpc: Rpc, master: Keypair, dests: list[Pubkey], lamports: int, chunk: int = 20) -> None:
    sigs = []
    bh = latest_blockhash(rpc)
    for i in range(0, len(dests), chunk):
        ixs = [transfer(TransferParams(from_pubkey=master.pubkey(), to_pubkey=d, lamports=lamports)) for d in dests[i:i + chunk]]
        tx = Transaction([master], Message(ixs, master.pubkey()), bh)
        rpc.call("sendTransaction", [base64.b64encode(bytes(tx)).decode(), {"encoding": "base64", "skipPreflight": True}])
        sigs.append(str(tx.signatures[0]))
        time.sleep(0.01)
    got = wait_statuses(rpc, sigs, 60)
    bad = [s for s in sigs if s not in got or got[s].get("err")]
    if bad:
        raise SystemExit(f"funding failed for {len(bad)} of {len(sigs)} funding transactions")


# --------------------------------------------------------------------------------------------
# Direct QUIC injection into the local TPU (aioquic imported lazily)
# --------------------------------------------------------------------------------------------
class TpuClient:
    """ONE QUIC connection to the TPU (ALPN solana-tpu, self-signed Ed25519 client certificate),
    one unidirectional stream per transaction. IPv4 socket (aioquic's connect() binds IPv6)."""

    def __init__(self, host: str, port: int):
        self.addr = (host, port)
        self.protocol = None
        self.terminated = None
        self.connects = 0
        self._ka: asyncio.Task | None = None
        self._cert = None

    def _make_cert(self):
        from cryptography import x509
        from cryptography.hazmat.primitives.asymmetric import ed25519
        from cryptography.x509.oid import NameOID
        key = ed25519.Ed25519PrivateKey.generate()
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "itb-calibration")])
        now = dt.datetime.now(dt.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
                .not_valid_after(now + dt.timedelta(days=30)).sign(key, None))
        return cert, key

    async def connect(self) -> None:
        from aioquic.asyncio.protocol import QuicConnectionProtocol
        from aioquic.quic.configuration import QuicConfiguration
        from aioquic.quic.connection import QuicConnection
        from aioquic.quic.events import ConnectionTerminated

        client = self

        class Proto(QuicConnectionProtocol):
            def quic_event_received(self, event):  # noqa: ANN001
                if isinstance(event, ConnectionTerminated):
                    client.terminated = event

        if self._cert is None:
            self._cert = self._make_cert()
        cfg = QuicConfiguration(is_client=True, alpn_protocols=["solana-tpu"], verify_mode=ssl.CERT_NONE,
                                server_name="connect", idle_timeout=30.0)
        cfg.certificate, cfg.private_key = self._cert
        loop = asyncio.get_running_loop()
        self.terminated = None
        quic = QuicConnection(configuration=cfg)
        _, proto = await loop.create_datagram_endpoint(lambda: Proto(quic), local_addr=("0.0.0.0", 0),
                                                       family=socket.AF_INET)
        proto.connect(self.addr)
        await asyncio.wait_for(proto.wait_connected(), 10)
        self.protocol = proto
        self.connects += 1
        if self._ka is None or self._ka.done():
            self._ka = asyncio.create_task(self._keepalive())

    async def _keepalive(self) -> None:
        while True:
            await asyncio.sleep(0.5)
            p = self.protocol
            if p is not None and self.terminated is None:
                try:
                    p._quic.send_ping(int(time.monotonic_ns()) & 0x3FFFFFFF)
                    p.transmit()
                except Exception:  # noqa: BLE001 - connection state errors are handled by ensure()
                    pass

    async def ensure(self) -> None:
        if self.protocol is None or self.terminated is not None:
            await self.connect()

    def write(self, wire: bytes) -> int:
        q = self.protocol._quic
        sid = q.get_next_available_stream_id(is_unidirectional=True)
        q.send_stream_data(sid, wire, end_stream=True)
        return sid

    def flush(self) -> int:
        t = time.time_ns()
        self.protocol.transmit()
        return t

    async def close(self) -> None:
        if self._ka:
            self._ka.cancel()
        if self.protocol is not None and self.terminated is None:
            self.protocol.close()
            await asyncio.sleep(0.05)


# --------------------------------------------------------------------------------------------
# Pair execution
# --------------------------------------------------------------------------------------------
@dataclass
class Plan:
    condition: str                 # A | B | C | B-sweep
    idx: int
    cfg: Cfg
    hi_label: int | None           # label with the higher fee; None = equal fees (placebo)
    first_label: int               # label written/sent first
    payers: dict[int, Keypair] = field(repr=False, default_factory=dict)
    fillers: list[Keypair] = field(repr=False, default_factory=list)


def payer_count(p: Plan) -> int:
    return 2 + len(p.fillers)


def make_plans(rng: random.Random, spec: list[tuple[str, int, Cfg]]) -> list[Plan]:
    """spec = [(condition, n_pairs, cfg)]. Fee contrast and send position are two independent coins;
    the plan list is shuffled so conditions are interleaved in time."""
    plans = []
    for cond, n, cfg in spec:
        for i in range(n):
            hi = None if cond == "C" else rng.choice((1, 2))
            first = rng.choice((1, 2))
            plans.append(Plan(cond, i, cfg, hi, first))
    rng.shuffle(plans)
    for p in plans:
        p.payers = {1: Keypair(), 2: Keypair()}
        p.fillers = [Keypair() for _ in range(p.cfg.k)] if p.cfg.transport == "quic" else []
    return plans


def price_of(p: Plan, label: int) -> int:
    if p.hi_label is None:
        return p.cfg.price_hi          # equal fees
    return p.cfg.price_hi if label == p.hi_label else p.cfg.price_lo


async def run_pair(rpc: Rpc, tpu: TpuClient | None, p: Plan, run_id: str, seed: int, settle_s: float) -> dict[str, Any]:
    cfg = p.cfg
    bh = await asyncio.to_thread(latest_blockhash, rpc)
    w = Keypair().pubkey()                       # shared writable account of THIS pair (B, C)
    txs: dict[int, dict[str, Any]] = {}
    wires: dict[int, bytes] = {}
    for lab in (1, 2):
        if cfg.transport == "quic":
            sig, wire = build_tx(p.payers[lab], bh, cu_limit=cfg.cu_limit, cu_price=price_of(p, lab), w=w)
        else:  # A: the live experiment's probe tx (memo, own payer, no shared writable account)
            bt = build_probe_tx(p.payers[lab], str(bh), cu_limit=cfg.cu_limit, cu_price=price_of(p, lab),
                                memo=f"cal-{run_id}-{p.condition}{p.idx}-{lab}")
            sig, wire = bt.signature, base64.b64decode(bt.wire_b64)
        wires[lab] = wire
        txs[lab] = {"label": lab, "sig": sig, "payer": str(p.payers[lab].pubkey()), "cu_limit": cfg.cu_limit,
                    "cu_price": price_of(p, lab), "send_pos": 0 if lab == p.first_label else 1,
                    "t_send_ns": None, "t_ack_ns": None, "slot": None, "index": None, "err": None}
    order = [p.first_label, 3 - p.first_label]
    filler_sigs: list[str] = []
    send_error = None
    try:
        if cfg.transport == "rpc":
            t_first = time.monotonic()
            for pos, lab in enumerate(order):
                target = t_first + pos * cfg.gap_ms / 1000.0
                delay = target - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                txs[lab]["t_send_ns"] = time.time_ns()
                send_rpc(rpc, wires[lab])
                txs[lab]["t_ack_ns"] = time.time_ns()
        else:
            await tpu.ensure()
            for fp in p.fillers:
                fsig, fwire = build_tx(fp, bh, cu_limit=cfg.filler_cu_limit or cfg.cu_limit, cu_price=cfg.filler_price,
                                       w=w, burn_sigs=cfg.filler_sigs)
                tpu.write(fwire)
                filler_sigs.append(fsig)
            if cfg.lead_ms and p.fillers:
                tpu.flush()
                await asyncio.sleep(cfg.lead_ms / 1000.0)
            for lab in order:                                  # back-to-back writes, one flush
                txs[lab]["stream_id"] = tpu.write(wires[lab])
            t = tpu.flush()
            for lab in order:
                txs[lab]["t_send_ns"] = t
    except (RpcError, TransportError, ValueError, OSError, asyncio.TimeoutError) as e:
        send_error = f"{type(e).__name__}: {str(e)[:120]}"

    sigs = [txs[1]["sig"], txs[2]["sig"]]
    got = await asyncio.to_thread(wait_statuses, rpc, sigs, settle_s) if send_error is None else {}
    filler_got: dict[str, dict[str, Any]] = {}
    if filler_sigs:                                            # let fillers drain so pairs do not overlap
        filler_got = await asyncio.to_thread(wait_statuses, rpc, filler_sigs, 5.0)
    for lab in (1, 2):
        st = got.get(txs[lab]["sig"])
        if st:
            txs[lab]["slot"] = st["slot"]
            txs[lab]["err"] = st.get("err")
    rec: dict[str, Any] = {
        "record": "pair", "schema": SCHEMA, "run_id": run_id, "seed": seed, "condition": p.condition,
        "pair": p.idx, "cfg": asdict(cfg), "hi_label": p.hi_label, "first_label": p.first_label,
        "send_order": order, "filler_count": len(p.fillers), "filler_landed": len(filler_got),
        "filler_failed": sum(1 for st in filler_got.values() if st.get("err")), "w": str(w) if cfg.transport == "quic" else None,
        "send_error": send_error, "txs": [txs[1], txs[2]], "slot": None, "leader": None,
    }
    return rec


def attach_block_positions(rpc: Rpc, rec: dict[str, Any], cache: dict[int, dict[str, Any] | None]) -> None:
    """Fill index (position in getBlock signatures) and block producer (Fee reward) per tx."""
    for t in rec["txs"]:
        slot = t["slot"]
        if slot is None:
            continue
        if slot not in cache:
            info = None
            for _ in range(20):
                try:
                    info = block_info(rpc, slot, "confirmed")
                    break
                except RpcError as e:
                    if e.code not in (-32004, -32014):
                        raise
                    time.sleep(0.25)
            cache[slot] = info
        info = cache[slot]
        if info is None:
            continue
        sigs = info["signatures"]
        t["index"] = sigs.index(t["sig"]) if t["sig"] in sigs else None
        t["leader"] = info["leader"]
        t["block_txs"] = len(sigs)
    s1, s2 = (t["slot"] for t in rec["txs"])
    if s1 is not None and s1 == s2:
        rec["slot"] = s1
        rec["leader"] = rec["txs"][0].get("leader")


# --------------------------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------------------------
def check_local(url: str, what: str) -> None:
    host = urllib.parse.urlparse(url if "//" in url else "//" + url).hostname
    if host not in LOOPBACK:
        raise SystemExit(f"refusing non-local {what}: this script only talks to a local test validator")


# K fillers, pair CU limit, filler CU limit (0 = same), ed25519 entries per filler, lead (ms) before the pair.
DEFAULT_SPECS = ";".join([
    "0,200000,0,0,0",            # bare pair, no fillers
    "8,200000,0,0,0",            # plain cheap fillers
    "32,2000,0,0,0",
    "4,2000,1400000,0,1",        # expensive (1.4M CU limit) but fast fillers
    "1,2000,1400000,50,1",       # expensive and slow fillers (50 ed25519 verifications each)
    "2,2000,1400000,50,1",
    "4,2000,1400000,50,0",
    "4,2000,1400000,50,1",
    "4,200000,1400000,50,1",
    "4,2000,1400000,50,3",
    "8,2000,1400000,50,2",
    "4,2000,1400000,25,1",
])


def parse_specs(text: str, price_lo: int, price_hi: int) -> list[Cfg]:
    out = []
    for spec in (x.strip() for x in text.split(";") if x.strip()):
        k, cu, fcu, fsig, lead = spec.split(",")
        out.append(Cfg(k=int(k), cu_limit=int(cu), filler_cu_limit=int(fcu), filler_sigs=int(fsig),
                       lead_ms=float(lead), price_lo=price_lo, price_hi=price_hi))
    return out


async def execute(args, rpc: Rpc, tpu: TpuClient | None, plans: list[Plan], out, run_id: str, master: Keypair, tag: str) -> list[dict[str, Any]]:
    need = sorted({id(k): k for p in plans for k in [*p.payers.values(), *p.fillers]}.values(), key=lambda k: str(k.pubkey()))
    if need:
        print(f"[{tag}] funding {len(need)} fresh payers", flush=True)
        await asyncio.to_thread(fund, rpc, master, [k.pubkey() for k in need], args.payer_lamports)
    recs, cache = [], {}
    t0 = time.monotonic()
    for i, p in enumerate(plans, 1):
        rec = await run_pair(rpc, tpu, p, run_id, args.seed, args.settle_s)
        await asyncio.to_thread(attach_block_positions, rpc, rec, cache)
        out.write(json.dumps(rec) + "\n")
        out.flush()
        recs.append(rec)
        if i % 10 == 0 or i == len(plans):
            print(f"[{tag}] {i}/{len(plans)} pairs done ({time.monotonic() - t0:.0f}s)", flush=True)
    return recs


async def amain(args) -> int:
    check_local(args.rpc, "--rpc")
    rpc = Rpc(args.rpc, rate_per_s=5000.0, burst=5000.0, timeout=20.0, retries=1)
    conds = [c.strip().upper() for c in args.conditions.split(",") if c.strip()]
    if os.path.exists(args.out) and not args.overwrite:
        raise SystemExit(f"{args.out} exists (use --overwrite)")
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    rng = random.Random(args.seed)
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-s{args.seed}"
    version = rpc.call("getVersion")
    quic_needed = any(c in ("B", "C") for c in conds)
    tpu = None
    if quic_needed:
        host_port = args.tpu
        if not host_port:
            nodes = rpc.call("getClusterNodes")
            host_port = next((n["tpuQuic"] for n in nodes if n.get("tpuQuic")), None)
        if not host_port:
            raise SystemExit("no tpuQuic address (pass --tpu HOST:PORT)")
        check_local(host_port, "TPU address")
        h, _, pt = host_port.rpartition(":")
        tpu = TpuClient(h, int(pt))
        await tpu.connect()
    print(f"run {run_id}  validator {version}  conditions {conds}", flush=True)

    master = Keypair()
    # Fund the master generously: every payer gets payer_lamports, plus slack for funding fees.
    # (upper bound computed from the plans, see below)
    summaries: list[dict[str, Any]] = []
    all_recs: list[dict[str, Any]] = []
    with open(args.out, "w", encoding="utf-8") as out:
        out.write(json.dumps({"record": "meta", "schema": SCHEMA, "run_id": run_id, "seed": args.seed,
                              "validator": version, "pairs": args.pairs, "argv": sys.argv[1:], "sweep_specs": args.sweep_specs,
                              "utc": dt.datetime.now(dt.timezone.utc).isoformat()}) + "\n")

        async def airdrop(lamports: int) -> None:
            sig = rpc.call("requestAirdrop", [str(master.pubkey()), lamports])
            got = await asyncio.to_thread(wait_statuses, rpc, [sig], 30)
            if sig not in got:
                raise SystemExit("airdrop not confirmed (is the faucet running?)")

        # ---- B configuration: sweep, then choose
        b_cfg = Cfg(k=args.b_k, cu_limit=args.b_cu_limit, price_lo=args.price_lo, price_hi=args.price_hi,
                    lead_ms=args.b_lead_ms, filler_cu_limit=args.b_filler_cu, filler_sigs=args.b_filler_sigs)
        sweep_note = None
        b_reliable = True
        if "B" in conds or "C" in conds:
            if args.sweep_pairs > 0:
                grid = parse_specs(args.sweep_specs, args.price_lo, args.price_hi)
                plans = make_plans(rng, [("B-sweep", args.sweep_pairs, c) for c in grid])
                n_pay = sum(payer_count(p) for p in plans)
                await airdrop(int((n_pay * args.payer_lamports + 10**9) ))
                print(f"sweep: {len(grid)} configurations x {args.sweep_pairs} pairs", flush=True)
                sweep_recs = await execute(args, rpc, tpu, plans, out, run_id, master, "sweep")
                all_recs += sweep_recs
                rows = summarize(sweep_recs)
                best = pick_best_sweep(rows)
                if best is not None:
                    b_cfg = cfg_from_dict(best["cfg"])
                    b_reliable = best["ci_hi"][0] >= args.reliable
                    sweep_note = (f"selected B configuration: {b_cfg.key()} (Wilson lower bound of higher-fee-first "
                                  f"{best['ci_hi'][0]:.3f} on {best['n_same_slot']} same-slot sweep pairs; "
                                  f"{'reliable' if b_reliable else 'NOT reliable'} at threshold {args.reliable})")
                else:
                    b_reliable = False
                    sweep_note = "no sweep configuration produced enough same-slot pairs; using the default B configuration"
                print(sweep_note, flush=True)
        # ---- final conditions
        spec: list[tuple[str, int, Cfg]] = []
        a_cfg = Cfg(transport="rpc", k=0, cu_limit=args.b_cu_limit, price_lo=args.price_lo, price_hi=args.price_hi, gap_ms=args.gap_ms)
        if "A" in conds:
            spec.append(("A", args.pairs, a_cfg))
        if "B" in conds:
            spec.append(("B", args.pairs, b_cfg))
        if "C" in conds:   # placebo "like B", or "like A" when no B configuration was reliable
            spec.append(("C", args.pairs, b_cfg if b_reliable else a_cfg))
        plans = make_plans(rng, spec)
        n_pay = sum(payer_count(p) for p in plans)
        await airdrop(int(n_pay * args.payer_lamports + 10**9))
        final_recs = await execute(args, rpc, tpu, plans, out, run_id, master, "final")
        all_recs += final_recs
    if tpu is not None:
        await tpu.close()

    rows = summarize(all_recs)
    sweep_rows = [r for r in rows if r["condition"] == "B-sweep"]
    final_rows = [r for r in rows if r["condition"] != "B-sweep"]
    print("\n=== B configuration sweep (every configuration tried) ===")
    print(format_summary(sweep_rows) if sweep_rows else "(sweep skipped)")
    if sweep_note:
        print(sweep_note)
    print("\n=== Final conditions ===")
    print(format_summary(final_rows))
    print("\nA configuration:", a_cfg.key(), "| B configuration:", b_cfg.key(),
          "| C configuration:", (b_cfg if b_reliable else a_cfg).key())
    print("\n" + format_markdown(rows))
    errs = [r for r in all_recs if r.get("send_error")]
    unl = sum(1 for r in all_recs for t in r["txs"] if t["slot"] is None)
    fails = sum(1 for r in all_recs for t in r["txs"] if t["err"])
    print(f"\nsend errors: {len(errs)} pairs | txs not landed: {unl} | txs landed with an error: {fails} | QUIC connects: {tpu.connects if tpu else 0}")
    print(f"records written to {args.out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Localnet calibration of the ordering analysis (local test validator only).")
    ap.add_argument("--rpc", default="http://127.0.0.1:8899")
    ap.add_argument("--tpu", default=None, help="TPU QUIC HOST:PORT (default: tpuQuic from getClusterNodes)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--pairs", type=int, default=60, help="pairs per final condition")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--conditions", default="A,B,C")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--gap-ms", type=float, default=50.0, help="condition A: gap between the two RPC sends")
    ap.add_argument("--price-lo", type=int, default=LO_PRICE)
    ap.add_argument("--price-hi", type=int, default=HI_PRICE)
    ap.add_argument("--b-k", type=int, default=0, help="B/C fillers if the sweep is skipped")
    ap.add_argument("--b-cu-limit", type=int, default=200_000, help="CU limit of A and (without sweep) of B/C")
    ap.add_argument("--b-lead-ms", type=float, default=0.0)
    ap.add_argument("--b-filler-cu", type=int, default=0)
    ap.add_argument("--b-filler-sigs", type=int, default=0)
    ap.add_argument("--sweep-pairs", type=int, default=30, help="pairs per sweep configuration (0 = no sweep)")
    ap.add_argument("--sweep-specs", default=DEFAULT_SPECS,
                    help="';'-separated configurations 'K,cu_limit,filler_cu_limit,filler_sigs,lead_ms'")
    ap.add_argument("--reliable", type=float, default=0.8,
                    help="a B configuration is reliable if the Wilson lower bound of higher-fee-first is >= this")
    ap.add_argument("--payer-lamports", type=int, default=5_000_000)
    ap.add_argument("--settle-s", type=float, default=20.0, help="max wait for a pair to be confirmed")
    args = ap.parse_args(argv)
    return asyncio.run(amain(args))


if __name__ == "__main__":
    sys.exit(main())
