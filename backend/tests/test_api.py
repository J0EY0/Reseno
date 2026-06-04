import json
from pathlib import Path

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app import config as app_config
from app.config import get_settings
from app.db.connection import connect
from app.schemas.exports import ExportResumePdfRequest
from app.services.agent import WebReference, WebSearchResult
from app.services.auth_tokens import create_access_token
from app.services.llm_client import (
    LlmRequestError,
    LlmStreamDelta,
    LlmToolCall,
    LlmToolCallResponse,
)


def minimal_resume_item(
    resume_id: str = "resume-test",
    title: str = "Test Resume",
) -> dict:
    return {
        "id": resume_id,
        "title": title,
        "updatedAt": "2026-05-16T01:00:00.000Z",
        "jobBrief": "",
        "typography": {"fontFamily": "inter", "fontSize": 16},
        "template": "minimal",
        "resume": {
            "basic": {
                "name": title,
                "headline": "",
                "phone": "",
                "email": "",
                "location": "",
                "avatar": "",
                "summary": "",
                "customFields": [],
            },
            "sections": [],
        },
    }


def create_agent_model_config(client: TestClient) -> dict:
    response = client.post(
        "/api/model-configs",
        json={
            "id": "llm-agent",
            "provider": "openai",
            "nickname": "Agent Model",
            "apiKey": "sk-agent-secret",
            "model": "gpt-5.1",
            "apiUrl": "https://api.openai.com/v1",
            "temperature": 0.4,
            "topP": 0.9,
            "maxTokens": 1200,
            "systemPrompt": "",
        },
    )
    assert response.status_code == 200
    return response.json()["data"]


def stub_jd_search(query: str) -> tuple[WebSearchResult, int, None]:
    return (
        WebSearchResult(
            title="AI Application Developer JD",
            url="https://example.test/jobs/ai-application-developer",
            excerpt="AI application development responsibilities and requirements.",
        ),
        1,
        None,
    )


def tool_call(
    call_id: str,
    name: str,
    arguments: dict | None = None,
) -> LlmToolCall:
    raw_arguments = "{}" if arguments is None else "{}"
    return LlmToolCall(
        id=call_id,
        name=name,
        arguments=arguments or {},
        raw_arguments=raw_arguments,
    )


def stub_tool_call_batches(
    *batches: list[LlmToolCall],
):
    pending = list(batches)

    def call_tools(*_: object) -> LlmToolCallResponse:
        if pending:
            return LlmToolCallResponse(content="", tool_calls=pending.pop(0))

        return LlmToolCallResponse(content="", tool_calls=[])

    return call_tools


def stub_tool_call_responses(
    *responses: LlmToolCallResponse,
):
    pending = list(responses)

    def call_tools(*_: object) -> LlmToolCallResponse:
        if pending:
            return pending.pop(0)

        return LlmToolCallResponse(content="", tool_calls=[])

    return call_tools


def test_workspace_bootstrap_returns_empty_backend_workspace(
    client: TestClient,
) -> None:
    response = client.get("/api/workspace/bootstrap?locale=zh")

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    assert payload["data"]["resumes"] == []
    assert payload["data"]["deletedResumes"] == []


def test_auth_login_does_not_return_credentials(
    unauthenticated_client: TestClient,
) -> None:
    login_response = unauthenticated_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "ResuMate@2026"},
    )
    invalid_response = unauthenticated_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "wrong-password"},
    )

    assert login_response.status_code == 200
    assert "ResuMate@2026" not in login_response.text
    login_data = login_response.json()["data"]
    assert login_data["username"] == "admin"
    assert login_data["tokenType"] == "bearer"
    assert login_data["accessToken"]
    assert login_data["expiresAt"]
    assert invalid_response.status_code == 200
    assert invalid_response.json()["code"] == 40001
    assert invalid_response.json()["message"] == "INVALID_CREDENTIALS"


def test_protected_api_requires_jwt(unauthenticated_client: TestClient) -> None:
    response = unauthenticated_client.get("/api/workspace/bootstrap?locale=en")

    assert response.status_code == 200
    assert response.json()["code"] == 40001
    assert response.json()["message"] == "UNAUTHORIZED_REQUEST"
    assert response.json()["data"]["loginUrl"] == "/login"


def test_public_api_paths_only_include_login() -> None:
    from app.middleware.auth import PUBLIC_API_PATHS

    assert PUBLIC_API_PATHS == {"/api/auth/login"}


def test_protected_api_requires_jwt_with_default_initialized_password(
    tmp_path,
    monkeypatch,
) -> None:
    from app.config import get_settings
    from app.main import create_app

    monkeypatch.delenv("RESUMATE_MASTER_KEY", raising=False)
    monkeypatch.delenv("RESUMATE_JWT_SECRET", raising=False)
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("APP_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("APP_ENV_FILE", str(tmp_path / ".env"))
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_USERNAME", "admin")
    monkeypatch.delenv("AUTH_PASSWORD", raising=False)
    get_settings.cache_clear()

    with TestClient(create_app()) as test_client:
        response = test_client.get("/api/workspace/bootstrap?locale=en")

    env_content = (tmp_path / ".env").read_text(encoding="utf-8")
    get_settings.cache_clear()

    assert "AUTH_PASSWORD=ResuMate@2026" in env_content
    assert response.status_code == 200
    assert response.json()["code"] == 40001
    assert response.json()["message"] == "UNAUTHORIZED_REQUEST"


def test_development_app_env_skips_jwt_middleware(tmp_path, monkeypatch) -> None:
    from app.config import get_settings
    from app.main import create_app

    monkeypatch.delenv("RESUMATE_MASTER_KEY", raising=False)
    monkeypatch.delenv("RESUMATE_JWT_SECRET", raising=False)
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("APP_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("APP_ENV_FILE", str(tmp_path / ".env"))
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_USERNAME", "admin")
    monkeypatch.setenv("AUTH_PASSWORD", "ResuMate@2026")
    get_settings.cache_clear()

    with TestClient(create_app()) as test_client:
        response = test_client.get("/api/workspace/bootstrap?locale=en")
        password_response = test_client.post(
            "/api/auth/password",
            json={
                "currentPassword": "ResuMate@2026",
                "newPassword": "Changed@2026",
                "confirmPassword": "Changed@2026",
            },
        )

    get_settings.cache_clear()

    assert response.status_code == 200
    assert response.json()["code"] == 0
    assert password_response.status_code == 200
    assert password_response.json()["code"] == 0


def test_auth_refresh_revokes_previous_jwt(
    unauthenticated_client: TestClient,
) -> None:
    login_response = unauthenticated_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "ResuMate@2026"},
    )
    old_token = login_response.json()["data"]["accessToken"]
    refresh_response = unauthenticated_client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {old_token}"},
        json={},
    )
    new_token = refresh_response.json()["data"]["accessToken"]
    old_token_response = unauthenticated_client.get(
        "/api/workspace/bootstrap?locale=en",
        headers={"Authorization": f"Bearer {old_token}"},
    )
    new_token_response = unauthenticated_client.get(
        "/api/workspace/bootstrap?locale=en",
        headers={"Authorization": f"Bearer {new_token}"},
    )

    assert refresh_response.status_code == 200
    assert new_token != old_token
    assert old_token_response.status_code == 200
    assert old_token_response.json()["code"] == 40001
    assert old_token_response.json()["message"] == "UNAUTHORIZED_REQUEST"
    assert new_token_response.status_code == 200
    assert new_token_response.json()["code"] == 0


def test_auth_password_update_writes_env_and_requires_new_login(
    unauthenticated_client: TestClient,
) -> None:
    settings = get_settings()
    login_response = unauthenticated_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "ResuMate@2026"},
    )
    token = login_response.json()["data"]["accessToken"]
    update_response = unauthenticated_client.post(
        "/api/auth/password",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "currentPassword": "ResuMate@2026",
            "newPassword": "Changed@2026",
            "confirmPassword": "Changed@2026",
        },
    )
    old_login_response = unauthenticated_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "ResuMate@2026"},
    )
    new_login_response = unauthenticated_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "Changed@2026"},
    )
    revoked_token_response = unauthenticated_client.get(
        "/api/workspace/bootstrap?locale=en",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert update_response.status_code == 200
    assert update_response.json()["code"] == 0
    assert update_response.json()["data"] == {"username": "admin", "updated": True}
    assert "AUTH_PASSWORD=Changed@2026" in settings.env_file_path.read_text(
        encoding="utf-8"
    )
    assert old_login_response.json()["code"] == 40001
    assert old_login_response.json()["message"] == "INVALID_CREDENTIALS"
    assert new_login_response.json()["code"] == 0
    assert revoked_token_response.json()["code"] == 40001


def test_auth_password_update_validates_confirmation(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/auth/password",
        json={
            "currentPassword": "ResuMate@2026",
            "newPassword": "Changed@2026",
            "confirmPassword": "Mismatch@2026",
        },
    )

    assert response.status_code == 200
    assert response.json()["code"] == 40000
    assert response.json()["message"] == "PASSWORD_CONFIRMATION_MISMATCH"


def test_auth_password_update_wrong_current_password_keeps_session(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/auth/password",
        json={
            "currentPassword": "wrong-password",
            "newPassword": "Changed@2026",
            "confirmPassword": "Changed@2026",
        },
    )
    session_response = client.get("/api/workspace/bootstrap?locale=en")

    assert response.status_code == 200
    assert response.json()["code"] == 40000
    assert response.json()["message"] == "INVALID_CREDENTIALS"
    assert session_response.json()["code"] == 0


def test_expired_jwt_is_rejected(client: TestClient) -> None:
    expired_token, _ = create_access_token("admin", ttl_seconds=-1)
    response = client.get(
        "/api/workspace/bootstrap?locale=en",
        headers={"Authorization": f"Bearer {expired_token}"},
    )

    assert response.status_code == 200
    assert response.json()["code"] == 40001
    assert response.json()["message"] == "UNAUTHORIZED_REQUEST"


def test_workspace_snapshot_persists(client: TestClient) -> None:
    snapshot = {
        "resumes": [minimal_resume_item()],
        "modelConfigs": [],
        "savedAt": "2026-05-16T00:00:00.000Z",
    }

    save_response = client.put(
        "/api/workspace/snapshot?locale=en",
        json={"snapshot": snapshot},
    )
    bootstrap_response = client.get("/api/workspace/bootstrap?locale=en")

    assert save_response.status_code == 200
    assert save_response.json()["data"]["savedAt"] == snapshot["savedAt"]
    assert bootstrap_response.status_code == 200
    assert bootstrap_response.json()["data"]["savedAt"] == snapshot["savedAt"]
    assert bootstrap_response.json()["data"]["resumes"][0]["id"] == "resume-test"


def test_workspace_snapshot_roundtrip_preserves_full_frontend_state(
    client: TestClient,
) -> None:
    snapshot = {
        "resumes": [
            {
                "id": "resume-roundtrip",
                "title": "Roundtrip Resume",
                "updatedAt": "2026-05-16T02:00:00.000Z",
                "jobBrief": "Backend data flow",
                "typography": {"fontFamily": "inter", "fontSize": 18},
                "template": "template-custom",
                "resume": {
                    "basic": {
                        "name": "Round Trip",
                        "headline": "Engineer",
                        "phone": "",
                        "email": "",
                        "location": "",
                        "avatar": "",
                        "summary": "",
                        "customFields": [],
                    },
                    "sections": [],
                },
            }
        ],
        "defaultTemplateId": "template-custom",
        "customTemplates": [
            {
                "id": "template-custom",
                "preset": "minimal",
                "name": "Custom",
                "description": "Custom template",
                "layout": {
                    "basicInfo": "centered",
                    "section": "plain",
                    "avatarPosition": "right",
                    "avatarShape": "rounded",
                    "avatarWidth": 96,
                    "avatarHeight": 96,
                    "avatarOffsetX": 0,
                    "avatarOffsetY": 0,
                    "avatarBorderWidth": 0,
                    "avatarBorderColor": "#ffffff",
                    "images": [],
                },
                "typography": {"fontFamily": "inter", "fontSize": 16},
                "settings": {
                    "pagePaddingTop": 48,
                    "pagePaddingX": 48,
                    "pagePaddingBottom": 48,
                    "sectionGap": 18,
                    "itemGap": 12,
                    "bodyLineHeight": 1.5,
                    "nameScale": 1.8,
                    "sectionTitleScale": 1,
                    "itemTitleScale": 1,
                    "metaScale": 0.9,
                    "bodyScale": 1,
                    "pageBackground": "#ffffff",
                    "surfaceColor": "#ffffff",
                    "headingColor": "#111111",
                    "bodyColor": "#222222",
                    "mutedColor": "#666666",
                    "dividerColor": "#dddddd",
                    "dividerThickness": 1,
                },
                "updatedAt": "2026-05-16T02:00:00.000Z",
                "isBuiltIn": False,
            }
        ],
        "deletedResumes": [],
        "deletedTemplates": [],
        "modelConfigs": [
            {
                "id": "llm-roundtrip",
                "provider": "openai",
                "nickname": "Roundtrip GPT",
                "apiKey": "sk-roundtrip-secret",
                "model": "gpt-5.1",
                "apiUrl": "https://api.openai.com/v1",
                "temperature": 0.4,
                "topP": 0.9,
                "maxTokens": 1200,
                "systemPrompt": "Roundtrip",
            }
        ],
        "agentSettings": {
            "defaultModelId": "llm-roundtrip",
            "responseLanguage": "follow",
            "behaviorMode": "balanced",
            "autoRunMatch": True,
        },
        "savedAt": "2026-05-16T02:00:00.000Z",
    }

    save_response = client.put(
        "/api/workspace/snapshot?locale=en",
        json={"snapshot": snapshot},
    )
    bootstrap_response = client.get("/api/workspace/bootstrap?locale=en")

    assert save_response.status_code == 200
    assert bootstrap_response.status_code == 200
    data = bootstrap_response.json()["data"]
    assert data["resumes"][0]["id"] == "resume-roundtrip"
    assert data["customTemplates"][0]["id"] == "template-custom"
    assert data["modelConfigs"][0]["apiKeyPreview"] == "sk-rou****"
    assert data["agentSettings"]["defaultModelId"] == "llm-roundtrip"

    with connect() as conn:
        resume_row = conn.execute(
            """
            SELECT id, current_version_id, title
            FROM resumes
            WHERE id = ?
            """,
            ("resume-roundtrip",),
        ).fetchone()
        template_row = conn.execute(
            """
            SELECT id, name, deleted, purged
            FROM templates
            WHERE id = ?
            """,
            ("template-custom",),
        ).fetchone()
        state_row = conn.execute(
            """
            SELECT state_json
            FROM workspace_state
            WHERE locale = ?
            """,
            ("en",),
        ).fetchone()

    assert resume_row is not None
    assert resume_row["current_version_id"] == 1
    assert resume_row["title"] == "Roundtrip Resume"
    assert template_row is not None
    assert template_row["name"] == "Custom"
    assert template_row["deleted"] == 0
    assert template_row["purged"] == 0
    assert state_row is not None
    assert "customTemplates" not in state_row["state_json"]
    assert "deletedTemplates" not in state_row["state_json"]
    resume_json_path = (
        get_settings().storage_dir
        / "resumes"
        / "resume-roundtrip"
        / "versions"
        / "1.json"
    )
    template_json_path = (
        get_settings().storage_dir / "templates" / "template-custom" / "current.json"
    )
    assert resume_json_path.exists()
    assert template_json_path.exists()


def test_workspace_snapshot_does_not_persist_api_key(client: TestClient) -> None:
    snapshot = {
        "resumes": [],
        "modelConfigs": [
            {
                "id": "llm-test",
                "provider": "openai",
                "nickname": "Test",
                "apiKey": "sk-workspace-secret",
                "model": "gpt-5.1",
                "apiUrl": "https://api.openai.com/v1",
                "temperature": 0.4,
                "topP": 0.9,
                "maxTokens": None,
                "systemPrompt": "test",
            },
        ],
        "savedAt": "2026-05-16T00:00:00.000Z",
    }

    save_response = client.put(
        "/api/workspace/snapshot?locale=en",
        json={"snapshot": snapshot},
    )
    bootstrap_response = client.get("/api/workspace/bootstrap?locale=en")

    assert save_response.status_code == 200
    assert bootstrap_response.status_code == 200
    model_config = bootstrap_response.json()["data"]["modelConfigs"][0]
    assert "apiKey" not in model_config
    assert "apiKeyEnvName" not in model_config
    assert model_config["apiKeyPreview"] == "sk-wor****"

    with connect() as conn:
        row = conn.execute(
            """
            SELECT state_json
            FROM workspace_state
            WHERE locale = ?
            """,
            ("en",),
        ).fetchone()
        llm_row = conn.execute(
            """
            SELECT encrypted_api_key, api_key_preview
            FROM llm_configs
            WHERE provider = ?
            """,
            ("openai",),
        ).fetchone()

    assert row is not None
    assert llm_row is not None
    assert llm_row["encrypted_api_key"] != "sk-workspace-secret"
    assert llm_row["api_key_preview"] == model_config["apiKeyPreview"]
    state_json = row["state_json"]
    assert "sk-workspace-secret" not in state_json
    assert "modelConfigs" not in state_json


def test_workspace_versions_can_be_listed_and_loaded(client: TestClient) -> None:
    snapshot = {
        "resumes": [minimal_resume_item("resume-versioned", "Versioned")],
        "modelConfigs": [],
        "savedAt": "2026-05-16T01:00:00.000Z",
    }

    save_response = client.put(
        "/api/workspace/snapshot?locale=zh",
        json={"snapshot": snapshot},
    )
    version_id = save_response.json()["data"]["versionId"]

    versions_response = client.get("/api/workspace/versions?locale=zh")
    version_response = client.get(f"/api/workspace/versions/{version_id}?locale=zh")

    assert versions_response.status_code == 200
    versions = versions_response.json()["data"]["versions"]
    assert versions[0]["versionId"] == version_id
    assert version_response.status_code == 200
    assert version_response.json()["data"]["snapshot"]["savedAt"] == snapshot["savedAt"]
    assert (
        version_response.json()["data"]["snapshot"]["resumes"][0]["id"]
        == "resume-versioned"
    )


def test_identical_resume_hash_does_not_create_new_version(
    client: TestClient,
) -> None:
    first_snapshot = {
        "resumes": [minimal_resume_item("resume-hash", "Hash Stable")],
        "modelConfigs": [],
        "savedAt": "2026-05-16T01:00:00.000Z",
    }
    second_snapshot = {
        "resumes": [
            {
                **minimal_resume_item("resume-hash", "Hash Stable"),
                "updatedAt": "2026-05-17T01:00:00.000Z",
            }
        ],
        "modelConfigs": [],
        "savedAt": "2026-05-17T01:00:00.000Z",
    }

    first_response = client.put(
        "/api/workspace/snapshot?locale=en",
        json={"snapshot": first_snapshot},
    )
    second_response = client.put(
        "/api/workspace/snapshot?locale=en",
        json={"snapshot": second_snapshot},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.json()["data"]["versionId"] == "1"
    assert second_response.json()["data"]["versionId"] == "1"

    with connect() as conn:
        version_count = conn.execute(
            """
            SELECT COUNT(*) AS version_count
            FROM resume_versions
            WHERE resume_id = ?
            """,
            ("resume-hash",),
        ).fetchone()["version_count"]

    assert version_count == 1


def test_master_key_generated_once(client: TestClient) -> None:
    settings = get_settings()
    env_file = settings.env_file_path
    first_content = env_file.read_text(encoding="utf-8")

    get_settings.cache_clear()
    second_settings = get_settings()
    second_content = env_file.read_text(encoding="utf-8")

    assert second_settings.env_file_path == env_file
    assert "APP_DATA_DIR=~/.resumate" in first_content
    assert "AUTH_PASSWORD=ResuMate@2026" in first_content
    assert "AUTH_PASSWORD=replace-me" not in first_content
    assert "DO NOT CHANGE: RESUMATE_MASTER_KEY" in first_content
    assert "DO NOT CHANGE: RESUMATE_JWT_SECRET" in first_content
    assert first_content == second_content
    assert first_content.count("RESUMATE_MASTER_KEY=") == 1
    assert first_content.count("RESUMATE_JWT_SECRET=") == 1


def test_existing_master_key_is_not_rewritten(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    master_key = Fernet.generate_key().decode("ascii")
    jwt_secret = "x" * 48
    original_content = (
        f"APP_ENV=development\n"
        f"AUTH_PASSWORD=custom-password\n"
        f"RESUMATE_MASTER_KEY={master_key}\n"
        f"RESUMATE_JWT_SECRET={jwt_secret}\n"
    )
    env_file.write_text(original_content, encoding="utf-8")
    monkeypatch.delenv("RESUMATE_MASTER_KEY", raising=False)
    monkeypatch.setenv("APP_ENV_FILE", str(env_file))
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("APP_STORAGE_DIR", str(tmp_path / "storage"))
    get_settings.cache_clear()

    first_settings = get_settings()
    get_settings.cache_clear()
    second_settings = get_settings()

    assert first_settings.env_file_path == env_file
    assert second_settings.env_file_path == env_file
    assert env_file.read_text(encoding="utf-8") == original_content


def test_default_env_file_lives_in_data_dir(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / ".resumate"
    monkeypatch.delenv("APP_ENV_FILE", raising=False)
    monkeypatch.delenv("RESUMATE_MASTER_KEY", raising=False)
    monkeypatch.setenv("APP_DATA_DIR", str(data_dir))
    monkeypatch.setenv("APP_DB_PATH", str(data_dir / "app.db"))
    monkeypatch.setenv("APP_STORAGE_DIR", str(data_dir / "storage"))
    monkeypatch.setattr(app_config, "LEGACY_ENV_PATH", tmp_path / "missing.env")
    get_settings.cache_clear()

    settings = get_settings()
    env_file = data_dir / ".env"
    content = env_file.read_text(encoding="utf-8")

    assert settings.env_file_path == env_file.resolve()
    assert env_file.exists()
    assert "APP_DATA_DIR=~/.resumate" in content
    assert "AUTH_PASSWORD=ResuMate@2026" in content
    assert "DO NOT CHANGE: RESUMATE_MASTER_KEY" in content
    assert "DO NOT CHANGE: RESUMATE_JWT_SECRET" in content
    assert content.count("RESUMATE_MASTER_KEY=") == 1
    assert content.count("RESUMATE_JWT_SECRET=") == 1


def test_model_config_encrypts_api_key_in_sqlite(client: TestClient) -> None:
    response = client.post(
        "/api/model-configs",
        json={
            "id": "llm-api",
            "provider": "openai",
            "nickname": "API",
            "apiKey": "sk-new-secret",
            "model": "gpt-5.1",
            "apiUrl": "https://api.openai.com/v1",
            "temperature": 0.4,
            "topP": 0.9,
            "maxTokens": None,
            "systemPrompt": "test",
        },
    )
    list_response = client.get("/api/model-configs")
    delete_response = client.delete("/api/model-configs/llm-api")
    empty_list_response = client.get("/api/model-configs")

    assert response.status_code == 200
    assert list_response.status_code == 200
    assert delete_response.status_code == 200
    assert empty_list_response.status_code == 200
    assert response.json()["data"]["apiKeyPreview"] == "sk-new****"
    assert list_response.json()["data"]["configs"][0]["apiKeyPreview"] == "sk-new****"
    assert empty_list_response.json()["data"]["configs"] == []
    assert "sk-new-secret" not in response.text

    with connect() as conn:
        row = conn.execute(
            """
            SELECT encrypted_api_key, api_key_preview, enabled
            FROM llm_configs
            WHERE client_id = ?
            """,
            ("llm-api",),
        ).fetchone()

    assert row is not None
    assert row["encrypted_api_key"] != "sk-new-secret"
    assert row["api_key_preview"] == "sk-new****"
    assert row["enabled"] == 0


def test_identical_model_config_does_not_update_row(client: TestClient) -> None:
    payload = {
        "id": "llm-noop",
        "provider": "openai",
        "nickname": "Noop",
        "apiKey": "sk-noop-secret",
        "model": "gpt-5.1",
        "apiUrl": "https://api.openai.com/v1",
        "temperature": 0.4,
        "topP": 0.9,
        "maxTokens": None,
        "systemPrompt": "test",
    }

    first_response = client.post("/api/model-configs", json=payload)

    assert first_response.status_code == 200

    with connect() as conn:
        conn.execute(
            """
            UPDATE llm_configs
            SET updated_at = ?
            WHERE client_id = ?
            """,
            ("2000-01-01 00:00:00", "llm-noop"),
        )
        row_before = conn.execute(
            """
            SELECT encrypted_api_key, updated_at
            FROM llm_configs
            WHERE client_id = ?
            """,
            ("llm-noop",),
        ).fetchone()

    second_response = client.post("/api/model-configs", json=payload)

    assert second_response.status_code == 200

    with connect() as conn:
        row_after = conn.execute(
            """
            SELECT encrypted_api_key, updated_at
            FROM llm_configs
            WHERE client_id = ?
            """,
            ("llm-noop",),
        ).fetchone()

    assert row_before is not None
    assert row_after is not None
    assert row_after["encrypted_api_key"] == row_before["encrypted_api_key"]
    assert row_after["updated_at"] == row_before["updated_at"]


def test_agent_chat_guides_when_model_is_missing(client: TestClient) -> None:
    response = client.post(
        "/api/agent/chat",
        json={
            "prompt": "Find missing keywords",
            "conversation": [],
            "files": [],
            "locale": "en",
            "resume": {
                "basic": {
                    "name": "Avery",
                    "summary": "Frontend engineer with React project experience.",
                },
                "sections": [],
            },
            "jobBrief": "React TypeScript",
            "keywordMatch": {
                "matched": ["React"],
                "missing": ["TypeScript"],
                "score": 60,
            },
            "appliedActions": [],
            "modelConfig": None,
            "settings": {},
            "stream": False,
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert "No usable model configuration" in data["message"]["text"]
    assert data["message"]["edits"] == []
    assert data["message"]["tools"] == []


def test_agent_chat_persists_and_loads_session(client: TestClient) -> None:
    response = client.post(
        "/api/agent/chat",
        json={
            "resumeId": "resume-test",
            "prompt": "帮我检查项目经历",
            "message": {
                "id": "agent-user-session-1",
                "role": "user",
                "text": "帮我检查项目经历",
            },
            "messages": [
                {
                    "id": "agent-user-session-1",
                    "role": "user",
                    "text": "帮我检查项目经历",
                },
            ],
            "conversation": [
                {"role": "user", "text": "帮我检查项目经历"},
            ],
            "files": [],
            "locale": "zh",
            "resume": {"basic": {"name": "王小明"}, "sections": []},
            "jobBrief": "",
            "keywordMatch": {"matched": [], "missing": [], "score": 0},
            "appliedActions": [],
            "modelConfig": None,
            "settings": {},
            "stream": False,
        },
    )
    session_response = client.get("/api/agent/resumes/resume-test/session")

    assert response.status_code == 200
    assert session_response.status_code == 200
    session_data = session_response.json()["data"]
    messages = session_data["messages"]
    assert session_data["resumeId"] == "resume-test"
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[0]["id"] == "agent-user-session-1"
    assert messages[0]["text"] == "帮我检查项目经历"
    assert messages[1]["response"]["role"] == "assistant"
    assert messages[1]["response"]["text"] == response.json()["data"]["message"]["text"]


def test_agent_chat_supports_json(client: TestClient, monkeypatch) -> None:
    model_config = create_agent_model_config(client)
    monkeypatch.setattr(
        "app.services.agent.complete_chat",
        lambda *_: (
            '{"text":"Real model response","suggestions":["Use TypeScript"],'
            '"knowledge":[{"title":"TypeScript","detail":"Prepare examples."}],'
            '"quickReplies":["Preview edits"]}'
        ),
    )
    monkeypatch.setattr(
        "app.services.agent.complete_chat_tool_call",
        stub_tool_call_batches(
            [
                tool_call(
                    "call-jd",
                    "jd_reference_search",
                    {"query": "frontend engineer job description"},
                ),
            ],
            [
                tool_call("call-analysis", "resume_analysis"),
            ],
            [
                tool_call("call-plan", "edit_plan"),
            ],
            [
                tool_call(
                    "call-execute",
                    "edit_execute",
                    {
                        "edits": [
                            {
                                "title": "Update summary",
                                "target": "basic.summary",
                                "reason": (
                                    "Add the missing TypeScript keyword from the JD."
                                ),
                                "operation": {
                                    "type": "replace_field",
                                    "path": "basic.summary",
                                    "value": (
                                        "Frontend engineer with React and "
                                        "TypeScript project experience."
                                    ),
                                },
                            },
                        ],
                    },
                ),
            ],
        ),
    )
    monkeypatch.setattr("app.services.agent._search_jd_reference", stub_jd_search)

    response = client.post(
        "/api/agent/chat",
        json={
            "prompt": "Find missing keywords",
            "message": {
                "id": "agent-user-1",
                "role": "user",
                "text": "Find missing keywords",
                "files": [
                    {
                        "id": "file-1",
                        "filename": "jd.txt",
                        "mediaType": "text/plain",
                        "content": "TypeScript JD attachment text",
                        "url": "https://example.test/jd.txt",
                    }
                ],
            },
            "messages": [
                {"role": "user", "text": "Find missing keywords"},
            ],
            "conversation": [
                {"role": "user", "text": "Find missing keywords"},
            ],
            "files": [
                {
                    "id": "file-1",
                    "filename": "jd.txt",
                    "mediaType": "text/plain",
                    "content": "TypeScript JD attachment text",
                    "url": "https://example.test/jd.txt",
                }
            ],
            "locale": "en",
            "resume": {
                "basic": {
                    "name": "Avery",
                    "summary": "Frontend engineer with React project experience.",
                },
                "sections": [],
            },
            "jobBrief": "React TypeScript",
            "keywordMatch": {
                "matched": ["React"],
                "missing": ["TypeScript"],
                "score": 60,
            },
            "appliedActions": [],
            "modelConfig": model_config,
            "settings": {},
            "stream": False,
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["message"]["role"] == "assistant"
    assert data["message"]["text"] == "Real model response"
    assert data["message"]["actions"]
    assert data["message"]["tools"]
    assert data["message"]["sources"]
    assert data["message"]["edits"]
    assert data["message"]["quickReplies"]
    assert any(
        source["sourceType"] == "jobBrief" for source in data["message"]["sources"]
    )
    assert any(
        source["sourceType"] == "attachment"
        and source["excerpt"] == "TypeScript JD attachment text"
        for source in data["message"]["sources"]
    )
    assert not any(
        source["sourceType"] in {"resume", "system"}
        for source in data["message"]["sources"]
    )
    assert data["message"]["edits"][0]["status"] == "executed"
    assert data["message"]["edits"][0]["operation"]["type"] == "replace_field"
    assert any(
        tool["title"] == "jd_reference_search" for tool in data["message"]["tools"]
    )


def test_agent_chat_executes_model_selected_item_edit_without_jd_search(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    monkeypatch.setattr(
        "app.services.agent.complete_chat",
        lambda *_: '{"text":"已生成项目经历修改草稿"}',
    )
    monkeypatch.setattr(
        "app.services.agent.complete_chat_tool_call",
        stub_tool_call_batches(
            [
                tool_call(
                    "call-execute",
                    "edit_execute",
                    {
                        "edits": [
                            {
                                "title": "强化项目结果",
                                "target": "sections.project.items.project-1",
                                "reason": (
                                    "用户要求修改项目经历，直接定位现有项目条目。"
                                ),
                                "replacement": "负责推荐链路优化，点击率提升 12%。",
                                "operation": {
                                    "type": "update_item",
                                    "sectionId": "project",
                                    "itemId": "project-1",
                                    "patch": {
                                        "description": (
                                            "负责推荐链路优化，点击率提升 12%。"
                                        ),
                                        "highlights": ["协同后端将接口延迟降低 30%"],
                                    },
                                },
                            },
                        ],
                    },
                ),
            ],
            [
                tool_call(
                    "call-finish",
                    "finish",
                    {
                        "status": "ready",
                        "reason": "Observation shows the project item now matches.",
                    },
                ),
            ],
        ),
    )

    response = client.post(
        "/api/agent/chat",
        json={
            "prompt": "把项目经历写得更像推荐算法工程师",
            "message": {
                "role": "user",
                "text": "把项目经历写得更像推荐算法工程师",
            },
            "messages": [
                {"role": "user", "text": "把项目经历写得更像推荐算法工程师"},
            ],
            "conversation": [
                {"role": "user", "text": "把项目经历写得更像推荐算法工程师"},
            ],
            "files": [],
            "locale": "zh",
            "resume": {
                "basic": {"name": "王小明", "summary": ""},
                "sections": [
                    {
                        "id": "project",
                        "kind": "project",
                        "layout": "timeline",
                        "customTitle": "",
                        "items": [
                            {
                                "id": "project-1",
                                "title": "电商推荐系统优化",
                                "subtitle": "",
                                "meta": "",
                                "period": "2023/06 - 2023/09",
                                "description": "负责推荐算法迭代。",
                                "highlights": [],
                            },
                        ],
                    },
                ],
            },
            "jobBrief": "",
            "keywordMatch": {"matched": [], "missing": [], "score": 0},
            "appliedActions": [],
            "modelConfig": model_config,
            "settings": {},
            "stream": False,
        },
    )

    assert response.status_code == 200
    message = response.json()["data"]["message"]
    tool_titles = [tool["title"] for tool in message["tools"]]
    assert tool_titles == ["edit_execute"]
    observations = message["tools"][0]["output"]["observations"]
    assert observations[0]["target"] == "sections.project.items.project-1"
    assert observations[0]["before"]["description"] == "负责推荐算法迭代。"
    assert (
        observations[0]["after"]["description"]
        == "负责推荐链路优化，点击率提升 12%。"
    )
    assert message["text"] == "已生成项目经历修改草稿"
    assert message["edits"][0]["target"] == "sections.project.items.project-1"
    assert message["edits"][0]["operation"] == {
        "type": "update_item",
        "sectionId": "project",
        "itemId": "project-1",
        "patch": {
            "description": "负责推荐链路优化，点击率提升 12%。",
            "highlights": ["协同后端将接口延迟降低 30%"],
        },
    }


def test_agent_chat_executes_empty_resume_project_insert_from_plan(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    prompt = (
        "帮我添加项目经历：项目名称：电商后台管理系统\n"
        "时间：2023.03 - 2023.06\n"
        "负责 Spring Boot、MySQL、Redis、Docker 和 SQL 优化。"
    )
    monkeypatch.setattr(
        "app.services.agent.complete_chat",
        lambda *_: '{"text":"已生成项目经历草稿"}',
    )
    monkeypatch.setattr(
        "app.services.agent.complete_chat_tool_call",
        stub_tool_call_batches(
            [
                tool_call("call-analysis", "resume_analysis"),
            ],
            [
                tool_call(
                    "call-plan",
                    "edit_plan",
                    {
                        "steps": [
                            {
                                "action": "insert_section",
                                "target": "sections",
                                "reason": "用户提供了项目经历，需要新增项目模块。",
                            },
                        ],
                    },
                ),
            ],
            [
                tool_call("call-execute", "edit_execute"),
            ],
            [
                tool_call(
                    "call-finish",
                    "finish",
                    {
                        "status": "ready",
                        "reason": "Observation shows the project section was added.",
                    },
                ),
            ],
        ),
    )

    response = client.post(
        "/api/agent/chat",
        json={
            "prompt": prompt,
            "message": {"role": "user", "text": prompt},
            "messages": [],
            "conversation": [],
            "files": [],
            "locale": "zh",
            "resume": {"basic": {"name": "姓名", "summary": ""}, "sections": []},
            "jobBrief": "",
            "keywordMatch": {"matched": [], "missing": [], "score": 0},
            "appliedActions": [],
            "modelConfig": model_config,
            "settings": {},
            "stream": False,
        },
    )

    assert response.status_code == 200
    message = response.json()["data"]["message"]
    tool_titles = [tool["title"] for tool in message["tools"]]
    assert tool_titles == ["resume_analysis", "edit_plan", "edit_execute"]
    assert message["edits"]
    operation = message["edits"][0]["operation"]
    assert operation["type"] == "insert_section"
    assert operation["section"]["kind"] == "project"
    assert operation["section"]["items"][0]["title"] == "电商后台管理系统"
    assert operation["section"]["items"][0]["period"] == "2023.03 - 2023.06"


def test_agent_chat_direct_message_does_not_return_tools(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    monkeypatch.setattr(
        "app.services.agent.complete_chat",
        lambda *_: "你好，我可以回答简历相关问题。",
    )

    response = client.post(
        "/api/agent/chat",
        json={
            "prompt": "你好",
            "message": {"role": "user", "text": "你好"},
            "messages": [{"role": "user", "text": "你好"}],
            "conversation": [{"role": "user", "text": "你好"}],
            "files": [],
            "locale": "zh",
            "resume": {"basic": {"name": "王小明"}, "sections": []},
            "jobBrief": "",
            "keywordMatch": {"matched": [], "missing": [], "score": 0},
            "appliedActions": [],
            "modelConfig": model_config,
            "settings": {},
            "stream": False,
        },
    )

    assert response.status_code == 200
    message = response.json()["data"]["message"]
    assert message["text"] == "你好，我可以回答简历相关问题。"
    assert message["tools"] == []
    assert message["edits"] == []
    assert message["actions"] == []


def test_agent_model_error_does_not_return_llm_tool(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)

    def raise_provider_error(*_: object) -> str:
        raise LlmRequestError("provider unavailable")

    monkeypatch.setattr("app.services.agent.complete_chat", raise_provider_error)

    response = client.post(
        "/api/agent/chat",
        json={
            "prompt": "你好",
            "message": {"role": "user", "text": "你好"},
            "messages": [{"role": "user", "text": "你好"}],
            "conversation": [{"role": "user", "text": "你好"}],
            "files": [],
            "locale": "zh",
            "resume": {"basic": {"name": "王小明"}, "sections": []},
            "jobBrief": "",
            "keywordMatch": {"matched": [], "missing": [], "score": 0},
            "appliedActions": [],
            "modelConfig": model_config,
            "settings": {},
            "stream": False,
        },
    )

    assert response.status_code == 200
    message = response.json()["data"]["message"]
    assert "调用模型失败" in message["text"]
    assert "provider unavailable" in message["text"]
    assert message["tools"] == []


def test_agent_chat_uses_provided_jd_url(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    monkeypatch.setattr(
        "app.services.agent.complete_chat",
        lambda *_: '{"text":"Real model response for JD URL"}',
    )
    monkeypatch.setattr(
        "app.services.agent.complete_chat_tool_call",
        stub_tool_call_batches(
            [
                tool_call(
                    "call-jd",
                    "jd_url_fetch",
                    {"url": "https://example.test/jobs/frontend"},
                ),
            ],
            [
                tool_call("call-analysis", "resume_analysis"),
            ],
            [
                tool_call("call-plan", "edit_plan"),
            ],
            [
                tool_call("call-execute", "edit_execute"),
            ],
        ),
    )
    monkeypatch.setattr(
        "app.services.agent._fetch_web_reference",
        lambda *_: WebReference(
            title="Frontend Engineer Job",
            excerpt="React TypeScript responsibilities and requirements.",
        ),
    )

    response = client.post(
        "/api/agent/chat",
        json={
            "prompt": "请基于 https://example.test/jobs/frontend 调整模块顺序",
            "message": {
                "id": "agent-user-1",
                "role": "user",
                "text": "请基于 https://example.test/jobs/frontend 调整模块顺序",
            },
            "messages": [
                {
                    "role": "user",
                    "text": "请基于 https://example.test/jobs/frontend 调整模块顺序",
                },
            ],
            "conversation": [
                {
                    "role": "user",
                    "text": "请基于 https://example.test/jobs/frontend 调整模块顺序",
                },
            ],
            "files": [],
            "locale": "zh",
            "resume": {
                "basic": {"name": "王小明", "summary": "前端开发。"},
                "sections": [
                    {
                        "id": "education",
                        "kind": "education",
                        "layout": "timeline",
                        "customTitle": "",
                        "items": [
                            {
                                "id": "edu-1",
                                "title": "大学",
                                "subtitle": "",
                                "meta": "",
                                "period": "",
                                "description": "",
                                "highlights": [],
                            },
                        ],
                    },
                    {
                        "id": "project",
                        "kind": "project",
                        "layout": "timeline",
                        "customTitle": "",
                        "items": [
                            {
                                "id": "project-1",
                                "title": "项目",
                                "subtitle": "",
                                "meta": "",
                                "period": "",
                                "description": "",
                                "highlights": [],
                            },
                        ],
                    },
                ],
            },
            "jobBrief": "",
            "keywordMatch": {"matched": [], "missing": [], "score": 0},
            "appliedActions": [],
            "modelConfig": model_config,
            "settings": {},
            "stream": False,
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert any(tool["title"] == "jd_url_fetch" for tool in data["message"]["tools"])
    assert data["message"]["sources"] == [
        {
            "id": "source-jd-url",
            "title": "Frontend Engineer Job",
            "sourceType": "web",
            "url": "https://example.test/jobs/frontend",
            "excerpt": "React TypeScript responsibilities and requirements.",
        },
    ]
    assert any(
        edit["operation"]["type"] == "reorder_sections"
        for edit in data["message"]["edits"]
    )


def test_agent_chat_cleans_chinese_target_role(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    monkeypatch.setattr(
        "app.services.agent.complete_chat",
        lambda *_: '{"text":"已分析目标岗位"}',
    )
    monkeypatch.setattr(
        "app.services.agent.complete_chat_tool_call",
        stub_tool_call_batches(
            [
                tool_call(
                    "call-jd",
                    "jd_reference_search",
                    {"query": "AI应用开发 岗位 JD 职责 任职要求"},
                ),
            ],
            [
                tool_call("call-analysis", "resume_analysis"),
            ],
            [
                tool_call("call-plan", "edit_plan"),
            ],
        ),
    )
    monkeypatch.setattr("app.services.agent._search_jd_reference", stub_jd_search)

    response = client.post(
        "/api/agent/chat",
        json={
            "prompt": "帮我优化简历，应聘的职位是AI应用开发",
            "message": {
                "role": "user",
                "text": "帮我优化简历，应聘的职位是AI应用开发",
            },
            "messages": [
                {"role": "user", "text": "帮我优化简历，应聘的职位是AI应用开发"},
            ],
            "conversation": [
                {"role": "user", "text": "帮我优化简历，应聘的职位是AI应用开发"},
            ],
            "files": [],
            "locale": "zh",
            "resume": {"basic": {"name": "王小明"}, "sections": []},
            "jobBrief": "",
            "keywordMatch": {"matched": [], "missing": [], "score": 0},
            "appliedActions": [],
            "modelConfig": model_config,
            "settings": {},
            "stream": False,
        },
    )

    assert response.status_code == 200
    message = response.json()["data"]["message"]
    jd_tool = next(
        tool
        for tool in message["tools"]
        if tool["title"] == "jd_reference_search"
    )
    assert jd_tool["output"]["role"] == "AI应用开发"
    assert jd_tool["input"]["query"] == "AI应用开发 岗位 JD 职责 任职要求"
    assert message["knowledge"][0]["title"] == "AI应用开发"
    assert not any(
        "的职位是" in suggestion
        for suggestion in message["suggestions"]
    )


def test_agent_chat_streams_tool_and_source_metadata(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    monkeypatch.setattr("app.services.agent._search_jd_reference", stub_jd_search)
    monkeypatch.setattr(
        "app.services.agent.complete_chat_tool_call",
        stub_tool_call_batches(
            [
                tool_call(
                    "call-jd",
                    "jd_reference_search",
                    {"query": "前端开发工程师 岗位 JD 职责 任职要求"},
                ),
            ],
            [
                tool_call("call-analysis", "resume_analysis"),
            ],
            [
                tool_call("call-plan", "edit_plan"),
            ],
        ),
    )

    def stream_response(*_: object) -> object:
        yield LlmStreamDelta(kind="text", delta="流式")
        yield LlmStreamDelta(kind="text", delta="真实模型响应")

    monkeypatch.setattr("app.services.agent.complete_chat_stream", stream_response)

    with client.stream(
        "POST",
        "/api/agent/chat",
        headers={"accept": "text/event-stream"},
        json={
            "prompt": "优化个人简介",
            "message": {"role": "user", "text": "优化个人简介"},
            "messages": [{"role": "user", "text": "优化个人简介"}],
            "conversation": [{"role": "user", "text": "优化个人简介"}],
            "files": [],
            "locale": "zh",
            "resume": {"basic": {"name": "王小明"}, "sections": []},
            "jobBrief": "",
            "keywordMatch": {
                "matched": ["React"],
                "missing": ["TypeScript"],
                "score": 72,
            },
            "appliedActions": [],
            "modelConfig": model_config,
            "settings": {},
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: message_start" in body
    assert "event: plan" not in body
    assert "event: timeline" in body
    assert "event: text_delta" not in body
    assert "我先分析目标岗位和当前简历" not in body
    assert "event: tools" in body
    assert '"state":"input-available"' in body
    assert '"state":"output-available"' in body
    assert "event: message_delta" in body
    assert "event: message_done" in body
    assert "流式真实模型响应" in body
    assert body.index("jd_reference_search") < body.index("resume_analysis")
    assert body.index("resume_analysis") < body.index("edit_plan")
    assert body.index("event: tools") < body.index("流式真实模型响应")
    assert body.index("流式真实模型响应") < body.index('"source-jd-search"')
    assert '"tools":' in body
    assert '"source-jd-search"' in body
    assert '"edits":[]' in body
    assert '"quickReplies":' in body
    assert "edit_plan" in body
    assert "edit_execute" not in body


def test_agent_chat_streams_model_narration_between_tool_actions(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    monkeypatch.setattr(
        "app.services.agent.complete_chat_tool_call",
        stub_tool_call_responses(
            LlmToolCallResponse(
                content="我先看一下当前简历内容。",
                tool_calls=[tool_call("call-analysis", "resume_analysis")],
            ),
            LlmToolCallResponse(
                content="我发现简介比较短，下一步先整理可执行的修改方向。",
                tool_calls=[tool_call("call-plan", "edit_plan")],
            ),
        ),
    )

    def stream_response(*_: object) -> object:
        yield LlmStreamDelta(kind="text", delta="最后给出草稿建议。")

    monkeypatch.setattr("app.services.agent.complete_chat_stream", stream_response)

    with client.stream(
        "POST",
        "/api/agent/chat",
        headers={"accept": "text/event-stream"},
        json={
            "prompt": "优化个人简介",
            "message": {"role": "user", "text": "优化个人简介"},
            "messages": [{"role": "user", "text": "优化个人简介"}],
            "conversation": [{"role": "user", "text": "优化个人简介"}],
            "files": [],
            "locale": "zh",
            "resume": {
                "basic": {"name": "王小明", "summary": "有前端项目经验。"},
                "sections": [],
            },
            "jobBrief": "",
            "keywordMatch": {"matched": [], "missing": [], "score": 0},
            "appliedActions": [],
            "modelConfig": model_config,
            "settings": {},
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: updates" not in body
    assert "event: timeline" in body
    assert "event: text_delta" not in body
    assert "我先看一下当前简历内容。" in body
    assert "已读取当前简历结构" not in body
    assert "已整理出" not in body
    assert "我发现简介比较短，下一步先整理可执行的修改方向。" in body
    assert body.index("我先看一下当前简历内容。") < body.index(
        "resume_analysis",
    )
    assert body.index("resume_analysis") < body.index(
        "我发现简介比较短，下一步先整理可执行的修改方向。",
    )
    assert body.index("我发现简介比较短，下一步先整理可执行的修改方向。") < body.index(
        "edit_plan",
    )
    assert body.index("edit_plan") < body.index("最后给出草稿建议。")
    assert "最后给出草稿建议。" in body

    message_done_frame = next(
        frame
        for frame in body.split("\n\n")
        if frame.startswith("event: message_done\n")
    )
    message_done_data = next(
        line.removeprefix("data: ")
        for line in message_done_frame.splitlines()
        if line.startswith("data: ")
    )
    timeline = json.loads(message_done_data)["message"]["timeline"]
    assert [part["type"] for part in timeline] == [
        "text",
        "tool_group",
        "text",
        "tool_group",
        "text",
    ]
    assert [
        part["toolIds"]
        for part in timeline
        if part["type"] == "tool_group"
    ] == [["call-analysis"], ["call-plan"]]


def test_agent_chat_streams_model_tool_batch_as_ordered_timeline_operations(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    monkeypatch.setattr("app.services.agent._search_jd_reference", stub_jd_search)
    monkeypatch.setattr(
        "app.services.agent.complete_chat_tool_call",
        stub_tool_call_responses(
            LlmToolCallResponse(
                content="我先同时检查简历结构和岗位参考。",
                tool_calls=[
                    tool_call("call-analysis", "resume_analysis"),
                    tool_call(
                        "call-jd",
                        "jd_reference_search",
                        {"query": "前端开发工程师 岗位 JD 职责 任职要求"},
                    ),
                ],
            ),
        ),
    )

    def stream_response(*_: object) -> object:
        yield LlmStreamDelta(kind="text", delta="下一步会基于这些结果给出草稿。")

    monkeypatch.setattr("app.services.agent.complete_chat_stream", stream_response)

    with client.stream(
        "POST",
        "/api/agent/chat",
        headers={"accept": "text/event-stream"},
        json={
            "prompt": "优化个人简介",
            "message": {"role": "user", "text": "优化个人简介"},
            "messages": [{"role": "user", "text": "优化个人简介"}],
            "conversation": [{"role": "user", "text": "优化个人简介"}],
            "files": [],
            "locale": "zh",
            "resume": {
                "basic": {"name": "王小明", "summary": "有前端项目经验。"},
                "sections": [],
            },
            "jobBrief": "",
            "keywordMatch": {"matched": [], "missing": [], "score": 0},
            "appliedActions": [],
            "modelConfig": model_config,
            "settings": {},
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: plan" not in body
    assert "event: timeline" in body
    assert "event: text_delta" not in body
    assert body.index("我先同时检查简历结构和岗位参考。") < body.index(
        "resume_analysis",
    )
    assert "已读取当前简历结构" not in body
    assert "已拿到岗位参考" not in body
    assert body.index("resume_analysis") < body.index("jd_reference_search")
    assert body.index("jd_reference_search") < body.index(
        "下一步会基于这些结果给出草稿。",
    )

    message_done_frame = next(
        frame
        for frame in body.split("\n\n")
        if frame.startswith("event: message_done\n")
    )
    message_done_data = next(
        line.removeprefix("data: ")
        for line in message_done_frame.splitlines()
        if line.startswith("data: ")
    )
    timeline = json.loads(message_done_data)["message"]["timeline"]
    assert [part["type"] for part in timeline] == [
        "text",
        "tool_group",
        "tool_group",
        "text",
    ]
    assert [
        part["toolIds"]
        for part in timeline
        if part["type"] == "tool_group"
    ] == [["call-analysis"], ["call-jd"]]


def test_agent_chat_streams_terminal_model_text_after_tool_observation(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    monkeypatch.setattr(
        "app.services.agent.complete_chat_tool_call",
        stub_tool_call_responses(
            LlmToolCallResponse(
                content="我先读取当前简历。",
                tool_calls=[tool_call("call-analysis", "resume_analysis")],
            ),
            LlmToolCallResponse(
                content="当前简历已经足够回答这个问题，我不会继续调用工具。",
                tool_calls=[],
            ),
        ),
    )

    def stream_response(*_: object) -> object:
        raise AssertionError("terminal tool-loop text should not request final stream")

    monkeypatch.setattr("app.services.agent.complete_chat_stream", stream_response)

    with client.stream(
        "POST",
        "/api/agent/chat",
        headers={"accept": "text/event-stream"},
        json={
            "prompt": "分析一下我的简历",
            "message": {"role": "user", "text": "分析一下我的简历"},
            "messages": [{"role": "user", "text": "分析一下我的简历"}],
            "conversation": [{"role": "user", "text": "分析一下我的简历"}],
            "files": [],
            "locale": "zh",
            "resume": {
                "basic": {"name": "王小明", "summary": "有前端项目经验。"},
                "sections": [],
            },
            "jobBrief": "",
            "keywordMatch": {"matched": [], "missing": [], "score": 0},
            "appliedActions": [],
            "modelConfig": model_config,
            "settings": {},
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "我先读取当前简历。" in body
    assert "当前简历已经足够回答这个问题，我不会继续调用工具。" in body
    assert "已读取当前简历结构" not in body
    assert body.index("我先读取当前简历。") < body.index("resume_analysis")
    assert body.index("resume_analysis") < body.index(
        "当前简历已经足够回答这个问题，我不会继续调用工具。",
    )

    message_done_frame = next(
        frame
        for frame in body.split("\n\n")
        if frame.startswith("event: message_done\n")
    )
    message_done_data = next(
        line.removeprefix("data: ")
        for line in message_done_frame.splitlines()
        if line.startswith("data: ")
    )
    timeline = json.loads(message_done_data)["message"]["timeline"]
    assert [part["type"] for part in timeline] == ["text", "tool_group", "text"]
    assert timeline[-1]["text"] == "当前简历已经足够回答这个问题，我不会继续调用工具。"


def test_agent_chat_streams_edit_metadata_when_execute_finishes(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    monkeypatch.setattr("app.services.agent._search_jd_reference", stub_jd_search)
    monkeypatch.setattr(
        "app.services.agent.complete_chat_tool_call",
        stub_tool_call_batches(
            [
                tool_call(
                    "call-jd",
                    "jd_reference_search",
                    {"query": "前端开发工程师 岗位 JD 职责 任职要求"},
                ),
            ],
            [
                tool_call("call-analysis", "resume_analysis"),
            ],
            [
                tool_call("call-plan", "edit_plan"),
            ],
            [
                tool_call("call-execute", "edit_execute"),
            ],
        ),
    )

    def stream_response(*_: object) -> object:
        yield LlmStreamDelta(kind="text", delta="模型")
        yield LlmStreamDelta(kind="text", delta="完成分析")

    monkeypatch.setattr("app.services.agent.complete_chat_stream", stream_response)

    with client.stream(
        "POST",
        "/api/agent/chat",
        headers={"accept": "text/event-stream"},
        json={
            "prompt": "优化个人简介",
            "message": {"role": "user", "text": "优化个人简介"},
            "messages": [{"role": "user", "text": "优化个人简介"}],
            "conversation": [{"role": "user", "text": "优化个人简介"}],
            "files": [],
            "locale": "zh",
            "resume": {
                "basic": {"name": "王小明", "summary": "有前端项目经验。"},
                "sections": [],
            },
            "jobBrief": "",
            "keywordMatch": {
                "matched": ["React"],
                "missing": ["TypeScript"],
                "score": 72,
            },
            "appliedActions": [],
            "modelConfig": model_config,
            "settings": {},
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "我先分析目标岗位和当前简历" not in body
    assert "event: plan" not in body
    assert "event: tools" in body
    assert "event: edits" in body
    assert "event: text_delta" not in body
    assert "模型完成分析" in body
    assert body.index("event: tools") < body.index("模型完成分析")
    assert body.index("event: edits") < body.index("模型完成分析")
    assert body.rindex('"edits":[{') > body.index("模型完成分析")
    assert '"edits":[{' in body
    assert "edit_plan" in body
    assert "edit_execute" in body


def test_agent_chat_streams_direct_model_tokens(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)

    def stream_response(*_: object) -> object:
        yield LlmStreamDelta(kind="reasoning", delta="先确认用户意图。")
        yield LlmStreamDelta(kind="text", delta="你好")
        yield LlmStreamDelta(kind="text", delta="，我可以帮你看简历。")

    monkeypatch.setattr("app.services.agent.complete_chat_stream", stream_response)

    with client.stream(
        "POST",
        "/api/agent/chat",
        headers={"accept": "text/event-stream"},
        json={
            "prompt": "你好",
            "message": {"role": "user", "text": "你好"},
            "messages": [{"role": "user", "text": "你好"}],
            "conversation": [{"role": "user", "text": "你好"}],
            "files": [],
            "locale": "zh",
            "resume": {"basic": {"name": "王小明"}, "sections": []},
            "jobBrief": "",
            "keywordMatch": {"matched": [], "missing": [], "score": 0},
            "appliedActions": [],
            "modelConfig": model_config,
            "settings": {},
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "正在等待模型返回。" not in body
    assert "event: reasoning_delta" in body
    assert "event: text_delta" in body
    assert "你好，我可以帮你看简历。" in body
    assert "先确认用户意图。" in body
    assert "event: tools" not in body


def test_import_resume_accepts_json_upload(client: TestClient) -> None:
    response = client.post(
        "/api/import/resume",
        files={
            "file": (
                "resume.json",
                b'{"basic":{"name":"Avery"},"sections":[]}',
                "application/json",
            ),
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["resumes"]


def test_export_pdf_creates_download(client: TestClient, monkeypatch) -> None:
    def write_test_pdf(
        export_id: str,
        request: ExportResumePdfRequest,
        **_: object,
    ) -> Path:
        from app.services.pdf import get_export_path

        export_path = get_export_path(export_id)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_bytes(b"%PDF-1.4\n% test\n")
        assert request.render_base_url == "http://frontend.test"
        return export_path

    monkeypatch.setattr("app.routers.exports.write_resume_pdf", write_test_pdf)

    resume_id = "resume-export"
    snapshot = {
        "resumes": [minimal_resume_item(resume_id=resume_id, title="Export Resume")],
        "modelConfigs": [],
        "savedAt": "2026-05-16T00:00:00.000Z",
    }
    save_response = client.put(
        "/api/workspace/snapshot?locale=en",
        json={"snapshot": snapshot},
    )
    assert save_response.status_code == 200

    response = client.post(
        "/api/exports/resume-pdf",
        json={
            "resumeId": resume_id,
            "locale": "en",
            "fileNameSeed": "resume-en",
            "savedAt": "2026-05-16T00:00:00.000Z",
            "renderBaseUrl": "http://frontend.test",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["fileName"] == "resume-en.pdf"
    download_url = data["downloadUrl"]

    download_response = client.get(download_url)

    assert download_response.status_code == 200
    assert download_response.headers["content-type"] == "application/pdf"
    assert download_response.content.startswith(b"%PDF")
