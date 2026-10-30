from itb.blockstats import order_stats, tx_rows


def _tx(i, fee, cost, keys=("Payer",), version=1, nsig=1):
    return {"version": version,
            "transaction": {"signatures": [f"sig{i}"] * nsig, "message": {"accountKeys": list(keys)}},
            "meta": {"fee": fee, "costUnits": cost, "err": None, "loadedAddresses": {"writable": [], "readonly": []}}}


def test_sorted_block_gives_rho_minus_one():
    block = {"transactions": [_tx(i, 5000 + (100 - i) * 10, 1000) for i in range(30)]}
    st = order_stats(tx_rows(block))
    assert st["n_used"] == 30
    assert st["spearman_rho_index_vs_reward_per_cu"] < -0.99
    assert st["adjacent_nonincreasing_share"] == 1.0


def test_votes_and_tips_excluded():
    txs = [_tx(i, 6000, 1000) for i in range(12)]
    txs.append(_tx(99, 6000, 1000, keys=("P", "Vote111111111111111111111111111111111111111")))
    txs.append(_tx(98, 6000, 1000, keys=("P", "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5")))
    rows = tx_rows({"transactions": txs})
    st = order_stats(rows)
    assert st["n_tx"] == 14 and st["n_used"] == 12 and st["n_tip"] == 1
    assert rows[0]["priority_fee"] == 1000 and rows[0]["reward_per_cu"] == 1.0
