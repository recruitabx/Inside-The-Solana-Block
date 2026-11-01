# Firedancer pack tile and in-block transaction order (source notes, v26.10.5)

Scope: mechanisms only. No conclusions about our experiment, no design.

**Pinned source.** Tag `v26.10.5`, commit `6286f99e400c1d5ac6f95b8cf36491555faa3726`, researched 2026-10-30. Verified: `git rev-parse HEAD` printed that hash and `git describe --tags` printed `v26.10.5` in the clone made with `git clone --filter=blob:none --depth 1 --branch v26.10.5 https://github.com/firedancer-io/firedancer` (into `/tmp/claude-0/-home-user-Inside-The-Solana-Block/8de50ae6-1ba8-5ff6-ac11-6a0da13bc5fe/scratchpad/src/firedancer`). All `path:LINE` are relative to that clone. Frankendancer's Agave side is a submodule that the clone does not check out (verified: `git submodule status` printed `-c8630b6b3666711203d53c82e5f14ed68c0917f1 agave`); I fetched a few files from that commit of `https://github.com/firedancer-io/agave` with `git fetch --depth 1 --filter=blob:none` and cite them as `agave-fd/...`.

**Source labels.** `[V]`: verified, the quote sits at the cited `path:LINE` (script in "Citation check"). `[V:Kn]`: verified by command Kn in "Commands". `[D]`: from docs https://docs.firedancer.io/guide/getting-started.html fetched 2026-10-30. `[X]`: cannot be determined from here. "Reading" marks an inference from `[V]` lines, not executed (no build allowed).

## Summary of mechanisms relevant to in-block order

- Ordering key is a static ratio, fee reward divided by estimated cost units, fixed when the transaction is inserted. It uses requested, not consumed, compute. `[V]`
- Pack keeps separate pools (votes, non-votes, bundles) plus per-hot-account penalty treaps, and is configured for one transaction per non-bundle microblock. `[V]`
- Block order equals pack scheduling order: PoH (and the Alpenglow `motor` tile) stamp microblocks strictly by a pack-assigned index, so parallel execution tiles cannot interleave the final block. Reading of the lines in section 2.4.
- Pack schedules only while leader; it keeps accepting and sorting transactions the rest of the time. `[V]`
- Default strategy `balanced` paces normal transactions through the slot; votes are exempt. `[V]`
- A block is therefore a sequence of "best eligible at that instant" picks, not a global sort. Reading.
- Randomness exists only in eviction when the pool is full, in choosing a penalty treap, and in internal seeds. `[V:K1]`

| Mechanism in source | What the block (transaction index) can show |
|---|---|
| Static fee/cost ratio, requested CUs | Each transaction's own ratio is computable from its fee fields; its consumed CUs are not what pack sorted on |
| One tx per microblock, PoH stamps by `pack_idx` | Index order is pack's scheduling order (minus transactions that did not commit); cross-tile interleaving is not visible |
| Conflicting writers serialized, later `pack_idx` for the second | Which of two same-account writers came first is visible; why (priority vs. a skip) is not |
| Scheduling only while leader, pool persists across slots | Index shows pick order, not arrival time; a high-fee late arrival can follow lower-fee earlier picks |
| Penalty treaps (writers of an account with more than 64 references) | Hot-account writers appear released one at a time, interleaved with others |
| Votes scheduled first | The Alpenglow topology has no vote-sending tile; the architect's no-votes-after-slot-459652999 observation is supplied, not checked here `[X]` |
| Randomness, equal-ratio tie order | Not visible |

## 1. Product naming and version strings

- Two validators are built from this repo: Frankendancer (hybrid with Agave code) and Firedancer (no Agave code). `README.md:27` ``**Frankendancer** A hybrid validator using parts of Firedancer and`` `README.md:32` ``**Firedancer** A full from-scratch Firedancer with no Agave code.`` `[V]`
- Release tags: `docs/getting-started:2` ``vYY.MM.PATCH` Full Firedancer releases.`` and `docs/getting-started:3` ``v0.xxx.yyyyy` Legacy Frankendancer releases.`` `[D]`
- **Full Firedancer** version comes from `src/app/firedancer/version.mk`: `src/app/firedancer/version.mk:1` ``FD_VERSION_MAJOR := 26`` and `src/app/firedancer/version.mk:3` ``FD_VERSION_PATCH := 5``. Minor is printed with two digits for major 26 and above: `src/util/fd_version.c:30` ``major>=26UL ?``. The full client's gossip tile advertises `src/discof/gossip/fd_gossip_tile.c:710` ``version.client      = FD_GOSSIP_CONTACT_INFO_CLIENT_FIREDANCER;`` and `src/discof/gossip/fd_gossip_tile.c:711` ``version.major       = (ushort)fd_major_version;``. So `26.10.5` is the full client at this tag, and `26.10.4` is the previous patch of the same release line (reading of the `vYY.MM.PATCH` scheme). `[V]`
- **Frankendancer (fdctl)** declares `src/app/fdctl/version.mk:2` ``VERSION_MINOR := 1`` and `src/app/fdctl/version.mk:3` ``VERSION_PATCH := 1``, which are inputs, not the printed string. `with-version.mk` builds minor as `src/app/fdctl/with-version.mk:13` ``FIREDANCER_VERSION_MINOR := $(VERSION_MINOR)$(call pad2,$(VERSION_PATCH))`` and patch as `src/app/fdctl/with-version.mk:29` ``FIREDANCER_VERSION_PATCH := $(or $(AGAVE_VERSION_MAJOR),0)``; `version.c` publishes them: `src/app/fdctl/version.c:19` ``fd_version_cstr = FDCTL_VERSION_CSTR;``. The Agave fork reads them over FFI (`agave-fd/version/src/v4.rs:201` ``// FIREDANCER: Report firedancer version to gossip``, `agave-fd/version/src/v4.rs:204` ``static fdctl_minor_version: u64;``) and reports client `Frankendancer`: `agave-fd/version/src/client_ids.rs:94` ``// FIREDANCER: Report client as Firedancer to gossip`` then `agave-fd/version/src/client_ids.rs:95` ``Self::Frankendancer``. The fork's workspace version is `agave-fd/Cargo.toml:141` ``version = "4.3.0"``. Hand arithmetic `[V:K7]`: `0.101.40300`. Reading: the Frankendancer string from this tag's rules is not literally `0.1.1`; `0.1.1` equals the raw `fdctl/version.mk` triple. The Makefile was not executed.
- Which client id pairs with the literal version `0.1.1` in the architect's `getClusterNodes` data `[X]`. This repo sets a client id only once for the full client `[V:K6]`; other ids appear only in a name lookup table. The version text format in this repo's RPC tile is `src/flamenco/gossip/fd_gossip_message.h:527` ``NULL, "%hu.%hu.%hu", major, minor_actual, patch );``, but the architect's data came from a mainnet RPC, not this code `[X]`.
- Frankendancer and Firedancer share one pack tile: both `main.c` register it (`src/app/fdctl/main.c:77` ``&fd_tile_pack,`` in fdctl, `src/app/firedancer/main.c:141` ``&fd_tile_pack,`` in firedancer), and the tile accepts both link-name families (`src/disco/pack/fd_pack_tile.c:1284` ``"poh_pack"``, `src/disco/pack/fd_pack_tile.c:1285` ``"pohh_pack"``, `src/disco/pack/fd_pack_tile.c:1405` ``"pack_execle" : "pack_bank"``). Execution tiles: Frankendancer `bank` `src/app/fdctl/config/default.toml:834` ``bank_tile_count = 4``, Firedancer `execle` `src/app/firedancer/config/default.toml:1054` ``execle_tile_count = 2``. `[V]`

## 2. The pack tile

### 2.1 Priority key

- Purpose: `src/disco/pack/fd_pack.h:6` ``maximize the overall profitability of the validator.``. Treap order: `src/disco/pack/fd_pack.c:233` ``The priority is given by reward/compute.``, compared by cross-multiplication: `src/disco/pack/fd_pack.c:227` ``#define COMPARE_WORSE(x,y)``. `[V]`
- Reward is the validator's share of signature fees plus the priority fee: `src/disco/pack/fd_pack.c:1040` ``ulong sig_rewards = FD_PACK_FEE_PER_SIGNATURE * txn->signature_cnt;`` with `src/disco/pack/fd_pack.h:21` ``#define FD_PACK_FEE_PER_SIGNATURE           (5000UL)``, then `src/disco/pack/fd_pack.c:1054` ``sig_rewards = sig_rewards * FD_PACK_TXN_FEE_BURN_PCT / 100UL;`` with `src/disco/pack/fd_pack.h:42` ``#define FD_PACK_TXN_FEE_BURN_PCT        50UL``, then added to the priority fee and saturated: `src/disco/pack/fd_pack.c:1062` ``? (uint)(sig_rewards + priority_rewards) : UINT_MAX;``. The priority fee is the requested CU limit times the price: `src/disco/pack/fd_compute_budget_program.h:201` ``ceil((cu_limit * micro_lamports_per_cu)/10^6)``. Reward is then divided by an allocation divisor: `src/disco/pack/fd_pack.c:1088` ``out->rewards /= (uint)divisor;``. `[V]`
- Cost is the estimated total cost units: `src/disco/pack/fd_pack.c:1063` ``out->compute_est                          = (uint)cost_estimate;``, summed as `src/disco/pack/fd_pack_cost.h:564` ``ulong total_cost = signature_cost + writable_cost +``, with `src/disco/pack/fd_pack_cost.h:88` ``#define FD_PACK_COST_PER_SIGNATURE                    (  720U)`` and `src/disco/pack/fd_pack_cost.h:92` ``#define FD_PACK_COST_PER_WRITABLE_ACCT                (  300U)``. The execution term is the requested CU limit, not usage. `[V]`
- Consumed CUs matter only for block-level accounting: `src/disco/pack/fd_pack.h:735` ``all the requested CUs, this function "rebates" them to pack so that`` `[V]`

### 2.2 Pools and penalty treaps

- Three treaps: `src/disco/pack/fd_pack.c:614` ``treap_t pending[1];``, `src/disco/pack/fd_pack.c:615` ``treap_t pending_votes[1];``, `src/disco/pack/fd_pack.c:616` ``treap_t pending_bundles[1];``. Simple votes go to the vote treap: `src/disco/pack/fd_pack.c:1581` ``if( FD_LIKELY( is_vote ) ) insert_into = pack->pending_votes;``. Bundles keep FIFO order among themselves by fudging rewards: `src/disco/pack/fd_pack.c:1761` ``order among the bundles is FIFO.`` `[V]`
- Hot accounts: `src/disco/pack/fd_pack.c:509` ``writes to an account with more than PENALTY_TREAP_THRESHOLD`` with `src/disco/pack/fd_pack.c:553` ``#define PENALTY_TREAP_THRESHOLD 64UL``. A transaction with several hot accounts picks one at random: `src/disco/pack/fd_pack.c:1550` ``fd_rng_uint_roll( pack->rng, (uint)cumulative_penalty )`` then `src/disco/pack/fd_pack.c:1563` ``ord->root = FD_ORD_TXN_ROOT_PENALTY( penalty_idx[i] );``. When a writer of that account completes, the best penalty-treap transaction moves to the main treap: `src/disco/pack/fd_pack.c:2362` ``best->root = FD_ORD_TXN_ROOT_PENDING;`` `[V]`

### 2.3 Choosing transactions for a microblock

- Pack asks for one microblock whenever an execution tile is idle, using the lowest-numbered idle tile: `src/disco/pack/fd_pack_tile.c:735` ``int i = fd_ulong_find_lsb( ctx->execle_idle_bitset );``. Budget `src/disco/pack/fd_pack_tile.c:62` ``const ulong CUS_PER_MICROBLOCK = 1600000UL;``; vote share `src/disco/pack/fd_pack_tile.c:64` ``const float VOTE_FRACTION = 1.0f;``. Order of passes: votes `src/disco/pack/fd_pack.c:2749` ``status1= fd_pack_schedule_impl( pack, pack->pending_votes,``, bundles only if no votes `src/disco/pack/fd_pack.c:2765` ``/* Bundle can't mix with votes, so only try to schedule a bundle if we``, then `src/disco/pack/fd_pack.c:2779` ``/* Fill any remaining space with non-vote transactions */``. `[V]`
- Inside a pass the treap is walked best to worst: `src/disco/pack/fd_pack.c:2044` ``treap_rev_iter_init( sched_from, pool )``. A transaction is skipped, not rejected, if it exceeds the remaining CUs (`src/disco/pack/fd_pack.c:2059` ``if( FD_UNLIKELY( cur->compute_est>cu_limit ) ) {``), touches an account in use (`src/disco/pack/fd_pack.c:2075` ``FD_PACK_BITSET_INTERSECT4_EMPTY( bitset_rw_in_use, bitset_w_in_use``), or would exceed the per-account write-cost limit (`src/disco/pack/fd_pack.c:2110` ``in_wcost_table->total_cost+cur->compute_est > max_write_cost_per_acct``). The first that passes is taken: `src/disco/pack/fd_pack.c:2164` ``/* Include this transaction in the microblock! */`` and its accounts are marked in use: `src/disco/pack/fd_pack.c:2203` ``use->in_use_by = bank_tile_mask | FD_PACK_IN_USE_WRITABLE;`` `[V]`
- Microblock size: `src/disco/pack/fd_pack_tile.c:65` ``#define EFFECTIVE_TXN_PER_MICROBLOCK 1UL``. Reading: a non-bundle microblock is the best eligible vote, else the best eligible non-vote. `[V]`

### 2.4 Execution tiles, PoH, and final order

- Each microblock gets an index: `src/disco/pack/fd_pack_tile.c:775` ``trailer->pack_idx = ctx->pack_idx;``; bundles consume one per transaction: `src/disco/pack/fd_pack_tile.c:788` ``ctx->pack_idx += fd_uint_if( trailer->is_bundle, (uint)schedule_cnt, 1U );`` and `src/discof/execle/fd_execle_tile.c:690` ``ulong execle_sig = fd_disco_execle_sig( slot, ctx->_pack_idx+i );``. `[V]`
- The PoH tile stamps only the next expected index: `src/discof/poh/fd_poh_tile.c:38` ``them in PoH in the order they are produced by pack.`` and `src/discof/poh/fd_poh_tile.c:223` ``if( FD_UNLIKELY( pack_idx!=ctx->expect_pack_idx ) ) return 1;``. Frankendancer's `pohh` does the same: `src/discoh/pohh/fd_pohh_tile.c:453` ``them in PoH in the order they are produced by pack.`` and `src/discoh/pohh/fd_pohh_tile.c:1960` ``if( FD_UNLIKELY( pack_idx!=ctx->expect_pack_idx ) ) return -1;``. Alpenglow's `motor` too: `src/discof/motor/fd_motor_tile.c:344` ``if( FD_UNLIKELY( pack_idx!=ctx->expect_pack_idx ) ) return 1;`` `[V]`
- Non-committable results are dropped before stamping: `src/discof/poh/fd_poh.c:745` ``if( FD_UNLIKELY( !(txn->flags & FD_TXN_P_FLAGS_EXECUTE_SUCCESS) ) ) continue;``; fee-only transactions are kept: `src/discof/execle/fd_execle_tile.c:386` ``the block.  It's a bit of a misnomer now that there are fee-only`` `[V]`
- Reading: block order is pack's scheduling order with failures removed. Execution tiles overlap in time, but PoH re-serializes by index.

## 3. Timing

- Scheduling is gated on leadership: `src/disco/pack/fd_pack_tile.c:641` ``if( FD_UNLIKELY( ctx->leader_slot==ULONG_MAX ) ) {`` (after `src/disco/pack/fd_pack_tile.c:640` ``/* Am I leader? */``). Inserts are not gated: `src/disco/pack/fd_pack_tile.c:1178` ``fd_pack_insert_txn_fini( ctx->pack, ctx->cur_spot, blockhash_height, &deleted )``. Config comment: `src/app/firedancer/config/default.toml:1655` ``become leader and stores them for future execution.  This`` `[V]`
- Slot end: `src/disco/pack/fd_pack_tile.c:599` ``get_done_packing( ctx, done_packing, FD_PACK_END_SLOT_REASON_TIME );`` then `src/disco/pack/fd_pack_tile.c:601` ``fd_pack_end_block( ctx->pack );``. Other end reasons: microblock cap `src/disco/pack/fd_pack_tile.c:825` ``get_done_packing( ctx, done_packing, FD_PACK_END_SLOT_REASON_MICROBLOCK );``. End-of-block resets limits only: `src/disco/pack/fd_pack.h:783` ``the per-block limits are cleared and transactions in``. The full-clear function has no caller in the pack tile `[V:K3]`. Reading: unscheduled transactions stay pending into the next slot.
- Leaders get consecutive slots (pre-Alpenglow comment): `src/discof/poh/fd_poh.h:268` ``is always given at least four (4) consecutive slots in the`` `[V]`
- Pacing is a strategy: default `src/app/firedancer/config/default.toml:1708` ``schedule_strategy = "balanced"``. In `balanced`, bundles only on tile 0 (`src/disco/pack/fd_pack_tile.c:751` ``fd_int_if( i==0,                FD_PACK_SCHEDULE_BUNDLE, 0 )``) and normal transactions only on tiles below the pacer's count (`src/disco/pack/fd_pack_tile.c:752` ``| fd_int_if( i<pacing_execle_cnt, FD_PACK_SCHEDULE_TXN,    0 );``); `perf` allows all: `src/disco/pack/fd_pack_tile.c:742` ``flags = FD_PACK_SCHEDULE_VOTE | FD_PACK_SCHEDULE_BUNDLE | FD_PACK_SCHEDULE_TXN;``. The pacer starts at leadership (`src/disco/pack/fd_pack_tile.c:1118` ``fd_pack_pacing_init( ctx->pacer, now_ticks, end_ticks``) with `src/disco/pack/fd_pack_pacing.h:48` ``pacer->ticks_per_cu = 9.0f * ticks_per_ns;``. No fixed microblock delay: `src/disco/pack/fd_pack_tile.c:38` ``#define MICROBLOCK_DURATION_NS  (0L)`` `[V]`
- Computed illustration `[V:K8]` (assumptions: 400 ms slot, nothing consumed, formula re-implemented from `fd_pack_pacing.h`): with a 30,000,000 CU block limit, the first tile is enabled at 110.0 ms and the second at 255.0 ms; with 100,000,000 both are enabled at 0 ms. Real limits and slot end are runtime values `[X]`.
- Waiting time has no fixed term: a pending transaction is released when it is the best eligible one at some scheduling attempt, after pacing allows its tile. Reading.
- Expiry lifetime: `src/disco/pack/fd_pack_tile.c:50` ``#define TRANSACTION_LIFETIME_SLOTS 151UL``. Applied at leadership: `src/disco/pack/fd_pack_tile.c:1088` ``ulong exp_cnt = fd_pack_expire_before( ctx->pack, fd_ulong_max( ctx->block_height``, and while not leader from observed block heights: `src/disco/pack/fd_pack_tile.c:917` ``if( FD_UNLIKELY( (ctx->leader_slot==ULONG_MAX) & (sig>ctx->highest_observed_block_height) ) ) {`` `[V]`

## 4. Conflicts (two writers of one account)

- In-use state is an account-to-tile bitmask with a write flag: `src/disco/pack/fd_pack.c:652` ``acct_in_use: Map from account address to bitmask indicating which`` `[V]`
- A transaction conflicting with an in-flight microblock is skipped (section 2.3); after the tile reports completion, pack clears the marks (`src/disco/pack/fd_pack_tile.c:584` ``int completed = fd_pack_microblock_complete( ctx->pack, (ulong)poll_cursor );``; `src/disco/pack/fd_pack.h:758` ``permits the scheduling of transactions that conflict with the``), and the transaction can be scheduled with a later index. `[V]`
- Reading: normally the higher ratio goes first, but if it is blocked (CU limit, write-cost limit, in-use account) a lower-ratio writer can be scheduled before it. A transaction skipped repeatedly for reasons other than account conflicts is parked: `src/disco/pack/fd_pack.c:557` ``reasons other than account conflicts) before we won't consider it`` (the comment continues "until the next slot") `[V]`

## 5. Expiry, dedup, pool size, randomness

- Pool size: `src/app/firedancer/config/default.toml:1660` ``max_pending_transactions = 65524``. When full: `src/disco/pack/fd_pack.c:1523` ``if( FD_UNLIKELY( pack->pending_txn_cnt == pack->pack_depth ) ) {``; new arrival replaces the worst of eight sampled treap minimums (`src/disco/pack/fd_pack.c:1224` ``We'll also use M=8.``, `src/disco/pack/fd_pack.c:1232` ``samples[ i ] = fd_rng_uint_roll( pack->rng, pool_max );``) or is rejected: `src/disco/pack/fd_pack.c:1527` ``if( FD_UNLIKELY( !_delete_cnt ) ) REJECT( PRIORITY );`` `[V]`
- Expired on insert: `src/disco/pack/fd_pack.c:1500` ``REJECT( EXPIRED          );``. Durable-nonce transactions get a synthetic lifetime: `src/disco/pack/fd_pack.h:49` ``#define FD_PACK_NONCE_SYNTHETIC_LIFETIME 500UL`` `[V]`
- Dedup is upstream: `src/disco/dedup/fd_dedup_tile.c:11` ``fd_dedup provides services to deduplicate multiple streams of input``, signature cache `src/app/firedancer/config/default.toml:1584` ``signature_cache_size = 33554430``. Pack drops transactions already executed elsewhere: `src/disco/pack/fd_pack_tile.c:1018` ``fd_pack_delete_transaction( ctx->pack, fd_type_pun( ctx->executed_txn_sig ) )``. A duplicate-signature reject code exists (`src/disco/pack/fd_pack.h:404` ``#define FD_PACK_INSERT_REJECT_DUPLICATE             ( -3)``) but nothing else in `src/disco/pack` uses it `[V:K2]`.
- Randomness: 24 lines use `fd_rng_` in `src/disco/pack`; only 2 are draws (`fd_rng_uint_roll`): eviction sampling above and the penalty choice in section 2.2 `[V:K1]`. The rest seed structures, e.g. `src/disco/pack/fd_pack.c:905` ``treap_seed( pool, pack_depth+extra_depth, fd_rng_ulong( rng ) );``; the tile seeds from OS entropy: `src/disco/pack/fd_pack_tile.c:1207` ``if( FD_UNLIKELY( !fd_rng_secure( &ctx->rng_seed, sizeof(uint) ) ) ) {`` `[V]`
- Ties: insert places an equal element on the greater side: `src/util/tmpl/fd_treap.c:777` ``int lt = TREAP_(lt)( pool + n, pool + i );``; the treap documents `src/util/tmpl/fd_treap.c:259` ``iterate over equal elements in "time" order, with the one``; pack iterates in reverse (section 2.3). Reading: among exactly equal ratios the most recently inserted is visited first. Not executed `[X]`.

## 6. Alpenglow

- Pack has no Alpenglow branch: the only three matching lines are comments `[V:K4]`.
- Topology swaps the PoH tile: `src/app/firedancer/topology.c:293` ``char const * poh    = alpenglow_enabled ? "motor" : "poh";``; `txsend` is built only in the non-Alpenglow branch (`src/app/firedancer/topology.c:664` ``fd_topob_tile( topo, "txsend",  "txsend",``, with `src/app/firedancer/topology.c:325` ``if( !alpenglow_enabled ) fd_topob_wksp( topo, "txsend" );``) and sends votes (`src/discof/txsend/fd_txsend_tile.c:401` ``send_vote_to_leader( fd_txsend_tile_t *  ctx,``); gossip votes off: `src/app/firedancer/topology.c:290` ``int gossip_vote_enabled = leader_enabled || ( rpc_enabled && !alpenglow_enabled );`` `[V]`
- Block layout: `src/discof/motor/fd_motor_tile.c:15` ``header | entries* | footer | alpentick``; entries use `src/discof/motor/fd_motor_tile.c:25` ``in the block has num_hashes==1.``. Ordering still by index (section 2.4).
- Slot end is relative to ParentReady: `src/discof/replay/fd_replay_tile.c:1784` ``long slot_end_ns = ctx->votor_leader->parent_ready_ns`` `src/discof/replay/fd_replay_tile.c:1786` ``- (long)FD_TARGET_SLOT_ADJUSTMENT_NS - AG_TIME_TO_COMPLETE_BROADCAST_NS;``, with `src/discof/replay/fd_replay_tile.c:105` ``#define AG_TIME_TO_COMPLETE_BROADCAST_NS (6000000L)`` and `src/flamenco/runtime/fd_slot_params.h:33` ``#define FD_TARGET_SLOT_ADJUSTMENT_NS (50000000UL)`` `[V]`
- Microblock cap is fixed: `src/discof/replay/fd_replay_tile.c:1803` ``msg->max_microblocks_in_slot = FD_POH_ALPENGLOW_MAX_MICROBLOCKS_PER_SLOT;``, `src/discof/poh/fd_poh.h:336` ``#define FD_POH_ALPENGLOW_MAX_MICROBLOCKS_PER_SLOT (131072UL)``; one tick: `src/discof/replay/fd_replay_tile.c:1797` ``one tick per block, no hash budget``. Reading: the hash-budget term of pack's dynamic cap becomes unlimited (`src/disco/pack/fd_pack_tile.c:451` ``ulong can_mixin    = fd_ulong_if( !!ctx->slot_mixin_per_tick,``).
- Enablement: `src/app/firedancer/config/default.toml:698` ``alpenglow = false``. Mainnet preset has zero `alpenglow` lines `[V:K5]`; feature and config must agree at epoch boundaries: `src/discof/replay/fd_replay_tile.c:698` ``FD_CHECK_CRIT( !is_epoch_boundary || FD_FEATURE_ACTIVE_BANK( bank, alpenglow )==!!ctx->alpenglow,``. Which nodes run Alpenglow mode `[X]`.

## Open questions

1. Client id for version `0.1.1` `[X]`.
2. Mainnet block cost limit and exact slot end `[X]`.
3. Executed tie order `[X]`.
4. Whether mainnet leaders use bundles: the bundle tile defaults to `src/app/firedancer/config/default.toml:1592` ``enabled = false`` (section `[tiles.bundle]`) `[V]`; actual mainnet use `[X]`.
5. What `getBlock` exposes of microblock boundaries `[X]`.
6. FireBAM and Harmonic forks are outside this repo `[X]`.

## Commands

- K1: `grep -rn "fd_rng_" src/disco/pack/*.c src/disco/pack/*.h | grep -v "test_\|fuzz_" | wc -l` gave 24; the same with `fd_rng_uint_roll` gave 2 (`fd_pack.c:1232`, `fd_pack.c:1550`).
- K2: `grep -rn "REJECT_DUPLICATE\b\|REJECT( *DUPLICATE" src/disco/pack | grep -v _ACCT | wc -l` gave 1 (the definition; the second alternative covers the `REJECT( reason )` macro).
- K3: `grep -c fd_pack_clear_all src/disco/pack/fd_pack_tile.c` gave 0.
- K4: `grep -rciE "alpenglow|votor" src/disco/pack/*.c src/disco/pack/*.h | grep -v :0` printed `fd_pack_tile.c:1` and `fd_microblock.h:2`, all inside comments.
- K5: `grep -c alpenglow src/app/firedancer/config/<f>`: mainnet.toml 0, mainnet-jito.toml 0, testnet.toml 1, devnet.toml 1, default.toml 2.
- K6: `grep -rn "version\.client *=" src --include=*.c | grep -v "fuzz_\|test_"` printed one line, `fd_gossip_tile.c:710`.
- K7: `printf '0.%s%02d.%s%02d%02d\n' 1 1 4 3 0` printed `0.101.40300`.
- K8: a Python re-implementation of `fd_pack_pacing.h` (enabled = int(remaining_cus / (t_end - now) * 9), max_cus = limit + 0.05 * duration / 9, in ns; first time k tiles are enabled = t_end - max_cus * 9 / k) printed 110.0 and 255.0 for the 30,000,000 limit and 0.0 and 0.0 for 100,000,000.

## Citation check

Method: for every `path:LINE` plus double-backtick quote above this section (numbered in order of appearance), read that line of the file at the pinned commit (`agave-fd/...` is the Agave fork commit, `docs/getting-started` is the saved text of the fetched docs lines), collapse whitespace, and test that the quote is a substring of the line. Script, run as `python3 -I`:

```python
import re
doc=open("firedancer_pack.md").read().split("## Citation check")[0]
for i,m in enumerate(re.finditer(r"`([^`\n]+?):(\d+)` ``([^\n]+?)``",doc),1):
    L=open(resolve(m[1])).read().split("\n")   # resolve(): clone root, agave-fd dir, or docs snippet
    ok=norm(m[3]) in norm(L[int(m[2])-1])        # norm(): collapse whitespace
    print(f"C{i:03d}:{'PASS' if ok else 'FAIL'}",end=" ")
```

Counts computed by the script: citations 131, PASS 131, FAIL 0.

C001:PASS C002:PASS C003:PASS C004:PASS C005:PASS C006:PASS C007:PASS C008:PASS C009:PASS C010:PASS C011:PASS C012:PASS C013:PASS C014:PASS C015:PASS C016:PASS C017:PASS C018:PASS C019:PASS C020:PASS C021:PASS C022:PASS C023:PASS C024:PASS C025:PASS C026:PASS C027:PASS C028:PASS C029:PASS C030:PASS C031:PASS C032:PASS C033:PASS C034:PASS C035:PASS C036:PASS C037:PASS C038:PASS C039:PASS C040:PASS C041:PASS C042:PASS C043:PASS C044:PASS C045:PASS C046:PASS C047:PASS C048:PASS C049:PASS C050:PASS C051:PASS C052:PASS C053:PASS C054:PASS C055:PASS C056:PASS C057:PASS C058:PASS C059:PASS C060:PASS C061:PASS C062:PASS C063:PASS C064:PASS C065:PASS C066:PASS C067:PASS C068:PASS C069:PASS C070:PASS C071:PASS C072:PASS C073:PASS C074:PASS C075:PASS C076:PASS C077:PASS C078:PASS C079:PASS C080:PASS C081:PASS C082:PASS C083:PASS C084:PASS C085:PASS C086:PASS C087:PASS C088:PASS C089:PASS C090:PASS C091:PASS C092:PASS C093:PASS C094:PASS C095:PASS C096:PASS C097:PASS C098:PASS C099:PASS C100:PASS C101:PASS C102:PASS C103:PASS C104:PASS C105:PASS C106:PASS C107:PASS C108:PASS C109:PASS C110:PASS C111:PASS C112:PASS C113:PASS C114:PASS C115:PASS C116:PASS C117:PASS C118:PASS C119:PASS C120:PASS C121:PASS C122:PASS C123:PASS C124:PASS C125:PASS C126:PASS C127:PASS C128:PASS C129:PASS C130:PASS C131:PASS
