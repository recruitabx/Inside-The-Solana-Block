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
ROOM = 43_000_000


def _validators(tmp_path):
    v = {"targets": [{"role": r, "identity": f"ID{i}", "clientId": r.split("-")[0], "version": "4.3.2",
                      "replacements": [{"identity": f"ID{i}r{k}", "clientId": r.split("-")[0], "version": "4.3.2"} for k in (1, 2, 3)]}
                     for i, r in enumerate(ROLES)]}
    p = tmp_path / "validators.json"
    p.write_text(json.dumps(v))
    return str(p)


def _args(tmp_path, *extra, room=ROOM, spent="0"):
    out = tmp_path / "plan.json"
    return ["--validators", _validators(tmp_path), "--out", str(out), "--seed", "1", "--fee-room", str(room), "--pilot-spent", spent, *extra], out


def _plan(tmp_path, *extra, **kw):
    argv, out = _args(tmp_path, *extra, **kw)
    return mp.main(argv), out


def test_default_quotas_candidates_and_planned_fees(tmp_path, capsys):
    rc, out = _plan(tmp_path)
    assert rc == 0
    plan = json.load(open(out))
    q = {t["role"]: t["quota_per_target"] for t in plan["targets"]}
    assert [q[r] for r in ROLES] == [343] * 6 + [282, 282]
    assert plan["n_payers"] == 6 and plan["pilot_per_target"] == 12 and plan["pilot_s_per_target"] == 2 and plan["tau0_ms"] is None
    t0 = plan["targets"][0]                                   # targets are ROLES with an ordered candidate list
    assert t0["role"] == "AgaveBam-1" and t0["clientId"] == "AgaveBam" and t0["candidates"] == ["ID0", "ID0r1", "ID0r2", "ID0r3"]
    f = plan["planned_fees"]
    assert f["main_run_fees"] == 39_356_856 and f["pilot_spent"] == 0 and f["operations"] == 500_000
    assert f["planned_fee_total"] == 39_856_856 and f["fee_room"] == ROOM and f["scaled_to_room"] is False
    assert "planned fee total = 39,856,856" in capsys.readouterr().out
    shares = {t["role"]: t["shares"] for t in plan["targets"]}
    assert shares["AgaveBam-1"] == {"P": 0.70, "E": 0.10, "D": 0.10, "S": 0.10} and shares["Agave-1"]["P"] == 0.85


def test_pair_fees_and_u_pilot_formula(tmp_path):
    assert mp.pair_fees() == {"contrast": 15_501, "equal": 10_002}
    assert abs(mp.mean_pair_fee(mp.SHARES_HIGH) - 14_951.1) < 1e-9 and abs(mp.mean_pair_fee(mp.SHARES_85) - 15_226.05) < 1e-9
    rc, out = _plan(tmp_path, "--u-pilot", "0.60", "--tau0-ms", "-170")
    q = {t["role"]: t["quota_per_target"] for t in json.load(open(out))["targets"]}
    assert q["AgaveBam-1"] == -(-115 * 100 // 42) == 274 and q["Rakurai-1"] == -(-115 * 100 // 51) == 226     # ceil(115/(0.70*0.60)), ceil(115/(0.85*0.60))
    assert json.load(open(out))["tau0_ms"] == -170
    plan, rep = mp.build_plan(json.load(open(_validators(tmp_path))), 1, None, 0.40, False, ROOM, 0)    # would be refused, see below
    assert rep["planned_fee_total"] > ROOM
    q = {t["role"]: t["quota_per_target"] for t in plan["targets"]}
    assert q["AgaveBam-1"] == 411 and q["Rakurai-1"] == 330 and q["Agave-1"] == 330          # low-window roles capped at 330


def test_shares_all_85_fallback(tmp_path):
    rc, out = _plan(tmp_path, "--shares-all-85", "--u-pilot", "0.40")
    plan = json.load(open(out))
    assert rc == 0 and plan["shares_all_85"] is True
    assert all(t["shares"] == {"P": 0.85, "E": 0.05, "D": 0.05, "S": 0.05} for t in plan["targets"])
    q = {t["role"]: t["quota_per_target"] for t in plan["targets"]}
    assert q["AgaveBam-1"] == 339 and q["Rakurai-1"] == 330 and q["Agave-1"] == 330          # ceil(115/(0.85*0.40)) = 339
    rc, out = _plan(tmp_path, "--shares-all-85")
    assert {t["quota_per_target"] for t in json.load(open(out))["targets"]} == {282}


def test_plan_refused_above_the_funded_fee_room(tmp_path, capsys):
    # pilot spent 3,000,000 + operations 500,000 + main 39,356,856 = 42,856,856
    rc, out = _plan(tmp_path, room=42_856_855, spent="3000000")
    assert rc == 1 and not out.exists()
    err = capsys.readouterr().err
    assert "REFUSED" in err and "42,856,856" in err and "42,856,855" in err
    rc, out = _plan(tmp_path, room=42_856_856, spent="3000000")                    # exactly the room: accepted
    assert rc == 0 and json.load(open(out))["planned_fees"]["planned_fee_total"] == 42_856_856
    with pytest.raises(SystemExit):
        mp.main(["--validators", _validators(tmp_path), "--out", str(out), "--seed", "1", "--u-pilot", "0", "--fee-room", "1", "--pilot-spent", "0"])


def test_fee_room_pilot_spent_and_seed_are_required(tmp_path):
    base = ["--validators", _validators(tmp_path), "--out", str(tmp_path / "p.json")]
    for argv in (base + ["--seed", "1", "--pilot-spent", "0"], base + ["--seed", "1", "--fee-room", "1"],
                 base + ["--fee-room", "1", "--pilot-spent", "0"]):
        with pytest.raises(SystemExit) as e:
            mp.main(argv)
        assert e.value.code == 2
    with pytest.raises(SystemExit):
        mp.main(base + ["--seed", "1", "--fee-room", "0", "--pilot-spent", "0"])


def test_pilot_spent_is_read_from_the_ledger(tmp_path):
    led = tmp_path / "spend.jsonl"
    rows = [{"kind": "reserve", "sig": "a", "max_fee": 10_500, "tag": "pilot:r:0"}, {"kind": "settle", "sig": "a", "actual_fee": 10_400},
            {"kind": "reserve", "sig": "b", "max_fee": 5_001, "tag": "pilot:r:0"}, {"kind": "settle", "sig": "b", "actual_fee": 5_001},
            {"kind": "reserve", "sig": "c", "max_fee": 5_000, "tag": "anchor:r"}, {"kind": "settle", "sig": "c", "actual_fee": 5_000},
            {"kind": "reserve", "sig": "d", "max_fee": 5_000, "tag": "pilot:r:1"}]            # open reservation: not spent
    led.write_text("".join(json.dumps(r) + "\n" for r in rows))
    rc, out = _plan(tmp_path, "--ledger", str(led), spent="ledger")
    assert rc == 0 and json.load(open(out))["planned_fees"]["pilot_spent"] == 20_401  # every settled fee counts (pilot, re-pilot, anchors, funding); open reservations do not
    rc, out = _plan(tmp_path, "--ledger", str(tmp_path / "missing.jsonl"), spent="ledger")
    assert rc == 0 and json.load(open(out))["planned_fees"]["pilot_spent"] == 0


def test_scale_to_room_scales_quotas_down_proportionally_and_reports_low_roles(tmp_path, capsys):
    room = 30_000_000
    rc, out = _plan(tmp_path, "--scale-to-room", room=room, spent="1736112")
    assert rc == 0
    plan = json.load(open(out))
    f = plan["planned_fees"]
    q = {t["role"]: t["quota_per_target"] for t in plan["targets"]}
    unscaled_main = 39_356_856
    factor = (room - 1_736_112 - 500_000) / unscaled_main
    assert f["scaled_to_room"] is True and abs(f["scale_factor"] - factor) < 1e-9 and f["planned_fee_total_unscaled"] > room
    assert q["AgaveBam-1"] == int(343 * factor) and q["Rakurai-1"] == int(282 * factor)          # floor of the proportional share
    assert f["planned_fee_total"] <= room and f["planned_fee_total"] > room - 2 * 8 * 15_501       # and no more than the floor loses
    below = {r for r, x in f["projected_usable"].items() if x < 100}                                  # quota x share_P x u < 100
    assert set(f["roles_below_100_usable"]) == below == set(ROLES)                                    # 0.77 of the quotas leaves every role under 100
    out_txt = capsys.readouterr().out
    assert "quotas scaled by" in out_txt and "roles projected below 100 usable: " in out_txt and "AgaveBam-1" in out_txt
    # a tight scale leaves some roles above 100 usable and some below
    rc, out = _plan(tmp_path, "--scale-to-room", room=39_000_000, spent="1736112")
    f = json.load(open(out))["planned_fees"]
    assert rc == 0 and f["planned_fee_total"] <= 39_000_000 and f["roles_below_100_usable"] == []
    # without --scale-to-room the same room is refused; with enough room nothing is scaled
    rc, _ = _plan(tmp_path, room=room, spent="1736112")
    assert rc == 1
    rc, out = _plan(tmp_path, "--scale-to-room", room=ROOM)
    assert rc == 0 and json.load(open(out))["planned_fees"]["scaled_to_room"] is False
    assert json.load(open(out))["targets"][0]["quota_per_target"] == 343


def test_scale_to_room_with_no_room_for_the_main_run_is_refused(tmp_path):
    rc, out = _plan(tmp_path, "--scale-to-room", room=2_000_000, spent="1736112")      # room - pilot - operations < 0
    assert rc == 1 and not out.exists()
