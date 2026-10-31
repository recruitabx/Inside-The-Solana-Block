"""Figures of the report. One function so far: the forest plot of the two confirmatory estimands.

`forest_plot(verdicts, path)` takes the dict that `itb analyze` writes to results/verdicts.json
(keys "units", "config", "final") and draws one row per unit (target role and clientId) with
  p = P(the transaction with the higher reward per cost unit lands first)    (blue circle)
  q = P(the transaction that was sent first lands first)                     (orange diamond)
and their exact 95% Clopper-Pearson intervals, the reference line at 0.5, the equivalence band
[equiv_lo, equiv_hi] of the preregistration, the verdict text and the number of pairs per row.

The picture uses a white background and dark text so it reads the same in light and dark viewers
(the PNG is opaque). Blue and orange come from the Okabe-Ito palette (colour-blind safe); the two
estimands also differ by marker shape and by a vertical offset inside the row, so colour is never
the only code. It needs nothing but the verdicts dict: no data files, no network."""
from __future__ import annotations

import textwrap

import matplotlib
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

WIDTH_PX, HEIGHT_PX, DPI = 1200, 700, 100
TITLE = "Which of two transactions lands first?"
XLABEL = "share of same-block pairs"
COLOR_P, COLOR_Q = "#0072B2", "#D55E00"        # Okabe-Ito blue and vermillion (orange)
INK, INK_SOFT, GRID, BAND = "#1b1b1b", "#555555", "#d9d9d9", "#e4e4e4"
DEFAULT_BAND = (0.35, 0.65)
DODGE = 0.17                                    # vertical offset of p (up) and q (down) inside a row
VERDICT_WRAP = 58                               # characters per line of the verdict text


def _interval(est: dict | None) -> tuple[float, float, float] | None:
    """(point, low, high) of a verdicts.json estimate, or None if it has no data."""
    if not est or not est.get("n") or est.get("p") is None or not est.get("ci95"):
        return None
    lo, hi = est["ci95"]
    return float(est["p"]), float(lo), float(hi)


def _unit_n(u: dict) -> str:
    """Number of pairs of the unit's primary cell; both estimands are computed from the same pairs,
    so one number, unless a pair has no defined fee contrast (then p's own n is shown as well)."""
    n_q, n_p = (u.get("send") or {}).get("n", 0), (u.get("fee") or {}).get("n", 0)
    n = u.get("n_primary", max(n_p, n_q))
    return f"N = {n}" if n_p == n_q or not n_p else f"N = {n}\n(p: {n_p})"


def _wrap(text: str, width: int) -> str:
    """Wrap on spaces but never inside an operator and its operand ("<= 0.30" stays together)."""
    glued = text.replace("<= ", "<=\u00a0").replace(">= ", ">=\u00a0").replace("= ", "=\u00a0")
    return textwrap.fill(glued, width).replace("\u00a0", " ")


def forest_plot(verdicts: dict, path: str) -> str:
    """Render the forest plot of `verdicts` (the dict of results/verdicts.json) to the PNG `path`.
    Returns `path`. The image is 1200 x 700 pixels for up to 8 units and grows in height beyond that.
    DejaVu Sans (shipped with matplotlib) is used so that the layout is the same on every machine."""
    with matplotlib.rc_context({"font.family": "DejaVu Sans"}):
        return _draw(verdicts, path)


def _draw(verdicts: dict, path: str) -> str:
    units = list(verdicts.get("units") or [])
    cfg = verdicts.get("config") or {}
    lo_b, hi_b = cfg.get("equiv_lo", DEFAULT_BAND[0]), cfg.get("equiv_hi", DEFAULT_BAND[1])
    n_rows = max(len(units), 1)
    height_px = max(HEIGHT_PX, 250 + 55 * n_rows)
    fig = Figure(figsize=(WIDTH_PX / DPI, height_px / DPI), dpi=DPI, facecolor="white")
    top_px, bottom_px = 140, 92                  # space above and below the plot area, in pixels
    ax = fig.add_axes([0.185, bottom_px / height_px, 0.40, (height_px - top_px - bottom_px) / height_px], facecolor="white")

    ax.set_xlim(0, 1)
    ax.set_ylim(-0.5, n_rows - 0.5)
    ax.axvspan(lo_b, hi_b, color=BAND, zorder=0, lw=0)
    ax.axvline(0.5, color=INK_SOFT, lw=1.2, ls=(0, (4, 3)), zorder=1)
    for y in range(1, n_rows):                   # thin separators between rows
        ax.axhline(y - 0.5, color=GRID, lw=0.8, zorder=0.5)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1])
    ax.set_xticklabels(["0", "0.25", "0.5", "0.75", "1"], fontsize=10, color=INK)
    ax.set_yticks([])
    ax.set_xlabel(XLABEL, fontsize=11, color=INK, labelpad=8)
    ax.tick_params(axis="x", colors=INK_SOFT, length=4)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(INK_SOFT)
    # the edges of the equivalence band, written at the top of the band
    for x in (lo_b, hi_b):
        ax.text(x, n_rows - 0.5 + 0.04, f"{x:g}", ha="center", va="bottom", fontsize=8, color=INK_SOFT)

    # blended transforms: x in axes coordinates, y in data coordinates
    tr = ax.get_yaxis_transform()
    for i, u in enumerate(units):
        y = n_rows - 1 - i
        role, client = u.get("target_role") or u.get("identity") or "?", u.get("client_id")
        ax.text(-0.03, y + 0.1, str(role), transform=tr, ha="right", va="center", fontsize=10.5, fontweight="bold", color=INK)
        if client is not None:
            ax.text(-0.03, y - 0.14, str(client), transform=tr, ha="right", va="center", fontsize=8.5, color=INK_SOFT)
        got = False
        for key, colour, marker, dy in (("fee", COLOR_P, "o", DODGE), ("send", COLOR_Q, "D", -DODGE)):
            iv = _interval(u.get(key))
            if iv is None:
                continue
            got = True
            pt, lo, hi = iv
            ax.plot([lo, hi], [y + dy, y + dy], color=colour, lw=2.2, solid_capstyle="butt", zorder=3)
            ax.plot([pt], [y + dy], marker=marker, ms=8 if marker == "o" else 7, mfc=colour, mec=INK, mew=0.8, ls="none", zorder=4, clip_on=False)
        if not got:
            ax.text(0.5, y, "no pairs in the primary cell", ha="center", va="center", fontsize=9, color=INK_SOFT, style="italic", zorder=3)
        ax.text(1.04, y, _unit_n(u), transform=tr, ha="left", va="center", fontsize=9.5, color=INK, linespacing=1.3)
        verdict = str(u.get("verdict", ""))
        ax.text(1.19, y, _wrap(verdict, VERDICT_WRAP), transform=tr, ha="left", va="center", fontsize=9, color=INK, linespacing=1.25)
    if not units:
        ax.text(0.5, 0, "no units", ha="center", va="center", fontsize=11, color=INK_SOFT)

    # column heads
    y_head = (height_px - top_px + 6) / height_px
    fig.text(0.185 + 0.40 * 1.04, y_head, "pairs", fontsize=9.5, fontweight="bold", color=INK, ha="left", va="bottom")
    fig.text(0.185 + 0.40 * 1.19, y_head, "verdict", fontsize=9.5, fontweight="bold", color=INK, ha="left", va="bottom")
    # title, legend, notes
    fig.text(0.02, 1 - 20 / height_px, TITLE, fontsize=17, fontweight="bold", color=INK, ha="left", va="top")
    if not verdicts.get("final", False):
        fig.text(0.98, 1 - 24 / height_px, "SYNTHETIC SELF-TEST, not real data", fontsize=10, fontweight="bold", color="#9a1b1b",
                 ha="right", va="top")
    handles = [
        Line2D([], [], color=COLOR_P, lw=2.2, marker="o", ms=8, mfc=COLOR_P, mec=INK, mew=0.8, label="p: higher reward per cost unit first"),
        Line2D([], [], color=COLOR_Q, lw=2.2, marker="D", ms=7, mfc=COLOR_Q, mec=INK, mew=0.8, label="q: sent first, lands first"),
        Line2D([], [], color=INK_SOFT, lw=1.2, ls=(0, (4, 3)), label="0.5: no effect"),
        Patch(facecolor=BAND, edgecolor="none", label=f"equivalence band {lo_b:g} to {hi_b:g}"),
    ]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.02, 1 - 56 / height_px), ncol=4, frameon=False, fontsize=9.5,
               labelcolor=INK, columnspacing=1.6, handletextpad=0.6, handlelength=2.2)
    note = ("Markers: estimate; lines: exact 95% Clopper-Pearson interval. Pairs: both transactions in one block of the targeted "
            "leader, in the targeted window.")
    fig.text(0.02, 14 / height_px, textwrap.fill(note, 190), fontsize=8, color=INK_SOFT, ha="left", va="bottom")
    fig.savefig(path, dpi=DPI, facecolor="white")
    return path
