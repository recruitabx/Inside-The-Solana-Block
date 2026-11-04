#!/usr/bin/env python3
"""Build docs/index.html (the GitHub Pages landing page) from the repository files.

Every number on the page is read at build time from:
  results/verdicts.json, results/secondary.json, results/runs.csv, results/runs.md,
  results/audit.txt, results/verify_sample.txt, results/first_analysis_*/verdicts.json,
  data/plan.json, data/anchors/, REPORT.md (anchors, timeline and the "what we do not
  separate" list), docs/DESIGN.md (the Considerations table), docs/PREREGISTRATION.md
  (amendments), docs/CALIBRATION.md (known answers), docs/research/ (citation checks)
  and tests/ (unit tests).

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
WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight",
         9: "nine", 10: "ten", 11: "eleven", 12: "twelve"}


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


def word(n: int) -> str:
    return WORDS.get(int(n), str(n))


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


def num(row: dict, key: str) -> float:
    try:
        return float((row or {}).get(key) or 0)
    except (ValueError, TypeError):
        return 0.0


def gh_slug(heading: str) -> str:
    s = heading.strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    return re.sub(r"\s+", "-", s).strip("-")


# ----------------------------------------------------------------------------
# data
# ----------------------------------------------------------------------------

def parse_units(verdicts: dict) -> list[dict]:
    units = []
    for u in verdicts.get("units", []):
        fee, send = u.get("fee", {}) or {}, u.get("send", {}) or {}
        n = int(u.get("n_primary", fee.get("n", 0)) or 0)
        versions = u.get("versions_seen") or []
        units.append({
            "role": u.get("target_role", ""),
            "client": u.get("client_id", ""),
            "version": ", ".join(versions),
            "identity": u.get("identity", ""),
            "n": n,
            "n_probes": int(u.get("n_probes_arm_P", 0) or 0),
            "n_probes_all": int(u.get("n_probes_all_arms", 0) or 0),
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
    return units


def load_runs() -> dict:
    runs = []
    path = ROOT / "results/runs.csv"
    if path.exists():
        with path.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                runs.append(row)
    run_rows = [r for r in runs if r.get("row_type") == "run"]
    main_runs = [r for r in run_rows if r.get("phase") not in ("pilot", "repilot")]
    starts = sorted(r["start_utc"] for r in main_runs if r.get("start_utc"))
    ends = sorted((r.get("end_utc") or r.get("start_utc")) for r in main_runs if r.get("start_utc"))
    first_day = starts[0][:10] if starts else ""
    last_day = ends[-1][:10] if ends else first_day
    data_dates = first_day if first_day == last_day else f"{first_day} to {last_day}"
    totals = {r["run_id"]: r for r in runs if r.get("row_type") in ("phase_total", "total")}
    tot_all = totals.get("TOTAL all", {})

    def total(key: str, rows: list[dict]) -> int:
        return int(sum(num(r, key) for r in rows))

    out = {
        "n_runs": len(main_runs),
        "n_runs_all": len(run_rows),
        "data_dates": data_dates,
        "first_day": first_day,
        "last_day": last_day,
        "main_probes": total("probes_sent", main_runs),
        "main_tx_sent": total("tx_sent", main_runs),
        "main_tx_landed": total("tx_landed", main_runs),
        "main_usable": total("usable_probes", main_runs),
        "all_tx_sent": total("tx_sent", run_rows) or int(num(tot_all, "tx_sent")),
        "all_tx_landed": total("tx_landed", run_rows) or int(num(tot_all, "tx_landed")),
        "all_probes": total("probes_sent", run_rows) or int(num(tot_all, "probes_sent")),
        "all_fees": total("fees_settled_lamports", run_rows) or int(num(tot_all, "fees_settled_lamports")),
        "run_anchors": sum(1 for r in run_rows if (r.get("anchor_signature") or "").strip()),
        "phases": sorted({r.get("phase", "") for r in main_runs}),
    }
    return out


def parse_by_role(runs_md: str) -> list[dict]:
    """The 'Main phase by role' table in results/runs.md: role, probes, usable."""
    rows = []
    sec = section(runs_md, r"^## .*by role.*$")
    for line in sec.splitlines():
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cells = [strip_md(c) for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[0].lower() in ("role", "total"):
            continue
        try:
            probes, usable = int(cells[1].replace(",", "")), int(cells[2].replace(",", ""))
        except ValueError:
            continue
        if probes > 0:
            rows.append({"role": cells[0], "probes": probes, "usable": usable, "share": usable / probes})
    return rows


def parse_calibration(cal: str) -> dict:
    """Known answers from the results block of docs/CALIBRATION.md.

    Lines look like:  A    60/60      60/60 = 1.000 [...]   26/60 = 0.433 [...]
    Condition A tests arrival order (first-sent-first), B tests priority (higher-fee-first).
    """
    out = {}
    pat = re.compile(r"^([A-Z])\s+(\d+)/(\d+)\s+(\d+)/(\d+)\s*=.*?(\d+)/(\d+)\s*=", re.M)
    for m in pat.finditer(cal):
        cond = m.group(1)
        out[cond] = {"same_slot": (int(m.group(2)), int(m.group(3))),
                     "first_sent": (int(m.group(4)), int(m.group(5))),
                     "higher_fee": (int(m.group(6)), int(m.group(7)))}
    res = {}
    if "A" in out:
        res["arrival"] = out["A"]["first_sent"]
    if "B" in out:
        res["priority"] = out["B"]["higher_fee"]
    return res


def count_citations() -> tuple[int, int]:
    """(documents, citations that PASS their check) over docs/research/*.md."""
    docs = sorted((ROOT / "docs/research").glob("*.md"))
    total = 0
    for p in docs:
        t = p.read_text(encoding="utf-8")
        m = re.search(r"^#+ .*Citation check.*$", t, re.M)
        sec = t[m.end():] if m else ""
        counted = max(
            len(re.findall(r"^\|\s*PASS\s*\|", sec, re.M)),
            len(re.findall(r"\b[A-Z]\d{2,3}:?\s?PASS\b", sec)),
            len(re.findall(r" PASS$", sec, re.M)),
        )
        declared = [int(x) for x in re.findall(r"PASS\s*[=:]?\s*(\d+)\b", sec)]
        declared += [int(x) for x in re.findall(r"PASS\s+(\d+),", sec)]
        total += max([counted] + declared)
    return len(docs), total


def parse_timeline(report: str) -> list[dict]:
    """Rows of the REPORT.md section 1 table: when, title, detail, signature, slot."""
    events = []
    sec1 = section(report, r"^## 1\.")
    for line in sec1.splitlines():
        if not line.startswith("|") or line.startswith("|---") or line.lower().startswith("| when"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        when = strip_md(cells[0])
        raw = cells[1]
        sig = re.search(r"`([1-9A-HJ-NP-Za-km-z]{80,90})`", raw)
        slot = re.search(r"slot (\d+)", raw)
        what = strip_md(raw)
        if sig:
            what = what.replace(sig.group(1), "").replace("memo transaction", "memo transaction")
        what = re.sub(r"\s+", " ", what).replace(" ,", ",").replace("( )", "").replace("()", "").strip(" :,")
        if ":" in what:
            title, detail = what.split(":", 1)
        elif ", " in what:
            title, detail = what.split(", ", 1)
        else:
            title, detail = what, ""
        # file references in parentheses go to the detail line, not the title
        refs = re.findall(r"\(((?:docs|data|results|src)/[^)]+)\)", title)
        title = re.sub(r"\s*\((?:docs|data|results|src)/[^)]+\)", "", title).strip()
        if refs:
            detail = (detail.strip() + "; " if detail.strip() else "") + ", ".join(refs)
        title = title[:1].upper() + title[1:]
        detail = re.sub(r"\(slot \d+\)", "", detail)
        detail = re.sub(r"\s+", " ", detail).strip(" ,.;")
        detail = re.sub(r"\(\s*\)", "", detail).strip(" ,")
        if detail.lower() in ("memo transaction", "memo"):
            detail = ""
        events.append({"when": when, "title": title, "detail": detail,
                       "sig": sig.group(1) if sig else "", "slot": slot.group(1) if slot else ""})
    return events


def load_all() -> dict:
    verdicts = load_json("results/verdicts.json")
    secondary = load_json("results/secondary.json")
    plan = load_json("data/plan.json")
    report = read_text("REPORT.md")
    design = read_text("docs/DESIGN.md")
    prereg = read_text("docs/PREREGISTRATION.md")
    calibration = read_text("docs/CALIBRATION.md")
    runs_md = read_text("results/runs.md")

    cfg = verdicts.get("config", {}) if isinstance(verdicts, dict) else {}
    min_n = int(cfg.get("min_n", 100))
    equiv = (float(cfg.get("equiv_lo", 0.35)), float(cfg.get("equiv_hi", 0.65)))
    units = parse_units(verdicts)
    runs = load_runs()

    n_probes = int(verdicts.get("n_rows_analysed") or runs["main_probes"] or sum(u["n_probes"] for u in units))
    tx_sent = runs["main_tx_sent"]
    tx_landed = runs["main_tx_landed"]
    landing = tx_landed / tx_sent if tx_sent else None

    # --- spend
    audit = None
    audit_txt = read_text("results/audit.txt")
    if audit_txt.strip():
        try:
            audit = json.loads(audit_txt)
        except json.JSONDecodeError:
            audit = None
    spent = int((audit or {}).get("settled_fees_lamports") or runs["all_fees"])
    cap = int((audit or {}).get("hard_ceiling_lamports") or 50_000_000)

    # --- verify sample
    verify_txt = read_text("results/verify_sample.txt")
    vm = re.search(r"RESULT:\s*(\w+)\s*\((\d+)/(\d+)", verify_txt)
    verify = {"result": vm.group(1), "k": int(vm.group(2)), "n": int(vm.group(3))} if vm else None

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

    # --- timeline and anchors from REPORT.md section 1
    timeline = parse_timeline(report)
    anchors = [e for e in timeline if e["sig"]]

    # --- what we do not separate: REPORT.md section 6
    not_separated = []
    for line in section(report, r"^## 6\.").splitlines():
        if line.lstrip().startswith("- "):
            not_separated.append(strip_md(line.lstrip()[2:]))
    wrong = re.search(r"^## (\d+\.\s*What went wrong.*)$", report, re.M)
    wrong_anchor = gh_slug(wrong.group(1)) if wrong else "7-what-went-wrong"

    # --- considerations: docs/DESIGN.md table
    considerations = []
    for line in section(design, r"^## How the design handles each consideration").splitlines():
        if not line.startswith("|") or line.startswith("|---") or line.startswith("| Consideration"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2:
            considerations.append({"title": strip_md(cells[0]), "text": shorten(strip_md(cells[1]), 330)})

    # --- first analysis (archived), if any
    first_dirs = sorted(p for p in (ROOT / "results").glob("first_analysis_*") if p.is_dir())
    first = None
    if first_dirs:
        fdir = first_dirs[-1]
        fv = load_json(f"results/{fdir.name}/verdicts.json", required=False)
        if isinstance(fv, dict):
            funits = {u["role"]: u for u in parse_units(fv)}
            differs = any((funits.get(u["role"], {}).get("n") != u["n"]) for u in units) or len(funits) != len(units)
            first = {"name": fdir.name, "date": fdir.name.replace("first_analysis_", ""), "units": funits,
                     "differs": differs, "n_probes": fv.get("n_rows_analysed"), "cfg": fv.get("config", {})}

    # --- depth counts
    by_role = parse_by_role(runs_md)
    if not by_role:
        by_role = [{"role": u["role"], "probes": u["n_probes"], "usable": u["n"], "share": u["n"] / u["n_probes"]}
                   for u in units if u["n_probes"]]
        by_role_note = "arm P only (results/verdicts.json)"
    else:
        by_role_note = "all arms (results/runs.md)"
    by_role.sort(key=lambda r: -r["share"])
    client_of = {u["role"]: u["client"] for u in units}
    for r in by_role:
        r["client"] = client_of.get(r["role"], "")

    n_docs, n_citations = count_citations()
    n_amend = len(re.findall(r"\*\*Amendment", prereg))
    n_tests = 0
    for p in (ROOT / "tests").glob("test_*.py"):
        n_tests += len(re.findall(r"^\s*def test_", p.read_text(encoding="utf-8"), re.M))
    n_snapshots = len(list((ROOT / "data/snapshots").glob("*.json"))) + len(list((ROOT / "data/selection/snapshots").glob("*.json")))
    n_manifest_files = 0
    for p in (ROOT / "data/anchors").glob("*.txt"):
        n_manifest_files += sum(1 for ln in p.read_text(encoding="utf-8").splitlines() if re.search(r"[0-9a-f]{64}", ln))
    calib = parse_calibration(calibration)
    clients = sorted({u["client"] for u in units})

    return {
        "verdicts": verdicts, "secondary": secondary, "plan": plan, "cfg": cfg, "min_n": min_n, "equiv": equiv,
        "units": units, "clients": clients, "runs": runs, "data_dates": runs["data_dates"],
        "n_probes": n_probes, "tx_sent": tx_sent, "tx_landed": tx_landed, "landing": landing,
        "spent": spent, "cap": cap, "audit": audit, "verify": verify,
        "p_co": p_co, "q_co": q_co, "co_rule": co_rule, "q_s": q_s, "p_e": p_e, "q_e": q_e,
        "timeline": timeline, "anchors": anchors, "not_separated": not_separated, "wrong_anchor": wrong_anchor,
        "considerations": considerations, "first": first,
        "by_role": by_role, "by_role_note": by_role_note,
        "n_docs": n_docs, "n_citations": n_citations, "n_amend": n_amend, "n_tests": n_tests,
        "n_snapshots": n_snapshots, "n_manifest_files": n_manifest_files, "calib": calib,
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
    if not with_p:
        return "No usable pairs yet: the results files contain no estimates."
    above = [u for u in with_p if u["p"] > 0.5]
    pmin, pmax = min(u["p"] for u in with_p), max(u["p"] for u in with_p)
    lead = f"all {word(n_units)}" if len(above) == n_units else f"{word(len(above))} of {word(n_units)}"
    s = (f"In {lead} validators the higher-fee transaction came first in more than half of the usable pairs, "
         f"p from {f2(pmin)} to {f2(pmax)}, but never strictly.")
    judged = [u for u in units if not is_descriptive(u, min_n)]
    if judged:
        bases = {verdict_base(u["verdict"]) for u in judged}
        if len(bases) == 1:
            base = bases.pop()
            who = "both" if len(judged) == 2 else "all"
            s += f" {word(len(judged)).capitalize()} reached the preregistered N of {min_n} and {who} get the verdict \"{base}\""
            s += ": fee and request position each decide part of the pairs." if base == "mixed" else "."
        else:
            parts = ", ".join(f"{u['role']} \"{verdict_base(u['verdict'])}\"" for u in judged)
            s += f" {word(len(judged)).capitalize()} reached the preregistered N of {min_n}: {parts}."
    else:
        s += f" None reached the preregistered N of {min_n}."
    n_desc = n_units - len(judged)
    if n_desc:
        s += f" The other {word(n_desc)} are descriptive, N below {min_n}."
    return s


def delivery_sentence(d: dict) -> str:
    rows = d["by_role"]
    if len(rows) < 2:
        return ""
    # split at the largest ratio gap between consecutive shares (ascending); the low group
    # must be clearly separated (ratio of at least 1.6) and at most half of the roles
    asc = sorted(rows, key=lambda r: r["share"])
    best_i, best_ratio = None, 0.0
    for i in range(1, len(asc)):
        lo_s = asc[i - 1]["share"]
        ratio = asc[i]["share"] / lo_s if lo_s > 0 else float("inf")
        if i <= len(asc) // 2 and ratio > best_ratio:
            best_i, best_ratio = i, ratio
    low = asc[:best_i] if best_i and best_ratio >= 1.6 else []
    high = asc[best_i:] if low else []
    if low and high:
        names = ", ".join(r["role"] for r in low)
        lo_min, lo_max = min(r["share"] for r in low), max(r["share"] for r in low)
        hi_min, hi_max = min(r["share"] for r in high), max(r["share"] for r in high)
        fams = []
        if any("Fire" in r["client"] for r in low):
            fams.append("Firedancer-family")
        if any("Harmonic" in r["client"] for r in low):
            fams.append("Harmonic")
        covered = all(("Fire" in r["client"]) or ("Harmonic" in r["client"]) for r in low)
        who = (" and ".join(fams) + " leaders") if (fams and covered) else "The leaders"
        return (f"{who} ({names}) included our RPC-sent pair in their own window in only "
                f"{pct(lo_min)} to {pct(lo_max)} of probes, against {pct(hi_min)} to {pct(hi_max)} for the others. "
                f"Most of their pairs landed one or more windows later, in other leaders' blocks.")
    best, worst = rows[0], rows[-1]
    return (f"The share of probes whose pair landed in the target's own window ranged from {pct(worst['share'])} "
            f"({worst['role']}) to {pct(best['share'])} ({best['role']}).")


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


def stat_str(stat: dict, name: str) -> str:
    if not isinstance(stat, dict) or not stat.get("n"):
        return f"{name}: no data"
    c = ci(stat)
    s = f"{name} = {f2(stat['p'])}"
    if c:
        s += f" [{f2(c[0])}, {f2(c[1])}]"
    return s


# ----------------------------------------------------------------------------
# HTML pieces
# ----------------------------------------------------------------------------

def metric(value: float, text: str, label: str, dec: int = 0, suffix: str = "") -> str:
    return (f'<div class="metric"><span class="num mono" data-count="{value:g}" data-dec="{dec}" data-suffix="{esc(suffix)}" '
            f'style="min-width:{len(text)}ch">{esc(text)}</span><span class="ul"></span><span class="lbl">{esc(label)}</span></div>')


def nav() -> str:
    return f"""
<nav class="nav" aria-label="Page"><div class="nav-in">
  <a class="brand" href="#top"><i class="brand-dot" aria-hidden="true"></i>Inside the Solana Block</a>
  <div class="nav-links">
    <a href="#results">Results</a><a href="#depth">Depth</a><a href="#method">Method</a><a href="#verify">Verify</a>
    <a class="nav-gh" href="{REPO_URL}" rel="noopener">GitHub</a>
  </div>
</div></nav>
"""


def hero(d: dict) -> str:
    usable = sum(u["n"] for u in d["units"])
    n_units, n_clients = len(d["units"]), len(d["clients"])
    metrics = [
        metric(d["n_probes"], fmt_int(d["n_probes"]), "pairs sent into leader windows"),
        metric(usable, fmt_int(usable), "usable conflicting pairs"),
        metric(n_units, str(n_units), f"validators, {n_clients} client types"),
        metric(d["tx_landed"], fmt_int(d["tx_landed"]), f"transactions landed ({pct(d['landing']) if d['landing'] is not None else 'n/a'})"),
    ]
    return f"""
<header class="hero" id="top">
  <div class="hero-grid">
    <div class="hero-copy">
      <p class="eyebrow reveal"><span class="pill">Solana mainnet</span><span class="dim">measured {esc(d["data_dates"])}, after Alpenglow</span></p>
      <h1 class="reveal d1">When two transactions compete,<br><span class="grad-text">who goes first?</span></h1>
      <p class="answer reveal d2">{esc(answer_sentence(d))}</p>
      <div class="cta reveal d3">
        <a class="btn btn-primary" href="#verify">Verify in 60 seconds</a>
        <a class="btn btn-ghost" href="{REPO_URL}/blob/main/REPORT.md" rel="noopener">Read the report</a>
      </div>
    </div>
    <figure class="hero-visual reveal d2" aria-label="A block of transactions assembling; the high-fee and the low-fee transaction of one pair drop into place.">
      <canvas id="blk" width="600" height="420"></canvas>
      <figcaption class="mono">one leader block, one of our pairs</figcaption>
    </figure>
  </div>
  <div class="metrics reveal d4">{''.join(metrics)}</div>
</header>
"""


def regime_glyph(kind: str) -> str:
    g = '<linearGradient id="gg-' + kind + '" x1="0" x2="1"><stop offset="0" stop-color="#9945FF"/><stop offset="1" stop-color="#14F195"/></linearGradient>'
    hi = 'fill="url(#gg-' + kind + ')"'
    lo = 'fill="none" stroke="rgba(255,255,255,.55)" stroke-width="1.5"'
    if kind == "co":
        body = (f'<rect x="8" y="10" width="104" height="28" rx="8" fill="none" stroke="rgba(255,255,255,.18)" stroke-dasharray="3 4"/>'
                f'<rect x="38" y="17" width="18" height="14" rx="4" {hi}/><rect x="64" y="17" width="18" height="14" rx="4" {lo}/>')
    elif kind == "spaced":
        body = (f'<rect x="12" y="17" width="18" height="14" rx="4" {hi}/><rect x="90" y="17" width="18" height="14" rx="4" {lo}/>'
                f'<path d="M36 24 H84" stroke="rgba(255,255,255,.3)" stroke-dasharray="2 4"/>'
                f'<text x="60" y="13" text-anchor="middle" font-size="9" fill="rgba(255,255,255,.6)" font-family="JetBrains Mono,monospace">200 ms</text>')
    else:
        body = (f'<rect x="38" y="17" width="18" height="14" rx="4" {lo}/><rect x="64" y="17" width="18" height="14" rx="4" {lo}/>'
                f'<text x="60" y="28" text-anchor="middle" font-size="11" fill="rgba(255,255,255,.7)">=</text>')
    return f'<svg class="glyph" viewBox="0 0 120 48" aria-hidden="true"><defs>{g}</defs>{body}</svg>'


def regimes(d: dict) -> str:
    items = [
        ("co", "Buffered together", "fee decides", d["p_co"], "p",
         "Pairs sent before the window that landed in its first slot: the higher fee came first."),
        ("spaced", "Sent 200 ms apart", "arrival decides", d["q_s"], "q",
         "Two requests in random order: the first-sent came first."),
        ("placebo", "Equal fees", "coin flip", d["p_e"], "p",
         "A randomly labelled pseudo-high transaction came first about half the time."),
    ]
    cards = []
    for i, (k, title, sub, st, name, note) in enumerate(items):
        if isinstance(st, dict) and st.get("n"):
            p, c = float(st["p"]), ci(st) or (float(st["p"]), float(st["p"]))
            kn = f"{st.get('k', '?')} of {st['n']} pairs"
            big = f'<span class="big mono" data-count="{p:.4f}" data-dec="2" style="min-width:4ch">{f2(p)}</span>'
            bar = (f'<div class="ibar" style="--lo:{100 * c[0]:.2f}%;--hi:{100 * c[1]:.2f}%;--v:{100 * p:.2f}%" '
                   f'role="img" aria-label="{name} = {f2(p)}, 95% interval {f2(c[0])} to {f2(c[1])}">'
                   f'<i class="half"></i><i class="seg"></i><i class="dot"></i></div>')
            ci_txt = f"95% interval {f2(c[0])} to {f2(c[1])}"
        else:
            big, bar, kn, ci_txt = '<span class="big mono">n/a</span>', '<div class="ibar"></div>', "no data", ""
        cards.append(f"""
    <article class="regime reveal" style="--i:{i}">
      {regime_glyph(k)}
      <h3>{esc(title)}<span class="sub">{esc(sub)}</span></h3>
      <div class="regime-num"><span class="name mono">{name} =</span>{big}</div>
      {bar}
      <div class="regime-meta mono"><span>{esc(kn)}</span><span>{esc(ci_txt)}</span></div>
      <p>{esc(note)}</p>
    </article>""")
    return f"""
<section class="regimes" aria-labelledby="h-regimes">
  <div class="sec-head">
    <p class="kicker reveal">Three regimes</p>
    <h2 id="h-regimes" class="reveal d1">The answer depends on when the two arrive</h2>
    <p class="lede reveal d2">Pooled over all validators, from <a href="{REPO_URL}/blob/main/results/secondary.json">results/secondary.json</a>. p is the share of pairs in which the higher fee came first; q the share in which the first-sent came first.</p>
  </div>
  <div class="regime-grid">{''.join(cards)}</div>
</section>
"""


def results(d: dict) -> str:
    min_n, (lo_b, hi_b) = d["min_n"], d["equiv"]
    first = d["first"]
    ghosts = first and first["differs"]
    rows = []
    for i, u in enumerate(d["units"]):
        fu = (first["units"].get(u["role"]) if ghosts else None) or {}

        def lane(kind: str, val, c, k, label: str, n: int, ghost):
            if val is None:
                return f'<div class="lane lane-{kind} empty"><span class="mono small">{label}: no data</span></div>'
            lo, hi = c if c else (val, val)
            tip = f"{label} = {f2(val)} [{f2(lo)}, {f2(hi)}]"
            if k is not None:
                tip += f", {k} of {n}"
            g = ""
            if ghost is not None:
                g = f'<i class="ghost" style="--g:{100 * ghost:.2f}%" title="first analysis: {label} = {f2(ghost)}"></i>'
            return (f'<div class="lane lane-{kind}" style="--lo:{100 * lo:.2f}%;--hi:{100 * hi:.2f}%;--v:{100 * val:.2f}%">'
                    f'{g}<span class="bar"></span>'
                    f'<button type="button" class="mark" data-tip="{esc(tip)}" aria-label="{esc(tip)}"></button></div>')

        def val_txt(label, v, c):
            if v is None:
                return f'<span class="v v-{label}"><b>{label}</b> n/a</span>'
            s = f'<span class="v v-{label}"><b>{label}</b> {f2(v)}'
            if c:
                s += f' <em>[{f2(c[0])}, {f2(c[1])}]</em>'
            return s + '</span>'

        rows.append(f"""
      <div class="row reveal" style="--i:{i}">
        <div class="who">
          <div class="role">{esc(u["role"])}</div>
          <div class="meta"><span>{esc(u["client"])} {esc(u["version"])}</span><span class="mono">N = {u["n"]}</span></div>
          {verdict_chip(u, min_n)}
        </div>
        <div class="track">
          {lane("p", u["p"], u["p_ci"], u["p_k"], "p", u["n"], fu.get("p"))}
          {lane("q", u["q"], u["q_ci"], u["q_k"], "q", u["n"], fu.get("q"))}
        </div>
        <div class="vals mono">{val_txt("p", u["p"], u["p_ci"])}{val_txt("q", u["q"], u["q_ci"])}</div>
      </div>""")

    table_rows = "".join(
        f"<tr><td>{esc(u['role'])}</td><td>{esc(u['client'])} {esc(u['version'])}</td><td class='mono'>{u['n']}</td>"
        f"<td class='mono'>{f2(u['p']) if u['p'] is not None else ''} "
        f"{'[' + f2(u['p_ci'][0]) + ', ' + f2(u['p_ci'][1]) + ']' if u['p_ci'] else ''}</td>"
        f"<td class='mono'>{f2(u['q']) if u['q'] is not None else ''} "
        f"{'[' + f2(u['q_ci'][0]) + ', ' + f2(u['q_ci'][1]) + ']' if u['q_ci'] else ''}</td>"
        f"<td>{esc(u['verdict'])}</td></tr>" for u in d["units"])

    v = d["verdicts"]
    bits = []
    if v.get("mode"):
        bits.append(f"Analysis: {v['mode']}")
    if v.get("holm_family_size"):
        bits.append(f"one Holm family of {v['holm_family_size']} tests")
    if d["cfg"].get("alpha") is not None:
        bits.append(f"family alpha {d['cfg']['alpha']:g}")
    note = "; ".join(bits)
    first_html = ""
    if first:
        link = f'<a href="{REPO_URL}/tree/main/results/{esc(first["name"])}">results/{esc(first["name"])}/</a>'
        if ghosts:
            first_html = (f' Hollow ticks mark the first analysis of {esc(first["date"])} '
                          f'({fmt_int(first["n_probes"] or 0)} pairs), kept unchanged in {link}.')
        else:
            first_html = f' The first analysis of {esc(first["date"])} is kept unchanged in {link}.'
    legend_first = '<span><i class="sw sw-ghost"></i>first analysis</span>' if ghosts else ""
    ticks = "".join(f'<span style="left:{t * 100:.0f}%">{t:g}</span>' for t in (0, 0.25, 0.5, 0.75, 1))
    n_units, n_clients = len(d["units"]), len(d["clients"])
    return f"""
<section class="results" id="results" aria-labelledby="h-results">
  <div class="sec-head">
    <p class="kicker reveal">Results by validator</p>
    <h2 id="h-results" class="reveal d1">{word(n_units).capitalize()} validators, {word(n_clients)} client types, one block at a time</h2>
    <p class="lede reveal d2">Dots are point estimates, bars are exact 95% intervals. The reference line is 0.5, the faint band is the preregistered "no rule" zone, {f2(lo_b)} to {f2(hi_b)}. Sorted by N. Hover a dot for the count.</p>
  </div>
  <div class="legend reveal d2" aria-hidden="true">
    <span><i class="sw sw-p"></i>p: higher fee first</span>
    <span><i class="sw sw-q"></i>q: first in request first</span>
    <span><i class="sw sw-band"></i>no-rule band</span>{legend_first}
  </div>
  <div class="chart">
    <div class="axis-row"><div class="who"></div><div class="axis mono">{ticks}</div><div class="vals"></div></div>
    {''.join(rows)}
  </div>
  <p class="foot reveal">{esc(note)}.{first_html} Verdict rules (N of at least {min_n}; strict, strong, partial, mixed, no rule) are fixed in <a href="{REPO_URL}/blob/main/docs/PREREGISTRATION.md">docs/PREREGISTRATION.md</a>. Source: <a href="{REPO_URL}/blob/main/results/verdicts.json">results/verdicts.json</a>.</p>
  <details class="tbl reveal">
    <summary>Show as table</summary>
    <div class="scroll"><table>
      <thead><tr><th>Validator</th><th>Client, version</th><th>N</th><th>p [95% CI]</th><th>q [95% CI]</th><th>Preregistered verdict</th></tr></thead>
      <tbody>{table_rows}</tbody>
    </table></div>
  </details>
</section>
"""


def delivery(d: dict) -> str:
    rows = d["by_role"]
    if not rows:
        return ""
    bars = "".join(f"""
    <div class="dbar reveal" style="--i:{i};--w:{100 * r['share']:.1f}%">
      <div class="dlabel"><span class="drole">{esc(r['role'])}</span><span class="dclient">{esc(r['client'])}</span></div>
      <div class="dtrack"><i></i></div>
      <div class="dval mono"><b>{pct(r['share'])}</b><span>{fmt_int(r['usable'])} / {fmt_int(r['probes'])}</span></div>
    </div>""" for i, r in enumerate(rows))
    return f"""
<section class="delivery" id="delivery" aria-labelledby="h-delivery">
  <div class="sec-head">
    <p class="kicker reveal">The delivery path</p>
    <h2 id="h-delivery" class="reveal d1">Where our pairs actually landed</h2>
    <p class="lede reveal d2">Share of probes whose pair landed together in the target's own leader window, {esc(d["by_role_note"])}. {esc(delivery_sentence(d))}</p>
  </div>
  <div class="dchart">{bars}</div>
  <p class="foot reveal">Landing itself was not the problem: {fmt_int(d["tx_landed"])} of {fmt_int(d["tx_sent"])} main-run transactions landed ({pct(d["landing"]) if d["landing"] is not None else "n/a"}), high and low fee alike. Source: <a href="{REPO_URL}/blob/main/results/runs.md">results/runs.md</a>.</p>
</section>
"""


def depth(d: dict) -> str:
    r = d["runs"]
    calib = d["calib"]
    items = [
        (fmt_int(r["all_tx_sent"]), "mainnet transactions sent", f"{fmt_int(r['all_probes'])} pairs in {r['n_runs_all']} runs, pilot included"),
        (str(len(d["units"])), "validators, one per client type", ", ".join(d["clients"])),
        (str(d["n_docs"]), "source-code research documents", "pinned commits of Agave, Jito, BAM, Harmonic, Firedancer"),
    ]
    if d["n_citations"]:
        items.append((fmt_int(d["n_citations"]), "code citations re-checked", "every quote re-read at its path and line, all PASS"))
    items.append((str(d["n_amend"]), "preregistration amendments", "each dated, each before the data it governs"))
    n_anchor = len(d["anchors"]) + r["run_anchors"]
    items.append((str(n_anchor), "on-chain anchors", f"{len(d['anchors'])} protocol memos, {r['run_anchors']} per-run memos; {d['n_manifest_files']} files hashed"))
    items.append((str(d["n_tests"]), "unit tests", "analysis, planning, wallet, spend cap, parsers"))
    if calib.get("arrival") and calib.get("priority"):
        a, p = calib["arrival"], calib["priority"]
        items.append((f"{a[0]}/{a[1]}", "localnet known answers, arrival", f"and {p[0]}/{p[1]} for priority order on Agave"))
    if d["n_snapshots"]:
        items.append((str(d["n_snapshots"]), "gossip snapshots", "client claims recorded at every run start and end"))
    spent_sol, cap_sol = d["spent"] / 1e9, d["cap"] / 1e9
    items.append((f"{spent_sol:.4f}", f"SOL spent of {cap_sol:.2f} cap", f"{pct(d['spent'] / d['cap'] if d['cap'] else 0)} of the hard cap, enforced in code before every send"))
    if d["verify"]:
        v = d["verify"]
        items.append((f"{v['k']}/{v['n']}", "random landed transactions re-verified", f"public RPC, result {v['result']}"))
    cells = "".join(f"""
    <div class="dcell reveal" style="--i:{i}">
      <span class="dnum mono">{esc(n)}</span>
      <span class="dlab">{esc(l)}</span>
      <span class="dcap">{esc(c)}</span>
    </div>""" for i, (n, l, c) in enumerate(items))
    return f"""
<section class="depth" id="depth" aria-labelledby="h-depth">
  <div class="sec-head">
    <p class="kicker reveal">Depth of the work</p>
    <h2 id="h-depth" class="reveal d1">Everything here is counted by the build script</h2>
    <p class="lede reveal d2">Nothing on this page is typed by hand. The numbers come from the result files, the documents and the code at build time.</p>
  </div>
  <div class="dgrid">{cells}</div>
</section>
"""


def method(d: dict) -> str:
    plan = d["plan"]
    try:
        ratio = f"{plan['price_high'] / plan['price_low']:,.0f}x"
    except (KeyError, TypeError, ZeroDivisionError):
        ratio = "far higher"
    tau = plan.get("tau0_ms")
    tau_s = f"about {abs(int(tau))} ms before" if isinstance(tau, (int, float)) else "just before"
    gap = plan.get("gap_ms", 200)
    cards = [
        ("01", "A conflicting pair",
         f"Two of our own transactions, from two payers, both writing one fresh shared account. The scheduler must put one before the other. The compute unit price differs {ratio}: {fmt_int(plan.get('price_high', 0))} vs {fmt_int(plan.get('price_low', 0))} micro-lamports per CU."),
        ("02", "Randomized fee and request position",
         f"Which transaction is high-fee and which goes first in the request are drawn independently. Sent as one JSON-RPC request {tau_s} the target's leader window; a separate arm sends two requests {gap} ms apart."),
        ("03", "Block producer read from the block",
         "A pair is usable only if both transactions sit in one block produced by the target, read from the block's Fee reward and never assumed from the schedule, inside the targeted window."),
        ("04", "Preregistered and anchored on mainnet",
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
      <summary><span class="acc-n mono">{i + 1:02d}</span><span>{esc(c["title"])}</span><i class="chev" aria-hidden="true"></i></summary>
      <p>{esc(c["text"])}</p>
    </details>""" for i, c in enumerate(d["considerations"]))
    n_cons = len(d["considerations"])
    return f"""
<section class="method" id="method" aria-labelledby="h-method">
  <div class="sec-head">
    <p class="kicker reveal">Method</p>
    <h2 id="h-method" class="reveal d1">One request, two transactions, one block</h2>
  </div>
  <div class="cards">{card_html}</div>
  <h3 class="sub reveal">The {word(n_cons)} considerations</h3>
  <p class="lede reveal d1">How the design handles each point of the bounty, shortened from <a href="{REPO_URL}/blob/main/docs/DESIGN.md">docs/DESIGN.md</a>.</p>
  <div class="accordion">{acc}</div>
</section>
"""


def timeline(d: dict) -> str:
    items = []
    for i, e in enumerate(d["timeline"]):
        when = e["when"] + (" UTC" if re.search(r"\d:\d", e["when"]) else "")
        link = ""
        if e["sig"]:
            short = e["sig"][:8] + "..." + e["sig"][-6:]
            slot = f'<span class="t-slot mono">slot {e["slot"]}</span>' if e["slot"] else ""
            link = (f'<a class="t-link mono" href="{EXPLORER}{esc(e["sig"])}" rel="noopener" title="{esc(e["sig"])}">'
                    f'<i class="dot-g"></i>{esc(short)} on Solscan</a>{slot}')
        items.append(f"""
    <li class="t-item reveal" style="--i:{i}">
      <span class="t-when mono">{esc(when)}</span>
      <div class="t-body">
        <div class="t-title">{esc(e["title"])}</div>
        {f'<div class="t-detail">{esc(e["detail"])}</div>' if e["detail"] else ''}
        {f'<div class="t-anchor">{link}</div>' if link else ''}
      </div>
    </li>""")
    return f"""
<section class="timeline" id="timeline" aria-labelledby="h-timeline">
  <div class="sec-head">
    <p class="kicker reveal">Timeline</p>
    <h2 id="h-timeline" class="reveal d1">Dated, in order, anchored</h2>
    <p class="lede reveal d2">Every anchor is a memo transaction on mainnet carrying the SHA-256 of a file in this repository. Compare it with <span class="mono">sha256sum</span> of the file at the named commit.</p>
  </div>
  <ol class="tline">{''.join(items)}</ol>
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
    spent, cap = d["spent"], d["cap"]
    ratio = spent / cap if cap else 0
    audit_ok = (d["audit"] or {}).get("RESULT")
    audit_line = f" Audit: {esc(audit_ok)}, every fee-paying transaction of our accounts is in the spend ledger." if audit_ok else ""
    vline = ""
    if d["verify"]:
        v = d["verify"]
        vline = (f'<p class="vsample reveal"><i class="dot-g"></i>Last sample: {v["k"]} of {v["n"]} random landed transactions {esc(v["result"])}, '
                 f'<a href="{REPO_URL}/blob/main/results/verify_sample.txt">results/verify_sample.txt</a>.</p>')
    return f"""
<section class="verify" id="verify" aria-labelledby="h-verify">
  <div class="sec-head">
    <p class="kicker reveal">Verify in 60 seconds</p>
    <h2 id="h-verify" class="reveal d1">Do not trust this page. Run it.</h2>
    <p class="lede reveal d2">Pick a random sample of our landed transactions, fetch the blocks from a public RPC and confirm the recorded positions and producers. No wallet, no key, nothing is sent.</p>
  </div>
  <div class="cmds">{cmd_html}</div>
  {vline}
  <div class="spend reveal">
    <div class="spend-head"><span>Spend</span><span class="mono">{fmt_int(spent)} of {fmt_int(cap)} lamports ({spent / 1e9:.4f} of {cap / 1e9:.2f} SOL)</span></div>
    <div class="meter" role="meter" aria-valuemin="0" aria-valuemax="{cap}" aria-valuenow="{spent}" aria-label="Fees settled against the hard cap"><span style="--w:{100 * ratio:.1f}%"></span></div>
    <p class="foot">The cap is enforced in code before every send; fees settle only for transactions that land.{audit_line}</p>
  </div>
</section>
"""


def limits(d: dict) -> str:
    items = "".join(f'<li class="reveal" style="--i:{i}"><span class="l-n mono">{i + 1:02d}</span><span>{esc(t)}</span></li>'
                    for i, t in enumerate(d["not_separated"]))
    return f"""
<section class="limits" id="limits" aria-labelledby="h-limits">
  <div class="sec-head">
    <p class="kicker reveal">Honest limits</p>
    <h2 id="h-limits" class="reveal d1">What we do not separate</h2>
  </div>
  <ul class="bullets">{items}</ul>
  <p class="foot reveal">The full list of problems, in order, is in <a href="{REPO_URL}/blob/main/REPORT.md#{esc(d["wrong_anchor"])}">What went wrong</a> in the report.</p>
</section>
"""


def footer(d: dict) -> str:
    return f"""
<footer class="site-foot">
  <span><a href="{REPO_URL}">github.com/recruitabx/Inside-The-Solana-Block</a></span>
  <span>MIT license</span>
  <span>Data: {esc(d["data_dates"])}, {d["runs"]["n_runs"]} runs</span>
  <span class="foot-note">Independent research for the Superteam Ukraine bounty</span>
</footer>
"""


# ----------------------------------------------------------------------------
# CSS and JS (no f-strings here, so braces are literal)
# ----------------------------------------------------------------------------

CSS = r"""
:root{
  --bg:#07070b; --bg-2:#0c0c14; --surface:rgba(255,255,255,.035); --surface-2:rgba(255,255,255,.06);
  --line:rgba(255,255,255,.09); --line-2:rgba(255,255,255,.16);
  --ink:#f3f4f8; --ink-2:#c3c7d3; --ink-3:#8b90a0;
  --magenta:#dc1fff; --violet:#9945FF; --mint:#14F195;
  --grad:linear-gradient(90deg,#dc1fff 0%,#9945FF 50%,#14F195 100%);
  --q:#cfd3dd; --band:rgba(255,255,255,.05);
  --radius:18px; --ease:cubic-bezier(.2,.7,.2,1);
  color-scheme:dark;
}
:root[data-theme="dark"]{color-scheme:dark}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark}}
*{box-sizing:border-box}
html{scroll-behavior:smooth;-webkit-text-size-adjust:100%;overflow-x:clip;background:var(--bg)}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;font-feature-settings:"cv11","ss01";-webkit-font-smoothing:antialiased;overflow-x:clip;min-height:100vh}
.mono{font-family:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-feature-settings:normal;font-variant-numeric:tabular-nums}
a{color:inherit;text-decoration:underline;text-decoration-color:var(--line-2);text-underline-offset:3px;transition:text-decoration-color .2s}
a:hover{text-decoration-color:var(--mint)}
:focus-visible{outline:2px solid var(--mint);outline-offset:3px;border-radius:4px}
main{max-width:1120px;margin:0 auto;padding:0 clamp(16px,4vw,40px);position:relative}
section,header.hero{padding:clamp(64px,9vw,120px) 0;position:relative}
section{border-top:1px solid var(--line)}
h1{font-family:"Inter Tight",Inter,system-ui,sans-serif;font-size:clamp(38px,5.4vw,72px);line-height:1.02;letter-spacing:-.035em;font-weight:600;margin:18px 0 22px;max-width:14ch;text-wrap:balance}
h2{font-family:"Inter Tight",Inter,system-ui,sans-serif;font-size:clamp(28px,3.8vw,46px);line-height:1.08;letter-spacing:-.03em;font-weight:600;margin:0 0 16px;text-wrap:balance;max-width:24ch}
h3{font-size:18px;font-weight:600;margin:0 0 8px;letter-spacing:-.01em}
h3.sub{margin-top:clamp(48px,7vw,80px);font-size:24px;letter-spacing:-.02em}
p{margin:0 0 12px}
.lede{color:var(--ink-2);max-width:66ch;font-size:17px;margin-bottom:34px;text-wrap:pretty}
.kicker{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--mint);margin:0 0 14px;display:flex;align-items:center;gap:10px}
.kicker::before{content:"";width:22px;height:1px;background:var(--grad)}
.sec-head{margin-bottom:clamp(24px,4vw,40px)}
.muted{color:var(--ink-3);font-weight:400}
.small{font-size:13px}
.foot{color:var(--ink-3);font-size:14px;max-width:74ch;margin-top:22px}
.grad-text{background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent;background-size:200% 100%;animation:shimmer 9s linear infinite}
@keyframes shimmer{0%{background-position:0 0}100%{background-position:200% 0}}
.dot-g{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--mint);box-shadow:0 0 10px rgba(20,241,149,.7);margin-right:8px;vertical-align:1px}

/* background */
.bg{position:fixed;inset:0;z-index:0;overflow:hidden;pointer-events:none;background:radial-gradient(1200px 700px at 70% -10%,rgba(153,69,255,.14),transparent 60%),var(--bg)}
.blob{position:absolute;border-radius:50%;will-change:transform;opacity:.55;mix-blend-mode:screen}
.b1{width:70vmax;height:70vmax;left:-20vmax;top:-30vmax;background:radial-gradient(circle at 50% 50%,rgba(153,69,255,.55),rgba(153,69,255,0) 62%);animation:drift1 38s ease-in-out infinite alternate}
.b2{width:60vmax;height:60vmax;right:-25vmax;top:10vh;background:radial-gradient(circle at 50% 50%,rgba(20,241,149,.32),rgba(20,241,149,0) 62%);animation:drift2 46s ease-in-out infinite alternate}
.b3{width:55vmax;height:55vmax;left:20vw;bottom:-35vmax;background:radial-gradient(circle at 50% 50%,rgba(220,31,255,.3),rgba(220,31,255,0) 62%);animation:drift3 52s ease-in-out infinite alternate}
@keyframes drift1{from{transform:translate(0,0) scale(1)}to{transform:translate(12vw,10vh) scale(1.15)}}
@keyframes drift2{from{transform:translate(0,0) scale(1)}to{transform:translate(-14vw,16vh) scale(.9)}}
@keyframes drift3{from{transform:translate(0,0) scale(1)}to{transform:translate(-10vw,-14vh) scale(1.1)}}
.arcs{position:absolute;left:50%;top:-12vh;width:160vmax;height:160vmax;transform:translateX(-50%);opacity:.6;filter:blur(26px);animation:spin 90s linear infinite}
.arcs path{fill:none;stroke-width:3;stroke-linecap:round}
@keyframes spin{to{transform:translateX(-50%) rotate(360deg)}}
.grain{position:absolute;inset:0;background-image:radial-gradient(rgba(255,255,255,.035) .6px,transparent .6px);background-size:3px 3px;opacity:.5}

/* nav */
.nav{position:sticky;top:0;z-index:20;padding:14px clamp(16px,4vw,40px);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);background:rgba(7,7,11,.55);border-bottom:1px solid var(--line)}
.nav-in{max-width:1120px;margin:0 auto;display:flex;justify-content:space-between;align-items:center;gap:16px}
.brand{font-weight:600;text-decoration:none;letter-spacing:-.01em;display:inline-flex;align-items:center;gap:10px;font-size:15px}
.brand-dot{width:10px;height:10px;border-radius:3px;background:var(--grad);box-shadow:0 0 14px rgba(153,69,255,.6);display:inline-block}
.nav-links{display:flex;gap:4px;font-size:14px}
.nav-links a{text-decoration:none;color:var(--ink-2);padding:6px 11px;border-radius:999px;transition:background .2s,color .2s}
.nav-links a:hover{background:var(--surface-2);color:var(--ink)}
.nav-gh{border:1px solid var(--line-2)}

/* hero */
.hero{padding-top:clamp(48px,7vw,88px)}
.hero-grid{display:grid;grid-template-columns:minmax(0,1.05fr) minmax(0,.95fr);gap:clamp(24px,5vw,64px);align-items:center}
.eyebrow{display:flex;flex-wrap:wrap;align-items:center;gap:10px 14px;margin:0;font-size:13px;color:var(--ink-3)}
.pill{display:inline-flex;align-items:center;gap:8px;padding:5px 12px;border-radius:999px;border:1px solid var(--line-2);background:var(--surface);color:var(--ink-2);font-weight:500}
.pill::before{content:"";width:6px;height:6px;border-radius:50%;background:var(--mint);box-shadow:0 0 10px var(--mint)}
.answer{font-size:clamp(16px,1.5vw,19px);line-height:1.6;color:var(--ink-2);max-width:58ch;text-wrap:pretty}
.cta{display:flex;flex-wrap:wrap;gap:12px;margin:30px 0 0}
.btn{display:inline-flex;align-items:center;gap:8px;padding:13px 22px;border-radius:999px;font-weight:600;font-size:15px;text-decoration:none;border:1px solid var(--line-2);transition:transform .25s var(--ease),background .2s,border-color .2s,box-shadow .25s;position:relative}
.btn:hover{transform:translateY(-1px)}
.btn-primary{background:#fff;color:#07070b;border-color:#fff}
.btn-primary:hover{box-shadow:0 0 0 1px rgba(255,255,255,.3),0 10px 34px rgba(153,69,255,.45)}
.btn-ghost{background:var(--surface);color:var(--ink)}
.btn-ghost:hover{border-color:rgba(255,255,255,.4);background:var(--surface-2)}
.hero-visual{margin:0;position:relative;width:100%;justify-self:stretch;border:1px solid var(--line);border-radius:24px;background:linear-gradient(180deg,rgba(255,255,255,.04),rgba(255,255,255,.015));box-shadow:0 30px 80px rgba(0,0,0,.45),inset 0 1px 0 rgba(255,255,255,.06);overflow:hidden;aspect-ratio:10/7}
.hero-visual::before{content:"";position:absolute;inset:-1px;border-radius:inherit;padding:1px;background:linear-gradient(135deg,rgba(220,31,255,.5),rgba(153,69,255,.15) 40%,rgba(20,241,149,.45));-webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;mask-composite:exclude;pointer-events:none;opacity:.8}
.hero-visual canvas{position:absolute;inset:0;width:100%;height:100%;display:block}
.hero-visual figcaption{position:absolute;left:18px;bottom:14px;font-size:11px;color:var(--ink-3);letter-spacing:.04em}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:clamp(14px,2.5vw,28px);margin-top:clamp(44px,6vw,72px);padding-top:30px;border-top:1px solid var(--line)}
.metric{display:grid;gap:8px;justify-items:start}
.metric .num{font-size:clamp(30px,3.6vw,46px);font-weight:500;letter-spacing:-.03em;line-height:1;display:inline-block}
.metric .ul{display:block;height:2px;width:0;background:var(--grad);border-radius:2px;transition:width 1.4s var(--ease) .3s}
.in .metric .ul,.metric.in .ul{width:56px}
.metric .lbl{color:var(--ink-3);font-size:13px;line-height:1.4}

/* reveal */
.reveal{opacity:0;transform:translateY(16px);transition:opacity .8s var(--ease),transform .8s var(--ease);transition-delay:calc(var(--i,0)*70ms)}
.reveal.d1{transition-delay:90ms}.reveal.d2{transition-delay:180ms}.reveal.d3{transition-delay:270ms}.reveal.d4{transition-delay:380ms}
.reveal.in{opacity:1;transform:none}

/* glass cards */
.glass,.regime,.card,.dcell,.cmd pre,.acc,.hero-visual{position:relative}
.regime,.card,.dcell{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);transition:border-color .35s,transform .35s var(--ease),box-shadow .35s;box-shadow:inset 0 1px 0 rgba(255,255,255,.05)}
.regime::after,.card::after,.dcell::after{content:"";position:absolute;inset:-1px;border-radius:inherit;padding:1px;background:var(--grad);-webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;mask-composite:exclude;opacity:0;transition:opacity .35s;pointer-events:none}
.regime:hover,.card:hover,.dcell:hover{transform:translateY(-3px);box-shadow:0 18px 50px rgba(0,0,0,.4),0 0 40px rgba(153,69,255,.12)}
.regime:hover::after,.card:hover::after,.dcell:hover::after{opacity:.75}

/* regimes */
.regime-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.regime{padding:24px 24px 20px;display:grid;gap:10px;align-content:start}
.regime .glyph{width:120px;height:48px;display:block;margin-bottom:4px}
.regime h3{font-size:19px;display:grid;gap:2px}
.regime h3 .sub{font-size:13px;font-weight:500;color:var(--ink-3);letter-spacing:.01em}
.regime-num{display:flex;align-items:baseline;gap:10px;margin-top:6px}
.regime-num .name{color:var(--ink-3);font-size:14px}
.regime .big{font-size:clamp(40px,4.5vw,56px);font-weight:500;letter-spacing:-.03em;line-height:1;display:inline-block}
.ibar{position:relative;height:22px;margin:6px 0 2px}
.ibar::before{content:"";position:absolute;left:0;right:0;top:50%;height:1px;background:var(--line-2)}
.ibar .half{position:absolute;left:50%;top:4px;bottom:4px;width:1px;background:rgba(255,255,255,.3)}
.ibar .seg{position:absolute;top:50%;height:4px;margin-top:-2px;border-radius:3px;left:var(--v);width:0;background:var(--grad);transition:left 1s var(--ease) .2s,width 1s var(--ease) .2s;opacity:.9}
.ibar .dot{position:absolute;top:50%;left:var(--v);width:12px;height:12px;margin:-6px 0 0 -6px;border-radius:50%;background:#fff;box-shadow:0 0 0 3px rgba(7,7,11,.9),0 0 18px rgba(20,241,149,.8);transform:scale(0);transition:transform .6s var(--ease) .5s}
.in .ibar .seg,.ibar.in .seg{left:var(--lo);width:calc(var(--hi) - var(--lo))}
.in .ibar .dot,.ibar.in .dot{transform:scale(1)}
.regime-meta{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;font-size:12px;color:var(--ink-3)}
.regime p{color:var(--ink-2);font-size:14px;margin:6px 0 0;line-height:1.5}

/* results */
.legend{display:flex;flex-wrap:wrap;gap:18px;font-size:13px;color:var(--ink-2);margin-bottom:18px}
.legend span{display:inline-flex;align-items:center;gap:8px}
.sw{width:12px;height:12px;border-radius:50%;display:inline-block}
.sw-p{background:var(--grad);box-shadow:0 0 10px rgba(153,69,255,.8)}
.sw-q{background:transparent;border:2.5px solid var(--q)}
.sw-band{border-radius:3px;background:var(--band);border:1px solid var(--line-2)}
.sw-ghost{width:3px;height:12px;border-radius:1px;background:rgba(255,255,255,.55)}
.chart{display:grid;gap:4px}
.axis-row,.row{display:grid;grid-template-columns:minmax(190px,250px) 1fr minmax(150px,190px);gap:clamp(12px,3vw,32px);align-items:center}
.axis{position:relative;height:18px;font-size:11px;color:var(--ink-3)}
.axis span{position:absolute;transform:translateX(-50%)}
.axis span:first-child{transform:none}
.axis span:last-child{transform:translateX(-100%)}
.row{padding:16px 10px;margin:0 -10px;border-top:1px solid var(--line);border-radius:12px;transition:background .3s}
.row:hover{background:var(--surface)}
.row:last-child{border-bottom:1px solid var(--line)}
.who .role{font-weight:600;letter-spacing:-.01em;font-size:16px}
.who .meta{display:flex;flex-wrap:wrap;gap:4px 12px;color:var(--ink-3);font-size:13px;margin:2px 0 8px}
.chip{display:inline-flex;align-items:center;gap:6px;font-size:12px;padding:3px 10px;border-radius:999px;line-height:1.5;max-width:100%}
.chip-soft{background:var(--band);color:var(--ink-2);border:1px solid var(--line)}
.chip-verdict{background:rgba(153,69,255,.16);color:#e7dcff;border:1px solid rgba(153,69,255,.5);font-weight:500}
.vdetail{font-size:12.5px;color:var(--ink-3);margin-top:6px;line-height:1.4;max-width:30ch}
.track{position:relative;display:grid;gap:12px;padding:12px 0}
.track::before{content:"";position:absolute;top:0;bottom:0;left:35%;width:30%;background:var(--band);border-radius:6px}
.track::after{content:"";position:absolute;top:-4px;bottom:-4px;left:50%;width:1px;background:rgba(255,255,255,.22)}
.lane{position:relative;height:16px}
.lane .bar{position:absolute;top:50%;height:4px;margin-top:-2px;border-radius:3px;left:var(--v);width:0;transition:left .9s var(--ease),width .9s var(--ease);transition-delay:calc(var(--i,0)*70ms + 150ms)}
.lane-p .bar{background:var(--grad);opacity:.85}
.lane-q .bar{background:var(--q);opacity:.4}
.lane .mark{position:absolute;top:50%;left:var(--v);width:14px;height:14px;margin:-7px 0 0 -7px;border-radius:50%;padding:0;cursor:default;transform:scale(0);transition:transform .6s var(--ease);transition-delay:calc(var(--i,0)*70ms + 100ms);border:0;z-index:2}
.lane .mark::before{content:"";position:absolute;inset:-8px}
.lane-p .mark{background:#fff;box-shadow:0 0 0 3px rgba(7,7,11,.95),0 0 16px rgba(153,69,255,.9),0 0 30px rgba(20,241,149,.5)}
.lane-q .mark{background:var(--bg);border:3px solid var(--q);box-shadow:0 0 0 2px rgba(7,7,11,.95)}
.lane .ghost{position:absolute;top:1px;bottom:1px;left:var(--g);width:3px;margin-left:-1.5px;background:rgba(255,255,255,.5);border-radius:1px;z-index:1}
.row.in .bar{left:var(--lo);width:calc(var(--hi) - var(--lo))}
.row.in .mark{transform:scale(1)}
.mark[data-tip]::after{content:attr(data-tip);position:absolute;left:50%;bottom:calc(100% + 10px);transform:translate(-50%,4px);background:#fff;color:#07070b;font:12px/1.3 "JetBrains Mono",ui-monospace,monospace;padding:6px 9px;border-radius:7px;white-space:nowrap;opacity:0;visibility:hidden;pointer-events:none;transition:opacity .2s,transform .2s,visibility .2s;z-index:5}
.mark:hover::after,.mark:focus-visible::after{opacity:1;visibility:visible;transform:translate(-50%,0)}
.lane.empty{display:flex;align-items:center;color:var(--ink-3)}
.vals{display:grid;gap:6px;font-size:13px;color:var(--ink-2)}
.vals .v{display:flex;gap:8px;align-items:baseline;white-space:nowrap}
.vals b{font-weight:500;color:var(--ink-3);width:1ch}
.vals em{font-style:normal;color:var(--ink-3);font-size:12px}
.tbl{margin-top:20px}
.tbl summary{cursor:pointer;color:var(--ink-2);font-size:14px;width:max-content}
.scroll{overflow-x:auto;margin-top:12px}
table{border-collapse:collapse;width:100%;font-size:13px;min-width:640px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--ink-3);font-weight:500}

/* delivery */
.dchart{display:grid;gap:10px}
.dbar{display:grid;grid-template-columns:minmax(170px,230px) 1fr minmax(110px,150px);gap:clamp(10px,3vw,28px);align-items:center;padding:8px 0}
.dlabel{display:grid;gap:1px}
.drole{font-weight:600;font-size:15px}
.dclient{color:var(--ink-3);font-size:12.5px}
.dtrack{height:10px;border-radius:999px;background:var(--surface-2);overflow:hidden;position:relative}
.dtrack i{display:block;height:100%;width:0;border-radius:999px;background:var(--grad);background-size:var(--track,100%) 100%;transition:width 1.1s var(--ease);transition-delay:calc(var(--i,0)*60ms + 120ms);box-shadow:0 0 16px rgba(20,241,149,.35)}
.dbar.in .dtrack i{width:var(--w)}
.dval{display:grid;justify-items:end;line-height:1.2}
.dval b{font-weight:500;font-size:16px}
.dval span{color:var(--ink-3);font-size:12px}

/* depth */
.dgrid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
.dcell{padding:22px 20px 18px;display:grid;gap:8px;align-content:start;min-height:150px}
.dnum{font-size:clamp(32px,3.4vw,44px);font-weight:500;letter-spacing:-.03em;line-height:1;position:relative;padding-bottom:12px}
.dnum::after{content:"";position:absolute;left:0;bottom:0;width:36px;height:2px;background:var(--grad);border-radius:2px}
.dlab{font-weight:600;font-size:14px;letter-spacing:-.01em}
.dcap{color:var(--ink-3);font-size:12.5px;line-height:1.45}

/* method */
.cards{display:grid;grid-template-columns:repeat(2,1fr);gap:14px;margin-top:8px}
.card{padding:24px 24px 20px}
.card .idx{color:var(--mint);font-size:12px;display:block;margin-bottom:14px;letter-spacing:.1em}
.card h3{font-size:19px}
.card p{color:var(--ink-2);font-size:15px;margin:0}
.accordion{border-top:1px solid var(--line)}
.acc{border-bottom:1px solid var(--line)}
.acc summary{list-style:none;display:flex;align-items:center;gap:16px;padding:18px 0;cursor:pointer;font-weight:500;font-size:16px}
.acc summary::-webkit-details-marker{display:none}
.acc-n{color:var(--ink-3);font-size:12px;width:2.5ch}
.chev{width:9px;height:9px;border-right:1.5px solid var(--ink-3);border-bottom:1.5px solid var(--ink-3);transform:rotate(45deg);transition:transform .3s var(--ease);flex:none;margin:0 6px 0 auto}
.acc[open] .chev{transform:rotate(-135deg)}
.acc[open] summary{color:var(--mint)}
.acc p{color:var(--ink-2);font-size:15px;max-width:72ch;padding:0 0 20px 0;margin:0 0 0 calc(2.5ch + 16px)}

/* timeline */
.tline{list-style:none;margin:0;padding:0 0 0 20px;position:relative;display:grid;gap:4px}
.tline::before{content:"";position:absolute;left:0;top:8px;bottom:8px;width:2px;background:linear-gradient(180deg,#dc1fff,#9945FF,#14F195);border-radius:2px;opacity:.8}
.t-item{position:relative;display:grid;grid-template-columns:minmax(150px,200px) 1fr;gap:clamp(10px,3vw,28px);padding:16px 0 16px 20px}
.t-item::before{content:"";position:absolute;left:-25px;top:24px;width:12px;height:12px;border-radius:50%;background:var(--bg);border:2px solid #fff;box-shadow:0 0 14px rgba(153,69,255,.8)}
.t-when{font-size:13px;color:var(--ink-3);padding-top:2px}
.t-title{font-weight:600;font-size:16px;letter-spacing:-.01em}
.t-detail{color:var(--ink-2);font-size:14px;margin-top:4px;max-width:70ch}
.t-anchor{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;margin-top:10px;font-size:12.5px}
.t-link{display:inline-flex;align-items:center;padding:6px 12px;border:1px solid var(--line-2);border-radius:999px;text-decoration:none;background:var(--surface);transition:border-color .25s,background .25s}
.t-link:hover{border-color:var(--mint);background:var(--surface-2)}
.t-slot{color:var(--ink-3)}

/* verify */
.cmds{display:grid;gap:14px}
.cmd-label{font-size:13px;color:var(--ink-3);margin-bottom:6px}
pre{position:relative;margin:0;background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:16px 92px 16px 18px;font-size:13.5px;line-height:1.6;overflow-x:auto;white-space:pre-wrap;word-break:break-word;backdrop-filter:blur(10px)}
pre code{color:#e9fbf2}
.copy{position:absolute;top:10px;right:10px;font:600 12px Inter,system-ui,sans-serif;color:var(--ink);background:var(--surface-2);border:1px solid var(--line-2);border-radius:999px;padding:5px 12px;cursor:pointer;transition:background .2s,color .2s,border-color .2s}
.copy:hover{border-color:rgba(255,255,255,.45)}
.copy.done{color:#07070b;background:var(--mint);border-color:var(--mint)}
.vsample{margin:22px 0 0;color:var(--ink-2);font-size:14px}
.spend{margin-top:clamp(32px,5vw,48px)}
.spend-head{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;font-size:14px;margin-bottom:8px}
.meter{height:8px;background:var(--surface-2);border:1px solid var(--line);border-radius:999px;overflow:hidden}
.meter span{display:block;height:100%;width:0;background:var(--grad);border-radius:999px;transition:width 1.4s var(--ease) .2s;box-shadow:0 0 14px rgba(20,241,149,.5)}
.spend.in .meter span{width:var(--w)}
.spend .foot{margin-top:10px}

/* limits */
.bullets{margin:0;padding:0;list-style:none;display:grid;gap:4px;max-width:78ch}
.bullets li{display:grid;grid-template-columns:3ch 1fr;gap:14px;color:var(--ink-2);padding:14px 0;border-top:1px solid var(--line);font-size:15.5px}
.bullets li:last-child{border-bottom:1px solid var(--line)}
.l-n{color:var(--ink-3);font-size:12px;padding-top:4px}

.site-foot{display:flex;flex-wrap:wrap;gap:10px 28px;padding:32px 0 56px;border-top:1px solid var(--line);color:var(--ink-3);font-size:13px}
.foot-note{margin-left:auto}

@media (max-width:980px){
  .hero-grid{grid-template-columns:1fr}
  .hero-visual{max-width:620px}
  h1{max-width:16ch}
  .dgrid{grid-template-columns:repeat(3,1fr)}
  .axis-row,.row{grid-template-columns:minmax(170px,220px) 1fr}
  .axis-row .vals{display:none}
  .row .vals{grid-column:2;display:flex;gap:16px;padding-top:0}
}
@media (max-width:760px){
  .nav-links a:not(.nav-gh){display:none}
  .metrics{grid-template-columns:repeat(2,1fr)}
  .cards{grid-template-columns:1fr}
  .regime-grid{grid-template-columns:1fr}
  .dgrid{grid-template-columns:repeat(2,1fr)}
  .axis-row,.row{grid-template-columns:1fr;gap:6px}
  .axis-row .who{display:none}
  .row .vals{grid-column:1}
  .track{padding:14px 0 12px}
  .mark[data-tip]::after{white-space:normal;width:max-content;max-width:220px}
  .dbar{grid-template-columns:1fr auto;grid-template-areas:"label val" "track track"}
  .dlabel{grid-area:label}.dtrack{grid-area:track}.dval{grid-area:val}
  .t-item{grid-template-columns:1fr;gap:4px}
  .foot-note{margin-left:0}
  .hero-visual{aspect-ratio:4/3}
  .arcs{filter:blur(14px);opacity:.45}
  .b3{display:none}
}
@media (max-width:420px){
  pre{padding-right:18px;padding-bottom:44px}
  .copy{top:auto;bottom:8px}
  .dgrid{grid-template-columns:1fr 1fr;gap:10px}
  .dcell{padding:16px 14px 14px;min-height:0}
  .metric .num{font-size:28px}
}
@media (prefers-reduced-motion:reduce){
  html{scroll-behavior:auto}
  .reveal{opacity:1;transform:none;transition:none}
  .lane .bar,.lane .mark,.meter span,.btn,.regime,.chev,.ibar .seg,.ibar .dot,.dtrack i,.metric .ul{transition:none}
  .blob,.arcs,.grad-text{animation:none}
  .ibar .seg{left:var(--lo);width:calc(var(--hi) - var(--lo))}
  .ibar .dot{transform:scale(1)}
  .dtrack i{width:var(--w)}
  .metric .ul{width:56px}
}
"""

JS = r"""
(function(){
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  function fmtNum(v, dec){
    var s = v.toFixed(dec), parts = s.split('.');
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    return parts.join('.');
  }
  function countUp(el){
    if (el.getAttribute('data-done')) return; el.setAttribute('data-done', '1');
    var target = parseFloat(el.getAttribute('data-count')), dec = parseInt(el.getAttribute('data-dec') || '0', 10);
    var suffix = el.getAttribute('data-suffix') || '', final = el.textContent;
    if (reduce || isNaN(target)) return;
    var t0 = null, dur = 1500;
    function step(now){
      if (t0 === null) t0 = now;
      var p = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - p, 3);
      el.textContent = (p < 1) ? fmtNum(target * e, dec) + suffix : final;
      if (p < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }
  // scroll reveals
  var els = document.querySelectorAll('.reveal,.spend,.metrics,.dbar');
  function enter(el){
    el.classList.add('in');
    el.querySelectorAll('[data-count]').forEach(countUp);
    if (el.hasAttribute('data-count')) countUp(el);
  }
  if (!reduce && 'IntersectionObserver' in window) {
    var io = new IntersectionObserver(function(entries){
      entries.forEach(function(e){ if (e.isIntersecting || e.boundingClientRect.bottom < 0) { enter(e.target); io.unobserve(e.target); } });
    }, {rootMargin:'0px 0px -8% 0px', threshold:0.08});
    els.forEach(function(el){ io.observe(el); });
    var pending = Array.prototype.slice.call(els), ticking = false;
    window.addEventListener('scroll', function(){
      if (ticking || !pending.length) return; ticking = true;
      requestAnimationFrame(function(){
        pending = pending.filter(function(el){ if (el.getBoundingClientRect().bottom < 0) { enter(el); return false; } return !el.classList.contains('in'); });
        ticking = false;
      });
    }, {passive:true});
  } else {
    els.forEach(function(el){ el.classList.add('in'); });
  }

  // hero block canvas
  var cv = document.getElementById('blk');
  if (cv && cv.getContext) {
    var ctx = cv.getContext('2d');
    var COLS = 26, ROWS = 11, N = COLS * ROWS, PERIOD = 8.2;
    var seed = 20261031;
    function rnd(){ seed = (seed * 48271) % 2147483647; return seed / 2147483647; }
    var cells = [];
    for (var i = 0; i < N; i++) { var r = Math.floor(i / COLS), c = i % COLS; cells.push({d: c * 0.05 + r * 0.07 + rnd() * 0.5, a: 0.18 + rnd() * 0.3, t: rnd()}); }
    var HI = {r: 5, c: 11}, LO = {r: 5, c: 12};
    var W = 0, H = 0, cs = 10, gap = 3, ox = 0, oy = 0, dpr = 1;
    function size(){
      var rect = cv.getBoundingClientRect(); if (!rect.width) return;
      dpr = Math.min(2, window.devicePixelRatio || 1); W = rect.width; H = rect.height;
      cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      var pad = 44;
      cs = Math.floor(Math.min((W - pad * 2) / COLS, (H - pad * 2 - 20) / ROWS));
      gap = Math.max(2, Math.round(cs * 0.3));
      ox = Math.round((W - COLS * cs) / 2); oy = Math.round((H - ROWS * cs) / 2) + 10;
    }
    function clamp(t){ return t < 0 ? 0 : t > 1 ? 1 : t; }
    function easeOut(t){ return 1 - Math.pow(1 - t, 3); }
    function back(t){ var c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2); }
    function rr(x, y, w, h, r){ ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath(); }
    function cellXY(rc){ return [ox + rc.c * cs + gap / 2, oy + rc.r * cs + gap / 2]; }
    function draw(t){
      ctx.clearRect(0, 0, W, H);
      var fade = t > PERIOD - 0.9 ? clamp((PERIOD - t) / 0.9) : 1;
      var fin = clamp(t / 0.7) * fade;
      var fx = ox - 16, fy = oy - 16, fw = COLS * cs + 32, fh = ROWS * cs + 32;
      rr(fx, fy, fw, fh, 14); ctx.strokeStyle = 'rgba(255,255,255,' + (0.16 * fin) + ')'; ctx.lineWidth = 1; ctx.stroke();
      ctx.fillStyle = 'rgba(255,255,255,' + (0.45 * fin) + ')'; ctx.font = '500 11px "JetBrains Mono", ui-monospace, monospace';
      ctx.textAlign = 'left'; ctx.fillText('block', fx + 2, fy - 9);
      ctx.textAlign = 'right'; ctx.fillText(N + ' tx', fx + fw - 2, fy - 9);
      var s = cs - gap;
      for (var i = 0; i < N; i++) {
        var r = Math.floor(i / COLS), c = i % COLS;
        if ((r === HI.r && c === HI.c) || (r === LO.r && c === LO.c)) continue;
        var k = easeOut(clamp((t - 0.25 - cells[i].d) / 0.55)) * fade;
        if (k <= 0) continue;
        var sz = s * (0.4 + 0.6 * k), x = ox + c * cs + cs / 2 - sz / 2, y = oy + r * cs + cs / 2 - sz / 2;
        var tint = cells[i].t < 0.08 ? 'rgba(153,69,255,' + (cells[i].a * 1.6 * k) + ')' : 'rgba(255,255,255,' + (cells[i].a * k) + ')';
        ctx.fillStyle = tint; rr(x, y, sz, sz, Math.max(2, sz * 0.22)); ctx.fill();
      }
      function drop(rc, t0, hi){
        var p = clamp((t - t0) / 1.0);
        if (p <= 0) return;
        var xy = cellXY(rc), x = xy[0], yEnd = xy[1], yStart = fy - 70;
        var y = yStart + (yEnd - yStart) * back(p);
        var a = Math.min(1, p * 3) * fade;
        var pulse = 1 + 0.06 * Math.sin((t - t0) * 3.2);
        var sz = s * (p < 1 ? 1.15 : pulse), cx = x + s / 2, cy = y + s / 2;
        ctx.save(); ctx.globalAlpha = a;
        if (hi) {
          var g = ctx.createLinearGradient(cx - sz, cy, cx + sz, cy); g.addColorStop(0, '#9945FF'); g.addColorStop(1, '#14F195');
          ctx.shadowColor = 'rgba(153,69,255,.95)'; ctx.shadowBlur = 22; ctx.fillStyle = g;
        } else {
          ctx.shadowColor = 'rgba(255,255,255,.7)'; ctx.shadowBlur = 14; ctx.fillStyle = '#ffffff';
        }
        rr(cx - sz / 2, cy - sz / 2, sz, sz, Math.max(2, sz * 0.24)); ctx.fill();
        ctx.restore();
        // ring after landing
        var rp = clamp((t - t0 - 1.0) / 0.9);
        if (rp > 0 && rp < 1) { ctx.beginPath(); ctx.arc(cx, cy, s * 0.7 + rp * s * 2.2, 0, Math.PI * 2); ctx.strokeStyle = (hi ? 'rgba(153,69,255,' : 'rgba(255,255,255,') + (0.6 * (1 - rp) * fade) + ')'; ctx.lineWidth = 1.5; ctx.stroke(); }
        // label
        var lp = clamp((t - t0 - 0.9) / 0.5) * fade;
        if (lp > 0) {
          ctx.save(); ctx.globalAlpha = lp; ctx.font = '500 11px "JetBrains Mono", ui-monospace, monospace'; ctx.textAlign = 'center';
          var ly = hi ? cy - s - 14 : cy + s + 20, ty = hi ? cy - s / 2 - 4 : cy + s / 2 + 4;
          ctx.strokeStyle = 'rgba(255,255,255,.35)'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(cx, ty); ctx.lineTo(cx, hi ? ly + 6 : ly - 12); ctx.stroke();
          var label = hi ? 'high fee' : 'low fee', tw = ctx.measureText(label).width + 14;
          ctx.fillStyle = 'rgba(7,7,11,.92)'; rr(cx - tw / 2, ly - 12, tw, 17, 6); ctx.fill();
          ctx.strokeStyle = hi ? 'rgba(20,241,149,.5)' : 'rgba(255,255,255,.3)'; ctx.stroke();
          ctx.fillStyle = hi ? '#c9f7e4' : 'rgba(255,255,255,.85)'; ctx.fillText(label, cx, ly);
          ctx.restore();
        }
      }
      drop(HI, 2.1, true); drop(LO, 2.45, false);
      // order caption
      var cp = clamp((t - 3.9) / 0.6) * fade;
      if (cp > 0) { ctx.save(); ctx.globalAlpha = cp; ctx.font = '500 11px "JetBrains Mono", ui-monospace, monospace'; ctx.textAlign = 'right'; ctx.fillStyle = 'rgba(255,255,255,.55)'; ctx.fillText('index ' + (HI.r * COLS + HI.c) + ' before ' + (LO.r * COLS + LO.c), fx + fw - 2, fy + fh + 18); ctx.restore(); }
    }
    var running = false, start = null, raf = 0;
    function loop(now){ if (!running) return; if (start === null) start = now; draw(((now - start) / 1000) % PERIOD); raf = requestAnimationFrame(loop); }
    function play(){ if (running || reduce) return; running = true; start = null; raf = requestAnimationFrame(loop); }
    function stop(){ running = false; cancelAnimationFrame(raf); }
    size();
    if (reduce) { draw(4.6); }
    else {
      if ('IntersectionObserver' in window) {
        new IntersectionObserver(function(entries){ entries.forEach(function(e){ if (e.isIntersecting) play(); else stop(); }); }, {threshold:0.05}).observe(cv);
      } else { play(); }
      document.addEventListener('visibilitychange', function(){ if (document.hidden) stop(); else play(); });
    }
    var rto = 0;
    window.addEventListener('resize', function(){ clearTimeout(rto); rto = setTimeout(function(){ size(); if (reduce) draw(4.6); }, 120); }, {passive:true});
    if ('ResizeObserver' in window) { new ResizeObserver(function(){ size(); if (reduce) draw(4.6); }).observe(cv.parentNode); }
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

ARCS_SVG = """<svg class="arcs" viewBox="0 0 1000 1000" aria-hidden="true" focusable="false">
<defs><linearGradient id="arcg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#dc1fff"/><stop offset=".5" stop-color="#9945FF"/><stop offset="1" stop-color="#14F195"/></linearGradient></defs>
<path d="M120 520 C 250 180, 700 160, 900 420" stroke="url(#arcg)" opacity=".55"/>
<path d="M80 640 C 300 300, 760 330, 940 560" stroke="url(#arcg)" opacity=".3"/>
</svg>"""


# ----------------------------------------------------------------------------
# assemble
# ----------------------------------------------------------------------------

def build() -> str:
    d = load_all()
    n_units = len(d["units"])
    desc = (f"{word(n_units).capitalize()} Solana mainnet validators, one per client, measured with randomized conflicting "
            "transaction pairs: does the higher fee or the request position decide the order in the block?")
    body = (hero(d) + regimes(d) + results(d) + delivery(d) + depth(d) + method(d)
            + timeline(d) + verify(d) + limits(d) + footer(d))
    page = f"""<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Inside the Solana Block</title>
<meta name="description" content="{esc(desc)}">
<meta name="color-scheme" content="dark">
<meta name="theme-color" content="#07070b">
<meta property="og:title" content="Inside the Solana Block">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{PAGES_URL}">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Cdefs%3E%3ClinearGradient id='g' x1='0' x2='1'%3E%3Cstop offset='0' stop-color='%239945FF'/%3E%3Cstop offset='1' stop-color='%2314F195'/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect width='32' height='32' rx='8' fill='%2307070b'/%3E%3Crect x='6' y='11' width='9' height='9' rx='2' fill='url(%23g)'/%3E%3Crect x='17' y='11' width='9' height='9' rx='2' fill='none' stroke='%23fff' stroke-width='2'/%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter+Tight:wght@500;600&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap">
<style>{CSS}</style>
</head>
<body>
<div class="bg" aria-hidden="true"><div class="blob b1"></div><div class="blob b2"></div><div class="blob b3"></div>{ARCS_SVG}<div class="grain"></div></div>
{nav()}
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
