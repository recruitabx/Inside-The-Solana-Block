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
| 20261031T084501Z-live-0dbdde | main | live | 2026-10-31T08:45:02Z | 2026-10-31T09:01:42Z | d088e2fbb4... | 48 | 96 | 51 | 53.1% | 10 | 381528 | 3Xxkc1Yg9yhP... | yes |  |
| 20261031T091005Z-live-1545ab | main | live | 2026-10-31T09:10:06Z | 2026-10-31T09:27:54Z | cfa4363eb6... | 55 | 110 | 65 | 59.1% | 17 | 501033 | 46P39FrB8Peb... | yes |  |
| 20261031T093617Z-live-bf5cc3 | main | live | 2026-10-31T09:36:18Z | 2026-10-31T09:53:31Z | 2068b11508... | 62 | 124 | 68 | 54.8% | 9 | 505038 | 4pd4hgdpBU3R... | yes |  |
| 20261031T100908Z-live-ad1524 | main | live | 2026-10-31T10:09:08Z | 2026-10-31T10:27:08Z | dae309c042... | 54 | 108 | 59 | 54.6% | 11 | 443532 | 3VJhHMSX1U62... | yes |  |
| 20261031T103531Z-live-471f48 | main | live | 2026-10-31T10:35:32Z |  | d693d6f298... | 13 | 26 | 12 | 46.2% | 1 | 98505 | 4xGsQp5bgfkk... | yes | no run_end record (running, or killed) |
| 20261031T105723Z-live-f4f397 | main | live | 2026-10-31T10:57:24Z | 2026-10-31T11:15:25Z | 43bd9f81ee... | 119 | 238 | 163 | 68.5% | 34 | 1244085 | 3s5ck4V7iGZT... | yes |  |
| 20261031T112348Z-live-83757f | main | live | 2026-10-31T11:23:49Z | 2026-10-31T11:41:49Z | e9a5462f7f... | 122 | 244 | 161 | 66.0% | 37 | 1206588 | 42cJE5LqzzG7... | yes |  |
| 20261031T115014Z-live-90d8c9 | main | live | 2026-10-31T11:50:14Z | 2026-10-31T12:07:57Z | 5a64255890... | 121 | 242 | 143 | 59.1% | 21 | 1072578 | 4eDQpscyqJTo... | yes |  |
| 20261031T123058Z-live-42b33d | main | live | 2026-10-31T12:30:59Z | 2026-10-31T12:48:59Z | 3deb250b2f... | 113 | 226 | 147 | 65.0% | 27 | 1125576 | 64CD12YdE8vD... | yes |  |
| 20261031T131705Z-live-6da283 | main | live | 2026-10-31T13:17:06Z | 2026-10-31T13:34:52Z | 5dec5f3365... | 113 | 226 | 142 | 62.8% | 20 | 1078575 | 4NyadG99MDSw... | yes |  |
| 20261031T135019Z-live-c4a21b | main | live | 2026-10-31T13:50:20Z |  | 7d5c443f04... | 78 | 156 | 0 | 0.0% | 0 | 0 | 4xpoeA2TVjew... | no | no run_end record (running, or killed) |
| **TOTAL main** | main |  | 2026-10-31T08:38:02Z | 2026-10-31T13:34:52Z |  | **898** | **1796** | **1011** | **56.3%** | **187** | **7657038** |  | partial | 12 runs |
| **TOTAL all** |  |  | 2026-10-30T17:10:30Z | 2026-10-31T13:34:52Z |  | **1045** | **2090** | **1231** | **58.9%** | **231** | **9367647** |  | partial | 17 runs |

## Run anchors (memo transaction of each run)

| run | anchor signature | anchor fee (lamports) |
|---|---|---|
| 20261030T171028Z-live-pilot-a2bbd7 | `3M7YjTPU6SgsN3VFVRdxxdUoS1D4WP66Tq9ndeFR41v8bwvJRuSwN2QGzQKYZfrtzD8jZgdFWkUZYdX1tFQmBsQR` | 7290 |
| 20261030T173035Z-live-pilot-7740ed | `zoeqKAiHBZwpotVYg2v9QM32U8ANcvZyB54Mjw285WYDuEWG4MEpMZnK7jgSG5RtKx2JGcTWW2rrQCxsSFt5B91` | 7290 |
| 20261030T173455Z-live-repilot-dd99a1 | `2JBALi5WETujEJyy63GMSreQ4YgCDiTcGfZwWujoDKqeM1ko3hjm7iJ94Z6c1CwpBxAzLDeUmp8hX9EkSSAsuL8i` | 7330 |
| 20261030T175239Z-live-repilot-b25293 | `4C9xocQVX5pqpspPtCPEdmCpjZ83EymmSAk9gNUux84XuzZgKHUuUdCybS3yizhgKHpAhyciF2jebEGGiSxoxRh5` | 7330 |
| 20261030T181612Z-live-repilot-63306b | `YvTvfJiZLnM66MVTKZKwHSkNVr5AREa6sLkemqKyJ2oKRi6eCJrsfe4Kh8B4CoJxFNdKWGe1Bxr2b4FUmQibJgB` | 7330 |
| 20261031T084501Z-live-0dbdde | `3Xxkc1Yg9yhPidCw4ekob3aD7arn1SKxnmNQ9sj34RXUJb7vP9swq67LLGRYaBBnKLgC4sWt3QFBqEicjfva6bDK` | 7170 |
| 20261031T091005Z-live-1545ab | `46P39FrB8PebGeLiMHKmYdhT24s4Nve95UVSoLGNFfMjRvduuVCc7bVywkkdHhqTxmcEWkxGicvtxzryEuEXWwBh` | 7170 |
| 20261031T093617Z-live-bf5cc3 | `4pd4hgdpBU3RDziXkmsUaYZYkAUrva8x5oaUoDPSwnfPfGRR3RR6Wtxnq157zRo9zEgRqtroRsKQp6v6W5qa1XZ6` | 7170 |
| 20261031T100908Z-live-ad1524 | `3VJhHMSX1U62ok86ExeJZ8jR8BdSBdESnzCtuCaWJbfHeYR4LdiSuwDxivDzRmny2nJUPQXkLSNH1cuRhqUrfUdv` | 7170 |
| 20261031T103531Z-live-471f48 | `4xGsQp5bgfkk8DDMwQs4qQg3Zvsi8x5j8E2vSLy7nq6161DpA7R1DkHEmumVFHszL5FdHpQ9ojzABehSsFCNrmBz` | 7170 |
| 20261031T105723Z-live-f4f397 | `3s5ck4V7iGZTpXJ6p7oFEC6Sk2y5NRsYQUNVbUSYgotwfzEw9Z9CeDaPr13Bdb4BbnpFmnz74X4Xs25e9bKU8SNs` | 7170 |
| 20261031T112348Z-live-83757f | `42cJE5LqzzG7bz9WPqQxjXdac66U6qfLdtHiYyBJo337W7enmUeewqtEH9UwVqiAtnPcK1f9d2n9QRTMQXEjPDPe` | 7170 |
| 20261031T115014Z-live-90d8c9 | `4eDQpscyqJToD78PgAFKiq7JD53hRPsiZrcfCPKTtj9nsQtoPxXDwYkuU7uuvVdRJozAYk9Fb7iXwZZ95ohdYe6Q` | 7170 |
| 20261031T123058Z-live-42b33d | `64CD12YdE8vD8dYpxidkM8r48dDyGyuWKHfNjFVPWm9n9cADQATBbG9emKPNygQ2Myy3R22yRrWcHHFJGQSrs7oA` | 7170 |
| 20261031T131705Z-live-6da283 | `4NyadG99MDSwrZWoDgQ7tb57jhYDomoqvXbd9pewuUqS9CqJX9bW9UVyrhBe8amXo4UWwkAnYdQZoVpSa7fiGz6y` | 7170 |
| 20261031T135019Z-live-c4a21b | `4xpoeA2TVjewZ6qF9YK1x5kWWLBUYc9gYiAknFGUV2j196oGB7xGwmAQDqhCgyp1fnnWs4CdVo3YDyL2FPPSAbgv` |  |

## Main phase by role

| role | probes | usable | quota (data/plan.json) |
|---|---|---|---|
| HarmonicAgave-1 | 226 | 33 | 333 |
| AgaveBam-1 | 203 | 76 | 333 |
| JitoLabs-1 | 148 | 42 | 333 |
| HarmonicFiredancer-1 | 124 | 8 | 333 |
| Firedancer-1 | 101 | 3 | 333 |
| FireBAM-1 | 45 | 16 | 333 |
| Rakurai-1 | 31 | 7 | 330 |
| Agave-1 | 20 | 2 | 330 |
| **total** | **898** | **187** | **2658** |
