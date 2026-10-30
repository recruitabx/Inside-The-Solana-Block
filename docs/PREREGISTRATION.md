# Preregistration: in-block ordering rules of selected Solana mainnet validators

Version 1.1, written 2026-10-30 before any live measurement (v1.0 was revised after an internal design review; both versions are in the git history). This version is frozen when its SHA-256 is written to mainnet in a memo transaction, before the pilot. Later changes are appended as dated amendments at the end and never overwrite this text.

## 1. Question and scope

For each selected validator: by what rule does it order transactions in its block, how strictly does the rule hold, and is there a rule at all. "No rule, it is noise" is an admissible answer.

Mainnet only; slots at or above `MIN_SLOT = 459653008` (first block after Alpenglow, `docs/ALPENGLOW_BOUNDARY.md`); primary evidence is our own transactions, other transactions are supplementary; Jito bundles and tips are out of scope; total fee spend is capped at 0.05 SOL (50,000,000 lamports) by `HARD_SPEND_CEILING_LAMPORTS` in `src/itb/config.py`; live window from the target freeze and pilot on 2026-10-31 to 2026-11-02, reserve 2026-11-03, resumable runs of at most 20 minutes, about 16 run-hours in total (the two low-window validators need 11 to 14 run-hours to reach their quotas).

## 2. Mechanisms and hypotheses

From the pinned sources in `docs/research/`: Agave 4.3.2 and 4.4.x and Jito-Solana without a BAM session compute priority = reward x 10^6 / (cost + 1), reward = priority fee + 2,500 lamports per signature (the non-burned half of the base fee), cost from the requested compute-unit (CU) and loaded-accounts-data limits. Rakurai's public client contains the same function, but its scheduler is a closed binary whose rule is unknown. The Agave greedy scheduler pops the highest priority, serializes conflicting transactions on one worker, lets non-conflicting batches race across workers, schedules only while a leader bank exists, and buffers arrivals in the two slots before its window. Firedancer 26.10.x orders by the same ratio, block order equals pack order, conflicting writers are serialized. AgaveBam and FireBAM: a BAM node orders by fee per CU in about 50 ms batches and the validator executes the received order. Harmonic clients: a hosted builder applies the operator's strategy, `fba` (50 ms batches by priority fee and tip, default), `fifo` or proprietary `mrev`, with local fallback; a memo in the window's first block names it. Our localnet calibration (`docs/CALIBRATION.md`) shows the Agave 4.3.2 rule directly: arrival order when the scheduler is idle (60 of 60 first-sent-first), fee order when both transactions wait in a busy scheduler (57 of 60 higher-fee-first).

Notation, both conditional on the pair landing in one block: p = P(higher reward-per-cost transaction first), q = P(first-sent transaction first), pi = 2p - 1.

| Hypothesis | Prediction | Predicted for |
|---|---|---|
| H_prio: reward per cost | p near 1, q near 0.5 when both are co-present in the buffer | Agave family, Firedancer, BAM, Harmonic `fba` |
| H_total: total priority fee | not separable in our pairs; tested on other people's transactions (section 12) | Harmonic wording |
| H_arrival: first in, first out | q_S near 1 in arm S; p and q in arm P near 0.5 if arrival within a batch is random | Harmonic `fifo`; any client when the pair is not co-present |
| H_null: noise | p and q near 0.5 and q_S near 0.5 | worker races, unseen path effects |
| H_race (arm D), exploratory | p_D below p_P on the Agave family (record-channel race), about equal on Firedancer | Agave family vs Firedancer |
| H_strategy, exploratory | p differs between Harmonic windows labelled FBA, MRV and FIF | Harmonic |

## 3. Unit of observation and outcomes

A probe is one pair of our transactions aimed at one leader window. Outcomes: landed (0, 1 or 2 transactions), same slot, block producer (the `rewardType = "Fee"` pubkey of that block, never the targeted identity), block indices and their gap, Y_fee = 1 if the higher reward-per-cost transaction has the lower index, Y_send = 1 if the first-sent transaction has the lower index. Covariates: arm, assignments, random key, send timestamps, tau = send time minus estimated start of the target's first slot, the provider's processed slot read right after the send, consecutive-window flag, gossip claims (clientId, version) of the target at run start and run end, schedule hash; from the block: slot index within the window, transaction count, total CU consumed, Harmonic strategy memo of the window's first block.

## 4. Validators

Eligibility, evaluated at the freeze (planned 2026-10-31 around 09:00 UTC) on the epoch-1074 leader schedule (the epoch that covers most of the live window): at least 400 leader windows in that epoch; the same (clientId, version) claim in every one of at least 4 gossip snapshots spanning at least 18 hours (committed in `data/selection/snapshots/`); not operated by our RPC provider (identities starting `HEL1US`, a channel confound). Gossip claims do flap: between 14:20 and 15:40 UTC on 2026-10-30, 33 of about 3,900 nodes changed clientId or version, one large identity alternating between JitoLabs 4.3.2 and Firedancer 26.10.4.

Selection: for every clientId with at least one eligible identity, the eligible identity with the most windows (role `<clientId>-1`). Expected roles: AgaveBam-1, JitoLabs-1, HarmonicAgave-1, HarmonicFiredancer-1, Firedancer-1, FireBAM-1, Rakurai-1, Agave-1. The selection must contain at least 6 validators, 3 clientIds and 3 distinct version strings, otherwise the window threshold is lowered to 300 and the selection repeated. Identities, claims, windows and ineligible top candidates with reasons are frozen in `data/validators.json` by `scripts/freeze_targets.py`.

Replacement: a target that is delinquent, absent from a later epoch's schedule, or reports a different clientId at a run's start snapshot is replaced by the next eligible identity of the same clientId by windows (version only breaks ties); the original's data is kept and reported separately. If a target's claim differs between a run's start and end snapshots, that run's probes for that target leave the primary cell and are reported separately. A version change alone splits the data into separate (identity, version) units.

## 5. Arms, transaction templates, randomization

Every probe transaction is legacy, one signature, four instructions: `SetComputeUnitLimit(1000)`, `SetComputeUnitPrice(price)`, `SetLoadedAccountsDataSizeLimit(4096)`, `SystemProgram.Transfer(payer -> W, 0 lamports)`. Accounts: payer (writable signer), W (writable), System and ComputeBudget programs (read-only). No memo. W is a fresh, never-funded address derived from the seed and the probe (a 0-lamport transfer to it executes and takes the write lock). Payers: a pool of 6 funded accounts, always two different ones per pair, each reused only after its previous transaction has a status or 35 s have passed.

| Level | price (micro-lamports/CU) | priority fee | total fee | reward | priority key (Agave) |
|---|---|---|---|---|---|
| high | 5,500,000 | 5,500 | 10,500 | 8,000 | 3,434,950 |
| low | 1,000 | 1 | 5,001 | 2,501 | 1,073,851 |

Key cost = 720 (signature) + 600 (two write locks) + 1,000 (requested CU) + 8 (one 32 KiB page of loaded-data limit) = 2,328, identical within a pair, so the 3.2 reward ratio is the contrast under any fee-based key. `meta.costUnits` is recorded (it reflects consumed CU). A 2x contrast would buy about 20% more probes; we keep 3.2x as margin against schedulers that may bucket or round.

| Arm | Share | Layout | Purpose |
|---|---|---|---|
| P, conflicting contrast (primary) | 70% (85% for Rakurai-1, Agave-1) | shared W, one high, one low, one JSON-RPC batch | forced serialization: fee rule vs request position |
| E, equal fee | 10% (5%) | shared W, both low | negative control: noise floor, request-position effect |
| D, disjoint contrast | 10% (5%) | separate W per transaction | scheduler order vs execution race |
| S, spaced | 10% (5%) | shared W; two requests 200 ms apart, which of high and low goes first is random | known send order: arrival rule (q_S) and overtaking (p_S) |

Randomization: for each window that passes all skip checks, a generator seeded with `"<seed>:<window first slot>:<target identity>"` (seed frozen in `data/plan.json`) draws independently: the arm (by the target's shares), which payer carries the high price, and the request position (or, in arm S, the send order) of the high transaction; in arm E one transaction is labelled "pseudo-high" the same way. Because the key is the window, the assignment does not depend on which earlier windows were skipped. The sender never reads outcomes.

Quotas: after the pilot, quota = ceil(115 / (share_P x u)) with u the pooled usable fraction from the pilot (section 10), which targets 115 usable primary probes (100 plus margin); Rakurai-1 and Agave-1 are capped at 330. At u = 0.48 this gives 343 and 282. Nothing is sent beyond a quota or the spend cap.

## 6. Timing and delivery

One send-time constant tau0, chosen in the pilot and then fixed: the pair is sent at tau0 relative to the estimated start of the target's first slot S. Rationale: an Agave-style provider forwards to the leaders of its processed slot + 1 and + 5, so a request arriving while that slot is S - 1 reaches the target while it is still buffering. Pilot grid: tau0 in {-270, -170, -70} ms. Rule: the earliest (most negative) tau0 whose pooled u is at least 0.40, else the tau0 with the highest u. This favours co-presence over raw landing rate. The slot clock starts at 213 ms per slot and is refitted from `getSlot(processed)` polled at least every 2 s. Arm S sends its first request at tau0 - 200 ms and the second at tau0.

`sendTransaction`: base64, `skipPreflight: true`, `preflightCommitment: processed`, `maxRetries: 0`, changed once to `maxRetries: 2` if the pilot landing rate is below 80%. One HTTP request per probe (two for arm S) to one endpoint. Rate rules: at most 2 transactions per request, at least 2.0 s between probes, one probe per window; a window is skipped (logged) when these rules or payer availability would be violated. Arm S sends two requests 200 ms apart; if the pilot shows a 429 rate of 5% or more on its second request, arm S's share moves to arm P. Each run starts with an anchor transaction whose memo carries the SHA-256 of the run configuration (plan hash, snapshot hash, run id, code commit).

## 7. Inclusion and exclusion

Primary cell for a unit (role, identity, clientId, version): main-phase arm-P probes with both transactions in one block whose Fee-reward pubkey is the target, in a slot of the targeted window, from runs in which the target's claim did not change. Excluded from p and q, counted and reported: one or zero transactions landed; different slots (secondary: share where the high-fee transaction landed in the earlier slot, and order by (slot, index)); landed at a leader other than the target (secondary, attributed to the actual producer, never pooled into a primary cell); slot below `MIN_SLOT` (rejected by code). A transaction with an execution error is included and flagged. Pilot probes never enter the confirmatory analysis. `itb analyze` refuses to read main-phase data unless run with `--final`, which we run once, after the last main run.

## 8. Estimands, statistics, sample size, stopping

Per unit, from the primary cell: p and q with exact Clopper-Pearson 95% intervals, pi reported as "share of pairs decided by fee" (a fee-deciding fraction plus coin flips), and the 2 x 2 table of Y_fee by request position of the high transaction. Tests: exact two-sided binomial tests of p = 0.5 and q = 0.5 for every unit, Holm-corrected over all these tests together (one family, about 16 tests), family alpha 0.05. Sensitivity check per unit: logistic regression of "transaction A first" on (A is high) and (A sent first). One probe per window, so probes are independent; probes sharing a block are noted.

Minimum usable N in the primary cell: 100 per unit. Exact calculation, two-sided: at the strictest Holm level 0.05/16, N = 100 gives power 0.84 against p = 0.70 (0.88 at 0.05/8); the equivalence condition (90% exact interval inside [0.35, 0.65]) holds with probability 0.81 for one of p and q at N = 100 when the true value is 0.5, and 0.65 for both. Controls (arm E, localnet runs) are exempt from the N rule. Secondary estimates are pooled by clientId; H_race and H_strategy use Fisher's exact test and are labelled exploratory; per-validator secondary numbers are descriptive.

Co-presence subgroup (secondary, same thresholds): arm-P pairs whose provider-reported processed slot right after sending was at most S - 1 and that landed in slot S, giving p_co.

Stopping: fixed quotas, no interim look at ordering outcomes; the only data-dependent choices (tau0, retries, arm-S share, quotas, share fallback) come from operational pilot rates. A unit short of N = 100 at the end is reported as insufficient data.

## 9. Decision rules

Per unit, with Holm-adjusted p-values and L the 95% lower bound of p (of 1 - p for a reverse rule):

- "Fee rule holds" when p = 0.5 is rejected: strict if L is at least 0.90, strong if at least 0.75, partial otherwise. Reported as "fee rule (strength), p [interval], pi". A rule in the opposite direction is reported as "reverse fee rule" with the same strengths.
- "Request-position rule holds": the same rules on q.
- Both rejected: "mixed", explained by the 2 x 2 table.
- Neither rejected, N at least 100, and the 90% intervals of both p and q inside [0.35, 0.65]: "no fee or request-position rule detected (|pi| at most 0.30)". If the pooled arm-S q_S of that unit's clientId is not inside [0.35, 0.65], or has fewer than 30 pairs, the verdict adds "arrival order (FIFO) not excluded".
- Otherwise "insufficient data", with the N reached.

Secondary verdicts (arm S, co-presence subgroup) use the same rules on their estimates and are labelled secondary.

## 10. Controls and pilot acceptance criteria

Negative control: arm E. Positive controls on localnet (`docs/CALIBRATION.md`, Agave 4.3.2 test validator, 60 pairs per condition, run before this version): arrival-known (spaced sends) 60 of 60 first-sent-first; priority-known (conflicting pair injected over one QUIC connection behind slow filler transactions) 57 of 60 higher-fee-first; placebo 29 of 60.

Pilot acceptance criteria, all numeric, none looking at ordering outcomes:

1. Synthetic data with planted rules (p in {1, 0.75, 0.5}, q in {1, 0.5}) at N = 100: the planted value lies inside the 95% interval in at least 94% of 1,000 replicates; false "rule holds" verdicts under the null across eight simulated units at most 5%; power against p = 0.70 at least 0.80.
2. The localnet arrival-known and priority-known runs, replayed through the analysis code, give "request-position rule holds" and "fee rule holds" respectively (control runs, exempt from the N rule).
3. Mainnet pilot, per target 12 arm-P probes (4 per tau0 value) and 2 arm-S probes: `simulateTransaction` of both templates at most 700 CU consumed and 4,096 bytes loaded; transaction landing rate at least 80% (else retries as in section 6 and one re-pilot); HTTP 429 rate below 5%; ledger spend equals the sum of `meta.fee` exactly; pooled usable fraction u (both transactions in one block of the targeted leader within the targeted window, over probes sent) at least 0.40. `itb pilot-report` prints only these operational numbers.

If u is below 0.48, shares become 85/5/5/5 for all targets and quotas follow section 5 with share_P = 0.85. If the planned fees then exceed 46,000,000 lamports, quotas are scaled down proportionally and units projected below N = 100 are declared at risk of insufficient data before the main run.

## 11. Budget

Per transaction: 5,000 base + priority fee. Pair P, D, S = 15,501 lamports; pair E = 10,002; share-weighted mean 14,951 (70/10/10/10) and 15,226 (85/5/5/5). Pilot 8 x 14 x 15,501 = 1,736,112, at most twice with a re-pilot: 3,472,224. Operations (10 fundings, 10 drains, 80 anchors at 5,000): 500,000. Main run at u = 0.48: 6 x 343 x 14,951 + 2 x 282 x 15,226 = 39,356,856. Total fees at most 43,329,080 lamports. Payer rent deposits (6 x 890,880 = 5,345,280) are recoverable and are drained back at the end; peak funding need = 48,674,360 lamports, under 0.05 SOL. The pilot fits the 10,000,000 lamports on hand (rent 5,345,280 + pilot 3,472,224 + pilot operations). Enforcement: `SpendLedger` books each transaction's maximum fee before sending, replaces it by `meta.fee` on confirmation, and refuses any send that would exceed the cap; `itb audit` checks that no fee-paying transaction of our accounts is missing from the ledger.

## 12. Secondary analyses without spend

From the blocks our pairs landed in (full blocks for a 10% sample of slots): (a) the scheduler key of every other transaction, reward (priority fee + 2,500 per signature) over cost estimated from the requested CU limit (cost units minus consumed CU plus requested CU), against block index: Spearman rho per block and validator; (b) the CU-limit versus total-fee crossover: among adjacent pairs where total priority fee and reward per cost disagree, the share ordered by each key; (c) block size, total CU and slot index of our pairs by validator.

## 13. What we do not separate

- First in, first out by true arrival from random order within one request: we do not observe arrival; q measures request position. Arm S, with randomized send order 200 ms apart, estimates an arrival rule with known order, pooled by clientId.
- Fee-dependent routing by the provider: the provider advertises a "priority lane"; if the high-fee transaction travels faster, a FIFO leader would show p above 0.5. Arms D and E share this route and cannot rule it out; arm S bounds it only in part.
- External builders (BAM node, Harmonic builder) from the validator's own scheduler: we observe the composite; the Harmonic memo partly labels it.
- Operator configuration from client software: block-production method, Rakurai's closed binary, the Harmonic strategy and BAM plugins are chosen per operator, so a verdict describes one validator, and pooling by clientId is descriptive.
- Provider routing in general (node choice, staked or unstaked connections, duplicates, reordering) from leader behaviour.
- Co-presence in the scheduler buffer: p measures the rule as experienced by a sender using one RPC request, a lower bound on a priority rule's strictness under co-presence; p_co is the secondary estimate on likely co-present pairs.
- Leader software: clientId and version are self-reported gossip claims that can flap; when an identity alternates between clients we cannot tell which machine produced a block. Runs whose start and end claims differ leave the primary cell.

## 14. Verification artefacts

Committed: `data/validators.json`, `data/plan.json` (with the seed), per-run gossip snapshots, every probe with signatures and covariates, every landing with slot, index and producer pubkey, block summaries, the spend ledger, anchor signatures. Every outcome can be re-derived with `getBlock(slot, {transactionDetails: "signatures", rewards: true, maxSupportedTransactionVersion: 1})`, served indefinitely, unlike `getSlotLeaders` (about 9 days).
