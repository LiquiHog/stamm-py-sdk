"""STAMM SDK constants — app IDs, ABI selectors, tier config, fee schedule."""

REGISTRY_APP_ID = 3544666315
FACTORY_APP_ID = 3544766605
OPUP_APP_ID = 3544641019
BUDGET_APP_ID = 3544641082

NUM_TIERS = 6
TIER_P_INDEX = 5
TIER_CHARS = {0: "0", 1: "1", 2: "2", 3: "3", 4: "4", 5: "p"}

# Fee schedule: standard tiers in basis points, Tier P in parts per million
TIER_FEES_BPS = {0: 3, 1: 10, 2: 30, 3: 100, 4: 300}
TIER_P_FEE_PPM = 1_000_000

# Normalized fees in parts-per-million for all tiers
TIER_FEES_PPM = {0: 30, 1: 100, 2: 300, 3: 1000, 4: 3000, 5: 1}

# Fee split constants
TIER_RETAINED_PCT = 80
EFFECTIVE_FEE_DENOM = 20_000

# RT box
RT_ENTRY_SIZE = 16
RT_BOX_SIZE = 96

# Minimum swap input per tier (below this, total_fee rounds to 0 and swap returns 0)
# Formula: ceil(10_000 / fee_bps) for standard tiers
MIN_SWAP_INPUT = {0: 3_334, 1: 1_000, 2: 334, 3: 100, 4: 34, 5: 1_000_001}

# Opup calls needed per operation
OPUP_COUNTS = {
    "swap": 6,
    "swap_smart": 8,
    "swap_limit": 6,
    "swap_routed": 8,
    "mint": 6,
    "burn": 6,
    "seed_and_mint": 8,
    "seed_tier": 6,
}

# Budget app method selector
BUDGET_PROVIDE_SEL = bytes.fromhex("2cb9a9c1")

# ABI method selectors (from ARC56, SHA-512/256 of full signature)
SELECTORS = {
    "swap": bytes.fromhex("287d47b0"),
    "swap_limit": bytes.fromhex("4c6ea2d7"),
    "swap_smart": bytes.fromhex("92927b10"),
    "swap_routed": bytes.fromhex("90c59a40"),
    "mint": bytes.fromhex("b7f1975d"),
    "burn": bytes.fromhex("81bf0079"),
    "seed_tier": bytes.fromhex("1960e30c"),
    "seed_and_mint": bytes.fromhex("9e803cf7"),
    "get_pool": bytes.fromhex("426bd3bd"),
    "get_lp_info": bytes.fromhex("78baa39f"),
}
