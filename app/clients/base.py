from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.core.settings import Settings, get_settings
from app.models.domain import NormalizedRecord

RETRYABLE = (httpx.TransportError, httpx.HTTPStatusError)


class SourceUnavailable(RuntimeError):
    pass


class SourceClient(ABC):
    name: str
    base_url: str
    auth_type: str = "none"
    default_retailer: str = "unknown"
    country: str | None = None

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=self.settings.http_timeout_seconds,
            headers={"User-Agent": "cpi-platform/0.1 (portfolio project)"},
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def is_available(self) -> bool:
        return True

    @retry(
        retry=retry_if_exception_type(RETRYABLE),
        stop=stop_after_attempt(4),
        wait=wait_exponential_jitter(initial=1, max=20),
        reraise=True,
    )
    def _get_json(self, path: str, **kwargs: Any) -> Any:
        resp = self._client.get(path, **kwargs)
        resp.raise_for_status()
        return resp.json()

    @abstractmethod
    def fetch_raw(self, external_id: str) -> Any:
        pass

    @abstractmethod
    def normalize(self, raw: Any) -> NormalizedRecord | None:
        pass

    def iter_raw(self, raw: Any) -> Iterator[Any]:
        yield raw

    def top_external_ids(self, limit: int = 50) -> list[tuple[str, int, str | None]]:
        return []

    @abstractmethod
    def discover(self, limit: int | None = None) -> Iterator[tuple[str, Any]]:
        pass
