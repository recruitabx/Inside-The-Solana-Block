from itb.collect import landed_records
from itb.config import MIN_SLOT


class R:
    def call(self, method, params=None):
        if method == "getSignatureStatuses":
            return {"value": [{"slot": MIN_SLOT + 5, "confirmationStatus": "confirmed", "err": None} for _ in params[0]]}
        if method == "getBlock":
            return {"signatures": ["x", "sig1"], "rewards": [{"pubkey": "LEADER", "rewardType": "Fee"}], "blockTime": 1, "blockHeight": 2}
        if method == "getTransaction":
            return {"meta": {"fee": 5001, "computeUnitsConsumed": 450, "costUnits": 2000, "err": None}, "blockTime": 1, "slot": MIN_SLOT + 5}
        raise AssertionError(method)


def test_landed_record_flags_producer_claim_change_between_snapshots():
    start = {"LEADER": {"clientId": "Agave", "version": "4.3.2"}}
    same = landed_records(R(), [{"signature": "sig1", "probe_id": "p"}], start, clients_end=start)[0]
    assert same["leader"] == "LEADER" and same["leader_claim_changed_in_run"] is False and same["tx_index"] == 1
    end = {"LEADER": {"clientId": "AgaveBam", "version": "4.3.2"}}
    ch = landed_records(R(), [{"signature": "sig1", "probe_id": "p"}], start, clients_end=end)[0]
    assert ch["leader_claim_changed_in_run"] is True and ch["leader_client_id_end"] == "AgaveBam" and ch["leader_client_id"] == "Agave"
    old = landed_records(R(), [{"signature": "sig1", "probe_id": "p"}], start)[0]     # no end snapshot: no flag invented
    assert "leader_claim_changed_in_run" not in old
