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
