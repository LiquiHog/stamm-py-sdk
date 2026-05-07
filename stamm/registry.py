"""Registry reader — direct box reads for pool/LP lookups."""

import base64

from algosdk.error import AlgodHTTPError
from algosdk.v2client import algod

from stamm.constants import REGISTRY_APP_ID
from stamm.types import LpInfo


class RegistryReader:
    def __init__(self, algod_client: algod.AlgodClient, registry_id: int = REGISTRY_APP_ID):
        self.algod = algod_client
        self.registry_id = registry_id

    def get_pool(self, asset_a: int, asset_b: int) -> int | None:
        """Look up pool app ID for an asset pair. Order-independent.
        Returns pool app ID, or None if no pool exists for the pair.
        """
        min_id = min(asset_a, asset_b)
        max_id = max(asset_a, asset_b)
        box_key = b"p" + min_id.to_bytes(8, "big") + max_id.to_bytes(8, "big")

        try:
            box = self.algod.application_box_by_name(self.registry_id, box_key)
        except AlgodHTTPError:
            return None
        value = base64.b64decode(box["value"])
        return int.from_bytes(value, "big")

    def get_lp_info(self, lp_asset_id: int) -> LpInfo | None:
        """Look up pool info for an LP asset ID.
        Returns LpInfo, or None if the LP asset is not registered.
        """
        box_key = b"l" + lp_asset_id.to_bytes(8, "big")

        try:
            box = self.algod.application_box_by_name(self.registry_id, box_key)
        except AlgodHTTPError:
            return None
        value = base64.b64decode(box["value"])
        pool_id = int.from_bytes(value[0:8], "big")
        a_id = int.from_bytes(value[8:16], "big")
        b_id = int.from_bytes(value[16:24], "big")
        tier = int.from_bytes(value[24:32], "big")
        return LpInfo(pool_id=pool_id, asset_a=a_id, asset_b=b_id, tier=tier)

    def list_pools(self, page_size: int | None = None) -> list[tuple[int, int, int]]:
        """Enumerate all registered pools via box listing API with pagination.
        Returns [(asset_a, asset_b, pool_id), ...] for all pair boxes.

        page_size: optional per-page box limit. Some node providers reject
        explicit limits; pass None to use the provider's default.
        """
        pools = []
        next_token = None
        while True:
            kwargs = {}
            if page_size is not None:
                kwargs["limit"] = page_size
            if next_token:
                kwargs["next_page"] = next_token
            result = self.algod.application_boxes(self.registry_id, **kwargs)
            for box_info in result.get("boxes", []):
                name = base64.b64decode(box_info["name"])
                if len(name) == 17 and name[0:1] == b"p":
                    a_id = int.from_bytes(name[1:9], "big")
                    b_id = int.from_bytes(name[9:17], "big")
                    try:
                        box = self.algod.application_box_by_name(self.registry_id, name)
                    except AlgodHTTPError:
                        continue
                    value = base64.b64decode(box["value"])
                    pool_id = int.from_bytes(value, "big")
                    pools.append((a_id, b_id, pool_id))
            next_token = result.get("next-token")
            if not next_token:
                break
        return pools
