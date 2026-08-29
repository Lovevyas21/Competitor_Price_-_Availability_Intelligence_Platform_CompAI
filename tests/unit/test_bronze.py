from datetime import UTC, datetime

import pytest

from app.core.settings import Settings
from app.ingestion.bronze import (
    LocalBronzeStore,
    bronze_object_path,
    get_bronze_store,
)

OBSERVED = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


def test_roundtrip_preserves_payload(tmp_path):
    store = LocalBronzeStore(tmp_path)
    payload = {"id": 1, "price": 4.19, "nested": {"a": [1, 2]}}
    store.put("openprices", OBSERVED, "abc", payload)
    assert store.get("openprices", OBSERVED, "abc") == payload


def test_partition_layout_is_source_and_date(tmp_path):
    assert bronze_object_path("openprices", OBSERVED, "abc") == (
        "source=openprices/dt=2026-08-29/abc.json.gz"
    )


def test_exists_reflects_writes(tmp_path):
    store = LocalBronzeStore(tmp_path)
    assert not store.exists("s", OBSERVED, "k")
    store.put("s", OBSERVED, "k", {"x": 1})
    assert store.exists("s", OBSERVED, "k")


def test_no_temp_files_left_behind(tmp_path):
    """Writes go through a temp file then rename; nothing partial should survive."""
    store = LocalBronzeStore(tmp_path)
    store.put("s", OBSERVED, "k", {"x": 1})
    assert list(tmp_path.rglob("*.tmp")) == []


def test_factory_returns_local_backend(tmp_path):
    settings = Settings(bronze_backend="local", bronze_local_path=str(tmp_path))
    assert isinstance(get_bronze_store(settings), LocalBronzeStore)


def test_s3_backend_requires_bucket():
    settings = Settings(bronze_backend="s3", bronze_s3_bucket=None)
    with pytest.raises(ValueError, match="BRONZE_S3_BUCKET"):
        get_bronze_store(settings)
