import base64

from solders.keypair import Keypair
from solders.transaction import Transaction

from itb.leaders import windows_from_leaders
from itb.txbuild import build_probe_tx

BH = "11111111111111111111111111111111"


def test_probe_tx_shape_and_fee():
    kp = Keypair()
    b = build_probe_tx(kp, BH, cu_limit=1000, cu_price=12_345, memo="itb1:p7:0")
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
    assert writable == [kp.pubkey()]
    assert b.max_fee == 5000 + 13  # ceil(12345*1000/1e6)
    tx.verify()  # raises if the signature is invalid


def test_windows_grouping():
    w = windows_from_leaders(100, ["A", "A", "A", "A", "B", "B", "B", "B", "A"])
    assert [(x.leader, x.first_slot, x.last_slot) for x in w] == [("A", 100, 103), ("B", 104, 107), ("A", 108, 108)]
