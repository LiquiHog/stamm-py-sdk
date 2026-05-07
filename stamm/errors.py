"""Custom exception types for the STAMM SDK."""


class StammError(Exception):
    """Base exception for STAMM SDK."""


class PoolNotFoundError(StammError):
    """No pool exists for the given asset pair."""


class TierInactiveError(StammError):
    """The requested tier is not active."""


class TierNotSeededError(StammError):
    """The requested tier has not been seeded."""


class InsufficientLiquidityError(StammError):
    """Not enough liquidity for the requested operation."""


class SlippageError(StammError):
    """Expected output is below the minimum after slippage."""


class NotOptedInError(StammError):
    """User is not opted into the required asset."""


class DuplicateTierError(StammError):
    """swap_routed received duplicate tier indices."""


class SwapBelowMinimumError(StammError):
    """Swap amount is below the per-tier minimum input.

    Below this threshold the tier's fee rounds to zero and the contract
    returns zero output. Use a larger amount or route through a higher-fee tier.
    """

    def __init__(self, tier: int, minimum: int, amount: int):
        self.tier = tier
        self.minimum = minimum
        self.amount = amount
        super().__init__(
            f"Amount {amount} is below minimum {minimum} for tier {tier}"
        )
