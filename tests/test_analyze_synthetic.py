import json

from itb.analyze import DEFAULTS, analyze
from itb.synthetic import write_synthetic


def _run(tmp_path, validators, seed=0):
    raw = tmp_path / f"raw{seed}"
    write_synthetic(str(raw), validators, seed=seed)
    analyze(str(raw), str(tmp_path / f"out{seed}"), dict(DEFAULTS))
    v = json.load(open(tmp_path / f"out{seed}" / "verdicts.json"))["validators"]
    return {x["leader"]: x for x in v}


def test_planted_fee_rule_recovered_and_null_called_null(tmp_path):
    res = _run(tmp_path, {"FEE": {"n": 200, "p_fee": 0.99}, "NULL": {"n": 400, "p_fee": 0.5},
                          "SMALL": {"n": 20, "p_fee": 0.5}, "SEND": {"n": 200, "p_fee": 0.5, "p_send": 0.99},
                          "PART": {"n": 300, "p_fee": 0.68}})
    assert res["FEE"]["verdict"] == "fee rule holds, strict", res["FEE"]["verdict"]
    assert res["NULL"]["verdict"] == "no detectable rule", res["NULL"]["verdict"]
    assert res["SMALL"]["verdict"].startswith("insufficient data")
    assert res["SEND"]["verdict"] == "send-order rule holds, strict", res["SEND"]["verdict"]
    assert res["PART"]["verdict"] == "fee rule holds, partial", res["PART"]["verdict"]


def test_false_positive_rate_on_random_order(tmp_path):
    hits = 0
    reps = 60
    for s in range(reps):
        res = _run(tmp_path, {"NULL": {"n": 100, "p_fee": 0.5}}, seed=1000 + s)
        hits += res["NULL"]["verdict"].startswith(("fee rule", "mixed"))
    assert hits / reps <= 0.10  # nominal 5%; generous bound for 60 repetitions
