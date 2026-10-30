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
        raise AssertionError(method)

    def batch(self, calls, retry=True):
        FakeRpc.calls += [m for m, _ in calls]
        return [{"result": "sig"} for _ in calls]


PLAN = {"seed": 1, "n_payers": 4, "targets": [{"identity": TARGET, "role": "X-1"}], "cu_price_levels": [1, 1000],
        "cu_limit": 600, "send_offsets_slots": [0], "min_offset_slots": 0, "memo": False}


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
    for f in (tmp / "data" / "raw").glob("*.sent.jsonl"):
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
    monkeypatch.setenv("ITB_SPEND_CAP_LAMPORTS", "9000")  # less than one probe (2 x 5001)
    runner.main(["--live", "--minutes", "0.08"])
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
    monkeypatch.setenv("ITB_SPEND_CAP_LAMPORTS", "30000")  # room for 2 probes of 2 tx (10002 each)
    runner.main(["--live", "--minutes", "0.15"])
    n_sent = FakeRpc.calls.count("sendTransaction")
    led = [json.loads(x) for x in (env / "data" / "ledger" / "spend.jsonl").read_text().splitlines()]
    assert n_sent == len(led) == 4  # every send was reserved; third probe hit the cap
    assert any(r["record"] == "probe_aborted_cap" for r in _records(env))


def test_cap_above_ceiling_refused(env, monkeypatch):
    monkeypatch.setenv("ITB_LIVE", "1")
    monkeypatch.setenv("ITB_SPEND_CAP_LAMPORTS", str(50_000_001))
    with pytest.raises(SystemExit):
        runner.main(["--live", "--minutes", "0.05"])
