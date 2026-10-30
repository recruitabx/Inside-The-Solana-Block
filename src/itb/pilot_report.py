"""`itb pilot-report`: operational metrics of the mainnet pilot, and nothing else.

Reads the pilot send logs (`data/raw/*pilot*.sent.jsonl`, probes with phase "pilot") and the matching
landing logs written by `itb collect`, and prints per target and pooled: transaction landing rate,
both-landed rate, same-slot rate, target-hit rate, usable fraction u, HTTP 429 and error rates (the
first and second request of arm S separately), mean landing slot offset, and the reconciliation of the
spend ledger with the on-chain fees. It prints the preregistered tau0 choice (docs/PREREGISTRATION.md
section 6): the earliest (most negative) tau0 whose pooled u is at least 0.40, else the tau0 with the
highest u.

It also simulates both probe templates (simulateTransaction, unsigned, funding wallet public key as payer;
itb.simulate) and requires unitsConsumed <= 700 and loadedAccountsDataSize <= 4096 (`--no-simulate` skips it).

It never reads or prints the order of transactions inside a block (no block index, no "which landed
first"), so looking at it is not an interim look at ordering outcomes.

Definitions (denominators are probes sent unless stated):
  landing rate        landed transactions / transactions sent
  both-landed rate    probes with both transactions landed
  same-slot rate      probes with both transactions landed in one slot
  target-hit rate     probes with both transactions in one block produced by the target (Fee reward pubkey)
  u (usable)          probes with both transactions in one block produced by the target AND in a slot of the
                      targeted window
  request error       a request whose answer was not "ok" (arm S: first and second request separately; other
                      arms: the single batch request); 429: HTTP 429 or a rate-limit error answer
  slot offset         landing slot minus the first slot of the targeted window, mean over landed transactions
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from collections import defaultdict

from .pairs import load_jsonl
from .simulate import PUBLIC_RPC, funding_pubkey, render as render_simulation, simulate_templates, template_params

U_THRESHOLD = 0.40           # tau0 rule
LANDING_MIN = 0.80           # pilot acceptance criteria (section 10)
RATE_429_MAX = 0.05


def is_429(x) -> bool:
    if isinstance(x, dict):
        return x.get("code") == 429 or "too many requests" in str(x.get("message", "")).lower()
    return isinstance(x, str) and ("HTTP 429" in x or "too many requests" in x.lower())


def _requests(probe: dict) -> list[tuple[str, list]]:
    """(request name, answers) of a probe: arm S has two requests, every other arm one batch."""
    res = probe.get("send_results") or []
    if probe.get("arm") == "S" and len(res) == 2:
        return [("S_first", [res[0]]), ("S_second", [res[1]])]
    return [("batch", list(res))]


def load_pilot(sent_glob: str) -> tuple[list[dict], dict[str, dict]]:
    probes, landed = [], {}
    for path in sorted(glob.glob(sent_glob)):
        probes += [r for r in load_jsonl(path) if r.get("record") == "probe" and r.get("mode") == "live"
                   and r.get("phase") == "pilot" and r.get("send_results")]
        lp = path.replace(".sent.jsonl", ".landed.jsonl")
        if os.path.exists(lp):
            landed.update({r["signature"]: r for r in load_jsonl(lp)})
    return probes, landed


def probe_status(p: dict, landed: dict[str, dict]) -> dict:
    """Operational facts of one probe. Block order (tx_index) is deliberately not read."""
    recs = [landed.get(t["signature"], {}) for t in p["txs"]]
    ok = [r.get("record") == "landed" for r in recs]
    slots = [r.get("slot") for r, o in zip(recs, ok) if o]
    both = all(ok)
    same = both and len(set(slots)) == 1
    hit = same and recs[0].get("leader") == p["target_leader"]
    first = p["window_first_slot"]
    last = p.get("window_last_slot", first + 3)
    return {"n_tx": len(recs), "n_landed": sum(ok), "both": both, "same_slot": same, "target_hit": hit,
            "usable": bool(hit and first <= slots[0] <= last), "offsets": [s - first for s in slots],
            "requests": [(name, any(a != "ok" for a in ans), any(is_429(a) for a in ans)) for name, ans in _requests(p)]}


def _rate(k: int, n: int) -> float | None:
    return k / n if n else None


def metrics(statuses: list[dict]) -> dict:
    n = len(statuses)
    tx = sum(s["n_tx"] for s in statuses)
    offs = [o for s in statuses for o in s["offsets"]]
    req: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])   # name -> requests, errors, 429
    for s in statuses:
        for name, err, r429 in s["requests"]:
            req[name][0] += 1; req[name][1] += int(err); req[name][2] += int(r429)
    return {"probes": n, "tx_sent": tx, "tx_landed": sum(s["n_landed"] for s in statuses),
            "landing_rate": _rate(sum(s["n_landed"] for s in statuses), tx),
            "both_landed": sum(s["both"] for s in statuses), "both_landed_rate": _rate(sum(s["both"] for s in statuses), n),
            "same_slot": sum(s["same_slot"] for s in statuses), "same_slot_rate": _rate(sum(s["same_slot"] for s in statuses), n),
            "target_hit": sum(s["target_hit"] for s in statuses), "target_hit_rate": _rate(sum(s["target_hit"] for s in statuses), n),
            "usable": sum(s["usable"] for s in statuses), "u": _rate(sum(s["usable"] for s in statuses), n),
            "mean_slot_offset": (sum(offs) / len(offs)) if offs else None,
            "requests": {k: {"n": v[0], "errors": v[1], "error_rate": _rate(v[1], v[0]), "http_429": v[2],
                             "rate_429": _rate(v[2], v[0])} for k, v in sorted(req.items())}}


def choose_tau0(by_tau: dict[int, dict], threshold: float = U_THRESHOLD) -> dict:
    """Earliest (most negative) tau0 whose pooled u is at least `threshold`, else the tau0 with the highest u
    (ties: the earliest)."""
    have = {t: m for t, m in by_tau.items() if m["probes"] > 0}
    if not have:
        return {"tau0_ms": None, "rule": "no arm-P pilot probes"}
    ok = sorted(t for t, m in have.items() if m["u"] >= threshold)
    if ok:
        return {"tau0_ms": ok[0], "rule": f"earliest tau0 with pooled u >= {threshold:.2f}", "u": have[ok[0]]["u"]}
    best = max(have, key=lambda t: (have[t]["u"], -t))
    return {"tau0_ms": best, "rule": f"no tau0 reaches u >= {threshold:.2f}: tau0 with the highest u", "u": have[best]["u"]}


def reconcile_ledger(ledger_path: str, probes: list[dict], landed: dict[str, dict]) -> dict:
    """Sum of settled actual fees vs sum of meta.fee of landed pilot transactions; open reservations."""
    if not os.path.exists(ledger_path):
        return {"ledger_found": False}
    entries: dict[str, dict] = {}
    for r in load_jsonl(ledger_path):
        e = entries.setdefault(r["sig"], {})
        e[r["kind"]] = r
    sigs = [t["signature"] for p in probes for t in p["txs"]]
    pil = [s for s in sigs if s in entries]
    settled = sum(entries[s]["settle"]["actual_fee"] for s in pil if "settle" in entries[s])
    onchain = sum(int(landed[s].get("fee") or 0) for s in sigs if landed.get(s, {}).get("record") == "landed")
    open_ = [s for s in pil if "settle" not in entries[s] and "release" not in entries[s]]
    open_all = [s for s, e in entries.items() if "settle" not in e and "release" not in e]
    return {"ledger_found": True, "pilot_tx_in_ledger": len(pil), "pilot_tx_sent": len(sigs),
            "settled_actual_fee_sum": settled, "onchain_meta_fee_sum_landed": onchain, "exact_match": settled == onchain,
            "landed_not_settled": sum(1 for s in sigs if landed.get(s, {}).get("record") == "landed" and s in entries and "settle" not in entries[s]),
            "open_reservations_pilot": len(open_), "open_reservations_pilot_max_fee": sum(entries[s]["reserve"]["max_fee"] for s in open_),
            "open_reservations_ledger": len(open_all)}


def build_report(sent_glob: str, ledger_path: str) -> dict:
    probes, landed = load_pilot(sent_glob)
    st = [(p, probe_status(p, landed)) for p in probes]
    label = lambda p: f"{p.get('target_role') or '?'} {p['target_leader'][:6]}"
    per_target = {}
    for name in sorted({label(p) for p, _ in st}):
        per_target[name] = {arm: metrics([s for p, s in st if label(p) == name and p.get("arm") == arm]) for arm in ("P", "S")}
        per_target[name]["all"] = metrics([s for p, s in st if label(p) == name])
    pooled = {"P": metrics([s for p, s in st if p.get("arm") == "P"]), "S": metrics([s for p, s in st if p.get("arm") == "S"]),
              "all": metrics([s for _, s in st])}
    taus = sorted({p.get("tau0_ms") for p, _ in st if p.get("arm") == "P" and p.get("tau0_ms") is not None})
    by_tau = {t: metrics([s for p, s in st if p.get("arm") == "P" and p.get("tau0_ms") == t]) for t in taus}
    choice = choose_tau0(by_tau)
    u_p = pooled["P"]["u"]
    ledger = reconcile_ledger(ledger_path, probes, landed)
    s2 = pooled["S"]["requests"].get("S_second", {})
    criteria = {
        "landing_rate_ge_0.80": None if pooled["all"]["landing_rate"] is None else pooled["all"]["landing_rate"] >= LANDING_MIN,
        "http_429_rate_lt_0.05": None if not pooled["all"]["requests"] else
        all((v["rate_429"] or 0) < RATE_429_MAX for k, v in pooled["all"]["requests"].items() if k != "S_second"),
        "arm_S_second_request_429_rate_lt_0.05": None if not s2 else (s2["rate_429"] or 0) < RATE_429_MAX,
        "ledger_spend_equals_meta_fee": ledger.get("exact_match") if ledger.get("ledger_found") else None,
        "pooled_u_ge_0.40": None if u_p is None else u_p >= U_THRESHOLD}
    return {"sent_glob": sent_glob, "n_probes": len(probes), "per_target": per_target, "pooled": pooled,
            "u_by_tau0_arm_P": by_tau, "tau0_choice": choice, "u_pooled_arm_P_all_tau0": u_p,
            "u_arm_P_at_chosen_tau0": by_tau.get(choice["tau0_ms"], {}).get("u") if choice["tau0_ms"] is not None else None,
            "ledger": ledger, "criteria": criteria}


def _f(x, pct=True) -> str:
    if x is None:
        return "  n/a"
    return f"{100 * x:5.1f}%" if pct else f"{x:6.2f}"


def _row(name: str, m: dict) -> str:
    rq = m["requests"]
    b = rq.get("batch") or {}
    s1, s2 = rq.get("S_first") or {}, rq.get("S_second") or {}
    return (f"{name:<22s} {m['probes']:4d} {_f(m['landing_rate'])} {_f(m['both_landed_rate'])} {_f(m['same_slot_rate'])} "
            f"{_f(m['target_hit_rate'])} {_f(m['u'])} {_f(m['mean_slot_offset'], False)}  "
            f"{_f(b.get('rate_429'))}/{_f(b.get('error_rate'))}  {_f(s1.get('rate_429'))}/{_f(s1.get('error_rate'))}  "
            f"{_f(s2.get('rate_429'))}/{_f(s2.get('error_rate'))}")


def render(rep: dict) -> str:
    L = [f"pilot report (operational metrics only; no ordering outcomes): {rep['n_probes']} pilot probes, {rep['sent_glob']}", ""]
    head = (f"{'':<22s} {'n':>4s} {'land tx':>6s} {'both':>6s} {'1 slot':>6s} {'tgt hit':>6s} {'u':>6s} {'offset':>6s}  "
            f"{'P 429/err':>13s}  {'S1 429/err':>13s}  {'S2 429/err':>13s}")
    L += ["per target and pooled, arms P and S together (offset: mean landing slot - window first slot, in slots)", head]
    for name, arms in rep["per_target"].items():
        L.append(_row(name, arms["all"]))
    L += [_row("POOLED all arms", rep["pooled"]["all"]), _row("POOLED arm P", rep["pooled"]["P"]), _row("POOLED arm S", rep["pooled"]["S"]), ""]
    L += ["usable fraction u per tau0, arm P, pooled across targets", f"{'tau0 ms':>8s} {'probes':>7s} {'usable':>7s} {'u':>7s}"]
    for t, m in rep["u_by_tau0_arm_P"].items():
        L.append(f"{t:8d} {m['probes']:7d} {m['usable']:7d} {_f(m['u']):>7s}")
    c = rep["tau0_choice"]
    L += ["", f"tau0 CHOICE (preregistered rule): {c['tau0_ms']} ms; rule applied: {c['rule']}",
          f"u pooled over arm P (all tau0): {_f(rep['u_pooled_arm_P_all_tau0'])}; u of arm P at the chosen tau0: {_f(rep['u_arm_P_at_chosen_tau0'])}", ""]
    lg = rep["ledger"]
    if lg.get("ledger_found"):
        L += ["ledger reconciliation (pilot transactions)",
              f"  transactions in ledger {lg['pilot_tx_in_ledger']} of {lg['pilot_tx_sent']} sent; "
              f"sum of settled actual fees {lg['settled_actual_fee_sum']} lamports; sum of meta.fee of landed {lg['onchain_meta_fee_sum_landed']} lamports; "
              f"exact match: {lg['exact_match']}",
              f"  landed but not yet settled: {lg['landed_not_settled']}; open reservations: pilot {lg['open_reservations_pilot']} "
              f"({lg['open_reservations_pilot_max_fee']} lamports at worst case), whole ledger {lg['open_reservations_ledger']}"]
    else:
        L.append("ledger reconciliation: ledger file not found")
    if "templates_simulation" in rep:
        L += ["", render_simulation(rep["templates_simulation"])] if rep["templates_simulation"]["templates"] else \
            ["", "simulateTransaction check of the probe templates: FAIL (" + str(rep["templates_simulation"].get("error")) + ")"]
    L += ["", "acceptance criteria (section 10, operational ones only): " + ", ".join(f"{k} = {v}" for k, v in rep["criteria"].items())]
    return "\n".join(L)


def simulate_check(rpc_url: str, payer: str | None = None, plan_path: str = "data/plan.json") -> dict:
    """simulateTransaction check of both templates; a missing public key or an RPC failure is reported, not raised."""
    from .rpc import Rpc
    payer = payer or funding_pubkey()
    if not payer:
        return {"ok": False, "payer": None, "templates": {}, "error": "no funding wallet public key (data/accounts.json, ~/ops/wallet.pub or --payer)"}
    return simulate_templates(Rpc(rpc_url, rate_per_s=2.0, burst=2.0, timeout=30), payer, template_params(plan_path))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="itb pilot-report", description="operational pilot metrics (never ordering outcomes)")
    ap.add_argument("--sent", default="data/raw/*pilot*.sent.jsonl", help="glob of pilot send logs")
    ap.add_argument("--ledger", default="data/ledger/spend.jsonl")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    ap.add_argument("--no-simulate", action="store_true", help="skip the simulateTransaction check of the probe templates")
    ap.add_argument("--payer", default=None, help="payer public key for the template simulation (default: the funding wallet's)")
    ap.add_argument("--rpc", default=os.environ.get("ITB_READ_RPC_URL", PUBLIC_RPC), help="read endpoint for the simulation")
    a = ap.parse_args(argv)
    rep = build_report(a.sent, a.ledger)
    if rep["n_probes"] == 0:
        print(f"no live pilot probes found in {a.sent}")
        return 1
    if not a.no_simulate:
        sim = simulate_check(a.rpc, a.payer)
        rep["templates_simulation"] = sim
        rep["criteria"]["templates_simulate_units_le_700_loaded_le_4096"] = sim["ok"]
    print(json.dumps(rep, indent=1, sort_keys=True, default=str) if a.json else render(rep))
    return 0
