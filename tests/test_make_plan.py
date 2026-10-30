import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "make_plan.py"
_spec = importlib.util.spec_from_file_location("make_plan", _SCRIPT)
mp = importlib.util.module_from_spec(_spec)
sys.modules["make_plan"] = mp
_spec.loader.exec_module(mp)

ROLES = ["AgaveBam-1", "JitoLabs-1", "HarmonicAgave-1", "HarmonicFiredancer-1", "Firedancer-1", "FireBAM-1", "Rakurai-1", "Agave-1"]


def _validators(tmp_path):
    v = {"targets": [{"role": r, "identity": f"ID{i}", "clientId": r.split("-")[0], "version": "4.3.2"} for i, r in enumerate(ROLES)]}
    p = tmp_path / "validators.json"
    p.write_text(json.dumps(v))
    return str(p)


def _plan(tmp_path, *extra):
    out = tmp_path / "plan.json"
    rc = mp.main(["--validators", _validators(tmp_path), "--out", str(out), "--seed", "1", *extra])
    return rc, out


def test_default_quotas_and_fee_total_match_preregistration(tmp_path, capsys):
    rc, out = _plan(tmp_path)
    assert rc == 0
    plan = json.load(open(out))
    q = {t["role"]: t["quota_per_target"] for t in plan["targets"]}
    assert [q[r] for r in ROLES] == [343] * 6 + [282, 282]
    assert plan["n_payers"] == 6 and "n_payers_pilot" not in plan
    assert plan["pilot_per_target"] == 12 and plan["pilot_s_per_target"] == 2 and plan["tau0_ms"] is None
    f = plan["planned_fees"]
    assert f["main_run_fees"] == 39_356_856 and f["pilot_fees_with_repilot"] == 3_472_224 and f["operations"] == 500_000
    assert f["planned_fee_total"] == 43_329_080 and f["peak_funding_need"] == 43_329_080 + 6 * 890_880 == 48_674_360
    out_txt = capsys.readouterr().out
    assert "planned fee total = 43,329,080" in out_txt and "peak funding need = fee total + 6 x 890,880 rent" in out_txt
    shares = {t["role"]: t["shares"] for t in plan["targets"]}
    assert shares["AgaveBam-1"] == {"P": 0.70, "E": 0.10, "D": 0.10, "S": 0.10} and shares["Agave-1"]["P"] == 0.85


def test_pair_fees_and_u_pilot_formula(tmp_path):
    assert mp.pair_fees() == {"contrast": 15_501, "equal": 10_002}
    assert abs(mp.mean_pair_fee(mp.SHARES_HIGH) - 14_951.1) < 1e-9 and abs(mp.mean_pair_fee(mp.SHARES_85) - 15_226.05) < 1e-9
    rc, out = _plan(tmp_path, "--u-pilot", "0.60", "--tau0-ms", "-170")
    q = {t["role"]: t["quota_per_target"] for t in json.load(open(out))["targets"]}
    assert q["AgaveBam-1"] == -(-115 * 100 // 42) == 274 and q["Rakurai-1"] == -(-115 * 100 // 51) == 226     # ceil(115/(0.70*0.60)), ceil(115/(0.85*0.60))
    assert json.load(open(out))["tau0_ms"] == -170
    plan, rep = mp.build_plan(json.load(open(_validators(tmp_path))), 1, None, 0.40, False)    # would be refused, see below
    assert rep["planned_fee_total"] > 46_000_000
    q = {t["role"]: t["quota_per_target"] for t in plan["targets"]}
    assert q["AgaveBam-1"] == 411 and q["Rakurai-1"] == 330 and q["Agave-1"] == 330          # low-window targets capped at 330


def test_shares_all_85_fallback(tmp_path):
    rc, out = _plan(tmp_path, "--shares-all-85", "--u-pilot", "0.40")
    plan = json.load(open(out))
    assert rc == 0 and plan["shares_all_85"] is True
    assert all(t["shares"] == {"P": 0.85, "E": 0.05, "D": 0.05, "S": 0.05} for t in plan["targets"])
    q = {t["role"]: t["quota_per_target"] for t in plan["targets"]}
    assert q["AgaveBam-1"] == 339 and q["Rakurai-1"] == 330 and q["Agave-1"] == 330          # ceil(115/(0.85*0.40)) = 339
    rc, out = _plan(tmp_path, "--shares-all-85")
    assert {t["quota_per_target"] for t in json.load(open(out))["targets"]} == {282}


def test_plan_refused_above_46_million(tmp_path, capsys):
    out = tmp_path / "plan.json"
    rc = mp.main(["--validators", _validators(tmp_path), "--out", str(out), "--seed", "1", "--u-pilot", "0.35"])
    assert rc == 1 and not out.exists()
    assert "REFUSED" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        mp.main(["--validators", _validators(tmp_path), "--out", str(out), "--seed", "1", "--u-pilot", "0"])
