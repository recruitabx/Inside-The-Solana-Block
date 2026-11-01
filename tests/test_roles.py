import pytest

from itb.roles import assign_roles, candidates_of


def _snap(**nodes):
    return {"nodes": {k: {"clientId": c, "version": v, "delinquent": d} for k, (c, v, d) in nodes.items()}}


def test_first_valid_candidate_wins_and_rejections_are_logged():
    t = {"role": "Agave-1", "clientId": "Agave", "identity": "P", "candidates": ["P", "R1", "R2", "R3"]}
    snap = _snap(P=("Agave", "4.3.2", True), R1=("Firedancer", "26.10.5", False), R2=("Agave", "4.4.0", False), R3=("Agave", "4.3.2", False))
    a = assign_roles([t], snap)["Agave-1"]
    assert a["identity"] == "R2" and a["candidate_index"] == 2 and a["version"] == "4.4.0" and a["skipped"] is None
    assert [(r["identity"], r["reason"][:10]) for r in a["rejected"]] == [("P", "delinquent"), ("R1", "clientId F")]


def test_primary_is_kept_when_valid_and_version_changes_do_not_matter():
    t = {"role": "X-1", "clientId": "Agave", "identity": "P", "candidates": ["P", "R1"]}
    a = assign_roles([t], _snap(P=("Agave", "9.9.9", False), R1=("Agave", "4.3.2", False)))["X-1"]
    assert a["identity"] == "P" and a["candidate_index"] == 0 and a["rejected"] == []


def test_role_without_valid_candidate_is_skipped_with_reasons():
    t = {"role": "X-1", "clientId": "Agave", "identity": "P", "candidates": ["P", "GONE"]}
    a = assign_roles([t], _snap(P=("Jito", "1", False)))["X-1"]
    assert a["identity"] is None and a["skipped"] == "no valid candidate" and len(a["rejected"]) == 2
    assert a["rejected"][1]["reason"] == "not a staked node in the start snapshot"


def test_delinquent_field_must_be_false_and_identity_is_assigned_once():
    t = {"role": "X-1", "clientId": "Agave", "identity": "P"}
    assert candidates_of(t) == ["P"]
    snap = {"nodes": {"P": {"clientId": "Agave", "version": "1"}}}           # snapshot without the field: not provably current
    assert assign_roles([t], snap)["X-1"]["identity"] is None
    t2 = {"role": "Y-1", "clientId": "Agave", "identity": "P", "candidates": ["P"]}
    ok = _snap(P=("Agave", "1", False))
    out = assign_roles([{**t, "candidates": ["P"]}, t2], ok)
    assert out["X-1"]["identity"] == "P" and out["Y-1"]["identity"] is None and out["Y-1"]["rejected"][0]["reason"].startswith("already assigned")
    with pytest.raises(ValueError):
        assign_roles([{"role": "Z-1", "identity": "P"}], ok)


def test_client_snapshot_marks_nodes_without_a_current_vote_account_with_stake_as_delinquent():
    from itb.leaders import client_snapshot

    class R:
        def call(self, method, params=None):
            if method == "getClusterNodes":
                return [{"pubkey": k, "clientId": "Agave", "version": "4.3.2"} for k in ("CUR", "DEL", "BOTH", "NOSTAKE", "UNVOTED")]
            if method == "getVoteAccounts":
                return {"current": [{"nodePubkey": "CUR", "activatedStake": 5}, {"nodePubkey": "BOTH", "activatedStake": 7},
                                    {"nodePubkey": "NOSTAKE", "activatedStake": 0}],
                        "delinquent": [{"nodePubkey": "DEL", "activatedStake": 9}, {"nodePubkey": "BOTH", "activatedStake": 1}]}
            return 123
    nodes = client_snapshot(R())["nodes"]
    assert set(nodes) == {"CUR", "DEL", "BOTH"}                       # staked nodes only
    assert nodes["CUR"]["delinquent"] is False and nodes["BOTH"]["delinquent"] is False and nodes["DEL"]["delinquent"] is True
