import base64

from solders.keypair import Keypair
from solders.transaction import Transaction

from itb.leaders import windows_from_leaders
from itb.txbuild import build_probe_tx, build_probe_unsigned_b64, fresh_address

BH = "11111111111111111111111111111111"


def test_probe_tx_shape_and_fee():
    kp = Keypair()
    w = fresh_address("seed", 7)
    b = build_probe_tx(kp, BH, cu_limit=1000, cu_price=12_345, shared=w)
    tx = Transaction.from_bytes(base64.b64decode(b.wire_b64))
    assert str(tx.signatures[0]) == b.signature
    msg = tx.message
    assert msg.account_keys[0] == kp.pubkey()
    assert msg.header.num_required_signatures == 1
    # only the fee payer is writable
    h, keys = msg.header, msg.account_keys
    nsig = h.num_required_signatures

    def is_writable(i):
        if i < nsig:
            return i < nsig - h.num_readonly_signed_accounts
        return i < len(keys) - h.num_readonly_unsigned_accounts
    writable = [k for i, k in enumerate(keys) if is_writable(i)]
    assert writable == [kp.pubkey(), w]  # exactly the payer and the shared account W
    assert len(msg.instructions) == 4
    assert b.max_fee == 5000 + 13  # ceil(12345*1000/1e6)
    tx.verify()  # raises if the signature is invalid


def test_windows_grouping():
    w = windows_from_leaders(100, ["A", "A", "A", "A", "B", "B", "B", "B", "A"])
    assert [(x.leader, x.first_slot, x.last_slot) for x in w] == [("A", 100, 103), ("B", 104, 107), ("A", 108, 108)]


def test_design_arms_randomization_independent():
    import random
    from itb.design import make_probe
    plan = {"shares": {"P": 0.7, "E": 0.1, "D": 0.1, "S": 0.1}, "price_high": 5_500_000, "price_low": 1000,
            "cu_limit": 1000, "loaded_limit": 4096, "gap_ms": 200}
    rng = random.Random(1)
    specs = [make_probe(rng, plan, {}) for _ in range(4000)]
    share_p = sum(s["arm"] == "P" for s in specs) / len(specs)
    assert 0.67 < share_p < 0.73
    P = [s for s in specs if s["arm"] == "P"]
    # high-price batch position ~ 50/50 and independent of which payer slot is high
    assert 0.46 < sum(s["hi_pos"] == 0 for s in P) / len(P) < 0.54
    both = sum(s["hi_pos"] == 0 and s["hi_idx"] == 0 for s in P) / len(P)
    assert 0.21 < both < 0.29
    S = [s for s in specs if s["arm"] == "S"]
    assert all(s["gap_s"] == 0.2 for s in S)  # two requests 200 ms apart
    # arm S direction is randomized 50/50: the first-sent transaction is the high one in half of the probes
    assert 0.44 < sum(s["hi_pos"] == 0 for s in S) / len(S) < 0.56
    assert all(s["s_low_first"] == (s["hi_pos"] == 1) for s in S)
    assert all(s["s_low_first"] is None for s in specs if s["arm"] != "S")
    assert all(s["order"][0] != s["hi_idx"] for s in S if s["s_low_first"])
    E = [s for s in specs if s["arm"] == "E"]
    assert all(t["cu_price"] == 1000 for s in E for t in s["txs"])
    D = [s for s in specs if s["arm"] == "D"]
    assert all({t["w_index"] for t in s["txs"]} == {0, 1} for s in D)


def test_unsigned_template_matches_the_signed_one_except_for_the_signature():
    kp = Keypair()
    w = fresh_address("seed", 9)
    signed = Transaction.from_bytes(base64.b64decode(build_probe_tx(kp, BH, cu_limit=1000, cu_price=5_500_000, shared=w).wire_b64))
    unsigned = Transaction.from_bytes(base64.b64decode(
        build_probe_unsigned_b64(kp.pubkey(), cu_limit=1000, cu_price=5_500_000, shared=w, blockhash=BH)))
    assert bytes(unsigned.message) == bytes(signed.message)
    assert all(str(s) == "1" * 64 for s in unsigned.signatures) and str(signed.signatures[0]) != "1" * 64
