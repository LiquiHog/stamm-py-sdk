"""Raw transaction group builders for STAMM operations.

Each method returns a list of transactions with group ID already assigned.
ALGO pools auto-detected from pool_state.asset_a == 0.

Budget is provided externally via the Budget app or direct OpUp calls.
Each builder prepends budget calls automatically using the Budget app.
When hub is active (pool_state.hub_app_id > 0), hub app is included
in foreign_apps and extra fee is added for the inner notification call.
"""

from algosdk import transaction

from stamm.constants import (
    SELECTORS, TIER_P_INDEX,
    BUDGET_APP_ID, OPUP_APP_ID, BUDGET_PROVIDE_SEL, OPUP_COUNTS,
)
from stamm.types import PoolState
from stamm.errors import DuplicateTierError


def _suggested_params(algod_client, fee: int = 1000):
    params = algod_client.suggested_params()
    params.flat_fee = True
    params.fee = fee
    return params


def _build_deposit(sender: str, receiver: str, asset_id: int, amount: int, sp) -> transaction.Transaction:
    """Build a deposit transaction -- Payment for ALGO, AssetTransfer for ASA."""
    if asset_id == 0:
        return transaction.PaymentTxn(
            sender=sender, sp=sp, receiver=receiver, amt=amount,
        )
    return transaction.AssetTransferTxn(
        sender=sender, sp=sp, receiver=receiver, amt=amount, index=asset_id,
    )


def _assign_group(txns: list) -> list:
    """Assign group ID to a list of transactions."""
    gid = transaction.calculate_group_id(txns)
    for t in txns:
        t.group = gid
    return txns


def _build_budget_call(sender: str, sp_zero, opup_count: int) -> transaction.Transaction:
    """Build a Budget app call that spawns N inner OpUp calls."""
    return transaction.ApplicationCallTxn(
        sender=sender,
        sp=sp_zero,
        index=BUDGET_APP_ID,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[
            BUDGET_PROVIDE_SEL,
            opup_count.to_bytes(8, "big"),
        ],
        foreign_apps=[OPUP_APP_ID],
    )


def _foreign_assets(pool_state: PoolState, *extra):
    """Build deduplicated foreign_assets list."""
    assets = set()
    if pool_state.asset_a > 0:
        assets.add(pool_state.asset_a)
    assets.add(pool_state.asset_b)
    for a in extra:
        if a and a > 0:
            assets.add(a)
    return sorted(assets)


def _hub_extras(pool_state: PoolState):
    """Return (foreign_apps, extra_fee) for hub notification."""
    if pool_state.hub_app_id > 0:
        return [pool_state.hub_app_id], 1000
    return [], 0


class TransactionBuilder:
    def __init__(self, algod_client):
        self.algod = algod_client

    def build_swap(
        self, pool_state: PoolState,
        asset_in: int, amount_in: int, tier: int,
        min_output: int, sender: str,
        extra_opup: int = 0,
    ) -> list:
        """Build swap transaction group.
        Group: [budget_call, deposit, app_call]

        extra_opup: extra opup calls beyond the standard count. Pass 2 if the
        pool needs a sync (use `PoolReader.needs_sync` to detect).
        """
        sp_zero = _suggested_params(self.algod, fee=0)
        pool_addr = pool_state.address
        pool_id = pool_state.app_id
        hub_apps, hub_fee = _hub_extras(pool_state)
        opup_count = OPUP_COUNTS["swap"] + extra_opup

        budget_txn = _build_budget_call(sender, sp_zero, opup_count)
        deposit_txn = _build_deposit(sender, pool_addr, asset_in, amount_in, sp_zero)

        # Fee: 3 group txns + N opup inners + 1 pool inner (output) + hub
        total_fee = (3 + opup_count + 1 + len(hub_apps)) * 1000
        app_txn = transaction.ApplicationCallTxn(
            sender=sender,
            sp=_suggested_params(self.algod, fee=total_fee),
            index=pool_id,
            on_complete=transaction.OnComplete.NoOpOC,
            app_args=[
                SELECTORS["swap"],
                pool_state.asset_a.to_bytes(8, "big"),
                pool_state.asset_b.to_bytes(8, "big"),
                tier.to_bytes(8, "big"),
                min_output.to_bytes(8, "big"),
            ],
            foreign_assets=_foreign_assets(pool_state),
            foreign_apps=hub_apps,
            boxes=[(0, b"rt")],
        )
        return _assign_group([budget_txn, deposit_txn, app_txn])

    def build_swap_smart(
        self, pool_state: PoolState,
        asset_in: int, amount_in: int,
        min_output: int, sender: str,
        extra_opup: int = 0,
    ) -> list:
        """Build swap_smart transaction group.
        Group: [budget_call, deposit, app_call]

        extra_opup: extra opup calls beyond the standard count. Pass 2 if the
        pool needs a sync (use `PoolReader.needs_sync` to detect).
        """
        sp_zero = _suggested_params(self.algod, fee=0)
        pool_addr = pool_state.address
        pool_id = pool_state.app_id
        hub_apps, hub_fee = _hub_extras(pool_state)
        opup_count = OPUP_COUNTS["swap_smart"] + extra_opup

        budget_txn = _build_budget_call(sender, sp_zero, opup_count)
        deposit_txn = _build_deposit(sender, pool_addr, asset_in, amount_in, sp_zero)

        total_fee = (3 + opup_count + 1 + len(hub_apps)) * 1000
        app_txn = transaction.ApplicationCallTxn(
            sender=sender,
            sp=_suggested_params(self.algod, fee=total_fee),
            index=pool_id,
            on_complete=transaction.OnComplete.NoOpOC,
            app_args=[
                SELECTORS["swap_smart"],
                pool_state.asset_a.to_bytes(8, "big"),
                pool_state.asset_b.to_bytes(8, "big"),
                min_output.to_bytes(8, "big"),
            ],
            foreign_assets=_foreign_assets(pool_state),
            foreign_apps=hub_apps,
            boxes=[(0, b"rt")],
        )
        return _assign_group([budget_txn, deposit_txn, app_txn])

    def build_swap_routed(
        self, pool_state: PoolState,
        asset_in: int, amount_in: int,
        tiers: list, amounts: list,
        min_output: int, sender: str,
        price_num: int = 0, price_den: int = 0,
        extra_opup: int = 0,
    ) -> list:
        """Build swap_routed transaction group.
        Validates no duplicate tiers. Packs legs into byte[] ABI arg.

        extra_opup: extra opup calls beyond the standard count. Pass 2 if the
        pool needs a sync (use `PoolReader.needs_sync` to detect).
        """
        seen = set()
        for t in tiers:
            if t in seen:
                raise DuplicateTierError(f"Duplicate tier {t} in swap_routed")
            seen.add(t)

        legs = b""
        for t, a in zip(tiers, amounts):
            legs += t.to_bytes(1, "big") + a.to_bytes(8, "big")
        legs_encoded = len(legs).to_bytes(2, "big") + legs

        sp_zero = _suggested_params(self.algod, fee=0)
        pool_addr = pool_state.address
        pool_id = pool_state.app_id
        hub_apps, hub_fee = _hub_extras(pool_state)
        opup_count = OPUP_COUNTS["swap_routed"] + extra_opup

        budget_txn = _build_budget_call(sender, sp_zero, opup_count)
        deposit_txn = _build_deposit(sender, pool_addr, asset_in, amount_in, sp_zero)

        total_fee = (3 + opup_count + 1 + len(hub_apps)) * 1000
        app_txn = transaction.ApplicationCallTxn(
            sender=sender,
            sp=_suggested_params(self.algod, fee=total_fee),
            index=pool_id,
            on_complete=transaction.OnComplete.NoOpOC,
            app_args=[
                SELECTORS["swap_routed"],
                pool_state.asset_a.to_bytes(8, "big"),
                pool_state.asset_b.to_bytes(8, "big"),
                legs_encoded,
                price_num.to_bytes(8, "big"),
                price_den.to_bytes(8, "big"),
                min_output.to_bytes(8, "big"),
            ],
            foreign_assets=_foreign_assets(pool_state),
            foreign_apps=hub_apps,
            boxes=[(0, b"rt")],
        )
        return _assign_group([budget_txn, deposit_txn, app_txn])

    def build_swap_limit(
        self, pool_state: PoolState,
        asset_in: int, amount_in: int, tier: int,
        min_output: int, limit_num: int, limit_den: int,
        sender: str,
        extra_opup: int = 0,
    ) -> list:
        """Build swap_limit transaction group.

        extra_opup: extra opup calls beyond the standard count. Pass 2 if the
        pool needs a sync (use `PoolReader.needs_sync` to detect).
        """
        sp_zero = _suggested_params(self.algod, fee=0)
        pool_addr = pool_state.address
        pool_id = pool_state.app_id
        hub_apps, hub_fee = _hub_extras(pool_state)
        opup_count = OPUP_COUNTS["swap_limit"] + extra_opup

        budget_txn = _build_budget_call(sender, sp_zero, opup_count)
        deposit_txn = _build_deposit(sender, pool_addr, asset_in, amount_in, sp_zero)

        total_fee = (3 + opup_count + 1 + len(hub_apps)) * 1000
        app_txn = transaction.ApplicationCallTxn(
            sender=sender,
            sp=_suggested_params(self.algod, fee=total_fee),
            index=pool_id,
            on_complete=transaction.OnComplete.NoOpOC,
            app_args=[
                SELECTORS["swap_limit"],
                pool_state.asset_a.to_bytes(8, "big"),
                pool_state.asset_b.to_bytes(8, "big"),
                tier.to_bytes(8, "big"),
                limit_num.to_bytes(8, "big"),
                limit_den.to_bytes(8, "big"),
                min_output.to_bytes(8, "big"),
            ],
            foreign_assets=_foreign_assets(pool_state),
            foreign_apps=hub_apps,
            boxes=[(0, b"rt")],
        )
        return _assign_group([budget_txn, deposit_txn, app_txn])

    def build_mint(
        self, pool_state: PoolState,
        deposit_a: int, deposit_b: int, tier: int,
        min_lp_out: int, sender: str,
        extra_opup: int = 0,
    ) -> list:
        """Build mint transaction group.
        Group: [budget_call, a_transfer, b_transfer, app_call]

        extra_opup: extra opup calls beyond the standard count. Pass 2 if the
        pool needs a sync (use `PoolReader.needs_sync` to detect).
        """
        sp_zero = _suggested_params(self.algod, fee=0)
        pool_addr = pool_state.address
        pool_id = pool_state.app_id
        lp_asset = pool_state.tiers[tier].lp_asset_id
        hub_apps, hub_fee = _hub_extras(pool_state)
        opup_count = OPUP_COUNTS["mint"] + extra_opup

        budget_txn = _build_budget_call(sender, sp_zero, opup_count)
        a_txn = _build_deposit(sender, pool_addr, pool_state.asset_a, deposit_a, sp_zero)
        b_txn = _build_deposit(sender, pool_addr, pool_state.asset_b, deposit_b, sp_zero)

        # Fee: 4 group txns + N opup inners + 1 inner (LP transfer) + hub
        total_fee = (4 + opup_count + 1 + len(hub_apps)) * 1000
        app_txn = transaction.ApplicationCallTxn(
            sender=sender,
            sp=_suggested_params(self.algod, fee=total_fee),
            index=pool_id,
            on_complete=transaction.OnComplete.NoOpOC,
            app_args=[
                SELECTORS["mint"],
                pool_state.asset_a.to_bytes(8, "big"),
                pool_state.asset_b.to_bytes(8, "big"),
                lp_asset.to_bytes(8, "big"),
                tier.to_bytes(8, "big"),
                min_lp_out.to_bytes(8, "big"),
            ],
            foreign_assets=_foreign_assets(pool_state, lp_asset),
            foreign_apps=hub_apps,
            boxes=[(0, b"rt")],
        )
        return _assign_group([budget_txn, a_txn, b_txn, app_txn])

    def build_burn(
        self, pool_state: PoolState,
        lp_amount: int, tier: int,
        min_a_out: int, min_b_out: int,
        output_asset: int,
        sender: str,
        extra_opup: int = 0,
    ) -> list:
        """Build burn transaction group.
        output_asset: lp_asset_id for proportional, asset_a or asset_b for single-sided.
        Group: [budget_call, lp_transfer, app_call]

        extra_opup: extra opup calls beyond the standard count. Pass 2 if the
        pool needs a sync (use `PoolReader.needs_sync` to detect).
        """
        sp_zero = _suggested_params(self.algod, fee=0)
        pool_addr = pool_state.address
        pool_id = pool_state.app_id
        lp_asset = pool_state.tiers[tier].lp_asset_id
        hub_apps, hub_fee = _hub_extras(pool_state)
        opup_count = OPUP_COUNTS["burn"] + extra_opup

        budget_txn = _build_budget_call(sender, sp_zero, opup_count)
        lp_txn = transaction.AssetTransferTxn(
            sender=sender, sp=sp_zero, receiver=pool_addr,
            amt=lp_amount, index=lp_asset,
        )

        # Fee: 3 group txns + N opup inners + 2 inner (output transfers) + hub
        total_fee = (3 + opup_count + 2 + len(hub_apps)) * 1000
        app_txn = transaction.ApplicationCallTxn(
            sender=sender,
            sp=_suggested_params(self.algod, fee=total_fee),
            index=pool_id,
            on_complete=transaction.OnComplete.NoOpOC,
            app_args=[
                SELECTORS["burn"],
                lp_asset.to_bytes(8, "big"),
                pool_state.asset_a.to_bytes(8, "big"),
                pool_state.asset_b.to_bytes(8, "big"),
                tier.to_bytes(8, "big"),
                min_a_out.to_bytes(8, "big"),
                min_b_out.to_bytes(8, "big"),
                output_asset.to_bytes(8, "big"),
            ],
            foreign_assets=_foreign_assets(pool_state, lp_asset, output_asset),
            foreign_apps=hub_apps,
            boxes=[(0, b"rt")],
        )
        return _assign_group([budget_txn, lp_txn, app_txn])

    def build_seed_tier(
        self, pool_state: PoolState,
        tier: int, sender: str,
        extra_opup: int = 0,
    ) -> list:
        """Build seed_tier transaction group (1 micro of each asset).
        Group: [budget_call, a_transfer, b_transfer, app_call]

        extra_opup: extra opup calls beyond the standard count. Pass 2 if the
        pool needs a sync (use `PoolReader.needs_sync` to detect).
        """
        sp_zero = _suggested_params(self.algod, fee=0)
        pool_addr = pool_state.address
        pool_id = pool_state.app_id
        opup_count = OPUP_COUNTS["seed_tier"] + extra_opup

        budget_txn = _build_budget_call(sender, sp_zero, opup_count)
        a_txn = _build_deposit(sender, pool_addr, pool_state.asset_a, 1, sp_zero)
        b_txn = _build_deposit(sender, pool_addr, pool_state.asset_b, 1, sp_zero)

        total_fee = (4 + opup_count) * 1000
        app_txn = transaction.ApplicationCallTxn(
            sender=sender,
            sp=_suggested_params(self.algod, fee=total_fee),
            index=pool_id,
            on_complete=transaction.OnComplete.NoOpOC,
            app_args=[
                SELECTORS["seed_tier"],
                pool_state.asset_a.to_bytes(8, "big"),
                pool_state.asset_b.to_bytes(8, "big"),
                tier.to_bytes(8, "big"),
            ],
            foreign_assets=_foreign_assets(pool_state),
        )
        return _assign_group([budget_txn, a_txn, b_txn, app_txn])

    def build_seed_and_mint(
        self, pool_state: PoolState,
        deposit_a: int, deposit_b: int, tier: int,
        min_lp_out: int, sender: str,
        extra_opup: int = 0,
    ) -> list:
        """Build seed_and_mint transaction group (first liquidity provision).
        Deposits must include 4 extra micros each for seeding default tiers.
        Group: [budget_call, a_transfer, b_transfer, app_call]

        extra_opup: extra opup calls beyond the standard count. Pass 2 if the
        pool needs a sync (use `PoolReader.needs_sync` to detect).
        """
        sp_zero = _suggested_params(self.algod, fee=0)
        pool_addr = pool_state.address
        pool_id = pool_state.app_id
        lp_asset = pool_state.tiers[tier].lp_asset_id
        opup_count = OPUP_COUNTS["seed_and_mint"] + extra_opup

        total_a = deposit_a + 4
        total_b = deposit_b + 4

        budget_txn = _build_budget_call(sender, sp_zero, opup_count)
        a_txn = _build_deposit(sender, pool_addr, pool_state.asset_a, total_a, sp_zero)
        b_txn = _build_deposit(sender, pool_addr, pool_state.asset_b, total_b, sp_zero)

        total_fee = (4 + opup_count + 1) * 1000
        app_txn = transaction.ApplicationCallTxn(
            sender=sender,
            sp=_suggested_params(self.algod, fee=total_fee),
            index=pool_id,
            on_complete=transaction.OnComplete.NoOpOC,
            app_args=[
                SELECTORS["seed_and_mint"],
                pool_state.asset_a.to_bytes(8, "big"),
                pool_state.asset_b.to_bytes(8, "big"),
                lp_asset.to_bytes(8, "big"),
                tier.to_bytes(8, "big"),
                min_lp_out.to_bytes(8, "big"),
            ],
            foreign_assets=_foreign_assets(pool_state, lp_asset),
            boxes=[(0, b"rt")],
        )
        return _assign_group([budget_txn, a_txn, b_txn, app_txn])

    def build_opt_in(self, asset_id: int, sender: str) -> transaction.Transaction:
        """Build asset opt-in transaction (0-amount self-transfer)."""
        sp = _suggested_params(self.algod)
        return transaction.AssetTransferTxn(
            sender=sender, sp=sp, receiver=sender, amt=0, index=asset_id,
        )
