import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_BOOTSTRAP_DATA_DIR = Path(tempfile.mkdtemp(prefix="resumate-pytest-bootstrap-"))
os.environ.setdefault("APP_DATA_DIR", str(_BOOTSTRAP_DATA_DIR))
os.environ.setdefault("APP_DB_PATH", str(_BOOTSTRAP_DATA_DIR / "app.db"))
os.environ.setdefault("APP_STORAGE_DIR", str(_BOOTSTRAP_DATA_DIR / "storage"))
os.environ.setdefault("APP_ENV_FILE", str(_BOOTSTRAP_DATA_DIR / ".env"))


@pytest.fixture(autouse=True)
def stub_model_metadata_fetch(monkeypatch) -> Iterator[None]:
    from app.services import model_metadata

    model_metadata._CATALOG_CACHE = None
    monkeypatch.setattr(model_metadata, "_fetch_catalog", lambda: {})

    yield

    model_metadata._CATALOG_CACHE = None


@pytest.fixture
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    from app.config import get_settings
    from app.main import create_app

    monkeypatch.delenv("RESUMATE_MASTER_KEY", raising=False)
    monkeypatch.delenv("RESUMATE_JWT_SECRET", raising=False)
    monkeypatch.delenv("APP_USER_SETTINGS_PATH", raising=False)
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("APP_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("APP_ENV_FILE", str(tmp_path / ".env"))
    get_settings.cache_clear()

    with TestClient(
        create_app(),
        client=("127.0.0.1", 50000),
    ) as test_client:
        setup_response = test_client.post(
            "/api/auth/setup",
            json={
                "username": "admin",
                "password": "TestPassword2026",
                "confirmPassword": "TestPassword2026",
            },
        )
        access_token = setup_response.json()["data"]["accessToken"]
        test_client.headers.update({"Authorization": f"Bearer {access_token}"})
        yield test_client

    get_settings.cache_clear()


@pytest.fixture
def unauthenticated_client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    from app.config import get_settings
    from app.main import create_app

    monkeypatch.delenv("RESUMATE_MASTER_KEY", raising=False)
    monkeypatch.delenv("RESUMATE_JWT_SECRET", raising=False)
    monkeypatch.delenv("APP_USER_SETTINGS_PATH", raising=False)
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("APP_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("APP_ENV_FILE", str(tmp_path / ".env"))
    get_settings.cache_clear()

    with TestClient(
        create_app(),
        client=("127.0.0.1", 50000),
    ) as test_client:
        test_client.post(
            "/api/auth/setup",
            json={
                "username": "admin",
                "password": "TestPassword2026",
                "confirmPassword": "TestPassword2026",
            },
        )
        yield test_client

    get_settings.cache_clear()


@pytest.fixture
def uninitialized_client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    from app.config import get_settings
    from app.main import create_app

    monkeypatch.delenv("RESUMATE_MASTER_KEY", raising=False)
    monkeypatch.delenv("RESUMATE_JWT_SECRET", raising=False)
    monkeypatch.delenv("APP_USER_SETTINGS_PATH", raising=False)
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("APP_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("APP_ENV_FILE", str(tmp_path / ".env"))
    get_settings.cache_clear()

    with TestClient(
        create_app(),
        client=("127.0.0.1", 50000),
    ) as test_client:
        yield test_client

    get_settings.cache_clear()
