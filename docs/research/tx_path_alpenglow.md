# Transaction path and block production under Alpenglow (Solana mainnet, 2026-10-30)

Scope: mechanisms and read-only measurements only; no experiment design. Pinned source: Agave v4.3.2, commit `a203300045b405f86c9c84308b2eae76af69ac3b` (verified: `git rev-parse HEAD` and `git describe --tags` in the checkout gave this hash and `v4.3.2`). All `path:LINE` are relative to that checkout.

Labels. "verified: id" = command in Table V. "docs: Wn" = from docs, URL in Table W, fetched 2026-10-30 ("excerpt" = only the search excerpt was read). "src" = `path:LINE` => `quote`, graded in Citation check. "CBD" = cannot be determined from here.

Table V. `S=/tmp/claude-0/-home-user-Inside-The-Solana-Block/8de50ae6-1ba8-5ff6-ac11-6a0da13bc5fe/scratchpad`; run `cd $S && python3 -I rd/<script>`; output in `$S/out/<same stem>.txt`.
- t0: t0_smoke.py (getSlot, getVersion on both endpoints). a1: a1_leaders.py. a2: a2_slotdur.py. a3: a3_skip.py, a3b_partial.py (output a3b_partial_boundary.txt), a3c_recent.py, a3d_sanity.py. a4: a4_block.py, a4b_v1_boundary.py. a5: a5_features.py. d1: d1_latency.py. d2: d2_schedule.py.

Table W (host paths; all https). W1 solana.com/upgrades/alpenglow. W2 solana.com/upgrades/reduced-slot-times (excerpt). W3 solana.com/upgrades/larger-transaction-sizes. W4 github.com/solana-foundation/solana-improvement-documents/blob/main/proposals/0385-transaction-v1.md (excerpt). W5 helius.dev/docs/sending-transactions/overview. W6 helius.dev/docs/sending-transactions/send-manually. W7 helius.dev/pricing.md (page header: last-updated 2025-01-20). W8 helius.dev/docs/billing/rate-limits (excerpt). W9 helius.dev/docs/sending-transactions/sender (excerpt). W10 helius.dev/docs/api-reference/rpc/http/sendtransaction. W11 docs.anza.xyz/validator/tpu (excerpt). W12 solana.com/docs/defi/stake-weighted-qos (excerpt). W13 raw.githubusercontent.com/paritytech/jsonrpc/v18.0.0/core/src/io.rs (saved as `$S/web/jsonrpc_io.rs`). W14 helius.dev/docs/sending-transactions/optimizing-transactions (excerpt). W15 docs.rs/solana-clock/3.2.0/solana_clock/constant.HOLD_TRANSACTIONS_SLOT_OFFSET.html.

RPC_URL budget: about 90 calls (append-only counter `$S/out/rpc_url_calls.bytes`, seeded with 85 for calls made before the counter was fixed). Heavy sampling used api.mainnet-beta.solana.com ("public"). Both endpoints report `solana-core: 4.3.2` (verified: t0).

## 0. Findings

1. Leader windows are 4 slots, 4-aligned; one identity can hold 2 or 3 windows back to back (runs of 8, 12). verified: a1, d2.
2. Nominal slot time is 200 ms (since slot 454,896,000); realized 212.7 to 215.8 ms, similar before and after Alpenglow. verified: a2, a5.
3. Recent skip rate about 0.11% (0.100% of windows fully skipped); skips are window-granular; windows can end early (`PPP.`, `P...`) and in sampled ranges never started late. verified: a3.
4. Votes left the blocks: 649 of 1051 txs were votes at slot 459652999, 0 of 1701 at 459653008. verified: a4.
5. getBlock has no entries field; 16 sampled blocks: 37% v1, 38% v0, 25% legacy transactions. verified: a4.
6. A window starts when its leader sees ParentReady, not at a wall-clock instant; early start (fast leader handover) is inactive on mainnet. src, verified: a5.
7. Helius Free: 1 sendTransaction/s, "Staked Connections: No" on the pricing page; the real route of a Free send is CBD.
8. Agave default: send to the leaders of tip+1 and tip+5, retry every 2 s until blockhash expiry unless maxRetries says otherwise. src.
9. No stage after HTTP parsing guarantees arrival order, and the leader orders by priority, not arrival. src; Helius internals CBD.
10. getSlot round trip p50 132 ms (Helius), 145 ms (public); Helius processed slot within 0 to 2 slots of the freshest seen. verified: d1.

## A. Alpenglow measured with read-only RPC

### A1. Leader window length (verified: a1, d2)

`getSlotLeaders`, 3000 slots per range, inner runs of one leader (run length: count; all run starts were slot mod 4 = 0; no aligned 4-slot group had two leaders):
- recent 463315522..463318521: {4: 729, 8: 10}.
- about 400k slots earlier: {4: 731, 8: 9}.
- after boundary 459653008..459656007: {4: 736, 8: 6}.
- before boundary 459650000..459652999: {4: 733, 8: 6, 12: 1}.

Whole epoch 1072, `getLeaderSchedule` (650 identities, 432000 slots): {4: 105670, 8: 1126, 12: 26}; 0 mismatches against `getSlotLeaders` on 2000 slots. Runs of 8 or 12 are consecutive windows of one identity. Constant: `leader-schedule/src/lib.rs:20` => `NUM_CONSECUTIVE_LEADER_SLOTS: NonZeroUsize = NonZeroUsize::new(4)`. The epoch 1063 schedule is no longer served (verified: a1).

### A2. Slot duration (verified: a2, a5)

20 `getBlockTime` samples per 100k-slot span, endpoint slope (OLS agrees within 0.001):
- before, 459552999..459652996: 4.6338 slots/s, 215.8 ms.
- after, first span 459653008..459753005: 4.7018, 212.7 ms.
- after, latest span 463217616..463317613: 4.6852, 213.4 ms.
- whole post span 459653008..463317616: 4.7019, 212.7 ms.

Nominal: feature `iBRLjhJnkmDZgNoZRDMW11d8ZV7HvsL3vAyRjZB5npW` activated at slot 454,464,000 = epoch 1052 (verified: a5, 454464000/432000 = 1052), effective one epoch later at 454,896,000: `runtime/src/slot_params.rs:172` => `ns_per_slot: 200_000_000,` and `runtime/src/slot_params.rs:324` => `A gate that activates in epoch E is effective starting at the first slot`. docs: W2 gives the same date. Realized is 6 to 8% above nominal on both sides of the boundary. blockTime is whole seconds, so neighbouring slots share it (verified: a4, slots 463314508 and 509 both 1793369568).

### A3. Skip rate (verified: a3)

- TowerBFT, 459628000..459652999: 40 of 25000 skipped, 0.160%.
- first 25k after 459653008: 348 of 25000, 1.392%.
- recent 463226145..463326145: 111 of 100001, 0.111%. Window patterns (P block, . skipped): `PPPP` 24969, `....` 25, `P...` 3, `PPP.` 2.
- first 50k after the switch: 98 fully skipped windows of about 12,500 and 18 partial, all prefix style (`PPP.`, `PP..`, `P...`). The 50k before it: one `P...`, one `..PP`.
- skipped slots by position in the window, recent 25,001 slots: 5, 6, 6, 6 of about 6250 each.

### A4. Block structure today (verified: a4)

`getBlock` keys: `blockHeight, blockTime, blockhash, parentSlot, previousBlockhash, rewards, transactions`; no entries, tick or footer field. Transaction keys `meta, transaction, version`; meta has `computeUnitsConsumed, costUnits`. Without `maxSupportedTransactionVersion: 1` (also with 0) the call fails with code -32015; `signatures` mode needs no parameter.

Four consecutive blocks 463314508..511: 1106, 1562, 1125, 1010 txs (19.4M to 44.3M CU consumed). Ten blocks spread over 400k slots: 169 to 824 txs, median 334.5. Pooled 16 blocks (9045 txs): legacy 2217 (24.5%), v0 3453 (38.2%), v1 3375 (37.3%). Block 459652999 (1051 txs, 649 votes) is followed by 459653008 (parent 459652999; 459653000..007 skipped; 1701 txs, 0 votes).

Version 1 is SIMD-0385 (docs: W3, W4), feature `txv1aq4pp281K9um3tnPgkfX8UqtFT6wcVW3hNezGLL` (`feature-set/src/lib.rs:2600` => `SIMD-0385: Transaction V1`), active since slot 447,120,000 = epoch 1035 (verified: a5; docs: W3 says 2026-09-15). Changes (docs: W3, W4): first byte 0x81, signatures last; a config mask carries priority fee (total lamports), compute-unit limit, loaded-accounts data limit, heap size, so ComputeBudget instructions become no-ops and unset limits default to 0; no address lookup tables, 64 inline addresses; 4096-byte limit (SIMD-0296; base64 needed above 1232). A v1 message in getBlock adds `transactionConfig` (verified: a4b: keys `accountKeys, header, instructions, recentBlockhash, transactionConfig`).

## B. Alpenglow mechanics relevant to block production

All src at the pinned commit.
- Window and slot time: 4 slots (A1). Per-block deadline is set from the bank's slot time: `core/src/block_creation_loop.rs:457` => `.saturating_mul((leader_slot_index(slot) as u32).saturating_add(1))`.
- Start: Votor emits ProduceWindow when ParentReady holds for our first slot and starts the timer then: `votor/src/consensus_pool_service.rs:469` => `block_timer: Instant::now(),`. ParentReady = parent notarized (or notar-fallback) and the slots between skip-certified: `votor/src/consensus_pool/parent_ready_tracker.rs:7` => `(non-inclusive) are skip-certified.`. Start time follows consensus progress. Closing a block also waits for it: `core/src/block_creation_loop.rs:698` => `Don't timeout until we've received ParentReady.`
- Stop: block k closes at `ns_per_slot*(k+1) - 6 ms - 50 ms` after the timer (`core/src/block_creation_loop.rs:78` => `TIME_TO_COMPLETE_BLOCK_BROADCAST: Duration = Duration::from_millis(6)`; `core/src/block_creation_loop.rs:84` => `BLOCK_PRODUCTION_BUFFER: Duration = Duration::from_millis(50)`), i.e. 144, 344, 544, 744 ms at 200 ms. Blocks are closed by the clock, not when full, with one "alpentick" and a footer: `core/src/block_creation_loop.rs:833` => `w_poh_recorder.tick_alpenglow(max_tick_height, footer)?;`. Inference (arithmetic on verified: a2 and these constants): 4 x 213.4 = 853.6 ms per window less 744 ms leaves about 110 ms for notarization and the next ParentReady.
- Network skip: first-shred wait is `votor/src/common.rs:29` => `DELTA_TIMEOUT: Duration = Duration::from_millis(400)` plus `votor/src/event_handler.rs:248` => `let delta_first_fec_set = delta_block;` (200 ms), so a silent leader is declared crashed 600 ms after ParentReady; later slots time out every 200 ms. A timeout on a slot we have not voted for makes us vote skip for every slot of that window we have not yet voted on: `votor/src/event_handler.rs:896` => `for s in start..=last_of_consecutive_leader_slots(slot) {`. This fits the prefix-only partial windows of A3.
- Missed window: if the window is already skip-certified the leader does not produce: `votor/src/consensus_pool_service.rs:452` => `has already been certified, skipping production`.
- Early start (fast leader handover, optimistic parent) is gated: `core/src/replay_stage.rs:1643` => `bank.feature_set.snapshot().alpenglow_fast_leader_handover`; feature `FLHoAWBDjNh6zwmJ5i1NKK4KyD8otAiv7XxvmnFnVnKH` (`feature-set/src/lib.rs:2619` => `SIMD-0326: Alpenglow fast leader handover`) has no account on mainnet (verified: a5); docs: W1 places it in Agave v4.4.
- Votor vs Rotor: Votor is live, Rotor (replacing Turbine) is unscheduled; finality about 150 ms and `confirmed` equals `finalized` (docs: W1).
- Votes: no longer transactions; validators exchange votes directly and certificates appear in the block footer (docs: W1). Footer carries producer time: `entry/src/block_component.rs:72` => `Producer Time Nanos`. The leader's clock sets it (`core/src/block_creation_loop.rs:545` => `let mut block_producer_time_nanos = SystemTime::now()`), bounded to twice the elapsed slot time above the parent (`runtime/src/block_component_processor.rs:760` => `.saturating_mul(2)`). RPC shows only whole-second `blockTime` and no footer (verified: a4).
- Migration: TowerBFT ran the first 5000 slots of epoch 1064; Alpenglow took over from 459,653,000 (docs: W1); first vote-free block is 459653008 (verified: a4).

## C. Transaction path from our backend to the leader

### C1. Agave RPC to the leader (src)

1. `send_transaction` (`rpc/src/rpc.rs`): `skipPreflight=true` forces processed commitment and skips signature check, health check and simulation: `rpc/src/rpc.rs:3917` => `Some(CommitmentConfig::processed())`, `rpc/src/rpc.rs:3951` => `if !skip_preflight {`, `rpc/src/rpc.rs:3977` => `preflight_bank.simulate_transaction(&transaction, false)`. Unknown blockhash plus skipped preflight gets an invented expiry: `rpc/src/rpc.rs:3942` => `(skip_preflight && last_valid_block_height == 0)`. The call returns once enqueued: `rpc/src/rpc.rs:2782` => `.send(transaction_info)`.
2. Defaults of the send-transaction-service (STS): forward count `send-transaction-service/src/send_transaction_service.rs:39` => `DEFAULT_LEADER_FORWARD_COUNT: u64 = 2;`, retry period `send-transaction-service/src/send_transaction_service.rs:36` => `DEFAULT_RETRY_RATE_MS: u64 = 2_000;`, batch `send-transaction-service/src/send_transaction_service.rs:45` => `DEFAULT_TRANSACTION_BATCH_SIZE: usize = 1;`, retry pool `send-transaction-service/src/send_transaction_service.rs:33` => `MAX_TRANSACTION_RETRY_POOL_SIZE: usize = 10_000;`. Operators can change them (`validator/src/commands/run/args/send_transaction_config.rs:180` => `.long("rpc-send-leader-count")`); Helius values are CBD.
3. Which leaders: target slot is the highest commitment slot plus one (`rpc/src/cluster_tpu_info.rs:51` => `let target_slot = current_slot.saturating_add(1);`), then 4*i slots further per leader (`rpc/src/cluster_tpu_info.rs:79` => `i.saturating_mul(NUM_CONSECUTIVE_LEADER_SLOTS.get() as u64)`). Fanout 2 therefore sends to the leaders of tip+1 and tip+5 (the next window), merged if identical (`tpu-client-next/src/connection_workers_scheduler.rs:366` => `pub fn extract_send_leaders`); connections are also opened one leader further (`tpu-client-next/src/client_builder.rs:225` => `connect: self.leader_send_fanout.saturating_add(1),`).
4. `maxRetries`: Some(0) means one broadcast, then no retry (`send-transaction-service/src/send_transaction_service.rs:272` => `drop transactions with 0 max retries`). None retries until expiry (`send-transaction-service/src/send_transaction_service.rs:41` => `DEFAULT_SERVICE_MAX_RETRIES: usize = usize::MAX;`), expiry being `send-transaction-service/src/send_transaction_service.rs:427` => `transaction_info.last_valid_block_height < root_bank.block_height()`. A request value is capped by the service value: `send-transaction-service/src/send_transaction_service.rs:110` => `.map(|max_retries| max_retries.min(service_max_retries))`. Blockhash life is 150 blocks, about 30 s at 200 ms (docs: W2).
5. Transport: one QUIC unidirectional stream per transaction (`tpu-client-next/src/quic_networking.rs:103` => `let mut send_stream = connection.open_uni().await?;`); per-leader queues are 128 deep and overflow is dropped with only a debug log (`send-transaction-service/src/transaction_client.rs:147` => `.worker_channel_size(128)`; `tpu-client-next/src/connection_workers_scheduler.rs:334` => `worker cannot accept a transaction because its channel is full`, `tpu-client-next/src/connection_workers_scheduler.rs:349` => `Failed to send transaction to {new_leader:?}, worker send error: {err}.`).

### C2. What Helius documents

- Basic `sendTransaction` routes "directly to current and upcoming block leaders through a priority lane" (docs: W5). Staked connections are "the default method for all Helius paid plans" (docs: W14); the pricing page says Free has "Staked Connections: No" and "1 sendTransaction / sec" (docs: W7, W8). The Free route is therefore CBD.
- Helius advises: "Do not rely on the RPC provider's default retry logic", staked sends "can still be dropped", rebroadcast yourself (docs: W6, W14). Whether Helius itself rebroadcasts or de-duplicates on Free is CBD.
- Jito: only `sendBundle` is documented as "proxied directly to Jito" (docs: W5); basic sendTransaction to Jito is undocumented (CBD). Helius Sender (separate host, free on all plans, 50/s) submits "across all pathways (Helius, Jito, Harmonic, Rakurai, etc.) simultaneously" and requires a tip plus a priority fee inside the transaction (docs: W9, W8). It changes content and route; noted, not recommended.
- The node "does not alter the transaction" and runs signature check and simulation unless skipped (docs: W10).

### C3. Stake-weighted QoS and QUIC limits at the leader

src: unstaked connections get 128 concurrent streams (`streamer/src/nonblocking/swqos.rs:39` => `QUIC_MAX_UNSTAKED_CONCURRENT_STREAMS: u32 = 128;`); staked ones 128 to 512 by stake share (`streamer/src/nonblocking/swqos.rs:40` => `QUIC_MIN_STAKED_CONCURRENT_STREAMS: u32 = 128;`, `streamer/src/nonblocking/swqos.rs:46` => `QUIC_MAX_STAKED_CONCURRENT_STREAMS: u32 = 512;`). Ingress budget `streamer/src/quic.rs:52` => `DEFAULT_MAX_STREAMS_PER_MS: u64 = 500;` of which unstaked traffic is expected to take 20% (`streamer/src/nonblocking/stream_throttle.rs:19` => `EXPECTED_UNSTAKED_STREAMS_RATIO: f64 = 0.20;`). Each unstaked connection is capped at `streamer/src/nonblocking/stream_throttle.rs:17` => `MAX_UNSTAKED_TPS: u64 = 200;` (20 streams per 100 ms) per connection (`streamer/src/nonblocking/swqos.rs:292` => `fn max_streams_per_throttling_interval(&self, conn_context: &SwQosConnectionContext) -> u64 {`) and the excess is delayed (`streamer/src/nonblocking/stream_throttle.rs:268` => `sleep(throttle_duration).await;`). Connections per peer: `streamer/src/quic.rs:42` => `DEFAULT_MAX_QUIC_CONNECTIONS_PER_UNSTAKED_PEER: usize = 8;`, `streamer/src/quic.rs:45` => `DEFAULT_MAX_QUIC_CONNECTIONS_PER_STAKED_PEER: usize = 16;`. docs: W11 add that throttled streams may be dropped with error code 15; docs: W12 describes 80% of leader capacity as stake-weighted. Whether our sends arrive staked or unstaked is CBD. Leader software per slot is CBD (docs: W3 mentions Jito-Solana needs v4.2.2; docs: W1 says Firedancer and Frankendancer were not supported for the migration).

### C4. Where a transaction can be dropped or delayed

- Helius HTTP: 429 above 1 sendTransaction/s on Free (docs: W8). Helius internals: CBD.
- Agave preflight: signature, health or simulation failure rejects before enqueue (C1.1).
- STS: a signature already pending is ignored (`send-transaction-service/src/send_transaction_service.rs:247` => `.received_duplicate_transactions`); pool cap 10,000; expiry; maxRetries (C1).
- tpu-client-next: 128-deep queue; a failed stream is not resent (`tpu-client-next/src/connection_worker.rs:255` => `it doesn't retry to send the same transaction again`).
- Leader QUIC: stream, TPS and connection limits above.
- Sigverify: dedup window 2 s, false-positive rate 0.001 (`core/src/sigverify_stage.rs:39` => `MAX_DEDUPER_AGE: Duration = Duration::from_secs(2);`, `core/src/sigverify_stage.rs:40` => `DEDUPER_FALSE_POSITIVE_RATE: f64 = 0.001;`).
- Banking buffer: `core/src/banking_stage.rs:87` => `TOTAL_BUFFERED_PACKETS: usize = 100_000;`. A non-leader holds packets only when its own window is under 2 slots away and forwards-and-holds up to 20 slots away (`core/src/banking_stage/decision_maker.rs:95` => `if slots_until_leader < FORWARD_TRANSACTIONS_TO_LEADER_AT_SLOT_OFFSET {`; constants 2 and 20, docs: W15).
- Scheduler: a full block or low priority leaves the transaction unscheduled (C5). Expiry about 30 s (docs: W2).

### C5. Is arrival order of two transactions preserved?

- Order inside a JSON-RPC batch is the client's array order. Helius front end, node choice and queues: CBD.
- jsonrpc-core on a plain Agave RPC starts batch calls in array order, then joins them (docs: W13): `web/jsonrpc_io.rs:253` => `.map(move |call| self.handle_call(call, meta.clone()))`. Whether the derived sync handler runs inline was not read (CBD).
- Handler to STS is a FIFO channel; with batch size 1 the order holds. With a larger batch the transactions come out of a `HashMap`, so order is random: `send-transaction-service/src/send_transaction_service.rs:212` => `let mut transactions = HashMap::new();`, read at `send-transaction-service/src/send_transaction_service.rs:262` => `transaction_info.wire_transaction.clone()`.
- Each batch is sent from its own spawned task, with no ordering guarantee between batches on a multi-thread runtime: `send-transaction-service/src/transaction_client.rs:49` => `self.runtime_handle.spawn(async move {`. Runtime configuration is CBD.
- Per-leader worker sends sequentially, but each transaction is its own QUIC stream, and streams carry no mutual ordering (docs: W11).
- Leader scheduler orders by priority, then by a slab key that is reused after removals, not by arrival: `core/src/transaction_priority.rs:21` => `/// P = R / (1 + C)`; `core/src/banking_stage/transaction_scheduler/transaction_priority_id.rs:4` => `PartialOrd, Ord)]`; `core/src/banking_stage/transaction_scheduler/transaction_state_container.rs:162` => `self.priority_queue.pop_last()`; `core/src/banking_stage/transaction_scheduler/transaction_state_container.rs:270` => `let transaction_id = entry.key();`. Default scheduler: `core/src/validator.rs:218` => `CentralSchedulerGreedy,`; other leaders may differ (CBD).
- Knowable: each transaction's final position in `getBlock` (verified: a4). Not knowable: arrival times at Helius, at our node or at the leader.

## D. Leader schedule detection and RPC freshness

- Semantics (verified: d2): per epoch of 432000 slots, `leaderScheduleSlotOffset` 432000. `getSlotLeaders(463536000, 4)` (next epoch) answered; epoch+2 returned "leader schedule for epoch 1074 is unavailable". `getLeaderSchedule` and `getSlotLeaders` agree. The mapping slot to leader is unchanged by Alpenglow; when and whether the leader runs its window is not fixed by the schedule (B, A3).
- Latency (verified: d1), 20 sequential `getSlot`: Helius min 114, p50 132, mean 162, p90 199, max 390 ms; public min 123, p50 145, mean 152, p90 169, max 247 ms.
- Staleness (verified: d1), 20 rounds, both endpoints and 3 commitments called concurrently, lag behind the freshest slot seen in the round: Helius processed median 0 (max 2), confirmed 1 (max 3), finalized 1 (max 3); public processed 0 (max 2), confirmed 1 (max 3), finalized 1 (max 3); Helius minus public processed median 0, range -1 to 2. The true tip is CBD (no oracle). One slot is about 213 ms, comparable to one round trip.

## Open questions (CBD)

1. Route, rebroadcast, batch ordering and STS settings of a Free-plan Helius send.
2. Which leaders run Agave, Jito-Solana, Harmonic or other software, hence which scheduler orders their blocks.
3. Arrival times at the leader and the real ParentReady time of each window.
4. Whether fast leader handover (Agave v4.4) changes window starts during the study.

## Citation check

Generated by `python3 -I $S/rd/cite_check.py`. For every cited `path:LINE` plus quote in the body, `sed -n "LINEp" path | grep -cF -- "quote"` must print 1 (`web/` paths resolve under `$S`). Counts by command on the body text (everything before this heading):

```
sed '/^## Citation check/,$d' tx_path_alpenglow.md | grep -oE '`[^` ]+\.(rs|toml):[0-9]+` =>' | wc -l   -> 67
grep -c ' PASS$' (list below)   -> 67
grep -c ' FAIL$' (list below)   -> 0
```

Pinned HEAD printed by the script: `a203300045b405f86c9c84308b2eae76af69ac3b`. Results per citation (number, path:LINE, result):

```
1 leader-schedule/src/lib.rs:20 PASS
2 runtime/src/slot_params.rs:172 PASS
3 runtime/src/slot_params.rs:324 PASS
4 feature-set/src/lib.rs:2600 PASS
5 core/src/block_creation_loop.rs:457 PASS
6 votor/src/consensus_pool_service.rs:469 PASS
7 votor/src/consensus_pool/parent_ready_tracker.rs:7 PASS
8 core/src/block_creation_loop.rs:698 PASS
9 core/src/block_creation_loop.rs:78 PASS
10 core/src/block_creation_loop.rs:84 PASS
11 core/src/block_creation_loop.rs:833 PASS
12 votor/src/common.rs:29 PASS
13 votor/src/event_handler.rs:248 PASS
14 votor/src/event_handler.rs:896 PASS
15 votor/src/consensus_pool_service.rs:452 PASS
16 core/src/replay_stage.rs:1643 PASS
17 feature-set/src/lib.rs:2619 PASS
18 entry/src/block_component.rs:72 PASS
19 core/src/block_creation_loop.rs:545 PASS
20 runtime/src/block_component_processor.rs:760 PASS
21 rpc/src/rpc.rs:3917 PASS
22 rpc/src/rpc.rs:3951 PASS
23 rpc/src/rpc.rs:3977 PASS
24 rpc/src/rpc.rs:3942 PASS
25 rpc/src/rpc.rs:2782 PASS
26 send-transaction-service/src/send_transaction_service.rs:39 PASS
27 send-transaction-service/src/send_transaction_service.rs:36 PASS
28 send-transaction-service/src/send_transaction_service.rs:45 PASS
29 send-transaction-service/src/send_transaction_service.rs:33 PASS
30 validator/src/commands/run/args/send_transaction_config.rs:180 PASS
31 rpc/src/cluster_tpu_info.rs:51 PASS
32 rpc/src/cluster_tpu_info.rs:79 PASS
33 tpu-client-next/src/connection_workers_scheduler.rs:366 PASS
34 tpu-client-next/src/client_builder.rs:225 PASS
35 send-transaction-service/src/send_transaction_service.rs:272 PASS
36 send-transaction-service/src/send_transaction_service.rs:41 PASS
37 send-transaction-service/src/send_transaction_service.rs:427 PASS
38 send-transaction-service/src/send_transaction_service.rs:110 PASS
39 tpu-client-next/src/quic_networking.rs:103 PASS
40 send-transaction-service/src/transaction_client.rs:147 PASS
41 tpu-client-next/src/connection_workers_scheduler.rs:334 PASS
42 tpu-client-next/src/connection_workers_scheduler.rs:349 PASS
43 streamer/src/nonblocking/swqos.rs:39 PASS
44 streamer/src/nonblocking/swqos.rs:40 PASS
45 streamer/src/nonblocking/swqos.rs:46 PASS
46 streamer/src/quic.rs:52 PASS
47 streamer/src/nonblocking/stream_throttle.rs:19 PASS
48 streamer/src/nonblocking/stream_throttle.rs:17 PASS
49 streamer/src/nonblocking/swqos.rs:292 PASS
50 streamer/src/nonblocking/stream_throttle.rs:268 PASS
51 streamer/src/quic.rs:42 PASS
52 streamer/src/quic.rs:45 PASS
53 send-transaction-service/src/send_transaction_service.rs:247 PASS
54 tpu-client-next/src/connection_worker.rs:255 PASS
55 core/src/sigverify_stage.rs:39 PASS
56 core/src/sigverify_stage.rs:40 PASS
57 core/src/banking_stage.rs:87 PASS
58 core/src/banking_stage/decision_maker.rs:95 PASS
59 web/jsonrpc_io.rs:253 PASS
60 send-transaction-service/src/send_transaction_service.rs:212 PASS
61 send-transaction-service/src/send_transaction_service.rs:262 PASS
62 send-transaction-service/src/transaction_client.rs:49 PASS
63 core/src/transaction_priority.rs:21 PASS
64 core/src/banking_stage/transaction_scheduler/transaction_priority_id.rs:4 PASS
65 core/src/banking_stage/transaction_scheduler/transaction_state_container.rs:162 PASS
66 core/src/banking_stage/transaction_scheduler/transaction_state_container.rs:270 PASS
67 core/src/validator.rs:218 PASS
```
