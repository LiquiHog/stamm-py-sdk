"""Read pool state and display tier info."""

import os

from algosdk.v2client import algod
from stamm import PoolReader, RegistryReader

# Optionally override the node:
#   export ALGORAND_NODE_URL="https://your-node.example"
NODE_URL = os.environ.get("ALGORAND_NODE_URL", "https://mainnet-api.4160.nodely.dev")
NODE_TOKEN = os.environ.get("ALGORAND_NODE_TOKEN", "")
client = algod.AlgodClient(NODE_TOKEN, NODE_URL)
reader = PoolReader(client)
registry = RegistryReader(client)

# Look up USDC/HOG pool (order doesn't matter)
USDC = 31566704
HOG = 3178895177

pool_id = registry.get_pool(USDC, HOG)
if pool_id is None:
    print("Pool not found")
    exit()

pool = reader.get_state(pool_id)
print(f"Pool {pool.app_id} ({pool.address[:16]}...)")
print(f"Asset A: {pool.asset_a}, Asset B: {pool.asset_b}")
print(f"Aggregates: A={pool.aggregate_a:,} B={pool.aggregate_b:,}")
print(f"Treasury: A={pool.treasury_a:,} B={pool.treasury_b:,}")
print()

for tier in pool.tiers:
    status = "ACTIVE" if tier.active else "inactive"
    print(f"Tier {tier.char} ({tier.fee_ppm} ppm): "
          f"A={tier.reserve_a:,} B={tier.reserve_b:,} "
          f"LP={tier.total_lp:,} [{status}]")
