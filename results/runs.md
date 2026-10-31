# Runs (operational summary)

Counts and fees only: no ordering outcome is read or shown here. Written by `itb runs` from `data/raw/*.sent.jsonl`, `data/raw/*.landed.jsonl` and `data/ledger/spend.jsonl`.

- probes, tx sent: live probes with a send result and their transactions; tx landed: transactions with a landing record; landing = tx landed / tx sent (a lower bound while `collected` is not `yes`).
- usable: both transactions in ONE block produced by the targeted leader, in a slot of the targeted window (all arms; the analysis applies its further conditions per arm and per claim).
- fees settled: lamports settled in the ledger for the run's probe transactions (matched by signature); the anchor transaction is not included.

## Runs

| run | phase | mode | start (UTC) | end (UTC) | git | probes | tx sent | tx landed | landing | usable | fees settled (lamports) | anchor | collected | note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 20261030T171028Z-live-pilot-a2bbd7 | pilot | live | 2026-10-30T17:10:30Z | 2026-10-30T17:28:16Z | 6a1dc10c42... | 53 | 106 | 77 | 72.6% | 17 | 599538 | 3M7YjTPU6Sgs... | yes |  |
| 20261030T173035Z-live-pilot-7740ed | pilot | live | 2026-10-30T17:30:36Z | 2026-10-30T17:31:38Z | c080823593... | 5 | 10 | 5 | 50.0% | 0 | 36003 | zoeqKAiHBZwp... | yes | ended with KeyboardInterrupt |
| **TOTAL pilot** | pilot |  | 2026-10-30T17:10:30Z | 2026-10-30T17:31:38Z |  | **58** | **116** | **82** | **70.7%** | **17** | **635541** |  | yes | 2 runs |
| 20261030T173455Z-live-repilot-dd99a1 | repilot | live | 2026-10-30T17:34:56Z | 2026-10-30T17:48:43Z | 8449672497... | 43 | 86 | 65 | 75.6% | 12 | 512031 | 2JBALi5WETuj... | yes |  |
| 20261030T175239Z-live-repilot-b25293 | repilot | live | 2026-10-30T17:52:40Z | 2026-10-30T18:10:06Z | 9f256c2f01... | 46 | 92 | 73 | 79.3% | 15 | 563037 | 4C9xocQVX5pq... | yes |  |
| 20261030T181612Z-live-repilot-63306b | repilot | live | 2026-10-30T18:16:13Z | 2026-10-30T18:16:25Z | 9c3cc4c61b... | 0 | 0 | 0 |  | 0 | 0 | YvTvfJiZLnM6... | n/a | ended with KeyboardInterrupt |
| **TOTAL repilot** | repilot |  | 2026-10-30T17:34:56Z | 2026-10-30T18:16:25Z |  | **89** | **178** | **138** | **77.5%** | **27** | **1075068** |  | yes | 3 runs |
| 20261031T083802Z-live-2661db | main | unknown | 2026-10-31T08:38:02Z |  |  | 0 | 0 | 0 |  | 0 | 0 |  | n/a | no run_start record (empty or still starting) |
| 20261031T084501Z-live-0dbdde | main | live | 2026-10-31T08:45:02Z |  | d088e2fbb4... | 8 | 16 | 0 | 0.0% | 0 | 0 | 3Xxkc1Yg9yhP... | no | no run_end record (running, or killed) |
| **TOTAL main** | main |  | 2026-10-31T08:38:02Z |  |  | **8** | **16** | **0** | **0.0%** | **0** | **0** |  | no | 2 runs |
| **TOTAL all** |  |  | 2026-10-30T17:10:30Z | 2026-10-30T18:16:25Z |  | **155** | **310** | **220** | **71.0%** | **44** | **1710609** |  | partial | 7 runs |

## Run anchors (memo transaction of each run)

| run | anchor signature | anchor fee (lamports) |
|---|---|---|
| 20261030T171028Z-live-pilot-a2bbd7 | `3M7YjTPU6SgsN3VFVRdxxdUoS1D4WP66Tq9ndeFR41v8bwvJRuSwN2QGzQKYZfrtzD8jZgdFWkUZYdX1tFQmBsQR` | 7290 |
| 20261030T173035Z-live-pilot-7740ed | `zoeqKAiHBZwpotVYg2v9QM32U8ANcvZyB54Mjw285WYDuEWG4MEpMZnK7jgSG5RtKx2JGcTWW2rrQCxsSFt5B91` | 7290 |
| 20261030T173455Z-live-repilot-dd99a1 | `2JBALi5WETujEJyy63GMSreQ4YgCDiTcGfZwWujoDKqeM1ko3hjm7iJ94Z6c1CwpBxAzLDeUmp8hX9EkSSAsuL8i` | 7330 |
| 20261030T175239Z-live-repilot-b25293 | `4C9xocQVX5pqpspPtCPEdmCpjZ83EymmSAk9gNUux84XuzZgKHUuUdCybS3yizhgKHpAhyciF2jebEGGiSxoxRh5` | 7330 |
| 20261030T181612Z-live-repilot-63306b | `YvTvfJiZLnM66MVTKZKwHSkNVr5AREa6sLkemqKyJ2oKRi6eCJrsfe4Kh8B4CoJxFNdKWGe1Bxr2b4FUmQibJgB` | 7330 |
| 20261031T084501Z-live-0dbdde | `3Xxkc1Yg9yhPidCw4ekob3aD7arn1SKxnmNQ9sj34RXUJb7vP9swq67LLGRYaBBnKLgC4sWt3QFBqEicjfva6bDK` |  |

## Main phase by role

| role | probes | usable | quota (data/plan.json) |
|---|---|---|---|
| HarmonicAgave-1 | 1 | 0 | 333 |
| AgaveBam-1 | 0 | 0 | 333 |
| JitoLabs-1 | 2 | 0 | 333 |
| HarmonicFiredancer-1 | 0 | 0 | 333 |
| Firedancer-1 | 3 | 0 | 333 |
| FireBAM-1 | 0 | 0 | 333 |
| Rakurai-1 | 2 | 0 | 330 |
| Agave-1 | 0 | 0 | 330 |
| **total** | **8** | **0** | **2658** |
