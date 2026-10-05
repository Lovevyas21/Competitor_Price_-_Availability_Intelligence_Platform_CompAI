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
    return sorted(name for name, cls in CLIENTS.items() if cls().is_available())
