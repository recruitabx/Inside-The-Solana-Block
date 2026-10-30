# Design rationale

Companion to `docs/PREREGISTRATION.md` (the binding document). This page gives the reasoning a reader needs in two minutes.

## Why this design

A block alone does not reveal the rule that ordered it. In a read-only sample of mainnet blocks (4 per client, 2026-10-30) the rank correlation between block index and fee per cost unit was weak on every client (Spearman rho between -0.30 and +0.26, computed with consumed cost units as an approximation of the scheduler key), and 18% to 50% of non-vote transactions paid no priority fee. No client sorts its whole block by fee; a rule, if any, acts among transactions that compete at the same moment. We therefore create that competition ourselves. Each probe is a pair of our own transactions that differ in exactly one thing, the fee, with the fee assignment and the position in the request randomized independently. Everything else is identical: instructions, size, compute-unit limit, loaded-data limit, account layout.

Three choices follow from the pinned source code and our localnet calibration:

1. The pair conflicts. Both transactions write one shared account W, so a scheduler cannot run them in parallel and must put one first. In the Agave source, non-conflicting transactions on different worker threads are recorded in the order the workers finish, not in priority order (`docs/research/agave_jito_scheduler.md`, section 2.7); a conflicting pair is serialized on one worker in scheduling order.
2. The pair arrives just before the window. Agave and Jito buffer transactions that arrive less than two slots before their window and schedule only once a leader bank exists; Firedancer's pack schedules only while leader; BAM and Harmonic builders batch in about 50 ms. The localnet calibration shows why this matters: an idle Agave 4.3.2 node ordered spaced transactions by arrival (60 of 60), and ordered a conflicting pair by fee (57 of 60) only when both waited in a busy scheduler (`docs/CALIBRATION.md`). One send-time constant is chosen in the pilot (the earliest offset with an adequate usable rate, which favours co-presence) and then fixed; the realized offset is logged per probe.
3. The fee contrast is defined on the scheduler key, reward per cost, not on the price field. With a 1,000 CU limit and a 4,096-byte loaded-data limit the cost is 2,328 units for both transactions; the high transaction pays 5,500 lamports of priority fee against 1 lamport, a 3.2x reward ratio once the 2,500-lamport base-fee share is included.

The outputs are two numbers per validator, p (share of pairs where the higher-fee transaction came first) and q (share where the first-sent came first), each with an exact confidence interval, and a verdict from rules written before the data exist: fee rule (strict, strong, partial), request-position rule, mixed, no fee or request-position rule detected (an equivalence test), or insufficient data. An equal-fee arm gives the noise floor, a disjoint arm separates scheduler order from execution races, and a spaced arm with randomized send order 200 ms apart measures arrival order directly.

## How the design handles each consideration

| Consideration | How it is handled, or why deliberately not |
|---|---|
| Leader schedule and leader types | Windows are 4 slots and 4-aligned (measured). Targets are frozen identities, one per client type, chosen by a stated rule that requires a stable gossip claim (same clientId and version over at least 18 hours) because claims flap: 33 of about 3,900 nodes changed claim within 80 minutes on 2026-10-30. Leader type is the gossip clientId plus version, snapshotted at the start and end of every run and committed. The leader that actually produced a block is read from its Fee reward, never assumed from the schedule. |
| Path from our backend to the executing node | Our VM cannot send UDP or QUIC, so every transaction goes as an HTTPS JSON-RPC request to one provider. Source code tells us what an Agave-style provider does (forward to the leaders of processed slot + 1 and + 5, one QUIC stream per transaction); what we cannot see (provider internals, staked or unstaked connections, node choice, a fee-dependent "priority lane") is listed as not separated. We disable retries, read the provider's processed slot right after each send, and log the send offset. For BAM and Harmonic leaders the advertised TPU belongs to the external node; the path ends there. |
| Interaction of our own transactions with each other | Within a pair the interaction is the design (shared W in arms P, E, S; none in arm D). Across pairs there is none by construction: one probe per window, a fresh W per probe, distinct payers, a payer reused only after confirmation or expiry, at least 2 s between probes. |
| Competition inside the block | Other transactions compete with ours. Ours sit high in the priority queue (about 1.1 and 3.4 lamports per cost unit, while 18% to 50% of transactions pay no priority fee), so the leader can schedule both promptly; the order between them is still the leader's decision. Block size, total CU and slot index are recorded, and the same blocks are used to test the scheduler key on other people's transactions. |
| Send order | The position of the high-fee transaction in the request is randomized independently of the fee assignment, giving q as a second estimand. The spaced arm sends two requests 200 ms apart in random order, the only arm with a known send order, to test for an arrival rule and for overtaking. |
| Noise versus rule | Pre-specified estimands and verdict thresholds; an equal-fee arm as the noise floor; an equivalence test (90% intervals of both p and q inside [0.35, 0.65]) as the only route to "no rule detected"; Holm correction over all tests; synthetic data with planted rules and two localnet known answers as checks on the analysis code. |

What we do not separate is listed in section 13 of the preregistration: arrival from random order within one request; fee-dependent provider routing; external builder from local scheduler; operator configuration from client software; whether the pair was co-present in the buffer; and self-reported, sometimes flapping, leader software.

## The transport limitation and its consequences

The study VM cannot reach validators directly: outbound UDP is blocked, so there is no QUIC to a leader's TPU. All probes go through one provider endpoint, which on 2026-10-30 accepted a JSON-RPC batch of two sends every two seconds (eight of eight at that pace, about half rejected at one second). Consequences:

- Arrival order at the leader is unobservable; the request position is what we control. Arm S is the only arm with a known send order.
- The provider may route the two transactions through different nodes or connections, and may favour higher fees. This cannot be removed and is listed as not separated.
- Target hits are imperfect: a request that arrives early lands with the previous leader. Every landed pair is attributed to the actual block producer; untargeted landings are kept as secondary data.
- Budget bounds the six high-window validators (quota about 343 probes each, about 43 million lamports of fees in total); leader windows bound the two low-window validators, which need 11 to 14 run-hours.

## Threats to validity

- Co-presence. If the two transactions are never in the buffer together, p near 0.5 reflects arrival luck, not the absence of a fee rule. The early send offset, the co-presence subgroup p_co, arm S and the logged offsets bound this, and the verdict "no rule detected" adds "arrival order not excluded" unless arm S rules it out.
- Provider route. Internal reordering, duplicate suppression or a fee-dependent fast lane at the provider could mimic or mask a rule. We disclose it; no arm of this design removes it.
- External builders. For AgaveBam, FireBAM and Harmonic validators the verdict describes builder plus validator as one system; the Harmonic strategy memo labels windows, but the builders' code is not public. A BAM session can connect or drop between windows, which the run-start and run-end snapshots record.
- Self-reported software. clientId and version are gossip claims; an identity can alternate between machines running different clients.
- Low-window validators. Agave-1 and Rakurai-1 have about 18 and 24 windows per hour; they are the most likely "insufficient data" verdicts, and that is reported rather than patched.
- Our transactions are unusual: tiny, high priority per cost, zero-lamport transfers. The verdict is about how the leader orders two such transactions; the supplementary analysis of other people's transactions checks whether the same key explains their order.
- Fee-first and send-first are not exclusive. A leader can show both (fee decides when co-present, arrival otherwise); the 2 x 2 table and the per-validator logistic model report that mixture.
