"""Bronze layer: persist every raw payload before parsing.

Raw-first means any normalizer bug is replayable -- we re-parse from bronze rather than
re-hitting an API whose quota we may have exhausted.

Two backends behind one interface. `local` writes to disk for dev; `s3` is the phase-6
production target. Layout is identical in both, so the migration is a config change:

    <root>/source=<source>/dt=YYYY-MM-DD/<key>.json.gz
"""

from __future__ import annotations

import gzip
import json
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.core.settings import Settings, get_settings

log = get_logger(__name__)


def bronze_object_path(source: str, observed_at: datetime, key: str) -> str:
    """Relative object path, shared by every backend."""
    return f"source={source}/dt={observed_at.strftime('%Y-%m-%d')}/{key}.json.gz"


def _encode(payload: Any) -> bytes:
    return gzip.compress(json.dumps(payload, default=str, separators=(",", ":")).encode("utf-8"))


class BronzeStore(ABC):
    @abstractmethod
    def put(self, source: str, observed_at: datetime, key: str, payload: Any) -> str:
        """Persist a raw payload. Returns the full location written."""

    @abstractmethod
    def get(self, source: str, observed_at: datetime, key: str) -> Any:
        """Read a raw payload back (used by replay/backfill)."""

    @abstractmethod
    def exists(self, source: str, observed_at: datetime, key: str) -> bool: ...


class LocalBronzeStore(BronzeStore):
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, source: str, observed_at: datetime, key: str) -> Path:
        return self.root / bronze_object_path(source, observed_at, key)

    def put(self, source: str, observed_at: datetime, key: str, payload: Any) -> str:
        path = self._path(source, observed_at, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename so a crash mid-write cannot leave a truncated payload.
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(_encode(payload))
        tmp.replace(path)
        return str(path)

    def get(self, source: str, observed_at: datetime, key: str) -> Any:
        return json.loads(gzip.decompress(self._path(source, observed_at, key).read_bytes()))

    def exists(self, source: str, observed_at: datetime, key: str) -> bool:
        return self._path(source, observed_at, key).exists()


class S3BronzeStore(BronzeStore):
    """Phase-6 backend. Imports boto3 lazily so dev installs stay slim."""

    def __init__(self, bucket: str, prefix: str = "bronze") -> None:
        import boto3  # noqa: PLC0415

        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self._client = boto3.client("s3")

    def _key(self, source: str, observed_at: datetime, key: str) -> str:
        return f"{self.prefix}/{bronze_object_path(source, observed_at, key)}"

    def put(self, source: str, observed_at: datetime, key: str, payload: Any) -> str:
        obj_key = self._key(source, observed_at, key)
        self._client.put_object(Bucket=self.bucket, Key=obj_key, Body=_encode(payload))
        return f"s3://{self.bucket}/{obj_key}"

    def get(self, source: str, observed_at: datetime, key: str) -> Any:
        import gzip as _gzip  # noqa: PLC0415

        obj = self._client.get_object(Bucket=self.bucket, Key=self._key(source, observed_at, key))
        return json.loads(_gzip.decompress(obj["Body"].read()))

    def exists(self, source: str, observed_at: datetime, key: str) -> bool:
        from botocore.exceptions import ClientError  # noqa: PLC0415

        try:
            self._client.head_object(Bucket=self.bucket, Key=self._key(source, observed_at, key))
        except ClientError:
            return False
        return True


def get_bronze_store(settings: Settings | None = None) -> BronzeStore:
    settings = settings or get_settings()
    if settings.bronze_backend == "s3":
        if not settings.bronze_s3_bucket:
            raise ValueError("BRONZE_BACKEND=s3 requires BRONZE_S3_BUCKET to be set")
        return S3BronzeStore(settings.bronze_s3_bucket)
    return LocalBronzeStore(settings.bronze_local_path)
