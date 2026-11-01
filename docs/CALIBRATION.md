# Localnet calibration

Can the analysis recover a known answer? This calibration runs on a local Agave 4.3.2 test validator and checks the pipeline (pair design, in-block index from getBlock, Wilson interval, exact binomial test), not mainnet.

## What each condition tests

Each pair has a fee contrast (CU price 1,000 vs 1,000,000 micro-lamports) and a send position, two independent seeded coin flips. Statistics use same-slot pairs only. Transactions use the live probe template (`itb.txbuild`).

- **A, arrival-known.** Disjoint fee payers, sent through the local RPC 50 ms apart. Known answer: the first-sent transaction lands first, whatever the fee.
- **B, priority-known.** Both transactions also write one shared account W, so they conflict. They are injected directly into the local TPU over one QUIC connection (aioquic, ALPN `solana-tpu`, self-signed Ed25519 client certificate, one unidirectional stream per transaction, written back-to-back). Known answer: higher reward per cost first. A bare pair is processed in arrival order, so B is preceded by K filler transactions (priority fee 0, also writing W). A sweep of 12 configurations (30 pairs each) runs first; the best Wilson lower bound wins and is used for B on fresh pairs.
- **C, placebo.** Same as B with equal fees. The label of each transaction is a coin, so P(label 1 first) must be 0.5.

## Reproduce

```
curl -LO https://github.com/anza-xyz/agave/releases/download/v4.3.2/solana-release-x86_64-unknown-linux-gnu.tar.bz2
tar xjf solana-release-x86_64-unknown-linux-gnu.tar.bz2
./solana-release/bin/solana-test-validator --ledger ./ledger --reset --quiet --rpc-port 8899 &
# wait until getSlot answers on http://127.0.0.1:8899
pip install -e '.[test]' aioquic
python scripts/localnet_calibration.py --rpc http://127.0.0.1:8899 \
  --out data/calibration/localnet_$(date -u +%F)_final.jsonl --pairs 60 --seed 1
python scripts/localnet_calibration.py --summarize data/calibration/localnet_2026-10-30_final.jsonl
pytest tests/test_calibration_parse.py
```

It takes about 10 minutes. The script refuses non-loopback endpoints and uses only keys it generates.

## Results

Run 20261030T154029Z, seed 1, 60 pairs per condition. All 540 pairs and all 2,730 fillers landed. Values: k/n, Wilson 95% interval, exact binomial p against 0.5.

```
cond same-slot  first-sent-first                                higher-fee-first (C: label-1-first)
A    60/60      60/60 = 1.000 [0.940, 1.000] p=1.7e-18          26/60 = 0.433 [0.316, 0.559] p=3.7e-01
B    60/60      33/60 = 0.550 [0.425, 0.669] p=5.2e-01          57/60 = 0.950 [0.863, 0.983] p=6.3e-14
C    60/60      33/60 = 0.550 [0.425, 0.669] p=5.2e-01          29/60 = 0.483 [0.362, 0.607] p=9.0e-01
```

Configurations tried for B (fillers K, CU limits, ed25519 verifications per filler, pause before the pair):

```
K   pairCU  fillerCU  ed25519  leadms same-slot higher-fee-first first-sent-first
0   200000  -         -        0      30/30     13/30            25/30
1   2000    1400000   50       1      30/30     13/30            28/30
2   2000    1400000   50       1      30/30     15/30            29/30
4   2000    1400000   0        1      30/30     10/30            26/30
4   2000    1400000   25       1      30/30     29/30            13/30
4   2000    1400000   50       0      30/30     30/30            12/30
4   2000    1400000   50       1      30/30     30/30            12/30
4   200000  1400000   50       1      30/30     30/30            15/30
4   2000    1400000   50       3      30/30     27/30            21/30
8   200000  200000    0        0      30/30     20/30            22/30
8   2000    1400000   50       2      30/30     29/30            22/30
32  2000    2000      0        0      30/30     17/30            23/30
```

Reading:

- A recovers arrival order (60/60); fee has no effect (p=0.37).
- B recovers priority order (57/60); send order has no effect (p=0.52). The three misses are unexplained.
- C does not flag the placebo (p=0.90).
- A bare pair gives arrival order; cheap or few fillers give no reliable priority order. It appeared only with 4 or 8 fillers that are both expensive (1.4M CU limit) and slow (25 or 50 ed25519 verifications). Our reading of the Agave source is that the scheduler then cannot schedule W-conflicting transactions for a few milliseconds, so both pair transactions wait in its queue. Not confirmed by instrumentation.

## What calibration does not show

- One local node and leader, loopback only: no network path, no leader rotation, no stake-weighted QUIC treatment (unstaked client), no other traffic.
- Only Agave 4.3.2 with its default greedy scheduler. Other clients may order differently.
- No external builders (Jito, BAM, Harmonic).
- B needed engineered filler traffic. It shows the analysis can see a priority effect when one exists, not that mainnet leaders produce one.
- Live probes go through provider RPC, not directly to a TPU; how arrival and priority separate there is untested.
- One placebo of 60 pairs is not a false-positive rate; `tests/test_stats.py` simulates that.
