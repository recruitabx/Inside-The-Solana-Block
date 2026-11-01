# Alpenglow boundary (MIN_SLOT)

All measurements in this repository are taken after the Alpenglow activation on mainnet and
never mix data from before it. The code rejects any slot below `MIN_SLOT = 459653008`
(`src/itb/config.py`).

How the boundary was determined: after Alpenglow, consensus votes are no longer transactions
inside blocks. `scripts/alpenglow_boundary.py` binary-searches getBlock for the last block that
still contains Vote program transactions.

Output on 2026-10-30 against the public endpoint `https://api.mainnet-beta.solana.com`
(identical result was obtained earlier the same day through a second provider, Helius):

```
last block with vote transactions: slot 459652999 (649 vote tx, blockTime 2026-10-21T13:54:00+00:00)
slot 459653000: skipped
slot 459653001: skipped
slot 459653002: skipped
slot 459653003: skipped
slot 459653004: skipped
slot 459653005: skipped
slot 459653006: skipped
slot 459653007: skipped
first block after it: slot 459653008, vote tx = 0, blockTime 2026-10-21T13:54:03+00:00
```

Reproduce:

```bash
python scripts/alpenglow_boundary.py
```

Note: epoch 1064 starts at slot 459648000 (1064 x 432000), so the first 5008 slots of epoch 1064
are still pre-Alpenglow. The boundary is therefore defined by slot, not by epoch.
