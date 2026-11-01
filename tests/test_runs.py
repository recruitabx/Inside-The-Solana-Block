import csv
import inspect
import json

from itb import cli, runs

PILOT = "20260101T000000Z-live-pilot-aaaaaa"
REPILOT = "20260101T010000Z-live-repilot-bbbbbb"
MAIN = "20260102T000000Z-live-cccccc"
T_PILOT, T_REPILOT, T_MAIN = 1767225600.0, 1767229200.0, 1767312000.0     # 2026-01-01T00:00:00Z, 01:00:00Z, 2026-01-02T00:00:00Z


def _w(path, recs, tail=""):
    path.write_text("".join(json.dumps(r) + "\n" for r in recs) + tail)


def _probe(run, k, phase, role, target, first, *, last=None, mode="live", send=("ok", "ok")):
    p = {"record": "probe", "mode": mode, "run_id": run, "probe_id": f"{run}:{k}", "phase": phase, "target_role": role,
         "target_leader": target, "window_first_slot": first, "send_results": list(send),
         "txs": [{"signature": f"{run}-{k}{c}", "send_pos": i} for i, c in enumerate("ab")]}
    if last is not None:
        p["window_last_slot"] = last
    return p


def _landing(probe, spec, swap_index=False):
    """spec: one entry per transaction: (slot, leader) -> landed, "not" -> not_landed, None -> no record."""
    out = []
    for i, (t, s) in enumerate(zip(probe["txs"], spec)):
        if s is None:
            continue
        if s == "not":
            out.append({"record": "not_landed", "signature": t["signature"], "probe_id": probe["probe_id"], "reason": "x"})
        else:
            out.append({"record": "landed", "signature": t["signature"], "probe_id": probe["probe_id"], "slot": s[0], "leader": s[1],
                        "tx_index": (11 - i) if swap_index else (10 + i), "fee": 5001})
    return out


def make_fixture(tmp_path, swap_index=False):
    raw = tmp_path / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (tmp_path / "ledger").mkdir(exist_ok=True)
    led, landed_all = [], {}

    def run_files(run, phase, t0, probes, specs, *, end=None, git="g" * 40, anchor=None, tail=""):
        recs = [{"record": "run_start", "run_id": run, "mode": "live", "phase": phase, "t": t0, "git_commit": git,
                 **({"anchor": {"signature": anchor, "send_results": ["ok"]}} if anchor else {})},
                {"record": "window_skipped", "run_id": run, "reason": "x"}] + probes
        if end:
            recs.append({"record": "run_end", "run_id": run, "t": t0 + end[0], **end[1]})
        _w(raw / f"{run}.sent.jsonl", recs, tail)
        land = [x for p, s in zip(probes, specs) for x in _landing(p, s, swap_index)]
        landed_all[run] = land
        for p, s in zip(probes, specs):
            for t, one in zip(p["txs"], s):
                led.append({"kind": "reserve", "sig": t["signature"], "max_fee": 10_500, "tag": phase})
                high = phase == "pilot" and p["probe_id"].endswith(":1") and t["send_pos"] == 0
                led.append({"kind": "settle", "sig": t["signature"], "actual_fee": 10_500 if high else 5_001} if isinstance(one, tuple)
                           else {"kind": "release", "sig": t["signature"], "reason": "x"})
        if anchor:
            led.extend([{"kind": "reserve", "sig": anchor, "max_fee": 7000, "tag": f"anchor:{run}"},
                        {"kind": "settle", "sig": anchor, "actual_fee": 7000}])

    # pilot: one usable probe (fees 10500 + 5001), one that landed in another leader's block (5001 + 5001); dry and unsent probes are ignored
    pp = [_probe(PILOT, 1, "pilot", "R1", "T1", 1000), _probe(PILOT, 2, "pilot", "R1", "T1", 1010),
          _probe(PILOT, 3, "pilot", "R1", "T1", 1020, mode="dry"), _probe(PILOT, 4, "pilot", "R1", "T1", 1030, send=())]
    run_files(PILOT, "pilot", T_PILOT, pp, [[(1001, "T1")] * 2, [(1011, "OTHER")] * 2, [None, None], [None, None]],
              end=(90, {}), anchor="ANCHOR-pilot")
    # repilot: one probe, one transaction landed, a send error, interrupted
    rp = [_probe(REPILOT, 1, "repilot", "R1", "T1", 2000, send=("ok", "transport: boom"))]
    run_files(REPILOT, "repilot", T_REPILOT, rp, [[(2001, "T1"), "not"]], end=(30, {"error": "KeyboardInterrupt: "}), anchor="ANCHOR-repilot")
    # main, still running (no run_end, a partly written last line): window edge, outside, two slots, other role, uncollected
    mp = [_probe(MAIN, 1, "main", "R1", "T1", 3000), _probe(MAIN, 2, "main", "R1", "T1", 4000, last=4003),
          _probe(MAIN, 3, "main", "R1", "T1", 5000), _probe(MAIN, 4, "main", "R2", "T2", 6000),
          _probe(MAIN, 5, "main", "R2", "T2", 7000), _probe(MAIN, 6, "main", "RX", "TX", 8000)]
    run_files(MAIN, "main", T_MAIN, mp, [[(3003, "T1")] * 2, [(4004, "T1")] * 2, [(5001, "T1"), (5002, "T1")], [(6001, "T2")] * 2,
                                         [None, None], [None, None]], anchor="ANCHOR-main", tail='{"record": "probe", "mode": "li')
    # a synthetic file must never count as a run
    _w(raw / "synthetic-live-0.sent.jsonl", [{"record": "run_start", "run_id": "synthetic-live-0", "phase": "main", "t": T_MAIN},
                                             _probe("synthetic-live-0", 1, "main", "R1", "T1", 1)])
    for run, land in landed_all.items():
        _w(raw / f"{run}.landed.jsonl", land, tail='{"record": "landed", "sign' if run == MAIN else "")
    _w(tmp_path / "ledger" / "spend.jsonl", led)
    (tmp_path / "plan.json").write_text(json.dumps({"quota_per_target": 4, "targets": [
        {"role": "R1", "quota_per_target": 5}, {"role": "R2"}, {"role": "R3"}]}))
    return str(raw), str(tmp_path / "ledger" / "spend.jsonl"), str(tmp_path / "plan.json")


def _build(tmp_path, **kw):
    raw, ledger, plan = make_fixture(tmp_path, **kw)
    rows, roles = runs.build(raw, ledger, plan)
    return {r["run_id"]: r for r in rows}, roles, (raw, ledger, plan)


def test_one_row_per_run_with_counts_fees_and_anchor(tmp_path):
    rows, _, _ = _build(tmp_path)
    p = rows[PILOT]
    assert (p["phase"], p["mode"], p["start_utc"], p["end_utc"]) == ("pilot", "live", "2026-01-01T00:00:00Z", "2026-01-01T00:01:30Z")
    assert p["git_commit"] == "g" * 40 and p["anchor_signature"] == "ANCHOR-pilot" and p["anchor_fee_lamports"] == 7000
    assert (p["probes_sent"], p["tx_sent"], p["tx_landed"], p["landing_rate"], p["usable_probes"]) == (2, 4, 4, 1.0, 1)
    assert p["fees_settled_lamports"] == 10_500 + 3 * 5_001 and p["collected"] == "yes" and p["note"] == ""
    r = rows[REPILOT]
    assert (r["probes_sent"], r["tx_sent"], r["tx_landed"], r["landing_rate"], r["usable_probes"]) == (1, 2, 1, 0.5, 0)
    assert r["send_errors"] == 1 and r["fees_settled_lamports"] == 5_001 and r["note"] == "ended with KeyboardInterrupt"
    m = rows[MAIN]
    assert m["phase"] == "main" and m["start_utc"] == "2026-01-02T00:00:00Z" and m["end_utc"] == ""
    assert (m["probes_sent"], m["tx_sent"], m["tx_landed"], m["usable_probes"]) == (6, 12, 8, 2)   # window edge counts, 4004 > 4003 does not
    assert m["collected"] == "partial" and "no run_end" in m["note"] and m["fees_settled_lamports"] == 8 * 5_001
    assert "synthetic-live-0" not in rows


def test_totals_per_phase_and_overall(tmp_path):
    rows, _, _ = _build(tmp_path)
    assert [(k, v["row_type"]) for k, v in rows.items()] == [
        (PILOT, "run"), ("TOTAL pilot", "phase_total"), (REPILOT, "run"), ("TOTAL repilot", "phase_total"),
        (MAIN, "run"), ("TOTAL main", "phase_total"), ("TOTAL all", "total")]
    t = rows["TOTAL all"]
    assert (t["probes_sent"], t["tx_sent"], t["tx_landed"], t["usable_probes"]) == (9, 18, 13, 3)
    assert t["fees_settled_lamports"] == (10_500 + 3 * 5_001) + 5_001 + 8 * 5_001
    assert t["landing_rate"] == round(13 / 18, 4) and t["note"] == "3 runs"
    assert t["start_utc"] == "2026-01-01T00:00:00Z" and t["end_utc"] == "2026-01-01T01:00:30Z"
    assert rows["TOTAL main"]["tx_sent"] == 12 and rows["TOTAL pilot"]["note"] == "1 run"


def test_role_table_of_the_main_phase_against_the_plan_quotas(tmp_path):
    _, roles, _ = _build(tmp_path)
    assert {x["role"]: (x["probes"], x["usable"], x["quota"]) for x in roles} == {
        "R1": (3, 1, 5), "R2": (2, 1, 4), "R3": (0, 0, 4), "RX": (1, 0, "")}


def test_outputs_markdown_and_csv(tmp_path):
    raw, ledger, plan = make_fixture(tmp_path)
    out = tmp_path / "results"
    assert cli.main(["runs", "--raw", raw, "--ledger", ledger, "--plan", plan, "--out", str(out)]) == 0
    md = (out / "runs.md").read_text()
    assert chr(0x2014) not in md and "| **TOTAL all** |" in md and "| R1 | 3 | 1 | 5 |" in md and "`ANCHOR-main`" in md
    with open(out / "runs.csv", newline="") as f:
        rd = list(csv.DictReader(f))
    assert list(rd[0]) == runs.CSV_FIELDS and len(rd) == 7
    assert rd[0]["run_id"] == PILOT and rd[0]["anchor_signature"] == "ANCHOR-pilot" and rd[-1]["row_type"] == "total"
    assert rd[-1]["tx_sent"] == "18" and rd[-1]["landing_rate"] == str(round(13 / 18, 4))


def test_never_reads_or_depends_on_the_position_in_the_block(tmp_path):
    a, _, _ = _build(tmp_path / "a")
    b, rb, _ = _build(tmp_path / "b", swap_index=True)
    assert a == b
    assert "tx_" + "index" not in inspect.getsource(runs)
    # the records handed on by the reader carry no field beyond the four it asks for
    got = list(runs.read_jsonl(str(tmp_path / "a" / "raw" / f"{PILOT}.landed.jsonl"), runs.LANDED_KEYS))
    assert got and all(set(g) == set(runs.LANDED_KEYS) for g in got)


def test_a_run_whose_send_log_is_still_empty_and_missing_files(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "20261031T083802Z-live-2661db.sent.jsonl").write_text("")
    rows, roles = runs.build(str(raw), str(tmp_path / "none.jsonl"), str(tmp_path / "none.json"))
    r = [x for x in rows if x["row_type"] == "run"][0]
    assert (r["phase"], r["start_utc"], r["probes_sent"], r["collected"]) == ("main", "2026-10-31T08:38:02Z", 0, "n/a")
    assert "no run_start" in r["note"] and roles == []
    md = runs.render_md(rows, roles)
    assert "no main-phase probes" in md
