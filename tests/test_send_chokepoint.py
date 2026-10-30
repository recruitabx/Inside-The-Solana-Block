import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "itb"


def test_only_send_module_mentions_send_rpc_method():
    hits = sorted(p.name for p in SRC.glob("*.py") if "sendTransaction" in p.read_text())
    assert hits == ["send.py"], hits


def test_send_reserves_before_sending(tmp_path):
    from itb.send import SignedTx, send_signed
    from itb.spend import SpendCapExceeded, SpendLedger

    calls = []

    class R:
        host = "fake"

        def batch(self, c, retry=True):
            calls.append([m for m, _ in c])
            return [{"result": "x"} for _ in c]

    with SpendLedger(str(tmp_path / "l.jsonl"), 12_000) as led:
        r = send_signed(R(), led, [SignedTx("a", "AA==", 5000), SignedTx("b", "AA==", 5000)], tag="t", order=[1, 0])
        assert calls == [["sendTransaction", "sendTransaction"]] and r["send_order"] == [1, 0]
        try:
            send_signed(R(), led, [SignedTx("c", "AA==", 5000)], tag="t2")
            raise AssertionError("cap not enforced")
        except SpendCapExceeded:
            pass
        assert len(calls) == 1  # nothing sent after the cap refusal


def test_spaced_send_uses_separate_requests(tmp_path):
    from itb.send import SignedTx, send_signed
    from itb.spend import SpendLedger
    calls = []

    class R:
        host = "fake"

        def batch(self, c, retry=True):
            calls.append(len(c))
            return [{"result": "x"} for _ in c]

    with SpendLedger(str(tmp_path / "l.jsonl"), 100_000) as led:
        r = send_signed(R(), led, [SignedTx("a", "AA==", 5000), SignedTx("b", "AA==", 5000)], tag="t", gap_s=0.05)
    assert calls == [1, 1] and r["send_times"][1][0] - r["send_times"][0][0] >= 0.05


def test_send_options_include_preflight_commitment_processed(tmp_path):
    from itb.send import SignedTx, send_signed
    from itb.spend import SpendLedger
    seen = []

    class R:
        host = "fake"

        def batch(self, c, retry=True):
            seen.extend(p[1] for _, p in c)
            return [{"result": "x"} for _ in c]

    with SpendLedger(str(tmp_path / "l.jsonl"), 100_000) as led:
        send_signed(R(), led, [SignedTx("a", "AA==", 5000)], tag="t", max_retries=2)
    assert seen == [{"encoding": "base64", "skipPreflight": True, "preflightCommitment": "processed", "maxRetries": 2}]
