"""simulateTransaction check of the two probe templates (docs/PREREGISTRATION.md section 10, criterion 3).

Both templates (high and low compute-unit price) are built with the funding wallet's PUBLIC key as payer
as an UNSIGNED transaction and simulated with sigVerify false and replaceRecentBlockhash true. Nothing is
signed and nothing is sent. The template must stay cheap and small:
unitsConsumed <= 700 and loadedAccountsDataSize <= 4096.
Used by scripts/acceptance.py and `itb pilot-report`.
"""
from __future__ import annotations

import json
import os

from solders.pubkey import Pubkey

from .rpc import Rpc, RpcError, TransportError
from .txbuild import build_probe_unsigned_b64, fresh_address

PUBLIC_RPC = "https://api.mainnet-beta.solana.com"
MAX_UNITS_CONSUMED = 700
MAX_LOADED_ACCOUNTS_DATA = 4096
DEFAULT_TEMPLATE = {"price_high": 5_500_000, "price_low": 1_000, "cu_limit": 1_000, "loaded_limit": 4_096}


def funding_pubkey(accounts_path: str = "data/accounts.json", pub_path: str = "~/ops/wallet.pub") -> str | None:
    """Public key of the funding wallet: data/accounts.json ("wallet") if present, else the one-line public key
    file. Never reads a secret key file."""
    if os.path.exists(accounts_path):
        try:
            with open(accounts_path) as f:
                return str(json.load(f)["wallet"]).strip()
        except (OSError, ValueError, KeyError):
            pass
    pub = os.path.expanduser(pub_path)
    if os.path.exists(pub):
        with open(pub) as f:
            return f.read().strip() or None
    return None


def template_params(plan_path: str = "data/plan.json") -> dict:
    """The frozen template parameters of the plan if there is one, else the preregistered defaults."""
    p = dict(DEFAULT_TEMPLATE)
    if os.path.exists(plan_path):
        try:
            with open(plan_path) as f:
                plan = json.load(f)
            p.update({k: plan[k] for k in ("price_high", "price_low", "cu_limit", "loaded_limit") if k in plan})
        except (OSError, ValueError):
            pass
    return p


def simulate_templates(rpc: Rpc, payer: str, params: dict | None = None) -> dict:
    """{"payer", "ok", "templates": {"high"|"low": {"ok", "unitsConsumed", "loadedAccountsDataSize", "err", ...}}}.
    A transport or RPC failure is reported in `error`, not raised."""
    prm = {**DEFAULT_TEMPLATE, **(params or {})}
    out: dict = {"payer": payer, "limits": {"unitsConsumed": MAX_UNITS_CONSUMED, "loadedAccountsDataSize": MAX_LOADED_ACCOUNTS_DATA},
                 "templates": {}}
    try:
        pk = Pubkey.from_string(payer)
    except ValueError:
        out.update(ok=False, error="payer is not a valid public key")
        return out
    for name, price in (("high", prm["price_high"]), ("low", prm["price_low"])):
        b64 = build_probe_unsigned_b64(pk, cu_limit=prm["cu_limit"], cu_price=price, loaded_limit=prm["loaded_limit"],
                                       shared=fresh_address("simulate", name))
        opts = {"encoding": "base64", "sigVerify": False, "replaceRecentBlockhash": True, "commitment": "processed"}
        try:
            v = rpc.call("simulateTransaction", [b64, opts])["value"]
        except (RpcError, TransportError) as e:
            out["templates"][name] = {"ok": False, "cu_price": price, "error": f"{type(e).__name__}: {str(e)[:200]}"}
            continue
        units, loaded = v.get("unitsConsumed"), v.get("loadedAccountsDataSize")
        ok = (v.get("err") is None and units is not None and loaded is not None
              and units <= MAX_UNITS_CONSUMED and loaded <= MAX_LOADED_ACCOUNTS_DATA)
        out["templates"][name] = {"ok": bool(ok), "cu_price": price, "unitsConsumed": units, "loadedAccountsDataSize": loaded,
                                  "err": v.get("err")}
    out["ok"] = len(out["templates"]) == 2 and all(t["ok"] for t in out["templates"].values())
    return out


def render(res: dict) -> str:
    L = [f"simulateTransaction of the probe templates (payer = funding wallet public key {res['payer']}, unsigned, sigVerify false, "
         f"replaceRecentBlockhash true; need unitsConsumed <= {MAX_UNITS_CONSUMED}, loadedAccountsDataSize <= {MAX_LOADED_ACCOUNTS_DATA})"]
    for name, t in res["templates"].items():
        L.append(f"  {name:4s} price {t['cu_price']}: {'PASS' if t['ok'] else 'FAIL'}  unitsConsumed={t.get('unitsConsumed')} "
                 f"loadedAccountsDataSize={t.get('loadedAccountsDataSize')} err={t.get('err')} {t.get('error', '')}".rstrip())
    L.append(f"  templates: {'PASS' if res.get('ok') else 'FAIL'}" + (f" ({res['error']})" if res.get("error") else ""))
    return "\n".join(L)
