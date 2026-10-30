import glob
import json

import numpy as np
import pytest
from scipy import optimize

from itb.analyze import DEFAULTS, FIFO_NOTE, NO_RULE, analyze, logit_irls
from itb.stats import holm
from itb.synthetic import write_synthetic


def _run(tmp_path, validators, seed=0, final=True, mutate=None):
    raw = tmp_path / f"raw{seed}"
    write_synthetic(str(raw), validators, seed=seed)
    if mutate:
        mutate(raw)
    summary = analyze(str(raw), str(tmp_path / f"out{seed}"), dict(DEFAULTS), final=final)
    doc = json.load(open(tmp_path / f"out{seed}" / "verdicts.json"))
    return {u["identity"]: u for u in doc["units"]}, doc, summary


def _ids(**kw):
    return {k: {"client_id": "Agave", "version": "4.3.2", **v} for k, v in kw.items()}


def test_planted_rules_recovered_and_null_called_null(tmp_path):
    res, doc, _ = _run(tmp_path, _ids(
        FEE={"n": 200, "p_fee": 0.99}, NULL={"n": 400, "p_fee": 0.5}, SMALL={"n": 20, "p_fee": 1.0},
        SEND={"n": 200, "p_fee": 0.5, "p_send": 0.99}, PART={"n": 300, "p_fee": 0.68}, REV={"n": 200, "p_fee": 0.01}))
    assert res["FEE"]["verdict"] == "fee rule holds, strict", res["FEE"]["verdict"]
    assert res["NULL"]["verdict"] == NO_RULE + FIFO_NOTE, res["NULL"]["verdict"]   # no arm-S data: FIFO not excluded
    assert res["SMALL"]["verdict"] == "insufficient data (n=20)"               # regardless of p-values
    assert res["SEND"]["verdict"] == "send-order rule holds, strict", res["SEND"]["verdict"]
    assert res["PART"]["verdict"] == "fee rule holds, partial", res["PART"]["verdict"]
    assert res["REV"]["verdict"] == "reverse fee rule holds, strict", res["REV"]["verdict"]
    assert doc["holm_family_size"] == 12 and doc["final"] is True


def test_mixed_rule(tmp_path):
    res, _, _ = _run(tmp_path, _ids(MIX={"cells": [{"arm": "P", "n": 400, "b_fee": 2.0, "b_send": 2.0}]}))
    assert res["MIX"]["verdict"] == "mixed: fee rule partial and send-order rule partial", res["MIX"]["verdict"]
    t = res["MIX"]["table_2x2"]   # high sent first lands first far more often than high sent second
    assert t["sent_first_landed_first"] / (t["sent_first_landed_first"] + t["sent_first_landed_second"]) > 0.9


def test_false_positive_rate_on_random_order(tmp_path):
    hits = 0
    reps = 60
    for s in range(reps):
        res, _, _ = _run(tmp_path, _ids(NULL={"n": 100, "p_fee": 0.5}), seed=1000 + s)
        hits += res["NULL"]["verdict"].startswith(("fee rule", "reverse fee", "send-order", "reverse send", "mixed"))
    assert hits / reps <= 0.10  # nominal 5%; generous bound for 60 repetitions


def test_fifo_remark_depends_on_pooled_arm_s(tmp_path):
    cells_null = [{"arm": "P", "n": 400, "p_fee": 0.5}]
    # pooled arm S with q_S near 0.5 and n >= 30 on the same clientId: arrival order excluded, no remark
    res, _, _ = _run(tmp_path, _ids(A={"cells": cells_null + [{"arm": "S", "n": 300, "p_send": 0.5}]}), seed=1)
    assert res["A"]["verdict"] == NO_RULE
    # q_S = 1 (FIFO at arm S): remark stays
    res, _, _ = _run(tmp_path, _ids(A={"cells": cells_null + [{"arm": "S", "n": 60, "p_send": 1.0}]}), seed=2)
    assert res["A"]["verdict"] == NO_RULE + FIFO_NOTE
    # fewer than 30 arm-S pairs: remark stays
    res, _, _ = _run(tmp_path, _ids(A={"cells": cells_null + [{"arm": "S", "n": 20, "p_send": 0.5}]}), seed=3)
    assert res["A"]["verdict"] == NO_RULE + FIFO_NOTE


def test_main_phase_needs_final_and_only_main_is_confirmatory(tmp_path):
    v = _ids(A={"n": 120, "p_fee": 0.95})

    def to_real_main(raw):                  # strip the synthetic flag: now it looks like real main data
        for f in glob.glob(str(raw / "*.sent.jsonl")):
            recs = [json.loads(x) for x in open(f)]
            for r in recs:
                r.pop("synthetic", None)
            open(f, "w").write("".join(json.dumps(r) + "\n" for r in recs))

    res, doc, summ = _run(tmp_path, v, seed=1, final=False, mutate=to_real_main)
    assert res == {} and summ["n_main_rows_refused"] == 120 and doc["final"] is False
    res, doc, summ = _run(tmp_path, v, seed=2, final=True, mutate=to_real_main)
    assert res["A"]["verdict"].startswith("fee rule holds") and summ["n_main_rows_refused"] == 0
    # synthetic main data are accepted without --final; pilot rows never enter a final analysis

    def to_pilot(raw):
        for f in glob.glob(str(raw / "*.sent.jsonl")):
            recs = [json.loads(x) for x in open(f)]
            for r in recs:
                if r["record"] == "probe":
                    r["phase"] = "pilot"; r.pop("synthetic", None)
            open(f, "w").write("".join(json.dumps(r) + "\n" for r in recs))
    res, _, summ = _run(tmp_path, v, seed=3, final=True, mutate=to_pilot)
    assert res == {} and summ["n_rows_analysed"] == 0
    res, _, summ = _run(tmp_path, v, seed=4, final=False, mutate=to_pilot)
    assert res["A"]["fee"]["n"] == 120                 # pilot data may be analysed without --final


def test_cli_refuses_main_without_final(tmp_path, capsys):
    from itb.analyze import main
    raw = tmp_path / "raw"
    write_synthetic(str(raw), _ids(A={"n": 10}), seed=1)
    for f in glob.glob(str(raw / "*.sent.jsonl")):
        recs = [json.loads(x) for x in open(f)]
        for r in recs:
            r.pop("synthetic", None)
        open(f, "w").write("".join(json.dumps(r) + "\n" for r in recs))
    assert main(["--raw", str(raw), "--out", str(tmp_path / "o")]) == 0
    out = capsys.readouterr().out
    assert "refusing to include 10 main-phase probes without --final" in out


def test_claim_change_excludes_run_and_exclusions_are_counted(tmp_path):
    res, _, _ = _run(tmp_path, _ids(
        FLIP={"n": 50, "p_fee": 1.0, "claim_end_version": "4.4.0"},
        MIXED={"cells": [{"arm": "P", "n": 400, "p_fee": 1.0, "p_miss": 0.1, "p_one": 0.1, "p_diff_slot": 0.1,
                          "p_other_leader": 0.1, "p_first_slot": 1.0, "p_err": 0.05}]}))
    f = res["FLIP"]
    assert f["n_primary"] == 0 and f["exclusions"]["claim_changed_in_run"] == 50 and f["verdict"] == "insufficient data (n=0)"
    m = res["MIXED"]
    e = m["exclusions"]
    assert e["primary"] == m["n_primary"] and e["none_landed"] > 0 and e["one_landed"] > 0
    assert e["different_slots"] > 0 and e["other_producer"] > 0 and e["primary_with_execution_error"] > 0
    assert m["n_primary"] + sum(e[k] for k in ("none_landed", "one_landed", "different_slots", "other_producer",
                                               "target_outside_window")) == 400
    assert m["fee"]["p"] == 1.0                           # other leaders / different slots never enter the cell


def test_outside_window_slot_excluded(tmp_path):
    def shift(raw):                                         # land every pair after the targeted window
        for f in glob.glob(str(raw / "*.landed.jsonl")):
            recs = [json.loads(x) for x in open(f)]
            for r in recs:
                r["slot"] += 10
            open(f, "w").write("".join(json.dumps(r) + "\n" for r in recs))
    res, _, _ = _run(tmp_path, _ids(A={"n": 30}), mutate=shift)
    assert res["A"]["n_primary"] == 0 and res["A"]["exclusions"]["target_outside_window"] == 30


def test_unit_split_by_version_and_one_holm_family(tmp_path):
    raw = tmp_path / "raw"
    write_synthetic(str(raw), {"X": {"n": 100, "p_fee": 0.8, "client_id": "Agave", "version": "4.3.2", "role": "R1"},
                               "Y": {"n": 100, "p_fee": 0.6, "client_id": "JitoLabs", "version": "4.3.2", "role": "R2"}}, seed=1)
    analyze(str(raw), str(tmp_path / "o"), dict(DEFAULTS), final=True)
    doc = json.load(open(tmp_path / "o" / "verdicts.json"))
    us = doc["units"]
    assert {(u["target_role"], u["identity"], u["client_id"], u["version"]) for u in us} == {
        ("R1", "X", "Agave", "4.3.2"), ("R2", "Y", "JitoLabs", "4.3.2")}
    ps = [u[w]["p_value"] for u in us for w in ("fee", "send")]
    adj = holm(ps)
    got = [u[w]["p_holm"] for u in us for w in ("fee", "send")]
    assert np.allclose(adj, got) and doc["holm_family_size"] == 4
    # derived files exist
    for name in ("verdicts.csv", "table_2x2.csv", "logit.csv", "secondary.json"):
        assert (tmp_path / "o" / name).exists()


def test_2x2_and_logit_on_planted_fee_rule(tmp_path):
    res, _, _ = _run(tmp_path, _ids(A={"n": 300, "p_fee": 0.9}, B={"n": 300, "p_fee": 0.5, "p_send": 0.9}))
    a, b = res["A"], res["B"]
    t = a["table_2x2"]
    assert sum(t.values()) == a["n_primary"] == 300
    assert t["sent_first_landed_first"] + t["sent_second_landed_first"] == a["fee"]["k"]
    la = a["logit"]
    assert la["converged"] and la["coef"]["A_is_high"] > 1.5 and abs(la["coef"]["A_sent_first"]) < 1.0
    assert all(v > 0 for v in la["se"].values())
    lb = b["logit"]
    assert lb["coef"]["A_sent_first"] > 1.5 and abs(lb["coef"]["A_is_high"]) < 1.0


def test_logit_irls_matches_direct_maximum_likelihood():
    rng = np.random.default_rng(3)
    X = np.column_stack([np.ones(400), rng.integers(0, 2, 400), rng.integers(0, 2, 400)]).astype(float)
    true = np.array([-0.2, 1.1, 0.4])
    y = (rng.random(400) < 1 / (1 + np.exp(-X @ true))).astype(float)
    got = logit_irls(X, y)

    def nll(b):
        eta = X @ b
        return float(np.sum(np.logaddexp(0, eta) - y * eta))
    ref = optimize.minimize(nll, np.zeros(3), method="BFGS", options={"gtol": 1e-9}).x
    assert np.allclose(list(got["coef"].values()), ref, atol=1e-4)
    assert got["converged"] and not got["separation"]
    # standard errors from the observed information
    mu = 1 / (1 + np.exp(-X @ ref))
    cov = np.linalg.inv(X.T @ (X * (mu * (1 - mu))[:, None]))
    assert np.allclose(list(got["se"].values()), np.sqrt(np.diag(cov)), atol=1e-3)
    assert "error" in logit_irls(X[:2], y[:2])


def test_secondary_tables(tmp_path):
    v = _ids(
        H={"client_id": "HarmonicAgave", "version": "4.4.0", "role": "H-1", "cells": [
            {"arm": "P", "n": 120, "p_fee": 0.95, "strategy": "FBA", "p_copresent": 0.0},
            {"arm": "P", "n": 120, "p_fee": 0.5, "strategy": "FIF", "p_copresent": 0.0},
            {"arm": "P", "n": 20, "p_fee": 0.5, "p_copresent": 0.0},
            {"arm": "E", "n": 80, "p_send": 0.5}, {"arm": "S", "n": 60, "p_send": 1.0},
            {"arm": "D", "n": 80, "p_fee": 0.5, "p_diff_slot": 0.3, "p_other_leader": 0.2},
            {"arm": "P", "n": 150, "p_fee": 0.5, "p_fee_co": 1.0, "p_copresent": 1.0, "p_first_slot": 1.0}]},
    )
    res, doc, _ = _run(tmp_path, v)
    sec = doc["secondary"]
    c = "HarmonicAgave"
    assert sec["arm_S"][c]["q"]["p"] == 1.0 and sec["arm_S"][c]["q_rule"].endswith("strict")
    assert sec["arm_E"][c]["q"]["n"] == 80 and 0.3 < sec["arm_E"][c]["q"]["p"] < 0.7
    assert "p" in sec["arm_E"][c] and sec["arm_E"][c]["p"]["n"] == 80       # placebo p_E from the pseudo-high label
    d = sec["arm_D_vs_P"][c]
    assert d["label"] == "exploratory" and d["p_D"]["n"] > 0 and "p_value" in d["fisher_fee_first"]
    assert sec["copresence_p_co"][c]["p_co"]["p"] == 1.0 and sec["copresence_p_co"][c]["p_co"]["n"] >= 100
    hs = sec["harmonic_strategy"]
    assert hs["label"] == "exploratory" and hs["by_label"]["FBA"]["n"] > 0 and hs["by_label"]["FIF"]["n"] > 0
    assert "no block summary" in hs["by_label"] and hs["fisher_pairs"]["FBA_vs_FIF"]["p_value"] < 0.01
    ds = sec["different_slot_pairs"]["D/" + c]
    assert ds["n_different_slots"] > 0 and ds["high_fee_earlier_slot"]["n"] == ds["n_different_slots"]
    assert any(u["n_tx"] > 0 and u["producer"].startswith("OTHER") for u in sec["untargeted_landings"])
    assert sec["execution_errors"]["n_tx_with_error"] == 0


def test_execution_errors_counted(tmp_path):
    _, doc, _ = _run(tmp_path, _ids(A={"cells": [{"arm": "P", "n": 100, "p_err": 0.3}]}))
    e = doc["secondary"]["execution_errors"]
    assert e["n_tx_with_error"] > 10 and e["by_arm"]["P"] == e["n_tx_with_error"]
