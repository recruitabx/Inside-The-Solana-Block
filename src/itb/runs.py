"""`itb runs`: the operational summary of every run, for the report. Counts and fees only.

Reads data/raw/*.sent.jsonl (run_start, probe and run_end records), data/raw/*.landed.jsonl and the
spend ledger data/ledger/spend.jsonl, and writes results/runs.md and results/runs.csv:
one row per run, a totals row per phase and an overall total, plus (markdown) a per-role table of the
main phase against the quotas of data/plan.json.

This module never reads the position of a transaction inside its block and never compares the two
transactions of a pair: from the landing records it takes only the signature, the slot and the block
producer. So it cannot reveal which transaction of a pair landed first, and it may be run while a
measurement is still collecting data (a partly written last line of a file is skipped).

Definitions
  probe sent           a live probe record with a send result (the runner's own count for the quotas)
  transaction sent     a transaction of such a probe, handed to the send endpoint (send_errors counts
                       the ones whose send result was not "ok"; their outcome can still be unknown)
  transaction landed   a transaction with a `landed` record from `itb collect`
  collected            yes | partial | no: whether every sent transaction has a landing record yet
                       (the landing rate of a run that is not fully collected is a lower bound)
  usable probe         both transactions landed in ONE block, produced by the targeted leader, in a
                       slot of the targeted window (all arms; the analysis then applies further
                       conditions per arm and per claim, see itb analyze)
  fees settled         lamports settled in the ledger for the signatures of the run's probe
                       transactions; the anchor transaction is listed separately
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
from datetime import datetime, timezone

PHASE_ORDER = {"pilot": 0, "repilot": 1, "main": 2}
LANDED_KEYS = ("record", "signature", "slot", "leader")      # the only fields taken from a landing record
CSV_FIELDS = ["run_id", "phase", "mode", "start_utc", "end_utc", "git_commit", "probes_sent", "tx_sent", "tx_landed", "landing_rate",
              "usable_probes", "fees_settled_lamports", "anchor_signature", "anchor_fee_lamports", "send_errors", "collected",
              "note", "row_type"]


# ---- reading --------------------------------------------------------------------------------------

def read_jsonl(path: str, keys: tuple[str, ...] | None = None):
    """Records of a JSONL file; a missing file is empty and a line that does not parse (the partly written
    last line of a file that a running process appends to) is skipped. With `keys`, only these fields are kept."""
    try:
        f = open(path, encoding="utf-8")
    except FileNotFoundError:
        return
    with f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict):
                yield rec if keys is None else {k: rec.get(k) for k in keys}


def landing_index(raw_dir: str) -> dict[str, tuple | None]:
    """{signature: (slot, producer) if landed, None if the collector recorded `not_landed`}."""
    out: dict[str, tuple | None] = {}
    for path in sorted(glob.glob(os.path.join(raw_dir, "*.landed.jsonl"))):
        for r in read_jsonl(path, LANDED_KEYS):
            sig = r["signature"]
            if not sig:
                continue
            if r["record"] == "landed":
                out[sig] = (r["slot"], r["leader"])
            elif r["record"] == "not_landed" and sig not in out:
                out[sig] = None
    return out


def settled_fees(ledger_path: str) -> dict[str, int]:
    """{signature: actual fee in lamports} of every settled reservation of the spend ledger (read-only, no lock)."""
    return {r["sig"]: int(r["actual_fee"]) for r in read_jsonl(ledger_path) if r.get("kind") == "settle" and r.get("sig")}


def load_runs(raw_dir: str) -> list[dict]:
    """One dict per send log (synthetic files are skipped): run_start / run_end records and the probe records."""
    runs = []
    for path in sorted(glob.glob(os.path.join(raw_dir, "*.sent.jsonl"))):
        base = os.path.basename(path)[: -len(".sent.jsonl")]
        if base.startswith("synthetic"):
            continue
        run = {"file_run_id": base, "start": None, "end": None, "probes": []}
        for r in read_jsonl(path):
            if r.get("record") == "run_start":
                run["start"] = r
            elif r.get("record") == "run_end":
                run["end"] = r
            elif r.get("record") == "probe":
                run["probes"].append(r)
        runs.append(run)
    return runs


# ---- one run --------------------------------------------------------------------------------------

def iso_utc(t) -> str:
    return "" if t is None else datetime.fromtimestamp(float(t), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _id_time(run_id: str) -> float | None:
    """Start time from the run id prefix YYYYmmddTHHMMSSZ, for a run whose send log has no run_start yet."""
    m = re.match(r"(\d{8}T\d{6})Z", run_id)
    return datetime.strptime(m.group(1), "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc).timestamp() if m else None


def _phase(run: dict, run_id: str) -> str:
    if run["start"] and run["start"].get("phase"):
        return str(run["start"]["phase"])
    for p in run["probes"]:
        if p.get("phase"):
            return str(p["phase"])
    m = re.search(r"-(repilot|pilot)-", run_id)
    return m.group(1) if m else "main"


def is_usable(probe: dict, landed: dict) -> bool:
    """Both transactions landed, in one slot of the targeted window, and the block is the targeted leader's."""
    sigs = [t.get("signature") for t in probe.get("txs") or []]
    got = [landed.get(s) for s in sigs]
    if len(sigs) != 2 or any(g is None for g in got):
        return False
    slot = got[0][0]
    if slot is None or got[1][0] != slot or got[0][1] != probe.get("target_leader") or got[1][1] != probe.get("target_leader"):
        return False
    first = probe.get("window_first_slot")
    last = probe.get("window_last_slot", None if first is None else first + 3)
    return first is not None and first <= slot <= last


def sent_probes(run: dict) -> list[dict]:
    """The runner's own definition of a probe that was sent: a live probe record that carries send results."""
    return [p for p in run["probes"] if p.get("mode") == "live" and p.get("send_results")]


def summarize_run(run: dict, landed: dict, fees: dict) -> dict:
    run_id = (run["start"] or {}).get("run_id") or run["file_run_id"]
    start, end = run["start"] or {}, run["end"] or {}
    probes = sent_probes(run)
    sigs = [t["signature"] for p in probes for t in p.get("txs") or [] if t.get("signature")]
    n_known = sum(1 for s in sigs if s in landed)
    anchor = ((start.get("anchor") or {}).get("signature")) or ""
    notes = []
    if not run["start"]:
        notes.append("no run_start record (empty or still starting)")
    elif not run["end"]:
        notes.append("no run_end record (running, or killed)")
    if end.get("error"):
        notes.append(f"ended with {str(end['error']).strip().rstrip(':')}")
    row = {"run_id": run_id, "phase": _phase(run, run_id), "mode": start.get("mode") or "unknown",
           "start_utc": iso_utc(start.get("t") if run["start"] else _id_time(run_id)), "end_utc": iso_utc(end.get("t")),
           "git_commit": start.get("git_commit") or "", "probes_sent": len(probes), "tx_sent": len(sigs),
           "tx_landed": sum(1 for s in sigs if landed.get(s) is not None),
           "usable_probes": sum(is_usable(p, landed) for p in probes),
           "fees_settled_lamports": sum(fees.get(s, 0) for s in sigs),
           "anchor_signature": anchor, "anchor_fee_lamports": fees.get(anchor, "") if anchor else "",
           "send_errors": sum(1 for p in probes for r in p.get("send_results") or [] if r != "ok"),
           "collected": "n/a" if not sigs else "yes" if n_known == len(sigs) else "partial" if n_known else "no",
           "note": "; ".join(notes), "row_type": "run"}
    row["landing_rate"] = rate(row["tx_landed"], row["tx_sent"])
    row["_start_t"] = start.get("t") if run["start"] else _id_time(run_id)
    return row


def rate(num: int, den: int):
    return "" if not den else round(num / den, 4)


# ---- totals and tables ----------------------------------------------------------------------------

SUMS = ("probes_sent", "tx_sent", "tx_landed", "usable_probes", "fees_settled_lamports", "send_errors")


def total_row(rows: list[dict], label: str, row_type: str, phase: str) -> dict:
    t = {k: "" for k in CSV_FIELDS}
    t.update({"run_id": label, "phase": phase, "row_type": row_type, "mode": "", "note": f"{len(rows)} run" + ("" if len(rows) == 1 else "s")})
    for k in SUMS:
        t[k] = sum(r[k] for r in rows)
    t["landing_rate"] = rate(t["tx_landed"], t["tx_sent"])
    starts, ends = [r["start_utc"] for r in rows if r["start_utc"]], [r["end_utc"] for r in rows if r["end_utc"]]
    t["start_utc"], t["end_utc"] = min(starts, default=""), max(ends, default="")
    fees_anchor = [r["anchor_fee_lamports"] for r in rows if r["anchor_fee_lamports"] != ""]
    t["anchor_fee_lamports"] = sum(fees_anchor) if fees_anchor else ""
    states = {r["collected"] for r in rows if r["collected"] != "n/a"}
    t["collected"] = "n/a" if not states else "yes" if states == {"yes"} else "partial" if states != {"no"} else "no"
    return t


def table_rows(runs_rows: list[dict]) -> list[dict]:
    """Runs by phase and start time, each phase followed by its totals row, then the overall total."""
    ordered = sorted(runs_rows, key=lambda r: (PHASE_ORDER.get(r["phase"], 9), r["phase"], r["_start_t"] or 0.0, r["run_id"]))
    out: list[dict] = []
    for phase in dict.fromkeys(r["phase"] for r in ordered):
        grp = [r for r in ordered if r["phase"] == phase]
        out += grp + [total_row(grp, f"TOTAL {phase}", "phase_total", phase)]
    out.append(total_row(ordered, "TOTAL all", "total", ""))
    return out


def role_table(runs: list[dict], landed: dict, plan_path: str) -> list[dict]:
    """Main phase, per target role: probes sent, usable probes and the quota of the plan."""
    quota: dict[str, int | str] = {}
    try:
        with open(plan_path, encoding="utf-8") as f:
            plan = json.load(f)
        for t in plan.get("targets", []):
            quota[t["role"]] = int(t.get("quota_per_target", plan.get("quota_per_target", 0)))
    except (FileNotFoundError, ValueError, KeyError):
        pass
    by_role: dict[str, list[int]] = {r: [0, 0] for r in quota}
    for run in runs:
        if _phase(run, (run["start"] or {}).get("run_id") or run["file_run_id"]) != "main":
            continue
        for p in sent_probes(run):
            c = by_role.setdefault(p.get("target_role") or "?", [0, 0])
            c[0] += 1
            c[1] += is_usable(p, landed)
    return [{"role": r, "probes": c[0], "usable": c[1], "quota": quota.get(r, "")} for r, c in by_role.items()]


# ---- output ---------------------------------------------------------------------------------------

def write_csv(rows: list[dict], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def _pct(x) -> str:
    return "" if x == "" else f"{100 * x:.1f}%"


def _short(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n] + "..."


def _md_table(head: list[str], body: list[list[str]]) -> list[str]:
    return ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"] + ["| " + " | ".join(r) + " |" for r in body]


def render_md(rows: list[dict], roles: list[dict]) -> str:
    head = ["run", "phase", "mode", "start (UTC)", "end (UTC)", "git", "probes", "tx sent", "tx landed", "landing", "usable",
            "fees settled (lamports)", "anchor", "collected", "note"]
    body = []
    for r in rows:
        total = r["row_type"] != "run"
        b = (lambda s: f"**{s}**" if s else s) if total else (lambda s: s)
        body.append([b(r["run_id"]), r["phase"], r["mode"], r["start_utc"], r["end_utc"], _short(r["git_commit"], 10),
                     b(str(r["probes_sent"])), b(str(r["tx_sent"])), b(str(r["tx_landed"])), b(_pct(r["landing_rate"])),
                     b(str(r["usable_probes"])), b(str(r["fees_settled_lamports"])), _short(r["anchor_signature"], 12),
                     r["collected"], r["note"]])
    out = ["# Runs (operational summary)", "",
           "Counts and fees only: no ordering outcome is read or shown here. Written by `itb runs` from `data/raw/*.sent.jsonl`, "
           "`data/raw/*.landed.jsonl` and `data/ledger/spend.jsonl`.", "",
           "- probes, tx sent: live probes with a send result and their transactions; tx landed: transactions with a landing record; "
           "landing = tx landed / tx sent (a lower bound while `collected` is not `yes`).",
           "- usable: both transactions in ONE block produced by the targeted leader, in a slot of the targeted window (all arms; the analysis "
           "applies its further conditions per arm and per claim).",
           "- fees settled: lamports settled in the ledger for the run's probe transactions (matched by signature); the anchor transaction is "
           "not included.", "", "## Runs", ""]
    out += _md_table(head, body)
    out += ["", "## Run anchors (memo transaction of each run)", ""]
    anchors = [r for r in rows if r["row_type"] == "run" and r["anchor_signature"]]
    out += _md_table(["run", "anchor signature", "anchor fee (lamports)"],
                     [[r["run_id"], f"`{r['anchor_signature']}`", str(r["anchor_fee_lamports"])] for r in anchors]) if anchors else ["none"]
    out += ["", "## Main phase by role", ""]
    if roles:
        body = [[x["role"], str(x["probes"]), str(x["usable"]), str(x["quota"])] for x in roles]
        q = [x["quota"] for x in roles if x["quota"] != ""]
        body.append(["**total**", f"**{sum(x['probes'] for x in roles)}**", f"**{sum(x['usable'] for x in roles)}**",
                     f"**{sum(q)}**" if q else ""])
        out += _md_table(["role", "probes", "usable", "quota (data/plan.json)"], body)
    else:
        out += ["no main-phase probes and no plan"]
    return "\n".join(out) + "\n"


def summary_lines(rows: list[dict]) -> list[str]:
    return [f"{r['run_id']}: {r['note']}, probes {r['probes_sent']}, tx sent {r['tx_sent']}, landed {r['tx_landed']} "
            f"({_pct(r['landing_rate']) or 'n/a'}), usable {r['usable_probes']}, fees {r['fees_settled_lamports']} lamports"
            for r in rows if r["row_type"] != "run"]


def build(raw_dir: str, ledger_path: str, plan_path: str) -> tuple[list[dict], list[dict]]:
    landed, fees = landing_index(raw_dir), settled_fees(ledger_path)
    runs = load_runs(raw_dir)
    rows = table_rows([summarize_run(r, landed, fees) for r in runs])
    return rows, role_table(runs, landed, plan_path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="itb runs", description="operational summary of the runs (no ordering outcomes)")
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--ledger", default="data/ledger/spend.jsonl")
    ap.add_argument("--plan", default="data/plan.json")
    ap.add_argument("--out", default="results")
    a = ap.parse_args(argv)
    rows, roles = build(a.raw, a.ledger, a.plan)
    os.makedirs(a.out, exist_ok=True)
    write_csv(rows, os.path.join(a.out, "runs.csv"))
    with open(os.path.join(a.out, "runs.md"), "w", encoding="utf-8") as f:
        f.write(render_md(rows, roles))
    print("\n".join(summary_lines(rows)))
    print(f"wrote {os.path.join(a.out, 'runs.md')} and {os.path.join(a.out, 'runs.csv')}")
    return 0
