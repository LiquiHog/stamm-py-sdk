"""Swap tokens using the high-level client."""

import os

from algosdk.v2client import algod
from stamm import StammClient

# NEVER paste your mnemonic into source. Export it in your shell:
#   export ALGORAND_MNEMONIC="word1 word2 ... word25"
# Optionally override the node:
#   export ALGORAND_NODE_URL="https://your-node.example"
NODE_URL = os.environ.get("ALGORAND_NODE_URL", "https://mainnet-api.4160.nodely.dev")
NODE_TOKEN = os.environ.get("ALGORAND_NODE_TOKEN", "")
algod_client = algod.AlgodClient(NODE_TOKEN, NODE_URL)

stamm = StammClient.from_mnemonic(algod_client, os.environ["ALGORAND_MNEMONIC"])

USDC = 31566704
HOG = 3178895177

# Get a quote first (no transaction submitted)
quote = stamm.get_swap_quote(USDC, HOG, amount=1_000_000)  # 1 USDC
print(f"Swap 1 USDC -> {quote.expected_out:,} micro-HOG")
print(f"Price impact: {quote.price_impact_pct:.2f}%")
print(f"Effective price: {quote.effective_price:.6f}")
print(f"Tiers used: {quote.tiers_used}")

# Execute the swap (auto-routed, 0.5% slippage)
# result = stamm.swap(USDC, HOG, amount=1_000_000, slippage_pct=0.5)
# print(f"Confirmed in round {result['confirmed-round']}")
