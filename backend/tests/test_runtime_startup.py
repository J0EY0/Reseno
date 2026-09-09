import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.runtime_environment import runtime_environment


@pytest.mark.parametrize("module", ["app.config", "app.main"])
def test_import_and_configuration_reads_have_no_runtime_side_effects(
    tmp_path: Path, module: str
) -> None:
    data_dir = tmp_path / "runtime"
    configuration = tmp_path / "configuration.env"
    configuration.write_text(f"APP_DATA_DIR={data_dir}\nCUSTOM_TEST_VALUE=from-file\n")
    original = configuration.read_bytes()
    environment = {**os.environ, **runtime_environment(data_dir)}
    environment["APP_ENV_FILE"] = str(configuration)
    environment.pop("APP_DATA_DIR")
    environment.pop("CUSTOM_TEST_VALUE", None)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import importlib, os; before = dict(os.environ); "
            f"importlib.import_module({module!r}); "
            "from app.config import get_settings; settings = get_settings(); "
            "assert dict(os.environ) == before; "
            "assert settings.data_dir == __import__('pathlib').Path("
            f"{str(data_dir)!r})",
        ],
        env=environment,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert configuration.read_bytes() == original
    assert not data_dir.exists()


def test_lifespan_rejects_a_second_backend_before_touching_active_runs(monkeypatch):
    from fastapi.testclient import TestClient

    from app import main

    startup_calls = []
    monkeypatch.setattr(
        main,
        "fail_interrupted_agent_turn_executions",
        lambda _: startup_calls.append(1),
    )
    with TestClient(main.create_app()) as first:
        with pytest.raises(RuntimeError, match="already running"):
            with TestClient(main.create_app()):
                pass
        assert first.get("/health").status_code == 200
        assert startup_calls == [1]
    with TestClient(main.create_app()) as restarted:
        assert restarted.get("/health").status_code == 200


@pytest.mark.parametrize("shared", ["db_path", "data_dir", "storage_dir"])
def test_workspace_ownership_covers_each_configurable_storage_location(
    tmp_path: Path, shared: str
) -> None:
    from dataclasses import replace

    from app.config import get_settings
    from app.runtime import backend_instance

    first = get_settings()
    second = replace(
        first,
        data_dir=tmp_path / "second",
        db_path=tmp_path / "second" / "app.db",
        storage_dir=tmp_path / "second" / "storage",
    )
    second = replace(second, **{shared: getattr(first, shared)})
    with backend_instance(first):
        with pytest.raises(RuntimeError, match="already running"):
            with backend_instance(second):
                pass
    with backend_instance(second):
        pass


def test_process_exit_releases_workspace_ownership(tmp_path: Path) -> None:
    from app.config import get_settings
    from app.runtime import backend_instance

    ready = tmp_path / "ready"
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import pathlib, sys; from app.config import get_settings; "
            "from app.runtime import backend_instance; "
            "guard = backend_instance(get_settings()); guard.__enter__(); "
            f"pathlib.Path({str(ready)!r}).touch(); "
            "print('ready', flush=True); sys.stdin.read()",
        ],
        cwd=Path(__file__).resolve().parents[1],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        import time

        deadline = time.monotonic() + 10
        while not ready.exists() and process.poll() is None:
            assert time.monotonic() < deadline, "Child did not acquire ownership."
            time.sleep(0.02)
        assert ready.exists(), process.communicate(timeout=5)
        with pytest.raises(RuntimeError, match="already running"):
            with backend_instance(get_settings()):
                pass
    finally:
        process.terminate()
        process.communicate(timeout=5)
    with backend_instance(get_settings()):
        pass
