"""High-level STAMM client — reads state, quotes, builds, signs, submits."""

from algosdk import account, mnemonic, transaction
from algosdk.v2client import algod, indexer

from stamm.constants import MIN_SWAP_INPUT
from stamm.pool import PoolReader
from stamm.registry import RegistryReader
from stamm.indexer import IndexerReader
from stamm.builders import TransactionBuilder
from stamm.math import quote_swap, quote_swap_smart, quote_mint, quote_burn, calculate_price
from stamm.types import PoolState, SwapQuote, MintQuote, BurnQuote, LpInfo
from stamm.errors import (
    PoolNotFoundError, TierInactiveError, TierNotSeededError,
    InsufficientLiquidityError, SlippageError, DuplicateTierError,
    SwapBelowMinimumError,
)

DEFAULT_WAIT_ROUNDS = 4


class StammClient:
    def __init__(
        self,
        algod_client: algod.AlgodClient,
        sender: str,
        signer,
        indexer_client: indexer.IndexerClient | None = None,
    ):
        """
        Args:
            algod_client: Algorand client
            sender: User's address
            signer: Callable that signs a transaction group.
                    Signature: signer(txn_group: list[Transaction]) -> list[SignedTransaction]
                    Receives transactions with group ID already assigned.
            indexer_client: Optional indexer client. Required for `list_pool_ids`;
                            other read methods work without it.
        """
        self.algod = algod_client
        self.sender = sender
        self.signer = signer
        self.pool_reader = PoolReader(algod_client)
        self.registry = RegistryReader(algod_client)
        self.indexer_reader = IndexerReader(indexer_client) if indexer_client else None
        self.builder = TransactionBuilder(algod_client)

    @classmethod
    def from_mnemonic(
        cls,
        algod_client: algod.AlgodClient,
        mnemonic_phrase: str,
        indexer_client: indexer.IndexerClient | None = None,
    ) -> "StammClient":
        """Convenience constructor: derive sender + signer from a 25-word mnemonic.

        For hardware wallets or custodial signing, use the regular constructor
        and supply your own signer callable.
        """
        sk = mnemonic.to_private_key(mnemonic_phrase)
        sender = account.address_from_private_key(sk)

        def signer(txns):
            return [t.sign(sk) for t in txns]

        return cls(algod_client, sender, signer, indexer_client=indexer_client)

    def _resolve_pool(self, asset_in: int, asset_out: int) -> tuple[PoolState, bool]:
        """Look up pool and determine swap direction.
        Returns (pool_state, is_a_to_b).
        """
        pool_id = self.registry.get_pool(asset_in, asset_out)
        if pool_id is None:
            raise PoolNotFoundError(f"No pool for {asset_in}/{asset_out}")
        pool = self.pool_reader.get_state(pool_id)
        is_a_to_b = asset_in == pool.asset_a or (asset_in == 0 and pool.asset_a == 0)
        return pool, is_a_to_b

    def _submit(self, txns: list, wait_rounds: int = DEFAULT_WAIT_ROUNDS) -> dict:
        """Sign and submit a transaction group."""
        signed = self.signer(txns)
        txid = self.algod.send_transactions(signed)
        return transaction.wait_for_confirmation(self.algod, txid, wait_rounds)

    def _sync_opup(self, pool_state: PoolState) -> int:
        """Return the extra opup count needed if the pool requires a sync."""
        return 2 if self.pool_reader.needs_sync(pool_state) else 0

    def _ensure_opted_in(self, asset_id: int, wait_rounds: int) -> None:
        """Send and confirm an opt-in transaction if the sender isn't opted in."""
        if asset_id <= 0 or self._is_opted_in(asset_id):
            return
        opt_txn = self.builder.build_opt_in(asset_id, self.sender)
        signed = self.signer([opt_txn])
        self.algod.send_transaction(signed[0])
        transaction.wait_for_confirmation(self.algod, signed[0].get_txid(), wait_rounds)

    def _is_opted_in(self, asset_id: int) -> bool:
        """Check if sender is opted into an asset."""
        acct = self.algod.account_info(self.sender)
        for a in acct.get("assets", []):
            if a["asset-id"] == asset_id:
                return True
        return False

    # ── Swap ─────────────────────────────────────────────

    def swap(
        self, asset_in: int, asset_out: int, amount: int,
        slippage_pct: float = 0.5, tier: int | None = None,
        wait_rounds: int = DEFAULT_WAIT_ROUNDS,
    ) -> dict:
        """Swap tokens. If tier is None, uses swap_smart (auto-routing)."""
        pool, is_a_to_b = self._resolve_pool(asset_in, asset_out)

        if tier is not None:
            ts = pool.tiers[tier]
            if not ts.active:
                raise TierInactiveError(f"Tier {tier} is not active")
            min_in = MIN_SWAP_INPUT.get(tier, 0)
            if amount < min_in:
                raise SwapBelowMinimumError(tier=tier, minimum=min_in, amount=amount)
            quote = quote_swap(pool, amount, is_a_to_b, tier)
        else:
            quote = quote_swap_smart(pool, amount, is_a_to_b)

        if quote.expected_out == 0:
            raise InsufficientLiquidityError("Zero output")

        min_output = int(quote.expected_out * (1 - slippage_pct / 100))
        if min_output <= 0:
            raise SlippageError(f"min_output is 0 at {slippage_pct}% slippage")

        extra_opup = self._sync_opup(pool)
        if tier is not None:
            txns = self.builder.build_swap(
                pool, asset_in, amount, tier, min_output, self.sender,
                extra_opup=extra_opup,
            )
        else:
            txns = self.builder.build_swap_smart(
                pool, asset_in, amount, min_output, self.sender,
                extra_opup=extra_opup,
            )

        return self._submit(txns, wait_rounds)

    def swap_limit(
        self, asset_in: int, asset_out: int, amount: int,
        tier: int, limit_price: float, slippage_pct: float = 0.5,
        wait_rounds: int = DEFAULT_WAIT_ROUNDS,
    ) -> dict:
        """Swap with price limit on a specific tier."""
        pool, is_a_to_b = self._resolve_pool(asset_in, asset_out)
        ts = pool.tiers[tier]
        if not ts.active:
            raise TierInactiveError(f"Tier {tier} is not active")

        min_in = MIN_SWAP_INPUT.get(tier, 0)
        if amount < min_in:
            raise SwapBelowMinimumError(tier=tier, minimum=min_in, amount=amount)

        quote = quote_swap(pool, amount, is_a_to_b, tier)
        if quote.expected_out == 0:
            raise InsufficientLiquidityError("Zero output")

        min_output = int(quote.expected_out * (1 - slippage_pct / 100))

        # limit_price = max price of input per output, encoded with 10^6 precision
        precision = 1_000_000
        limit_num = int(limit_price * precision)
        limit_den = precision

        txns = self.builder.build_swap_limit(
            pool, asset_in, amount, tier, min_output, limit_num, limit_den, self.sender,
            extra_opup=self._sync_opup(pool),
        )
        return self._submit(txns, wait_rounds)

    def swap_routed(
        self, asset_in: int, asset_out: int, amount: int,
        tiers: list, amounts: list,
        slippage_pct: float = 0.5,
        price_limit: float | None = None,
        wait_rounds: int = DEFAULT_WAIT_ROUNDS,
    ) -> dict:
        """Swap with explicit tier routing."""
        # Validate no duplicates
        if len(set(tiers)) != len(tiers):
            raise DuplicateTierError("Duplicate tiers in routing")

        # Validate each leg meets the per-tier minimum
        for t, a in zip(tiers, amounts):
            min_in = MIN_SWAP_INPUT.get(t, 0)
            if a < min_in:
                raise SwapBelowMinimumError(tier=t, minimum=min_in, amount=a)

        pool, is_a_to_b = self._resolve_pool(asset_in, asset_out)

        # Compute expected total output for slippage
        total_expected = 0
        for t, a in zip(tiers, amounts):
            q = quote_swap(pool, a, is_a_to_b, t)
            total_expected += q.expected_out

        if total_expected == 0:
            raise InsufficientLiquidityError("Zero output")

        min_output = int(total_expected * (1 - slippage_pct / 100))

        price_num, price_den = 0, 0
        if price_limit is not None:
            precision = 1_000_000
            price_num = int(price_limit * precision)
            price_den = precision

        txns = self.builder.build_swap_routed(
            pool, asset_in, amount, tiers, amounts,
            min_output, self.sender, price_num, price_den,
            extra_opup=self._sync_opup(pool),
        )
        return self._submit(txns, wait_rounds)

    def get_swap_quote(
        self, asset_in: int, asset_out: int, amount: int,
        tier: int | None = None,
    ) -> SwapQuote:
        """Get swap quote without submitting."""
        pool, is_a_to_b = self._resolve_pool(asset_in, asset_out)
        if tier is not None:
            return quote_swap(pool, amount, is_a_to_b, tier)
        return quote_swap_smart(pool, amount, is_a_to_b)

    def get_mint_quote(
        self, pool_id: int, amount_a: int, amount_b: int, tier: int,
    ) -> MintQuote:
        """Get mint quote without submitting."""
        pool = self.pool_reader.get_state(pool_id)
        return quote_mint(pool.tiers[tier], amount_a, amount_b)

    def get_burn_quote(
        self, pool_id: int, lp_amount: int, tier: int,
        single_sided: int | None = None,
    ) -> BurnQuote:
        """Get burn quote without submitting.

        single_sided: None for proportional, or asset_id to receive single asset.
        """
        pool = self.pool_reader.get_state(pool_id)
        ts = pool.tiers[tier]
        output_asset = ts.lp_asset_id if single_sided is None else single_sided
        return quote_burn(ts, lp_amount, output_asset, asset_a=pool.asset_a)

    # ── Liquidity ────────────────────────────────────────

    def mint(
        self, pool_id: int, amount_a: int, amount_b: int,
        tier: int, slippage_pct: float = 0.5,
        wait_rounds: int = DEFAULT_WAIT_ROUNDS,
    ) -> dict:
        """Add liquidity to a tier.

        If the sender is not yet opted into the tier's LP token, this method
        first sends a separate opt-in transaction and waits for it to confirm
        before submitting the mint group. Hardware-wallet users will be
        prompted to sign twice on the first mint per tier.
        """
        pool = self.pool_reader.get_state(pool_id)
        ts = pool.tiers[tier]

        if ts.total_lp == 0:
            raise TierNotSeededError(f"Tier {tier} not seeded")

        self._ensure_opted_in(ts.lp_asset_id, wait_rounds)

        quote = quote_mint(ts, amount_a, amount_b)
        if quote.expected_lp == 0:
            raise InsufficientLiquidityError("Zero LP output")

        min_lp = int(quote.expected_lp * (1 - slippage_pct / 100))
        txns = self.builder.build_mint(
            pool, amount_a, amount_b, tier, min_lp, self.sender,
            extra_opup=self._sync_opup(pool),
        )
        return self._submit(txns, wait_rounds)

    def burn(
        self, pool_id: int, lp_amount: int, tier: int,
        slippage_pct: float = 0.5,
        single_sided: int | None = None,
        wait_rounds: int = DEFAULT_WAIT_ROUNDS,
    ) -> dict:
        """Remove liquidity from a tier.
        single_sided: None for proportional, or asset_id to receive single asset.
        """
        pool = self.pool_reader.get_state(pool_id)
        ts = pool.tiers[tier]
        lp_asset = ts.lp_asset_id

        output_asset = lp_asset if single_sided is None else single_sided

        quote = quote_burn(ts, lp_amount, output_asset, asset_a=pool.asset_a)

        min_a = int(quote.expected_a * (1 - slippage_pct / 100))
        min_b = int(quote.expected_b * (1 - slippage_pct / 100))

        txns = self.builder.build_burn(
            pool, lp_amount, tier, min_a, min_b, output_asset, self.sender,
            extra_opup=self._sync_opup(pool),
        )
        return self._submit(txns, wait_rounds)

    def seed_tier(
        self, pool_id: int, tier: int,
        wait_rounds: int = DEFAULT_WAIT_ROUNDS,
    ) -> dict:
        """Seed an unseeded tier (1 micro of each asset)."""
        pool = self.pool_reader.get_state(pool_id)
        txns = self.builder.build_seed_tier(
            pool, tier, self.sender,
            extra_opup=self._sync_opup(pool),
        )
        return self._submit(txns, wait_rounds)

    def seed_and_mint(
        self, pool_id: int, deposit_a: int, deposit_b: int,
        tier: int,
        wait_rounds: int = DEFAULT_WAIT_ROUNDS,
    ) -> dict:
        """First liquidity provision on a new pool.

        No slippage parameter: the first deposit sets the initial price,
        so there is no prior reserve ratio to slip against.

        If the sender is not opted into the LP token, an opt-in transaction
        is submitted and confirmed before the seed_and_mint group.
        """
        pool = self.pool_reader.get_state(pool_id)
        ts = pool.tiers[tier]

        self._ensure_opted_in(ts.lp_asset_id, wait_rounds)

        txns = self.builder.build_seed_and_mint(
            pool, deposit_a, deposit_b, tier, 0, self.sender,
            extra_opup=self._sync_opup(pool),
        )
        return self._submit(txns, wait_rounds)

    # ── Read ─────────────────────────────────────────────

    def get_pool(self, asset_a: int, asset_b: int) -> PoolState | None:
        """Look up pool by asset pair (order-independent) and return full state."""
        pool_id = self.registry.get_pool(asset_a, asset_b)
        if pool_id is None:
            return None
        return self.pool_reader.get_state(pool_id)

    def get_pool_by_id(self, pool_id: int) -> PoolState:
        """Get full pool state by app ID."""
        return self.pool_reader.get_state(pool_id)

    def get_lp_info(self, lp_asset_id: int) -> LpInfo | None:
        """Look up pool info from an LP asset ID."""
        return self.registry.get_lp_info(lp_asset_id)

    def get_price(self, asset_a: int, asset_b: int) -> float | None:
        """Get current price of asset_a in terms of asset_b."""
        pool = self.get_pool(asset_a, asset_b)
        if pool is None:
            return None
        price = calculate_price(pool)
        # If user asked for B/A instead of A/B, invert
        if asset_a == pool.asset_b:
            return 1.0 / price if price > 0 else None
        return price

    def list_pools(self, page_size: int | None = None) -> list[tuple[int, int, int]]:
        """List all registered pools. Returns [(asset_a, asset_b, pool_id), ...].

        Walks the registry's pair boxes — one algod call to list, plus one per
        pool to read each pool_id. Fine at current scale; for thousands of
        pools, prefer `list_pool_ids` with an indexer client.

        page_size: optional per-page box limit. Some node providers reject
        explicit limits; pass None to use the provider's default.
        """
        return self.registry.list_pools(page_size=page_size)

    def list_pool_ids(self, page_size: int | None = None) -> list[int]:
        """List every pool app ID created by the factory.

        Uses the indexer if one was supplied at construction (fast at scale —
        single paginated query, no per-pool reads). Otherwise falls back to
        `list_pools` and discards the pair data, which is strictly slower.

        page_size: optional per-page limit. Pass None to use the provider default.
        """
        if self.indexer_reader is not None:
            return self.indexer_reader.list_pool_ids(page_size=page_size)
        return [pool_id for _, _, pool_id in self.registry.list_pools(page_size=page_size)]
