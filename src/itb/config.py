"""Constants that define the measurement regime. Changing them changes what the data means."""

# First block produced after the Alpenglow activation on mainnet.
# Evidence: the last block that still contains vote transactions is slot 459652999
# (blockTime 2026-10-21T13:54:00Z); slots 459653000..459653007 were skipped; slot
# 459653008 is the first block without vote transactions. See docs/ALPENGLOW_BOUNDARY.md.
MIN_SLOT = 459_653_008

LAMPORTS_PER_SOL = 1_000_000_000

# Hard ceiling of total fee spend for the whole experiment (0.05 SOL). The configurable cap
# (ITB_SPEND_CAP_LAMPORTS) can only be LOWER than this; anything higher is rejected.
HARD_SPEND_CEILING_LAMPORTS = 50_000_000

# Base fee per signature on mainnet (lamports).
BASE_FEE_PER_SIGNATURE = 5_000

# getBlock / getTransaction must accept the newest transaction format seen on mainnet.
MAX_SUPPORTED_TX_VERSION = 1

MEMO_PROGRAM_ID = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"
COMPUTE_BUDGET_PROGRAM_ID = "ComputeBudget111111111111111111111111111111"
VOTE_PROGRAM_ID = "Vote111111111111111111111111111111111111111"
