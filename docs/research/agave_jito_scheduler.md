# Agave, Jito-Solana and Rakurai: block production and in-block ordering mechanisms

Date: 2026-10-30. Scope: source-code mechanisms only, from primary sources. No conclusions about our experiment, no design.

## 0. Pinned revisions, conventions

| Key | Repository | Tag | Full commit (`git rev-parse HEAD`) |
|---|---|---|---|
| A | anza-xyz/agave | v4.3.2 | a203300045b405f86c9c84308b2eae76af69ac3b |
| J | jito-foundation/jito-solana | v4.3.2-jito | 013a4306f585cbd213ee5071550339af766f930c |
| R | rakurai-io/rakurai-validator | release/v4.3.2-rakurai.1 | c74a67fb32032dbab66ddd89cef78dc4d6ecbc1c |
| A44 | anza-xyz/agave | v4.4.0 | 9ef63128134af559561f6a91a641ec01e665c70d |
| J44 | jito-foundation/jito-solana | v4.4.0-jito | 9a9756848e20745ab5e720741fef6c81dacbf455 |
| R44 | rakurai-io/rakurai-validator | release/v4.4.0-rakurai.0 | b1baabfb86b23ec699ab1bc3b20ff331fce92644 |

Also inspected: Agave v4.4.0-rc.1 (b6149a719f8fa84123ac3ce1e5f201af64bca8ee) and Jito v4.4.0-rc.1-jito (d545d8c264cccf8695a262583133a4301a91ba76). [verified: V2]

- The Jito checkout is one commit ("Jito Patch") whose parent is exactly the Agave v4.3.2 commit, so `git diff` between them is the complete Jito change. The Rakurai checkout is one commit ("Rakurai Patch") whose parent is the Jito commit above. [verified: V3, V4]
- A second Jito tag, v4.3.2-jito.0 (7037b4f425e655b8f973ee8ebea9a4de1a85b208), differs from v4.3.2-jito in 11 files; under core, poh, cost-model, runtime and scheduling-utils only poh/src/poh_recorder.rs differs, and the diff is caching of start-bank fields. [verified: V5]
- Citation form: `K:path:LINE` "quote", K as in the table (EXT = solana-clock 3.2.0 `lib.rs`, the version pinned in Agave's Cargo.lock; RLY = jito-relayer master `main.rs`; both fetched 2026-10-30, hashes in V10). Every citation is re-checked in "Citation check".
- Source labels: "verified: cite" = the citation check command `sed -n 'LINEp' FILE | grep -F -- 'QUOTE'`; "verified: Vn" = numbered command in "Commands run"; "from docs Dn" = web page listed in "Web sources", fetched 2026-10-30; "cannot be determined from here".

## 1. Summary of mechanisms relevant to in-block order

1. Default method `central-scheduler-greedy`; both CLI values use `GreedyScheduler`; 4 workers by default. [verified: cite, 2.1]
2. Priority = reward * 1,000,000 / (cost + 1), integer division. reward = priority fee + the non-burned half of the signature fee. cost uses the REQUESTED CU limit and loaded-accounts limit, not actual usage. [verified: cite, 2.3]
3. Equal-priority tie-break depends on version: 4.3.2 (Agave, Jito, public Rakurai container code) pops the highest reused slab key, not arrival order; 4.4.0 and 4.4.0-rc.1 pop the oldest container insertion first. Gossip lists both version families (V13). [verified: cite, V9, V13, 2.3]
4. Scheduling runs only while a leader bank exists. Before that it buffers up to 100,000 transactions (lowest priority evicted). Inside a bank, CU budget is released linearly over a pacing window. [verified: cite, 2.4, 2.5]
5. A pass pops in descending priority and skips transactions that conflict, so a lower-priority non-conflicting transaction can be scheduled before a blocked higher-priority one. Conflicting transactions are pinned to the thread already holding the lock; others go to the least-loaded thread. [verified: cite, 2.6]
6. A worker executes a batch (at most 64 transactions), then sends ONE record to a single shared bounded channel; one record becomes one PoH `Entry` with the batch's processed transactions in batch order. Entry order is the order records are dequeued, so ordering across threads follows execution and record completion time, not priority. [verified: cite, 2.7]
7. After Alpenglow the PoH tick service is not started; `BlockCreationLoop` dequeues records, enforces a per-slot deadline, and on a "sad" fast-leader handover re-injects recorded transactions into the scheduler. [verified: cite, 2.8]
8. Jito (non-bundle path): the same scheduler plus a check against accounts locked by in-flight bundles; bundles run on their own thread with no CU reservation found. With BAM connected the local scheduler is disabled. No per-transaction hold exists in the validator code. [verified: cite, 3]
9. Rakurai: public client fork of Jito; the scheduler is a closed binary over FFI; the public client changes block-end timing constants. [verified: cite, 4]

## 2. Agave v4.3.2

### 2.1 Methods, defaults, threads

- Two `BlockProductionMethod` variants exist: `CentralScheduler` and `CentralSchedulerGreedy`. `A:core/src/validator.rs:215` "pub enum BlockProductionMethod {", `A:core/src/validator.rs:217` "#[default]", `A:core/src/validator.rs:218` "CentralSchedulerGreedy,". [verified: cite]
- CLI default is that default value, with kebab-case names (`central-scheduler`, `central-scheduler-greedy`). `A:validator/src/commands/run/args.rs:1198` ".default_value(BlockProductionMethod::default().into())", `A:core/src/validator.rs:213` "#[strum(serialize_all = ". [verified: cite]
- `central-scheduler` is deprecated: `A:core/src/validator.rs:233` "is deprecated and will be removed in a future release". Both values are handled by one match arm and use `GreedyScheduler`: `A:core/src/banking_stage.rs:491` "| BlockProductionMethod::CentralSchedulerGreedy => {", `A:core/src/banking_stage.rs:588` "// Both block production methods currently route to the greedy scheduler.". No prio-graph scheduler exists in this tree's `transaction_scheduler/` directory. [verified: cite, V1]
- An external scheduler can replace the internal one: `A:validator/src/commands/run/args.rs:1227` "enable-scheduler-bindings", `A:core/src/banking_stage.rs:496` "BankingControlMsg::External { session } => self.spawn_external(session),". [verified: cite]
- Workers: `A:core/src/banking_stage.rs:85` "const DEFAULT_NUM_WORKERS: NonZeroUsize = NonZeroUsize::new(4).unwrap();", flag `A:validator/src/cli/thread_args.rs:260` "block-production-num-workers" with default `A:validator/src/cli/thread_args.rs:264` "BankingStage::default_num_workers().get()", maximum `A:core/src/banking_stage.rs:84` "const MAX_NUM_WORKERS: NonZeroUsize = NonZeroUsize::new(64).unwrap();". [verified: cite]
- Threads spawned: 8 check workers `A:core/src/banking_stage.rs:518` "NUM_CHECK_WORKERS: NonZeroUsize = NonZeroUsize::new(8).unwrap();", one vote worker `A:core/src/banking_stage.rs:544` "threads.push(self.spawn_vote_worker());", the N consume workers `A:core/src/banking_stage.rs:578` "solCoWorker{id:02}", and one scheduler thread `A:core/src/banking_stage.rs:598` "solBnkTxSched". Channels have capacity `A:core/src/banking_stage.rs:519` "const CHANNEL_CAPACITY: usize = 10_000;". [verified: cite]

### 2.2 Ingress to the container

Sigverify sends non-vote packets to the banking channel (`A:core/src/tpu.rs:286` "non_vote_sender,"); it can drop packets below a priority floor published by the scheduler (`A:core/src/sigverify_stage.rs:67` "total_dropped_below_priority_floor: Arc<AtomicUsize>,", `A:core/src/sigverify_stage.rs:158` "scheduler_priority_floor: Option<Arc<SchedulerPriorityFloor>>,"), which is raised when the buffer is nearly full: `A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:44` "const SATURATION_BUFFER_PCT: u8 = 99;" and cleared below `A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:46` "const DESATURATION_BUFFER_PCT: u8 = 95;". The scheduler thread reads at most `A:core/src/banking_stage/transaction_scheduler/receive_and_buffer.rs:332` "const MAX_PACKET_RECEIVES: usize = 512;" per iteration and hands bytes to the check workers, which parse and compute priority and cost (`A:core/src/banking_stage/transaction_scheduler/check_worker.rs:47` "precheck_transaction(bytes, &banks.root_bank, &banks.working_bank, &filter_keys);", `A:core/src/banking_stage/transaction_scheduler/receive_and_buffer.rs:97` "calculate_priority_and_cost(working_bank, &view, &transaction_configuration);"). Results are inserted into the container by the scheduler thread, in the order results are drained: `A:core/src/banking_stage/transaction_scheduler/receive_and_buffer.rs:487` "let transaction_id = container.insert_map_only(state);". [verified: cite]

Inference from the cited lines (not measured): the 8 check workers share one work queue and one result queue, so insertion order can differ from packet arrival order.

### 2.3 Priority, reward, cost, tie-break

- Formula, in the source comment and code: `A:core/src/transaction_priority.rs:21` "/// P = R / (1 + C)"; `A:core/src/transaction_priority.rs:59` "const MULTIPLIER: u64 = 1_000_000;", `A:core/src/transaction_priority.rs:62` ".saturating_mul(MULTIPLIER)", `A:core/src/transaction_priority.rs:63` ".saturating_div(cost.saturating_add(1)),". [verified: cite]
- Cost input uses the requested limits, not actual consumption: `A:core/src/transaction_priority.rs:39` "u64::from(transaction_configuration.compute_unit_limit)," as the "actual_programs_execution_cost" argument of `A:cost-model/src/cost_model.rs:56` "pub fn calculate_cost_for_executed_transaction", and `A:core/src/transaction_priority.rs:40` "transaction_configuration.loaded_accounts_data_size_limit,". [verified: cite]
- Cost = sum of five terms: `A:cost-model/src/transaction_cost.rs:19` "pub fn sum(&self) -> u64 {" (signature, write lock, data bytes, program execution, loaded accounts data size; allocated accounts data size is not in the sum). Signature cost `A:cost-model/src/block_cost_limits.rs:10` "pub const SIGNATURE_COST: u64 = COMPUTE_UNIT_TO_US_RATIO * 24;"; write-lock cost `A:cost-model/src/block_cost_limits.rs:18` "pub const WRITE_LOCK_UNITS: u64 = COMPUTE_UNIT_TO_US_RATIO * 10;" applied per write lock `A:cost-model/src/cost_model.rs:155` "WRITE_LOCK_UNITS.saturating_mul(num_write_locks)"; data bytes `A:cost-model/src/cost_model.rs:182` "transaction.instruction_data_len() / (INSTRUCTION_DATA_BYTES_COST as u16)"; the ratio constant `A:cost-model/src/block_cost_limits.rs:8` "pub const COMPUTE_UNIT_TO_US_RATIO: u64 = 30;". [verified: cite]
- Requested CU limit is the transaction's `SetComputeUnitLimit`, or a computed default when absent: `A:compute-budget-instruction/src/compute_budget_instruction_details.rs:125` "|| self.calculate_default_compute_unit_limit(feature_set),". Transaction v1 carries limit and priority fee directly in its config: `A:runtime-transaction/src/transaction_meta.rs:124` "priority_fee_lamports: config.priority_fee.unwrap_or(0),". [verified: cite]
- Reward = priority fee + base-fee share. Priority fee for legacy/v0 is `ceil(price * limit / 1e6)`: `A:compute-budget/src/compute_budget_limits.rs:63` "(compute_unit_price as u128).saturating_mul(compute_unit_limit as u128);", `A:compute-budget/src/compute_budget_limits.rs:65` ".saturating_add(MICRO_LAMPORTS_PER_LAMPORT.saturating_sub(1) as u128)". Base fee is signatures * lamports_per_signature: `A:fee/src/lib.rs:55` "signature_count.saturating_mul(lamports_per_signature)". The reward is the validator deposit: `A:core/src/transaction_priority.rs:51` ".calculate_reward_and_burn_fee_details(&CollectorFeeDetails::from(fee_details))", `A:core/src/transaction_priority.rs:52` ".get_deposit();", with `A:runtime/src/bank/fee_distribution.rs:101` "let burn = fee_details.transaction_fee * self.burn_percent() / 100;" and `A:runtime/src/bank/fee_distribution.rs:104` ".saturating_add(fee_details.transaction_fee.saturating_sub(burn));" (priority fee on `A:runtime/src/bank/fee_distribution.rs:103` ".priority_fee"). Burn percent is documented as static 50%: `A:runtime/src/bank/fee_distribution.rs:109` "// NOTE: burn percent is statically 50%". [verified: cite]
- Tip transfers, bundles and other off-chain signals are not inputs to this formula in Agave: the function body contains only the cost call, the fee call, the reward call and the multiplier. [verified: V14]
- Tie-break (v4.3.2): the queue is a `BTreeSet<TransactionPriorityId>` popped from the maximum end: `A:core/src/banking_stage/transaction_scheduler/transaction_state_container.rs:45` "priority_queue: BTreeSet<TransactionPriorityId>,", `A:core/src/banking_stage/transaction_scheduler/transaction_state_container.rs:162` "self.priority_queue.pop_last()". The id type derives ordering over (priority, id): `A:core/src/banking_stage/transaction_scheduler/transaction_priority_id.rs:4` "#[derive(Copy, Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]". `id` is a slab key assigned from a vacant entry, `A:core/src/banking_stage/transaction_scheduler/transaction_state_container.rs:270` "let transaction_id = entry.key();", and keys of removed entries are reused (the v4.4.0 test asserts reuse: `A44:core/src/banking_stage/transaction_scheduler/transaction_state_container.rs:428` "assert_eq!(priority_id.id, removed.id);"). So at equal priority the highest key pops first, which is not arrival order. [verified: cite]

### 2.4 Scheduler loop, hold before leader, buffer capacity

- Loop order each iteration (single thread): decision, receive completed work, drain check results, schedule, recheck queue if not leader, receive packets. `A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:206` "measure_us!(self.decision_maker.make_consume_or_forward_decision());", `A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:254` "self.receive_completed()?;", `A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:256` "let _scheduled = self.process_transactions(&decision, cost_pacer.as_ref(), &now)?;", `A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:257` "if decision.bank().is_none() {". [verified: cite]
- Scheduling happens only for `Consume`, which requires a working bank: `A:core/src/banking_stage/decision_maker.rs:65` "if let Some(working_bank) = state.working_bank() {", `A:core/src/banking_stage/decision_maker.rs:66` "BufferedPacketsDecision::Consume(working_bank.clone())", and the controller schedules only in that arm `A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:303` "BufferedPacketsDecision::Consume(_bank) => {". [verified: cite]
- With no working bank, post-Alpenglow timing is from the Alpenglow slot clock (`A:core/src/banking_stage/decision_maker.rs:85` "// PoH tick height no longer advances after Alpenglow activation."). `Hold` when fewer than 2 slots to the leader window, `ForwardAndHold` when fewer than 20, else `Forward`: `A:core/src/banking_stage/decision_maker.rs:95` "if slots_until_leader < FORWARD_TRANSACTIONS_TO_LEADER_AT_SLOT_OFFSET {", `A:core/src/banking_stage/decision_maker.rs:97` "} else if slots_until_leader < HOLD_TRANSACTIONS_SLOT_OFFSET {", constants `EXT:clock/src/lib.rs:111` "pub const FORWARD_TRANSACTIONS_TO_LEADER_AT_SLOT_OFFSET: u64 = 2;" and `EXT:clock/src/lib.rs:112` "pub const HOLD_TRANSACTIONS_SLOT_OFFSET: u64 = 20;". Past the window end the decision is `Forward` again: `A:core/src/banking_stage/decision_maker.rs:91` "if current_slot > last_leader_slot {". [verified: cite]
- `Hold` and `ForwardAndHold` buffer but do not schedule: `A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:335` "BufferedPacketsDecision::ForwardAndHold => 0,", `A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:336` "BufferedPacketsDecision::Hold => 0,". Ingress is checked and buffered for every decision except `Forward`: `A:core/src/banking_stage/transaction_scheduler/receive_and_buffer.rs:336` "let should_check = !matches!(decision, BufferedPacketsDecision::Forward);". `Forward` drops: `A:core/src/banking_stage/transaction_scheduler/receive_and_buffer.rs:408` "stats.num_dropped_without_parsing += 1;" and clears the container, `A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:327` "BufferedPacketsDecision::Forward => {". [verified: cite]
- Capacity: `A:core/src/banking_stage.rs:87` "const TOTAL_BUFFERED_PACKETS: usize = 100_000;" used as `A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:169` "let container_capacity = TOTAL_BUFFERED_PACKETS;". Over capacity the lowest-priority entry is evicted: `A:core/src/banking_stage/transaction_scheduler/transaction_state_container.rs:196` "self.priority_queue.pop_first()" (doc: `A:core/src/banking_stage/transaction_scheduler/transaction_state_container.rs:42` "/// a new transaction, the lowest priority transaction will be dropped."). [verified: cite]
- Retryable-later transactions (cost-limit failures) are held and re-queued at the next bank: `A:core/src/banking_stage/transaction_scheduler/transaction_state_container.rs:204` "self.held_transactions.push(priority_id);", flushed at `A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:217` "self.container.flush_held_transactions();". [verified: cite]

### 2.5 Time pacing within a slot

- On first seeing a new working bank the controller builds a `CostPacer` whose clock starts at that loop iteration (`A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:248` "detection_time: now,") and whose limit is the bank's block cost limit (`A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:221` "let block_limit = cost_tracker.get_block_limit();"). Budget = linear ramp minus cost already tracked: `A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:535` "let allocation_per_milli = self.block_limit / fill_time.as_millis() as u64;", `A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:537` "allocation_per_milli * millis_since_detection", `A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:543` "target.saturating_sub(self.shared_block_cost.load())". [verified: cite]
- Default fill time is slot time minus 50 ms: `A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:63` "const DEFAULT_SCHEDULER_PACING_NON_FILL_TIME_MILLIS: u64 = 50;", `A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:65` "NonZeroU64::new(DEFAULT_MS_PER_SLOT - DEFAULT_SCHEDULER_PACING_NON_FILL_TIME_MILLIS).unwrap();" with 400 ms per default slot (`EXT:clock/src/lib.rs:77` "static_assertions::const_assert_eq!(DEFAULT_MS_PER_SLOT, 400);"), i.e. 350 ms (V8). CLI: `A:validator/src/commands/run/args.rs:1203` "block-production-pacing-fill-time-millis". [verified: cite, V8]
- If fill time exceeds the bank slot time it is clamped for later banks, but the pacer for the current bank is built from the value read BEFORE the clamp: `A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:227` "let fill_time = self.config.scheduler_pacing.fill_time();", `A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:229` "pacing_fill_time.as_nanos() > b.ns_per_slot", `A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:236` "self.config.scheduler_pacing = SchedulerPacing::FillTimeMillis(", `A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:249` "fill_time,". [verified: cite]
- Mainnet state affecting those numbers: the four slot-time features (350, 300, 250, 200 ms) are all active, the 200 ms one since slot 454464000; `raise_block_limits_to_100m` is active since slot 435888000 [verified: V6]. The 200 ms parameter set has block cost limit 30,000,000 `A:runtime/src/slot_params.rs:175` "cost_tracker_limits: CostTrackerLimits::new(12_000_000, 30_000_000, 50_000_000),", scaled by 100/60 when that feature is on `A:runtime/src/bank.rs:4918` "params.cost_limits(self.feature_set.snapshot().raise_block_limits_to_100m);", giving 50,000,000 block cost and 20,000,000 per-account cost, a 150 ms clamped fill time, and 333,333 CU per ms of ramp (V8). Measured average over 4000 slot numbers, including skipped slots: 213.5 ms per slot (V7). Inference from the lines above and V6 (not measured on a leader): the 350 ms default exceeds a 200 ms slot, so the clamp path applies, and the first bank seen by a newly started scheduler thread uses the unclamped 350 ms ramp while later banks use 150 ms. [verified: cite, V6, V7, V8 for the inputs]

### 2.6 Greedy scheduling pass, threads, conflicts

- Description in source: `A:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:50` "/// Dead-simple scheduler that is efficient and will attempt to schedule" / `A:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:51` "/// in priority order, scheduling anything that can be immediately". [verified: cite]
- Limits per pass: `A:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:42` "target_scheduled_cus: MAX_BLOCK_UNITS / 4," (15,000,000 CU, V8; `MAX_BLOCK_UNITS` is the 60,000,000 constant `A:cost-model/src/block_cost_limits.rs:27` "pub const MAX_BLOCK_UNITS_SIMD_0256: u64 = 60_000_000;", independent of slot parameters), per-thread share `A:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:100` "let target_cu_per_thread = self.config.target_scheduled_cus / num_threads as u64;" (3,750,000 with 4 workers, V8), scan cap `A:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:43` "max_scanned_transactions_per_scheduling_pass: 100_000,". In-flight CU is subtracted from the pacer budget `A:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:87` "// Subtract any in-flight compute units from the budget." and each scheduled transaction subtracts its priority-time cost `A:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:194` "budget = budget.saturating_sub(cost);". [verified: cite, V8]
- Order of consideration: pop highest priority `A:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:137` "let Some(id) = container.pop() else {"; if it cannot be placed it is set aside and scanning continues: `A:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:164` "Err(TransactionSchedulingError::UnschedulableConflicts) => {", `A:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:166` "self.unschedulables.push(id);"; set-aside entries return to the queue at the end of the pass `A:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:229` "container.push_ids_into_queue(self.unschedulables.drain(..));". Inference from these lines: a lower-priority transaction can be scheduled ahead of a higher-priority one blocked by locks. [verified: cite for the lines]
- Thread-aware locks: a write-locked account may only go to the thread holding it `A:scheduling-utils/src/thread_aware_account_locks.rs:162` "/// If only write-locked, then only the thread holding the write lock is schedulable."; conflicts with several threads make the transaction unschedulable `A:scheduling-utils/src/thread_aware_account_locks.rs:98` ".ok_or(TryLockError::MultipleConflicts)?;"; a conflict outside the allowed threads also defers it `A:scheduling-utils/src/thread_aware_account_locks.rs:101` "return Err(TryLockError::ThreadNotAllowed);". Otherwise a thread is chosen by the caller: `A:scheduling-utils/src/thread_aware_account_locks.rs:104` "let thread_id = thread_selector(schedulable_threads);". Threads at their CU target or with a full channel are removed from the allowed set: `A:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:104` "if self.common.consume_work_senders[thread_id].is_full()". [verified: cite]
- Free choice = least (batched + in-flight CU), then fewest transactions: `A:core/src/banking_stage/transaction_scheduler/scheduler_common.rs:155` "batch_cus_per_thread[thread_id] + in_flight_cus_per_thread[thread_id],", `A:core/src/banking_stage/transaction_scheduler/scheduler_common.rs:159` ".min_by(|a, b| a.1.cmp(&b.1).then_with(|| a.2.cmp(&b.2)))". The doc comment above `select_thread` says work is "the number of transactions"; the code compares CU first. [verified: cite]
- Locks are released when a batch returns: `A:core/src/banking_stage/transaction_scheduler/scheduler_common.rs:316` ".unlock_accounts(write_account_locks, read_account_locks, thread_id);". Batches are cut at `A:core/src/banking_stage/consumer.rs:33` "pub const TARGET_NUM_TRANSACTIONS_PER_BATCH: usize = 64;" or by entry-byte target, and sent to that thread's channel (`A:core/src/banking_stage/transaction_scheduler/scheduler_common.rs:217` "self.consume_work_senders[thread_index]"). [verified: cite]

### 2.7 Execution, recording, and what fixes the order in the block

- Worker loop: one batch at a time from its own channel `A:core/src/banking_stage/consume_worker.rs:76` "match self.consume_receiver.try_recv() {", processed by `A:core/src/banking_stage/consume_worker.rs:120` "let output = self.consumer.process_and_record_aged_transactions(". If no active leader bank, the work is handed back as retryable: `A:core/src/banking_stage/consume_worker.rs:110` "return Ok(ProcessingStatus::CouldNotProcess(work));". [verified: cite]
- Inside a batch: cost reservation `A:core/src/banking_stage/consumer.rs:201` "QosService::select_and_accumulate_transaction_costs(" (reserves the tracker with the cost-model estimate, `A:core/src/banking_stage/qos_service.rs:68` "let mut reserving_cost = CostModel::calculate_cost(tx, feature_set);"), then bank-level account locks `A:core/src/banking_stage/consumer.rs:210` "bank.prepare_sanitized_batch_with_results(", then execute `A:core/src/banking_stage/consumer.rs:320` "measure_us!(bank.load_and_execute_transactions(", then record, then commit `A:core/src/banking_stage/consumer.rs:424` "self.committer.commit_transactions(". Execution happens BEFORE recording. A bank-level lock clash returns `AccountInUse` and is retried immediately `A:core/src/banking_stage/consumer.rs:275` "// locking failure due to vote conflict or jito - immediately retry.". After commit, tracker costs are replaced by actual compute units `A:core/src/banking_stage/qos_service.rs:175` "cost_tracker.update_execution_cost(". [verified: cite]
- Only processed transactions are recorded, in batch order: `A:core/src/banking_stage/consumer.rs:362` "if processing_result.was_processed() {", `A:core/src/banking_stage/consumer.rs:364` "processed_transactions.push(tx.to_versioned_transaction());". Recording is one call per batch: `A:core/src/banking_stage/consumer.rs:381` ".record_transactions(bank.bank_id(), processed_transactions)". [verified: cite]
- That call is a non-blocking send of one `Record` into a bounded channel shared by all workers and the vote thread: `A:poh/src/transaction_recorder.rs:110` ".try_send(Record::new(mixin, transactions, bank_id))", `A:poh/src/record_channels.rs:33` "let (sender, receiver) = bounded(CAPACITY);", `A:poh/src/record_channels.rs:19` "/// Transaction processing threads (workers/vote thread) send records, and". Sequential send order is enforced only when transaction indexes are tracked: `A:poh/src/record_channels.rs:97` "// Grab lock on `transaction_indexes` here to ensure we are sending". [verified: cite]
- One record becomes one entry with the batch's transactions in order: `A:poh/src/poh_recorder.rs:386` "Entry {", `A:poh/src/poh_recorder.rs:389` "transactions,". [verified: cite]
- Consequence for two non-conflicting transactions on different threads: they sit in different batches; each batch is executed and sent as a record independently; the entry order is the order records are dequeued, i.e. the order in which workers finish execute+record. The scheduler's priority order is not re-applied at record time. Within one thread, batches are processed one after another, so two transactions that conflict and went to the same thread keep scheduling order, unless one of them is returned as retryable and rescheduled. Transactions in one batch keep scheduler pop order. [verified: cite for each step; the combined statement is an inference from those lines and was not measured on a live validator]

### 2.8 Alpenglow changes to block production (code at v4.3.2)

- PoH tick service is not started after migration: `A:poh/src/poh_service.rs:124` "Post Alpenglow migration, not starting PohService". The record receiver goes to `BlockCreationLoop` (`A:core/src/block_creation_loop.rs:284` "let record_receiver = match record_receiver_receiver.recv() {"), the only thread that touches the PohRecorder once Alpenglow is active (`A:core/src/block_creation_loop.rs:6` "this is the only thread that will touch the"). [verified: cite]
- Records are dequeued FIFO in a select loop and appended: `A:core/src/block_creation_loop.rs:740` "recv(ctx.record_receiver.inner()) -> msg => {", `A:core/src/block_creation_loop.rs:748` "ctx.poh_recorder.write().unwrap().record(". [verified: cite]
- Deadline per slot, measured from the leader-window timer (`A:core/src/block_creation_loop.rs:454` "Returns the elapsed leader-window time at which"): `A:core/src/block_creation_loop.rs:456` "Duration::from_nanos_u128(bank.ns_per_slot_at_slot(slot))", `A:core/src/block_creation_loop.rs:457` ".saturating_mul((leader_slot_index(slot) as u32).saturating_add(1))", minus `A:core/src/block_creation_loop.rs:78` "const TIME_TO_COMPLETE_BLOCK_BROADCAST: Duration = Duration::from_millis(6);" and `A:core/src/block_creation_loop.rs:84` "const BLOCK_PRODUCTION_BUFFER: Duration = Duration::from_millis(50);". With a 4-slot window (checked on mainnet, V11) and 200 ms slots the deadlines are 144, 344, 544, 744 ms after the window timer (V8). After the deadline: stop intake and drain, then footer and single tick: `A:core/src/block_creation_loop.rs:773` "shutdown_and_drain_record_receiver(&ctx.poh_recorder, &mut ctx.record_receiver, None)?;", `A:core/src/block_creation_loop.rs:833` "w_poh_recorder.tick_alpenglow(max_tick_height, footer)?;". [verified: cite, V8, V11]
- The loop does not time out before ParentReady: `A:core/src/block_creation_loop.rs:698` "// Don't timeout until we've received ParentReady.". With an optimistic parent (fast leader handover) it keeps recording while waiting, retaining the transactions: `A:core/src/block_creation_loop.rs:745` "accumulated_txs.extend(record.transactions.iter().cloned());". On a "sad" handover (ParentReady differs from the optimistic parent) the bank is cleared and the recorded transactions are sent back to the banking-stage ingress to be rescheduled: `A:core/src/block_creation_loop.rs:1035` "rescheduling {} txs after sad leader handover for slot {slot}", `A:core/src/block_creation_loop.rs:1045` ".send(banking_packet_batch)". They then pass the priority queue again. [verified: cite]
- The leader bank for each slot is created by the loop (`A:core/src/block_creation_loop.rs:1285` "fn create_and_insert_leader_bank("), after the parent has been replayed (`A:core/src/block_creation_loop.rs:1091` "fn start_leader_wait_for_parent_replay("); the bank is set on the recorder and banking stage is then woken (`A:core/src/block_creation_loop.rs:1373` "ctx.poh_recorder.write().unwrap().set_bank(tpu_bank);", `A:core/src/block_creation_loop.rs:1383` "// Wakeup banking stage"). Inference from these lines: the scheduler's `Consume` decision starts when that bank is published, not at a wall-clock slot boundary. [verified: cite]

### 2.9 v4.4.0 and v4.4.0-rc.1 (differences relevant here)

- Unchanged (0 changed lines between 4.3.2 and 4.4.0): `core/src/transaction_priority.rs`, `decision_maker.rs`, `poh/src/record_channels.rs`, `poh/src/transaction_recorder.rs`, `cost-model/src/block_cost_limits.rs`, `thread_aware_account_locks.rs`, `runtime/src/slot_params.rs` (V9). Constants identical: workers `A44:core/src/banking_stage.rs:85` "const DEFAULT_NUM_WORKERS: NonZeroUsize = NonZeroUsize::new(4).unwrap();", buffer `A44:core/src/banking_stage.rs:87` "const TOTAL_BUFFERED_PACKETS: usize = 100_000;", end-of-block constants `A44:core/src/block_creation_loop.rs:78` "const TIME_TO_COMPLETE_BLOCK_BROADCAST: Duration = Duration::from_millis(6);" and `A44:core/src/block_creation_loop.rs:84` "const BLOCK_PRODUCTION_BUFFER: Duration = Duration::from_millis(50);", pacing non-fill `A44:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:90` "const DEFAULT_SCHEDULER_PACING_NON_FILL_TIME_MILLIS: u64 = 50;", greedy target `A44:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:43` "target_scheduled_cus: MAX_BLOCK_UNITS / 4,". [verified: cite, V9]
- CHANGED, tie-break: equal priority now pops the oldest container-insertion first, then lowest id: `A44:core/src/banking_stage/transaction_scheduler/transaction_priority_id.rs:25` ".then_with(|| other.arrival_order.cmp(&self.arrival_order))", `A44:core/src/banking_stage/transaction_scheduler/transaction_priority_id.rs:52` "// Equal priority then compare by arrival order, oldest first", counter assigned in the container `A44:core/src/banking_stage/transaction_scheduler/transaction_state_container.rs:278` "let arrival_order = self.next_arrival_order;". The field is present in Agave, Jito and Rakurai 4.4.0 and in Agave and Jito 4.4.0-rc.1, and absent in all three 4.3.2 trees (V9). [verified: cite, V9]
- CHANGED, bank transition: the controller does not schedule onto a new bank while transactions from the previous bank are still in flight: `A44:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:304` "// A slot transition gates only new scheduling. Check-result processing,". Also `ConsumeWork` carries the target slot (`A44:core/src/banking_stage/transaction_scheduler/scheduler_common.rs:213` "target_slot: slot,"), and execution takes a bank execution guard `A44:core/src/banking_stage/consumer.rs:324` "let tx_execution_guard = bank.try_enter_transaction_execution();". [verified: cite]

## 3. Jito-Solana v4.3.2-jito (difference from Agave v4.3.2)

Whole-patch size: 235 files changed (V3). Non-bundle banking-path changes found by diff (V9, V12):

- Priority formula unchanged: `J:core/src/transaction_priority.rs:21` "/// P = R / (1 + C)" (0 changed lines, V9). Block timing constants unchanged: `J:core/src/block_creation_loop.rs:78` "const TIME_TO_COMPLETE_BLOCK_BROADCAST: Duration = Duration::from_millis(6);", `J:core/src/block_creation_loop.rs:84` "const BLOCK_PRODUCTION_BUFFER: Duration = Duration::from_millis(50);". [verified: cite, V9]
- Default scheduler is still `GreedyScheduler`: `J:core/src/banking_stage.rs:670` "// Both block production methods currently route to the greedy scheduler.", `J:core/src/banking_stage.rs:677` "spawn_scheduler!(scheduler);". Its only functional change is a pre-check against accounts locked by in-flight bundles: `J:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:271` "// Check bundle account locks doesn't have it yet", reads conflict with bundle write locks `J:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:274` "if l_account_locks.write_locks().contains_key(lock) {", writes with bundle write or read locks `J:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:280` "|| l_account_locks.read_locks().contains_key(lock)"; a hit returns `J:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:275` "return Err(TransactionSchedulingError::UnschedulableConflicts);" (set aside and retried in a later pass). [verified: cite]
- Bundle stage interaction: runs on its own thread `J:core/src/bundle_stage.rs:412` "solBundleStgTx"; the regular scheduler is not paused. It pre-locks up to a window of bundles `J:core/src/bundle_stage.rs:629` "const BUNDLE_WINDOW_SIZE: NonZeroUsize = NonZeroUsize::new(10).unwrap();" through the account locker the scheduler consults (`J:core/src/bundle_stage/bundle_account_locker.rs:104` "/// used in BankingStage during TransactionBatch construction to ensure that BankingStage"). It consumes only while the leader decision is `Consume` and atomic batches are enabled: `J:core/src/bundle_stage.rs:587` "match decision_maker.make_atomic_consume_or_forward_decision() {". On a new slot it first runs tip-program maintenance: `J:core/src/bundle_stage.rs:633` "if bank.slot() != *last_tip_update_slot {". A bundle executes all-or-nothing `J:core/src/bundle_stage/bundle_consumer.rs:306` "all_or_nothing: true," and is recorded with one `record_transactions` call `J:core/src/bundle_stage/bundle_consumer.rs:384` "measure_us!(self.transaction_recorder.record_transactions(", so a bundle is one entry on the same record channel. It uses the same cost reservation as regular batches `J:core/src/bundle_stage/bundle_consumer.rs:145` "QosService::select_and_accumulate_transaction_costs(", with no separate CU reservation found in the bundle code. A bundle that hits an account-in-use clash is retryable: `J:core/src/bundle_stage.rs:897` "account in use, or PoH record error, it's retryable". Bundles are not ordered by the regular priority formula (bundle storage is separate: `J:core/src/bundle_stage.rs:448` "BundleStorage::with_capacity(2_000)"). [verified: cite]
- Where packets enter: TPU/QUIC packets go to `FetchStageManager`, which "intercepts" them: `J:core/src/tpu.rs:217` "// If relayer is connected, packets are dropped. If not, packets are forwarded to sigverify.", forwarding only in the original-TPU state `J:core/src/proxy/fetch_stage_manager.rs:425` "matches!(self.current_tpu_state.tpu_type, TpuConnectionType::Original)". BAM has highest TPU priority, relayer second: `J:core/src/proxy/fetch_stage_manager.rs:266` "// BAM has the highest priority.", `J:core/src/proxy/fetch_stage_manager.rs:278` "// Relayer has second priority". Relayer packets enter sigverify directly `J:core/src/proxy/relayer_stage.rs:427` ".send(packet_batch)"; block-engine packets go to sigverify, or straight to banking when trusted: `J:core/src/proxy/block_engine_stage.rs:995` "if trust_packets {". Bundles come from the block-engine stream through `J:core/src/tpu.rs:355` "unverified_bundle_sender," into `J:core/src/tpu.rs:365` "let bundle_sigverify_stage = BundleSigverifyStage::new(", not through the banking channel. [verified: cite]
- Regular transactions that touch the tip-payment program are dropped before scheduling: the program id is added to the filter set `J:core/src/tpu.rs:414` "filter_keys.insert(tip_manager.tip_payment_program_id());", which the banking stage receives (`J:core/src/tpu.rs:451` "filter_keys.clone(),") and applies in the check workers (`A:core/src/banking_stage/transaction_scheduler/receive_and_buffer.rs:88` "PacketHandlingError::FilterKey,"). Tip-program maintenance runs on the bundle thread (`J:core/src/bundle_stage.rs:738` "fn handle_tip_programs("), so no code orders it before output of the regular scheduler. [verified: cite]
- Delay ("speed bump"): the validator code has no hold on regular transactions: zero matches for "speed bump" in rs/md and the only `sleep` calls in the packet path are connection back-off and test code (V12). The only validator-side delay constant in the path is a 60 s wait before switching the advertised TPU to a relayer: `J:core/src/proxy/fetch_stage_manager.rs:32` "const RELAYER_TPU_ENABLE_DELAY: Duration = Duration::from_secs(60);" (a switch delay, not a per-transaction delay). The relayer (separate repository, master as fetched) has a configurable packet delay with default `RLY:transaction-relayer/src/main.rs:133` "#[arg(long, env, default_value_t = 50)]" for `packet_delay_ms`. Per Jito/BAM statements, the relayer delay was 200 ms, was reduced to 50 ms in June 2025, and Jito turned off its self-hosted relayers in early August 2025 (from docs D2, D3). Which mainnet validators currently route through a delaying relayer: cannot be determined from here. [verified: cite, V12; from docs D2, D3]
- BAM mode: the standard controller schedules only when BAM is NOT connected: `J:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:571` "self.bam_controller == bam_connected", `J:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:315` "if !self.scheduling_enabled() {". A separate BAM scheduler thread `J:core/src/banking_stage.rs:722` "solBamSched" runs FIFO over a prio-graph (`J:core/src/banking_stage/transaction_scheduler/bam_scheduler.rs:2` "/// schedules them to workers in a FIFO, account-aware manner. This is facilitated by the"), with batch priority a decreasing counter `J:core/src/banking_stage/transaction_scheduler/bam_receive_and_buffer.rs:916` "self.next_fifo_priority = self.next_fifo_priority.saturating_sub(1);" and its own workers `J:core/src/banking_stage/transaction_scheduler/bam_scheduler.rs:63` "pub(in crate::banking_stage) const NUM_BAM_WORKERS: usize = 8;". In BAM mode the scheduler budget is unbounded, not paced: `J:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:333` "u64::MAX". BAM docs state the validator executes the received stream in the received order and that TPU transactions go through BAM (from docs D4). The ordering inside a BAM batch stream is decided off-box in the BAM node: cannot be determined from here. [verified: cite; from docs D4]
- Alpenglow gate for atomic batches: `J:core/src/banking_stage/decision_maker.rs:75` "if require_atomic_bank && !state.atomic_batches_enabled() {" (bundles and BAM batches wait until the optimistic parent is confirmed). Records carry a `reschedule_on_sad_handover` flag (`J:poh/src/transaction_recorder.rs:52` "`reschedule_on_sad_handover` must be false when the transactions have all-or-nothing"), and only flagged records are accumulated for re-injection (`J:core/src/block_creation_loop.rs:756` "if optimistic_parent.is_some() && record.reschedule_on_sad_handover {"); bundle records are sent with `false` (`J:core/src/bundle_stage/bundle_consumer.rs:384` "measure_us!(self.transaction_recorder.record_transactions(" and its third argument on the following lines, V15). [verified: cite, V15]
- v4.4.0-jito keeps the same bundle pre-check `J44:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:185` "&self.bundle_account_locker," and the BAM gate `J44:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:628` "self.bam_controller == bam_connected", and has the Agave 4.4.0 tie-break `J44:core/src/banking_stage/transaction_scheduler/transaction_priority_id.rs:32` ".then_with(|| other.arrival_order.cmp(&self.arrival_order))". [verified: cite]

## 4. Rakurai

- Source is partly public. The client repository (fork of Jito, one patch commit on top of the Jito commit above) is public; the scheduler is NOT in it. The tree links a prebuilt library `R:core/build.rs:44` "cargo:rustc-link-lib=rakurai_scheduler" and calls it over FFI `R:core/src/banking_stage.rs:354` "fn run_rakurai_scheduler(". Docs say the binary is downloaded after authenticating (`R:rakurai_docs/validators/setup_and_build.md:92` "Before running the scheduler, you must **authenticate** and download the correct binary for your OS and release version."). Scheduling logic: cannot be determined from here (binary not obtained; fetching it requires an authenticated validator activation account, which I did not attempt). [verified: cite]
- Public claims: `R:README.md:13` "It incorporates heuristics-based **transaction scheduling** and other optimization techniques to efficiently process high-value transactions" and `R:rakurai_docs/transaction_inclusion/tips.md:53` "The scheduler weighs reward (tip + fees) relative to estimated compute cost, similar to Solana's standard priority formula." Tips to eight tip accounts act as additional "virtual priority" (from docs D1). The exact formula, tie-break and ordering inside blocks: cannot be determined from here. [verified: cite; from docs D1]
- Public client still contains the Jito code paths: both the closed scheduler and the standard `GreedyScheduler` thread are spawned (`R:core/src/banking_stage.rs:1189` "let rakurai_scheduler_handle = run_rakurai_scheduler(", `R:core/src/banking_stage.rs:1353` "spawn_scheduler!(scheduler);"), and the controller calls closed functions to decide state (`R:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:130` "fn check_state("). Which one schedules in a given slot: cannot be determined from here. Default client mode: `R:core/src/validator.rs:199` "RakuraiJito,". [verified: cite]
- Priority function is public and extended to also return the reward: `R:core/src/transaction_priority.rs:21` "/// P = R / (1 + C)", `R:core/src/transaction_priority.rs:65` "reward,". Tie-break in v4.3.2-rakurai.1 is the pre-4.4 (priority, id) order (no `arrival_order`, V9); v4.4.0-rakurai.0 has it (V9). The closed scheduler may not use this container order: cannot be determined from here. [verified: cite, V9]
- Public block-end timing differs from Agave and Jito: `R:core/src/block_creation_loop.rs:79` "const TIME_TO_COMPLETE_BLOCK_BROADCAST: Duration = Duration::from_millis(0);", `R:core/src/block_creation_loop.rs:85` "const BLOCK_PRODUCTION_BUFFER: Duration = Duration::from_millis(0);", `R:core/src/block_creation_loop.rs:88` "const FIRST_SLOT_START_DELAY: Duration = Duration::from_millis(15);", `R:core/src/block_creation_loop.rs:92` "const SLOT_DURATION_EXTENSION: Duration = Duration::from_millis(4);", used as `R:core/src/block_creation_loop.rs:630` "wait_for_first_slot_start(block_timer);" (a thread sleep before the first bank of a window, `R:core/src/block_creation_loop.rs:497` "thread::sleep(remaining);") and in `R:core/src/block_creation_loop.rs:484` ".saturating_add(FIRST_SLOT_START_DELAY)". With 200 ms slots the deadlines are 219, 423, 627, 831 ms after the window timer (V8). Same logic with renamed constants in v4.4.0-rakurai.0 (`R44:core/src/block_creation_loop.rs:87` "const SLOT_ALIGNMENT_ADJUSTMENT: Duration = Duration::from_millis(15);"). [verified: cite, V8]
- What I tried to find scheduler source: cloned `rakurai-io/rakurai-validator` at both release tags and searched the tree (no `rakurai_scheduler` directory under `core/src/banking_stage/`, submodules are protos, programs, sdk and parking_lot only, V16); cloned `rakurai-io/rakurai-agave` default branch (41fcaa9d1e7a31d6b578d8313a9e5b3d2e756c0b, last commit 2024-06-26, workspace version 2.1.0; stale, holds an upstream-style `prio_graph_scheduler.rs`, not the v4.3.x client; V16); fetched docs.rakurai.io pages (D1). I did not attempt the authenticated scheduler download. [verified: V16; from docs D1]

## 5. Open questions (cannot be determined from here)

- Rakurai scheduler: priority, tie-break, batching and thread policy (closed binary).
- BAM node ordering rules and whether a given mainnet validator is BAM-connected, relayer-connected or neither at a given time (runtime configuration).
- Fraction of mainnet leaders on 4.3.x vs 4.4.x builds at a given slot (only version strings from `getClusterNodes` are available to the architect).
- Whether the order in which `getBlock` returns transactions equals the entry order described here: not examined in this document.
- Actual wall-clock timing of check workers, scheduler passes and record completion on a live leader: not measured here.

## 6. Web sources

- D1: https://docs.rakurai.io/docs/services/rakurai_jito_private/readme (fetched 2026-10-30): Rakurai describes "heuristics-based transaction scheduling", its client as a fork of the jito-solana client, and the scheduler as a library.
- D2: https://bam.dev/blog/supporting-ibrl-fast-and-predictable-execution-on-solana (fetched 2026-10-30): relayer speed bump of 200 ms, reduced to 50 ms in June 2025, Jito turned off its self-hosted relayers in early August 2025.
- D3: https://jito-foundation.gitbook.io/mev/jito-relayer/features (web search excerpt, 2026-10-30): the relayer sends transactions to the validator "with configurable delay".
- D4: https://bam.dev/docs/bam/bam-overview (fetched 2026-10-30): BAM validator executes received transactions in the exact order received; direct TPU transactions are processed through BAM.

## 7. Commands run

- V1: `ls core/src/banking_stage/transaction_scheduler/` in the A checkout lists: batch_id_generator, check_worker, greedy_scheduler, in_flight_tracker, mod, receive_and_buffer, scheduler, scheduler_common, scheduler_controller, scheduler_error, scheduler_metrics, transaction_priority_id, transaction_state, transaction_state_container (no prio-graph scheduler file).
- V2: `git clone --filter=blob:none --depth 1 --branch <tag> <url> <dir>` for each row of the table; `git -C <dir> rev-parse HEAD` gave the hashes in section 0. Tags found with `git ls-remote --tags https://github.com/jito-foundation/jito-solana | grep 4.3.2` (v4.3.2-jito, v4.3.2-jito.0) and `git ls-remote --tags https://github.com/rakurai-io/rakurai-validator`.
- V3: `git -C jito-4.3.2 rev-parse 013a430^` gave a203300045b405f86c9c84308b2eae76af69ac3b (after `git fetch --deepen=30`); `git diff --shortstat a203300 013a430` gave "235 files changed, 35931 insertions(+), 1783 deletions(-)".
- V4: after `git fetch --deepen=3` in the Rakurai checkout, `git log --format='%h %an %s' -4` shows c74a67f "Rakurai Patch" above 013a430 "Jito Patch"; `git diff --shortstat 013a430 HEAD` gave "315 files changed, 53631 insertions(+), 2502 deletions(-)".
- V5: `git diff --shortstat 013a430 7037b4f` gave "11 files changed, 662 insertions(+), 53 deletions(-)"; `git diff --name-only 013a430 7037b4f` lists Cargo.lock files, ci/do-audit.sh, poh/src/poh_recorder.rs, rpc files.
- V6: JSON-RPC `getAccountInfo` (finalized) on feature accounts, read-only; decoded activation slot: reduce_slot_time_to_350ms 440208000, 300ms 441936000, 250ms 447552000, 200ms 454464000, raise_block_limits_to_100m 435888000, alpenglow 459648000. Genesis hash from `getGenesisHash` was 5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d; `getVersion` returned solana-core 4.3.2 from the endpoint.
- V7: `getBlockTime` at finalized slot-100 and 4000 slot numbers earlier: 4000 slots, 854 s, 213.5 ms per slot number (skipped slots included).
- V8: arithmetic (`bash tools/calc.sh`, integer division as in Rust): MAX_BLOCK_UNITS/4 = 15000000; per thread with 4 workers = 3750000; 400-50 = 350; 200-50 = 150; 30000000*100/60 = 50000000; 12000000*100/60 = 20000000; 50000000/350 = 142857; 50000000/150 = 333333; Agave deadlines for slot index 0..3 at 200 ms: 144, 344, 544, 744; Rakurai deadlines ((200+4)*(i+1)+15): 219, 423, 627, 831.
- V9: `bash tools/v9.sh` (diff line counts A vs A44 for the listed files; `arrival_order` occurrence counts per tree: 0 in A, J, R; 4 in A44, A44-rc.1, J44, J44-rc.1, R44; A vs J changed lines: transaction_priority.rs 0, greedy_scheduler.rs 151, scheduler_controller.rs 315, receive_and_buffer.rs 78, decision_maker.rs 103, record_channels.rs 77).
- V10: `sha256sum` of fetched files: clock 3.2.0 `lib.rs` 2ed8fbb22ec832b1ddfecf85b906101ec3486721d8691dad331356c1afb1d036 (from raw.githubusercontent.com anza-xyz/solana-sdk tag clock@v3.2.0; version taken from `grep -n 'name = "solana-clock"' -A 1 Cargo.lock`); jito-relayer `main.rs` 8acb0eb4aba90239e18a12cd173c9bb895d0a673992943321f81e597dff85015.
- V11: JSON-RPC `getSlotLeaders` for 16 slots starting at a multiple of 4: runs of identical consecutive leaders were [4, 4, 4, 4].
- V12: in the J checkout, `grep -rniE 'speed.?bump' --include=*.rs --include=*.md .` gave 0 lines; `grep -n "sleep(" ...` over greedy_scheduler.rs, scheduler_controller.rs, receive_and_buffer.rs, bundle_stage.rs, relayer_stage.rs, fetch_stage_manager.rs lists only relayer_stage.rs:142, 172 (connection back-off) and fetch_stage_manager.rs:614, 637, 762 (test code).
- V13: JSON-RPC `getClusterNodes` (read-only), version histogram of gossip nodes (all nodes, not stake-weighted, client type not distinguishable): 3924 nodes; 1979 report 4.3.2, 383 report 4.4.0-rc.1, 368 report 4.3.0, 280 report 4.4.0.
- V14: `sed -n 36,66p core/src/transaction_priority.rs` in the A checkout (function body of `calculate_priority_and_cost`).
- V15: `sed -n 380,392p core/src/bundle_stage/bundle_consumer.rs` in the J checkout shows the `record_transactions(` call with arguments `bank.bank_id()`, `processed_transactions`, `false`.
- V16: in the R checkout `ls core/src/banking_stage/` (shows alpenglow_timing, committer, consume_worker, consumer, decision_maker, house_keeper, latest_validator_vote_packet, leader_slot_metrics, leader_slot_timing_metrics, postpack_confirmation_config, progress_tracker, qos_service, reward_distributor, scheduler_messages, scheduler_update_notifier, tpu_to_pack, transaction_scheduler, virtual_priority_config, vote_packet_receiver, vote_storage, vote_worker) and `cat .gitmodules` (jito-protos/protos, jito-protos/bam-protos, rakurai_programs, solana-sdk, parking_lot); in the rakurai-agave checkout `git rev-parse HEAD`, `git log -1`, `grep -m1 '^version' Cargo.toml`, `ls core/src/banking_stage/transaction_scheduler`.

## 8. Citation check

Each row re-runs `sed -n 'LINEp' FILE | grep -F -- 'QUOTE'` against the pinned checkout (K as in section 0). Generated by a script that extracts every `K:path:LINE` "quote" pair from this document.

| Result | Ref | Quote |
|---|---|---|
| PASS | A:core/src/validator.rs:215 | pub enum BlockProductionMethod { |
| PASS | A:core/src/validator.rs:217 | #[default] |
| PASS | A:core/src/validator.rs:218 | CentralSchedulerGreedy, |
| PASS | A:validator/src/commands/run/args.rs:1198 | .default_value(BlockProductionMethod::default().into()) |
| PASS | A:core/src/validator.rs:213 | #[strum(serialize_all =  |
| PASS | A:core/src/validator.rs:233 | is deprecated and will be removed in a future release |
| PASS | A:core/src/banking_stage.rs:491 | \| BlockProductionMethod::CentralSchedulerGreedy => { |
| PASS | A:core/src/banking_stage.rs:588 | // Both block production methods currently route to the greedy scheduler. |
| PASS | A:validator/src/commands/run/args.rs:1227 | enable-scheduler-bindings |
| PASS | A:core/src/banking_stage.rs:496 | BankingControlMsg::External { session } => self.spawn_external(session), |
| PASS | A:core/src/banking_stage.rs:85 | const DEFAULT_NUM_WORKERS: NonZeroUsize = NonZeroUsize::new(4).unwrap(); |
| PASS | A:validator/src/cli/thread_args.rs:260 | block-production-num-workers |
| PASS | A:validator/src/cli/thread_args.rs:264 | BankingStage::default_num_workers().get() |
| PASS | A:core/src/banking_stage.rs:84 | const MAX_NUM_WORKERS: NonZeroUsize = NonZeroUsize::new(64).unwrap(); |
| PASS | A:core/src/banking_stage.rs:518 | NUM_CHECK_WORKERS: NonZeroUsize = NonZeroUsize::new(8).unwrap(); |
| PASS | A:core/src/banking_stage.rs:544 | threads.push(self.spawn_vote_worker()); |
| PASS | A:core/src/banking_stage.rs:578 | solCoWorker{id:02} |
| PASS | A:core/src/banking_stage.rs:598 | solBnkTxSched |
| PASS | A:core/src/banking_stage.rs:519 | const CHANNEL_CAPACITY: usize = 10_000; |
| PASS | A:core/src/tpu.rs:286 | non_vote_sender, |
| PASS | A:core/src/sigverify_stage.rs:67 | total_dropped_below_priority_floor: Arc<AtomicUsize>, |
| PASS | A:core/src/sigverify_stage.rs:158 | scheduler_priority_floor: Option<Arc<SchedulerPriorityFloor>>, |
| PASS | A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:44 | const SATURATION_BUFFER_PCT: u8 = 99; |
| PASS | A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:46 | const DESATURATION_BUFFER_PCT: u8 = 95; |
| PASS | A:core/src/banking_stage/transaction_scheduler/receive_and_buffer.rs:332 | const MAX_PACKET_RECEIVES: usize = 512; |
| PASS | A:core/src/banking_stage/transaction_scheduler/check_worker.rs:47 | precheck_transaction(bytes, &banks.root_bank, &banks.working_bank, &filter_keys); |
| PASS | A:core/src/banking_stage/transaction_scheduler/receive_and_buffer.rs:97 | calculate_priority_and_cost(working_bank, &view, &transaction_configuration); |
| PASS | A:core/src/banking_stage/transaction_scheduler/receive_and_buffer.rs:487 | let transaction_id = container.insert_map_only(state); |
| PASS | A:core/src/transaction_priority.rs:21 | /// P = R / (1 + C) |
| PASS | A:core/src/transaction_priority.rs:59 | const MULTIPLIER: u64 = 1_000_000; |
| PASS | A:core/src/transaction_priority.rs:62 | .saturating_mul(MULTIPLIER) |
| PASS | A:core/src/transaction_priority.rs:63 | .saturating_div(cost.saturating_add(1)), |
| PASS | A:core/src/transaction_priority.rs:39 | u64::from(transaction_configuration.compute_unit_limit), |
| PASS | A:cost-model/src/cost_model.rs:56 | pub fn calculate_cost_for_executed_transaction |
| PASS | A:core/src/transaction_priority.rs:40 | transaction_configuration.loaded_accounts_data_size_limit, |
| PASS | A:cost-model/src/transaction_cost.rs:19 | pub fn sum(&self) -> u64 { |
| PASS | A:cost-model/src/block_cost_limits.rs:10 | pub const SIGNATURE_COST: u64 = COMPUTE_UNIT_TO_US_RATIO * 24; |
| PASS | A:cost-model/src/block_cost_limits.rs:18 | pub const WRITE_LOCK_UNITS: u64 = COMPUTE_UNIT_TO_US_RATIO * 10; |
| PASS | A:cost-model/src/cost_model.rs:155 | WRITE_LOCK_UNITS.saturating_mul(num_write_locks) |
| PASS | A:cost-model/src/cost_model.rs:182 | transaction.instruction_data_len() / (INSTRUCTION_DATA_BYTES_COST as u16) |
| PASS | A:cost-model/src/block_cost_limits.rs:8 | pub const COMPUTE_UNIT_TO_US_RATIO: u64 = 30; |
| PASS | A:compute-budget-instruction/src/compute_budget_instruction_details.rs:125 | \|\| self.calculate_default_compute_unit_limit(feature_set), |
| PASS | A:runtime-transaction/src/transaction_meta.rs:124 | priority_fee_lamports: config.priority_fee.unwrap_or(0), |
| PASS | A:compute-budget/src/compute_budget_limits.rs:63 | (compute_unit_price as u128).saturating_mul(compute_unit_limit as u128); |
| PASS | A:compute-budget/src/compute_budget_limits.rs:65 | .saturating_add(MICRO_LAMPORTS_PER_LAMPORT.saturating_sub(1) as u128) |
| PASS | A:fee/src/lib.rs:55 | signature_count.saturating_mul(lamports_per_signature) |
| PASS | A:core/src/transaction_priority.rs:51 | .calculate_reward_and_burn_fee_details(&CollectorFeeDetails::from(fee_details)) |
| PASS | A:core/src/transaction_priority.rs:52 | .get_deposit(); |
| PASS | A:runtime/src/bank/fee_distribution.rs:101 | let burn = fee_details.transaction_fee * self.burn_percent() / 100; |
| PASS | A:runtime/src/bank/fee_distribution.rs:104 | .saturating_add(fee_details.transaction_fee.saturating_sub(burn)); |
| PASS | A:runtime/src/bank/fee_distribution.rs:103 | .priority_fee |
| PASS | A:runtime/src/bank/fee_distribution.rs:109 | // NOTE: burn percent is statically 50% |
| PASS | A:core/src/banking_stage/transaction_scheduler/transaction_state_container.rs:45 | priority_queue: BTreeSet<TransactionPriorityId>, |
| PASS | A:core/src/banking_stage/transaction_scheduler/transaction_state_container.rs:162 | self.priority_queue.pop_last() |
| PASS | A:core/src/banking_stage/transaction_scheduler/transaction_priority_id.rs:4 | #[derive(Copy, Clone, Debug, PartialEq, Eq, PartialOrd, Ord)] |
| PASS | A:core/src/banking_stage/transaction_scheduler/transaction_state_container.rs:270 | let transaction_id = entry.key(); |
| PASS | A44:core/src/banking_stage/transaction_scheduler/transaction_state_container.rs:428 | assert_eq!(priority_id.id, removed.id); |
| PASS | A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:206 | measure_us!(self.decision_maker.make_consume_or_forward_decision()); |
| PASS | A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:254 | self.receive_completed()?; |
| PASS | A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:256 | let _scheduled = self.process_transactions(&decision, cost_pacer.as_ref(), &now)?; |
| PASS | A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:257 | if decision.bank().is_none() { |
| PASS | A:core/src/banking_stage/decision_maker.rs:65 | if let Some(working_bank) = state.working_bank() { |
| PASS | A:core/src/banking_stage/decision_maker.rs:66 | BufferedPacketsDecision::Consume(working_bank.clone()) |
| PASS | A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:303 | BufferedPacketsDecision::Consume(_bank) => { |
| PASS | A:core/src/banking_stage/decision_maker.rs:85 | // PoH tick height no longer advances after Alpenglow activation. |
| PASS | A:core/src/banking_stage/decision_maker.rs:95 | if slots_until_leader < FORWARD_TRANSACTIONS_TO_LEADER_AT_SLOT_OFFSET { |
| PASS | A:core/src/banking_stage/decision_maker.rs:97 | } else if slots_until_leader < HOLD_TRANSACTIONS_SLOT_OFFSET { |
| PASS | EXT:clock/src/lib.rs:111 | pub const FORWARD_TRANSACTIONS_TO_LEADER_AT_SLOT_OFFSET: u64 = 2; |
| PASS | EXT:clock/src/lib.rs:112 | pub const HOLD_TRANSACTIONS_SLOT_OFFSET: u64 = 20; |
| PASS | A:core/src/banking_stage/decision_maker.rs:91 | if current_slot > last_leader_slot { |
| PASS | A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:335 | BufferedPacketsDecision::ForwardAndHold => 0, |
| PASS | A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:336 | BufferedPacketsDecision::Hold => 0, |
| PASS | A:core/src/banking_stage/transaction_scheduler/receive_and_buffer.rs:336 | let should_check = !matches!(decision, BufferedPacketsDecision::Forward); |
| PASS | A:core/src/banking_stage/transaction_scheduler/receive_and_buffer.rs:408 | stats.num_dropped_without_parsing += 1; |
| PASS | A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:327 | BufferedPacketsDecision::Forward => { |
| PASS | A:core/src/banking_stage.rs:87 | const TOTAL_BUFFERED_PACKETS: usize = 100_000; |
| PASS | A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:169 | let container_capacity = TOTAL_BUFFERED_PACKETS; |
| PASS | A:core/src/banking_stage/transaction_scheduler/transaction_state_container.rs:196 | self.priority_queue.pop_first() |
| PASS | A:core/src/banking_stage/transaction_scheduler/transaction_state_container.rs:42 | /// a new transaction, the lowest priority transaction will be dropped. |
| PASS | A:core/src/banking_stage/transaction_scheduler/transaction_state_container.rs:204 | self.held_transactions.push(priority_id); |
| PASS | A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:217 | self.container.flush_held_transactions(); |
| PASS | A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:248 | detection_time: now, |
| PASS | A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:221 | let block_limit = cost_tracker.get_block_limit(); |
| PASS | A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:535 | let allocation_per_milli = self.block_limit / fill_time.as_millis() as u64; |
| PASS | A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:537 | allocation_per_milli * millis_since_detection |
| PASS | A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:543 | target.saturating_sub(self.shared_block_cost.load()) |
| PASS | A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:63 | const DEFAULT_SCHEDULER_PACING_NON_FILL_TIME_MILLIS: u64 = 50; |
| PASS | A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:65 | NonZeroU64::new(DEFAULT_MS_PER_SLOT - DEFAULT_SCHEDULER_PACING_NON_FILL_TIME_MILLIS).unwrap(); |
| PASS | EXT:clock/src/lib.rs:77 | static_assertions::const_assert_eq!(DEFAULT_MS_PER_SLOT, 400); |
| PASS | A:validator/src/commands/run/args.rs:1203 | block-production-pacing-fill-time-millis |
| PASS | A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:227 | let fill_time = self.config.scheduler_pacing.fill_time(); |
| PASS | A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:229 | pacing_fill_time.as_nanos() > b.ns_per_slot |
| PASS | A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:236 | self.config.scheduler_pacing = SchedulerPacing::FillTimeMillis( |
| PASS | A:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:249 | fill_time, |
| PASS | A:runtime/src/slot_params.rs:175 | cost_tracker_limits: CostTrackerLimits::new(12_000_000, 30_000_000, 50_000_000), |
| PASS | A:runtime/src/bank.rs:4918 | params.cost_limits(self.feature_set.snapshot().raise_block_limits_to_100m); |
| PASS | A:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:50 | /// Dead-simple scheduler that is efficient and will attempt to schedule |
| PASS | A:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:51 | /// in priority order, scheduling anything that can be immediately |
| PASS | A:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:42 | target_scheduled_cus: MAX_BLOCK_UNITS / 4, |
| PASS | A:cost-model/src/block_cost_limits.rs:27 | pub const MAX_BLOCK_UNITS_SIMD_0256: u64 = 60_000_000; |
| PASS | A:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:100 | let target_cu_per_thread = self.config.target_scheduled_cus / num_threads as u64; |
| PASS | A:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:43 | max_scanned_transactions_per_scheduling_pass: 100_000, |
| PASS | A:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:87 | // Subtract any in-flight compute units from the budget. |
| PASS | A:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:194 | budget = budget.saturating_sub(cost); |
| PASS | A:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:137 | let Some(id) = container.pop() else { |
| PASS | A:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:164 | Err(TransactionSchedulingError::UnschedulableConflicts) => { |
| PASS | A:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:166 | self.unschedulables.push(id); |
| PASS | A:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:229 | container.push_ids_into_queue(self.unschedulables.drain(..)); |
| PASS | A:scheduling-utils/src/thread_aware_account_locks.rs:162 | /// If only write-locked, then only the thread holding the write lock is schedulable. |
| PASS | A:scheduling-utils/src/thread_aware_account_locks.rs:98 | .ok_or(TryLockError::MultipleConflicts)?; |
| PASS | A:scheduling-utils/src/thread_aware_account_locks.rs:101 | return Err(TryLockError::ThreadNotAllowed); |
| PASS | A:scheduling-utils/src/thread_aware_account_locks.rs:104 | let thread_id = thread_selector(schedulable_threads); |
| PASS | A:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:104 | if self.common.consume_work_senders[thread_id].is_full() |
| PASS | A:core/src/banking_stage/transaction_scheduler/scheduler_common.rs:155 | batch_cus_per_thread[thread_id] + in_flight_cus_per_thread[thread_id], |
| PASS | A:core/src/banking_stage/transaction_scheduler/scheduler_common.rs:159 | .min_by(\|a, b\| a.1.cmp(&b.1).then_with(\|\| a.2.cmp(&b.2))) |
| PASS | A:core/src/banking_stage/transaction_scheduler/scheduler_common.rs:316 | .unlock_accounts(write_account_locks, read_account_locks, thread_id); |
| PASS | A:core/src/banking_stage/consumer.rs:33 | pub const TARGET_NUM_TRANSACTIONS_PER_BATCH: usize = 64; |
| PASS | A:core/src/banking_stage/transaction_scheduler/scheduler_common.rs:217 | self.consume_work_senders[thread_index] |
| PASS | A:core/src/banking_stage/consume_worker.rs:76 | match self.consume_receiver.try_recv() { |
| PASS | A:core/src/banking_stage/consume_worker.rs:120 | let output = self.consumer.process_and_record_aged_transactions( |
| PASS | A:core/src/banking_stage/consume_worker.rs:110 | return Ok(ProcessingStatus::CouldNotProcess(work)); |
| PASS | A:core/src/banking_stage/consumer.rs:201 | QosService::select_and_accumulate_transaction_costs( |
| PASS | A:core/src/banking_stage/qos_service.rs:68 | let mut reserving_cost = CostModel::calculate_cost(tx, feature_set); |
| PASS | A:core/src/banking_stage/consumer.rs:210 | bank.prepare_sanitized_batch_with_results( |
| PASS | A:core/src/banking_stage/consumer.rs:320 | measure_us!(bank.load_and_execute_transactions( |
| PASS | A:core/src/banking_stage/consumer.rs:424 | self.committer.commit_transactions( |
| PASS | A:core/src/banking_stage/consumer.rs:275 | // locking failure due to vote conflict or jito - immediately retry. |
| PASS | A:core/src/banking_stage/qos_service.rs:175 | cost_tracker.update_execution_cost( |
| PASS | A:core/src/banking_stage/consumer.rs:362 | if processing_result.was_processed() { |
| PASS | A:core/src/banking_stage/consumer.rs:364 | processed_transactions.push(tx.to_versioned_transaction()); |
| PASS | A:core/src/banking_stage/consumer.rs:381 | .record_transactions(bank.bank_id(), processed_transactions) |
| PASS | A:poh/src/transaction_recorder.rs:110 | .try_send(Record::new(mixin, transactions, bank_id)) |
| PASS | A:poh/src/record_channels.rs:33 | let (sender, receiver) = bounded(CAPACITY); |
| PASS | A:poh/src/record_channels.rs:19 | /// Transaction processing threads (workers/vote thread) send records, and |
| PASS | A:poh/src/record_channels.rs:97 | // Grab lock on `transaction_indexes` here to ensure we are sending |
| PASS | A:poh/src/poh_recorder.rs:386 | Entry { |
| PASS | A:poh/src/poh_recorder.rs:389 | transactions, |
| PASS | A:poh/src/poh_service.rs:124 | Post Alpenglow migration, not starting PohService |
| PASS | A:core/src/block_creation_loop.rs:284 | let record_receiver = match record_receiver_receiver.recv() { |
| PASS | A:core/src/block_creation_loop.rs:6 | this is the only thread that will touch the |
| PASS | A:core/src/block_creation_loop.rs:740 | recv(ctx.record_receiver.inner()) -> msg => { |
| PASS | A:core/src/block_creation_loop.rs:748 | ctx.poh_recorder.write().unwrap().record( |
| PASS | A:core/src/block_creation_loop.rs:454 | Returns the elapsed leader-window time at which |
| PASS | A:core/src/block_creation_loop.rs:456 | Duration::from_nanos_u128(bank.ns_per_slot_at_slot(slot)) |
| PASS | A:core/src/block_creation_loop.rs:457 | .saturating_mul((leader_slot_index(slot) as u32).saturating_add(1)) |
| PASS | A:core/src/block_creation_loop.rs:78 | const TIME_TO_COMPLETE_BLOCK_BROADCAST: Duration = Duration::from_millis(6); |
| PASS | A:core/src/block_creation_loop.rs:84 | const BLOCK_PRODUCTION_BUFFER: Duration = Duration::from_millis(50); |
| PASS | A:core/src/block_creation_loop.rs:773 | shutdown_and_drain_record_receiver(&ctx.poh_recorder, &mut ctx.record_receiver, None)?; |
| PASS | A:core/src/block_creation_loop.rs:833 | w_poh_recorder.tick_alpenglow(max_tick_height, footer)?; |
| PASS | A:core/src/block_creation_loop.rs:698 | // Don't timeout until we've received ParentReady. |
| PASS | A:core/src/block_creation_loop.rs:745 | accumulated_txs.extend(record.transactions.iter().cloned()); |
| PASS | A:core/src/block_creation_loop.rs:1035 | rescheduling {} txs after sad leader handover for slot {slot} |
| PASS | A:core/src/block_creation_loop.rs:1045 | .send(banking_packet_batch) |
| PASS | A:core/src/block_creation_loop.rs:1285 | fn create_and_insert_leader_bank( |
| PASS | A:core/src/block_creation_loop.rs:1091 | fn start_leader_wait_for_parent_replay( |
| PASS | A:core/src/block_creation_loop.rs:1373 | ctx.poh_recorder.write().unwrap().set_bank(tpu_bank); |
| PASS | A:core/src/block_creation_loop.rs:1383 | // Wakeup banking stage |
| PASS | A44:core/src/banking_stage.rs:85 | const DEFAULT_NUM_WORKERS: NonZeroUsize = NonZeroUsize::new(4).unwrap(); |
| PASS | A44:core/src/banking_stage.rs:87 | const TOTAL_BUFFERED_PACKETS: usize = 100_000; |
| PASS | A44:core/src/block_creation_loop.rs:78 | const TIME_TO_COMPLETE_BLOCK_BROADCAST: Duration = Duration::from_millis(6); |
| PASS | A44:core/src/block_creation_loop.rs:84 | const BLOCK_PRODUCTION_BUFFER: Duration = Duration::from_millis(50); |
| PASS | A44:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:90 | const DEFAULT_SCHEDULER_PACING_NON_FILL_TIME_MILLIS: u64 = 50; |
| PASS | A44:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:43 | target_scheduled_cus: MAX_BLOCK_UNITS / 4, |
| PASS | A44:core/src/banking_stage/transaction_scheduler/transaction_priority_id.rs:25 | .then_with(\|\| other.arrival_order.cmp(&self.arrival_order)) |
| PASS | A44:core/src/banking_stage/transaction_scheduler/transaction_priority_id.rs:52 | // Equal priority then compare by arrival order, oldest first |
| PASS | A44:core/src/banking_stage/transaction_scheduler/transaction_state_container.rs:278 | let arrival_order = self.next_arrival_order; |
| PASS | A44:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:304 | // A slot transition gates only new scheduling. Check-result processing, |
| PASS | A44:core/src/banking_stage/transaction_scheduler/scheduler_common.rs:213 | target_slot: slot, |
| PASS | A44:core/src/banking_stage/consumer.rs:324 | let tx_execution_guard = bank.try_enter_transaction_execution(); |
| PASS | J:core/src/transaction_priority.rs:21 | /// P = R / (1 + C) |
| PASS | J:core/src/block_creation_loop.rs:78 | const TIME_TO_COMPLETE_BLOCK_BROADCAST: Duration = Duration::from_millis(6); |
| PASS | J:core/src/block_creation_loop.rs:84 | const BLOCK_PRODUCTION_BUFFER: Duration = Duration::from_millis(50); |
| PASS | J:core/src/banking_stage.rs:670 | // Both block production methods currently route to the greedy scheduler. |
| PASS | J:core/src/banking_stage.rs:677 | spawn_scheduler!(scheduler); |
| PASS | J:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:271 | // Check bundle account locks doesn't have it yet |
| PASS | J:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:274 | if l_account_locks.write_locks().contains_key(lock) { |
| PASS | J:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:280 | \|\| l_account_locks.read_locks().contains_key(lock) |
| PASS | J:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:275 | return Err(TransactionSchedulingError::UnschedulableConflicts); |
| PASS | J:core/src/bundle_stage.rs:412 | solBundleStgTx |
| PASS | J:core/src/bundle_stage.rs:629 | const BUNDLE_WINDOW_SIZE: NonZeroUsize = NonZeroUsize::new(10).unwrap(); |
| PASS | J:core/src/bundle_stage/bundle_account_locker.rs:104 | /// used in BankingStage during TransactionBatch construction to ensure that BankingStage |
| PASS | J:core/src/bundle_stage.rs:587 | match decision_maker.make_atomic_consume_or_forward_decision() { |
| PASS | J:core/src/bundle_stage.rs:633 | if bank.slot() != *last_tip_update_slot { |
| PASS | J:core/src/bundle_stage/bundle_consumer.rs:306 | all_or_nothing: true, |
| PASS | J:core/src/bundle_stage/bundle_consumer.rs:384 | measure_us!(self.transaction_recorder.record_transactions( |
| PASS | J:core/src/bundle_stage/bundle_consumer.rs:145 | QosService::select_and_accumulate_transaction_costs( |
| PASS | J:core/src/bundle_stage.rs:897 | account in use, or PoH record error, it's retryable |
| PASS | J:core/src/bundle_stage.rs:448 | BundleStorage::with_capacity(2_000) |
| PASS | J:core/src/tpu.rs:217 | // If relayer is connected, packets are dropped. If not, packets are forwarded to sigverify. |
| PASS | J:core/src/proxy/fetch_stage_manager.rs:425 | matches!(self.current_tpu_state.tpu_type, TpuConnectionType::Original) |
| PASS | J:core/src/proxy/fetch_stage_manager.rs:266 | // BAM has the highest priority. |
| PASS | J:core/src/proxy/fetch_stage_manager.rs:278 | // Relayer has second priority |
| PASS | J:core/src/proxy/relayer_stage.rs:427 | .send(packet_batch) |
| PASS | J:core/src/proxy/block_engine_stage.rs:995 | if trust_packets { |
| PASS | J:core/src/tpu.rs:355 | unverified_bundle_sender, |
| PASS | J:core/src/tpu.rs:365 | let bundle_sigverify_stage = BundleSigverifyStage::new( |
| PASS | J:core/src/tpu.rs:414 | filter_keys.insert(tip_manager.tip_payment_program_id()); |
| PASS | J:core/src/tpu.rs:451 | filter_keys.clone(), |
| PASS | A:core/src/banking_stage/transaction_scheduler/receive_and_buffer.rs:88 | PacketHandlingError::FilterKey, |
| PASS | J:core/src/bundle_stage.rs:738 | fn handle_tip_programs( |
| PASS | J:core/src/proxy/fetch_stage_manager.rs:32 | const RELAYER_TPU_ENABLE_DELAY: Duration = Duration::from_secs(60); |
| PASS | RLY:transaction-relayer/src/main.rs:133 | #[arg(long, env, default_value_t = 50)] |
| PASS | J:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:571 | self.bam_controller == bam_connected |
| PASS | J:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:315 | if !self.scheduling_enabled() { |
| PASS | J:core/src/banking_stage.rs:722 | solBamSched |
| PASS | J:core/src/banking_stage/transaction_scheduler/bam_scheduler.rs:2 | /// schedules them to workers in a FIFO, account-aware manner. This is facilitated by the |
| PASS | J:core/src/banking_stage/transaction_scheduler/bam_receive_and_buffer.rs:916 | self.next_fifo_priority = self.next_fifo_priority.saturating_sub(1); |
| PASS | J:core/src/banking_stage/transaction_scheduler/bam_scheduler.rs:63 | pub(in crate::banking_stage) const NUM_BAM_WORKERS: usize = 8; |
| PASS | J:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:333 | u64::MAX |
| PASS | J:core/src/banking_stage/decision_maker.rs:75 | if require_atomic_bank && !state.atomic_batches_enabled() { |
| PASS | J:poh/src/transaction_recorder.rs:52 | `reschedule_on_sad_handover` must be false when the transactions have all-or-nothing |
| PASS | J:core/src/block_creation_loop.rs:756 | if optimistic_parent.is_some() && record.reschedule_on_sad_handover { |
| PASS | J:core/src/bundle_stage/bundle_consumer.rs:384 | measure_us!(self.transaction_recorder.record_transactions( |
| PASS | J44:core/src/banking_stage/transaction_scheduler/greedy_scheduler.rs:185 | &self.bundle_account_locker, |
| PASS | J44:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:628 | self.bam_controller == bam_connected |
| PASS | J44:core/src/banking_stage/transaction_scheduler/transaction_priority_id.rs:32 | .then_with(\|\| other.arrival_order.cmp(&self.arrival_order)) |
| PASS | R:core/build.rs:44 | cargo:rustc-link-lib=rakurai_scheduler |
| PASS | R:core/src/banking_stage.rs:354 | fn run_rakurai_scheduler( |
| PASS | R:rakurai_docs/validators/setup_and_build.md:92 | Before running the scheduler, you must **authenticate** and download the correct binary for your OS and release version. |
| PASS | R:README.md:13 | It incorporates heuristics-based **transaction scheduling** and other optimization techniques to efficiently process high-value transactions |
| PASS | R:rakurai_docs/transaction_inclusion/tips.md:53 | The scheduler weighs reward (tip + fees) relative to estimated compute cost, similar to Solana's standard priority formula. |
| PASS | R:core/src/banking_stage.rs:1189 | let rakurai_scheduler_handle = run_rakurai_scheduler( |
| PASS | R:core/src/banking_stage.rs:1353 | spawn_scheduler!(scheduler); |
| PASS | R:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:130 | fn check_state( |
| PASS | R:core/src/validator.rs:199 | RakuraiJito, |
| PASS | R:core/src/transaction_priority.rs:21 | /// P = R / (1 + C) |
| PASS | R:core/src/transaction_priority.rs:65 | reward, |
| PASS | R:core/src/block_creation_loop.rs:79 | const TIME_TO_COMPLETE_BLOCK_BROADCAST: Duration = Duration::from_millis(0); |
| PASS | R:core/src/block_creation_loop.rs:85 | const BLOCK_PRODUCTION_BUFFER: Duration = Duration::from_millis(0); |
| PASS | R:core/src/block_creation_loop.rs:88 | const FIRST_SLOT_START_DELAY: Duration = Duration::from_millis(15); |
| PASS | R:core/src/block_creation_loop.rs:92 | const SLOT_DURATION_EXTENSION: Duration = Duration::from_millis(4); |
| PASS | R:core/src/block_creation_loop.rs:630 | wait_for_first_slot_start(block_timer); |
| PASS | R:core/src/block_creation_loop.rs:497 | thread::sleep(remaining); |
| PASS | R:core/src/block_creation_loop.rs:484 | .saturating_add(FIRST_SLOT_START_DELAY) |
| PASS | R44:core/src/block_creation_loop.rs:87 | const SLOT_ALIGNMENT_ADJUSTMENT: Duration = Duration::from_millis(15); |

Totals, computed with `grep -c '^| PASS |' FILE` and `grep -c '^| FAIL |' FILE` after an independent second run of every row (parser plus sed and grep -F): PASS = 235, FAIL = 0.
