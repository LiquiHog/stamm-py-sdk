"""Data classes for STAMM SDK."""

from dataclasses import dataclass


@dataclass
class TierState:
    index: int
    char: str
    reserve_a: int
    reserve_b: int
    total_lp: int
    lp_asset_id: int
    treasury_lp: int
    fee_bps: int       # 3/10/30/100/300 for standard, 0 for Tier P
    fee_ppm: int       # normalized: 30/100/300/1000/3000 for standard, 1 for Tier P
    active: bool
    score_a2b: int
    score_b2a: int


@dataclass
class PoolState:
    app_id: int
    address: str
    asset_a: int
    asset_b: int
    aggregate_a: int
    aggregate_b: int
    treasury_a: int
    treasury_b: int
    mask: int
    tiers: list
    version: int
    hub_app_id: int
    registered: bool


@dataclass
class SwapQuote:
    amount_in: int
    expected_out: int
    effective_price: float
    price_impact_pct: float
    fee_total: int
    tiers_used: list
    is_a_to_b: bool


@dataclass
class MintQuote:
    deposit_a: int
    deposit_b: int
    expected_lp: int
    tier: int
    swap_amount: int
    residual_a: int
    residual_b: int


@dataclass
class BurnQuote:
    lp_amount: int
    expected_a: int
    expected_b: int
    tier: int
    output_asset: int
    is_single_sided: bool


@dataclass
class LpInfo:
    pool_id: int
    asset_a: int
    asset_b: int
    tier: int
