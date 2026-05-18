from __future__ import annotations

import os

from temporalio.client import Client

_client: Client | None = None


def temporal_address() -> str:
    return os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")


def temporal_namespace() -> str:
    return os.environ.get("TEMPORAL_NAMESPACE", "default")


async def get_temporal_client() -> Client:
    global _client
    if _client is None:
        _client = await Client.connect(
            temporal_address(),
            namespace=temporal_namespace(),
        )
    return _client
