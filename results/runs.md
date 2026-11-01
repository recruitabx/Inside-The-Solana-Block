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
| 20261031T135019Z-live-c4a21b | main | live | 2026-10-31T13:50:20Z | 2026-10-31T14:08:20Z | 7d5c443f04... | 122 | 244 | 159 | 65.2% | 24 | 1202085 | 4xpoeA2TVjew... | yes |  |
| 20261031T143056Z-live-b3e100 | main | live | 2026-10-31T14:30:57Z | 2026-10-31T14:48:51Z | 990be6c5be... | 129 | 258 | 170 | 65.9% | 29 | 1306587 | 3TVnw8d1PYsg... | yes |  |
| 20261031T151240Z-live-4fff40 | main | live | 2026-10-31T15:12:40Z | 2026-10-31T15:30:24Z | f341014ef5... | 106 | 212 | 144 | 67.9% | 25 | 1105074 | 4tA81kCQaUSu... | yes |  |
| 20261031T153848Z-live-2d70c6 | main | live | 2026-10-31T15:38:49Z | 2026-10-31T15:56:49Z | f509d26e65... | 136 | 272 | 184 | 67.7% | 41 | 1415094 | 42HT7v5mUpi5... | yes |  |
| 20261031T160518Z-live-a5ef1a | main | live | 2026-10-31T16:05:19Z | 2026-10-31T16:23:06Z | b7e607dfce... | 109 | 218 | 175 | 80.3% | 50 | 1326093 | 45QZFzGBEf6G... | yes |  |
| 20261031T163130Z-live-4d211e | main | live | 2026-10-31T16:31:31Z | 2026-10-31T16:49:26Z | fbcb4e2358... | 104 | 208 | 144 | 69.2% | 24 | 1116072 | 63yraMSsLetp... | yes |  |
| 20261031T165749Z-live-466b92 | main | live | 2026-10-31T16:57:50Z | 2026-10-31T17:15:34Z | 08269c8381... | 74 | 148 | 115 | 77.7% | 18 | 872061 | 4JAGwzGVK8sy... | yes |  |
| 20261031T172415Z-live-dbd7db | main | live | 2026-10-31T17:24:16Z | 2026-10-31T17:42:11Z | aeefb0d6fd... | 79 | 158 | 93 | 58.9% | 10 | 718047 | 4LrvrryeuPq4... | yes |  |
| 20261031T175034Z-live-ea2eeb | main | live | 2026-10-31T17:50:35Z | 2026-10-31T18:08:37Z | 6f561c6c8b... | 92 | 184 | 125 | 67.9% | 16 | 971562 | 21pr6NBcdrtK... | yes |  |
| 20261031T181700Z-live-75730f | main | live | 2026-10-31T18:17:01Z | 2026-10-31T18:34:43Z | 9b0ccd485f... | 71 | 142 | 87 | 61.3% | 15 | 660546 | FA2m9AYf6ZUk... | yes |  |
| 20261031T184307Z-live-8c3f95 | main | live | 2026-10-31T18:43:08Z | 2026-10-31T19:01:00Z | 3491bb83e0... | 47 | 94 | 54 | 57.5% | 12 | 407529 | 4wSLYvBtmzVD... | yes |  |
| 20261031T190923Z-live-5626ab | main | live | 2026-10-31T19:09:24Z | 2026-10-31T19:27:04Z | 611f26400f... | 51 | 102 | 63 | 61.8% | 5 | 480033 | 2EviNfd2p4HL... | yes |  |
| 20261031T193527Z-live-37d80d | main | live | 2026-10-31T19:35:28Z | 2026-10-31T19:53:24Z | 976733a4e7... | 43 | 86 | 63 | 73.3% | 8 | 480033 | 5zzCDHZQFgLP... | yes |  |
| 20261031T200225Z-live-740532 | main | live | 2026-10-31T20:02:26Z | 2026-10-31T20:20:28Z | 8c391f7263... | 118 | 236 | 184 | 78.0% | 38 | 1415094 | NiNiWRBmvTd6... | yes |  |
| 20261031T202851Z-live-88df58 | main | live | 2026-10-31T20:28:52Z | 2026-10-31T20:46:48Z | 11cdef1809... | 99 | 198 | 143 | 72.2% | 34 | 1083576 | 4Dxw2HKT9YSW... | yes |  |
| 20261031T205511Z-live-022c4c | main | live | 2026-10-31T20:55:12Z | 2026-10-31T21:13:04Z | df41c36ec8... | 106 | 212 | 163 | 76.9% | 40 | 1266081 | 4dgd8JyHJgW1... | yes |  |
| 20261031T212127Z-live-51d947 | main | live | 2026-10-31T21:21:28Z | 2026-10-31T21:39:12Z | b0d55ecf82... | 114 | 228 | 181 | 79.4% | 52 | 1356099 | CvhehWTnG4TC... | yes |  |
| 20261031T214735Z-live-0fdc2c | main | live | 2026-10-31T21:47:36Z | 2026-10-31T22:05:33Z | a7b9d70749... | 114 | 228 | 181 | 79.4% | 42 | 1356099 | 2rUT44kt1G2E... | yes |  |
| 20261031T221356Z-live-70dfcc | main | live | 2026-10-31T22:13:57Z | 2026-10-31T22:31:58Z | 6699010a1a... | 115 | 230 | 164 | 71.3% | 36 | 1221591 | 4AVitg6qvtiN... | yes |  |
| **TOTAL main** | main |  | 2026-10-31T08:38:02Z | 2026-10-31T22:31:58Z |  | **2649** | **5298** | **3603** | **68.0%** | **706** | **27416394** |  | yes | 30 runs |
| **TOTAL all** |  |  | 2026-10-30T17:10:30Z | 2026-10-31T22:31:58Z |  | **2796** | **5592** | **3823** | **68.4%** | **750** | **29127003** |  | yes | 35 runs |

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
| 20261031T135019Z-live-c4a21b | `4xpoeA2TVjewZ6qF9YK1x5kWWLBUYc9gYiAknFGUV2j196oGB7xGwmAQDqhCgyp1fnnWs4CdVo3YDyL2FPPSAbgv` | 7170 |
| 20261031T143056Z-live-b3e100 | `3TVnw8d1PYsgRcN4TBh11HamUMRwZo7hhV9nHKWpgu9rSKEfAEpLMRixD3cgZXNCo2SioAUCRQWEJ9HKpUd6yxR5` | 7170 |
| 20261031T151240Z-live-4fff40 | `4tA81kCQaUSuS98NexQbg8aP4Rc4He4Tn9TNA4GtJp8ZHtJmLbX4tEvyTPstBfX4Hs9h2Ae19bwuiAhviadBzbij` | 7170 |
| 20261031T153848Z-live-2d70c6 | `42HT7v5mUpi5njECyVyJLDZ9S4gxGfvTdSQ3CP8zoSpRp7V53cKEmx3EC72cw2Ppx4hLEbMJEtKycrvdkbEwWX8n` | 7170 |
| 20261031T160518Z-live-a5ef1a | `45QZFzGBEf6GPGLfYn7fndRRQ9bkfsN61BargNUERBhdmcnB7kJ298WYtzji9454Jx1MdtnPaeZWUcpRwX2SXShP` | 7170 |
| 20261031T163130Z-live-4d211e | `63yraMSsLetp8GQvBikzrfEm9nNjYDdnpHSJvDhKsnkkfYDZoLqs2FdpDJP5F7JjXNhzygp9rTYXY1MxomoRNNM4` | 7170 |
| 20261031T165749Z-live-466b92 | `4JAGwzGVK8syQS7RDWJ48eibJKZ5snECHWriNnJcco7ZpGJ8voPjJoxLmrMSwRjiqVjYzbwrxYWbw9Ff3Nt1uz4Q` | 7170 |
| 20261031T172415Z-live-dbd7db | `4LrvrryeuPq4J6ZEaXaPfuQ4Mu9vBQLxJNbjz2TyS1HhYHPJg12MUddQnVaWgtAMcheGmC77MQFF5X2oMXwNL2s3` | 7170 |
| 20261031T175034Z-live-ea2eeb | `21pr6NBcdrtKyurrUYXGaS8ASQK1BSPqQADkrJXm26MVfhR8agRmcZPRXp3bqHvuFKVLtgQDGnab8dYcqEraqgzx` | 7170 |
| 20261031T181700Z-live-75730f | `FA2m9AYf6ZUkxeRvMxSTKkGsskB8xLg7NUurRNkcirxMBo8pSYvG7ABarPfMndotQtypWU8PSh8ZhJWwRG3f8tF` | 7170 |
| 20261031T184307Z-live-8c3f95 | `4wSLYvBtmzVDtuDtZwdHDn5cUL3hrUdCsZfPS8cvM8yqa5cPKgvc5SfoEXJXmMJBjZJcm9YKqqCMo9h4FQoYf8S2` | 7170 |
| 20261031T190923Z-live-5626ab | `2EviNfd2p4HLxjwYJxmAK8Kec46QxZWmpptPbP7WkBh5eEEiC3hVTwccAT7PW4t9rc3G9K1yaayU2VfwFFyaLNMC` | 7170 |
| 20261031T193527Z-live-37d80d | `5zzCDHZQFgLPMuMaDGXgWWzNR8aufJfJLBMHMA1WN6yaB3zbHgt4Y7GTgviXZ3YtqYdFwxT8j7Ro2iMdWYGrQrkS` | 7170 |
| 20261031T200225Z-live-740532 | `NiNiWRBmvTd6caG2MnegwBVFLLEUzQm99cLubTBYKmSFScrxa2WWuUcaJLwMgSutcYx9zpu7bMvt1kLFTSwbGAB` | 7170 |
| 20261031T202851Z-live-88df58 | `4Dxw2HKT9YSWbgkRSpaFTE7zMrcJtVGUPqG2raSFTeTwWwZb3RGaHw6ZzEfH5aMb6SbtgbLxQSwWRfmX8pJSKhvZ` | 7170 |
| 20261031T205511Z-live-022c4c | `4dgd8JyHJgW1fxa3ajC2iFgSKTh8d4d4Fa5nErhppiXjGfnv5L6MftM25pVEGKUAuGG2cFYLUpr3KhXH2TLu1NgV` | 7170 |
| 20261031T212127Z-live-51d947 | `CvhehWTnG4TCcFBDmghUCUaAxjLY8nBq9NVTyNMcB4o2izaizpaERHb2tV6zZAMfGxn6uhrinYnx9zDLvBqczCH` | 7170 |
| 20261031T214735Z-live-0fdc2c | `2rUT44kt1G2EgbS3TiAGZEKeRgz3sHgYW1j6Ny44Ra347QiSRvJuhnQqkqo7aM81tZ3t8cMz3kU3Niqg981ZUMrc` | 7170 |
| 20261031T221356Z-live-70dfcc | `4AVitg6qvtiNxHr62UTsjWw8LrB81EW4gKMVUsayVdFyErX6SGcbBgQCUQEkRZFBrF9nJuEWrZoMLC71g6RfQLCh` | 7170 |

## Main phase by role

| role | probes | usable | quota (data/plan.json) |
|---|---|---|---|
| HarmonicAgave-1 | 550 | 95 | 900 |
| AgaveBam-1 | 506 | 246 | 900 |
| JitoLabs-1 | 471 | 157 | 900 |
| HarmonicFiredancer-1 | 333 | 31 | 333 |
| Firedancer-1 | 333 | 21 | 333 |
| FireBAM-1 | 227 | 104 | 333 |
| Rakurai-1 | 124 | 28 | 330 |
| Agave-1 | 105 | 24 | 330 |
| **total** | **2649** | **706** | **4359** |
