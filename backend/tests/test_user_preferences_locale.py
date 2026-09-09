import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.services.user_preferences import load_user_settings, save_user_settings


@pytest.mark.parametrize("locale", ["en", "zh"])
@pytest.mark.parametrize(
    "update",
    [{"theme": "dark"}, {"agentSettings": {"behaviorMode": "strict"}}],
)
def test_partial_preferences_update_preserves_saved_locale(
    client: TestClient, locale: str, update: dict[str, object]
) -> None:
    initial = client.put(
        f"/api/workspace/user-settings?locale={locale}",
        json={"settings": {"theme": "light"}},
    )
    assert initial.status_code == 200

    response = client.put("/api/workspace/user-settings", json={"settings": update})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["locale"] == locale
    assert load_user_settings()["locale"] == locale
    if "theme" in update:
        assert data["theme"] == "dark"
    else:
        assert data["theme"] == "light"
        assert data["agentSettings"]["behaviorMode"] == "strict"


def test_first_preferences_update_uses_default_locale(client: TestClient) -> None:
    assert not get_settings().user_settings_path.exists()

    response = client.put(
        "/api/workspace/user-settings", json={"settings": {"theme": "dark"}}
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"locale": "en", "theme": "dark"}
    assert load_user_settings() == {"locale": "en", "theme": "dark"}


@pytest.mark.parametrize("locale", ["en", "zh"])
def test_explicit_locale_replaces_saved_locale(client: TestClient, locale: str) -> None:
    previous = "zh" if locale == "en" else "en"
    save_user_settings(previous, {"theme": "dark"})

    response = client.put(
        f"/api/workspace/user-settings?locale={locale}", json={"settings": {}}
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"locale": locale, "theme": "dark"}
    assert load_user_settings() == {"locale": locale, "theme": "dark"}


@pytest.mark.parametrize("locale", ["fr", ""])
def test_invalid_explicit_http_locale_keeps_validation_behavior(
    client: TestClient, locale: str
) -> None:
    save_user_settings("zh", {"theme": "light"})
    path = get_settings().user_settings_path
    before = path.read_bytes()

    response = client.put(
        "/api/workspace/user-settings",
        params={"locale": locale},
        json={"settings": {"theme": "dark"}},
    )

    assert response.status_code == 422
    assert path.read_bytes() == before


@pytest.mark.parametrize("locale", ["fr", ""])
def test_invalid_service_locale_keeps_existing_normalization(locale: str) -> None:
    save_user_settings("zh", {"theme": "light"})

    result = save_user_settings(locale, {"theme": "dark"})

    assert result == {"locale": "en", "theme": "dark"}
    assert load_user_settings() == result
