from __future__ import annotations

import os

from ripple.rib.graph.postgres_store import PostgresStore
from ripple.rib.graph.store import RippleStore

_store: RippleStore | None = None


def get_store() -> RippleStore:
    global _store
    if _store is not None:
        return _store
    database_url = os.environ.get("RIB_DATABASE_URL")
    if not database_url:
        raise RuntimeError("RIB_DATABASE_URL is required (PostgreSQL)")
    _store = PostgresStore(database_url)
    return _store


def reset_store() -> None:
    global _store
    _store = None
