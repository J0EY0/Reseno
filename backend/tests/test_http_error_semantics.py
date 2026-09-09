from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import MASTER_KEY_ENV_NAME, get_settings
from app.services.agent_runs import AgentRunCapacityError, AgentRunConflictError
from app.services.llm_secrets import decrypt_api_key, encrypt_api_key


@pytest.mark.parametrize(
    ("path", "http_status", "business_code", "message"),
    [
        ("/api/resumes/missing", 404, 40004, "RESUME_NOT_FOUND"),
        ("/api/resumes/invalid-id", 400, 40000, "RESUME_ID_INVALID"),
    ],
)
def test_resume_lookup_retains_error_semantics(
    client: TestClient, path: str, http_status: int, business_code: int, message: str
) -> None:
    response = client.get(path)

    assert response.status_code == http_status
    assert response.json() == {
        "code": business_code,
        "message": message,
        "data": None,
        "requestId": None,
    }


@pytest.mark.parametrize("operation", ["duplicate", "save", "delete-active"])
def test_resume_lifecycle_conflict_retains_reason(
    client: TestClient, operation: str
) -> None:
    created = client.post("/api/resumes", json={"documentLocale": "en"}).json()["data"][
        "resume"
    ]
    route = f"/api/resumes/{created['id']}"
    if operation == "delete-active":
        response = client.delete(route)
        message = "RESUME_NOT_DELETED"
    else:
        assert client.post(f"{route}/trash").status_code == 200
        if operation == "duplicate":
            response = client.post(f"{route}/duplicate")
        else:
            response = client.put(
                route,
                json={
                    key: value
                    for key, value in created.items()
                    if key not in {"id", "updatedAt"}
                },
            )
        message = "RESUME_DELETED"

    assert response.status_code == 409
    assert response.json()["code"] == 40000
    assert response.json()["message"] == message


def test_missing_version_distinguishes_lookup_from_storage_failure(
    client: TestClient,
) -> None:
    created = client.post("/api/resumes", json={"documentLocale": "en"}).json()["data"][
        "resume"
    ]
    route = f"/api/resumes/{created['id']}"
    missing = client.get(f"{route}/versions/99")
    assert missing.status_code == 404
    assert missing.json()["message"] == "RESUME_VERSION_NOT_FOUND"

    version_path = (
        get_settings().storage_dir / "resumes" / created["id"] / "versions" / "1.json"
    )
    assert version_path.is_relative_to(get_settings().data_dir)
    version_path.unlink()
    broken = client.get(route)
    assert broken.status_code == 500
    assert broken.json()["message"] == "RESUME_VERSION_STORAGE_MISSING"
    assert str(version_path) not in broken.text


def test_empty_model_key_retains_required_field_reason() -> None:
    with pytest.raises(HTTPException) as error:
        encrypt_api_key(" ")
    assert error.value.status_code == 400
    assert error.value.detail == "MODEL_CONFIG_API_KEY_REQUIRED"


def test_agent_revision_conflict_uses_envelope_and_preserves_revision(
    client: TestClient,
) -> None:
    resume_id = client.post("/api/resumes", json={"documentLocale": "en"}).json()[
        "data"
    ]["resume"]["id"]
    route = f"/api/agent/resumes/{resume_id}/session"
    revision = client.get(route).json()["data"]["revision"]

    response = client.put(
        route, json={"locale": "en", "messages": [], "revision": "stale"}
    )

    assert response.status_code == 409
    assert response.json() == {
        "code": 40000,
        "message": "AGENT_SESSION_REVISION_CONFLICT",
        "data": {"revision": revision},
        "requestId": None,
    }


@pytest.mark.parametrize(
    ("error", "http_status", "message"),
    [
        (AgentRunConflictError(), 409, "AGENT_RUN_CONFLICT"),
        (AgentRunCapacityError(), 429, "AGENT_RUN_CAPACITY_EXCEEDED"),
    ],
)
def test_agent_pre_stream_failure_uses_http_error_envelope(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    http_status: int,
    message: str,
) -> None:
    monkeypatch.setattr(
        client.app.state.agent_runs, "start", AsyncMock(side_effect=error)
    )

    response = client.post(
        "/api/agent/chat",
        json={"message": {"id": "current", "role": "user", "text": "Hello"}},
    )

    assert response.status_code == http_status
    assert response.json() == {
        "code": 40000,
        "message": message,
        "data": None,
        "requestId": None,
    }


@pytest.mark.parametrize("http_status", [409, 412, 422, 428, 503])
def test_unified_error_handler_preserves_http_status_and_headers(
    client: TestClient,
    http_status: int,
) -> None:
    @client.app.get("/api/test-status")
    def fail() -> None:
        raise HTTPException(
            status_code=http_status,
            detail="STABLE_REASON",
            headers={"Retry-After": "3"},
        )

    response = client.get("/api/test-status")
    assert response.status_code == http_status
    assert response.headers["Retry-After"] == "3"
    assert response.json() == {
        "code": 50000 if http_status >= 500 else 40000,
        "message": "STABLE_REASON",
        "data": None,
        "requestId": None,
    }


def test_model_key_encryption_uses_the_initialized_workspace_settings(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del client
    encrypted = encrypt_api_key("synthetic-model-key")
    monkeypatch.setenv(MASTER_KEY_ENV_NAME, Fernet.generate_key().decode("ascii"))

    assert decrypt_api_key(encrypted) == "synthetic-model-key"
