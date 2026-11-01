import json

from itb import enrich
from itb.blocks import b58encode
from itb.collector_cli import collect_run
from itb.config import MEMO_PROGRAM_ID
from itb.rpc import RpcError

CB = "ComputeBudget111111111111111111111111111111"


def _tx(i, memo=None, limit=None, consumed=300, cost=1500, fee=5000):
    keys = ["Payer", MEMO_PROGRAM_ID, CB, "Prog"]
    ixs = [{"programIdIndex": 3, "accounts": [], "data": ""}]
    if memo:
        ixs.append({"programIdIndex": 1, "accounts": [], "data": b58encode(memo.encode())})
    if limit:
        ixs.append({"programIdIndex": 2, "accounts": [], "data": b58encode(bytes([2]) + limit.to_bytes(4, "little"))})
    return {"version": "legacy", "transaction": {"signatures": [f"s{i}"], "message": {"accountKeys": keys, "instructions": ixs}},
            "meta": {"fee": fee, "costUnits": cost, "computeUnitsConsumed": consumed, "err": None,
                     "loadedAddresses": {"writable": [], "readonly": []}}}


def _block(txs, producer="PRODUCER"):
    return {"blockTime": 1, "transactions": txs, "rewards": [{"pubkey": producer, "rewardType": "Fee", "lamports": 1}]}


class FakeRpc:
    def __init__(self, blocks):
        self.blocks, self.calls = blocks, []

    def call(self, method, params=None):
        assert method == "getBlock"
        slot, opts = params
        self.calls.append(slot)
        assert opts["transactionDetails"] == "full" and opts["rewards"] is True
        if slot in self.blocks:
            return self.blocks[slot]
        if slot == 7:
            raise RpcError("getBlock", {"code": -32004, "message": "Block not available for slot 7"})
        raise RpcError("getBlock", {"code": -32007, "message": "Slot was skipped"})


def test_strategy_memo_matches_documented_format_only():
    assert enrich.strategy_memo(_block([_tx(0), _tx(1, memo="FBA")])) == ("FBA", 1)
    assert enrich.strategy_memo(_block([_tx(0, memo="MRV"), _tx(1, memo="FIF")])) == ("MRV", 0)
    assert enrich.strategy_memo(_block([_tx(0, memo="BAL"), _tx(1, memo="FBA extra"), _tx(2, memo="fba")])) == (None, None)
    assert enrich.strategy_memo(_block([_tx(0)])) == (None, None)


def test_summary_fields_and_ten_percent_sample():
    b = _block([_tx(0, memo="FIF", limit=1000), _tx(1, consumed=700, cost=2000)])
    s = enrich.summarize_block(b, 1001)
    assert (s["slot"], s["producer"], s["tx_count"], s["cu_consumed_total"]) == (1001, "PRODUCER", 2, 1000)
    assert s["strategy"] == "FIF" and s["strategy_tx_index"] == 0 and s["sampled"] is False and "tx_rows" not in s
    s = enrich.summarize_block(b, 1000)                                  # slot % 10 == 0: per-transaction rows
    assert s["sampled"] is True and s["tx_cols"] == enrich.TX_COLS
    row = dict(zip(s["tx_cols"], s["tx_rows"][0]))
    assert row["index"] == 0 and row["requested_cu_limit"] == 1000 and row["cu_consumed"] == 300 and row["nsig"] == 1
    assert row["vote"] is False and row["jito_tip"] is False and row["fee"] == 5000 and row["cost_units"] == 1500
    assert dict(zip(s["tx_cols"], s["tx_rows"][1]))["requested_cu_limit"] == 200_000   # default: one non-budget instruction


def _sent(tmp_path):
    recs = [{"record": "run_start", "run_id": "r", "targets_client_now": {"HARM": "HarmonicAgave", "AG": "Agave"}},
            {"record": "probe", "mode": "live", "probe_id": "r:0", "target_leader": "HARM", "window_first_slot": 2000,
             "send_results": ["ok", "ok"], "txs": [{"signature": "a"}, {"signature": "b"}]},
            {"record": "probe", "mode": "live", "probe_id": "r:1", "target_leader": "AG", "window_first_slot": 3000,
             "send_results": ["ok", "ok"], "txs": [{"signature": "c"}, {"signature": "d"}]},
            {"record": "probe", "mode": "live", "probe_id": "r:2", "target_leader": "HARM", "window_first_slot": 4004,
             "send_results": ["ok", "ok"], "txs": [{"signature": "e"}, {"signature": "f"}]}]
    return recs


def test_slots_are_landed_slots_plus_first_slot_of_harmonic_windows():
    landed = [{"record": "landed", "slot": 3001}, {"record": "landed", "slot": 3001}, {"record": "not_landed"}]
    assert enrich.slots_to_summarize(_sent(None), landed) == [2000, 3001, 4004]


def test_enrich_run_is_idempotent_and_records_skipped_slots(tmp_path):
    blocks = {2000: _block([_tx(0, memo="FBA")]), 3001: _block([_tx(0)]), 4004: _block([_tx(0)])}
    rpc = FakeRpc(blocks)
    landed = [{"record": "landed", "slot": 3001}, {"record": "landed", "slot": 3002}, {"record": "landed", "slot": 7}]
    path = str(tmp_path / "r.blocks.jsonl")
    rep = enrich.enrich_run(path, _sent(None), landed, rpc)
    assert rep["new"] == 3 and rep["skipped_slots"] == 1 and rep["errors"] == 1      # 3002 skipped, slot 7 not available yet
    recs = [json.loads(x) for x in open(path)]
    assert sorted(r["slot"] for r in recs) == [2000, 3001, 3002, 4004]
    assert [r for r in recs if r["slot"] == 3002][0]["skipped"] is True
    assert [r for r in recs if r["slot"] == 2000][0]["strategy"] == "FBA"
    n_calls = len(rpc.calls)
    rep = enrich.enrich_run(path, _sent(None), landed, rpc)
    assert rep["new"] == 0 and len(rpc.calls) == n_calls + 1                         # only the unavailable slot 7 is retried
    assert len([x for x in open(path)]) == 4


def test_collect_run_writes_blocks_file_next_to_landed(tmp_path, monkeypatch):
    import itb.collector_cli as cc
    sent = tmp_path / "r.sent.jsonl"
    recs = _sent(None)
    for r in recs:
        if r["record"] == "probe":
            r["mode"] = "live"
    sent.write_text("".join(json.dumps(r) + "\n" for r in recs))
    monkeypatch.setattr(cc, "landed_records", lambda rpc, s, clients, cache, clients_end=None: [{"record": "landed", "signature": "a", "slot": 3001}])
    rpc = FakeRpc({2000: _block([_tx(0, memo="MRV")]), 3001: _block([_tx(0)]), 4004: _block([_tx(0)])})
    rep = collect_run(str(sent), rpc, None)
    assert rep["blocks"]["new"] == 3 and (tmp_path / "r.blocks.jsonl").exists() and (tmp_path / "r.landed.jsonl").exists()
    rep = collect_run(str(sent), rpc, None, enrich=False)
    assert "blocks" not in rep
