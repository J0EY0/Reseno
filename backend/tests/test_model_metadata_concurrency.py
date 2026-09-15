import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import AsyncMock

import pytest

from app.config import get_settings
from app.services import model_metadata


def test_concurrent_cache_writes_leave_one_complete_snapshot(
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


def test_concurrent_refreshes_fetch_each_source_once_and_publish_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        lite_started = asyncio.Event()
        reasoning_started = asyncio.Event()
        release = asyncio.Event()

        async def fetch_lite():
            lite_started.set()
            await release.wait()
            return {
                "openai/gpt-test": {
                    "litellm_provider": "openai",
                    "max_input_tokens": 128_000,
                    "supports_reasoning": True,
                },
            }

        async def fetch_reasoning():
            reasoning_started.set()
            await release.wait()
            return {
                "providers": {
                    "openai": {
                        "models": {
                            "gpt-test": {"reasoning_options": [{"type": "toggle"}]},
                        },
                    },
                },
                "models": {
                    "openai/base-test": {
                        "id": "openai/base-test",
                        "limit": {"context": 128000},
                    }
                },
            }

        lite = AsyncMock(side_effect=fetch_lite)
        reasoning = AsyncMock(side_effect=fetch_reasoning)
        monkeypatch.setattr(model_metadata, "_fetch_catalog", lite)
        monkeypatch.setattr(model_metadata, "_fetch_reasoning_catalog", reasoning)
        first = asyncio.create_task(model_metadata.refresh_model_metadata_cache())
        try:
            await asyncio.wait_for(
                asyncio.gather(lite_started.wait(), reasoning_started.wait()), 3
            )
            assert model_metadata.resolve_model_metadata("openai", "gpt-test") is None
            assert await model_metadata.refresh_model_metadata_cache() is False
            lite.assert_awaited_once()
            reasoning.assert_awaited_once()
        finally:
            release.set()
            await first

        cache_path = get_settings().data_dir / model_metadata.MODEL_METADATA_CACHE_NAME
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        assert model_metadata._CATALOG_CACHE == cache
        metadata = model_metadata.resolve_model_metadata("openai", "gpt-test")
        assert metadata is not None
        assert metadata.context_window_tokens == 128_000
        assert metadata.can_disable_thinking is True

    asyncio.run(run())
