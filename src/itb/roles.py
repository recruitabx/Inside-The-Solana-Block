"""Role-based targeting with replacement (docs/PREREGISTRATION.md section 4).

The plan's targets are ROLES. A role has a clientId and an ordered candidate list [primary identity,
replacement 1, 2, 3] (from data/validators.json). At the start of every run, from the run-start gossip
snapshot, each role is assigned the FIRST candidate that (a) is a staked node in the snapshot,
(b) currently reports the role's clientId, and (c) is not delinquent (it has a vote account in
getVoteAccounts "current" with stake). A role without such a candidate is skipped for that run and the
reason of every rejected candidate is logged. Quotas and counts belong to the role, not to the identity,
so a replacement inherits the remaining quota (budget-neutral).
"""
from __future__ import annotations


def candidates_of(target: dict) -> list[str]:
    """Ordered candidate identities of a plan target: its `candidates` list, else just its `identity`."""
    cand = list(target.get("candidates") or [])
    if not cand and target.get("identity"):
        cand = [target["identity"]]
    return cand


def assign_roles(targets: list[dict], snap: dict) -> dict[str, dict]:
    """{role: {"identity", "candidate_index", "clientId", "version", "rejected": [{"identity", "reason"}], "skipped"}}.
    `identity` is None (and `skipped` a reason) for a role without a valid candidate. An identity is
    assigned to at most one role."""
    out: dict[str, dict] = {}
    used: set[str] = set()
    for t in targets:
        role, want = t["role"], t.get("clientId")
        if want is None:
            raise ValueError(f"plan target {role} has no clientId: cannot check candidates against it")
        rejected, chosen = [], None
        for i, ident in enumerate(candidates_of(t)):
            node = snap["nodes"].get(ident)
            if ident in used:
                reason = "already assigned to another role"
            elif node is None:
                reason = "not a staked node in the start snapshot"
            elif node.get("clientId") != want:
                reason = f"clientId {node.get('clientId')} differs from the role's {want}"
            elif node.get("delinquent") is not False:
                reason = "delinquent (no current vote account with stake)"
            else:
                chosen = (i, ident, node)
                break
            rejected.append({"identity": ident, "reason": reason})
        if chosen is None:
            out[role] = {"identity": None, "candidate_index": None, "clientId": want, "version": None,
                         "rejected": rejected, "skipped": "no valid candidate"}
        else:
            i, ident, node = chosen
            used.add(ident)
            out[role] = {"identity": ident, "candidate_index": i, "clientId": node.get("clientId"),
                         "version": node.get("version"), "rejected": rejected, "skipped": None}
    return out
