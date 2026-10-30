# Data index

All files are JSON Lines (one JSON object per line) unless stated otherwise. Nothing under
`data/` is edited after it is written: runs append, the collector rewrites only its own
`*.landed.jsonl` outputs (idempotently) and appends to `*.blocks.jsonl`, and later corrections are new files.

| Path | Written by | What it holds |
|---|---|---|
| `data/validators.json` | `scripts/freeze_targets.py` | Frozen targets by role: clientId, version at freeze (a covariate, not part of the eligibility), window counts and the 3 ordered replacement candidates (same clientId). At least 6 targets, 3 clientIds and 3 version strings, else nothing is written |
| `data/plan.json` | `scripts/make_plan.py` | Frozen run configuration: seed, targets as ROLES (`role`, `clientId`, `identity` = primary, `candidates` = ordered [primary, replacement 1, 2, 3], arm shares, `quota_per_target` per role), fee levels, CU and loaded-data limits, timing constant, pilot sizes, `planned_fees` (`fee_room`, `pilot_spent`, `main_run_fees`, `operations`, `planned_fee_total`, `scaled_to_room`, `projected_usable`, `roles_below_100_usable`). The plan is refused if planned fees exceed the funded fee room (`--fee-room`) unless `--scale-to-room` scales the quotas down |
| `data/selection/leader_schedule_epoch<N>.json` | `scripts/freeze_targets.py` | Leader schedule of the ranking epoch the selection was computed from |
| `data/selection/snapshots/` | `itb snapshot --out-dir`, `scripts/freeze_targets.py --snapshot-now` | Gossip snapshots over at least 18 hours that decide eligibility (same clientId in every one of at least 4 spanning at least 18 hours) |
| `data/snapshots/clients_<slot>.json` | runner (start of every run), `itb snapshot` | Self-reported clientId and version of every staked node at that slot, with stake and `delinquent` (true unless the node has a vote account in `getVoteAccounts` current with stake) |
| `data/snapshots/clients_<slot>_end.json` | runner (end of every run) | The same, taken when the run ended (`_end` only if a start snapshot has that slot); a target whose clientId differs from the start leaves the primary cell (a changed version string does not) |
| `data/raw/<run>.sent.jsonl` | `itb run --live` | Send log: one `run_start`, one `probe` per pair, `window_skipped`, one `run_end`. Pilot runs have `pilot` in the run id (`<time>-live-pilot-<id>`) |
| `data/raw/<run>.landed.jsonl` | `itb collect` | One `landed` or `not_landed` record per sent transaction |
| `data/raw/<run>.blocks.jsonl` | `itb collect` | One compact `block` record per slot where one of our transactions landed and per first slot of a targeted Harmonic window (see below); appended, slots already summarized are skipped |
| `results/` | `itb analyze` | `verdicts.json` (units = (target_role, identity, clientId), verdicts, `fifo`, `claim_end_unknown`, secondary tables labelled "secondary, descriptive"), `verdicts.csv`, `version_split.csv` (descriptive split of each unit by version, no tests), `claim_end_unknown.csv`, `table_2x2.csv`, `logit.csv`, `secondary.json`. `itb analyze --final` analyses phase `main` only (pilot data and anything marked synthetic are excluded); without `--final` ONLY synthetic data are analysed and every real probe is refused |
| (stdout) | `itb pilot-report` | Operational pilot metrics and the tau0 choice from `data/raw/*pilot*.sent.jsonl`; never ordering outcomes. Also the `simulateTransaction` check of both probe templates (`--no-simulate` skips it) |
| (stdout) | `python scripts/acceptance.py` (`docker compose run --rm acceptance`) | PASS or FAIL per acceptance criterion: synthetic recovery (coverage, false rule, power), calibration controls through the analysis' verdict function, template simulation |
| `data/dryrun/<run>.sent.jsonl` | `itb run` (default) | Same format as live send logs, nothing was sent |
| `data/ledger/spend.jsonl` | spend ledger | `reserve` before every send (`tag`: `pilot:<probe id>` for pilot probes, `<probe id>` for main probes, `anchor:<run id>`), `settle` with the on-chain fee, `release` for expired transactions. `itb.spend.settled_total(path, tag_prefix)` sums the settled fees (`make_plan.py --pilot-spent ledger` uses prefix `pilot:`) |
| `data/ledger/operations.jsonl` | `itb fund/drain/anchor` | Funding, draining and anchor transactions |
| `data/accounts.json` | `itb fund` | Public keys of the funding wallet and the derived fee payers (for `itb audit`) |
| `data/calibration/` | `scripts/localnet_calibration.py` | Localnet known-answer runs (see `docs/CALIBRATION.md`) |

## `probe` record (send log)

| Field | Meaning |
|---|---|
| `probe_id`, `run_id`, `phase` | identifiers; `phase` is `pilot` or `main` (pilot data never enters the confirmatory analysis) |
| `arm`, `condition` | `P` conflicting contrast, `E` equal fee, `D` disjoint contrast, `S` spaced (two requests `gap_ms` apart; `condition` repeats `arm`) |
| `rng_key`, `s_low_first` | `"<seed>:<window first slot>:<target identity>"`, the seed of the generator that drew arm and assignments for this window; arm S only: `true` if the low-fee transaction was sent first (random, 50/50), else `null` |
| `target_leader`, `target_role` | identity whose window the pair was aimed at (the identity the role was assigned in this run) and its role; quotas and counts are per role |
| `target_client_id`, `target_version` | the target's gossip claim in the run's start snapshot (clientId defines the unit, version is a covariate) |
| `window_first_slot`, `window_last_slot` | the targeted leader window |
| `tau0_ms`, `planned_send_time`, `estimated_window_start_time` | send timing relative to the estimated start of the window |
| `txs[]` | per transaction: `signature`, `payer`, `cu_limit`, `cu_price` (micro-lamports per CU), `loaded_limit`, `shared_account` (W), `max_fee`, `label` (`high`, `low`, `pseudo-high`), `send_pos` (0 = sent first) |
| `hi_idx`, `hi_pos`, `send_order` | randomized assignment: which transaction is high, its position in the request (arm S: its position in the order of the two requests) |
| `send_results`, `send_times` | provider answer per transaction, request start and end times (unix seconds); arm S: the second request starts `gap_s` after the START of the first one |
| `synthetic` | only in synthetic test data (written to `synthetic-*` files); such records and files never count towards quotas and are excluded by `itb analyze --final` |
| `observed_slot_after_send` | provider's processed slot read right after sending (clock check) |

## `landed` record (collector)

`signature`, `probe_id`, `slot`, `tx_index` (position in `getBlock` signatures), `block_tx_count`,
`leader` (pubkey of the block's `Fee` reward, i.e. the producer), `leader_client_id`,
`leader_version` (from the run's start snapshot), `leader_client_id_end`, `leader_version_end`,
`leader_claim_changed_in_run` (producer's claim at the run's end snapshot, and whether it differs; only if the run
has an end snapshot), `fee`, `cost_units`, `cu_consumed`, `err` (execution error from `meta.err`), `status_err`, `block_time`.

## `run_start` and `run_end` records

`run_start`: `run_id`, `phase`, `plan_sha256`, `snapshot_sha256`, `config_sha256`, `snapshot` (path), `snapshot_slot`,
`quota` and `already_sent` (per role), `role_assignment` (per role: chosen `identity`, `candidate_index` in the plan's ordered list, `clientId`, `version`, `rejected` candidates with the reason, `skipped` = "no valid candidate" if the role sits out this run; a candidate is valid if it reports the role's clientId in the start snapshot and is not delinquent), `targets_client_now`, `targets_version_now` (claims of the assigned identities at the start), `ledger`, `anchor`.
`run_end` (written in every case, also after an exception): `probes`, `sent_per_role`, `error` (only after an exception), `ledger`, and from the second gossip snapshot `snapshot_end` (path),
`snapshot_end_slot`, `targets_client_end`, `targets_version_end`, `claim_changed` (per target, start (clientId, version) differs from
end), `client_changed` (per target, clientId differs: the probes leave the primary cell); `snapshot_end_error` instead if the snapshot failed. A run without a `run_end` has an unknown end claim:
the analysis keeps its probes and counts them as `claim_end_unknown`.

## `block` record (`data/raw/<run>.blocks.jsonl`)

`slot`, `producer` (Fee reward), `tx_count`, `cu_consumed_total` (sum of `computeUnitsConsumed`), `block_time`,
`strategy` (`FBA`, `MRV`, `FIF` if a memo whose whole text is that string is in the block, else `null`; only meaningful for the
first block of a Harmonic window) and `strategy_tx_index`, `sampled`. A skipped slot has `skipped: true`. For slots with
`slot % 10 == 0` (`sampled: true`) also `tx_cols` and `tx_rows`, one row per transaction: `index`, `version`, `vote`,
`jito_tip`, `nsig`, `fee`, `cost_units`, `cu_consumed`, `requested_cu_limit` (SetComputeUnitLimit, v1 config, or the
runtime default of 200,000 per non-ComputeBudget instruction capped at 1,400,000, an approximation).

## Verify any record yourself

```bash
curl -s https://api.mainnet-beta.solana.com -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"getBlock","params":[SLOT,{"transactionDetails":"signatures","rewards":true,"maxSupportedTransactionVersion":1}]}'
```

The signature must appear at `tx_index` of `result.signatures`, and the `Fee` entry of `result.rewards`
must be the recorded `leader`. `docker compose run --rm verify` does this for a random sample.
