import json
import multiprocessing as mp

import pytest

from itb.config import HARD_SPEND_CEILING_LAMPORTS
from itb.spend import SpendCapExceeded, SpendLedger, max_fee_lamports


def test_max_fee_rounds_up():
    assert max_fee_lamports(1, 0, 0) == 5000
    assert max_fee_lamports(2, 1, 1) == 10001  # 1 microlamport x 1 CU rounds up to 1 lamport
    assert max_fee_lamports(1, 1_000_000, 200) == 5200


def test_cap_above_hard_ceiling_rejected(tmp_path):
    with pytest.raises(ValueError):
        SpendLedger(str(tmp_path / "l.jsonl"), HARD_SPEND_CEILING_LAMPORTS + 1)


def test_reserve_until_cap_then_abort_and_nothing_written(tmp_path):
    p = tmp_path / "l.jsonl"
    with SpendLedger(str(p), 20_000) as led:
        led.reserve([("a", 5000), ("b", 5000)])
        led.reserve([("c", 5000)])
        before = p.read_text()
        with pytest.raises(SpendCapExceeded):
            led.reserve([("d", 5000), ("e", 1)])  # 15000 + 5001 > 20000
        assert p.read_text() == before  # abort leaves the ledger untouched
        assert led.committed() == 15000


def test_committed_survives_restart(tmp_path):
    p = str(tmp_path / "l.jsonl")
    with SpendLedger(p, 30_000) as led:
        led.reserve([("a", 10_000), ("b", 10_000)])
        led.settle("a", 5_100)
        led.release("b", "blockhash expired, unknown to cluster")
    with SpendLedger(p, 30_000) as led2:
        assert led2.committed() == 5_100
        led2.reserve([("c", 24_900)])
        with pytest.raises(SpendCapExceeded):
            led2.reserve([("d", 1)])


def test_duplicate_signature_rejected(tmp_path):
    with SpendLedger(str(tmp_path / "l.jsonl"), 100_000) as led:
        led.reserve([("a", 5000)])
        with pytest.raises(ValueError):
            led.reserve([("a", 5000)])


def _hold(path, q):
    led = SpendLedger(path, 10_000)
    q.put("locked")
    import time; time.sleep(2)
    led.close()


def test_second_process_cannot_open_ledger(tmp_path):
    p = str(tmp_path / "l.jsonl")
    q = mp.Queue()
    proc = mp.Process(target=_hold, args=(p, q)); proc.start()
    assert q.get(timeout=5) == "locked"
    with pytest.raises(RuntimeError):
        SpendLedger(p, 10_000)
    proc.join()


def test_ledger_lines_are_json(tmp_path):
    p = tmp_path / "l.jsonl"
    with SpendLedger(str(p), 10_000) as led:
        led.reserve([("a", 5000)], tag="probe-1")
    rec = json.loads(p.read_text().splitlines()[0])
    assert rec["kind"] == "reserve" and rec["tag"] == "probe-1"
