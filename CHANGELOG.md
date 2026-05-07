# Changelog

## 0.1 — v01 release

Initial public release of the STAMM Python SDK.

- High-level `StammClient` for swap, mint, burn, seed.
- Low-level `TransactionBuilder` for callers that need direct group control.
- `PoolReader` and `RegistryReader` for on-chain state queries.
- Offline quote calculations: `get_swap_quote`, `get_mint_quote`, `get_burn_quote`.
- Smart-routed swaps with per-tier minimum-input filtering.
- Auto opt-in to LP tokens during `mint` and `seed_and_mint`.
- `StammClient.from_mnemonic(...)` convenience constructor.
- Configurable `wait_rounds` per call.
- Optional indexer client for fast pool-id enumeration via `list_pool_ids()`.
- Typed throughout, ships `py.typed`.
