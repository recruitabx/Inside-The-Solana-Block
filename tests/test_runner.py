import json
import os
import time

import pytest
from solders.keypair import Keypair

import itb.runner as runner

T0 = time.time()
TARGET = str(Keypair().pubkey())
OTHER = str(Keypair().pubkey())


class FakeRpc:
    calls: list = []

    def __init__(self, *a, **k):
        self.host = "fake"

    def _slot(self):
        return 470_000_000 + int((time.time() - T0) / 0.2)

    def call(self, method, params=None):
        FakeRpc.calls.append(method)
        if method == "getSlot":
            return self._slot()
        if method == "getClusterNodes":
            return [{"pubkey": TARGET, "clientId": "Agave", "version": "4.3.2"}]
        if method == "getVoteAccounts":
            return {"current": [{"nodePubkey": TARGET, "activatedStake": 10}], "delinquent": []}
        if method == "getSlotLeaders":
            start, n = params
            return [TARGET if ((start + i) // 4) % 2 == 0 else OTHER for i in range(n)]
        if method == "getLatestBlockhash":
            return {"value": {"blockhash": "11111111111111111111111111111111"}}
        if method == "getSignatureStatuses":
            return {"value": [{"slot": 1} for _ in params[0]]}
        raise AssertionError(method)

    def batch(self, calls, retry=True):
        FakeRpc.calls += [m for m, _ in calls]
        return [{"result": "sig"} for _ in calls]


PLAN = {"seed": 1, "n_payers": 10, "targets": [{"identity": TARGET, "role": "X-1"}],
        "shares": {"P": 0.7, "E": 0.1, "D": 0.1, "S": 0.1}, "price_high": 5_500_000, "price_low": 1_000,
        "cu_limit": 1000, "loaded_limit": 4096, "gap_ms": 200, "tau0_ms": -170, "tau0_grid_ms": [-270, -170, -70],
        "min_request_interval_s": 0.5, "quota_per_target": 300, "pilot_per_target": 12}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner, "Rpc", FakeRpc)
    import itb.leaders as leaders
    monkeypatch.setattr(leaders, "Rpc", FakeRpc, raising=False)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "plan.json").write_text(json.dumps(PLAN))
    FakeRpc.calls = []
    return tmp_path


def _records(tmp):
    out = []
    for f in list((tmp / "data" / "raw").glob("*.sent.jsonl")) + list((tmp / "data" / "dryrun").glob("*.sent.jsonl")):
        out += [json.loads(x) for x in f.read_text().splitlines()]
    return out


def test_dry_run_sends_nothing(env):
    runner.main(["--minutes", "0.08"])
    assert "sendTransaction" not in FakeRpc.calls
    recs = _records(env)
    probes = [r for r in recs if r["record"] == "probe"]
    assert probes and all(r["mode"] == "dry" for r in probes)
    assert all(len(r["txs"]) == 2 for r in probes)


def test_live_flag_without_env_refuses(env, monkeypatch):
    monkeypatch.delenv("ITB_LIVE", raising=False)
    with pytest.raises(SystemExit):
        runner.main(["--live", "--minutes", "0.05"])
    assert "sendTransaction" not in FakeRpc.calls


def test_live_stops_at_cap_without_sending(env, monkeypatch):
    w = env / "w.json"
    w.write_text(json.dumps(list(bytes(Keypair()))))
    os.chmod(w, 0o600)
    monkeypatch.setenv("ITB_LIVE", "1")
    monkeypatch.setenv("ITB_WALLET", str(w))
    monkeypatch.setenv("ITB_SPEND_CAP_LAMPORTS", "9000")  # less than one probe (>= 10,002)
    runner.main(["--live", "--minutes", "0.08", "--no-anchor"])
    assert "sendTransaction" not in FakeRpc.calls
    recs = _records(env)
    assert any(r["record"] == "probe_aborted_cap" for r in recs)
    assert not (env / "data" / "ledger" / "spend.jsonl").exists() or (env / "data" / "ledger" / "spend.jsonl").read_text() == ""


def test_live_sends_and_reserves_before_sending(env, monkeypatch):
    w = env / "w.json"
    w.write_text(json.dumps(list(bytes(Keypair()))))
    os.chmod(w, 0o600)
    monkeypatch.setenv("ITB_LIVE", "1")
    monkeypatch.setenv("ITB_WALLET", str(w))
    monkeypatch.setenv("ITB_SPEND_CAP_LAMPORTS", "36000")  # anchor 5,000 + room for about 2 probes
    runner.main(["--live", "--minutes", "0.3"])
    n_sent = FakeRpc.calls.count("sendTransaction")
    led = [json.loads(x) for x in (env / "data" / "ledger" / "spend.jsonl").read_text().splitlines()]
    assert n_sent == len(led) >= 3  # anchor + every probe tx was reserved before sending
    assert sum(r["max_fee"] for r in led) <= 36000
    assert any(r["record"] == "probe_aborted_cap" for r in _records(env))


def test_cap_above_ceiling_refused(env, monkeypatch):
    monkeypatch.setenv("ITB_LIVE", "1")
    monkeypatch.setenv("ITB_SPEND_CAP_LAMPORTS", str(50_000_001))
    with pytest.raises(SystemExit):
        runner.main(["--live", "--minutes", "0.05"])


def _probes(tmp):
    return [r for r in _records(tmp) if r["record"] == "probe"]


def test_probe_randomness_comes_from_window_key(env):
    """The arm and the assignments are a pure function of (seed, window first slot, target)."""
    import random

    from itb import design
    runner.main(["--minutes", "0.12", "--max-probes", "3"])
    probes = _probes(env)
    assert probes
    for r in probes:
        key = f"{PLAN['seed']}:{r['window_first_slot']}:{r['target_leader']}"
        assert r["rng_key"] == key
        spec = design.make_probe(random.Random(key), PLAN, PLAN["targets"][0])
        assert (r["arm"], r["hi_idx"], r["send_order"]) == (spec["arm"], spec["hi_idx"], spec["order"])
        assert r["s_low_first"] == spec["s_low_first"]
        assert r["target_client_id"] == "Agave" and r["target_version"] == "4.3.2"
    end = [x for x in _records(env) if x["record"] == "run_end"][0]
    assert end["snapshot_end"].startswith("data/snapshots/clients_") and os.path.exists(env / end["snapshot_end"])
    assert end["targets_client_end"] == {TARGET: "Agave"} and end["targets_version_end"] == {TARGET: "4.3.2"}
    assert end["claim_changed"] == {TARGET: False}
    # the start snapshot is not overwritten by the end snapshot
    start = [x for x in _records(env) if x["record"] == "run_start"][0]
    assert start["snapshot"] != end["snapshot_end"]


def test_end_snapshot_detects_claim_change(env, monkeypatch):
    state = {"version": "4.3.2"}
    orig = FakeRpc.call

    def call(self, method, params=None):
        if method == "getClusterNodes":
            return [{"pubkey": TARGET, "clientId": "Agave", "version": state["version"]}]
        return orig(self, method, params)

    monkeypatch.setattr(FakeRpc, "call", call)
    orig_main = runner.client_snapshot
    n = {"k": 0}

    def snap(rpc):
        n["k"] += 1
        if n["k"] == 2:           # the second snapshot is the end-of-run one
            state["version"] = "4.4.0"
        return orig_main(rpc)

    monkeypatch.setattr(runner, "client_snapshot", snap)
    runner.main(["--minutes", "0.05", "--max-probes", "1"])
    end = [x for x in _records(env) if x["record"] == "run_end"][0]
    assert end["claim_changed"] == {TARGET: True} and end["targets_version_end"] == {TARGET: "4.4.0"}


def test_pilot_phase_mix_and_tau_cycle(env):
    plan = dict(PLAN, pilot_per_target=2, pilot_s_per_target=1, tau0_grid_ms=[-270, -170, -70])
    (env / "data" / "plan.json").write_text(json.dumps(plan))
    runner.main(["--phase", "pilot", "--minutes", "0.3", "--max-probes", "3"])
    probes = _probes(env)
    assert [r["arm"] for r in probes] == ["P", "P", "S"]
    assert [r["tau0_ms"] for r in probes[:2]] == [-270, -170]       # P probes cycle the grid
    s = probes[2]
    assert s["gap_s"] == 0.2 and s["s_low_first"] in (True, False) and len(s["send_order"]) == 2
    assert all(r["phase"] == "pilot" for r in probes)


def test_pilot_arm_sequence():
    from itb import design
    plan = {"pilot_per_target": 12, "pilot_s_per_target": 2}
    arms = [design.pilot_arm(i, plan) for i in range(14)]
    assert arms.count("S") == 2 and arms.count("P") == 12 and arms[6] == "S" and arms[13] == "S"
    assert design.pilot_arm(0, {"pilot_per_target": 12, "pilot_s_per_target": 0}) == "P"


class VirtualTime:
    def __init__(self):
        self.t = 1_000_000.0

    def time(self):
        return self.t

    def sleep(self, d):
        self.t += d


def test_wait_until_syncs_every_two_seconds_but_not_faster_than_one_per_second(monkeypatch):
    import itb.leaders as leaders
    vt = VirtualTime()
    t0 = vt.t
    monkeypatch.setattr(runner, "time", vt)
    monkeypatch.setattr(leaders, "time", vt)
    calls = []

    class R:
        def call(self, method, params=None):
            assert method == "getSlot"
            calls.append(vt.t)
            vt.t += 0.05                      # round trip
            return 470_000_000 + int((vt.t - t0) / 0.2143)

    clock = leaders.SlotClock(R())
    clock.sync()
    for _ in range(5):                        # hammering sync() inside one second costs one call only
        clock.sync()
    assert len(calls) == 1
    target = t0 + 31.0
    runner.wait_until(clock, lambda: target)
    assert vt.t >= target and vt.t - target < 0.3
    gaps = [b - a for a, b in zip(calls, calls[1:])]
    assert max(gaps) <= 2.4 and min(gaps) >= 0.95, gaps
    assert calls[-1] < target - 0.4           # no call in the last half second before the send
    assert abs(clock.slot_s - 0.2143) < 0.002  # refit from samples spanning more than 5 s
