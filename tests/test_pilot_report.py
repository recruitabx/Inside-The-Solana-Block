import json

from itb import pilot_report as pr


def _write(tmp_path, probes, swap_index=False, ledger=True):
    """probes: dicts with tau0, arm, target, landing ('usable' | 'other_leader' | 'one' | 'none' | 'diff_slot' | 'outside'),
    send_results."""
    raw = tmp_path / "raw"
    raw.mkdir(exist_ok=True)
    sent, landed, led = [], [], []
    for k, s in enumerate(probes):
        first = 1000 + 8 * k
        sigs = [f"s{k}a", f"s{k}b"]
        sent.append({"record": "probe", "mode": "live", "phase": "pilot", "run_id": "r", "probe_id": f"r:{k}", "arm": s["arm"],
                     "target_leader": s["target"], "target_role": s["target"] + "-1", "window_first_slot": first, "window_last_slot": first + 3,
                     "tau0_ms": s["tau0"], "send_results": s.get("send_results", ["ok", "ok"]),
                     "txs": [{"signature": g, "max_fee": 10_500 if i == 0 else 5_001} for i, g in enumerate(sigs)]})
        for i, g in enumerate(sigs):
            led.append({"kind": "reserve", "sig": g, "max_fee": 10_500 if i == 0 else 5_001})
            land = s["landing"]
            if land == "none" or (land == "one" and i == 1):
                landed.append({"record": "not_landed", "signature": g})
                led.append({"kind": "release", "sig": g, "reason": "x"})
                continue
            slot, leader = first + 1, s["target"]
            if land == "other_leader":
                leader = "OTHER"
            elif land == "diff_slot":
                slot = first + i
            elif land == "outside":
                slot = first + 5
            idx = (10 + i) if not swap_index else (11 - i)
            landed.append({"record": "landed", "signature": g, "slot": slot, "tx_index": idx, "leader": leader, "fee": 10_500 if i == 0 else 5_001})
            if not (s.get("unsettled") and i == 0):
                led.append({"kind": "settle", "sig": g, "actual_fee": 10_500 if i == 0 else 5_001})
    (raw / "x-live-pilot-1.sent.jsonl").write_text("".join(json.dumps(x) + "\n" for x in sent))
    (raw / "x-live-pilot-1.landed.jsonl").write_text("".join(json.dumps(x) + "\n" for x in landed))
    # a main-phase probe in the same file must be ignored
    with open(raw / "x-live-pilot-1.sent.jsonl", "a") as f:
        f.write(json.dumps({"record": "probe", "mode": "live", "phase": "main", "send_results": ["ok", "ok"], "target_leader": "T", "txs": []}) + "\n")
    lp = tmp_path / "ledger.jsonl"
    if ledger:
        lp.write_text("".join(json.dumps(x) + "\n" for x in led))
    return str(raw / "*pilot*.sent.jsonl"), str(lp)


def _p(tau0, landing="usable", arm="P", target="A", **kw):
    return {"tau0": tau0, "landing": landing, "arm": arm, "target": target, **kw}


def test_metrics_and_tau0_rule_picks_earliest_tau_with_u_ge_040(tmp_path):
    probes = ([_p(-270, "usable")] * 2 + [_p(-270, "none")] * 3                 # u = 0.40 at -270
              + [_p(-170, "usable")] * 4 + [_p(-170, "other_leader")]           # u = 0.80
              + [_p(-70, "usable")] * 5 + [_p(-70, "one")] * 0)                 # u = 1.0
    sent, led = _write(tmp_path, probes)
    rep = pr.build_report(sent, led)
    assert rep["n_probes"] == 15
    assert rep["u_by_tau0_arm_P"][-270]["u"] == 0.4 and rep["u_by_tau0_arm_P"][-170]["u"] == 0.8
    assert rep["tau0_choice"]["tau0_ms"] == -270                                # earliest with u >= 0.40
    assert "earliest" in rep["tau0_choice"]["rule"]


def test_tau0_rule_falls_back_to_highest_u(tmp_path):
    probes = [_p(-270, "usable")] + [_p(-270, "none")] * 4 + [_p(-170, "usable")] * 2 + [_p(-170, "diff_slot")] * 4 + [_p(-70, "none")] * 5
    rep = pr.build_report(*_write(tmp_path, probes))
    assert rep["u_by_tau0_arm_P"][-270]["u"] == 0.2 and abs(rep["u_by_tau0_arm_P"][-170]["u"] - 1 / 3) < 1e-12
    assert rep["tau0_choice"]["tau0_ms"] == -170 and "highest u" in rep["tau0_choice"]["rule"]
    assert pr.choose_tau0({-270: {"probes": 4, "u": 0.25}, -170: {"probes": 4, "u": 0.25}})["tau0_ms"] == -270   # tie: earliest
    assert pr.choose_tau0({})["tau0_ms"] is None


def test_rates_offsets_and_request_errors(tmp_path):
    probes = [
        _p(-170, "usable", target="A"),
        _p(-170, "other_leader", target="A", send_results=["ok", {"code": 429, "message": "Too many requests"}]),
        _p(-170, "one", target="B", send_results=["transport: HTTP 429 from rpc.example", "transport: HTTP 429 from rpc.example"]),
        _p(-170, "outside", target="B"),
        _p(-170, "usable", arm="S", target="A", send_results=["ok", "ok"]),
        _p(-170, "diff_slot", arm="S", target="B", send_results=["ok", "transport: HTTP 503 from rpc.example"]),
        _p(-170, "none", arm="S", target="B", send_results=["ok", {"code": -32002, "message": "Transaction simulation failed"}]),
    ]
    rep = pr.build_report(*_write(tmp_path, probes))
    a = rep["pooled"]["all"]
    assert a["probes"] == 7 and a["tx_sent"] == 14 and a["tx_landed"] == 11   # 'one' loses 1 transaction, 'none' loses 2
    P = rep["pooled"]["P"]
    assert P["probes"] == 4 and P["both_landed"] == 3 and P["same_slot"] == 3 and P["target_hit"] == 2 and P["usable"] == 1 and P["u"] == 0.25
    assert P["requests"]["batch"]["n"] == 4 and P["requests"]["batch"]["http_429"] == 2 and P["requests"]["batch"]["errors"] == 2
    S = rep["pooled"]["S"]
    assert S["requests"]["S_first"]["errors"] == 0 and S["requests"]["S_second"]["errors"] == 2 and S["requests"]["S_second"]["http_429"] == 0
    assert S["requests"]["S_second"]["n"] == 3
    # offsets (landing slot - window first slot) of the 7 landed P transactions: usable 1,1; other leader 1,1; one 1; outside 5,5
    assert abs(P["mean_slot_offset"] - (1 + 1 + 1 + 1 + 1 + 5 + 5) / 7) < 1e-12
    assert sorted(rep["per_target"]) == [k for k in rep["per_target"] if k.startswith(("A-1", "B-1"))]


def test_ledger_reconciliation_and_open_reservations(tmp_path):
    probes = [_p(-170, "usable"), _p(-170, "usable", unsettled=True), _p(-170, "none")]
    rep = pr.build_report(*_write(tmp_path, probes))
    lg = rep["ledger"]
    assert lg["ledger_found"] and lg["pilot_tx_sent"] == 6
    assert lg["onchain_meta_fee_sum_landed"] == 2 * (10_500 + 5_001)
    assert lg["settled_actual_fee_sum"] == 2 * 5_001 + 10_500 and lg["exact_match"] is False
    assert lg["landed_not_settled"] == 1 and lg["open_reservations_pilot"] == 1 and lg["open_reservations_pilot_max_fee"] == 10_500
    ok = tmp_path / "ok"
    ok.mkdir()
    rep = pr.build_report(*_write(ok, [_p(-170, "usable")]))
    assert rep["ledger"]["exact_match"] is True and rep["criteria"]["ledger_spend_equals_meta_fee"] is True
    assert pr.build_report(str(tmp_path / "raw" / "*pilot*.sent.jsonl"), str(tmp_path / "nope.jsonl"))["ledger"] == {"ledger_found": False}
    assert pr.reconcile_ledger(str(tmp_path / "nope.jsonl"), [], {}) == {"ledger_found": False}


def test_report_never_depends_on_block_order(tmp_path):
    probes = [_p(t, "usable") for t in (-270, -170, -70)] * 3 + [_p(-170, "usable", arm="S")] * 2
    d1, d2 = tmp_path / "a", tmp_path / "b"
    d1.mkdir(); d2.mkdir()
    rep1, rep2 = pr.build_report(*_write(d1, probes)), pr.build_report(*_write(d2, probes, swap_index=True))
    rep1["sent_glob"] = rep2["sent_glob"] = ""
    assert pr.render(rep1) == pr.render(rep2) and rep1 == rep2
    j = json.dumps(pr.build_report(*_write(d1, probes)))
    for word in ("tx_index", "first_landed", "high_fee_first", "y_fee", "landing_order"):
        assert word not in j


def test_cli_registered_and_main_runs(tmp_path, capsys):
    from itb.cli import COMMANDS, main
    assert COMMANDS["pilot-report"] == "itb.pilot_report"
    sent, led = _write(tmp_path, [_p(-170, "usable"), _p(-70, "usable")])
    assert main(["pilot-report", "--sent", sent, "--ledger", led]) == 0
    out = capsys.readouterr().out
    assert "tau0 CHOICE" in out and "operational metrics only" in out
    assert main(["pilot-report", "--sent", str(tmp_path / "none*.sent.jsonl")]) == 1
