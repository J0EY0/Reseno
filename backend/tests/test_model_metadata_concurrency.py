import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event, current_thread

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.services import model_metadata


def test_concurrent_cache_writes_leave_one_complete_snapshot(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready_to_replace = Barrier(2)
    original_replace = Path.replace

    def replace(path: Path, target: Path) -> Path:
        ready_to_replace.wait(timeout=5)
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", replace)
    snapshots = [{"models": [str(index)] * 2_000} for index in range(2)]
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(model_metadata._write_cache, snapshot)
            for snapshot in snapshots
        ]
        for future in futures:
            future.result(timeout=10)

    cache_path = get_settings().data_dir / model_metadata.MODEL_METADATA_CACHE_NAME
    assert json.loads(cache_path.read_text(encoding="utf-8")) in snapshots
    assert list(cache_path.parent.glob("*.tmp")) == []


def test_concurrent_partial_refreshes_preserve_both_catalogs(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_write_started = Event()
    second_snapshot_read = Event()
    original_load = model_metadata._load_cache
    original_write = model_metadata._write_cache

    def fetch_catalog():
        if current_thread().name == "litellm":
            return {
                "openai/gpt-test": {
                    "litellm_provider": "openai",
                    "max_input_tokens": 128_000,
                    "supports_reasoning": True,
                },
            }
        return {}

    def fetch_reasoning():
        if current_thread().name == "models-dev":
            assert first_write_started.wait(timeout=5)
            return {
                "openai": {
                    "models": {
                        "gpt-test": {"reasoning_options": [{"type": "toggle"}]},
                    },
                },
            }
        return {}

    def load_cache():
        snapshot = original_load()
        if current_thread().name == "models-dev":
            second_snapshot_read.set()
        return snapshot

    def write_cache(cache):
        if current_thread().name == "litellm":
            first_write_started.set()
            second_snapshot_read.wait(timeout=0.2)
        original_write(cache)

    def refresh(name: str) -> bool:
        current_thread().name = name
        return model_metadata.refresh_model_metadata_cache(provider="openai")

    monkeypatch.setattr(model_metadata, "_fetch_catalog", fetch_catalog)
    monkeypatch.setattr(model_metadata, "_fetch_reasoning_catalog", fetch_reasoning)
    monkeypatch.setattr(model_metadata, "_load_cache", load_cache)
    monkeypatch.setattr(model_metadata, "_write_cache", write_cache)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(refresh, name) for name in ("litellm", "models-dev")]
        assert all(future.result(timeout=10) for future in futures)

    cache_path = get_settings().data_dir / model_metadata.MODEL_METADATA_CACHE_NAME
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert model_metadata._CATALOG_CACHE == cache
    metadata = model_metadata.resolve_model_metadata("openai", "gpt-test")
    assert metadata is not None
    assert metadata.context_window_tokens == 128_000
    assert metadata.can_disable_thinking is True
