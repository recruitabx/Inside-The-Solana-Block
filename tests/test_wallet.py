import json
import os

import pytest
from solders.keypair import Keypair

from itb.wallet import derive_payers, load_wallet


def test_derivation_deterministic_and_distinct():
    m = Keypair()
    a, b = derive_payers(m, 8), derive_payers(m, 8)
    assert [str(x.pubkey()) for x in a] == [str(x.pubkey()) for x in b]
    assert len({str(x.pubkey()) for x in a} | {str(m.pubkey())}) == 9


def test_load_wallet_rejects_loose_permissions(tmp_path):
    p = tmp_path / "w.json"
    p.write_text(json.dumps(list(bytes(Keypair()))))
    os.chmod(p, 0o644)
    with pytest.raises(SystemExit):
        load_wallet(str(p))
    os.chmod(p, 0o600)
    assert load_wallet(str(p)).pubkey() is not None
