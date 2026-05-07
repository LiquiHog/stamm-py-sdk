"""Offline quote calculations — no network calls."""

from stamm.constants import (
    TIER_FEES_BPS, TIER_P_INDEX, TIER_P_FEE_PPM,
    TIER_RETAINED_PCT, EFFECTIVE_FEE_DENOM, TIER_FEES_PPM,
    NUM_TIERS, MIN_SWAP_INPUT,
)
from stamm.types import PoolState, TierState, SwapQuote, MintQuote, BurnQuote


def get_tier_fee_bps(tier: int) -> int:
    """Return fee in basis points for scoring. Tier P returns 1."""
    if tier == TIER_P_INDEX:
        return 1
    return TIER_FEES_BPS[tier]


def calculate_tier_fee(amount_in: int, tier: int) -> int:
    """Calculate total fee for a swap amount on a tier.
    Standard: floor(amount_in * fee_bps / 10_000)
    Tier P: max(1, floor(amount_in / 1_000_000))
    """
    if tier == TIER_P_INDEX:
        fee = amount_in // TIER_P_FEE_PPM
        return fee if fee > 0 else 1
    fee_bps = TIER_FEES_BPS[tier]
    return safe_mul_div(amount_in, fee_bps, 10_000)


def split_protocol_fee(total_fee: int, tier: int) -> tuple[int, int]:
    """Split fee into (tier_retained, protocol_fee)."""
    if tier == TIER_P_INDEX:
        return total_fee, 0
    retained = safe_mul_div(total_fee, TIER_RETAINED_PCT, 100)
    if retained == 0:
        retained = 1
    protocol = 0
    if total_fee >= retained:
        protocol = total_fee - retained
    return retained, protocol


def safe_mul_div(a: int, b: int, c: int) -> int:
    """floor(a * b / c) with overflow-safe 128-bit intermediate."""
    if c == 0:
        return 0
    return (a * b) // c


def sqrt128(hi: int, lo: int) -> int:
    """128-bit integer square root."""
    val = (hi << 64) | lo
    if val == 0:
        return 0
    x = val
    y = (x + 1) // 2
    while y < x:
        x = y
        y = (x + val // x) // 2
    return x


def swap_with_split_fees(
    reserve_in: int, reserve_out: int, amount_in: int, tier: int,
) -> tuple[int, int, int, int, int]:
    """Quote a swap with two-sided fees on a single tier.

    Returns (new_reserve_in, new_reserve_out, output, proto_in, proto_out).
    """
    total_fee = calculate_tier_fee(amount_in, tier)

    # If the fee rounds to zero, no output is produced.
    if total_fee == 0:
        return reserve_in + amount_in, reserve_out, 0, 0, 0

    input_fee = total_fee // 2
    output_fee_share = total_fee - input_fee

    if input_fee == 0:
        input_fee = 1

    input_retained, input_proto = split_protocol_fee(input_fee, tier)
    effective = amount_in - input_fee

    if reserve_in + effective == 0:
        return reserve_in, reserve_out, 0, 0, 0
    raw_output = safe_mul_div(reserve_out, effective, reserve_in + effective)

    out_fee = 0
    if amount_in > 0:
        out_fee = safe_mul_div(raw_output, output_fee_share, amount_in)

    if out_fee == 0 and raw_output > 0:
        out_fee = 1

    out_retained, out_proto = split_protocol_fee(out_fee, tier)
    user_output = raw_output - out_fee

    new_in = reserve_in + effective + input_retained
    new_out = reserve_out - raw_output + out_retained

    return new_in, new_out, user_output, input_proto, out_proto


def quote_swap(
    pool_state: PoolState, amount_in: int, is_a_to_b: bool, tier: int,
) -> SwapQuote:
    """Quote a single-tier swap."""
    ts = pool_state.tiers[tier]
    if is_a_to_b:
        r_in, r_out = ts.reserve_a, ts.reserve_b
    else:
        r_in, r_out = ts.reserve_b, ts.reserve_a

    if r_in <= 1 or r_out <= 1:
        return SwapQuote(
            amount_in=amount_in, expected_out=0, effective_price=0,
            price_impact_pct=100.0, fee_total=0, tiers_used=[tier],
            is_a_to_b=is_a_to_b,
        )

    _, _, dy, _, _ = swap_with_split_fees(r_in, r_out, amount_in, tier)
    fee_total = calculate_tier_fee(amount_in, tier)

    spot_price = r_out / r_in if r_in > 0 else 0
    effective_price = amount_in / dy if dy > 0 else float("inf")
    exec_price_ratio = dy / amount_in if amount_in > 0 else 0
    impact = (1 - exec_price_ratio / spot_price) * 100 if spot_price > 0 else 100.0

    return SwapQuote(
        amount_in=amount_in,
        expected_out=dy,
        effective_price=effective_price,
        price_impact_pct=max(0.0, impact),
        fee_total=fee_total,
        tiers_used=[tier],
        is_a_to_b=is_a_to_b,
    )


def quote_swap_smart(
    pool_state: PoolState, amount_in: int, is_a_to_b: bool,
) -> SwapQuote:
    """Quote a smart-routed swap across the best-scoring active tiers."""
    # Skip tiers where amount_in is below the per-tier minimum
    # (those legs would silently return 0 output).
    best_t, best_score = NUM_TIERS, 0
    second_t, second_score = NUM_TIERS, 0
    third_t, third_score = NUM_TIERS, 0

    for i in range(NUM_TIERS):
        if amount_in < MIN_SWAP_INPUT.get(i, 0):
            continue
        ts = pool_state.tiers[i]
        score = ts.score_a2b if is_a_to_b else ts.score_b2a
        if score > best_score:
            third_score, third_t = second_score, second_t
            second_score, second_t = best_score, best_t
            best_score, best_t = score, i
        elif score > second_score:
            third_score, third_t = second_score, second_t
            second_score, second_t = score, i
        elif score > third_score:
            third_score, third_t = score, i

    if best_t >= NUM_TIERS or best_score == 0:
        return SwapQuote(
            amount_in=amount_in, expected_out=0, effective_price=0,
            price_impact_pct=100.0, fee_total=0, tiers_used=[],
            is_a_to_b=is_a_to_b,
        )

    best_ts = pool_state.tiers[best_t]
    best_ra, best_rb = best_ts.reserve_a, best_ts.reserve_b

    # Default: 100% to best
    amt_best = amount_in
    amt_second = 0
    amt_third = 0

    if second_t < NUM_TIERS:
        second_ts = pool_state.tiers[second_t]
        second_ra, second_rb = second_ts.reserve_a, second_ts.reserve_b

        r_in_best = best_ra if is_a_to_b else best_rb
        r_in_second = second_ra if is_a_to_b else second_rb

        x_val = safe_mul_div(best_ra, second_score, best_score)
        prod = x_val * best_rb
        capacity_r_in = sqrt128(prod >> 64, prod & ((1 << 64) - 1))
        capacity1 = max(0, capacity_r_in - r_in_best)

        capacity2 = 0
        capacity2_r_in = 0
        r_in_third = 0

        if third_t < NUM_TIERS:
            third_ts = pool_state.tiers[third_t]
            third_ra, third_rb = third_ts.reserve_a, third_ts.reserve_b
            r_in_third = third_ra if is_a_to_b else third_rb

            x_val2 = safe_mul_div(second_ra, third_score, second_score)
            prod2 = x_val2 * second_rb
            capacity2_r_in = sqrt128(prod2 >> 64, prod2 & ((1 << 64) - 1))
            capacity2 = max(0, capacity2_r_in - r_in_second)

        if capacity1 < amount_in:
            remaining = amount_in - capacity1
            if capacity2 == 0 or remaining <= capacity2:
                adj_best = 10000 - get_tier_fee_bps(best_t)
                adj_second = 10000 - get_tier_fee_bps(second_t)
                r_adj = safe_mul_div(r_in_second, adj_second, adj_best)
                denom = capacity_r_in + r_adj
                if denom > 0:
                    split_best = safe_mul_div(remaining, capacity_r_in, denom)
                else:
                    split_best = remaining
                amt_best = capacity1 + split_best
                amt_second = remaining - split_best
            else:
                remaining2 = remaining - capacity2
                total_w = capacity_r_in + capacity2_r_in + r_in_third
                if total_w > 0:
                    s_best = safe_mul_div(remaining2, capacity_r_in, total_w)
                    s_second = safe_mul_div(remaining2, capacity2_r_in, total_w)
                    s_third = remaining2 - s_best - s_second
                    amt_best = capacity1 + s_best
                    amt_second = capacity2 + s_second
                    amt_third = s_third

    # Execute swaps and compute total output
    total_out = 0
    total_fee = 0
    tiers_used = []

    def _exec(ra, rb, amt, tier):
        r_in = ra if is_a_to_b else rb
        r_out = rb if is_a_to_b else ra
        _, _, dy, _, _ = swap_with_split_fees(r_in, r_out, amt, tier)
        return dy, calculate_tier_fee(amt, tier)

    if amt_best > 0:
        dy, fee = _exec(best_ra, best_rb, amt_best, best_t)
        total_out += dy
        total_fee += fee
        tiers_used.append(best_t)

    if amt_second > 0 and second_t < NUM_TIERS:
        dy, fee = _exec(second_ra, second_rb, amt_second, second_t)
        total_out += dy
        total_fee += fee
        tiers_used.append(second_t)

    if amt_third > 0 and third_t < NUM_TIERS:
        third_ts = pool_state.tiers[third_t]
        dy, fee = _exec(third_ts.reserve_a, third_ts.reserve_b, amt_third, third_t)
        total_out += dy
        total_fee += fee
        tiers_used.append(third_t)

    spot_a = pool_state.aggregate_b / pool_state.aggregate_a if pool_state.aggregate_a > 0 else 0
    spot_b = pool_state.aggregate_a / pool_state.aggregate_b if pool_state.aggregate_b > 0 else 0
    spot = spot_a if is_a_to_b else spot_b
    exec_ratio = total_out / amount_in if amount_in > 0 else 0
    impact = (1 - exec_ratio / spot) * 100 if spot > 0 else 100.0

    return SwapQuote(
        amount_in=amount_in,
        expected_out=total_out,
        effective_price=amount_in / total_out if total_out > 0 else float("inf"),
        price_impact_pct=max(0.0, impact),
        fee_total=total_fee,
        tiers_used=tiers_used,
        is_a_to_b=is_a_to_b,
    )


def quote_mint(
    tier_state: TierState, deposit_a: int, deposit_b: int,
) -> MintQuote:
    """Quote LP minting — handles balanced, hybrid, and single-sided."""
    ra, rb, tlp = tier_state.reserve_a, tier_state.reserve_b, tier_state.total_lp
    tier = tier_state.index

    if tlp <= 1:
        # Bootstrap: LP = sqrt(deposit_a * deposit_b)
        prod = deposit_a * deposit_b
        lp = sqrt128(prod >> 64, prod & ((1 << 64) - 1))
        return MintQuote(
            deposit_a=deposit_a, deposit_b=deposit_b,
            expected_lp=lp, tier=tier,
            swap_amount=0, residual_a=0, residual_b=0,
        )

    # Determine excess side by LP contribution
    lp_from_a = safe_mul_div(deposit_a, tlp, ra) if ra > 0 else 0
    lp_from_b = safe_mul_div(deposit_b, tlp, rb) if rb > 0 else 0

    if lp_from_a > lp_from_b:
        in_r, out_r = ra, rb
        dep_in, dep_out = deposit_a, deposit_b
    else:
        in_r, out_r = rb, ra
        dep_in, dep_out = deposit_b, deposit_a

    # Compute optimal swap amount for the excess side
    x_val = safe_mul_div(in_r, out_r, dep_out + out_r)
    prod = x_val * (dep_in + in_r)
    sqrt_val = sqrt128(prod >> 64, prod & ((1 << 64) - 1))

    swap_amount = 0
    if sqrt_val > in_r:
        swap_no_fee = sqrt_val - in_r
        fee_bps = get_tier_fee_bps(tier)
        swap_amount = safe_mul_div(swap_no_fee, EFFECTIVE_FEE_DENOM - fee_bps, EFFECTIVE_FEE_DENOM)
        if swap_amount > dep_in:
            swap_amount = dep_in
        if swap_amount == 0:
            swap_amount = 1

    if swap_amount > 0:
        post_in, post_out, swap_out, _, _ = swap_with_split_fees(
            in_r, out_r, swap_amount, tier,
        )
        if lp_from_a > lp_from_b:
            post_ra, post_rb = post_in, post_out
            user_a = deposit_a - swap_amount
            user_b = deposit_b + swap_out
        else:
            post_ra, post_rb = post_out, post_in
            user_a = deposit_a + swap_out
            user_b = deposit_b - swap_amount
    else:
        post_ra, post_rb = ra, rb
        user_a, user_b = deposit_a, deposit_b

    # Balanced mint from post-swap reserves
    lp_a = safe_mul_div(user_a, tlp, post_ra) if post_ra > 0 else 0
    lp_b = safe_mul_div(user_b, tlp, post_rb) if post_rb > 0 else 0
    lp_minted = min(lp_a, lp_b)

    mint_a = safe_mul_div(lp_minted, post_ra, tlp) if tlp > 0 else 0
    mint_b = safe_mul_div(lp_minted, post_rb, tlp) if tlp > 0 else 0
    residual_a = user_a - mint_a
    residual_b = user_b - mint_b

    return MintQuote(
        deposit_a=deposit_a, deposit_b=deposit_b,
        expected_lp=lp_minted, tier=tier,
        swap_amount=swap_amount, residual_a=residual_a, residual_b=residual_b,
    )


def quote_burn(
    tier_state: TierState, lp_amount: int, output_asset: int,
    asset_a: int = 0,
) -> BurnQuote:
    """Quote burn — proportional or single-sided.

    output_asset: lp_asset_id for proportional, asset_a or asset_b for single-sided.
    asset_a: the pool's asset_a ID, needed for single-sided direction detection.
    """
    ra, rb, tlp = tier_state.reserve_a, tier_state.reserve_b, tier_state.total_lp
    tier = tier_state.index

    if tlp == 0:
        return BurnQuote(
            lp_amount=lp_amount, expected_a=0, expected_b=0,
            tier=tier, output_asset=output_asset,
            is_single_sided=False,
        )

    # Proportional withdrawal
    a_out = safe_mul_div(lp_amount, ra, tlp)
    b_out = safe_mul_div(lp_amount, rb, tlp)

    is_single = output_asset != tier_state.lp_asset_id

    if is_single:
        post_ra = ra - a_out
        post_rb = rb - b_out

        if output_asset == asset_a:
            # Single to A: convert b_out to a via swap
            if post_rb > 0 and post_ra > 0:
                _, _, extra_a, _, _ = swap_with_split_fees(post_rb, post_ra, b_out, tier)
                return BurnQuote(
                    lp_amount=lp_amount, expected_a=a_out + extra_a, expected_b=0,
                    tier=tier, output_asset=output_asset,
                    is_single_sided=True,
                )
        else:
            # Single to B: convert a_out to b via swap
            if post_ra > 0 and post_rb > 0:
                _, _, extra_b, _, _ = swap_with_split_fees(post_ra, post_rb, a_out, tier)
                return BurnQuote(
                    lp_amount=lp_amount, expected_a=0, expected_b=b_out + extra_b,
                    tier=tier, output_asset=output_asset,
                    is_single_sided=True,
                )

    return BurnQuote(
        lp_amount=lp_amount, expected_a=a_out, expected_b=b_out,
        tier=tier, output_asset=output_asset,
        is_single_sided=is_single,
    )


def calculate_price(pool_state: PoolState) -> float:
    """Price of A in terms of B from aggregate reserves."""
    if pool_state.aggregate_a == 0:
        return 0.0
    return pool_state.aggregate_b / pool_state.aggregate_a


def calculate_tier_price(tier_state: TierState) -> float:
    """Price of A in terms of B from a specific tier."""
    if tier_state.reserve_a == 0:
        return 0.0
    return tier_state.reserve_b / tier_state.reserve_a
