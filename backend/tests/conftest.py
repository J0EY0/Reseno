import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from tests.runtime_environment import runtime_environment

_BOOTSTRAP_DATA_DIR = tempfile.TemporaryDirectory(prefix="reseno-pytest-bootstrap-")
os.environ.update(runtime_environment(Path(_BOOTSTRAP_DATA_DIR.name)))


@pytest.fixture(autouse=True)
def isolated_runtime_environment(tmp_path, monkeypatch) -> Iterator[None]:
    from app.config import get_settings

    for key, value in runtime_environment(tmp_path).items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


@pytest.fixture(autouse=True)
def stub_model_metadata_fetch(tmp_path, monkeypatch) -> Iterator[None]:
    from app.services import model_metadata

    model_metadata._CATALOG_CACHE = None
    monkeypatch.setattr(
        model_metadata,
        "MODEL_METADATA_SNAPSHOT_PATH",
        tmp_path / "no-bundled-models.json",
    )
    monkeypatch.setattr(model_metadata, "_fetch_catalog", AsyncMock(return_value={}))
    monkeypatch.setattr(
        model_metadata, "_fetch_reasoning_catalog", AsyncMock(return_value={})
    )

    yield

    model_metadata._CATALOG_CACHE = None


@pytest.fixture
def client(uninitialized_client) -> TestClient:
    response = uninitialized_client.post(
        "/api/auth/setup",
        json={
            "username": "admin",
            "password": "TestPassword2026",
            "confirmPassword": "TestPassword2026",
        },
    )
    access_token = response.json()["data"]["accessToken"]
    uninitialized_client.headers.update({"Authorization": f"Bearer {access_token}"})
    return uninitialized_client


@pytest.fixture
def unauthenticated_client(uninitialized_client) -> TestClient:
    response = uninitialized_client.post(
        "/api/auth/setup",
        json={
            "username": "admin",
            "password": "TestPassword2026",
            "confirmPassword": "TestPassword2026",
        },
    )
    assert response.status_code == 200
    return uninitialized_client


@pytest.fixture
def uninitialized_client() -> Iterator[TestClient]:
    from app.main import create_app

    with TestClient(
        create_app(),
        client=("127.0.0.1", 50000),
    ) as test_client:
        yield test_client
