from itb.blocks import b58encode
from itb.blockstats import order_stats, requested_cu_limit, tx_rows

CB = "ComputeBudget111111111111111111111111111111"


def _tx(i, fee, cost, keys=("Payer",), version=1, nsig=1, consumed=None, instrs=None, config=None):
    msg = {"accountKeys": list(keys)}
    if instrs is not None:
        msg["instructions"] = instrs
    if config is not None:
        msg["transactionConfig"] = config
    meta = {"fee": fee, "costUnits": cost, "err": None, "loadedAddresses": {"writable": [], "readonly": []}}
    if consumed is not None:
        meta["computeUnitsConsumed"] = consumed
    return {"version": version, "transaction": {"signatures": [f"sig{i}"] * nsig, "message": msg}, "meta": meta}


def set_limit(n):
    return {"programIdIndex": 1, "accounts": [], "data": b58encode(bytes([2]) + n.to_bytes(4, "little"))}


def test_sorted_block_gives_rho_minus_one():
    block = {"transactions": [_tx(i, 5000 + (100 - i) * 10, 1000) for i in range(30)]}
    st = order_stats(tx_rows(block))
    assert st["n_used"] == 30
    assert st["spearman_rho_index_vs_reward_per_cost_units_consumed"] < -0.99
    assert st["adjacent_nonincreasing_share_reward_per_cost_units_consumed"] == 1.0


def test_votes_and_tips_excluded():
    txs = [_tx(i, 6000, 1000) for i in range(12)]
    txs.append(_tx(99, 6000, 1000, keys=("P", "Vote111111111111111111111111111111111111111")))
    txs.append(_tx(98, 6000, 1000, keys=("P", "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5")))
    rows = tx_rows({"transactions": txs})
    st = order_stats(rows)
    assert st["n_tx"] == 14 and st["n_used"] == 12 and st["n_tip"] == 1
    assert rows[0]["priority_fee"] == 1000 and rows[0]["reward_per_cost_units_consumed"] == 1.0
    assert "reward_per_cu" not in rows[0]


def test_requested_limit_from_instruction_v1_config_and_default():
    keys = ["Payer", CB, "Prog"]
    other = {"programIdIndex": 2, "accounts": [], "data": ""}
    t = _tx(1, 5000, 100, keys=keys, instrs=[set_limit(1234), other])
    assert requested_cu_limit(t, keys) == (1234, "instruction")
    # the runtime caps the request at 1.4 million
    assert requested_cu_limit(_tx(1, 5000, 100, keys=keys, instrs=[set_limit(9_000_000), other]), keys) == (1_400_000, "instruction")
    # a SetComputeUnitPrice instruction (discriminator 3) is not a limit: default of 200,000 per other instruction
    price = {"programIdIndex": 1, "accounts": [], "data": b58encode(bytes([3]) + (5).to_bytes(8, "little"))}
    assert requested_cu_limit(_tx(1, 5000, 100, keys=keys, instrs=[price, other, other]), keys) == (400_000, "default")
    assert requested_cu_limit(_tx(1, 5000, 100, keys=keys, instrs=[other] * 9), keys) == (1_400_000, "default")
    v1 = _tx(1, 5000, 100, keys=keys, instrs=[other], config={"computeUnitLimit": 7000})
    assert requested_cu_limit(v1, keys) == (7000, "v1_config")


def test_scheduler_key_uses_requested_limit_and_gives_its_own_rho():
    keys = ["Payer", CB, "Prog"]
    other = {"programIdIndex": 2, "accounts": [], "data": ""}
    # same priority fee and same consumed cost everywhere; the requested limit grows with the index:
    # the key priority fee / costUnits cannot tell them apart, the scheduler key falls with the index
    txs = [_tx(i, 5000 + 10_000, 2000, keys=keys, consumed=500, instrs=[set_limit(1000 * (i + 1)), other]) for i in range(30)]
    rows = tx_rows({"transactions": txs})
    r0 = rows[0]
    assert r0["requested_cu_limit"] == 1000 and r0["requested_cu_limit_source"] == "instruction"
    assert r0["reward"] == 10_000 + 2500 and r0["cost_sched"] == 2000 - 500 + 1000
    assert abs(r0["sched_key"] - 12_500 / 2500) < 1e-12
    st = order_stats(rows)
    assert st["n_used_sched_key"] == 30
    assert st["spearman_rho_index_vs_sched_key"] < -0.99 and st["adjacent_nonincreasing_share_sched_key"] == 1.0
    assert "spearman_rho_index_vs_reward_per_cost_units_consumed" not in st   # constant key: no rank statistic
    # without computeUnitsConsumed the scheduler key cannot be built
    assert tx_rows({"transactions": [_tx(1, 6000, 100, keys=keys, instrs=[other])]})[0]["sched_key"] is None
