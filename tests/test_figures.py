import json
import struct

from itb.analyze import DEFAULTS, analyze
from itb.figures import forest_plot
from itb.synthetic import write_synthetic

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _png_size(path):
    data = open(path, "rb").read()
    assert data[:8] == PNG_MAGIC and data[12:16] == b"IHDR"
    return struct.unpack(">II", data[16:24]), len(data)


def _verdicts(tmp_path, validators, seed=0, **kw):
    raw, out = tmp_path / "raw", tmp_path / "out"
    write_synthetic(str(raw), validators, seed=seed)
    analyze(str(raw), str(out), dict(DEFAULTS), final=False, **kw)
    return out


def _units():
    base = {"client_id": "Agave", "version": "4.3.2"}
    return {"Alpha-1": {**base, "n": 150, "p_fee": 0.97}, "Beta-1": {**base, "n": 150, "p_fee": 0.5},
            "Gamma-1": {**base, "n": 150, "p_fee": 0.5, "p_send": 0.9}, "Small-1": {**base, "n": 20, "p_fee": 0.6}}


def test_forest_plot_renders_png_from_verdicts_json(tmp_path):
    out = _verdicts(tmp_path, _units(), figure=False)
    verdicts = json.load(open(out / "verdicts.json"))
    path = tmp_path / "fig.png"
    assert forest_plot(verdicts, str(path)) == str(path)
    (w, h), nbytes = _png_size(path)
    assert (w, h) == (1200, 700)
    assert 15_000 < nbytes < 1_000_000


def test_analyze_writes_figure_pq_next_to_verdicts(tmp_path):
    out = _verdicts(tmp_path, _units())      # default: the figure is part of the outputs
    assert (out / "verdicts.json").exists()
    (w, h), nbytes = _png_size(out / "figure_pq.png")
    assert (w, h) == (1200, 700) and nbytes > 15_000


def test_figure_is_deterministic_and_can_be_switched_off(tmp_path):
    out = _verdicts(tmp_path, _units())
    verdicts = json.load(open(out / "verdicts.json"))
    forest_plot(verdicts, str(tmp_path / "again.png"))
    assert open(tmp_path / "again.png", "rb").read() == open(out / "figure_pq.png", "rb").read()
    off = _verdicts(tmp_path / "off", _units(), figure=False)
    assert not (off / "figure_pq.png").exists()


def test_forest_plot_many_units_and_units_without_pairs(tmp_path):
    est = {"n": 100, "k": 60, "p": 0.6, "ci95": [0.5, 0.69]}
    units = [{"target_role": f"R{i}", "client_id": "X", "n_primary": 100, "fee": est, "send": est, "verdict": "fee rule holds, partial"}
             for i in range(12)]
    units.append({"target_role": "Empty", "client_id": "Y", "n_primary": 0, "fee": {"n": 0}, "send": {"n": 0},
                  "verdict": "insufficient data (n=0)"})
    path = tmp_path / "many.png"
    forest_plot({"units": units, "config": {}, "final": True}, str(path))
    (w, h), _ = _png_size(path)
    assert w == 1200 and h > 700                  # taller for more rows, never a clipped row
    forest_plot({"units": [], "final": True}, str(tmp_path / "none.png"))
    assert _png_size(tmp_path / "none.png")[0] == (1200, 700)
