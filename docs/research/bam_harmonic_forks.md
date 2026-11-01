# Transaction ordering in BAM, Harmonic and related validator forks

Date: 2026-10-30. Scope: primary-source mechanisms only; no conclusions about any experiment.

Labels. `[Dn]`: from docs (URL in Sources) fetched 2026-10-30. `[Cn]`: verified by the command in Sources. Code claims read `tree:path:LINE` "quote" `[ID]` at the pinned commit in Sources and are re-grepped in "Citation check". "Operator docs" means written by the project that runs the system; "marketing" means promotional claims. Gaps say "cannot be determined from here".

## 1. Summary

Stake share and version counts: [C2] (666 current vote accounts joined to gossip `clientId`).

| clientId (id), stake | Base client | Who decides order (per primary sources) | Ordering policy as documented | Source quality |
|---|---|---|---|---|
| AgaveBam (6), 35.19% | Jito-Solana (Agave fork), BAM session live | BAM Node (run by Jito Labs [D7]) while state is `Connected`; validator executes in received order (section 3) | Node: fee per CU in about 50 ms batches plus plugins [D5][D7]; validator: arrival-order key, lock-aware parallelism | code (validator), operator docs (node); node code not public |
| JitoLabs (1), 24.55% | Jito-Solana, no live BAM session | Local Agave scheduler plus Block Engine bundles [D2] | greedy scheduler `jito:core/src/banking_stage.rs:670` "// Both block production methods currently route to the greedy scheduler." [J19] | code, operator docs |
| FireBAM (12), 1.94% | Firedancer/Frankendancer fork [D2] | BAM Node while healthy, local pack tile otherwise [D9] | as AgaveBam | code, operator docs |
| HarmonicAgave (10), 21.69% | Salsa: Agave fork plus `harmonic-scheduler` | Harmonic builder streams microbatches; local fallback if no block by 50% of slot | Operator picks `fba` (default; 50 ms batches by priority fee and tip), `fifo`, `mrev` (proprietary) [D12] | operator docs (builder), code (validator) |
| HarmonicFiredancer (9), 8.75% | Samba: Firedancer fork | as HarmonicAgave | as HarmonicAgave | as HarmonicAgave |
| Firedancer (5), 5.56% | Firedancer | Local pack tile | not examined | none |
| Agave (3), 0.99% | Agave | Local scheduler | default `agave:core/src/validator.rs:217` "#[default]" [A33] `agave:core/src/validator.rs:218` "CentralSchedulerGreedy," [A30] | code |
| Rakurai (8), 1.17% | jito-solana fork plus closed scheduler library | Local Rakurai scheduler | Reward (tip plus fees) per estimated cost `rak:rakurai_docs/transaction_inclusion/tips.md:53` "The scheduler weighs reward (tip + fees) relative to estimated compute cost" [K02] | operator docs; scheduler closed |
| Raiku (13), 0.08% | not stated in sources read | Raiku Ackermann Node auctions; client injects | Highest bid first [D14] | marketing; no code found |
| Unknown(N) | unknown | unknown | none | none |

Key points. `clientId` is self-reported and unverified (section 2). AgaveBam and FireBAM are live states that flip with the BAM session (section 2). With BAM connected, the validator advertises the BAM Node's TPU and drops packets reaching its own (section 3). Harmonic validators advertise a Remote TPU while streaming and build locally only as fallback (section 4).

## 2. clientId mapping

Enum at `agave:version/src/client_ids.rs:4` "pub enum ClientId {" [A01] (agave v4.3.2). Decoding, `version/src/client_ids.rs`:

| id | line and quote |
|---|---|
| 0 | `:48` "0u16 => Self::SolanaLabs," [A02] |
| 1 | `:49` "1u16 => Self::JitoLabs," [A03] |
| 2 | `:50` "2u16 => Self::Frankendancer," [A04] |
| 3 | `:51` "3u16 => Self::Agave," [A05] |
| 4 | `:52` "4u16 => Self::AgavePaladin," [A06] |
| 5 | `:53` "5u16 => Self::Firedancer," [A07] |
| 6 | `:54` "6u16 => Self::AgaveBam," [A08] |
| 7 | `:55` "7u16 => Self::Sig," [A09] |
| 8 | `:56` "8u16 => Self::Rakurai," [A10] |
| 9 | `:57` "9u16 => Self::HarmonicFiredancer," [A11] |
| 10 | `:58` "10u16 => Self::HarmonicAgave," [A12] |
| 11 | `:59` "11u16 => Self::HarmonicFrankendancer," [A13] |
| 12 | `:60` "12u16 => Self::FireBAM," [A14] |
| 13 | `:61` "13u16 => Self::Raiku," [A15] |

Anything else: `agave:version/src/client_ids.rs:62` "_ => Self::Unknown(client)," [A16]. The shared registry lists 0 to 14, adding `14,FrankenBAM` (`reg:client-ids.csv:16` "14,FrankenBAM" [R05]), so Agave v4.3.2 prints id 14 as `Unknown(14)` (by [A16]). Its commit message says Frankendancer and Firedancer BAM "have been running with the same client ID (12)" [C8]. FireBAM v26.10.5 emits 12 (`firebam:src/disco/bam/fd_bam_tile.c:196` "desired_client_id = use_bam ? FD_GOSSIP_CONTACT_INFO_CLIENT_FIRE_BAM : FD_GOSSIP_CONTACT_INFO_CLIENT_FIREDANCER;" [FB01]); Firedancer v26.10.5 defines the same values (`fd:src/flamenco/gossip/fd_gossip_message.h:118` "FD_GOSSIP_CONTACT_INFO_CLIENT_FIRE_BAM" [F02]).

Derivation. `agave:rpc/src/rpc.rs:3737` "fn get_cluster_nodes(&self, meta: Self::Metadata) -> Result<Vec<RpcContactInfo>> {" [A20] calls `agave:rpc/src/rpc.rs:3751` "cluster_info.get_node_version(contact_info.pubkey())" [A21] (`agave:gossip/src/cluster_info.rs:1115` ".map(ContactInfo::version)" [A25]), reading the gossip `ContactInfo` field `agave:gossip/src/contact_info.rs:103` "version: solana_version::Version," [A26]. The client is copied by `agave:rpc/src/rpc.rs:3756` "Some(version.client().clone())," [A22] and stringified by `agave:rpc/src/rpc.rs:3788` "client_id: client_id.map(|id| format!("{id}"))," [A23]. The answer is the RPC node's local gossip table at that moment.

Self-reported? Yes. Each build hard-codes its id: Agave `agave:version/src/client_ids.rs:95` "Self::Agave" [A19], Jito `jito:version/src/client_ids.rs:95` "Self::JitoLabs" [J01], Salsa `salsa43:version/src/client_ids.rs:95` "Self::HarmonicAgave" [H01], Rakurai `rak:version/src/client_ids.rs:95` "Self::Rakurai" [K01], Samba `samba:src/discof/gossip/fd_gossip_tile.c:771` "FD_GOSSIP_CONTACT_INFO_CLIENT_HARMONIC_FIREDANCER" [S01], Firedancer `fd:src/discof/gossip/fd_gossip_tile.c:710` "version.client      = FD_GOSSIP_CONTACT_INFO_CLIENT_FIREDANCER;" [F03]; Agave's comment: `agave:version/src/client_ids.rs:94` "// Other client implementations need to modify this line." [A18]. Gossip values are signed by the node identity (`agave:gossip/src/crds_value.rs:79` ".verify(self.pubkey().as_ref(), self.signable_data().borrow())" [A28]), but `ContactInfo::sanitize` checks only the wallclock (`agave:gossip/src/contact_info.rs:639` "if self.wallclock >= MAX_WALLCLOCK {" [A27]) and decoding accepts any value ([A16]). So a node can publish any 16-bit value under its identity (verified in code; not tested on the network). Observed: 3909 gossip nodes, with `Unknown(N)` for ids outside the registry [C1]; one identity went from `Unknown(39384)` to `Unknown(36699)` within four minutes [C3]. The architect's `Unknown(38009)` is absent from both snapshots [C3]; whether it is the staked 0.08% `Unknown(39384)` [C2] cannot be determined from here.

Live states. Jito-Solana's BAM manager defines fallback JitoLabs and BAM id AgaveBam (`jito:core/src/bam_manager.rs:132` "let fallback_client_id = ClientId::JitoLabs;" [J02], `jito:core/src/bam_manager.rs:134` "let bam_client_id = ClientId::AgaveBam;" [J03]). It sets JitoLabs while no connection exists (`jito:core/src/bam_manager.rs:163` "Self::set_client_id(&dependencies.cluster_info, fallback_client_id);" [J04]) and AgaveBam once one exists (`jito:core/src/bam_manager.rs:284` "Self::set_client_id(&dependencies.cluster_info, bam_client_id);" [J05]). `Connected`, which drives scheduling, comes after drain states (`jito:core/src/bam_dependencies.rs:35` "DrainingBlockEngine = 2," [J29]), so the label can precede actual BAM scheduling. FireBAM does the same ([FB01]). Harmonic, Agave and Firedancer ids are constants. Rakurai's fork carries the BAM manager (`rak:core/src/bam_manager.rs:140` "let fallback_client_id = ClientId::JitoLabs;" [K09]) but skips it in its default mode (`rak:core/src/validator.rs:203` "#[default]" [K10], `rak:core/src/bam_manager.rs:158` "ClientMode::RakuraiJito" [K05]). Two snapshots four minutes apart showed no AgaveBam/JitoLabs flips among 3899 shared identities [C3]. Whether the BAM Node connects only around leader windows cannot be determined from here; its docs say it connects validators "that have upcoming leader slots" [D2].

## 3. BAM (Block Assembly Marketplace, Jito)

What it is. A BAM Node ingests transactions and bundles, validates and sequences them, and sends them to the leader, which must "Execute all received transactions in that exact order" [D1]. Nodes run in AMD SEV-SNP enclaves and validators "delegate scheduling decisions to specialized external BAM nodes" [D3]. Today trust "still resides on Jito’s reputation"; open sourcing "the BAM scheduling code" is listed as remaining work [D7]. Mainnet: AgaveBam 355 validators (169 on 4.4.0-rc.1, 128 on 4.3.2, 55 on 4.4.0), FireBAM 20 (17 on 26.10.5, 3 on 26.10.4) [C2].

Who orders, by what rule (documented). The BAM Node: "50ms batches, ordering by fee density" [D5]; "by fees per CU plus any custom Plugin ordering" [D7]. The maker plugin goes first in each batch, then "bundles and regular transactions compete on the same priority score" [D6]. A 2025 forum proposal describes sub-50 ms auctions with linear compute-unit pacing [D8]; whether current cannot be determined from here. Source quality: operator docs and blog posts.

Source availability. No public BAM Node repository: `git ls-remote` on guessed names failed [C6]. Public: the wire API (`bamproto:bam_api.proto:69` "rpc InitSchedulerStream(stream SchedulerMessage) returns (stream SchedulerResponse) {}" [B01]), the validator client (jito-solana), and `bam-plugins` (docs and protos only) [C7].

Does the validator reorder? Not by fee, in code. Received batches get a descending counter (`jito:core/src/banking_stage/transaction_scheduler/bam_receive_and_buffer.rs:149` "next_fifo_priority: u64::MAX," [J22], `jito:core/src/banking_stage/transaction_scheduler/bam_receive_and_buffer.rs:908` "self.next_fifo_priority = self.next_fifo_priority.saturating_sub(1);" [J23]), so priority is arrival order. The scheduler is `jito:core/src/banking_stage/transaction_scheduler/bam_scheduler.rs:2` "schedules them to workers in a FIFO, account-aware manner." [J25]; non-conflicting batches may run in parallel, which the operator states as "Except when write locks are non-conflicting and can be parallelized" [D4]. Validator-local additions: the tip-program crank runs before batches are admitted (`jito:core/src/banking_stage/transaction_scheduler/bam_scheduler.rs:318` "&& !tips.process_tip_programs(consumer, admission_bank, builder)" [J27]) and votes use a separate worker (`jito:core/src/banking_stage.rs:569` "threads.push(self.spawn_vote_worker(bundle_account_locker.clone()));" [J30]); their position relative to BAM batches in the entry stream cannot be determined from here.

Disconnected. Exactly one controller schedules: `jito:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:628` "self.bam_controller == bam_connected" [J17]. The local one is the greedy scheduler (`jito:core/src/banking_stage.rs:670` "// Both block production methods currently route to the greedy scheduler." [J19]). If BAM drops mid-slot, leftover BAM batches are drained (`jito:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:372` "When BAM disconnects while we're still leader" [J31]) and new ones discarded (`jito:core/src/banking_stage/transaction_scheduler/bam_receive_and_buffer.rs:894` "stats.num_dropped_without_parsing += batch.txns_max_age.len();" [J32]). Docs agree: "Internal Agave Scheduler" versus "External BAM Scheduler" [D2]; FireBAM "uses its normal transaction ingress, including Block Engine" when BAM is disabled or unhealthy [D9]. These lines exist in v4.3.2-jito, v4.4.0-rc.1-jito and v4.4.0-jito, and 352 of 355 AgaveBam validators report versions matching those tags [C2][C7].

TPU path. When `Connected`, the gossiped TPU becomes the BAM Node's: `jito:core/src/proxy/fetch_stage_manager.rs:266` "// BAM has the highest priority." [J10], `jito:core/src/proxy/fetch_stage_manager.rs:272` "tpu_type: TpuConnectionType::Bam," [J12]. Agave's RPC leader lookup (`ClusterTpuInfo`) targets the leader's gossiped QUIC TPU (`agave:rpc/src/cluster_tpu_info.rs:104` "node.tpu(Protocol::QUIC)?" [A31], `agave:rpc/src/cluster_tpu_info.rs:112` "if let Some(addr) = self.recent_peers.get(leader)" [A32]). Packets reaching the validator's own TPU are forwarded only in the Original TPU state: `jito:core/src/proxy/fetch_stage_manager.rs:407` "if self.should_forward_packets() {" [J13], `jito:core/src/proxy/fetch_stage_manager.rs:426` "matches!(self.current_tpu_state.tpu_type, TpuConnectionType::Original)" [J14]. Inference: RPC-forwarded and direct transactions for a Connected BAM leader reach the BAM Node, not the local scheduler; operator docs say the same [D1]. FireBAM's source states "jito-solana's fetch stage drops TPU packets while it advertises BAM's" (`firebam:src/disco/pack/fd_pack_tile_bam.c:967` "jito-solana's fetch stage drops TPU packets while it advertises BAM's" [FB03]). Third-party senders with other leader-address sources cannot be assessed from here.

## 4. Harmonic (HarmonicAgave, HarmonicFiredancer)

Who and what. Harmonic runs a hosted system (Remote TPU, Block Engine, builders) and publishes Salsa (Agave fork) and Samba (Firedancer fork); validators must be whitelisted by the Harmonic team [D10]. Salsa reports `salsa43:version/src/client_ids.rs:95` "Self::HarmonicAgave" [H01]; Samba reports `samba:src/discof/gossip/fd_gossip_tile.c:771` "FD_GOSSIP_CONTACT_INFO_CLIENT_HARMONIC_FIREDANCER" [S01]. Mainnet: HarmonicAgave 46 validators (38 on 4.3.2, 8 on 4.4.0-rc.1), HarmonicFiredancer 39 (22 on 26.10.5, 17 on 26.10.4); all reported versions match the checked tags [C2].

Ordering (documented). The bound builder runs the strategy the validator selects and emits "sequenced microbatches" [D11]. `fba`: 50 ms buffers sorted by "descending priority fees and tips"; `fifo`: "strict arrival order" at the builder; `mrev`: "selection logic is proprietary"; custom on request [D12]. Flag: `salsa43:harmonic-scheduler/src/config.rs:46` "default_value = "fba"" [H03]. Builder code is not public: cannot be determined from here.

Builder versus local (code). The validator uses the builder's block only if it arrives before half the slot: Salsa 4.3.2 `salsa43:harmonic-scheduler/src/validator/scheduler.rs:36` "const BLOCK_STAGE_TIMEOUT_PERCENT: u8 = 50;" [H04], 4.4.0 `salsa44:harmonic-scheduler/src/scheduler/leader.rs:28` "const BLOCK_STAGE_TIMEOUT_PERCENT: u8 = 50;" [H13]; Samba `samba:src/disco/pack/fd_pack_tile.c:1292` "ctx->harmonic_threshold_ns = ctx->slot_start_ns + slot_dur/2L;" [S02]. Otherwise it builds a fallback block (`salsa43:harmonic-scheduler/src/validator/scheduler.rs:478` "no block received, building fallback block: slot={}" [H07]; Samba `samba:src/disco/pack/fd_pack_tile.c:327` "if( !ctx->harmonic || harmonic_state==HARMONIC_MODE_FALLBACK ) {" [S03]). Replay keeps builder order subject to account conflicts (`salsa44:harmonic-scheduler/src/scheduler/block_stage.rs:82` "Bundles waiting on nothing, earliest first" [H18]); votes interleave late (4.3.2: `salsa43:harmonic-scheduler/src/validator/scheduler.rs:38` "VOTE_STAGE_START_PERCENT: u8 = 94;" [H19]). Builder-provided: the sequenced microbatches. Validator-local: the tip crank (4.4.0: signed through the validator's admin RPC, `salsa44:harmonic-scheduler/src/admin_rpc.rs:123` "signTipCrank" [H21]), votes, and the fallback block.

Ordinary RPC-forwarded transactions. While streaming, the validator gossips the Remote TPU as its TPU: Salsa 4.3.2 waits for Remote TPU, block engine and IPC (`salsa43:harmonic-scheduler/src/admin_rpc.rs:224` "// Wait for remote_tpu, block_engine, and validator IPC to all come up" [H10]) and restores its own TPU on failure (`salsa43:harmonic-scheduler/src/admin_rpc.rs:234` "set_tpu(client, original_tpu).await?;" [H12]); Salsa 4.4.0 `salsa44:harmonic-scheduler/src/remote_tpu.rs:47` "Remote TPU QUIC address advertised in gossip as the validator's TPU" [H17]; Samba `samba:src/disco/bundle/fd_bundle_tile.c:355` "Publish TPU connection update to gossip link." [S05]. Inference with [A31]: RPC senders reach the Remote TPU, which forwards to builders and keeps "a local copy" for the validator [D11]. The local scheduler orders them only in fallback, and the rule depends on version: Salsa 4.3.2 holds them in a deque (`salsa43:harmonic-scheduler/src/validator/fallback_stage.rs:70` "txs: VecDeque<SharableTransactionRegion>," [H08]) and takes `salsa43:harmonic-scheduler/src/validator/fallback_stage.rs:157` "self.txs.pop_front()" [H09], i.e. insertion order; Salsa 4.4.0 ranks bundles above packets and packets "by what they pay" (`salsa44:harmonic-scheduler/src/scheduler/storage.rs:103` "Bundles rank above packets, older ones higher; packets by what they pay" [H14]).

On-chain marker. The crank memo carries the strategy: Salsa `salsa44:harmonic-scheduler/src/block_engine.rs:525` "SchedulingStrategy::Fba => "FBA"," [H20]; Samba `samba:src/disco/pack/fd_pack_tile.c:315` "SCHEDULING_STRATEGY_FBA:  return "FBA";" [S07], but in fallback Samba writes its local strategy string (`samba:src/disco/pack/fd_pack_tile.c:328` "schedule_strategy_strings[ ctx->strategy ]" [S06]). Observed: in the first slot of 40 sampled leader windows of Harmonic-labelled nodes, all 40 carried a memo (35 "FBA", 5 "MRV", 0 "FIF"); 0 of 6 windows of other clients did [C4]. It sat at transaction 0 in 24 of the 40 [C4]. Firedancer's own crank memo is "PRF" or "BAL" (`fd:src/disco/pack/fd_pack_tile.c:73` "{ "PRF", "BAL" }" [F05]); sampled FireBAM windows showed "BAL" at transaction 0 in 4 of 4, Firedancer-labelled in 2 of 4 ("BAL", "BDL"; "BDL" is not in Firedancer v26.10.5), AgaveBam and JitoLabs in 0 of 7 [C5]. The string alone is not unique: "FBA" also appeared at transactions 415 and 309 of two Firedancer-labelled blocks [C5].

## 5. Rakurai and Raiku

Rakurai. Operator docs call it a "high-performance Solana validator node" with "heuristics-based transaction scheduling" [D13]; it is a fork of jito-solana running a scheduler library (`rak:rakurai_docs/validators/README.md:5` "Rakurai is a fork of jito-solana running the Rakurai scheduler library" [K08]). A tip is a transfer to one of eight tip accounts [D13], and the "scheduler weighs reward (tip + fees) relative to estimated compute cost" (`rak:rakurai_docs/transaction_inclusion/tips.md:53` "The scheduler weighs reward (tip + fees) relative to estimated compute cost" [K02]). The scheduler is a downloaded binary (`rak:rakurai_docs/validators/setup_and_build.md:90` "Download Rakurai Scheduler Binary" [K07]) called through `extern "C"` hooks (`rak:core/src/banking_stage/transaction_scheduler/scheduler_controller.rs:157` "fn check_state(" [K06]), so the exact ordering cannot be determined from here. Mainnet: 9 validators, 1.17% [C2]. Quality: operator docs and public client code; scheduler closed.

Raiku. Company material describes an off-chain "Ackermann Node" running AOT and JIT auctions and a sidecar that delivers reserved transactions at the assigned slot; within a slot "The highest bid goes first", ties by earlier arrival (JIT) or booking (AOT) [D14]. A 2026 article says "the validator running Raiku's client injects the reserved transaction into block production ahead of the general queue" [D15]; the docs site now presents a "Raiku custom validator" [D16]. Mainnet: 1 validator, 0.08%, version 4.4.0-rc.1 [C2]. Quality: marketing; no public client code found (guessed repository names failed [C6]); whether any exists cannot be determined from here.

## 6. Not determined

BAM Node source and current policy; Harmonic builder and `mrev` rule; Rakurai scheduler and Raiku client internals; whether any mainnet node falsifies `clientId`; vote position relative to BAM or Harmonic batches; owners of `Unknown(N)`; exact commits behind each mainnet version string (tags were pinned).

## Sources

Pins (tree: repository @ tag, commit):
- agave: anza-xyz/agave v4.3.2, a203300045b405f86c9c84308b2eae76af69ac3b
- jito: jito-foundation/jito-solana v4.4.0-jito, 9a9756848e20745ab5e720741fef6c81dacbf455; also checked v4.3.2-jito, v4.4.0-rc.1-jito
- bamproto: jito-labs/bam-protos (submodule of jito), 642c49ae6da23dcbc6c0c621288d4479799a8910
- firebam: jito-foundation/firebam v26.10.5, 0c93bf01c98c39d306fbb236f1dcb8265acbfabf
- salsa43: harmonic/salsa v4.3.2-harmonic.1, 6aa195dae243c077a769092adfa7c98c633eca64; also checked v4.3.2-harmonic
- salsa44: harmonic/salsa v4.4.0-harmonic, ff0c238a11b3618bfd77afd68a73aa3afe9c2279; also checked v4.4.0-rc.1-harmonic
- samba: harmonic/samba v26.10.5-harmonic, e40e2bd2a2d7e2759cd7ccc81d10629553570126; also checked v26.10.4-harmonic
- rak: rakurai-io/rakurai-validator v4.4.0-rakurai.0, b1baabfb86b23ec699ab1bc3b20ff331fce92644; also checked v4.3.2-rakurai.0 and .1
- fd: firedancer-io/firedancer v26.10.5, 6286f99e400c1d5ac6f95b8cf36491555faa3726
- reg: solana-foundation/solana-validator-client-ids main, 01f8630a1842b1bc5410627db9a73f1a182a0cef
- bam-plugins master, 94cfb53cecbe839be498dc08b00727c199cd0b3f

Docs (fetched 2026-10-30): D1 bam.dev/docs/bam/bam-overview; D2 bam.dev/validators; D3 bam.dev/overview; D4 bam.dev/blog/the-bam-verifier-ensuring-verifiable-execution-on-solana; D5 bam.dev/blog/introducing-bams-maker-priority-plugin-sub-slot-deterministic-execution-for-onchain-market-making; D6 bam.dev/docs/bam/maker-plugin/how-it-works; D7 bam.dev/blog/bam-attestations-road-to-transparency; D8 forum.bam.dev/t/brainstorming-paths-to-ace-on-bam/28 (scheduler section only); D9 jito-foundation.gitbook.io/mev/jito-solana/firebam-setup-guide; D10 docs.harmonic.gg; D11 docs.harmonic.gg/concepts/harmonic-architecture; D12 docs.harmonic.gg/concepts/scheduling-strategies; D13 docs.rakurai.io/docs/services/rakurai_jito_private/readme; D14 raiku.com/news/aot-jit-how-to-prevent-transactions-from-failing-on-solana; D15 raiku.com/news/the-engineering-contract-part-ii-how-the-rewrite-works; D16 docs.raiku.com.

Commands (73 read-only JSON-RPC calls in total):
- C1: `getClusterNodes`, counted by `clientId`.
- C2: `getVoteAccounts` (finalized) joined to C1 on `nodePubkey`; stake share = activatedStake sum over total; versions from C1.
- C3: second `getClusterNodes` four minutes later, diffed by pubkey.
- C4: `getSlotLeaders` (600 slots from 463321777), then `getBlock` (`jsonParsed`, `maxSupportedTransactionVersion` 1) on the first slot of 40 Harmonic-labelled and 6 other leader windows; first memo equal to FBA, FIF, MRV or ???.
- C5: same scan on 15 further windows (Firedancer, FireBAM, AgaveBam, JitoLabs), memos of at most 3 characters.
- C6: `git ls-remote https://github.com/<guess>` for `bam`, `bam-client`, `bam-node`, `bam-protocol`, `bam-sdk`, `bam-api` under jito-labs and jito-foundation, and nine `raiku` names; failures ask for credentials.
- C7: `git clone --filter=blob:none --depth 1 --branch <tag>` per pin, `git rev-parse HEAD`; `find` over `bam-plugins`.
- C8: `git -C client-ids-registry show 01f8630`.

## Citation check

Command per citation (`TREE` is the pinned checkout, `LINE`, `PATH`, `QUOTE` as printed in the citation):

```
sed -n "${LINE}p" "$TREE/$PATH" | grep -qF -- "$QUOTE" && echo PASS || echo FAIL
```

Counts, computed with `grep -c '^PASS'` and `grep -c '^FAIL'` over the result file: PASS=85, FAIL=0. A first run of the checker on a deliberately wrong line number returned FAIL, so the check can fail.

Per citation: J19 PASS, A33 PASS, A30 PASS, K02 PASS, A01 PASS, A02 PASS, A03 PASS, A04 PASS, A05 PASS, A06 PASS, A07 PASS, A08 PASS, A09 PASS, A10 PASS, A11 PASS, A12 PASS, A13 PASS, A14 PASS, A15 PASS, A16 PASS, R05 PASS, FB01 PASS, F02 PASS, A20 PASS, A21 PASS, A25 PASS, A26 PASS, A22 PASS, A23 PASS, A19 PASS, J01 PASS, H01 PASS, K01 PASS, S01 PASS, F03 PASS, A18 PASS, A28 PASS, A27 PASS, J02 PASS, J03 PASS, J04 PASS, J05 PASS, J29 PASS, K09 PASS, K10 PASS, K05 PASS, B01 PASS, J22 PASS, J23 PASS, J25 PASS, J27 PASS, J30 PASS, J17 PASS, J31 PASS, J32 PASS, J10 PASS, J12 PASS, A31 PASS, A32 PASS, J13 PASS, J14 PASS, FB03 PASS, H03 PASS, H04 PASS, H13 PASS, S02 PASS, H07 PASS, S03 PASS, H18 PASS, H19 PASS, H21 PASS, H10 PASS, H12 PASS, H17 PASS, S05 PASS, H08 PASS, H09 PASS, H14 PASS, H20 PASS, S07 PASS, S06 PASS, F05 PASS, K08 PASS, K07 PASS, K06 PASS.

Cross-version: citations whose quote also occurs in the same file of every other checked tag (jito 19 of 19, rak 8 of 8, salsa43 9 of 9, salsa44 6 of 6, samba 6 of 6); absent in at least one tag: none. Line numbers may differ between tags. `this_client()` value at line 95 across the 11 checkouts (command `sed -n 95p`): Self::Agave x1; Self::JitoLabs x3; Self::HarmonicAgave x4; Self::Rakurai x3.
