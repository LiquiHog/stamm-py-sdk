# STAMM Python SDK (v01)

Python SDK for interacting with STAMM multi-tier AMM pools on Algorand.

This is the **v01** release line.

## Install

```bash
pip install stamm-py-sdk
```

Requires Python 3.10+ and `py-algorand-sdk>=2.0`.

## Quickstart

```python
import os
from algosdk.v2client import algod
from stamm import StammClient

# Configure via environment variables:
#   ALGORAND_MNEMONIC    25-word mnemonic for the signing account
#   ALGORAND_NODE_URL    optional, defaults to a public mainnet endpoint
#   ALGORAND_NODE_TOKEN  optional API token for your node

node_url = os.environ.get("ALGORAND_NODE_URL", "https://mainnet-api.4160.nodely.dev")
node_token = os.environ.get("ALGORAND_NODE_TOKEN", "")
algod_client = algod.AlgodClient(node_token, node_url)

stamm = StammClient.from_mnemonic(algod_client, os.environ["ALGORAND_MNEMONIC"])

USDC = 31566704
HOG = 3178895177

# Quote without submitting
quote = stamm.get_swap_quote(USDC, HOG, amount=1_000_000)
print(f"1 USDC -> {quote.expected_out:,} micro-HOG ({quote.price_impact_pct:.2f}% impact)")

# Execute (auto-routed across the best-scoring tiers, 0.5% slippage)
result = stamm.swap(USDC, HOG, amount=1_000_000, slippage_pct=0.5)
print(f"Confirmed in round {result['confirmed-round']}")
```

## Custom signing (hardware wallets, multisig, etc.)

`from_mnemonic` is just a convenience wrapper. For any other signing setup,
use the regular constructor and pass your own signer callable:

```python
def signer(txns):
    # Receives transactions with the group ID already assigned.
    # Return a list of SignedTransaction in the same order.
    return [my_hardware_wallet.sign(t) for t in txns]

stamm = StammClient(algod_client, sender_address, signer)
```

## What you can do

| Method | Purpose |
|---|---|
| `swap(asset_in, asset_out, amount, slippage_pct=0.5, tier=None)` | Smart-routed swap by default; specify `tier` to swap on a single tier. |
| `swap_limit(asset_in, asset_out, amount, tier, limit_price, ...)` | Single-tier swap with a maximum execution price. |
| `swap_routed(asset_in, asset_out, amount, tiers, amounts, ...)` | Caller-defined per-tier routing. |
| `mint(pool_id, amount_a, amount_b, tier, ...)` | Add liquidity to a tier. Auto-opts into the LP token if needed. |
| `burn(pool_id, lp_amount, tier, single_sided=None, ...)` | Withdraw liquidity (proportional or single-sided). |
| `seed_tier(pool_id, tier)` | Seed a previously unseeded non-default tier. |
| `seed_and_mint(pool_id, deposit_a, deposit_b, tier)` | First liquidity provision on a brand-new pool. |
| `get_swap_quote / get_mint_quote / get_burn_quote` | Offline quotes — no transaction submitted. |
| `get_pool / get_pool_by_id / list_pools / list_pool_ids / get_lp_info / get_price` | Read-only state queries. |

All write methods accept a `wait_rounds: int = 4` kwarg if you want to override
the default confirmation timeout.

## Errors

The SDK raises typed exceptions you can catch programmatically:

- `PoolNotFoundError` — no pool exists for the asset pair.
- `TierInactiveError` — the requested tier is not active on this pool.
- `TierNotSeededError` — minting on a tier that hasn't received initial liquidity.
- `SwapBelowMinimumError(tier, minimum, amount)` — input below the per-tier minimum.
- `InsufficientLiquidityError` — quote produced zero output.
- `SlippageError` — slippage tolerance reduces `min_output` to zero.
- `DuplicateTierError` — `swap_routed` was given duplicate tier indices.
- `NotOptedInError` — sender is not opted into a required asset.

All inherit from `StammError`.

## Pool discovery

Two methods, two scales:

- **`list_pools()`** walks the registry's pair boxes and returns
  `[(asset_a, asset_b, pool_id), ...]`. One algod call to list box names plus
  one per pool to read each pool_id. Fine at current scale.

- **`list_pool_ids()`** returns just `[pool_id, ...]`. If you supply an
  indexer client at construction, it uses
  `indexer.search_applications(creator=factory_address)` — a single paginated
  query, no per-pool reads. Without an indexer it falls back to `list_pools()`,
  which is slower; pass an indexer when pool counts grow.

```python
from algosdk.v2client import algod, indexer

algod_client = algod.AlgodClient("", "https://mainnet-api.4160.nodely.dev")
indexer_client = indexer.IndexerClient("", "https://mainnet-idx.4160.nodely.dev")

stamm = StammClient.from_mnemonic(
    algod_client, os.environ["ALGORAND_MNEMONIC"],
    indexer_client=indexer_client,
)

ids = stamm.list_pool_ids()  # fast indexer path
```

For a single pair lookup use `get_pool(asset_a, asset_b)` — that reads exactly
one box and is the right call when you already know the pair.

## Pool sync detection

If a pool's tracked reserves drift from its actual on-chain balances (for
example, after a direct asset transfer to the pool address), the contract
runs an internal rescale on the next write call. That rescale costs extra
opcodes, and a swap that doesn't budget for them will fail.

`StammClient` handles this transparently: before each write, it compares the
pool's tracked reserves to its on-chain balances and provisions the additional
opup automatically. Once a write executes successfully, the sync resolves and
later calls revert to the standard budget.

If you're using `TransactionBuilder` directly, check it yourself:

```python
if pool_reader.needs_sync(pool_state):
    txns = builder.build_swap(..., extra_opup=2)
else:
    txns = builder.build_swap(...)
```

## Auto opt-in behavior

`mint()` and `seed_and_mint()` automatically opt the sender into the tier's
LP token if not already opted in. This is a separate transaction submitted
and confirmed before the main group. Hardware-wallet users will be prompted
to sign twice on the first mint per tier.

## Examples

See the [`examples/`](examples/) directory:

- `swap_example.py` — quote + smart-routed swap
- `mint_example.py` — add liquidity
- `burn_example.py` — proportional and single-sided withdrawal
- `read_pool.py` — inspect pool and tier state without signing

Each example reads `ALGORAND_MNEMONIC` and `ALGORAND_NODE_URL` from the
environment — never paste a mnemonic into source.

## License

The Python SDK in this repository is MIT-licensed — see [LICENSE](LICENSE).

The STAMM smart contracts and their source code are **not** covered by this
license. They are not distributed in this repository and remain under
separate terms.
