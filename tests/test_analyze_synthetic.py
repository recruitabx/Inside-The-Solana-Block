import glob
import json
import os

import numpy as np
import pytest
from scipy import optimize

from itb.analyze import DEFAULTS, FIFO_NOTE, NO_RULE, analyze, logit_irls
from itb.stats import holm
from itb.synthetic import write_synthetic


def _run(tmp_path, validators, seed=0, final=False, mutate=None):
    """Synthetic data are analysed WITHOUT --final (the default here); with final=True they would be excluded."""
    raw = tmp_path / f"raw{seed}"
    write_synthetic(str(raw), validators, seed=seed)
    if mutate:
        mutate(raw)
    summary = analyze(str(raw), str(tmp_path / f"out{seed}"), dict(DEFAULTS), final=final, figure=False)
    doc = json.load(open(tmp_path / f"out{seed}" / "verdicts.json"))
    return {u["identity"]: u for u in doc["units"]}, doc, summary


def _ids(**kw):
    return {k: {"client_id": "Agave", "version": "4.3.2", **v} for k, v in kw.items()}


def _edit_sent(raw, fn):
    for f in glob.glob(str(raw / "*.sent.jsonl")):
        recs = [json.loads(x) for x in open(f)]
        recs = [fn(r) or r for r in recs]
        open(f, "w").write("".join(json.dumps(r) + "\n" for r in recs))


def _to_real(raw, phase="main"):
    """Make synthetic data look like real data: no synthetic flag, file name without the synthetic prefix."""
    def strip(r):
        r.pop("synthetic", None)
        if r["record"] == "probe":
            r["phase"] = phase
    _edit_sent(raw, strip)
    for f in glob.glob(str(raw / "synthetic-*.sent.jsonl")):
        os.rename(f, f.replace("synthetic-", "real-"))


def test_planted_rules_recovered_and_null_called_null(tmp_path):
    res, doc, _ = _run(tmp_path, _ids(
        FEE={"n": 200, "p_fee": 0.99}, NULL={"n": 400, "p_fee": 0.5}, SMALL={"n": 20, "p_fee": 1.0},
        SEND={"n": 200, "p_fee": 0.5, "p_send": 0.99}, PART={"n": 300, "p_fee": 0.68}, REV={"n": 200, "p_fee": 0.01}))
    assert res["FEE"]["verdict"] == "fee rule holds, strict", res["FEE"]["verdict"]
    assert res["NULL"]["verdict"] == NO_RULE + FIFO_NOTE, res["NULL"]["verdict"]   # no arm-S data: FIFO not excluded
    assert res["SMALL"]["verdict"] == "insufficient data (n=20)"               # regardless of p-values
    assert res["SEND"]["verdict"] == "request-position rule holds, strict", res["SEND"]["verdict"]
    assert res["PART"]["verdict"] == "fee rule holds, partial", res["PART"]["verdict"]
    assert res["REV"]["verdict"] == "reverse fee rule holds, strict", res["REV"]["verdict"]
    assert doc["holm_family_size"] == 12 and doc["final"] is False


def test_mixed_rule(tmp_path):
    res, _, _ = _run(tmp_path, _ids(MIX={"cells": [{"arm": "P", "n": 400, "b_fee": 2.0, "b_send": 2.0}]}))
    assert res["MIX"]["verdict"] == "mixed: fee rule partial and request-position rule partial", res["MIX"]["verdict"]
    t = res["MIX"]["table_2x2"]   # high sent first lands first far more often than high sent second
    assert t["sent_first_landed_first"] / (t["sent_first_landed_first"] + t["sent_first_landed_second"]) > 0.9


def test_false_positive_rate_on_random_order(tmp_path):
    hits = 0
    reps = 60
    for s in range(reps):
        res, _, _ = _run(tmp_path, _ids(NULL={"n": 100, "p_fee": 0.5}), seed=1000 + s)
        hits += "rule holds" in res["NULL"]["verdict"] or res["NULL"]["verdict"].startswith("mixed")
    assert hits / reps <= 0.10  # nominal 5%; generous bound for 60 repetitions


def test_fifo_clause_uses_90pct_interval_of_arm_s_pooled_over_all_targets(tmp_path):
    cells_null = [{"arm": "P", "n": 400, "p_fee": 0.5}]
    # arm-S q_S near 0.5 with 300 pairs: 90% interval inside [0.35, 0.65], arrival order excluded, no remark
    res, doc, _ = _run(tmp_path, _ids(A={"cells": cells_null + [{"arm": "S", "n": 300, "p_send": 0.5}]}), seed=1)
    assert res["A"]["verdict"] == NO_RULE and doc["fifo"]["excluded"] is True
    # q_S = 1 (FIFO at arm S): remark stays
    res, doc, _ = _run(tmp_path, _ids(A={"cells": cells_null + [{"arm": "S", "n": 60, "p_send": 1.0}]}), seed=2)
    assert res["A"]["verdict"] == NO_RULE + FIFO_NOTE and doc["fifo"]["excluded"] is False
    # too few arm-S pairs for the interval to fit inside: remark stays
    res, _, _ = _run(tmp_path, _ids(A={"cells": cells_null + [{"arm": "S", "n": 20, "p_send": 0.5}]}), seed=3)
    assert res["A"]["verdict"] == NO_RULE + FIFO_NOTE


def test_fifo_clause_pools_arm_s_over_all_targets_and_reports_q_s_per_client(tmp_path):
    nul, s30 = {"arm": "P", "n": 400, "p_fee": 0.5}, {"arm": "S", "n": 30, "p_send": 0.5}
    v = {"A": {"client_id": "Agave", "role": "R1", "cells": [nul, s30]},
         "B": {"client_id": "JitoLabs", "role": "R2", "cells": [nul, s30]},
         "C": {"client_id": "Firedancer", "role": "R3", "cells": [nul]},
         "D": {"client_id": "AgaveBam", "role": "R4", "cells": [nul, s30]},
         "E": {"client_id": "FireBAM", "role": "R5", "cells": [nul, s30]}}
    res, doc, _ = _run(tmp_path, {k: {"version": "1", **x} for k, x in v.items()}, seed=4)
    pooled = doc["fifo"]["pooled_q_S"]
    by = doc["fifo"]["q_S_by_client_id"]
    assert pooled["n"] == 120 and doc["fifo"]["excluded"] is True          # 30 per client would not suffice, 120 pooled do
    assert by["values"]["Agave"]["ci90"][0] < 0.35 or by["values"]["Agave"]["ci90"][1] > 0.65
    assert all(u["verdict"] == NO_RULE for u in res.values()), {k: u["verdict"] for k, u in res.items()}   # also unit C without arm S
    assert by["label"] == "descriptive" and by["values"]["Agave"]["n"] == 30 and by["values"]["Firedancer"]["n"] == 0
    assert 0.35 < pooled["ci90"][0] and pooled["ci90"][1] < 0.65


def test_final_analyses_main_phase_real_data_only(tmp_path):
    v = _ids(A={"n": 120, "p_fee": 0.95})
    # real main-phase data: refused without --final, analysed with it
    res, doc, summ = _run(tmp_path, v, seed=1, final=False, mutate=_to_real)
    assert res == {} and summ["n_rows_refused"] == {"pilot": 0, "main": 120, "other_phase": 0} and doc["final"] is False
    res, doc, summ = _run(tmp_path, v, seed=2, final=True, mutate=_to_real)
    assert res["A"]["verdict"].startswith("fee rule holds") and doc["final"] is True and doc["confirmatory"] is True
    # synthetic data: analysed without --final, excluded with it (flagged records and files named synthetic-*)
    res, _, summ = _run(tmp_path, v, seed=3, final=False)
    assert res["A"]["fee"]["n"] == 120
    res, _, summ = _run(tmp_path, v, seed=4, final=True)
    assert res == {} and summ["n_rows_analysed"] == 0 and summ["n_rows_excluded"]["synthetic"] == 120
    res, _, summ = _run(tmp_path, v, seed=5, final=True, mutate=lambda raw: _edit_sent(raw, lambda r: r.pop("synthetic", None) and None))
    assert res == {} and summ["n_rows_excluded"]["synthetic"] == 120        # the file name alone marks it synthetic
    res, _, summ = _run(tmp_path, v, seed=6, final=False, mutate=lambda raw: _edit_sent(
        raw, lambda r: r.pop("synthetic", None) and None))
    assert res["A"]["fee"]["n"] == 120
    # pilot data: refused entirely without --final, excluded with it
    res, _, summ = _run(tmp_path, v, seed=7, final=False, mutate=lambda raw: _to_real(raw, "pilot"))
    assert res == {} and summ["n_rows_refused"]["pilot"] == 120 and summ["n_rows_analysed"] == 0
    res, _, summ = _run(tmp_path, v, seed=8, final=True, mutate=lambda raw: _to_real(raw, "pilot"))
    assert res == {} and summ["n_rows_excluded"]["pilot"] == 120 and summ["n_rows_analysed"] == 0


def test_cli_refuses_real_data_without_final_and_says_why(tmp_path, capsys):
    from itb.analyze import main
    raw = tmp_path / "raw"
    write_synthetic(str(raw), _ids(A={"n": 10}), seed=1)
    _to_real(raw, "pilot")
    assert main(["--raw", str(raw), "--out", str(tmp_path / "o")]) == 0
    out = capsys.readouterr().out
    assert "refusing 10 real probes (10 pilot, 0 main, 0 other)" in out and "only synthetic data are analysed" in out
    assert "NOT FINAL" in out
    assert main(["--raw", str(raw), "--out", str(tmp_path / "o2"), "--final"]) == 0
    out = capsys.readouterr().out
    assert "FINAL: main-phase data only; excluded 10 pilot, 0 synthetic" in out


def test_clientid_change_excludes_run_and_exclusions_are_counted(tmp_path):
    res, _, _ = _run(tmp_path, _ids(
        FLIP={"n": 50, "p_fee": 1.0, "claim_end_client_id": "Firedancer"},
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


def test_version_is_a_covariate_not_part_of_the_unit(tmp_path):
    """One identity observed under two versions in two runs is ONE unit; the split by version is descriptive only.
    A version change inside a run keeps the probes in the cell (labelled start>end)."""
    raw = tmp_path / "raw"
    ident = {"client_id": "Agave", "role": "R1"}
    write_synthetic(str(raw), {"A": {**ident, "version": "4.3.2", "n": 120, "p_fee": 0.8}}, seed=1)
    write_synthetic(str(raw), {"A": {**ident, "version": "4.4.0", "n": 100, "p_fee": 0.8},
                               "UP": {**ident, "version": "4.3.2", "n": 100, "p_fee": 0.8, "claim_end_version": "4.4.0"}}, seed=2)
    analyze(str(raw), str(tmp_path / "o"), dict(DEFAULTS))
    doc = json.load(open(tmp_path / "o" / "verdicts.json"))
    res = {u["identity"]: u for u in doc["units"]}
    a = res["A"]
    assert a["n_primary"] == 220 and "version" not in a and a["fee"]["n"] == 220       # one unit, both versions pooled
    split = {v["version"]: v for v in a["version_split"]["by_version"]}
    assert set(split) == {"4.3.2", "4.4.0"} and split["4.3.2"]["n_primary"] == 120 and split["4.4.0"]["n_primary"] == 100
    assert all("p_value" not in v["fee"] and "p_holm" not in v["fee"] and "p_value" not in v["send"] for v in split.values())
    assert "verdict" not in split["4.4.0"] and a["version_split"]["label"].startswith("descriptive")
    up = res["UP"]                                          # version changed during the run: kept, labelled start>end
    assert up["n_primary"] == 100 and up["exclusions"]["claim_changed_in_run"] == 0
    assert [v["version"] for v in up["version_split"]["by_version"]] == ["4.3.2>4.4.0"]
    assert len(open(tmp_path / "o" / "version_split.csv").read().splitlines()) == 1 + 2 + 1


def test_claim_end_unknown_probes_are_kept_and_counted(tmp_path):
    raw = tmp_path / "raw"
    write_synthetic(str(raw), _ids(A={"n": 120, "p_fee": 0.95, "role": "R1"}), seed=1, end_snapshot=False)
    analyze(str(raw), str(tmp_path / "o"), dict(DEFAULTS))
    doc = json.load(open(tmp_path / "o" / "verdicts.json"))
    u = doc["units"][0]
    assert u["n_primary"] == 120 and u["exclusions"]["claim_end_unknown"] == 120 and u["verdict"].startswith("fee rule holds")
    t = doc["claim_end_unknown"]
    assert t["total_all_arms"] == 120 and t["total_primary"] == 120 and t["by_unit"][0]["n_claim_end_unknown_arm_P"] == 120
    assert "n_claim_end_unknown_all_arms" in open(tmp_path / "o" / "claim_end_unknown.csv").read()


def test_outside_window_slot_excluded(tmp_path):
    def shift(raw):                                         # land every pair after the targeted window
        for f in glob.glob(str(raw / "*.landed.jsonl")):
            recs = [json.loads(x) for x in open(f)]
            for r in recs:
                r["slot"] += 10
            open(f, "w").write("".join(json.dumps(r) + "\n" for r in recs))
    res, _, _ = _run(tmp_path, _ids(A={"n": 30}), mutate=shift)
    assert res["A"]["n_primary"] == 0 and res["A"]["exclusions"]["target_outside_window"] == 30


def test_unit_is_role_identity_clientid_and_one_holm_family(tmp_path):
    raw = tmp_path / "raw"
    write_synthetic(str(raw), {"X": {"n": 100, "p_fee": 0.8, "client_id": "Agave", "version": "4.3.2", "role": "R1"},
                               "Y": {"n": 100, "p_fee": 0.6, "client_id": "JitoLabs", "version": "4.3.2", "role": "R2"}}, seed=1)
    analyze(str(raw), str(tmp_path / "o"), dict(DEFAULTS))
    doc = json.load(open(tmp_path / "o" / "verdicts.json"))
    us = doc["units"]
    assert {(u["target_role"], u["identity"], u["client_id"]) for u in us} == {("R1", "X", "Agave"), ("R2", "Y", "JitoLabs")}
    ps = [u[w]["p_value"] for u in us for w in ("fee", "send")]
    adj = holm(ps)
    got = [u[w]["p_holm"] for u in us for w in ("fee", "send")]
    assert np.allclose(adj, got) and doc["holm_family_size"] == 4
    # derived files exist
    for name in ("verdicts.csv", "table_2x2.csv", "logit.csv", "secondary.json", "version_split.csv", "claim_end_unknown.csv"):
        assert (tmp_path / "o" / name).exists()
    head = open(tmp_path / "o" / "verdicts.csv").readline().split(",")
    assert head[:3] == ["target_role", "identity", "client_id"] and "version" not in head[:4]


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
    assert sec["arm_S"][c]["q"]["p"] == 1.0 and sec["arm_S"][c]["q_rule"] == "request-position rule strict"
    assert set(sec["table_labels"].values()) == {"secondary, descriptive"} and "arm_S" in sec["table_labels"]
    assert "N rule" in sec["note"] or "no N rule" in sec["note"]
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


def test_fifo_clause_not_hidden_by_pooling():
    from itb.analyze import DEFAULTS, fifo_excluded
    cfg = dict(DEFAULTS)
    pooled_null = {"n": 112, "k": 56, "ci90": [0.42, 0.58]}
    assert fifo_excluded(pooled_null, {"n": 14, "k": 7}, cfg) is True
    assert fifo_excluded(pooled_null, {"n": 7, "k": 7}, cfg) is False      # own client 7/7 rejects 0.5 (p = 0.016)
    assert fifo_excluded({"n": 112, "k": 90, "ci90": [0.74, 0.86]}, {"n": 14, "k": 7}, cfg) is False
    assert fifo_excluded({"n": 0}, None, cfg) is False


def test_payer_conflict_flag():
    from itb.pairs import flag_payer_conflicts
    rows = [{"probe_id": "a", "same_slot": True, "slot": 10, "txs": [{"landed": True, "slot": 10, "payer": "P1"}, {"landed": True, "slot": 10, "payer": "P2"}]},
            {"probe_id": "b", "same_slot": False, "txs": [{"landed": True, "slot": 10, "payer": "P1"}, {"landed": False, "slot": None, "payer": "P3"}]},
            {"probe_id": "c", "same_slot": True, "slot": 11, "txs": [{"landed": True, "slot": 11, "payer": "P4"}, {"landed": True, "slot": 11, "payer": "P5"}]}]
    flag_payer_conflicts(rows)
    assert rows[0]["payer_conflict"] is True and rows[2]["payer_conflict"] is False
