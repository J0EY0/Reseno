import multiprocessing
import os
from pathlib import Path
from typing import Any

import pytest

from app.config import get_settings
from app.services.model_discovery_cache import (
    read_cached_provider_models,
    write_cached_provider_models,
)
from app.services.model_providers import DiscoveredModel


def _discovered_model(model_id: str) -> DiscoveredModel:
    return DiscoveredModel(
        id=model_id,
        label=model_id,
        context_window_tokens=1_000,
        max_output_tokens=100,
        supports_image=False,
        supports_thinking=False,
        metadata_source="test",
    )


def _write_provider_cache_in_process(
    data_dir: str,
    provider_id: str,
    model_id_prefix: str,
    model_count: int,
    start_barrier: Any,
) -> None:
    root = Path(data_dir)
    os.environ["APP_DATA_DIR"] = str(root)
    os.environ["APP_DB_PATH"] = str(root / "app.db")
    os.environ["APP_STORAGE_DIR"] = str(root / "storage")
    os.environ["APP_ENV_FILE"] = str(root / ".env")
    get_settings.cache_clear()
    models = [
        _discovered_model(f"{model_id_prefix}-{index}") for index in range(model_count)
    ]
    start_barrier.wait(timeout=15)
    write_cached_provider_models(provider_id, models)


def test_different_processes_preserve_each_provider_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("APP_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("APP_ENV_FILE", str(tmp_path / ".env"))
    get_settings.cache_clear()
    get_settings()

    model_count = 2_000
    process_context = multiprocessing.get_context("spawn")
    start_barrier = process_context.Barrier(2)
    processes = [
        process_context.Process(
            target=_write_provider_cache_in_process,
            args=(
                str(tmp_path),
                provider_id,
                model_id_prefix,
                model_count,
                start_barrier,
            ),
        )
        for provider_id, model_id_prefix in (
            ("openai", "gpt-test"),
            ("anthropic", "claude-test"),
        )
    ]

    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=30)
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)

    try:
        assert [process.exitcode for process in processes] == [0, 0]
        assert [model.id for model in read_cached_provider_models("openai") or []] == [
            f"gpt-test-{index}" for index in range(model_count)
        ]
        assert [
            model.id for model in read_cached_provider_models("anthropic") or []
        ] == [f"claude-test-{index}" for index in range(model_count)]
    finally:
        get_settings.cache_clear()


def test_same_provider_processes_leave_one_complete_cache_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("APP_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("APP_ENV_FILE", str(tmp_path / ".env"))
    get_settings.cache_clear()
    get_settings()

    model_count = 2_000
    process_context = multiprocessing.get_context("spawn")
    start_barrier = process_context.Barrier(2)
    processes = [
        process_context.Process(
            target=_write_provider_cache_in_process,
            args=(
                str(tmp_path),
                "openai",
                model_id_prefix,
                model_count,
                start_barrier,
            ),
        )
        for model_id_prefix in ("gpt-first", "gpt-second")
    ]

    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=30)
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)

    try:
        assert [process.exitcode for process in processes] == [0, 0]
        stored_model_ids = [
            model.id for model in read_cached_provider_models("openai") or []
        ]
        assert stored_model_ids in (
            [f"gpt-first-{index}" for index in range(model_count)],
            [f"gpt-second-{index}" for index in range(model_count)],
        )
    finally:
        get_settings.cache_clear()
