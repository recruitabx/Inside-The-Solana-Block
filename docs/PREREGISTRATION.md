# Preregistration: in-block ordering rules of selected Solana mainnet validators

Version 1.0, frozen 2026-10-30 before any live measurement. Later changes are appended as dated amendments at the end of this file and never overwrite this text.

## 1. Question and scope

For each selected validator: by what rule does it order transactions in its block, how strictly does the rule hold, and is there a rule at all. "No rule, it is noise" is an admissible answer.

Mainnet only; slots at or above `MIN_SLOT = 459653008` (first block after Alpenglow, `docs/ALPENGLOW_BOUNDARY.md`); primary evidence is our own transactions, other transactions are supplementary; Jito bundles and tips are out of scope; total fee spend is capped at 0.05 SOL (50,000,000 lamports) by `HARD_SPEND_CEILING_LAMPORTS` in `src/itb/config.py`; live window 2026-11-01 to 2026-11-02, reserve 2026-11-03, resumable runs of at most 20 minutes.

## 2. Mechanisms and hypotheses

From the pinned sources in `docs/research/`: Agave 4.3.2 and 4.4.x, Jito-Solana without a BAM session and the public part of Rakurai compute priority = reward x 10^6 / (cost + 1), reward = priority fee + 2,500 lamports per signature (the non-burned half of the base fee), cost from the requested compute-unit (CU) and loaded-accounts-data limits. The greedy scheduler pops the highest priority, pins a transaction that conflicts with an in-flight write lock to the thread holding it, lets non-conflicting batches race across workers to the record channel, schedules only while a leader bank exists, and buffers arrivals less than two slots before its window. Equal-priority ties: 4.3.2 pops the highest reused slab key, 4.4.x the oldest insertion. Firedancer 26.10.x orders by the same ratio, block order equals pack order, conflicting writers serialized, equal ratios most recently inserted first (source reading). AgaveBam and FireBAM: a BAM node orders by fee per CU in about 50 ms batches, the validator executes the received order. Harmonic clients: a hosted builder applies the operator's strategy, `fba` (50 ms batches by priority fee and tip, default), `fifo` or proprietary `mrev`, with local fallback if no block arrives by half the slot; a memo in the window's first block names the strategy.

Notation: p = P(higher reward-per-cost transaction lands first | both in one block), q = P(first-sent transaction lands first | both in one block).

| Hypothesis | Prediction | Predicted for |
|---|---|---|
| H_prio: reward per cost | p near 1, q near 0.5 when both are buffered together | all, including BAM and Harmonic `fba` |
| H_total: total priority fee | not separable from H_prio in our pairs; tested on other people's transactions (section 12) | Harmonic wording |
| H_arrival: first in, first out | q near 1, p near 0.5 | Harmonic `fifo`; any client when the pair is not buffered together |
| H_null: noise | p and q near 0.5 | worker races, unseen path effects |
| H_tie (arm E) | q_E above 0.5 on Agave 4.4.x; unpredictable on 4.3.2; below 0.5 on Firedancer | Agave family, Firedancer |
| H_race (arm D) | p_D below p_P on Agave-family clients (record-channel race); p_D about p_P on Firedancer (pack index) | Agave family vs Firedancer |
| H_overtake (arm S) | later-sent high-fee transaction first (p_S above 0.5) only under H_prio with buffering | all |
| H_strategy | p differs between FBA, MRV and FIF windows | Harmonic |

## 3. Unit of observation and outcomes

A probe is one pair of our transactions aimed at one leader window. Outcomes: landed (0, 1 or 2 transactions), same slot, leader identity (the `rewardType = "Fee"` pubkey of that block, never the targeted identity), block indices, Y_fee = 1 if the higher reward-per-cost transaction has the lower index, Y_send = 1 if the first-sent transaction has the lower index, index gap. Covariates at send: probe number, arm, assignments, send timestamp, tau = send time minus estimated start of the target's first slot, the provider's processed slot read right after the send, consecutive-window flag, per run the gossip snapshot (clientId, version) and schedule hash. From the block: slot index within the window, transaction count, total CU, strategy memo of the window's first block.

## 4. Validators

Rule: per clientId with mainnet stake, the identity with the most windows in the epoch-1073 schedule, excluding identities operated by our RPC provider (`HEL1US`, a channel confound). Eight targets by role: AgaveBam-1 (`DRpbCB`, 4.4.0-rc.1), JitoLabs-1 (`E1r4Ps`, 4.3.2), HarmonicAgave-1 (`Fd7btg`, 4.4.0-rc.1), HarmonicFiredancer-1 (`JUPiTE`, 26.10.5), Firedancer-1 (`9eGrDo`, 26.10.5), FireBAM-1 (`9jxgos`, 26.10.5), Rakurai-1 (`ana2y2`, 4.3.2), Agave-1 (`7QQGNm`, 4.3.2): eight clientIds, three version strings, satisfying at least six validators over at least three clients and three versions. Raiku (one node, 0.08%) is not selectable.

Full identities are frozen in `data/validators.json` before live data. Replacement: a target that is delinquent, absent from the next epoch's schedule, or reports a different clientId at a run's snapshot is replaced by the next identity by windows with the same clientId (same version if available); its data is kept and reported separately. A target that changes only its version string keeps its role; its data is split into (identity, version) units analysed separately.

## 5. Arms, transaction templates, randomization

Every probe transaction is legacy, one signature, four instructions: `SetComputeUnitLimit(1000)`, `SetComputeUnitPrice(price)`, `SetLoadedAccountsDataSizeLimit(4096)`, `SystemProgram.Transfer(payer -> W, 0 lamports)`. Accounts: payer (writable signer), W (writable), System and ComputeBudget programs (read-only). No memo (about 370 CU per byte). The layout without the third instruction simulates at 450 CU consumed and 235 bytes loaded; the third adds about 150 CU, leaving margin under 1,000 (checked in the pilot). W is a fresh, never-funded address derived from the seed and probe number; a 0-lamport transfer to it executes and takes a write lock. Payers come from a pool of 10 funded accounts; the two transactions of a pair always use different payers.

| Level | price (micro-lamports per CU) | priority fee | total fee | reward | priority key (Agave) |
|---|---|---|---|---|---|
| high | 5,500,000 | 5,500 | 10,500 | 8,000 | 3,434,950 |
| low | 1,000 | 1 | 5,001 | 2,501 | 1,073,851 |

Key cost = 720 (signature) + 600 (two write locks) + 1,000 (requested CU) + 8 (one 32 KiB page of loaded-data limit) = 2,328, identical within a pair, so the reward ratio of 3.2 is the contrast under any key that grows with the fee. Firedancer uses the same reward and the same 720 and 300 constants; its loaded-data term is read from `fd_pack_cost.h` at the pinned commit before the run. `meta.costUnits` of landed transactions is recorded (consumed CU, not the limit). Trade-off: a 2x contrast (priority fee 2,502) would save 2,998 lamports per pair, about 20% more probes; we keep 3.2x because the base-fee share compresses the ratio and closed schedulers (Rakurai, `mrev`) may bucket or round.

| Arm | Share | Layout | Purpose |
|---|---|---|---|
| P, conflicting contrast (primary) | 70% (85% for Rakurai-1, Agave-1) | shared W, one high, one low, one JSON-RPC batch | the scheduler must serialize the pair: fee rule vs send order |
| E, equal fee | 10% (5%) | shared W, both low | negative control: noise floor, send-position effect, tie-break |
| D, disjoint contrast | 10% (5%) | separate W per transaction, high and low | scheduler order vs execution race |
| S, spaced | 10% (5%) | shared W; low sent alone, high alone 200 ms later | known arrival order; overtaking |

Randomization: a seeded generator (`seed` in the frozen config) draws per probe number, independently: arm (by share), which payer carries the high price, and the batch position (0 or 1) of the high-price transaction; in arm E one transaction is labelled "pseudo-high" the same way. The sender never reads outcomes. Quotas: 300 probes for each of the six high-window validators; Rakurai-1 and Agave-1 take every window in the live time (planning: about 300 each). Nothing is sent after a validator's quota or the spend cap.

## 6. Timing and delivery

One send-time constant tau0, chosen in the pilot and then fixed: the pair is sent at tau0 relative to the estimated start of the target's first slot S. Rationale: an Agave-style provider forwards to the leaders of its processed slot + 1 and + 5, so a request arriving while that slot equals S - 1 reaches the target in its pre-window buffering state, both transactions buffered before scheduling starts. Pilot grid: tau0 in {-270, -170, -70} ms; the value with the highest usable fraction (section 10) wins. The slot clock fits slot against wall time from `getSlot(processed)` polled every 2 s (realized 213 ms per slot). Arm S sends the low transaction at tau0 - 200 ms and the high one at tau0.

`sendTransaction`: base64, `skipPreflight: true`, `preflightCommitment: processed`, `maxRetries: 0` (fallback `maxRetries: 2` if the pilot landing rate is below 60%). One HTTP request per probe (two for arm S) to one endpoint. Rate rules: at most 2 transactions per request, at least 2.0 s between requests, one probe per window; a window is skipped (logged) when these rules or payer availability (a payer is reused only after its last transaction is confirmed or expired) would be violated. Each run starts with an anchor transaction whose memo carries the SHA-256 of the run configuration (identities, seed, tau0, templates, gossip snapshot).

## 7. Inclusion and exclusion

Primary cell for validator v: arm P probes with both transactions in one block whose Fee-reward pubkey is v, in the targeted window. Excluded from p and q but counted and reported: one or zero transactions landed; different slots (reported as "high-fee earlier slot" rate); landed at a leader other than the target (secondary data attributed to the actual leader, reported per validator as untargeted landings, never pooled into the primary cell); slot below `MIN_SLOT` (rejected by code). A transaction with an execution error is included (its position was still decided by the leader) and flagged. Pilot probes never enter the confirmatory analysis.

## 8. Estimands, statistics, sample size, stopping

Per validator, from the primary cell: p and q with exact Clopper-Pearson 95% intervals, pi = 2p - 1 reported as "share of pairs decided by fee" (a fee-deciding fraction plus coin flips), and the 2 x 2 table of Y_fee by send position of the high transaction. Tests: exact two-sided binomial tests of p = 0.5 and q = 0.5, Holm-corrected across the eight validators within each family, family alpha 0.05. One model per validator: logistic regression of "transaction A first" on (A is high) and (A sent first), as a sensitivity check. One probe per window and one window per block, so probes are independent at block level; probes sharing a block are kept and noted.

Minimum usable N in the primary cell: 100 per validator. Exact binomial calculation at Holm alpha 0.05/8 = 0.00625, two-sided: N = 77 gives power 0.80 and N = 100 gives 0.88 against p = 0.70 (0.99 against 0.75); the equivalence test (90% exact interval inside [0.35, 0.65]) has power 0.81 at N = 100 when p = 0.5. Secondary arms are analysed pooled across validators and by client family; per-validator secondary numbers are descriptive.

Stopping: fixed quotas, no interim look at ordering outcomes; the only data-dependent choices are tau0, the retry fallback and the arm-share fallback, all from operational rates in the pilot. A validator short of N = 100 at the end of the live window is reported as insufficient data.

## 9. Decision rules

Per validator after Holm correction, with L_p the 95% lower bound:

- "Fee rule holds, strict": p = 0.5 rejected and L_p at least 0.90; "strong": L_p at least 0.75; "partial": rejected with L_p below 0.75. Reported as "fee rule holds with strictness p [interval], pi".
- "Send-order rule holds": the same thresholds on q.
- Both rejected: "mixed", explained by the 2 x 2 table.
- "No detectable rule": only if the 90% intervals of both p and q lie inside [0.35, 0.65].
- Otherwise "insufficient data", with the N reached.

Secondary verdicts (H_tie, H_race, H_overtake, H_strategy) use the same thresholds on pooled estimates and are labelled secondary.

## 10. Controls and pilot acceptance criteria

Negative control: arm E. Positive controls on localnet (Agave 4.3.2 test validator, single leader): the recorded arrival-order run (34 of 34 first-sent-first with spaced sends) replayed through the same analysis code, and a priority known answer. On that node arrival order dominates because the local RPC forwards batched transactions one by one, so the known answer is produced by injecting a conflicting high/low pair in one QUIC burst (both streams written before one flush, ideally one datagram) straight into the local TPU, 40 pairs, expecting the high one first; time-boxed to three hours, otherwise disclosed as not achieved.

Criteria, all numeric, none looking at mainnet ordering outcomes:

1. Synthetic data with planted rules (p in {1, 0.75, 0.5}, q in {1, 0.5}) at N = 100, 1,000 replicates: the planted value lies inside the 95% interval in at least 94% of replicates; false "rule holds" verdicts under the null across eight simulated validators at most 5%; power against p = 0.70 at least 0.80.
2. Localnet arrival-order replay yields q = 34/34 and "send-order rule holds".
3. Localnet priority answer: at least 36 of 40 high-first, or disclosed.
4. Mainnet pilot, 12 arm-P probes per validator (96, 4 per tau0 value): `simulateTransaction` of both templates reports at most 700 CU consumed and at most 4,096 bytes loaded; landing rate at least 80%; HTTP 429 rate below 5%; ledger spend equals the sum of `meta.fee` exactly; usable fraction u (both transactions in one block at the targeted leader, over probes sent) at least 0.48, which projects 300 x 0.70 x 0.48 = 101 usable primary probes per high-window validator. A failing criterion allows one re-pilot of the same size after adjusting tau0 or retries. Fallback if u stays below 0.48: shares become 85/5/5/5 for all validators (enough for u at least 0.40); validators still projected below 100 are pre-declared at risk of insufficient data.

## 11. Budget

Per transaction: 5,000 base + priority fee. Pair P, D, S = 15,501 lamports; pair E = 10,002; share-weighted mean 14,951 (high-window validators) and 15,226 (Rakurai-1, Agave-1). Pilot at most 2 x 96 x 15,501 = 2,976,192. Operations: 10 payer fundings, 10 drains, up to 60 anchors, 5,000 each: 400,000. Main run: 1,800 x 14,951 + 600 x 15,226 = 36,047,400. Total fees at most 39,423,592 lamports, 10.6 million under the cap; absolute maximum 3,118 probes at the mean cost. Payer rent deposits (10 x 890,880 = 8,908,800) are recoverable, not spend; even counted against funding the total is 48,332,392, under 0.05 SOL. Enforcement: `SpendLedger` books the maximum fee of every transaction at send time, replaces it by `meta.fee` on confirmation, and refuses any send that would push the booked total over the cap.

## 12. Secondary analyses without spend

From the same blocks (`meta.costUnits` and fee fields of all transactions): (a) reward per cost against block index, Spearman rho per block and validator; (b) the CU-limit versus total-fee crossover: among adjacent pairs of other people's transactions where one has the higher total priority fee and the other the higher reward per cost, the share ordered by each key; (c) index gap and slot index of our pairs by validator.

## 13. What we do not separate

- First in, first out by true arrival at the leader from random order: with both transactions in one request we do not observe arrival; q measures batch position. Arm S narrows this for one ordering only.
- An external builder (BAM node, Harmonic builder) from the validator's own scheduler: we observe the composite; the Harmonic memo partly labels it.
- The RPC provider's routing (node choice, staked or unstaked connections, duplicates, internal reordering) from the leader's behaviour.
- Co-presence of the two transactions in the scheduler buffer: p measures the rule as experienced by a sender using one RPC request, a lower bound on the strictness of a priority rule under co-presence.
- Leader software: clientId and version are self-reported in gossip and can flip (BAM session state); snapshots are committed per run because they cannot be re-queried later.

## 14. Verification artefacts

Committed: `data/validators.json`, the seed, per-run gossip snapshots and schedule hashes, every probe with signatures and covariates, every landing with slot, index and leader pubkey, the spend ledger, anchor signatures. Every outcome can be re-derived with `getBlock(slot, {transactionDetails: "signatures", rewards: true, maxSupportedTransactionVersion: 1})`, served indefinitely, unlike `getSlotLeaders` (about 9 days).
