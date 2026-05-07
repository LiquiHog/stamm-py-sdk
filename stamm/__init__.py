"""STAMM Python SDK — interact with STAMM multi-tier AMM pools on Algorand."""

from stamm.client import StammClient
from stamm.pool import PoolReader
from stamm.registry import RegistryReader
from stamm.indexer import IndexerReader
from stamm.builders import TransactionBuilder
from stamm.types import PoolState, TierState, SwapQuote, MintQuote, BurnQuote, LpInfo
from stamm.constants import MIN_SWAP_INPUT
from stamm.errors import (
    StammError,
    PoolNotFoundError,
    TierInactiveError,
    TierNotSeededError,
    InsufficientLiquidityError,
    SlippageError,
    NotOptedInError,
    DuplicateTierError,
    SwapBelowMinimumError,
)

__all__ = [
    "StammClient",
    "PoolReader",
    "RegistryReader",
    "IndexerReader",
    "TransactionBuilder",
    "PoolState",
    "TierState",
    "SwapQuote",
    "MintQuote",
    "BurnQuote",
    "LpInfo",
    "StammError",
    "PoolNotFoundError",
    "TierInactiveError",
    "TierNotSeededError",
    "InsufficientLiquidityError",
    "SlippageError",
    "NotOptedInError",
    "DuplicateTierError",
    "SwapBelowMinimumError",
    "MIN_SWAP_INPUT",
]
