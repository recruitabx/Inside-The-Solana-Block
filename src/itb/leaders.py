"""Leader schedule, leader windows and client identification."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass

from .rpc import Rpc


@dataclass(frozen=True)
class Window:
    leader: str
    first_slot: int
    last_slot: int

    @property
    def n_slots(self) -> int:
        return self.last_slot - self.first_slot + 1


def windows_from_leaders(start_slot: int, leaders: list[str]) -> list[Window]:
    """Group a getSlotLeaders result into runs of consecutive slots with the same leader."""
    out: list[Window] = []
    i = 0
    while i < len(leaders):
        j = i
        while j + 1 < len(leaders) and leaders[j + 1] == leaders[i]:
            j += 1
        out.append(Window(leaders[i], start_slot + i, start_slot + j))
        i = j + 1
    return out


def upcoming_windows(rpc: Rpc, start_slot: int, n_slots: int) -> list[Window]:
    leaders: list[str] = []
    s = start_slot
    while len(leaders) < n_slots:
        chunk = min(5000, n_slots - len(leaders))
        leaders += rpc.call("getSlotLeaders", [s, chunk])
        s += chunk
    return windows_from_leaders(start_slot, leaders)


def epoch_schedule_windows(rpc: Rpc, identities: set[str] | None = None) -> tuple[dict, list[Window]]:
    """Whole-epoch leader schedule as windows, optionally restricted to some identities."""
    info = rpc.call("getEpochInfo", [{"commitment": "confirmed"}])
    first = info["absoluteSlot"] - info["slotIndex"]
    sched = rpc.call("getLeaderSchedule", [None, {"commitment": "confirmed"}])
    slot_to_leader = {}
    for ident, idxs in sched.items():
        if identities is None or ident in identities:
            for k in idxs:
                slot_to_leader[first + k] = ident
    wins: list[Window] = []
    for s in sorted(slot_to_leader):
        ident = slot_to_leader[s]
        if wins and wins[-1].leader == ident and wins[-1].last_slot == s - 1:
            wins[-1] = Window(ident, wins[-1].first_slot, s)
        else:
            wins.append(Window(ident, s, s))
    return info, wins


def client_snapshot(rpc: Rpc) -> dict:
    """Self-reported client id and version of every staked node, with stake, at this moment.
    `delinquent` is True unless the node has a vote account in getVoteAccounts "current" with stake."""
    nodes = rpc.call("getClusterNodes")
    va = rpc.call("getVoteAccounts")
    stake: dict[str, int] = {}
    for a in va["current"] + va["delinquent"]:
        stake[a["nodePubkey"]] = stake.get(a["nodePubkey"], 0) + int(a["activatedStake"])
    current = {a["nodePubkey"] for a in va["current"] if int(a["activatedStake"]) > 0}
    slot = rpc.call("getSlot", [{"commitment": "confirmed"}])
    out = {"taken_at_unix": time.time(), "slot": slot, "total_stake": sum(stake.values()), "nodes": {}}
    for n in nodes:
        if stake.get(n["pubkey"], 0) > 0:
            out["nodes"][n["pubkey"]] = {"clientId": n.get("clientId"), "version": n.get("version"),
                                         "featureSet": n.get("featureSet"), "stake": stake[n["pubkey"]],
                                         "delinquent": n["pubkey"] not in current}
    return out


class SlotClock:
    """Estimates the current slot from periodic getSlot samples and a measured slot rate, so
    the scheduler does not have to poll the RPC every few hundred milliseconds.

    The slot time starts at 0.2143 s (mainnet after Alpenglow, 213 to 214 ms realized) and is
    refitted from the oldest and newest samples once they span at least `MIN_FIT_SPAN_S` seconds.
    `sync()` never issues more than about one RPC call per second: a call made less than
    `MIN_SYNC_INTERVAL_S` after the previous one returns the extrapolated slot instead."""

    INITIAL_SLOT_S = 0.2143
    MIN_FIT_SPAN_S = 5.0
    MIN_SYNC_INTERVAL_S = 0.95

    def __init__(self, rpc: Rpc, commitment: str = "processed"):
        self.rpc, self.commitment = rpc, commitment
        self.samples: list[tuple[float, int]] = []
        self.slot_s = self.INITIAL_SLOT_S
        self.last_call_t = 0.0      # start time of the last getSlot call (0.0: none yet)
        self.n_calls = 0

    def since_sync(self) -> float:
        return time.time() - self.last_call_t

    def sync(self) -> int:
        if self.samples and self.since_sync() < self.MIN_SYNC_INTERVAL_S:
            return int(self.now())
        t0 = time.time()
        self.last_call_t = t0
        self.n_calls += 1
        s = self.rpc.call("getSlot", [{"commitment": self.commitment}])
        t = (t0 + time.time()) / 2
        self.samples.append((t, s))
        self.samples = self.samples[-50:]
        if len(self.samples) >= 2:
            (ta, sa), (tb, sb) = self.samples[0], self.samples[-1]
            if sb > sa and tb - ta >= self.MIN_FIT_SPAN_S:
                self.slot_s = (tb - ta) / (sb - sa)
        return s

    def now(self) -> float:
        t, s = self.samples[-1]
        return s + (time.time() - t) / self.slot_s

    def time_of(self, slot: float) -> float:
        t, s = self.samples[-1]
        return t + (slot - s) * self.slot_s


def save_json(path: str, obj) -> None:
    with open(path, "w") as f:
        json.dump(obj if not isinstance(obj, Window) else asdict(obj), f)
