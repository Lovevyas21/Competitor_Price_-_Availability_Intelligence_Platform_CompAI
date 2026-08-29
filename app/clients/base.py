"""Common source-client interface.

Every source -- keyless dev sources now, Best Buy / eBay / Digi-Key later -- implements
`SourceClient`. The ingestion runner only ever talks to this interface, so adding a real
retail API is a new file, not a change to the pipeline.
"""

from __future__ import annotations

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

from app.core.logging import get_logger
from app.core.settings import Settings, get_settings
from app.models.domain import NormalizedRecord

log = get_logger(__name__)

RETRYABLE = (httpx.TransportError, httpx.HTTPStatusError)


class SourceUnavailable(RuntimeError):
    """Raised when a source cannot be used (missing credentials, upstream down)."""


class SourceClient(ABC):
    #: Stable source name; matches `sources.name` in Postgres.
    name: str
    base_url: str
    auth_type: str = "none"
    #: Default retailer this source's listings belong to.
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

    # -- lifecycle -------------------------------------------------------------
    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- capability check ------------------------------------------------------
    def is_available(self) -> bool:
        """Keyless sources are always available; keyed sources check credentials."""
        return True

    # -- transport -------------------------------------------------------------
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

    # -- contract --------------------------------------------------------------
    @abstractmethod
    def fetch_raw(self, external_id: str) -> Any:
        """Fetch one product's raw payload. Raw is persisted before parsing."""

    @abstractmethod
    def normalize(self, raw: Any) -> NormalizedRecord | None:
        """Parse a raw payload into the normalized model. None = skip this record."""

    def iter_raw(self, raw: Any) -> Iterator[Any]:
        """Split one fetch_raw payload into individual observation payloads.

        Most sources return one product per fetch, so the default yields the payload
        unchanged. Sources whose per-SKU endpoint returns a *history* (many dated
        observations for one product) override this.
        """
        yield raw

    def top_external_ids(self, limit: int = 50) -> list[tuple[str, int, str | None]]:
        """Candidate SKUs worth tracking, richest history first.

        Returns (external_id, observation_count, label). Sources that cannot rank their
        catalogue return an empty list and are seeded manually instead.
        """
        return []

    @abstractmethod
    def discover(self, limit: int | None = None) -> Iterator[tuple[str, Any]]:
        """Yield (external_id, raw_payload) pairs for seeding / bulk refresh.

        Sources with a listing endpoint return many products per HTTP call, which is
        far cheaper than per-SKU fetches against a quota.
        """
