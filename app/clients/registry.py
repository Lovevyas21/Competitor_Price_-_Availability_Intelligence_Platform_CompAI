"""Source registry.

Adding a source means adding one line here. The runner, the CLI and (in phase 2) the
Celery tasks all resolve clients through this table.
"""

from __future__ import annotations

from app.clients.base import SourceClient
from app.clients.fakestore import FakeStoreClient
from app.clients.openprices import OpenPricesClient

CLIENTS: dict[str, type[SourceClient]] = {
    FakeStoreClient.name: FakeStoreClient,
    OpenPricesClient.name: OpenPricesClient,
}


def get_client(name: str) -> SourceClient:
    try:
        return CLIENTS[name]()
    except KeyError:
        raise KeyError(f"unknown source '{name}'; known: {', '.join(sorted(CLIENTS))}") from None


def available_sources() -> list[str]:
    """Sources whose credentials (if any) are actually configured."""
    return sorted(name for name, cls in CLIENTS.items() if cls().is_available())
