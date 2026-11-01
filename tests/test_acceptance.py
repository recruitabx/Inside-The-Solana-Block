import base64
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "acceptance.py"
_spec = importlib.util.spec_from_file_location("acceptance", _SCRIPT)
acc = importlib.util.module_from_spec(_spec)
sys.modules["acceptance"] = acc
_spec.loader.exec_module(acc)

CAL = Path(__file__).resolve().parent.parent / "data" / "calibration" / "localnet_2026-10-30_final.jsonl"
PAYER = "B9Gj7heYv3KLxH2ojmhWAJTH2pv2tPYFqANqTZj7AUrG"


def _pair(cond, i, hi_label, first_label, first_lands, slot=100, same_slot=True, landed=True):
    """first_lands: label of the transaction with the lower block index."""
    txs = []
    for lab in (1, 2):
        txs.append({"label": lab, "sig": f"{cond}{i}-{lab}", "cu_price": 1_000_000 if lab == hi_label else 1_000, "send_pos": 0 if lab == first_label else 1,
                    "slot": (slot if same_slot or lab == 1 else slot + 1) if landed else None,
                    "index": (3 if lab == first_lands else 4) if landed else None, "err": None, "leader": "L"})
    return {"record": "pair", "condition": cond, "pair": i, "hi_label": hi_label, "first_label": first_label, "txs": txs}


def test_calibration_rows_convert_pairs_to_the_analysis_format():
    from itb.analyze import high_index, in_cell, outcomes
    recs = [_pair("A", 0, hi_label=1, first_label=2, first_lands=2),      # arrival order: sent first lands first, low fee first
            _pair("A", 1, hi_label=2, first_label=2, first_lands=2),
            _pair("B", 2, hi_label=1, first_label=2, first_lands=1),      # priority: high fee first although sent second
            _pair("A", 3, hi_label=1, first_label=1, first_lands=1, same_slot=False),     # different slots: left out
            _pair("A", 4, hi_label=1, first_label=1, first_lands=1, landed=False),        # did not land: left out
            {"record": "meta"}]
    rows = acc.calibration_rows(recs, "A")
    assert len(rows) == 2 and all(in_cell(r, "P") for r in rows)
    r0 = rows[0]
    assert [t["cu_price"] for t in r0["txs"]] == [1_000_000, 1_000] and r0["first_sent"] == 1 and r0["first_landed"] == 1
    assert high_index(r0) == 0 and outcomes(r0) == {"y_send": 1, "hi": 0, "y_fee": 0, "high_sent_first": 0}
    assert outcomes(rows[1])["y_send"] == 1 and outcomes(rows[1])["y_fee"] == 1
    b = acc.calibration_rows(recs, "B")
    assert len(b) == 1 and outcomes(b[0])["y_fee"] == 1 and outcomes(b[0])["y_send"] == 0
    assert b[0]["target_role"] == "control-B" and b[0]["claim_client_id"] == "Agave"


def _write_cal(path, a_rule, b_rule, n=60):
    """a_rule / b_rule: 'arrival' | 'priority' | 'none'"""
    recs, rng = [{"record": "meta", "validator": {"solana-core": "4.3.2"}}], np.random.default_rng(5)
    for cond, rule in (("A", a_rule), ("B", b_rule)):
        for i in range(n):
            hi, first = int(rng.integers(1, 3)), int(rng.integers(1, 3))
            lands = first if rule == "arrival" else hi if rule == "priority" else int(rng.integers(1, 3))
            recs.append(_pair(cond, i, hi, first, lands))
    path.write_text("".join(json.dumps(r) + "\n" for r in recs))
    return str(path)


def test_controls_pass_when_known_answers_are_recovered_and_fail_otherwise(tmp_path):
    ok = acc.check_controls(_write_cal(tmp_path / "ok.jsonl", "arrival", "priority"))
    assert ok["ok"] and [u["verdict"].split(",")[0] for u in ok["units"]] == ["request-position rule holds", "fee rule holds"]
    assert [u["n_same_slot"] for u in ok["units"]] == [60, 60]
    bad = acc.check_controls(_write_cal(tmp_path / "bad.jsonl", "arrival", "none"))
    assert not bad["ok"] and bad["units"][0]["ok"] and not bad["units"][1]["ok"]
    assert not acc.check_controls(str(tmp_path / "missing.jsonl"))["ok"]


def test_controls_are_exempt_from_the_n_rule(tmp_path):
    """60 pairs would be 'insufficient data (n=60)' under min_n = 100; the controls run with min_n = 0."""
    from itb.analyze import DEFAULTS, cell_estimates, decide, in_cell
    rows = acc.calibration_rows([json.loads(x) for x in open(_write_cal(tmp_path / "c.jsonl", "arrival", "priority"))], "A")
    fee, send = cell_estimates([r for r in rows if in_cell(r, "P")])
    u = {"fee": fee, "send": send}
    decide([u], dict(DEFAULTS), None)
    assert u["verdict"] == "insufficient data (n=60)"
    u = {"fee": fee, "send": send}
    decide([u], {**DEFAULTS, "min_n": 0}, None)
    assert u["verdict"].startswith("request-position rule holds")


@pytest.mark.skipif(not CAL.exists(), reason="calibration data not present")
def test_controls_on_the_committed_calibration_file():
    res = acc.check_controls(str(CAL))
    assert res["ok"], res
    assert res["units"][0]["verdict"].startswith("request-position rule holds") and res["units"][1]["verdict"].startswith("fee rule holds")


def test_simulate_counts_plants_independent_p_and_q():
    rng = np.random.default_rng(1)
    kf = ks = 0
    for _ in range(300):
        a, b = acc.simulate_counts(rng, 100, 0.75, 0.5); kf += a; ks += b
    assert abs(kf / 30000 - 0.75) < 0.02 and abs(ks / 30000 - 0.5) < 0.02
    kf = ks = 0
    for _ in range(300):
        a, b = acc.simulate_counts(rng, 100, 0.5, 1.0); kf += a; ks += b
    assert abs(kf / 30000 - 0.5) < 0.02 and ks == 30000
    assert acc.simulate_counts(rng, 100, 1.0, 0.5)[0] == 100


def test_synthetic_checks_run_and_are_sane_with_few_replicates():
    out = acc.check_synthetic(150, seed=11)
    assert out["replicates"] == 150 and len(out["coverage"]["rows"]) == 4
    assert out["coverage"]["min_coverage"] > 0.9 and out["false_rule"]["rate"] <= 0.10 and out["power"]["power"] > 0.7
    assert acc.claims_rule("fee rule holds, strict") and acc.claims_rule("mixed: fee rule partial and request-position rule partial")
    assert acc.claims_rule("reverse request-position rule holds, partial")
    assert not acc.claims_rule("no fee or request-position rule detected (|pi| <= 0.30); arrival order (FIFO) not excluded")
    assert not acc.claims_rule("insufficient data (n=60)")


class FakeRpc:
    units = {"high": 600, "low": 600}
    loaded = 235

    def __init__(self, *a, **k):
        pass

    def call(self, method, params=None):
        from solders.transaction import Transaction
        assert method == "simulateTransaction" and params[1]["sigVerify"] is False and params[1]["replaceRecentBlockhash"] is True
        tx = Transaction.from_bytes(base64.b64decode(params[0]))
        high = b"\x03" + (5_500_000).to_bytes(8, "little") in b"".join(bytes(i.data) for i in tx.message.instructions)
        return {"value": {"err": None, "unitsConsumed": FakeRpc.units["high" if high else "low"], "loadedAccountsDataSize": FakeRpc.loaded}}


def test_templates_check_builds_both_unsigned_templates_and_applies_the_limits(monkeypatch):
    monkeypatch.setattr("itb.rpc.Rpc", FakeRpc)
    FakeRpc.units, FakeRpc.loaded = {"high": 600, "low": 600}, 235
    res = acc.check_templates("http://unused", PAYER)
    assert res["ok"] and set(res["templates"]) == {"high", "low"} and res["payer"] == PAYER
    FakeRpc.units = {"high": 701, "low": 600}
    res = acc.check_templates("http://unused", PAYER)
    assert not res["ok"] and not res["templates"]["high"]["ok"] and res["templates"]["low"]["ok"]
    FakeRpc.units, FakeRpc.loaded = {"high": 600, "low": 600}, 4097
    assert not acc.check_templates("http://unused", PAYER)["ok"]
    FakeRpc.loaded = 235
    assert not acc.check_templates("http://unused", "not-a-key")["ok"]


def test_payer_is_the_public_key_from_accounts_or_wallet_pub(tmp_path, monkeypatch):
    from itb.simulate import funding_pubkey
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert funding_pubkey() is None
    (tmp_path / "ops").mkdir()
    (tmp_path / "ops" / "wallet.pub").write_text(PAYER + "\n")
    assert funding_pubkey() == PAYER
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "accounts.json").write_text(json.dumps({"wallet": "FromAccounts1111111111111111111111111111111", "payers": []}))
    assert funding_pubkey() == "FromAccounts1111111111111111111111111111111"        # accounts.json first


def test_main_prints_pass_or_fail_per_criterion(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("itb.rpc.Rpc", FakeRpc)
    FakeRpc.units, FakeRpc.loaded = {"high": 600, "low": 600}, 235
    cal = _write_cal(tmp_path / "c.jsonl", "arrival", "priority")
    rc = acc.main(["--replicates", "40", "--calibration", cal, "--payer", PAYER])
    out = capsys.readouterr().out
    for k in (1, 2, 3):
        assert f"CRITERION {k}: PASS" in out or f"CRITERION {k}: FAIL" in out
    assert "CRITERION 2: PASS" in out and "CRITERION 3: PASS" in out and ("ACCEPTANCE: PASS" in out) == (rc == 0)
    assert "request-position rule holds" in out and "send-order" not in out
    FakeRpc.units = {"high": 900, "low": 600}
    assert acc.main(["--replicates", "20", "--calibration", cal, "--payer", PAYER]) == 1
    assert "CRITERION 3: FAIL" in capsys.readouterr().out
