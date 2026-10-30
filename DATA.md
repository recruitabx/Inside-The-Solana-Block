# Data index

All files are JSON Lines (one JSON object per line) unless stated otherwise. Nothing under
`data/` is edited after it is written: runs append, the collector rewrites only its own
`*.landed.jsonl` outputs (idempotently) and appends to `*.blocks.jsonl`, and later corrections are new files.

| Path | Written by | What it holds |
|---|---|---|
| `data/validators.json` | `scripts/freeze_targets.py` | Frozen target identities by role, with clientId, version, window counts and replacement candidates |
| `data/plan.json` | `scripts/make_plan.py` | Frozen run configuration: seed, targets with arm shares and quotas, fee levels, CU and loaded-data limits, timing constant, pilot sizes, `planned_fees` (the plan is refused above 46,000,000 lamports) |
| `data/selection/leader_schedule_epoch<N>.json` | `scripts/freeze_targets.py` | Leader schedule of the ranking epoch the selection was computed from |
| `data/selection/snapshots/` | `itb snapshot --out-dir`, `scripts/freeze_targets.py --snapshot-now` | Gossip snapshots over at least 18 hours that decide eligibility (same clientId and version in every one) |
| `data/snapshots/clients_<slot>.json` | runner (start of every run), `itb snapshot` | Self-reported clientId and version of every staked node at that slot, with stake |
| `data/snapshots/clients_<slot>_end.json` | runner (end of every run) | The same, taken when the run ended (`_end` only if a start snapshot has that slot); a target whose claim differs from the start leaves the primary cell |
| `data/raw/<run>.sent.jsonl` | `itb run --live` | Send log: one `run_start`, one `probe` per pair, `window_skipped`, one `run_end`. Pilot runs have `pilot` in the run id (`<time>-live-pilot-<id>`) |
| `data/raw/<run>.landed.jsonl` | `itb collect` | One `landed` or `not_landed` record per sent transaction |
| `data/raw/<run>.blocks.jsonl` | `itb collect` | One compact `block` record per slot where one of our transactions landed and per first slot of a targeted Harmonic window (see below); appended, slots already summarized are skipped |
| `results/` | `itb analyze` | `verdicts.json` (units, verdicts, secondary tables), `verdicts.csv`, `table_2x2.csv`, `logit.csv`, `secondary.json`. `itb analyze` refuses main-phase data without `--final` |
| (stdout) | `itb pilot-report` | Operational pilot metrics and the tau0 choice from `data/raw/*pilot*.sent.jsonl`; never ordering outcomes |
| `data/dryrun/<run>.sent.jsonl` | `itb run` (default) | Same format as live send logs, nothing was sent |
| `data/ledger/spend.jsonl` | spend ledger | `reserve` before every send, `settle` with the on-chain fee, `release` for expired transactions |
| `data/ledger/operations.jsonl` | `itb fund/drain/anchor` | Funding, draining and anchor transactions |
| `data/accounts.json` | `itb fund` | Public keys of the funding wallet and the derived fee payers (for `itb audit`) |
| `data/calibration/` | `scripts/localnet_calibration.py` | Localnet known-answer runs (see `docs/CALIBRATION.md`) |

## `probe` record (send log)

| Field | Meaning |
|---|---|
| `probe_id`, `run_id`, `phase` | identifiers; `phase` is `pilot` or `main` (pilot data never enters the confirmatory analysis) |
| `arm`, `condition` | `P` conflicting contrast, `E` equal fee, `D` disjoint contrast, `S` spaced (two requests `gap_ms` apart; `condition` repeats `arm`) |
| `rng_key`, `s_low_first` | `"<seed>:<window first slot>:<target identity>"`, the seed of the generator that drew arm and assignments for this window; arm S only: `true` if the low-fee transaction was sent first (random, 50/50), else `null` |
| `target_leader`, `target_role` | identity whose window the pair was aimed at |
| `target_client_id`, `target_version` | the target's gossip claim in the run's start snapshot |
| `window_first_slot`, `window_last_slot` | the targeted leader window |
| `tau0_ms`, `planned_send_time`, `estimated_window_start_time` | send timing relative to the estimated start of the window |
| `txs[]` | per transaction: `signature`, `payer`, `cu_limit`, `cu_price` (micro-lamports per CU), `loaded_limit`, `shared_account` (W), `max_fee`, `label` (`high`, `low`, `pseudo-high`), `send_pos` (0 = sent first) |
| `hi_idx`, `hi_pos`, `send_order` | randomized assignment: which transaction is high, its position in the request (arm S: its position in the order of the two requests) |
| `send_results`, `send_times` | provider answer per transaction, request start and end times (unix seconds) |
| `observed_slot_after_send` | provider's processed slot read right after sending (clock check) |

## `landed` record (collector)

`signature`, `probe_id`, `slot`, `tx_index` (position in `getBlock` signatures), `block_tx_count`,
`leader` (pubkey of the block's `Fee` reward, i.e. the producer), `leader_client_id`,
`leader_version` (from the run's start snapshot), `leader_client_id_end`, `leader_version_end`,
`leader_claim_changed_in_run` (producer's claim at the run's end snapshot, and whether it differs; only if the run
has an end snapshot), `fee`, `cost_units`, `cu_consumed`, `err` (execution error from `meta.err`), `status_err`, `block_time`.

## `run_start` and `run_end` records

`run_start`: `run_id`, `phase`, `plan_sha256`, `snapshot_sha256`, `config_sha256`, `snapshot` (path), `snapshot_slot`,
`quota`, `already_sent`, `targets_client_now`, `targets_version_now` (claims at the start), `ledger`, `anchor`.
`run_end`: `probes`, `sent_per_target`, `ledger`, and from the second gossip snapshot `snapshot_end` (path),
`snapshot_end_slot`, `targets_client_end`, `targets_version_end`, `claim_changed` (per target, start claim differs from
end claim); `snapshot_end_error` instead if the snapshot failed. A run without a `run_end` has an unknown end claim:
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
