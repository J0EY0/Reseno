import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.config import get_settings
from app.services import model_metadata


def _catalog_inputs() -> tuple[dict, dict]:
    return (
        {
            "openai/gpt-test": {
                "litellm_provider": "openai",
                "max_input_tokens": 128_000,
                "max_output_tokens": 8_192,
                "supports_reasoning": True,
                "supports_function_calling": True,
                "supports_vision": True,
                "supports_native_streaming": True,
                "supports_web_search": True,
            },
        },
        {
            "providers": {
                "openai": {
                    "models": {
                        "gpt-test": {
                            "reasoning": True,
                            "reasoning_options": [{"type": "toggle"}],
                        },
                    },
                },
            },
            "models": {
                "openai/base-test": {
                    "id": "openai/base-test",
                    "limit": {"context": 128000},
                }
            },
        },
    )


def _snapshot(*, age_days: int = 30) -> dict:
    lite, reasoning = _catalog_inputs()
    return model_metadata.build_model_metadata_snapshot(
        lite,
        reasoning,
        fetched_at=(datetime.now(UTC) - timedelta(days=age_days)).isoformat(),
    )


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_first_offline_load_uses_bundled_facts_without_creating_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = tmp_path / "bundled-models.json"
    _write_json(bundle, _snapshot())
    monkeypatch.setattr(model_metadata, "MODEL_METADATA_SNAPSHOT_PATH", bundle)
    fetch = AsyncMock(side_effect=AssertionError("metadata reads must remain local"))
    monkeypatch.setattr(model_metadata, "_fetch_catalog", fetch)
    monkeypatch.setattr(model_metadata, "_fetch_reasoning_catalog", fetch)

    metadata = model_metadata.resolve_model_metadata("openai", "gpt-test")

    assert metadata is not None
    assert metadata.context_window_tokens == 128_000
    assert metadata.max_output_tokens == 8_192
    assert metadata.supports_tools is True
    assert metadata.supports_image is True
    assert metadata.supports_streaming is True
    assert metadata.supports_web_search is True
    assert metadata.can_disable_thinking is True
    assert not (tmp_path / model_metadata.MODEL_METADATA_CACHE_NAME).exists()
    fetch.assert_not_called()


@pytest.mark.parametrize("same_litellm_time", [False, True])
def test_bundle_and_disk_select_newest_whole_source_without_model_backfill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    same_litellm_time: bool,
) -> None:
    bundle = _snapshot(age_days=10)
    disk = _snapshot(age_days=20)
    if same_litellm_time:
        disk["catalogs"]["litellm"]["fetchedAt"] = bundle["catalogs"]["litellm"][
            "fetchedAt"
        ]
    disk["catalogs"]["litellm"]["providers"]["openai"] = {
        "gpt-disk": {"contextWindowTokens": 32_000}
    }
    disk["catalogs"]["modelsDev"]["fetchedAt"] = datetime.now(UTC).isoformat()
    disk["catalogs"]["modelsDev"]["providers"]["openai"]["gpt-test"][
        "canDisableThinking"
    ] = False
    bundled_path = tmp_path / "bundled-models.json"
    _write_json(bundled_path, bundle)
    _write_json(tmp_path / model_metadata.MODEL_METADATA_CACHE_NAME, disk)
    monkeypatch.setattr(model_metadata, "MODEL_METADATA_SNAPSHOT_PATH", bundled_path)

    selected = model_metadata._load_cache()

    expected_lite = disk if same_litellm_time else bundle
    assert selected["catalogs"]["litellm"] == expected_lite["catalogs"]["litellm"]
    assert selected["catalogs"]["modelsDev"] == disk["catalogs"]["modelsDev"]
    assert (
        model_metadata.resolve_model_metadata("openai", "gpt-test").can_disable_thinking
        is False
    )
    if not same_litellm_time:
        assert model_metadata.resolve_model_metadata("openai", "gpt-disk") is None


@pytest.mark.parametrize("invalid_disk", ["invalid json", '{"version":3}', "[]"])
def test_invalid_disk_cache_does_not_hide_bundled_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid_disk: str,
) -> None:
    bundle = tmp_path / "bundled-models.json"
    _write_json(bundle, _snapshot())
    monkeypatch.setattr(model_metadata, "MODEL_METADATA_SNAPSHOT_PATH", bundle)
    disk = tmp_path / model_metadata.MODEL_METADATA_CACHE_NAME
    disk.parent.mkdir(parents=True)
    disk.write_text(invalid_disk, encoding="utf-8")

    metadata = model_metadata.resolve_model_metadata("openai", "gpt-test")

    assert metadata is not None
    assert metadata.context_window_tokens == 128_000
    assert metadata.can_disable_thinking is True


def test_invalid_source_does_not_discard_other_valid_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot()
    snapshot["catalogs"]["modelsDev"] = {"fetchedAt": "broken", "providers": []}
    bundle = tmp_path / "bundled-models.json"
    _write_json(bundle, snapshot)
    monkeypatch.setattr(model_metadata, "MODEL_METADATA_SNAPSHOT_PATH", bundle)

    metadata = model_metadata.resolve_model_metadata("openai", "gpt-test")

    assert metadata is not None
    assert metadata.context_window_tokens == 128_000
    assert metadata.can_disable_thinking is None


def test_refresh_only_fetches_expired_source(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = _snapshot(age_days=0)
    snapshot["catalogs"]["modelsDev"]["fetchedAt"] = "2020-01-01T00:00:00+00:00"
    model_metadata._set_memory_cache(snapshot)
    lite_data, reasoning_data = _catalog_inputs()
    lite = AsyncMock(return_value=lite_data)
    reasoning = AsyncMock(return_value=reasoning_data)
    monkeypatch.setattr(model_metadata, "_fetch_catalog", lite)
    monkeypatch.setattr(model_metadata, "_fetch_reasoning_catalog", reasoning)

    assert asyncio.run(model_metadata.refresh_model_metadata_cache()) is True
    lite.assert_not_called()
    reasoning.assert_awaited_once()
    assert asyncio.run(model_metadata.refresh_model_metadata_cache()) is False
    lite.assert_not_called()
    reasoning.assert_awaited_once()


@pytest.mark.parametrize("failed_source", ["litellm", "modelsDev"])
def test_invalid_refreshed_source_retains_its_old_facts_and_timestamp(
    monkeypatch: pytest.MonkeyPatch,
    failed_source: str,
) -> None:
    old = _snapshot()
    model_metadata._set_memory_cache(old)
    lite, reasoning = _catalog_inputs()
    monkeypatch.setattr(
        model_metadata,
        "_fetch_catalog",
        AsyncMock(
            return_value={"unexpected": {}} if failed_source == "litellm" else lite
        ),
    )
    monkeypatch.setattr(
        model_metadata,
        "_fetch_reasoning_catalog",
        AsyncMock(
            return_value={"unexpected": {}}
            if failed_source == "modelsDev"
            else reasoning
        ),
    )

    assert asyncio.run(model_metadata.refresh_model_metadata_cache()) is True
    assert (
        model_metadata._load_cache()["catalogs"][failed_source]
        == old["catalogs"][failed_source]
    )
    metadata = model_metadata.resolve_model_metadata("openai", "gpt-test")
    assert metadata is not None and metadata.can_disable_thinking is True


def test_refresh_write_failure_still_publishes_usable_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lite, reasoning = _catalog_inputs()
    monkeypatch.setattr(model_metadata, "_fetch_catalog", AsyncMock(return_value=lite))
    monkeypatch.setattr(
        model_metadata, "_fetch_reasoning_catalog", AsyncMock(return_value=reasoning)
    )

    def fail_write(_snapshot: dict) -> None:
        raise OSError("read-only cache directory")

    monkeypatch.setattr(model_metadata, "_write_cache", fail_write)
    assert asyncio.run(model_metadata.refresh_model_metadata_cache()) is True
    metadata = model_metadata.resolve_model_metadata("openai", "gpt-test")
    assert metadata is not None and metadata.context_window_tokens == 128_000
    assert metadata.can_disable_thinking is True
    assert not (
        get_settings().data_dir / model_metadata.MODEL_METADATA_CACHE_NAME
    ).exists()


def test_lifespan_serves_local_metadata_while_fetching_and_cancels_on_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundled_path = tmp_path / "bundled-models.json"
    _write_json(bundled_path, _snapshot())
    monkeypatch.setattr(model_metadata, "MODEL_METADATA_SNAPSHOT_PATH", bundled_path)

    async def run() -> None:
        started = [asyncio.Event(), asyncio.Event()]
        stopped = [asyncio.Event(), asyncio.Event()]

        async def block_fetch(index: int) -> dict:
            started[index].set()
            try:
                await asyncio.Future()
            finally:
                stopped[index].set()
            return {}

        monkeypatch.setattr(model_metadata, "_fetch_catalog", lambda: block_fetch(0))
        monkeypatch.setattr(
            model_metadata, "_fetch_reasoning_catalog", lambda: block_fetch(1)
        )
        async with model_metadata.model_metadata_lifespan():
            metadata = model_metadata.resolve_model_metadata("openai", "gpt-test")
            assert metadata is not None and metadata.can_disable_thinking is True
            await asyncio.wait_for(
                asyncio.gather(*(event.wait() for event in started)), 3
            )
        assert all(event.is_set() for event in stopped)

    asyncio.run(asyncio.wait_for(run(), 5))


def test_lifespan_retries_failed_refresh_at_background_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        retried = asyncio.Event()
        count = 0

        async def fetch() -> dict:
            nonlocal count
            count += 1
            if count >= 2:
                retried.set()
            return {}

        monkeypatch.setattr(
            model_metadata, "MODEL_METADATA_REFRESH_INTERVAL_SECONDS", 0.01
        )
        monkeypatch.setattr(model_metadata, "_fetch_catalog", fetch)
        async with model_metadata.model_metadata_lifespan():
            await asyncio.wait_for(retried.wait(), 3)
        assert count >= 2

    asyncio.run(run())


def test_snapshot_generation_preserves_explicit_false_and_requires_both_sources() -> (
    None
):
    lite, reasoning = _catalog_inputs()
    lite["openai/gpt-test"]["supports_none_reasoning_effort"] = False
    snapshot = model_metadata.build_model_metadata_snapshot(
        lite, reasoning, fetched_at=datetime.now(UTC).isoformat()
    )
    model_metadata._set_memory_cache(snapshot)
    assert snapshot["version"] == 6
    assert (
        model_metadata.resolve_model_metadata("openai", "gpt-test").can_disable_thinking
        is False
    )
    for first, second in (({}, reasoning), (lite, {})):
        with pytest.raises(ValueError):
            model_metadata.build_model_metadata_snapshot(
                first, second, fetched_at=datetime.now(UTC).isoformat()
            )


def test_snapshot_generation_keeps_slashes_dots_and_dashes_in_model_ids() -> None:
    model_ids = ("gpt/alpha", "gpt.alpha", "gpt-alpha", "gpt_alpha")
    lite = {
        f"openai/{model}": {
            "litellm_provider": "openai",
            "max_input_tokens": 32_000 + index,
            "supports_reasoning": True,
        }
        for index, model in enumerate(model_ids)
    }
    reasoning = {
        "providers": {
            "openai": {
                "models": {
                    model: {"id": model, "reasoning_options": [{"type": "toggle"}]}
                    for model in model_ids
                }
            }
        },
        "models": {
            "openai/base-test": {"id": "openai/base-test", "limit": {"context": 128000}}
        },
    }
    snapshot = model_metadata.build_model_metadata_snapshot(
        lite, reasoning, fetched_at=datetime.now(UTC).isoformat()
    )
    model_metadata._set_memory_cache(snapshot)

    metadata = model_metadata.resolve_models_metadata("openai", list(model_ids))

    assert set(metadata) == set(model_ids)
    for index, model in enumerate(model_ids):
        assert metadata[model].context_window_tokens == 32_000 + index
        assert metadata[model].can_disable_thinking is True
    assert model_metadata.resolve_model_metadata("openai", "alpha") is None
