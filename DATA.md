# Data index

All files are JSON Lines (one JSON object per line) unless stated otherwise. Nothing under
`data/` is edited after it is written: runs append, the collector rewrites only its own
`*.landed.jsonl` outputs (idempotently), and later corrections are new files.

| Path | Written by | What it holds |
|---|---|---|
| `data/validators.json` | `scripts/freeze_targets.py` | Frozen target identities by role, with clientId, version, window counts and replacement candidates |
| `data/plan.json` | `scripts/make_plan.py` | Frozen run configuration: seed, targets, arm shares, fee levels, CU and loaded-data limits, timing constant |
| `data/selection/` | `scripts/freeze_targets.py` | Leader schedule and gossip snapshot the selection was computed from |
| `data/snapshots/clients_<slot>.json` | runner (every run), `itb snapshot` | Self-reported clientId and version of every staked node at that slot, with stake |
| `data/raw/<run>.sent.jsonl` | `itb run --live` | Send log: one `run_start`, one `probe` per pair, `window_skipped`, one `run_end` |
| `data/raw/<run>.landed.jsonl` | `itb collect` | One `landed` or `not_landed` record per sent transaction |
| `data/dryrun/<run>.sent.jsonl` | `itb run` (default) | Same format as live send logs, nothing was sent |
| `data/ledger/spend.jsonl` | spend ledger | `reserve` before every send, `settle` with the on-chain fee, `release` for expired transactions |
| `data/ledger/operations.jsonl` | `itb fund/drain/anchor` | Funding, draining and anchor transactions |
| `data/accounts.json` | `itb fund` | Public keys of the funding wallet and the derived fee payers (for `itb audit`) |
| `data/calibration/` | `scripts/localnet_calibration.py` | Localnet known-answer runs (see `docs/CALIBRATION.md`) |

## `probe` record (send log)

| Field | Meaning |
|---|---|
| `probe_id`, `run_id`, `phase` | identifiers; `phase` is `pilot` or `main` (pilot data never enters the confirmatory analysis) |
| `arm` | `P` conflicting contrast, `E` equal fee, `D` disjoint contrast, `S` spaced (low first, high 200 ms later) |
| `target_leader`, `target_role` | identity whose window the pair was aimed at |
| `window_first_slot`, `window_last_slot` | the targeted leader window |
| `tau0_ms`, `planned_send_time`, `estimated_window_start_time` | send timing relative to the estimated start of the window |
| `txs[]` | per transaction: `signature`, `payer`, `cu_limit`, `cu_price` (micro-lamports per CU), `loaded_limit`, `shared_account` (W), `max_fee`, `label` (`high`, `low`, `pseudo-high`), `send_pos` (0 = sent first) |
| `hi_idx`, `hi_pos`, `send_order` | randomized assignment: which transaction is high, its position in the request |
| `send_results`, `send_times` | provider answer per transaction, request start and end times (unix seconds) |
| `observed_slot_after_send` | provider's processed slot read right after sending (clock check) |

## `landed` record (collector)

`signature`, `probe_id`, `slot`, `tx_index` (position in `getBlock` signatures), `block_tx_count`,
`leader` (pubkey of the block's `Fee` reward, i.e. the producer), `leader_client_id`,
`leader_version` (from the run's snapshot), `fee`, `cost_units`, `cu_consumed`, `err`, `block_time`.

## Verify any record yourself

```bash
curl -s https://api.mainnet-beta.solana.com -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"getBlock","params":[SLOT,{"transactionDetails":"signatures","rewards":true,"maxSupportedTransactionVersion":1}]}'
```

The signature must appear at `tx_index` of `result.signatures`, and the `Fee` entry of `result.rewards`
must be the recorded `leader`. `docker compose run --rm verify` does this for a random sample.
