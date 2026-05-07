"""Indexer-backed enumeration of pool app IDs.

Uses the Algorand indexer's `search_applications(creator=...)` to list every
pool the factory has deployed in a single paginated query, without per-pool
algod box reads. Use this when the registry walk in `RegistryReader.list_pools`
becomes too slow at scale.
"""

from algosdk.encoding import checksum, encode_address
from algosdk.v2client import indexer

from stamm.constants import FACTORY_APP_ID


def _app_address(app_id: int) -> str:
    return encode_address(checksum(b"appID" + app_id.to_bytes(8, "big")))


class IndexerReader:
    def __init__(
        self,
        indexer_client: indexer.IndexerClient,
        factory_id: int = FACTORY_APP_ID,
    ):
        self.indexer = indexer_client
        self.factory_id = factory_id
        self.factory_address = _app_address(factory_id)

    def list_pool_ids(self, page_size: int | None = None) -> list[int]:
        """List every pool app ID created by the factory.

        page_size: optional per-page application limit. Pass None to use the
        indexer provider's default.
        """
        pool_ids: list[int] = []
        next_token = None
        while True:
            kwargs = {"creator": self.factory_address}
            if page_size is not None:
                kwargs["limit"] = page_size
            if next_token:
                kwargs["next_page"] = next_token
            result = self.indexer.search_applications(**kwargs)
            for app in result.get("applications", []):
                pool_ids.append(app["id"])
            next_token = result.get("next-token")
            if not next_token:
                break
        return pool_ids
