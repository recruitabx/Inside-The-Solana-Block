"""Record parsing and summary of scripts/localnet_calibration.py, on a synthetic JSONL (no network)."""
import importlib.util
import json
import random
import sys
from pathlib import Path

import pytest

from itb.stats import binom_two_sided_p, wilson_ci

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "localnet_calibration.py"
_spec = importlib.util.spec_from_file_location("localnet_calibration", _SCRIPT)
lc = importlib.util.module_from_spec(_spec)
sys.modules["localnet_calibration"] = lc  # dataclasses need the module to be registered
_spec.loader.exec_module(lc)


def pair(cond, i, *, hi_label, first_label, winner, same_slot=True, landed=True, cfg=None):
    """Synthetic record: `winner` is the label that gets the lower block index."""
    cfg = cfg or lc.Cfg(transport="rpc" if cond == "A" else "quic").__dict__
    txs = []
    for lab in (1, 2):
        t = {"label": lab, "sig": f"sig{cond}{i}{lab}", "send_pos": 0 if lab == first_label else 1,
             "cu_price": 1000, "cu_limit": 200000, "slot": 100 + i, "index": 1 if lab == winner else 2, "err": None}
        if not same_slot and lab != winner:
            t["slot"] += 1
        if not landed and lab == 2:
            t["slot"] = t["index"] = None
        txs.append(t)
    return {"record": "pair", "condition": cond, "pair": i, "cfg": cfg, "hi_label": hi_label,
            "first_label": first_label, "txs": txs}


def write_jsonl(path, recs):
    path.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")


def synthetic():
    recs = [{"record": "meta", "seed": 1}]
    # A: the first-sent tx always wins; the fee label is independent of it (alternating)
    for i in range(20):
        first = 1 + (i % 2)
        recs.append(pair("A", i, hi_label=1 + ((i // 2) % 2), first_label=first, winner=first))
    # B: the higher-fee tx wins 18 of 20 (the two losses are the same pairs where it was sent second)
    for i in range(20):
        hi, first = 1 + (i % 2), 1 + ((i // 2) % 2)
        winner = hi if i >= 2 else 3 - hi
        recs.append(pair("B", i, hi_label=hi, first_label=first, winner=winner))
    # C (placebo, equal fees -> hi_label None): label 1 wins 10 of 20
    for i in range(20):
        recs.append(pair("C", i, hi_label=None, first_label=1 + (i % 2), winner=1 if i % 2 else 2))
    # B-sweep rows for two configurations; one pair of the first config does not land, one is cross-slot
    good = lc.Cfg(k=4, filler_cu_limit=1_400_000, filler_sigs=50, lead_ms=1.0).__dict__
    bad = lc.Cfg(k=0).__dict__
    for i in range(10):
        recs.append(pair("B-sweep", i, hi_label=1, first_label=1 + (i % 2), winner=1, cfg=good))
        recs.append(pair("B-sweep", i, hi_label=1, first_label=1 + (i % 2), winner=1 + (i % 2), cfg=bad))
    recs.append(pair("B-sweep", 90, hi_label=1, first_label=1, winner=1, landed=False, cfg=good))
    recs.append(pair("B-sweep", 91, hi_label=1, first_label=1, winner=2, same_slot=False, cfg=good))
    return recs


def rows_by_group(rows):
    return {r["group"]: r for r in rows}


def test_load_records_skips_meta_and_blank_lines(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text(json.dumps({"record": "meta"}) + "\n\n" + json.dumps(pair("A", 0, hi_label=1, first_label=1, winner=1)) + "\n")
    assert len(lc.load_records(str(p))) == 1


def test_load_records_reports_bad_line(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text('{"record": "pair"}\n{not json}\n')
    with pytest.raises(ValueError, match=r"bad.jsonl:2"):
        lc.load_records(str(p))


def test_pair_outcome_basic_cases():
    o = lc.pair_outcome(pair("B", 0, hi_label=2, first_label=1, winner=2))
    assert o == {"same_slot": True, "first_label": 2, "first_sent_first": False, "hi_first": True, "label1_first": False}
    assert lc.pair_outcome(pair("B", 1, hi_label=1, first_label=1, winner=1, landed=False)) is None
    cross = lc.pair_outcome(pair("B", 2, hi_label=1, first_label=1, winner=2, same_slot=False))
    assert cross["same_slot"] is False and cross["first_label"] == 2   # earlier slot wins regardless of index
    assert lc.pair_outcome(pair("C", 3, hi_label=None, first_label=1, winner=1))["hi_first"] is None


def test_summary_recovers_planted_answers(tmp_path):
    p = tmp_path / "cal.jsonl"
    write_jsonl(p, synthetic())
    rows = rows_by_group(lc.summarize(lc.load_records(str(p))))

    a = rows["A"]
    assert (a["n_pairs"], a["n_same_slot"], a["k_first_sent"], a["k_hi"]) == (20, 20, 20, 10)
    assert a["ci_first_sent"] == wilson_ci(20, 20) and a["p_first_sent"] == binom_two_sided_p(20, 20)
    assert a["p_first_sent"] < 1e-5 and a["p_hi"] == 1.0

    b = rows["B"]
    assert (b["k_hi"], b["n_same_slot"]) == (18, 20) and not b["placebo_label"]
    assert b["ci_hi"] == wilson_ci(18, 20) and b["p_hi"] == binom_two_sided_p(18, 20)

    c = rows["C"]
    assert c["placebo_label"] and (c["k_hi"], c["n_same_slot"]) == (10, 20) and c["p_hi"] == 1.0


def test_summary_excludes_unlanded_and_cross_slot_pairs():
    rows = lc.summarize(synthetic())
    good = next(r for r in rows if r["condition"] == "B-sweep" and "K=4" in r["group"])
    assert (good["n_pairs"], good["n_landed"], good["n_same_slot"], good["k_hi"]) == (12, 11, 10, 10)


def test_rows_order_and_best_sweep_choice():
    rows = lc.summarize(synthetic())
    assert [r["condition"] for r in rows][:3] == ["A", "B", "C"]
    best = lc.pick_best_sweep(rows)
    assert lc.cfg_from_dict(best["cfg"]).k == 4 and best["ci_hi"][0] > 0.6
    # a sweep row with too few same-slot pairs is not eligible
    assert lc.pick_best_sweep([dict(best, n_same_slot=1)]) is None


def test_formatting_contains_counts_and_labels():
    rows = lc.summarize(synthetic())
    text = lc.format_summary(rows)
    assert "20/20 = 1.000" in text and "label-1-first (placebo)" in text and "higher-fee-first" in text
    md = lc.format_markdown(rows)
    assert md.count("\n") == len(rows) + 1 and "| A | 20 | 20 | 20 |" in md


def test_empty_group_does_not_crash():
    rec = pair("A", 0, hi_label=1, first_label=1, winner=1, landed=False)
    row = lc.summarize([rec])[0]
    assert row["n_same_slot"] == 0 and "n/a" in lc.format_summary([row])


def test_plans_are_seeded_and_coins_independent():
    spec = [("A", 200, lc.Cfg(transport="rpc")), ("C", 200, lc.Cfg())]
    p1 = lc.make_plans(random.Random(7), spec)
    p2 = lc.make_plans(random.Random(7), spec)
    key = lambda ps: [(p.condition, p.idx, p.hi_label, p.first_label) for p in ps]  # noqa: E731
    assert key(p1) == key(p2)
    a = [p for p in p1 if p.condition == "A"]
    both = sum(1 for p in a if p.hi_label == p.first_label)
    assert binom_two_sided_p(both, len(a)) > 0.001          # fee contrast independent of send position
    assert all(p.hi_label is None for p in p1 if p.condition == "C")   # placebo: equal fees


def test_refuses_non_local_endpoints():
    lc.check_local("http://127.0.0.1:8899", "--rpc")
    lc.check_local("127.0.0.1:8002", "TPU")
    with pytest.raises(SystemExit):
        lc.check_local("https://example.org", "--rpc")


def test_ed25519_filler_instruction_layout():
    ix = lc.ed25519_burn_ix(lc.Keypair(), 5)
    d = bytes(ix.data)
    assert d[0] == 5 and len(d) == 2 + 14 * 5 + 32 + 64 + len(b"itb-calibration-filler")
