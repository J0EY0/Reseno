import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from app.services import model_metadata
from scripts import update_model_metadata

FETCHED_AT = "2026-09-08T00:00:00+00:00"


def _catalogs() -> tuple[dict[str, Any], dict[str, Any]]:
    return (
        {
            "sample_spec": {"description": "Upstream schema documentation"},
            "gpt-test": {
                "litellm_provider": "openai",
                "mode": "chat",
                "max_input_tokens": 128_000,
                "max_output_tokens": 16_384,
                "supports_vision": True,
                "supports_reasoning": True,
                "supports_function_calling": True,
                "supports_native_streaming": True,
                "supports_web_search": True,
                "input_cost_per_token": 0.00001,
                "description": "Discarded upstream documentation. " * 500,
            },
            "other/gpt-test": {
                "litellm_provider": "other",
                "max_input_tokens": 999_999,
            },
        },
        {
            "providers": {
                "openai": {
                    "id": "openai",
                    "models": {
                        "gpt-test": {
                            "id": "gpt-test",
                            "reasoning": True,
                            "reasoning_options": ["none", "low", "high"],
                            "cost": {"input": 1, "output": 2},
                            "description": "Discarded model description. " * 500,
                        },
                    },
                },
                "other": {"id": "other", "models": {}},
            },
            "models": {
                "openai/base-test": {
                    "id": "openai/base-test",
                    "limit": {"context": 128000},
                }
            },
        },
    )


def _source_files(tmp_path: Path) -> tuple[Path, Path]:
    litellm, models_dev = _catalogs()
    litellm_file = tmp_path / "litellm.json"
    models_dev_file = tmp_path / "models-dev.json"
    litellm_file.write_text(json.dumps(litellm), encoding="utf-8")
    models_dev_file.write_text(json.dumps(models_dev), encoding="utf-8")
    return litellm_file, models_dev_file


def test_offline_generation_is_readable_stable_and_independent_of_runtime_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_runtime_access(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Generation must only access its sources and output.")

    monkeypatch.setattr(model_metadata, "get_settings", unexpected_runtime_access)
    monkeypatch.setattr(model_metadata, "_fetch_catalog", unexpected_runtime_access)
    monkeypatch.setattr(
        model_metadata,
        "_fetch_reasoning_catalog",
        unexpected_runtime_access,
    )
    litellm_file, models_dev_file = _source_files(tmp_path)
    output = tmp_path / "bundled" / "model_metadata_snapshot.json"
    asyncio.run(
        update_model_metadata.update_snapshot(
            output,
            litellm_file=litellm_file,
            models_dev_file=models_dev_file,
            fetched_at=FETCHED_AT,
        ),
    )
    first = output.read_bytes()
    snapshot = json.loads(first)
    general = snapshot["catalogs"]["litellm"]["providers"]["openai"]["gpt-test"]
    reasoning = snapshot["catalogs"]["modelsDev"]["providers"]["openai"]["gpt-test"]
    assert general["contextWindowTokens"] == 128_000
    assert general["maxOutputTokens"] == 16_384
    assert general["supportsImage"] is True
    assert general["supportsTools"] is True
    assert general["supportsStreaming"] is True
    assert general["supportsWebSearch"] is True
    assert reasoning["canDisableThinking"] is True
    assert b"description" not in first
    assert b"input_cost_per_token" not in first
    assert "other" not in snapshot["catalogs"]["litellm"]["providers"]
    source_bytes = litellm_file.stat().st_size + models_dev_file.stat().st_size
    assert len(first) < source_bytes / 10
    assert b'\n            "contextWindowTokens": 128000,\n' in first

    for source in (litellm_file, models_dev_file):
        catalog = json.loads(source.read_text(encoding="utf-8"))
        source.write_text(json.dumps(dict(reversed(list(catalog.items())))), "utf-8")
    asyncio.run(
        update_model_metadata.update_snapshot(
            output,
            litellm_file=litellm_file,
            models_dev_file=models_dev_file,
            fetched_at=FETCHED_AT,
        ),
    )
    assert output.read_bytes() == first


def test_remote_generation_fetches_both_sources_concurrently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    litellm, models_dev = _catalogs()

    async def run() -> None:
        litellm_started = asyncio.Event()
        models_dev_started = asyncio.Event()

        async def fetch_litellm() -> dict[str, Any]:
            litellm_started.set()
            await models_dev_started.wait()
            return litellm

        async def fetch_models_dev() -> dict[str, Any]:
            models_dev_started.set()
            await litellm_started.wait()
            return models_dev

        monkeypatch.setattr(model_metadata, "_fetch_catalog", fetch_litellm)
        monkeypatch.setattr(
            model_metadata,
            "_fetch_reasoning_catalog",
            fetch_models_dev,
        )
        await asyncio.wait_for(
            update_model_metadata.update_snapshot(
                tmp_path / "snapshot.json",
                fetched_at=FETCHED_AT,
            ),
            timeout=1,
        )

    asyncio.run(run())
    assert json.loads((tmp_path / "snapshot.json").read_bytes())["version"] == 6


@pytest.mark.parametrize("failed_source", ["litellm", "models_dev"])
@pytest.mark.parametrize("invalid_catalog", [{}, [], {"error": "upstream unavailable"}])
def test_invalid_source_preserves_existing_snapshot(
    tmp_path: Path,
    failed_source: str,
    invalid_catalog: Any,
) -> None:
    litellm_file, models_dev_file = _source_files(tmp_path)
    source = litellm_file if failed_source == "litellm" else models_dev_file
    source.write_text(json.dumps(invalid_catalog), encoding="utf-8")
    output = tmp_path / "snapshot.json"
    output.write_bytes(b"last valid bundled catalog")
    with pytest.raises(ValueError):
        asyncio.run(
            update_model_metadata.update_snapshot(
                output,
                litellm_file=litellm_file,
                models_dev_file=models_dev_file,
            ),
        )
    assert output.read_bytes() == b"last valid bundled catalog"


@pytest.mark.parametrize("failed_source", ["litellm", "models_dev"])
def test_failed_download_preserves_existing_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_source: str,
) -> None:
    litellm, models_dev = _catalogs()

    async def fetch_litellm() -> dict[str, Any]:
        return {} if failed_source == "litellm" else litellm

    async def fetch_models_dev() -> dict[str, Any]:
        return {} if failed_source == "models_dev" else models_dev

    monkeypatch.setattr(model_metadata, "_fetch_catalog", fetch_litellm)
    monkeypatch.setattr(model_metadata, "_fetch_reasoning_catalog", fetch_models_dev)
    output = tmp_path / "snapshot.json"
    output.write_bytes(b"last valid bundled catalog")
    with pytest.raises(ValueError):
        asyncio.run(update_model_metadata.update_snapshot(output))
    assert output.read_bytes() == b"last valid bundled catalog"


def test_failed_atomic_publish_preserves_existing_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    litellm_file, models_dev_file = _source_files(tmp_path)
    output = tmp_path / "snapshot.json"
    output.write_bytes(b"last valid bundled catalog")

    def fail_replace(_source: Path, _target: Path) -> Path:
        raise OSError("Read-only artifact directory")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="Read-only"):
        asyncio.run(
            update_model_metadata.update_snapshot(
                output,
                litellm_file=litellm_file,
                models_dev_file=models_dev_file,
            ),
        )
    assert output.read_bytes() == b"last valid bundled catalog"
    assert set(tmp_path.iterdir()) == {litellm_file, models_dev_file, output}


def test_offline_generation_requires_both_source_files(tmp_path: Path) -> None:
    litellm_file, _ = _source_files(tmp_path)
    with pytest.raises(ValueError, match="Provide both"):
        asyncio.run(
            update_model_metadata.update_snapshot(
                tmp_path / "snapshot.json",
                litellm_file=litellm_file,
            ),
        )
    assert not (tmp_path / "snapshot.json").exists()
