"""Command line entry point: `itb <command>`."""
from __future__ import annotations

import sys

COMMANDS = {
    "verify": "itb.verify",       # judges: re-check a random sample of our transactions with getBlock
    "run": "itb.runner",          # experiment runner (dry-run by default, --live to send)
    "collect": "itb.collector_cli",  # resolve sent transactions to slot/index/leader records
    "analyze": "itb.analyze",     # all tables/figures/verdicts from raw data
    "snapshot": "itb.snapshot",   # client id / version snapshot of staked nodes
    "fund": "itb.funds:fund",     # fund derived fee payers from the wallet (live only)
    "drain": "itb.funds:drain",   # return payer balances to the wallet (live only)
    "anchor": "itb.funds:anchor", # memo anchor of a sha256 (live only)
    "audit": "itb.audit",         # prove every fee-paying tx of our accounts is in the ledger
    "pilot-report": "itb.pilot_report",  # operational pilot metrics and the tau0 choice (never ordering outcomes)
}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help") or argv[0] not in COMMANDS:
        print("usage: itb {" + ",".join(COMMANDS) + "} [options]")
        return 0 if argv and argv[0] in ("-h", "--help") else 2
    target = COMMANDS[argv[0]]
    modname, _, attr = target.partition(":")
    mod = __import__(modname, fromlist=["main"])
    obj = getattr(mod, attr) if attr else mod
    return int(obj.main(argv[1:]) or 0)


if __name__ == "__main__":
    sys.exit(main())
