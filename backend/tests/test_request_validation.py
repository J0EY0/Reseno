import pytest
from fastapi.testclient import TestClient


def test_invalid_template_override_returns_serializable_validation_error(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/resumes",
        json={"documentLocale": "en", "templateSettings": {"pagePaddingX": None}},
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["message"] == "VALIDATION_ERROR"
    error = payload["data"]["errors"][0]
    assert error["loc"] == ["body", "templateSettings"]
    assert "cannot be null" in error["msg"]


@pytest.mark.parametrize("username", ["测试用户", "café", "admin🙂"])
def test_non_ascii_login_username_returns_invalid_credentials(
    unauthenticated_client: TestClient,
    username: str,
) -> None:
    response = unauthenticated_client.post(
        "/api/auth/login",
        json={"username": username, "password": "TestPassword2026"},
    )

    assert response.status_code == 401
    assert response.json()["message"] == "INVALID_CREDENTIALS"
