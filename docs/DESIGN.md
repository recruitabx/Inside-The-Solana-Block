# Design rationale

Companion to `docs/PREREGISTRATION.md`, the binding document; the reasoning in two minutes.

## Why this design

A block alone does not reveal the rule that ordered it. Our read-only sample of mainnet blocks showed weak rank correlation between block index and reward per cost on every client (Spearman rho from -0.30 to +0.26): no client sorts its whole block by fee, and the rule, if any, acts among transactions that compete at the same moment. We therefore create that competition ourselves. Each probe is a pair of our own transactions differing in exactly one thing, the fee, with fee assignment and request position randomized independently. Everything else is identical: instructions, size, compute-unit limit, loaded-data limit, account layout.

Three choices follow from the pinned sources and our localnet calibration:

1. The pair conflicts. Both transactions write one shared account W, so a scheduler cannot run them in parallel and must put one first. On localnet, non-conflicting pairs sent together were ordered by fee only 18 of 40 times (a race between worker threads), conflicting pairs 30 of 40.
2. The pair arrives just before the window. Agave and Jito buffer transactions arriving less than two slots before their window and schedule only once a leader bank exists; Firedancer's pack pool persists and schedules only while leader; BAM and Harmonic builders batch in about 50 ms. Landing the pair in that buffering state is the only way both are present at the first scheduling decision. One send-time constant is tuned in the pilot on operational rates, then fixed; the realized offset is logged per probe.
3. The fee contrast is defined on the scheduler key, reward per cost. With a 1,000 CU limit and a 4,096-byte loaded-data limit the cost is 2,328 units for both; the high transaction pays 5,500 lamports of priority fee against 1 lamport, a 3.2x reward ratio once the 2,500-lamport base-fee share is included. A 2x contrast would buy about 20% more probes; we prefer the margin against closed or bucketing schedulers.

The outputs are two numbers per validator, p (share of pairs where the higher-fee transaction came first) and q (share where the first-sent came first), with exact confidence intervals, plus a verdict from rules written before the data exist: fee rule (strict, strong, partial), send-order rule, mixed, no detectable rule (equivalence test), or insufficient data. A placebo arm with equal fees gives the noise floor, a disjoint arm separates scheduler order from execution races, and a spaced arm with known send order tests whether a later high-fee transaction can overtake.

## How the design handles each consideration

| Consideration | How it is handled, or why deliberately not |
|---|---|
| Leader schedule and leader types | Windows are 4 slots and 4-aligned; the next epoch's schedule is fetched when published and hashed per run. Leader type is the gossip clientId plus version string, snapshotted and committed per run because it cannot be re-queried later. Eight targets span eight clientIds (four with local schedulers, four with external builders) and three version strings. Consecutive windows of one leader are flagged. The leader that actually produced a block is read from its Fee reward, never assumed from the schedule. |
| Path from our backend to the executing node | Our VM cannot send UDP or QUIC, so every transaction goes as one HTTPS JSON-RPC request to one provider. Source code tells us what an Agave-style provider does (forward to the leaders of processed slot + 1 and + 5, one QUIC stream per transaction, retries every 2 s); provider internals, staked or unstaked connections and node choice are documented as unseen. We disable retries, read the provider's processed slot right after each send, and log the send offset. For BAM and Harmonic leaders the advertised TPU belongs to the external node; the path ends there. |
| Interaction of our own transactions with each other | Within a pair the interaction is the design (shared W in arms P, E, S; none in arm D). Across pairs there is none by construction: one probe per window, a fresh W per probe, distinct payers from a pool, a payer reused only after confirmation or expiry, at least 2 s between requests. |
| Competition inside the block | Ours sit high in the priority queue (about 1.1 and 3.4 lamports per cost unit against typically below 0.1), so the leader can schedule both promptly; their order is still its decision. Block size, total CU, slot index and index gap are recorded. Supplementary analyses on other people's transactions use `meta.costUnits` and the fee fields of every landed transaction. |
| Send order | The position of the high-fee transaction in the request is randomized independently of the fee assignment, giving q as a second estimand. The spaced arm fixes the order (low first, high 200 ms later) to test overtaking. |
| Noise versus rule | Pre-specified estimands and verdict thresholds; a placebo arm with no fee contrast; an equivalence test (90% interval of both p and q inside [0.35, 0.65]) as the only route to "no detectable rule"; Holm correction across validators; synthetic data with planted rules and two localnet known answers as checks on the analysis code. |

What we do not separate is stated in the preregistration: first-in-first-out by true arrival from random order; external builder from local scheduler; provider routing from leader behaviour; whether the pair was co-present in the buffer; and self-reported leader software.

## The transport limitation and its consequences

The study VM cannot reach validators directly: outbound UDP is blocked, so there is no QUIC to a leader's TPU. All probes go through one provider endpoint, which accepts a JSON-RPC batch of two sends every two seconds (eight of eight accepted at that pace, half rejected at one second). Consequences:

- Arrival order at the leader is unobservable; the batch position is what we control. Arm S alone has a near-certain arrival order, and only in one direction.
- The provider may route the two transactions through different nodes or connections; this noise cannot be removed, one reason the placebo and equivalence machinery exist.
- Target hits are imperfect: a request that arrives one slot early lands with the previous leader. Every landed pair is attributed to the actual block producer; untargeted landings are kept as secondary data.
- Budget rather than rate bounds the sample: at 15,501 lamports per contrast pair the cap allows about 3,100 probes; we plan 2,400.

Localnet showed the same in miniature: the local RPC forwards a batch one transaction at a time, so an idle node orders by arrival (34 of 34 with 50 ms spacing) and the fee can act only when both transactions reach the buffer before a scheduling pass; hence the positive control injects the pair in one QUIC burst into the local TPU.

## Threats to validity

- Co-presence. If the two transactions are never in the buffer together, p near 0.5 reflects arrival luck, not the absence of a fee rule. The pre-window send time, the placebo, the spaced arm and the logged offsets bound this, but p remains a lower bound on the strictness of a priority rule.
- Provider route. Internal reordering or duplicate suppression at the provider could mimic or mask a rule. The disjoint arm and the placebo share the route, so a route artefact would appear in them too.
- External builders. For AgaveBam, FireBAM and Harmonic validators the verdict describes builder plus validator as one system; the Harmonic strategy memo (FBA, MRV, FIF) labels windows, but the builders' code is not public. A BAM session can connect or drop between windows, and a leader whose advertised TPU moved to a BAM node drops packets at its own TPU, which may lower landing rates for those targets; the pilot measures this per validator.
- Self-reported software. clientId and version are gossip claims; we snapshot them per run and report them as claims.
- Time for low-window validators. Agave-1 and Rakurai-1 have about 18 and 24 windows per hour, so reaching 100 usable primary probes needs roughly 10 to 14 hours of runs; they are the likeliest "insufficient data" verdicts, reported rather than patched.
- Our transactions are unusual: tiny, high priority per cost, zero-lamport transfers. The verdict is about how the leader orders two such transactions; the supplementary analysis checks whether the same key explains other people's order.
- Fee-first and send-first are not exclusive. A leader can show both (fee decides when co-present, arrival otherwise); the 2 x 2 table and the per-validator logistic model report that mixture instead of forcing one label.

## Design conditions adopted

All mandatory design conditions are adopted; two are tightened: "no detectable rule" requires the equivalence test on both p and q, not only p, and the two low-window validators use arm shares 85/5/5/5, keeping the primary cell above the required 70% while maximizing their chance of reaching the minimum N.
