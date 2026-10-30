# Transaction path and block production under Alpenglow (Solana mainnet, 2026-10-30)

Scope: documents mechanisms and read-only measurements. It does not design the experiment.
Pinned source: Agave v4.3.2, commit `a203300045b405f86c9c84308b2eae76af69ac3b` (verified: `git -C scratchpad/src/agave rev-parse HEAD`, `git describe --tags` printed `v4.3.2`). All `path:LINE` below are relative to that checkout.

Label legend. "verified: aN" = command row in Table V (script and output kept in the scratchpad). "docs: Wn" = from docs, URL in Table W, fetched 2026-10-30 (where marked "excerpt", only the search-result excerpt was read, not the full page). "src" = code citation `path:LINE` => `quote`, checked in the Citation check section. "CBD" = cannot be determined from here.

Table V (scratch dir `S=/tmp/claude-0/-home-user-Inside-The-Solana-Block/8de50ae6-1ba8-5ff6-ac11-6a0da13bc5fe/scratchpad`; run as `cd $S && python3 -I rd/<script>`; output in `$S/out/`):

| id | script | output |
|---|---|---|
| t0 | rd/t0_smoke.py | out/t0_smoke.txt |
| a1 | rd/a1_leaders.py | out/a1_leaders.txt |
| a2 | rd/a2_slotdur.py | out/a2_slotdur.txt |
| a3 | rd/a3_skip.py, rd/a3b_partial.py, rd/a3c_recent.py | out/a3_skip.txt, out/a3b_partial_boundary.txt, out/a3c_recent.txt |
| a4 | rd/a4_block.py, rd/a4b_v1_boundary.py | out/a4_block.txt, out/a4b_v1_boundary.txt |
| a5 | rd/a5_features.py | out/a5_features.txt |
| d1 | rd/d1_latency.py | out/d1_latency.txt |
| d2 | rd/d2_schedule.py | out/d2_schedule.txt |

Table W (docs): W1 https://solana.com/upgrades/alpenglow; W2 https://solana.com/upgrades/reduced-slot-times (excerpt); W3 https://solana.com/upgrades/larger-transaction-sizes; W4 https://github.com/solana-foundation/solana-improvement-documents/blob/main/proposals/0385-transaction-v1.md (excerpt); W5 https://helius.dev/docs/sending-transactions/overview; W6 https://helius.dev/docs/sending-transactions/send-manually; W7 https://helius.dev/pricing.md (page header says last-updated 2025-01-20); W8 https://helius.dev/docs/billing/rate-limits (excerpt); W9 https://helius.dev/docs/sending-transactions/sender (excerpt); W10 https://helius.dev/docs/api-reference/rpc/http/sendtransaction; W11 https://docs.anza.xyz/validator/tpu (excerpt); W12 https://solana.com/docs/defi/stake-weighted-qos (excerpt); W13 https://raw.githubusercontent.com/paritytech/jsonrpc/v18.0.0/core/src/io.rs (saved as `web/jsonrpc_io.rs`); W14 https://helius.dev/docs/sending-transactions/optimizing-transactions (excerpt); W15 https://docs.rs/solana-clock/3.2.0/solana_clock/constant.HOLD_TRANSACTIONS_SLOT_OFFSET.html.

RPC_URL usage: about 90 calls in total (append-only counter `out/rpc_url_calls.bytes`, seeded with 85 for the calls made before the counter was fixed). Heavy sampling went to api.mainnet-beta.solana.com (called "public" below). Both endpoints report solana-core 4.3.2 (verified: t0, `getVersion` returned `solana-core: 4.3.2` on both).

## 0. Findings in ten lines

1. Leader windows are still 4 consecutive slots, 4-aligned; a validator can lead 2 or 3 windows in a row (run lengths 8, 12). verified: a1, d2.
2. Nominal slot time is 200 ms since slot 454,896,000; realized is 212.7 to 215.8 ms/slot, before and after Alpenglow alike. verified: a2, a5.
3. Skip rate is about 0.10% of slots recently; skips are window-granular, and a window can end early (prefix patterns `PPP.`, `P...`); in the sampled ranges after the switch a window never started late. verified: a3.
4. Vote transactions are gone from blocks (649 of 1051 txs before, 0 of 1701 after). verified: a4.
5. getBlock has no entries field; 16 sampled blocks hold 37% v1, 38% v0, 25% legacy transactions. verified: a4.
6. A window starts when its leader observes ParentReady, not at a wall-clock boundary; early start (fast leader handover) is not active on mainnet. src + verified: a5.
7. Helius Free plan: 1 sendTransaction/s and "Staked Connections: No" on the pricing page; the actual route of a Free-plan send is CBD.
8. Agave's default RPC fanout is 2 leaders (slot tip+1 and tip+5), retry every 2 s until blockhash expiry unless maxRetries says otherwise. src.
9. Arrival order at the leader is not preserved by any stage after the HTTP batch is parsed, and the leader's scheduler orders by priority, not arrival. src, CBD for Helius internals.
10. getSlot round trip p50 132 ms (Helius) and 145 ms (public); Helius processed slot is within 0 to 2 slots of the freshest value seen. verified: d1.

## A. Alpenglow measured with read-only RPC

### A1. Leader window length (verified: a1, d2)

`getSlotLeaders` over 3000 slots each, inner runs of identical leader:

| range | runs | run-length histogram | start slot mod 4 |
|---|---|---|---|
| recent 463315522..463318521 | 739 | {4: 729, 8: 10} | all 0 |
| ~400k slots earlier | 740 | {4: 731, 8: 9} | all 0 |
| after boundary 459653008..459656007 | 742 | {4: 736, 8: 6} | all 0 |
| before boundary 459650000..459652999 | 740 | {4: 733, 8: 6, 12: 1} | all 0 |

Whole epoch 1072 from `getLeaderSchedule` (650 identities, 432000 slots): {4: 105670, 8: 1126, 12: 26} and zero mismatches against `getSlotLeaders` on 2000 slots (verified: d2). Run lengths of 8 or 12 are consecutive windows given to the same identity, not longer windows. The code constant: `leader-schedule/src/lib.rs:20` => `NUM_CONSECUTIVE_LEADER_SLOTS: NonZeroUsize = NonZeroUsize::new(4)`. Epoch 1063 schedule is no longer served ("leader schedule for epoch 1063 is unavailable", verified: a1).

### A2. Slot duration (verified: a2, a5)

20 `getBlockTime` samples spread over 100k slots per span:

| span | slots/s (endpoints) | ms/slot |
|---|---|---|
| before: 459552999..459652996 | 4.6338 | 215.8 |
| after, first 100k: 459653008..459753005 | 4.7018 | 212.7 |
| after, latest 100k: 463217616..463317613 | 4.6852 | 213.4 |
| whole post span 459653008..463317616 | 4.7019 | 212.7 |

OLS slopes agree to 0.001 slots/s. Nominal: feature `iBRLjhJnkmDZgNoZRDMW11d8ZV7HvsL3vAyRjZB5npW` (reduce_slot_time_to_200ms) activated at slot 454,464,000 (epoch 1052), effective at the next epoch start 454,896,000 (verified: a5, arithmetic 454464000/432000 = 1052). Code: `runtime/src/slot_params.rs:172` => `ns_per_slot: 200_000_000,` and the one-epoch delay `runtime/src/slot_params.rs:324` => `A gate that activates in epoch E is effective starting at the first slot`. docs: W2 gives the same date (epoch 1053, 454,896,000). Realized is 6 to 8% above nominal both before and after the boundary; the Alpenglow change did not shorten slots. Blocks have 1-second blockTime granularity, so two consecutive slots usually share a blockTime (verified: a4, slots 463314508/509 share 1793369568).

### A3. Skip rate (verified: a3)

| range | slots | skipped | rate |
|---|---|---|---|
| TowerBFT, 459628000..459652999 | 25000 | 40 | 0.160% |
| Alpenglow first 25k after 459653008 | 25000 | 348 | 1.392% |
| recent 463224636..463324636 | 100001 | 111 | 0.111% |

Window patterns (P = block, . = skipped), recent 100k: `PPPP` 24969, `....` 25, `P...` 3, `PPP.` 2. Right after the switch (50k): 98 fully skipped windows of 12,500 plus 18 partial, all prefix-style (`PPP.`, `PP..`, `P...`). TowerBFT 50k before: one `P...` and one `..PP`. After the switch no `.PPP` or `..PP` was seen in the sampled ranges. Skipped slots per position in the window, recent 25,001 slots (verified: a3): 5, 6, 6, 6 of about 6250 each, i.e. window-granular.

### A4. Block structure today (verified: a4)

`getBlock` keys: `blockHeight, blockTime, blockhash, parentSlot, previousBlockhash, rewards, transactions`. There is no entries, tick, or footer field. Per-transaction keys: `meta, transaction, version`; meta keys include `computeUnitsConsumed, costUnits`. Without `maxSupportedTransactionVersion: 1` the call fails with code -32015 ("Transaction version (1) is not supported"), also with value 0. In `signatures` mode no version parameter is needed.

Four consecutive blocks 463314508..511 held 1106, 1562, 1125, 1010 transactions (19.4M to 44.3M CU consumed); 10 blocks spread over 400k slots held 169 to 824 (median 334.5). Versions pooled over 16 blocks (9045 txs): legacy 2217 (24.5%), v0 3453 (38.2%), v1 3375 (37.3%). Boundary: block 459652999 had 1051 txs, 649 vote txs; block 459653008 (parent 459652999, slots 459653000..007 skipped) had 1701 txs, 0 vote txs.

Transaction version 1 is SIMD-0385 (docs: W3, W4), enabled by feature `txv1aq4pp281K9um3tnPgkfX8UqtFT6wcVW3hNezGLL` (`feature-set/src/lib.rs:2600` => `SIMD-0385: Transaction V1`), activated at slot 447,120,000 = epoch 1035 (verified: a5; docs: W3 says 2026-09-15). What it changes (docs: W3, W4): version byte 0x81 first, signatures last; a config mask carries priority fee (total lamports, not micro-lamports per CU), compute-unit limit, loaded-accounts data size, heap size, so ComputeBudget instructions become no-ops; no address lookup tables, up to 64 inline addresses; size limit 4096 bytes (SIMD-0296; base64 needed above 1232). Unset CU limit and data size default to 0 in v1. In getBlock a v1 message adds `transactionConfig` (verified: a4b: keys `accountKeys, header, instructions, recentBlockhash, transactionConfig`; sub-keys `computeUnitLimit, heapSize, loadedAccountsDataSizeLimit, priorityFee`).

## B. Alpenglow mechanics relevant to block production

All src claims at the pinned commit.

- Window size and slot time: 4 slots (A1 constant). Slot duration is a bank parameter, `core/src/block_creation_loop.rs:457` => `.saturating_mul((leader_slot_index(slot) as u32).saturating_add(1))`.
- Start: the Votor consensus pool emits ProduceWindow when ParentReady holds for the first slot of our window and stamps the timer then: `votor/src/consensus_pool_service.rs:469` => `block_timer: Instant::now(),`. ParentReady means the parent block is notarized (or notar-fallback) and all slots in between are skip-certified: `votor/src/consensus_pool/parent_ready_tracker.rs:7` => `(non-inclusive) are skip-certified.`. So the start time is set by consensus progress, not by a wall clock. Completion of a block also waits for it: `core/src/block_creation_loop.rs:698` => `Don't timeout until we've received ParentReady.`
- Stop: block k of the window must be completed at `ns_per_slot*(k+1) - 6 ms - 50 ms` after the timer (`core/src/block_creation_loop.rs:78` => `TIME_TO_COMPLETE_BLOCK_BROADCAST: Duration = Duration::from_millis(6)`; `core/src/block_creation_loop.rs:84` => `BLOCK_PRODUCTION_BUFFER: Duration = Duration::from_millis(50)`). At 200 ms that is 144, 344, 544, 744 ms. The block is closed at the timeout, not when full: it ends with one "alpentick" and a footer: `core/src/block_creation_loop.rs:833` => `w_poh_recorder.tick_alpenglow(max_tick_height, footer)?;`. Inference (arithmetic on verified: a2 and the constants): 4 x 213.4 = 853.6 ms per window vs 744 ms to the last block close leaves roughly 110 ms for notarization and ParentReady of the next window.
- Skip by the network: after ParentReady, validators set timers; the first-FEC-set wait is `votor/src/common.rs:29` => `DELTA_TIMEOUT: Duration = Duration::from_millis(400)` plus `votor/src/event_handler.rs:248` => `let delta_first_fec_set = delta_block;` (= 200 ms), so a silent leader is declared crashed 600 ms after ParentReady; later slots time out every 200 ms. When a timeout fires for a slot we have not voted on, we vote skip for every not-yet-voted slot of that whole window: `votor/src/event_handler.rs:896` => `for s in start..=last_of_consecutive_leader_slots(slot) {`. This matches the measured prefix-only partial windows.
- Missed window: a leader whose window was already skip-certified does not produce: `votor/src/consensus_pool_service.rs:452` => `has already been certified, skipping production`; the loop also drops a window if the cluster moved on: `core/src/block_creation_loop.rs:1132` => `Skipping production of {slot} because highest parent ready slot is`.
- Early start (fast leader handover, build on an optimistic parent): code exists but is gated: `core/src/replay_stage.rs:1643` => `bank.feature_set.snapshot().alpenglow_fast_leader_handover`; the feature account `FLHoAWBDjNh6zwmJ5i1NKK4KyD8otAiv7XxvmnFnVnKH` (`feature-set/src/lib.rs:2619` => `SIMD-0326: Alpenglow fast leader handover`) does not exist on mainnet (verified: a5, "err/none"). docs: W1 says fast leader handoff arrives with Agave v4.4.
- Votor/Rotor: Votor (votes, certificates) is live; Rotor (replaces Turbine) is not scheduled (docs: W1). Finality target about 150 ms; `confirmed` and `finalized` describe the same state (docs: W1).
- Votes in blocks: votes are no longer transactions; they go validator to validator and aggregate into certificates (docs: W1). Certificates ride in the block footer; footer has producer time in nanoseconds: `entry/src/block_component.rs:72` => `Producer Time Nanos`. The leader's clock sets the timestamp, bounded to at most twice the elapsed slot duration above the parent: `runtime/src/block_component_processor.rs:760` => `.saturating_mul(2)`; leader reads `core/src/block_creation_loop.rs:545` => `let mut block_producer_time_nanos = SystemTime::now()`. RPC exposes only whole seconds in `blockTime` and none of the footer (verified: a4).
- Migration: TowerBFT ran 5000 slots of epoch 1064; Alpenglow took over from slot 459,653,000 (docs: W1); slots 459653000..007 are skipped and block 459653008 is the first without votes (verified: a4).

## C. Transaction path from our backend to the leader

### C1. Agave RPC sendTransaction to the leader (src)

1. Handler (`send_transaction` in `rpc/src/rpc.rs`): `skipPreflight=true` forces processed commitment and skips signature check, health check and simulation: `rpc/src/rpc.rs:3917` => `Some(CommitmentConfig::processed())`, `rpc/src/rpc.rs:3951` => `if !skip_preflight {`, `rpc/src/rpc.rs:3977` => `preflight_bank.simulate_transaction(&transaction, false)`. If the blockhash is unknown and preflight is skipped, a fallback expiry is invented: `rpc/src/rpc.rs:3942` => `(skip_preflight && last_valid_block_height == 0)`.
2. Success is returned as soon as the transaction is enqueued: `rpc/src/rpc.rs:2782` => `.send(transaction_info)`.
3. Send-transaction-service defaults: forward count `send-transaction-service/src/send_transaction_service.rs:39` => `DEFAULT_LEADER_FORWARD_COUNT: u64 = 2;`, retry period `send-transaction-service/src/send_transaction_service.rs:36` => `DEFAULT_RETRY_RATE_MS: u64 = 2_000;`, batch size `send-transaction-service/src/send_transaction_service.rs:45` => `DEFAULT_TRANSACTION_BATCH_SIZE: usize = 1;`, retry pool `send-transaction-service/src/send_transaction_service.rs:33` => `MAX_TRANSACTION_RETRY_POOL_SIZE: usize = 10_000;`. Operators can change them (`validator/src/commands/run/args/send_transaction_config.rs:180` => `.long("rpc-send-leader-count")`); Helius settings are CBD.
4. Which leaders: target slot is one past the highest commitment slot (`rpc/src/cluster_tpu_info.rs:51` => `let target_slot = current_slot.saturating_add(1);`) and the i-th leader is looked up 4*i slots further (`rpc/src/cluster_tpu_info.rs:79` => `i.saturating_mul(NUM_CONSECUTIVE_LEADER_SLOTS.get() as u64)`). With fanout 2: the leader of tip+1 and of tip+5 (always the next window), identical addresses merged. The client also keeps connect fanout +1: `tpu-client-next/src/client_builder.rs:225` => `connect: self.leader_send_fanout.saturating_add(1),`. Leader addresses refresh every second: `send-transaction-service/src/transaction_client.rs:30` => `LEADER_INFO_REFRESH_RATE_MS: u64 = 1000;`.
5. `maxRetries`: Some(0) means one broadcast, then dropped from the retry pool: `send-transaction-service/src/send_transaction_service.rs:272` => `drop transactions with 0 max retries`. None means retry until expiry (`send-transaction-service/src/send_transaction_service.rs:41` => `DEFAULT_SERVICE_MAX_RETRIES: usize = usize::MAX;`), expiry being `send-transaction-service/src/send_transaction_service.rs:427` => `transaction_info.last_valid_block_height < root_bank.block_height()`. A per-request value is capped by the service value: `send-transaction-service/src/send_transaction_service.rs:110` => `.map(|max_retries| max_retries.min(service_max_retries))`. Blockhash life is 150 blocks, about 30 s at 200 ms (docs: W2).
6. Transport: each transaction is one QUIC unidirectional stream: `tpu-client-next/src/quic_networking.rs:103` => `let mut send_stream = connection.open_uni().await?;`; per-leader queues are 128 deep and overflow is dropped without error: `send-transaction-service/src/transaction_client.rs:147` => `.worker_channel_size(128)`, `tpu-client-next/src/connection_workers_scheduler.rs:334` => `worker cannot accept a transaction because its channel is full`.

### C2. What Helius documents

- Basic `sendTransaction` "route[s] directly to current and upcoming block leaders through a priority lane" (docs: W5). Staged detail: staked connections are "the default method for all Helius paid plans" (docs: W14); the pricing table lists Free: "Staked Connections: No", Free "1 sendTransaction / sec" (docs: W7, W8). So the Free-plan route is CBD (no page states it).
- Helius says staked connections can still drop a transaction in the banking stage and tells users to rebroadcast themselves, "Do not rely on the RPC provider's default retry logic" (docs: W6, W14). Whether Helius runs its own rebroadcast or de-duplication on Free is CBD.
- Jito: only `sendBundle` is documented as "proxied directly to Jito" (docs: W5). Basic `sendTransaction` going to Jito is not documented (CBD). Helius Sender (separate host `sender.helius-rpc.com`, free on every plan, 50/s) submits "across all pathways (Helius, Jito, Harmonic, Rakurai, etc.) simultaneously" but requires a SOL tip and a priority fee in the transaction (docs: W9, W8). Using it changes the transaction content and the route; this is noted, not recommended.
- Helius states the node does not alter the transaction and runs preflight (signature check and simulation) unless skipped (docs: W10).

### C3. Stake-weighted QoS and QUIC limits at the leader

src, at the leader (`streamer`): unstaked peers get 128 concurrent streams per connection (`streamer/src/nonblocking/swqos.rs:39` => `QUIC_MAX_UNSTAKED_CONCURRENT_STREAMS: u32 = 128;`); staked peers 128 to 512 depending on stake share (`streamer/src/nonblocking/swqos.rs:40` => `QUIC_MIN_STAKED_CONCURRENT_STREAMS: u32 = 128;`, `streamer/src/nonblocking/swqos.rs:46` => `QUIC_MAX_STAKED_CONCURRENT_STREAMS: u32 = 512;`, `streamer/src/nonblocking/swqos.rs:48` => `QUIC_TOTAL_STAKED_CONCURRENT_STREAMS: u32 = 100_000;`). Total ingress budget `streamer/src/quic.rs:52` => `DEFAULT_MAX_STREAMS_PER_MS: u64 = 500;`; unstaked traffic is expected to take 20% of it (`streamer/src/nonblocking/stream_throttle.rs:19` => `EXPECTED_UNSTAKED_STREAMS_RATIO: f64 = 0.20;`) and each unstaked connection is capped at `streamer/src/nonblocking/stream_throttle.rs:17` => `MAX_UNSTAKED_TPS: u64 = 200;` (200 x 100 ms / 1000 = 20 streams per 100 ms interval), applied per connection: `streamer/src/nonblocking/swqos.rs:292` => `fn max_streams_per_throttling_interval(&self, conn_context: &SwQosConnectionContext) -> u64 {`; the excess is delayed by sleeping: `streamer/src/nonblocking/stream_throttle.rs:268` => `sleep(throttle_duration).await;`. Connection limits: `streamer/src/quic.rs:42` => `DEFAULT_MAX_QUIC_CONNECTIONS_PER_UNSTAKED_PEER: usize = 8;`, `streamer/src/quic.rs:45` => `DEFAULT_MAX_QUIC_CONNECTIONS_PER_STAKED_PEER: usize = 16;`, `streamer/src/quic.rs:57` => `DEFAULT_MAX_CONNECTIONS_PER_IPADDR_PER_MINUTE: u64 = 8;`. docs: W11 add that throttled streams are stopped with error code 15 and the client should back off; docs: W12 describe the 80% staked share. Whether our sends arrive over a staked or unstaked identity is CBD (depends on the Helius route above). Only the leader software matters at the end of the path; which implementation each leader runs is CBD (docs: W3 mentions Jito-Solana builds need v4.2.2; docs: W1 says Firedancer/Frankendancer were not supported for the migration).

### C4. Where a transaction can be dropped or delayed

| point | what happens | label |
|---|---|---|
| Helius HTTP | 429 above 1 sendTransaction/s on Free | docs: W8 |
| Helius internals | unknown queue, batching, routing | CBD |
| Agave preflight | sig/health/simulation errors reject before enqueue | src C1.1 |
| STS | same signature ignored while pending (`send-transaction-service/src/send_transaction_service.rs:247` => `.received_duplicate_transactions`); pool cap 10,000; expiry; maxRetries | src |
| tpu-client-next | 128-deep per-leader queue; failed stream not retried (`tpu-client-next/src/connection_worker.rs:255` => `it doesn't retry to send the same transaction again`) | src |
| QUIC at leader | stream and TPS limits above, throttling stop code | src, docs: W11 |
| sigverify | dedup window 2 s, false-positive rate 0.001: `core/src/sigverify_stage.rs:39` => `MAX_DEDUPER_AGE: Duration = Duration::from_secs(2);`, `core/src/sigverify_stage.rs:40` => `DEDUPER_FALSE_POSITIVE_RATE: f64 = 0.001;` | src |
| banking buffer | `core/src/banking_stage.rs:87` => `TOTAL_BUFFERED_PACKETS: usize = 100_000;` | src |
| non-leader holding | a node holds only when fewer than 2 slots from its own window and forwards earlier (`core/src/banking_stage/decision_maker.rs:95` => `if slots_until_leader < FORWARD_TRANSACTIONS_TO_LEADER_AT_SLOT_OFFSET {`; constants 2 and 20, docs: W15) | src |
| scheduler | block full or lower priority: not scheduled in this block | src C5 |
| expiry | about 30 s | docs: W2 |

### C5. Is the arrival order of two transactions preserved?

| stage | order | label |
|---|---|---|
| client array order inside a JSON-RPC batch | defined by client | n/a |
| Helius front end and node selection | unknown | CBD |
| jsonrpc-core batch on a plain Agave RPC: calls are started in array order, then joined: `web/jsonrpc_io.rs:253` => `.map(move |call| self.handle_call(call, meta.clone()))` and `web/jsonrpc_io.rs:256` => `future::join_all(futures)` | started in order; whether jsonrpc-derive runs sync handlers inline was not read | W13, partly CBD |
| RPC handler to STS channel | FIFO channel, but preflight time per tx varies | src |
| STS batch of size 1 | in order; with larger batch the values come from a HashMap (`send-transaction-service/src/send_transaction_service.rs:212` => `let mut transactions = HashMap::new();`, iterated at `send-transaction-service/src/send_transaction_service.rs:262` => `transaction_info.wire_transaction.clone()`) so order is random | src |
| each batch spawns a tokio task | no ordering guarantee across batches on a multi-thread runtime: `send-transaction-service/src/transaction_client.rs:49` => `self.runtime_handle.spawn(async move {` | src, CBD for runtime config |
| per-leader worker | sequential stream opening | src |
| QUIC | one stream per transaction, so no ordering across streams | docs: W11 |
| leader scheduler | orders by priority then slab key, not arrival: `core/src/transaction_priority.rs:21` => `/// P = R / (1 + C)`, `core/src/banking_stage/transaction_scheduler/transaction_priority_id.rs:4` => `PartialOrd, Ord)]`, `core/src/banking_stage/transaction_scheduler/transaction_state_container.rs:162` => `self.priority_queue.pop_last()`, `core/src/banking_stage/transaction_scheduler/transaction_state_container.rs:270` => `let transaction_id = entry.key();` (slab index, reused after removals) | src |

Knowable: final position of each transaction in `getBlock` (verified: a4). Not knowable: arrival timestamps at Helius, at our RPC node, or at the leader; which leader software ordered the block. Default scheduler: `core/src/validator.rs:218` => `CentralSchedulerGreedy,` (a validator can choose another; CBD per leader).

## D. Leader schedule detection and RPC freshness

- Semantics (verified: d2): the schedule is per epoch (432000 slots, `leaderScheduleSlotOffset` 432000), known one epoch ahead: `getSlotLeaders(463536000, 4)` (next epoch) worked, epoch+2 returned "leader schedule for epoch 1074 is unavailable". Slot to leader mapping is unchanged; what is not fixed is when the leader runs (Section B). Scheduled windows can be silently skipped (A3). `getLeaderSchedule` and `getSlotLeaders` agree (0 mismatches).
- Latency (verified: d1), 20 sequential `getSlot` calls: Helius min 114, p50 132, mean 162, p90 199, max 390 ms; public min 123, p50 145, mean 152, p90 169, max 247 ms.
- Staleness (verified: d1), 20 rounds, both endpoints and three commitments called concurrently, lag vs the freshest slot seen in the round: Helius processed median 0 (max 2), confirmed median 1 (max 3), finalized median 1 (max 3); public processed median 0 (max 2), confirmed 1 (max 3), finalized 1 (max 3); Helius minus public (processed) median 0, range -1..2. The true tip is CBD (no oracle); with slots of 213 ms a 1-slot lag is about 213 ms, comparable to one RPC round trip. `getSlot` without a commitment argument returned a finalized-like value, 1 slot behind processed at the median (Alpenglow finality is about 150 ms, docs: W1).

## Open questions (CBD)

1. Route and rebroadcast behaviour of a Free-plan Helius `sendTransaction` (staked or not, batch handling order, STS settings).
2. Which leaders run Agave, Jito-Solana, Harmonic or other software, and so which scheduler orders their blocks.
3. Arrival times at the leader and the actual ParentReady time of each window.
4. Whether fast leader handover (Agave v4.4) changes window start times during the study.

## Citation check

Generated by `python3 -I $S/rd/cite_check.py` (for each `path:LINE` => `quote`: `sed -n "LINEp" path | grep -cF -- "quote"` must print 1).
