import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "freeze_targets.py"
_spec = importlib.util.spec_from_file_location("freeze_targets", _SCRIPT)
ft = importlib.util.module_from_spec(_spec)
sys.modules["freeze_targets"] = ft
_spec.loader.exec_module(ft)

H = 3600.0


def _sched(spec):
    return {ident: [8 * i for i in range(w)] for ident, w in spec.items()}


def _snap(t, nodes):
    return {"taken_at_unix": 1_000_000.0 + t, "slot": 470_000_000 + int(t), "total_stake": 1000,
            "nodes": {k: {"clientId": c, "version": v, "stake": 10} for k, (c, v) in nodes.items()}}


def _setup(tmp_path, spans=(0, 6 * H, 13 * H, 20 * H), mutate=None):
    claims = {"A1": ("AgaveBam", "4.4.0"), "A2": ("AgaveBam", "4.4.0"), "A3": ("AgaveBam", "4.3.2"), "A4": ("AgaveBam", "4.4.0"),
              "A5": ("AgaveBam", "4.4.0"), "J1": ("JitoLabs", "4.3.2"), "J2": ("JitoLabs", "4.3.2"),
              "HEL1USxxxx": ("JitoLabs", "4.3.2"), "F1": ("Firedancer", "26.10.4"), "F2": ("Firedancer", "26.10.5"),
              "N1": ("NewClient", "1.0.0")}
    sched = _sched({"A1": 500, "A2": 450, "A3": 450, "A4": 410, "A5": 405, "J1": 600, "J2": 450, "HEL1USxxxx": 700, "F1": 399, "F2": 405, "N1": 440})
    sel = tmp_path / "sel"
    (sel / "snapshots").mkdir(parents=True)
    (sel / "leader_schedule_epoch1074.json").write_text(json.dumps(sched))
    for k, t in enumerate(spans):
        nodes = dict(claims)
        if k == 2:
            nodes["J1"] = ("Firedancer", "26.10.4")           # J1 flaps in the third snapshot
        if mutate:
            mutate(k, nodes)
        (sel / "snapshots" / f"clients_{k}.json").write_text(json.dumps(_snap(t, nodes)))
    return sel


def _run(tmp_path, sel, *extra):
    out = tmp_path / "validators.json"
    rc = ft.main(["--selection-dir", str(sel), "--out", str(out), *extra])
    return rc, out


def test_selection_rules_eligibility_replacements_and_reasons(tmp_path, capsys):
    sel = _setup(tmp_path)
    rc, out = _run(tmp_path, sel)
    assert rc == 0
    v = json.load(open(out))
    t = {x["clientId"]: x for x in v["targets"]}
    assert set(t) == {"AgaveBam", "JitoLabs", "Firedancer", "NewClient"}              # clientIds are not hard-coded
    assert t["AgaveBam"]["identity"] == "A1" and t["AgaveBam"]["role"] == "AgaveBam-1"
    assert [r["identity"] for r in t["AgaveBam"]["replacements"]] == ["A2", "A3", "A4"]   # next 3 by windows; A2/A3 tie broken by version then identity
    assert t["JitoLabs"]["identity"] == "J2"                                          # J1 flapped, HEL1US excluded
    assert t["Firedancer"]["identity"] == "F2" and t["NewClient"]["identity"] == "N1"
    assert [x["clientId"] for x in v["targets"]] == ["AgaveBam", "JitoLabs", "NewClient", "Firedancer"]    # ranked by windows
    inel = {r["identity"]: r["reason"] for r in v["ineligible_top"]}
    assert "claim changed across snapshots" in inel["J1"] and "HEL1US" in inel["HEL1USxxxx"] and "399 windows < 400" in inel["F1"]
    assert v["snapshot_span_hours"] == 20.0 and len(v["snapshots"]) == 4 and len(v["schedule_sha256"]) == 64
    assert v["epoch"] == 1074
    assert "distinct clientIds: 4 distinct versions: 4" in capsys.readouterr().out


def test_replacement_tiebreak_prefers_same_version_only_after_windows(tmp_path):
    rows = [{"identity": i, "clientId": "C", "version": v, "windows_epoch": w, "stake_share": 0.0, "eligible": True, "reason": None}
            for i, v, w in [("T", "1", 500), ("B", "2", 450), ("C", "1", 450), ("D", "2", 449), ("E", "1", 100), ("F", "1", 99)]]
    t, _ = ft.select_targets(rows)
    assert [r["identity"] for r in t[0]["replacements"]] == ["C", "B", "D"]            # windows first; at equal windows the same version first


def test_snapshots_must_span_18_hours_and_number_four(tmp_path, capsys):
    sel = _setup(tmp_path, spans=(0, 1 * H, 2 * H, 3 * H))
    rc, out = _run(tmp_path, sel)
    assert rc == 1 and not out.exists()
    err = capsys.readouterr()
    assert "snapshots insufficient: 4 spanning 3.0 h" in err.out and "FAILED" in err.err
    sel2 = _setup(tmp_path / "b", spans=(0, 10 * H, 20 * H))
    rc, out = _run(tmp_path / "b", sel2)
    assert rc == 1 and not out.exists()


def test_fewer_than_three_clientids_or_versions_exits_nonzero(tmp_path, capsys):
    def only_two(k, nodes):
        for i in ("F2", "N1"):
            nodes.pop(i)
    sel = _setup(tmp_path, mutate=only_two)
    rc, out = _run(tmp_path, sel)
    assert rc == 1 and not out.exists() and "FAILED" in capsys.readouterr().err

    def one_version(k, nodes):
        for i, (c, v) in list(nodes.items()):
            nodes[i] = (c, "4.3.2")
    sel2 = _setup(tmp_path / "c", mutate=one_version)
    rc, out = _run(tmp_path / "c", sel2)
    assert rc == 1                                          # 4 clientIds but a single version string
    rc, out = _run(tmp_path / "c", sel2, "--min-windows", "300")
    assert rc == 1


def test_min_windows_can_be_lowered_to_300(tmp_path):
    sel = _setup(tmp_path)
    rc, out = _run(tmp_path, sel, "--min-windows", "300")
    v = json.load(open(out))
    assert rc == 0 and {x["identity"] for x in v["targets"]} == {"A1", "J2", "F2", "N1"} and v["min_windows"] == 300
    f = [x for x in v["targets"] if x["clientId"] == "Firedancer"][0]
    assert [r["identity"] for r in f["replacements"]] == ["F1"]
