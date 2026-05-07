"""Remove liquidity using the high-level client."""

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

pool_id = 3542125902  # USDC/HOG pool

# Proportional burn (get both assets back)
# result = stamm.burn(
#     pool_id=pool_id,
#     lp_amount=500_000,
#     tier=2,
#     slippage_pct=1.0,
# )

# Single-sided burn (get only USDC back)
# USDC = 31566704
# result = stamm.burn(
#     pool_id=pool_id,
#     lp_amount=500_000,
#     tier=2,
#     slippage_pct=1.0,
#     single_sided=USDC,
# )
