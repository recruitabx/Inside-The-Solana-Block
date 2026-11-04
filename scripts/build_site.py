#!/usr/bin/env python3
"""Build docs/index.html (the GitHub Pages landing page) from the result files.

Every number on the page is read at build time from:
  results/verdicts.json, results/secondary.json, results/runs.csv,
  results/audit.txt (optional), data/plan.json, REPORT.md (anchors and the
  "what we do not separate" list) and docs/DESIGN.md (the Considerations table).

Re-run after `docker compose run --rm analyze`:
    python3 scripts/build_site.py

Standard library only. Writes docs/index.html and docs/.nojekyll.
"""
from __future__ import annotations

import csv
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO_URL = "https://github.com/recruitabx/Inside-The-Solana-Block"
PAGES_URL = "https://recruitabx.github.io/Inside-The-Solana-Block/"
EXPLORER = "https://solscan.io/tx/"
EM_DASH = "\u2014"


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------

def esc(s) -> str:
    return html.escape(str(s), quote=True)


def f2(x) -> str:
    return f"{float(x):.2f}"


def pct(x, digits=0) -> str:
    return f"{100 * float(x):.{digits}f}%"


def fmt_int(n) -> str:
    return f"{int(n):,}"


def load_json(rel: str, required: bool = True):
    path = ROOT / rel
    if not path.exists():
        if required:
            sys.exit(f"missing {rel}")
        return None
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def read_text(rel: str) -> str:
    path = ROOT / rel
    return path.read_text(encoding="utf-8") if path.exists() else ""


def section(md: str, start_pat: str, end_pat: str = r"^## ") -> str:
    """Return the markdown between a heading matching start_pat and the next heading."""
    m = re.search(start_pat, md, flags=re.M)
    if not m:
        return ""
    rest = md[m.end():]
    e = re.search(end_pat, rest, flags=re.M)
    return rest[: e.start()] if e else rest


def strip_md(s: str) -> str:
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)  # links
    s = s.replace("`", "")
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    return s.strip()


def shorten(text: str, limit: int = 300) -> str:
    """Keep whole sentences up to about `limit` characters."""
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text.strip())
    out = ""
    for p in parts:
        if out and len(out) + len(p) + 1 > limit:
            break
        out = (out + " " + p).strip()
    return out or text[:limit]


def ci(stat: dict) -> tuple[float, float] | None:
    c = stat.get("ci95") if isinstance(stat, dict) else None
    if c and len(c) == 2:
        return float(c[0]), float(c[1])
    return None


def stat_parts(stat: dict, name: str) -> tuple:
    """('p = 0.88 [0.81, 0.94]', '97 of 110 pairs')"""
    if not isinstance(stat, dict) or not stat.get("n"):
        return f"{name}: no data", ""
    c = ci(stat)
    s = f"{name} = {f2(stat['p'])}"
    if c:
        s += f" [{f2(c[0])}, {f2(c[1])}]"
    count = f"{stat['k']} of {stat['n']} pairs" if "k" in stat else f"{stat['n']} pairs"
    return s, count


# ----------------------------------------------------------------------------
# data
# ----------------------------------------------------------------------------

def load_all() -> dict:
    verdicts = load_json("results/verdicts.json")
    secondary = load_json("results/secondary.json")
    plan = load_json("data/plan.json")
    report = read_text("REPORT.md")
    design = read_text("docs/DESIGN.md")

    cfg = verdicts.get("config", {}) if isinstance(verdicts, dict) else {}
    min_n = int(cfg.get("min_n", 100))
    equiv = (float(cfg.get("equiv_lo", 0.35)), float(cfg.get("equiv_hi", 0.65)))

    # --- units (one per validator), sorted by N descending
    units = []
    for u in verdicts.get("units", []):
        fee, send = u.get("fee", {}), u.get("send", {})
        n = int(u.get("n_primary", fee.get("n", 0)) or 0)
        versions = u.get("versions_seen") or []
        units.append({
            "role": u.get("target_role", ""),
            "client": u.get("client_id", ""),
            "version": ", ".join(versions),
            "identity": u.get("identity", ""),
            "n": n,
            "n_probes": int(u.get("n_probes_arm_P", 0) or 0),
            "p": float(fee.get("p")) if fee.get("n") else None,
            "p_ci": ci(fee),
            "p_k": fee.get("k"),
            "p_holm": fee.get("p_holm"),
            "q": float(send.get("p")) if send.get("n") else None,
            "q_ci": ci(send),
            "q_k": send.get("k"),
            "q_holm": send.get("p_holm"),
            "verdict": str(u.get("verdict", "")),
        })
    units.sort(key=lambda r: (-r["n"], r["role"]))

    # --- runs.csv: dates, counts
    runs = []
    with (ROOT / "results/runs.csv").open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            runs.append(row)
    main_runs = [r for r in runs if r.get("row_type") == "run" and r.get("phase") not in ("pilot", "repilot")]
    starts = sorted(r["start_utc"] for r in main_runs if r.get("start_utc"))
    ends = sorted(r["end_utc"] for r in main_runs if r.get("end_utc"))
    first_day = starts[0][:10] if starts else ""
    last_day = ends[-1][:10] if ends else first_day
    data_dates = first_day if first_day == last_day else f"{first_day} to {last_day}"
    totals = {r["run_id"]: r for r in runs if r.get("row_type") in ("phase_total", "total")}
    tot_main = totals.get("TOTAL main", {})
    tot_all = totals.get("TOTAL all", {})

    def num(row, key):
        try:
            return float(row.get(key) or 0)
        except ValueError:
            return 0.0

    n_probes = int(verdicts.get("n_rows_analysed") or num(tot_main, "probes_sent") or sum(u["n_probes"] for u in units))
    tx_sent = int(num(tot_main, "tx_sent"))
    tx_landed = int(num(tot_main, "tx_landed"))
    landing = tx_landed / tx_sent if tx_sent else None
    n_usable_all_arms = int(num(tot_main, "usable_probes"))
    n_runs = len(main_runs)

    # --- spend
    audit = None
    audit_txt = read_text("results/audit.txt")
    if audit_txt.strip():
        try:
            audit = json.loads(audit_txt)
        except json.JSONDecodeError:
            audit = None
    spent = int((audit or {}).get("settled_fees_lamports") or num(tot_all, "fees_settled_lamports"))
    cap = int((audit or {}).get("hard_ceiling_lamports") or 50_000_000)

    # --- secondary: the three regimes
    def pooled(table: str, key: str):
        t = secondary.get(table, {})
        row = t.get("ALL", t) if isinstance(t, dict) else {}
        return row.get(key, {}) if isinstance(row, dict) else {}

    p_co = pooled("copresence_p_co", "p_co")
    q_co = pooled("copresence_p_co", "q_co")
    co_rule = (secondary.get("copresence_p_co", {}).get("ALL", {}) or {}).get("rule")
    q_s = pooled("arm_S", "q")
    p_e = pooled("arm_E", "p")
    q_e = pooled("arm_E", "q")

    # --- anchors from REPORT.md section 1
    anchors = []
    sec1 = section(report, r"^## 1\.")
    for line in sec1.splitlines():
        if not line.startswith("|"):
            continue
        sig = re.search(r"`([1-9A-HJ-NP-Za-km-z]{80,90})`", line)
        if not sig:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        when = strip_md(cells[0]) if cells else ""
        what = strip_md(cells[1]) if len(cells) > 1 else ""
        label = re.split(r":|\(", what)[0].replace(" anchored", "").strip().rstrip(",")
        slot = re.search(r"slot (\d+)", what)
        anchors.append({"when": when, "label": label[:1].upper() + label[1:], "sig": sig.group(1),
                        "slot": slot.group(1) if slot else ""})

    # --- what we do not separate: REPORT.md section 6
    not_separated = []
    for line in section(report, r"^## 6\.").splitlines():
        if line.lstrip().startswith("- "):
            not_separated.append(strip_md(line.lstrip()[2:]))

    # --- considerations: docs/DESIGN.md table
    considerations = []
    for line in section(design, r"^## How the design handles each consideration").splitlines():
        if not line.startswith("|") or line.startswith("|---") or line.startswith("| Consideration"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2:
            considerations.append({"title": strip_md(cells[0]), "text": shorten(strip_md(cells[1]), 320)})

    first_analysis_dir = sorted(p.name for p in (ROOT / "results").glob("first_analysis_*") if p.is_dir())

    return {
        "verdicts": verdicts, "secondary": secondary, "plan": plan, "cfg": cfg, "min_n": min_n, "equiv": equiv,
        "units": units, "data_dates": data_dates, "n_probes": n_probes, "tx_sent": tx_sent, "tx_landed": tx_landed,
        "landing": landing, "n_usable_all_arms": n_usable_all_arms, "n_runs": n_runs,
        "spent": spent, "cap": cap, "audit": audit,
        "p_co": p_co, "q_co": q_co, "co_rule": co_rule, "q_s": q_s, "p_e": p_e, "q_e": q_e,
        "anchors": anchors, "not_separated": not_separated, "considerations": considerations,
        "first_analysis": first_analysis_dir,
    }


# ----------------------------------------------------------------------------
# text generated from the data
# ----------------------------------------------------------------------------

def is_descriptive(u: dict, min_n: int) -> bool:
    return u["n"] < min_n or u["verdict"].lower().startswith("insufficient")


def verdict_base(v: str) -> str:
    return v.split(":")[0].strip()


def answer_sentence(d: dict) -> str:
    units, min_n = d["units"], d["min_n"]
    with_p = [u for u in units if u["p"] is not None]
    n_units = len(units)
    above = [u for u in with_p if u["p"] > 0.5]
    if not with_p:
        return "No usable pairs yet: the results files contain no estimates."
    pmin, pmax = min(u["p"] for u in with_p), max(u["p"] for u in with_p)
    lead = f"all {n_units}" if len(above) == n_units else f"{len(above)} of {n_units}"
    s = (f"In {lead} validators the higher-fee transaction came first in more than half "
         f"of the usable pairs (p from {f2(pmin)} to {f2(pmax)})")
    judged = [u for u in units if not is_descriptive(u, min_n)]
    if judged:
        bases = {verdict_base(u["verdict"]) for u in judged}
        if len(bases) == 1:
            base = bases.pop()
            who = "both" if len(judged) == 2 else "all"
            s += f"; {len(judged)} reached the preregistered N of {min_n} and {who} get the verdict \"{base}\""
            if base == "mixed":
                s += ": fee and request position each decide part of the pairs"
        else:
            parts = ", ".join(f"{u['role']} \"{verdict_base(u['verdict'])}\"" for u in judged)
            s += f"; {len(judged)} reached the preregistered N of {min_n}: {parts}"
    else:
        s += f"; none reached the preregistered N of {min_n}"
    n_desc = n_units - len(judged)
    s += "."
    if n_desc:
        s += f" The other {n_desc} are descriptive (N below {min_n})."
    return s


def verdict_chip(u: dict, min_n: int) -> str:
    if is_descriptive(u, min_n):
        return f'<span class="chip chip-soft" title="{esc(u["verdict"])}">descriptive (N &lt; {min_n})</span>'
    v = u["verdict"]
    base = verdict_base(v)
    detail = v[len(base) + 1:].strip() if ":" in v else ""
    out = f'<span class="chip chip-verdict" title="{esc(v)}">{esc(base)}</span>'
    if detail:
        out += f'<div class="vdetail">{esc(detail)}</div>'
    return out


# ----------------------------------------------------------------------------
# HTML pieces
# ----------------------------------------------------------------------------

def hero(d: dict) -> str:
    stats = [
        (fmt_int(d["n_probes"]), "pairs sent"),
        (fmt_int(sum(u["n"] for u in d["units"])), "usable conflicting pairs"),
        (str(len(d["units"])), "validators, one per client"),
        (pct(d["landing"]) if d["landing"] is not None else "n/a", "of transactions landed"),
    ]
    stat_html = "".join(
        f'<div class="stat"><span class="num">{esc(v)}</span><span class="lbl">{esc(l)}</span></div>' for v, l in stats)
    return f"""
<header class="hero">
  <p class="eyebrow reveal"><span>Inside the Solana block</span><span class="sep">measured on mainnet, {esc(d["data_dates"])}</span></p>
  <h1 class="reveal d1">When two transactions compete for the same account, which one does the leader put first?</h1>
  <p class="answer reveal d2">{esc(answer_sentence(d))}</p>
  <div class="cta reveal d3">
    <a class="btn btn-primary" href="#verify">Verify in 60 seconds</a>
    <a class="btn btn-ghost" href="{REPO_URL}/blob/main/REPORT.md">Read the report</a>
  </div>
  <div class="stats reveal d4">{stat_html}</div>
</header>
"""


def scene_svg(orient: str) -> str:
    """The explainer drawing: horizontal (desktop) or vertical (narrow screens)."""
    if orient == "h":
        vb, cls = "0 0 720 230", "scene-h"
        labels = [("req-label", 110, 36, "one request"), ("", 360, 36, "leader"), ("", 620, 36, "block")]
        box = (40, 48, 140, 130)
        routes = ["M180 113 C 240 113, 260 113, 318 113", "M402 113 C 460 113, 480 113, 538 113"]
        leader = (360, 113)
        slots = [(560, 48 + 40 * i, 120, 30) for i in range(4)]
        idx = [(552, 68 + 40 * i) for i in range(4)]
        chips = [("txH", 70, 68, "high fee"), ("txL", 70, 128, "low fee")]
    else:
        vb, cls = "0 0 360 520", "scene-v"
        labels = [("req-label", 180, 24, "one request"), ("leader-label", 230, 244, "leader"), ("block-label", 270, 318, "block")]
        box = (40, 36, 280, 90)
        routes = ["M180 126 L 180 196", "M180 282 L 180 322"]
        leader = (180, 240)
        slots = [(90, 330 + 40 * i, 180, 30) for i in range(4)]
        idx = [(82, 350 + 40 * i) for i in range(4)]
        chips = [("txH", 55, 56, "high fee"), ("txL", 195, 56, "low fee")]
    out = [f'<svg class="{cls}" viewBox="{vb}" role="img" aria-hidden="true">']
    out.append(f'<defs><marker id="arr-{orient}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
               f'<path d="M0 0 L10 5 L0 10 z" fill="var(--line)"/></marker></defs>')
    anchor_of = {"leader-label": "start", "block-label": "end"}
    out.append('<g font-size="12" fill="var(--ink-3)">' + "".join(
        f'<text class="{c}" x="{x}" y="{y}" text-anchor="{anchor_of.get(c, "middle")}">{t}</text>' for c, x, y, t in labels) + '</g>')
    out.append(f'<rect class="box" x="{box[0]}" y="{box[1]}" width="{box[2]}" height="{box[3]}" rx="12"/>')
    out.extend(f'<path class="route" d="{d}" marker-end="url(#arr-{orient})"/>' for d in routes)
    out.append(f'<circle class="leader" cx="{leader[0]}" cy="{leader[1]}" r="38"/>')
    out.append(f'<circle class="leader-pulse" cx="{leader[0]}" cy="{leader[1]}" r="38"/>')
    out.append('<g class="slots">' + "".join(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6"/>' for x, y, w, h in slots) + '</g>')
    out.append('<g font-size="11" fill="var(--ink-3)" text-anchor="end">' + "".join(
        f'<text x="{x}" y="{y}">{i + 1}</text>' for i, (x, y) in enumerate(idx)) + '</g>')
    cw, ch = (90, 30) if orient == "h" else (110, 34)
    for c, x, y, t in chips:
        out.append(f'<g class="tx {c}"><rect x="{x}" y="{y}" width="{cw}" height="{ch}" rx="7"/>'
                   f'<text x="{x + cw / 2:g}" y="{y + ch / 2 + 4.5:g}" text-anchor="middle" font-size="12">{t}</text></g>')
    out.append('</svg>')
    return "".join(out)


def explainer(d: dict) -> str:
    plan = d["plan"]
    price_hi = fmt_int(plan.get("price_high", 0))
    price_lo = fmt_int(plan.get("price_low", 0))
    regimes = [
        ("co", "Buffered together", "fee decides", stat_parts(d["p_co"], "p_co"),
         "Pairs sent before the window that landed in its first slot: the higher fee came first."),
        ("spaced", "Sent 200 ms apart", "arrival decides", stat_parts(d["q_s"], "q_S"),
         "Two requests in random order: the first-sent came first."),
        ("placebo", "Equal fees", "coin flip", stat_parts(d["p_e"], "p"),
         "A randomly labelled pseudo-high transaction came first about half the time."),
    ]
    cards = "".join(f"""
    <button type="button" class="regime" data-regime="{k}" aria-pressed="{'true' if i == 0 else 'false'}">
      <span class="regime-title">{esc(t)} <span class="muted">{esc(sub)}</span></span>
      <span class="regime-num mono">{esc(num[0])}</span><span class="regime-count mono">{esc(num[1])}</span>
      <span class="regime-note">{esc(note)}</span>
    </button>""" for i, (k, t, sub, num, note) in enumerate(regimes))
    return f"""
<section class="explainer" aria-labelledby="h-explainer">
  <h2 id="h-explainer" class="reveal">One request, two transactions, one block</h2>
  <p class="lede reveal d1">Both transactions write the same account, so the leader has to pick an order. One pays a far higher priority fee ({esc(price_hi)} vs {esc(price_lo)} micro-lamports per CU). We read the order from the block.</p>
  <figure class="scene reveal d2" id="scene" data-regime="co" aria-label="Animation: two transactions travel from one request to the leader and land in a block.">
    {scene_svg("h")}
    {scene_svg("v")}
    <figcaption class="regimes" role="group" aria-label="The three regimes we measured">{cards}</figcaption>
  </figure>
</section>
"""


def results(d: dict) -> str:
    min_n, (lo_b, hi_b) = d["min_n"], d["equiv"]
    rows = []
    for i, u in enumerate(d["units"]):
        def lane(kind: str, val, c, k, label: str, n: int):
            if val is None:
                return f'<div class="lane lane-{kind} empty"><span class="mono small">{label}: no data</span></div>'
            lo, hi = c if c else (val, val)
            tip = f"{label} = {f2(val)} [{f2(lo)}, {f2(hi)}]"
            if k is not None:
                tip += f", {k} of {n}"
            return (f'<div class="lane lane-{kind}" style="--lo:{100 * lo:.2f}%;--hi:{100 * hi:.2f}%;--v:{100 * val:.2f}%">'
                    f'<span class="bar"></span>'
                    f'<button type="button" class="mark" data-tip="{esc(tip)}" aria-label="{esc(tip)}"></button></div>')
        rows.append(f"""
      <div class="row reveal" style="--i:{i}">
        <div class="who">
          <div class="role">{esc(u["role"])}</div>
          <div class="meta"><span>{esc(u["client"])} {esc(u["version"])}</span><span class="mono">N = {u["n"]}</span></div>
          {verdict_chip(u, min_n)}
        </div>
        <div class="track" aria-hidden="false">
          {lane("p", u["p"], u["p_ci"], u["p_k"], "p", u["n"])}
          {lane("q", u["q"], u["q_ci"], u["q_k"], "q", u["n"])}
        </div>
      </div>""")

    table_rows = "".join(
        f"<tr><td>{esc(u['role'])}</td><td>{esc(u['client'])} {esc(u['version'])}</td><td class='mono'>{u['n']}</td>"
        f"<td class='mono'>{f2(u['p']) if u['p'] is not None else ''} "
        f"{'[' + f2(u['p_ci'][0]) + ', ' + f2(u['p_ci'][1]) + ']' if u['p_ci'] else ''}</td>"
        f"<td class='mono'>{f2(u['q']) if u['q'] is not None else ''} "
        f"{'[' + f2(u['q_ci'][0]) + ', ' + f2(u['q_ci'][1]) + ']' if u['q_ci'] else ''}</td>"
        f"<td>{esc(u['verdict'])}</td></tr>" for u in d["units"])

    v = d["verdicts"]
    mode = v.get("mode")
    fam = v.get("holm_family_size")
    alpha = d["cfg"].get("alpha")
    bits = []
    if mode:
        bits.append(f"Analysis: {mode}")
    if fam:
        bits.append(f"one Holm family of {fam} tests")
    if alpha is not None:
        bits.append(f"alpha {alpha}")
    note = "; ".join(bits)
    first = ""
    if d["first_analysis"]:
        name = d["first_analysis"][-1]
        first = (f' The first analysis is kept unchanged in <a href="{REPO_URL}/tree/main/results/{esc(name)}">'
                 f'results/{esc(name)}/</a>.')

    ticks = "".join(f'<span style="left:{t * 100:.0f}%">{t:g}</span>' for t in (0, 0.25, 0.5, 0.75, 1))
    return f"""
<section class="results" id="results" aria-labelledby="h-results">
  <h2 id="h-results" class="reveal">Eight validators, one per client</h2>
  <p class="lede reveal d1">p is the share of usable pairs in which the higher-fee transaction came first; q the share in which the first in the request came first. Dots are point estimates, bars are exact 95% intervals. The band marks the preregistered "no rule" zone, {f2(lo_b)} to {f2(hi_b)}. Sorted by N.</p>
  <div class="legend reveal d2" aria-hidden="true">
    <span><i class="sw sw-p"></i>p: higher fee first</span>
    <span><i class="sw sw-q"></i>q: first in request first</span>
    <span><i class="sw sw-band"></i>no-rule band</span>
  </div>
  <div class="chart">
    <div class="axis-row"><div class="who"></div><div class="axis mono">{ticks}</div></div>
    {''.join(rows)}
  </div>
  <p class="foot reveal">{esc(note)}.{first} Verdict rules and thresholds (N of at least {min_n}, strict, strong, partial, mixed, no rule) are fixed in <a href="{REPO_URL}/blob/main/docs/PREREGISTRATION.md">docs/PREREGISTRATION.md</a>. Source: <a href="{REPO_URL}/blob/main/results/verdicts.json">results/verdicts.json</a>.</p>
  <details class="tbl reveal">
    <summary>Show as table</summary>
    <div class="scroll"><table>
      <thead><tr><th>Validator</th><th>Client, version</th><th>N</th><th>p [95% CI]</th><th>q [95% CI]</th><th>Preregistered verdict</th></tr></thead>
      <tbody>{table_rows}</tbody>
    </table></div>
  </details>
</section>
"""


def how(d: dict) -> str:
    plan = d["plan"]
    ratio = ""
    try:
        ratio = f"{plan['price_high'] / plan['price_low']:,.0f}x"
    except (KeyError, TypeError, ZeroDivisionError):
        ratio = "higher"
    tau = plan.get("tau0_ms")
    tau_s = f"about {abs(int(tau))} ms before" if isinstance(tau, (int, float)) else "just before"
    gap = plan.get("gap_ms", 200)
    cards = [
        ("1", "A conflicting pair",
         f"Two of our own transactions, from two payers, both writing one fresh shared account. The scheduler must put one before the other. The compute unit price differs {ratio}: {fmt_int(plan.get('price_high', 0))} vs {fmt_int(plan.get('price_low', 0))} micro-lamports per CU."),
        ("2", "Randomized fee and position",
         f"Which transaction is high-fee and which goes first in the request are drawn independently. Sent as one JSON-RPC request {tau_s} the target's leader window; a separate arm sends two requests {gap} ms apart."),
        ("3", "Block producer read from the block",
         "A pair is usable only if both transactions sit in one block produced by the target, read from the block's Fee reward and never assumed from the schedule, inside the targeted window."),
        ("4", "Preregistered and anchored on mainnet",
         f"Estimands, thresholds, N of at least {d['min_n']} and the equivalence margin were fixed before the data. Hashes of the plan and of the data were written to mainnet as memo transactions."),
    ]
    card_html = "".join(f"""
    <div class="card reveal" style="--i:{i}">
      <span class="idx mono">{esc(n)}</span>
      <h3>{esc(t)}</h3>
      <p>{esc(b)}</p>
    </div>""" for i, (n, t, b) in enumerate(cards))
    acc = "".join(f"""
    <details class="acc reveal" style="--i:{i}">
      <summary><span>{esc(c["title"])}</span><i class="chev" aria-hidden="true"></i></summary>
      <p>{esc(c["text"])}</p>
    </details>""" for i, c in enumerate(d["considerations"]))
    return f"""
<section class="how" id="how" aria-labelledby="h-how">
  <h2 id="h-how" class="reveal">How it works</h2>
  <div class="cards">{card_html}</div>
  <h3 class="sub reveal">The six considerations</h3>
  <p class="lede reveal d1">How the design handles each point of the bounty, shortened from <a href="{REPO_URL}/blob/main/docs/DESIGN.md">docs/DESIGN.md</a>.</p>
  <div class="accordion">{acc}</div>
</section>
"""


def verify(d: dict) -> str:
    cmds = [
        ("Clone", f"git clone {REPO_URL}.git\ncd Inside-The-Solana-Block"),
        ("Re-check our transactions against mainnet blocks (public RPC, no key)", "docker compose run --rm verify"),
        ("Without Docker", "python3 -m venv .venv && . .venv/bin/activate && pip install -e . && itb verify"),
    ]
    cmd_html = "".join(f"""
    <div class="cmd reveal" style="--i:{i}">
      <div class="cmd-label">{esc(t)}</div>
      <pre class="mono"><code>{esc(c)}</code><button type="button" class="copy" data-copy="{esc(c)}" aria-label="Copy command">copy</button></pre>
    </div>""" for i, (t, c) in enumerate(cmds))
    anchor_items = []
    for i, a in enumerate(d["anchors"]):
        when = a["when"] + (" UTC" if re.search(r"\d:\d", a["when"]) else "")
        if a["slot"]:
            when += " / slot " + a["slot"]
        anchor_items.append(
            f'<li class="anchor reveal" style="--i:{i}">'
            f'<div class="a-head"><span class="a-label">{esc(a["label"])}</span><span class="a-when mono">{esc(when)}</span></div>'
            f'<a class="sig mono" href="{EXPLORER}{esc(a["sig"])}" rel="noopener">{esc(a["sig"])}</a></li>')
    anchors = "".join(anchor_items)
    spent, cap = d["spent"], d["cap"]
    ratio = spent / cap if cap else 0
    audit_ok = (d["audit"] or {}).get("RESULT")
    audit_line = f" Audit: {esc(audit_ok)}, every fee-paying transaction of our accounts is in the spend ledger." if audit_ok else ""
    return f"""
<section class="verify" id="verify" aria-labelledby="h-verify">
  <h2 id="h-verify" class="reveal">Verify in 60 seconds</h2>
  <p class="lede reveal d1">Pick a random sample of our landed transactions, fetch the blocks from a public RPC and confirm the recorded positions and producers. No wallet, no key, nothing is sent.</p>
  <div class="cmds">{cmd_html}</div>
  <h3 class="sub reveal">Mainnet anchors</h3>
  <p class="lede reveal d1">Each anchor is a memo transaction carrying the SHA-256 of a file in this repository. Compare it with <span class="mono">sha256sum</span> of the file at the named commit.</p>
  <ul class="anchors">{anchors}</ul>
  <div class="spend reveal">
    <div class="spend-head"><span>Spend</span><span class="mono">{fmt_int(spent)} of {fmt_int(cap)} lamports ({spent / 1e9:.4f} of {cap / 1e9:.2f} SOL)</span></div>
    <div class="meter" role="meter" aria-valuemin="0" aria-valuemax="{cap}" aria-valuenow="{spent}" aria-label="Fees settled against the hard cap"><span style="--w:{100 * ratio:.1f}%"></span></div>
    <p class="foot">The cap is enforced in code before every send; fees settle only for transactions that land.{audit_line}</p>
  </div>
</section>
"""


def limits(d: dict) -> str:
    items = "".join(f'<li class="reveal" style="--i:{i}">{esc(t)}</li>' for i, t in enumerate(d["not_separated"]))
    return f"""
<section class="limits" id="limits" aria-labelledby="h-limits">
  <h2 id="h-limits" class="reveal">What we do not separate</h2>
  <ul class="bullets">{items}</ul>
  <p class="foot reveal">The full list of problems, in order, is in <a href="{REPO_URL}/blob/main/REPORT.md#7-what-went-wrong">What went wrong</a> in the report.</p>
</section>
"""


def footer(d: dict) -> str:
    return f"""
<footer class="site-foot">
  <span><a href="{REPO_URL}">github.com/recruitabx/Inside-The-Solana-Block</a></span>
  <span>MIT license</span>
  <span>Data: {esc(d["data_dates"])}, {d["n_runs"]} runs</span>
</footer>
"""


# ----------------------------------------------------------------------------
# CSS and JS (no f-strings here, so braces are literal)
# ----------------------------------------------------------------------------

CSS = r"""
:root{
  --bg:#fbfbfa; --surface:#ffffff; --ink:#15161a; --ink-2:#4a4d55; --ink-3:#7a7e88;
  --line:#e3e4e8; --line-2:#cfd1d7; --accent:#4f46e5; --accent-ink:#ffffff; --accent-soft:#eceafc;
  --q:#8a8f9c; --band:rgba(21,22,26,.045); --shadow:0 1px 2px rgba(0,0,0,.04),0 8px 24px rgba(0,0,0,.05);
  --radius:14px; --ease:cubic-bezier(.2,.7,.2,1);
  color-scheme:light;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --bg:#0f1013; --surface:#16181d; --ink:#eef0f3; --ink-2:#b4b8c2; --ink-3:#7f8491;
    --line:#262931; --line-2:#363a44; --accent:#8b8cf8; --accent-ink:#0f1013; --accent-soft:#232346;
    --q:#8d93a1; --band:rgba(255,255,255,.06); --shadow:0 1px 2px rgba(0,0,0,.3),0 8px 24px rgba(0,0,0,.25);
    color-scheme:dark;
  }
}
:root[data-theme="dark"]{
  --bg:#0f1013; --surface:#16181d; --ink:#eef0f3; --ink-2:#b4b8c2; --ink-3:#7f8491;
  --line:#262931; --line-2:#363a44; --accent:#8b8cf8; --accent-ink:#0f1013; --accent-soft:#232346;
  --q:#8d93a1; --band:rgba(255,255,255,.06); --shadow:0 1px 2px rgba(0,0,0,.3),0 8px 24px rgba(0,0,0,.25);
  color-scheme:dark;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth;-webkit-text-size-adjust:100%;overflow-x:clip}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;font-feature-settings:"cv11","ss01";-webkit-font-smoothing:antialiased;overflow-x:hidden}
.mono{font-family:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-feature-settings:normal}
a{color:inherit;text-decoration:underline;text-decoration-color:var(--line-2);text-underline-offset:3px;transition:text-decoration-color .2s}
a:hover{text-decoration-color:var(--accent)}
main{max-width:1040px;margin:0 auto;padding:0 clamp(16px,4vw,40px)}
section,header.hero{padding:clamp(56px,9vw,112px) 0;border-top:1px solid var(--line)}
header.hero{border-top:0}
h1{font-size:clamp(30px,5.2vw,58px);line-height:1.08;letter-spacing:-.025em;font-weight:600;margin:14px 0 22px;max-width:18ch;text-wrap:balance}
h2{font-size:clamp(24px,3.2vw,36px);line-height:1.15;letter-spacing:-.02em;font-weight:600;margin:0 0 14px;text-wrap:balance}
h3{font-size:18px;font-weight:600;margin:0 0 8px;letter-spacing:-.01em}
h3.sub{margin-top:clamp(40px,6vw,64px);font-size:22px}
p{margin:0 0 12px}
.lede{color:var(--ink-2);max-width:66ch;font-size:17px;margin-bottom:28px}
.muted{color:var(--ink-3);font-weight:400}
.small{font-size:13px}
.foot{color:var(--ink-3);font-size:14px;max-width:72ch;margin-top:20px}
.eyebrow{color:var(--ink-3);font-size:14px;letter-spacing:.01em;display:flex;flex-wrap:wrap;align-items:center;gap:4px 10px;margin:0}
.eyebrow span{white-space:nowrap;display:inline-flex;align-items:center;gap:10px}
.eyebrow .sep::before{content:"";width:5px;height:5px;border-radius:50%;background:var(--accent);display:inline-block}
.answer{font-size:clamp(17px,1.6vw,20px);line-height:1.55;color:var(--ink-2);max-width:62ch;text-wrap:pretty}
.cta{display:flex;flex-wrap:wrap;gap:12px;margin:30px 0 0}
.btn{display:inline-flex;align-items:center;gap:8px;padding:12px 20px;border-radius:999px;font-weight:500;font-size:15px;text-decoration:none;border:1px solid var(--line-2);transition:transform .25s var(--ease),background .2s,border-color .2s,box-shadow .25s}
.btn:hover{transform:translateY(-1px)}
.btn-primary{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
.btn-primary:hover{box-shadow:0 8px 24px color-mix(in oklab,var(--accent) 35%,transparent)}
.btn-ghost{background:var(--surface)}
.btn-ghost:hover{border-color:var(--ink-3)}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-top:clamp(40px,6vw,64px);padding-top:28px;border-top:1px solid var(--line)}
.stat .num{display:block;font-family:"JetBrains Mono",ui-monospace,monospace;font-size:clamp(22px,2.6vw,30px);font-weight:500;letter-spacing:-.02em;line-height:1.1}
.stat .lbl{display:block;color:var(--ink-3);font-size:13px;margin-top:6px}

/* reveal */
.reveal{opacity:0;transform:translateY(14px);transition:opacity .7s var(--ease),transform .7s var(--ease);transition-delay:calc(var(--i,0)*60ms)}
.reveal.d1{transition-delay:90ms}.reveal.d2{transition-delay:180ms}.reveal.d3{transition-delay:270ms}.reveal.d4{transition-delay:360ms}
.reveal.in{opacity:1;transform:none}

/* explainer */
.scene{margin:0;background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow);padding:clamp(12px,2.5vw,28px)}
.scene svg{width:100%;height:auto;display:block}
.scene .scene-v{display:none;max-width:400px;margin:0 auto}
.scene .box{fill:none;stroke:var(--line-2);stroke-dasharray:4 5}
.scene .route{fill:none;stroke:var(--line);stroke-width:1.5}
.scene .leader{fill:var(--bg);stroke:var(--line-2);stroke-width:1.5}
.scene .leader-pulse{fill:none;stroke:var(--accent);stroke-width:1.5;opacity:0;transform-box:fill-box;transform-origin:center}
.scene .slots rect{fill:none;stroke:var(--line);stroke-width:1.5}
.scene .tx rect{stroke-width:1.5}
.scene .tx text{font-family:Inter,system-ui,sans-serif;font-weight:500}
.scene .txH rect{fill:var(--accent);stroke:var(--accent)}
.scene .txH text{fill:var(--accent-ink)}
.scene .txL rect{fill:var(--surface);stroke:var(--q)}
.scene .txL text{fill:var(--ink-2)}
.scene .tx{transform:translate(var(--sx),var(--sy))}
.scene .txH{--sx:505px;--sy:-20px;--mx:245px;--my:-14px}
.scene .txL{--sx:505px;--sy:-40px;--mx:245px;--my:14px}
.scene[data-regime="spaced"] .txH,.scene[data-regime="placebo"] .txH{--sy:20px}
.scene[data-regime="spaced"] .txL,.scene[data-regime="placebo"] .txL{--sy:-80px}
.scene[data-regime="placebo"].flip .txH{--sy:-20px}
.scene[data-regime="placebo"].flip .txL{--sy:-40px}
.scene .scene-v .txH{--sx:70px;--sy:272px;--mx:70px;--my:148px}
.scene .scene-v .txL{--sx:-70px;--sy:312px;--mx:-70px;--my:186px}
.scene[data-regime="spaced"] .scene-v .txH,.scene[data-regime="placebo"] .scene-v .txH{--sy:312px}
.scene[data-regime="spaced"] .scene-v .txL,.scene[data-regime="placebo"] .scene-v .txL{--sy:272px}
.scene[data-regime="placebo"].flip .scene-v .txH{--sy:272px}
.scene[data-regime="placebo"].flip .scene-v .txL{--sy:312px}
.scene[data-regime="placebo"] .txH rect{fill:var(--surface);stroke:var(--accent)}
.scene[data-regime="placebo"] .txH text{fill:var(--ink-2)}
@keyframes fly{
  0%{transform:translate(0,0)} 8%{transform:translate(0,0)}
  40%{transform:translate(var(--mx),var(--my))} 55%{transform:translate(var(--mx),var(--my))}
  85%{transform:translate(var(--sx),var(--sy))} 100%{transform:translate(var(--sx),var(--sy))}
}
@keyframes pulse{0%,45%{opacity:0;transform:scale(1)} 55%{opacity:.8;transform:scale(1)} 80%{opacity:0;transform:scale(1.45)} 100%{opacity:0}}
.scene.play .tx{animation:fly 4s var(--ease) infinite}
.scene.play[data-regime="spaced"] .txH{animation-delay:.5s}
.scene.play[data-regime="spaced"] .txL{animation-delay:0s}
.scene.play .leader-pulse{animation:pulse 4s linear infinite}
.regimes{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:18px}
.regime{text-align:left;background:var(--bg);border:1px solid var(--line);border-radius:12px;padding:14px 16px;cursor:pointer;font:inherit;color:inherit;display:grid;gap:6px;transition:border-color .3s,background .3s,box-shadow .3s;position:relative;overflow:hidden}
.regime[aria-pressed="true"]{border-color:var(--accent);background:var(--surface);box-shadow:0 0 0 3px var(--accent-soft)}
.regime-title{font-weight:500;font-size:14px}
.regime-num{font-size:15px;color:var(--ink);font-weight:500}
.regime-count{font-size:12px;color:var(--ink-3);margin-top:-4px}
.regime-note{font-size:13px;color:var(--ink-3);line-height:1.45}
.regime .pb{position:absolute;left:0;bottom:0;height:2px;background:var(--accent);width:0}
.regime[aria-pressed="true"] .pb{animation:pb var(--cycle,4s) linear forwards}
@keyframes pb{from{width:0}to{width:100%}}

/* results */
.legend{display:flex;flex-wrap:wrap;gap:18px;font-size:13px;color:var(--ink-2);margin-bottom:18px}
.legend span{display:inline-flex;align-items:center;gap:8px}
.sw{width:12px;height:12px;border-radius:50%;display:inline-block}
.sw-p{background:var(--accent)}
.sw-q{background:var(--surface);border:2.5px solid var(--q)}
.sw-band{border-radius:3px;background:var(--band);border:1px solid var(--line)}
.chart{display:grid;gap:6px}
.axis-row,.row{display:grid;grid-template-columns:minmax(200px,260px) 1fr;gap:clamp(12px,3vw,32px);align-items:center}
.axis{position:relative;height:18px;font-size:11px;color:var(--ink-3)}
.axis span{position:absolute;transform:translateX(-50%)}
.axis span:first-child{transform:none}
.axis span:last-child{transform:translateX(-100%)}
.row{padding:14px 0;border-top:1px solid var(--line)}
.row:last-child{border-bottom:1px solid var(--line)}
.who .role{font-weight:600;letter-spacing:-.01em}
.who .meta{display:flex;flex-wrap:wrap;gap:4px 12px;color:var(--ink-3);font-size:13px;margin:2px 0 8px}
.chip{display:inline-flex;align-items:center;gap:6px;font-size:12px;padding:3px 10px;border-radius:999px;line-height:1.5;max-width:100%}
.chip-soft{background:var(--band);color:var(--ink-2);border:1px solid var(--line)}
.chip-verdict{background:var(--accent-soft);color:var(--ink);border:1px solid transparent;font-weight:500}
.vdetail{font-size:12.5px;color:var(--ink-3);margin-top:6px;line-height:1.4;max-width:30ch}
.track{position:relative;display:grid;gap:10px;padding:12px 0}
.track::before{content:"";position:absolute;top:0;bottom:0;left:35%;width:30%;background:var(--band);border-radius:4px}
.track::after{content:"";position:absolute;top:0;bottom:0;left:50%;width:1px;background:var(--line-2)}
.lane{position:relative;height:14px}
.lane .bar{position:absolute;top:50%;height:3px;margin-top:-1.5px;border-radius:2px;left:var(--v);width:0;transition:left .9s var(--ease),width .9s var(--ease);transition-delay:calc(var(--i,0)*70ms + 150ms)}
.lane-p .bar{background:var(--accent);opacity:.55}
.lane-q .bar{background:var(--q);opacity:.55}
.lane .mark{position:absolute;top:50%;left:var(--v);width:14px;height:14px;margin:-7px 0 0 -7px;border-radius:50%;padding:0;cursor:default;transform:scale(0);transition:transform .6s var(--ease);transition-delay:calc(var(--i,0)*70ms + 100ms);border:0;box-shadow:0 0 0 2px var(--surface)}
.lane .mark::before{content:"";position:absolute;inset:-8px}
.lane-p .mark{background:var(--accent)}
.lane-q .mark{background:var(--surface);border:3px solid var(--q)}
.row.in .bar{left:var(--lo);width:calc(var(--hi) - var(--lo))}
.row.in .mark{transform:scale(1)}
.mark[data-tip]::after{content:attr(data-tip);position:absolute;left:50%;bottom:calc(100% + 10px);transform:translate(-50%,4px);background:var(--ink);color:var(--bg);font:12px/1.3 "JetBrains Mono",ui-monospace,monospace;padding:6px 9px;border-radius:7px;white-space:nowrap;opacity:0;visibility:hidden;pointer-events:none;transition:opacity .2s,transform .2s,visibility .2s;z-index:3}
.mark:hover::after,.mark:focus-visible::after{opacity:1;visibility:visible;transform:translate(-50%,0)}
.mark:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
.lane.empty{display:flex;align-items:center;color:var(--ink-3)}
.tbl{margin-top:20px}
.tbl summary{cursor:pointer;color:var(--ink-2);font-size:14px;width:max-content}
.scroll{overflow-x:auto;margin-top:12px}
table{border-collapse:collapse;width:100%;font-size:13px;min-width:640px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--ink-3);font-weight:500}

/* how */
.cards{display:grid;grid-template-columns:repeat(2,1fr);gap:14px;margin-top:8px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:22px 22px 18px;box-shadow:var(--shadow)}
.card .idx{color:var(--accent);font-size:13px;display:block;margin-bottom:10px}
.card p{color:var(--ink-2);font-size:15px;margin:0}
.accordion{border-top:1px solid var(--line)}
.acc{border-bottom:1px solid var(--line)}
.acc summary{list-style:none;display:flex;justify-content:space-between;align-items:center;gap:16px;padding:16px 0;cursor:pointer;font-weight:500}
.acc summary::-webkit-details-marker{display:none}
.chev{width:9px;height:9px;border-right:1.5px solid var(--ink-3);border-bottom:1.5px solid var(--ink-3);transform:rotate(45deg);transition:transform .3s var(--ease);flex:none;margin-right:4px}
.acc[open] .chev{transform:rotate(-135deg)}
.acc p{color:var(--ink-2);font-size:15px;max-width:72ch;padding:0 0 18px;margin:0}

/* verify */
.cmds{display:grid;gap:14px}
.cmd-label{font-size:13px;color:var(--ink-3);margin-bottom:6px}
pre{position:relative;margin:0;background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 86px 14px 16px;font-size:13.5px;line-height:1.6;overflow-x:auto;white-space:pre-wrap;word-break:break-word}
.copy{position:absolute;top:10px;right:10px;font:500 12px Inter,system-ui,sans-serif;color:var(--ink-2);background:var(--bg);border:1px solid var(--line-2);border-radius:999px;padding:4px 10px;cursor:pointer;transition:background .2s,color .2s}
.copy:hover{color:var(--ink)}
.copy.done{color:var(--accent);border-color:var(--accent)}
.anchors{list-style:none;margin:0;padding:0;display:grid;gap:10px}
.anchor{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.a-head{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;font-size:14px;margin-bottom:6px}
.a-label{font-weight:500}
.a-when{color:var(--ink-3);font-size:12px}
.sig{display:block;font-size:12.5px;word-break:break-all;color:var(--ink-2)}
.spend{margin-top:clamp(32px,5vw,48px)}
.spend-head{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;font-size:14px;margin-bottom:8px}
.meter{height:6px;background:var(--band);border:1px solid var(--line);border-radius:999px;overflow:hidden}
.meter span{display:block;height:100%;width:0;background:var(--accent);border-radius:999px;transition:width 1.2s var(--ease) .2s}
.spend.in .meter span{width:var(--w)}
.spend .foot{margin-top:10px}

/* limits */
.bullets{margin:0;padding:0;list-style:none;display:grid;gap:10px;max-width:72ch}
.bullets li{position:relative;padding-left:22px;color:var(--ink-2)}
.bullets li::before{content:"";position:absolute;left:0;top:.68em;width:8px;height:8px;border-radius:50%;background:var(--accent-soft);border:1.5px solid var(--accent)}

.site-foot{display:flex;flex-wrap:wrap;gap:10px 28px;padding:28px 0 48px;border-top:1px solid var(--line);color:var(--ink-3);font-size:13px}

@media (max-width:760px){
  .stats{grid-template-columns:repeat(2,1fr)}
  .cards{grid-template-columns:1fr}
  .regimes{grid-template-columns:1fr}
  .scene .scene-h{display:none}
  .scene .scene-v{display:block}
  .axis-row,.row{grid-template-columns:1fr;gap:6px}
  .axis-row .who{display:none}
  .track{padding:14px 0 12px}
  .mark[data-tip]::after{white-space:normal;width:max-content;max-width:220px}
}
@media (max-width:420px){
  pre{padding-right:16px;padding-bottom:40px}
  .copy{top:auto;bottom:8px}
}
@media (prefers-reduced-motion:reduce){
  html{scroll-behavior:auto}
  .reveal{opacity:1;transform:none;transition:none}
  .lane .bar,.lane .mark,.meter span,.btn,.regime,.chev{transition:none}
  .scene.play .tx,.scene.play .leader-pulse{animation:none}
  .scene .tx{transform:translate(var(--sx),var(--sy))}
  .regime[aria-pressed="true"] .pb{animation:none;width:100%}
}
"""

JS = r"""
(function(){
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  // scroll reveals
  var els = document.querySelectorAll('.reveal,.spend');
  if (!reduce && 'IntersectionObserver' in window) {
    var io = new IntersectionObserver(function(entries){
      entries.forEach(function(e){ if (e.isIntersecting || e.boundingClientRect.bottom < 0) { e.target.classList.add('in'); io.unobserve(e.target); } });
    }, {rootMargin:'0px 0px -8% 0px', threshold:0.08});
    els.forEach(function(el){ io.observe(el); });
    // elements jumped past without ever intersecting (instant anchor jumps)
    var pending = Array.prototype.slice.call(els), ticking = false;
    window.addEventListener('scroll', function(){
      if (ticking || !pending.length) return; ticking = true;
      requestAnimationFrame(function(){
        pending = pending.filter(function(el){ if (el.getBoundingClientRect().bottom < 0) { el.classList.add('in'); return false; } return !el.classList.contains('in'); });
        ticking = false;
      });
    }, {passive:true});
  } else {
    els.forEach(function(el){ el.classList.add('in'); });
  }
  // explainer regimes
  var scene = document.getElementById('scene');
  if (scene) {
    var order = ['co','spaced','placebo'], idx = 0, cycle = 4000, timer = null, flip = false;
    var buttons = scene.querySelectorAll('.regime');
    var labels = {co: 'one request', spaced: 'two requests, 200 ms apart', placebo: 'one request, equal fees'};
    var reqLabels = scene.querySelectorAll('.req-label');
    buttons.forEach(function(b){ var pb = document.createElement('span'); pb.className = 'pb'; b.appendChild(pb); });
    scene.style.setProperty('--cycle', cycle + 'ms');
    function show(k, manual){
      idx = order.indexOf(k);
      scene.setAttribute('data-regime', k);
      reqLabels.forEach(function(el){ el.textContent = labels[k]; });
      if (k === 'placebo') { flip = !flip; scene.classList.toggle('flip', flip); }
      buttons.forEach(function(b){
        var on = b.getAttribute('data-regime') === k;
        b.setAttribute('aria-pressed', on ? 'true' : 'false');
        var pb = b.querySelector('.pb'); if (pb) { pb.style.animation = 'none'; void pb.offsetWidth; pb.style.animation = ''; }
      });
      if (!reduce) {
        scene.classList.remove('play'); void scene.offsetWidth; scene.classList.add('play');
        clearTimeout(timer);
        timer = setTimeout(function(){ show(order[(idx + 1) % order.length]); }, cycle);
      }
    }
    buttons.forEach(function(b){ b.addEventListener('click', function(){ show(b.getAttribute('data-regime'), true); }); });
    if (reduce) { show('co'); }
    else if ('IntersectionObserver' in window) {
      var started = false;
      new IntersectionObserver(function(entries, obs){
        if (entries[0].isIntersecting && !started) { started = true; show('co'); obs.disconnect(); }
      }, {threshold:0.3}).observe(scene);
    } else { show('co'); }
  }
  // copy buttons
  document.querySelectorAll('.copy').forEach(function(btn){
    btn.addEventListener('click', function(){
      var text = btn.getAttribute('data-copy');
      var done = function(){ btn.textContent = 'copied'; btn.classList.add('done'); setTimeout(function(){ btn.textContent = 'copy'; btn.classList.remove('done'); }, 1600); };
      if (navigator.clipboard && navigator.clipboard.writeText) { navigator.clipboard.writeText(text).then(done, done); }
      else { var ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta); ta.select(); try { document.execCommand('copy'); } catch (e) {} document.body.removeChild(ta); done(); }
    });
  });
})();
"""


# ----------------------------------------------------------------------------
# assemble
# ----------------------------------------------------------------------------

def build() -> str:
    d = load_all()
    desc = ("Eight Solana mainnet validators, one per client, measured with randomized conflicting transaction pairs: "
            "does the higher fee or the request position decide the order in the block?")
    body = hero(d) + explainer(d) + results(d) + how(d) + verify(d) + limits(d) + footer(d)
    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Inside the Solana Block</title>
<meta name="description" content="{esc(desc)}">
<meta name="color-scheme" content="light dark">
<meta property="og:title" content="Inside the Solana Block">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{PAGES_URL}">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%234f46e5'/%3E%3Ccircle cx='11' cy='16' r='5' fill='%23fff'/%3E%3Ccircle cx='22' cy='16' r='5' fill='none' stroke='%23fff' stroke-width='2.5'/%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap">
<style>{CSS}</style>
</head>
<body>
<main>
{body}
</main>
<script>{JS}</script>
</body>
</html>
"""
    page = page.replace(EM_DASH, ", ")
    assert EM_DASH not in page
    return page


def main() -> None:
    out_dir = ROOT / "docs"
    out_dir.mkdir(exist_ok=True)
    page = build()
    (out_dir / "index.html").write_text(page, encoding="utf-8")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    print(f"wrote docs/index.html ({len(page.encode('utf-8')) / 1024:.1f} KB) and docs/.nojekyll")


if __name__ == "__main__":
    main()
