import gzip
import json

import pytest

from app.core.settings import Settings
from app.ingestion import tasks
from app.ingestion.bronze import LocalBronzeStore, get_deadletter_store


@pytest.fixture
def dlq_store(tmp_path, monkeypatch):
    store = LocalBronzeStore(tmp_path)
    monkeypatch.setattr(tasks, "get_deadletter_store", lambda: store)
    return store, tmp_path


def test_dead_letter_writes_payload_and_context(dlq_store):
    _, root = dlq_store
    tasks.dead_letter(
        "validation_failed",
        {"source": "openprices", "external_id": "123"},
        payload={"price": None},
    )

    files = list(root.rglob("*.json.gz"))
    assert len(files) == 1

    written = json.loads(gzip.decompress(files[0].read_bytes()))
    assert written["reason"] == "validation_failed"
    assert written["context"]["external_id"] == "123"
    assert written["payload"] == {"price": None}
    assert "failed_at" in written


def test_dead_letters_are_partitioned_by_source(dlq_store):
    _, root = dlq_store
    tasks.dead_letter("quota_exhausted", {"source": "ebay", "external_id": "9"})
    assert list(root.glob("source=ebay/*"))


def test_distinct_reasons_do_not_overwrite_each_other(dlq_store):
    """Two different failures for one SKU must both survive for inspection."""
    _, root = dlq_store
    ctx = {"source": "openprices", "external_id": "123"}
    tasks.dead_letter("validation_failed", ctx)
    tasks.dead_letter("transport_retries_exhausted", ctx)
    assert len(list(root.rglob("*.json.gz"))) == 2


def test_deadletter_store_is_separate_from_bronze(tmp_path):
    settings = Settings(
        bronze_backend="local",
        bronze_local_path=str(tmp_path / "bronze"),
        deadletter_local_path=str(tmp_path / "deadletter"),
    )
    store = get_deadletter_store(settings)
    assert isinstance(store, LocalBronzeStore)
    assert store.root != tmp_path / "bronze"
