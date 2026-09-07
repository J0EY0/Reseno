import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from cryptography.fernet import Fernet


@pytest.mark.parametrize("runner", ["pytest", "data-flow"])
def test_verification_preserves_inherited_runtime_files(
    tmp_path: Path,
    runner: str,
) -> None:
    external_dir = tmp_path / "existing-runtime"
    external_dir.mkdir()
    export_dir = external_dir / "exports"
    export_dir.mkdir()
    old_export = export_dir / "export-existing.pdf"
    old_export.write_bytes(b"existing synthetic export")
    expired_at = time.time() - 7200
    os.utime(old_export, (expired_at, expired_at))
    settings_path = external_dir / "user_settings.json"
    settings_path.write_text('{"locale":"zh","theme":"dark"}', encoding="utf-8")
    env_path = external_dir / ".env"
    master_key = Fernet.generate_key().decode()
    jwt_secret = "synthetic-existing-jwt-secret-123456789"
    env_path.write_text(
        f"RESUMATE_MASTER_KEY={master_key}\nRESUMATE_JWT_SECRET={jwt_secret}\n",
        encoding="utf-8",
    )
    existing_files = {
        path: path.read_bytes() for path in (old_export, settings_path, env_path)
    }
    probe = tmp_path / "test_probe.py"
    probe.write_text(
        """import os

import pytest

from app.config import get_settings

settings = get_settings()
assert str(settings.env_file_path) != os.environ["PROBE_ENV_FILE"]
assert os.environ["RESUMATE_MASTER_KEY"] != os.environ["PROBE_MASTER_KEY"]
assert os.environ["RESUMATE_JWT_SECRET"] != os.environ["PROBE_JWT_SECRET"]


@pytest.mark.parametrize(
    "fixture_name", ["client", "unauthenticated_client", "uninitialized_client"]
)
def test_isolated_client(request, fixture_name, tmp_path):
    request.getfixturevalue(fixture_name)
    from app.config import get_settings

    settings = get_settings()
    for path in (
        settings.data_dir, settings.db_path, settings.storage_dir,
        settings.export_dir, settings.user_settings_path, settings.env_file_path,
    ):
        assert path.is_relative_to(tmp_path)
    assert os.environ["RESUMATE_MASTER_KEY"] != os.environ["PROBE_MASTER_KEY"]
    assert os.environ["RESUMATE_JWT_SECRET"] != os.environ["PROBE_JWT_SECRET"]
""",
        encoding="utf-8",
    )
    command = (
        [sys.executable, "-m", "pytest", "-p", "tests.conftest", str(probe), "-q"]
        if runner == "pytest"
        else [
            sys.executable,
            "-c",
            "import os, runpy; from app.services import model_metadata; "
            "model_metadata._fetch_catalog = lambda: {}; "
            "model_metadata._fetch_reasoning_catalog = lambda: {}; "
            "runpy.run_path('scripts/verify_data_flow.py', run_name='__main__'); "
            "assert os.environ['RESUMATE_MASTER_KEY'] != "
            "os.environ['PROBE_MASTER_KEY']; "
            "assert os.environ['RESUMATE_JWT_SECRET'] != "
            "os.environ['PROBE_JWT_SECRET']",
        ]
    )
    result = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        env={
            **os.environ,
            "APP_DATA_DIR": str(external_dir),
            "APP_DB_PATH": str(external_dir / "app.db"),
            "APP_STORAGE_DIR": str(external_dir / "storage"),
            "APP_ENV_FILE": str(env_path),
            "APP_USER_SETTINGS_PATH": str(settings_path),
            "EXPORT_DIR": str(export_dir),
            "RESUMATE_MASTER_KEY": master_key,
            "RESUMATE_JWT_SECRET": jwt_secret,
            "PROBE_MASTER_KEY": master_key,
            "PROBE_JWT_SECRET": jwt_secret,
            "PROBE_ENV_FILE": str(env_path),
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert {path: path.read_bytes() for path in existing_files if path.exists()} == (
        existing_files
    )
    assert result.returncode == 0, result.stdout + result.stderr
