"""Pool state reader — reads on-chain state into typed objects."""

import base64

from algosdk import encoding
from algosdk.error import AlgodHTTPError
from algosdk.v2client import algod

from stamm.constants import (
    NUM_TIERS, TIER_CHARS, TIER_FEES_BPS, TIER_FEES_PPM,
    TIER_P_INDEX, RT_ENTRY_SIZE, RT_BOX_SIZE,
)
from stamm.types import PoolState, TierState


def _app_address(app_id: int) -> str:
    return encoding.encode_address(
        encoding.checksum(b"appID" + app_id.to_bytes(8, "big"))
    )


def _decode_global_state(algod_client: algod.AlgodClient, app_id: int) -> dict:
    app_info = algod_client.application_info(app_id)
    state = {}
    for item in app_info.get("params", {}).get("global-state", []):
        key = base64.b64decode(item["key"]).decode("utf-8", errors="replace")
        val = item["value"]
        if val["type"] == 1:
            state[key] = base64.b64decode(val.get("bytes", ""))
        else:
            state[key] = val.get("uint", 0)
    return state


class PoolReader:
    def __init__(self, algod_client: algod.AlgodClient):
        self.algod = algod_client

    def get_state(self, pool_id: int) -> PoolState:
        """Read full pool state including all tiers and RT box."""
        state = _decode_global_state(self.algod, pool_id)

        # Asset IDs (stored as GlobalState with explicit keys)
        aa = state.get("aa", 0)
        ab = state.get("ab", 0)
        if isinstance(aa, bytes):
            aa = int.from_bytes(aa, "big") if len(aa) == 8 else 0
        if isinstance(ab, bytes):
            ab = int.from_bytes(ab, "big") if len(ab) == 8 else 0

        mask = state.get("m", 0)

        # Read RT box scores
        rt_scores = self._read_rt_box(pool_id)

        # Build tier states
        tiers = []
        for i in range(NUM_TIERS):
            c = TIER_CHARS[i]
            ra = state.get(f"t{c}_ra", 0)
            rb = state.get(f"t{c}_rb", 0)
            lp = state.get(f"t{c}_lp", 0)
            la = state.get(f"t{c}_la", 0)
            tl = state.get(f"t{c}_tl", 0)
            active = bool(mask & (1 << i))
            s_a2b, s_b2a = rt_scores[i] if i < len(rt_scores) else (0, 0)

            tiers.append(TierState(
                index=i,
                char=c,
                reserve_a=ra,
                reserve_b=rb,
                total_lp=lp,
                lp_asset_id=la,
                treasury_lp=tl,
                fee_bps=TIER_FEES_BPS.get(i, 0),
                fee_ppm=TIER_FEES_PPM.get(i, 1),
                active=active,
                score_a2b=s_a2b,
                score_b2a=s_b2a,
            ))

        return PoolState(
            app_id=pool_id,
            address=_app_address(pool_id),
            asset_a=aa,
            asset_b=ab,
            aggregate_a=state.get("xa", 0),
            aggregate_b=state.get("xb", 0),
            treasury_a=state.get("ta", 0),
            treasury_b=state.get("tb", 0),
            mask=mask,
            tiers=tiers,
            version=state.get("v", 0),
            hub_app_id=state.get("ha", 0),
            registered=bool(state.get("r", 0)),
        )

    def get_tier(self, pool_id: int, tier: int) -> TierState:
        """Read a single tier's state."""
        pool = self.get_state(pool_id)
        return pool.tiers[tier]

    def get_routing_table(self, pool_id: int) -> list[tuple[int, int]]:
        """Read RT box — returns [(score_a2b, score_b2a)] per tier."""
        return self._read_rt_box(pool_id)

    def get_balances(self, pool_id: int, asset_a: int = None, asset_b: int = None) -> tuple[int, int]:
        """Get actual on-chain asset balances of the pool.
        For ALGO pools (asset_a == 0), subtracts min_balance from ALGO balance.
        """
        addr = _app_address(pool_id)
        acct = self.algod.account_info(addr)

        if asset_a is None or asset_b is None:
            state = self.get_state(pool_id)
            asset_a = state.asset_a
            asset_b = state.asset_b

        if asset_a == 0:
            bal_a = acct["amount"] - acct["min-balance"]
        else:
            bal_a = 0
            for a in acct.get("assets", []):
                if a["asset-id"] == asset_a:
                    bal_a = a["amount"]
                    break

        bal_b = 0
        for a in acct.get("assets", []):
            if a["asset-id"] == asset_b:
                bal_b = a["amount"]
                break

        return bal_a, bal_b

    def _read_rt_box(self, pool_id: int) -> list[tuple[int, int]]:
        """Read the RT box and parse into per-tier score tuples.

        Returns all-zero scores if the box does not exist (e.g. on a freshly
        created pool). Other algod or parsing errors propagate.
        """
        try:
            box = self.algod.application_box_by_name(pool_id, b"rt")
        except AlgodHTTPError:
            return [(0, 0)] * NUM_TIERS

        data = base64.b64decode(box["value"])
        scores = []
        for i in range(NUM_TIERS):
            offset = i * RT_ENTRY_SIZE
            s_a2b = int.from_bytes(data[offset:offset + 8], "big")
            s_b2a = int.from_bytes(data[offset + 8:offset + 16], "big")
            scores.append((s_a2b, s_b2a))
        return scores
