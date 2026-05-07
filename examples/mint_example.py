"""Add liquidity using the high-level client."""

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

# Look up the pool
pool = stamm.get_pool(USDC, HOG)
if pool is None:
    print("Pool not found")
    exit()

print(f"Pool {pool.app_id}")
print(f"Asset A: {pool.asset_a}, Asset B: {pool.asset_b}")

# Add liquidity to tier 2 (30 bps).
# The SDK auto-opts into the LP token on the first mint per tier
# (one extra signed transaction).
# result = stamm.mint(
#     pool_id=pool.app_id,
#     amount_a=1_000_000,   # 1 USDC
#     amount_b=2_000_000,   # 2 HOG
#     tier=2,
#     slippage_pct=1.0,
# )
# print(f"Minted LP, confirmed in round {result['confirmed-round']}")
