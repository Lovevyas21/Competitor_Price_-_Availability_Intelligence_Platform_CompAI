from __future__ import annotations

import gzip
import json
from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.core.settings import Settings, get_settings

log = get_logger(__name__)


def bronze_object_path(source: str, observed_at: datetime, key: str) -> str:
    return f"source={source}/dt={observed_at.strftime('%Y-%m-%d')}/{key}.json.gz"


def _encode(payload: Any) -> bytes:
    return gzip.compress(json.dumps(payload, default=str, separators=(",", ":")).encode("utf-8"))


class BronzeStore(ABC):
    @abstractmethod
    def put(self, source: str, observed_at: datetime, key: str, payload: Any) -> str:
        pass

    @abstractmethod
    def get(self, source: str, observed_at: datetime, key: str) -> Any:
        pass

    @abstractmethod
    def exists(self, source: str, observed_at: datetime, key: str) -> bool: ...

    @abstractmethod
    def iter_payloads(self, source: str, observed_at: datetime) -> Iterator[Any]:
        pass


class LocalBronzeStore(BronzeStore):
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, source: str, observed_at: datetime, key: str) -> Path:
        return self.root / bronze_object_path(source, observed_at, key)

    def put(self, source: str, observed_at: datetime, key: str, payload: Any) -> str:
        path = self._path(source, observed_at, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(_encode(payload))
        tmp.replace(path)
        return str(path)

    def get(self, source: str, observed_at: datetime, key: str) -> Any:
        return json.loads(gzip.decompress(self._path(source, observed_at, key).read_bytes()))

    def exists(self, source: str, observed_at: datetime, key: str) -> bool:
        return self._path(source, observed_at, key).exists()

    def iter_payloads(self, source: str, observed_at: datetime) -> Iterator[Any]:
        day_dir = self.root / f"source={source}" / f"dt={observed_at.strftime('%Y-%m-%d')}"
        if not day_dir.is_dir():
            return
        for path in sorted(day_dir.glob("*.json.gz")):
            yield json.loads(gzip.decompress(path.read_bytes()))


class S3BronzeStore(BronzeStore):
    def __init__(
        self, bucket: str, prefix: str = "bronze", endpoint_url: str | None = None
    ) -> None:
        import boto3

        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self._client = boto3.client("s3", endpoint_url=endpoint_url or None)

    def _key(self, source: str, observed_at: datetime, key: str) -> str:
        return f"{self.prefix}/{bronze_object_path(source, observed_at, key)}"

    def put(self, source: str, observed_at: datetime, key: str, payload: Any) -> str:
        obj_key = self._key(source, observed_at, key)
        self._client.put_object(Bucket=self.bucket, Key=obj_key, Body=_encode(payload))
        return f"s3://{self.bucket}/{obj_key}"

    def get(self, source: str, observed_at: datetime, key: str) -> Any:
        import gzip as _gzip

        obj = self._client.get_object(Bucket=self.bucket, Key=self._key(source, observed_at, key))
        return json.loads(_gzip.decompress(obj["Body"].read()))

    def exists(self, source: str, observed_at: datetime, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._client.head_object(Bucket=self.bucket, Key=self._key(source, observed_at, key))
        except ClientError:
            return False
        return True

    def iter_payloads(self, source: str, observed_at: datetime) -> Iterator[Any]:
        import gzip as _gzip

        prefix = f"{self.prefix}/source={source}/dt={observed_at.strftime('%Y-%m-%d')}/"
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                body = self._client.get_object(Bucket=self.bucket, Key=obj["Key"])["Body"].read()
                yield json.loads(_gzip.decompress(body))


def get_bronze_store(settings: Settings | None = None) -> BronzeStore:
    settings = settings or get_settings()
    if settings.bronze_backend == "s3":
        if not settings.bronze_s3_bucket:
            raise ValueError("BRONZE_BACKEND=s3 requires BRONZE_S3_BUCKET to be set")
        return S3BronzeStore(
            settings.bronze_s3_bucket, endpoint_url=settings.bronze_s3_endpoint_url
        )
    return LocalBronzeStore(settings.bronze_local_path)


def get_deadletter_store(settings: Settings | None = None) -> BronzeStore:
    settings = settings or get_settings()
    if settings.bronze_backend == "s3":
        if not settings.bronze_s3_bucket:
            raise ValueError("BRONZE_BACKEND=s3 requires BRONZE_S3_BUCKET to be set")
        return S3BronzeStore(settings.bronze_s3_bucket, prefix="deadletter")
    return LocalBronzeStore(settings.deadletter_local_path)
