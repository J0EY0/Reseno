import json
import re
from pathlib import Path

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app import config as app_config
from app.config import get_settings
from app.db.connection import connect
from app.schemas.agent import AgentChatRequest
from app.schemas.exports import ExportResumePdfRequest
from app.services.agent import WebReference, WebSearchResult
from app.services.agent.editing.operations import _model_edit_suggestions
from app.services.agent.executor import AgentPlanExecutor
from app.services.agent.prompts import EDIT_OPERATION_GUIDE, EDIT_OPERATION_GUIDES
from app.services.agent.runtime.messages import build_agent_messages
from app.services.agent.section_registry import (
    SECTION_DEFAULT_LAYOUTS,
    SECTION_KIND_ENUM,
    SECTION_REGISTRY,
)
from app.services.agent.tools import AgentToolRunner
from app.services.agent.tools import registry as tool_registry
from app.services.auth_tokens import create_access_token
from app.services.llm_client import (
    AgentLlmConfig,
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


def minimal_template_definition(
    template_id: str = "template-client-id",
    name: str = "Custom Template",
) -> dict:
    return {
        "id": template_id,
        "preset": "minimal",
        "name": name,
        "description": "Custom template",
        "layout": {
            "basicInfo": "centered",
            "section": "plain",
            "avatarPosition": "right",
            "avatarShape": "rounded",
            "avatarWidth": 25,
            "avatarHeight": 32,
            "avatarOffsetX": 0,
            "avatarOffsetY": 0,
            "avatarBorderWidth": 0,
            "avatarBorderColor": "#ffffff",
            "images": [],
        },
        "typography": {"fontFamily": "inter", "fontSize": 16},
        "settings": {
            "pagePaddingTop": 14,
            "pagePaddingX": 12,
            "pagePaddingBottom": 12,
            "sectionGap": 1.4,
            "itemGap": 1,
            "bodyLineHeight": 1.8,
            "nameScale": 2.15,
            "sectionTitleScale": 1.28,
            "itemTitleScale": 1.02,
            "metaScale": 0.92,
            "bodyScale": 0.96,
            "pageBackground": "#ffffff",
            "surfaceColor": "#f8fafc",
            "headingColor": "#111827",
            "bodyColor": "#334155",
            "mutedColor": "#64748b",
            "dividerColor": "#202020",
            "dividerThickness": 1,
        },
        "updatedAt": "2026-05-16T02:00:00.000Z",
        "isBuiltIn": False,
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


def parse_agent_stream_message(body: str) -> dict:
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
    return json.loads(message_done_data)["message"]


def post_agent_chat_stream(
    client: TestClient,
    payload: dict,
) -> tuple[str, dict]:
    stream_payload = {**payload, "stream": True}
    with client.stream(
        "POST",
        "/api/agent/chat",
        headers={"accept": "text/event-stream"},
        json=stream_payload,
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "").lower()
    assert response.headers.get("cache-control") == "no-cache"
    assert response.headers.get("x-accel-buffering") == "no"
    return body, parse_agent_stream_message(body)


def stub_stream_text(text: str):
    def stream_response(*_: object) -> object:
        yield LlmStreamDelta(kind="text", delta=text)

    return stream_response


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


async def async_stub_jd_search(query: str) -> tuple[WebSearchResult, int, None]:
    return stub_jd_search(query)


def tool_call(
    call_id: str,
    name: str,
    arguments: dict | None = None,
) -> LlmToolCall:
    raw_arguments = json.dumps(arguments or {}, ensure_ascii=False)
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
    assert payload["data"]["defaultTemplateId"] == "minimal"
    assert payload["data"]["customTemplates"] == []
    assert payload["data"]["deletedTemplates"] == []
    assert "resumes" not in payload["data"]
    assert "deletedResumes" not in payload["data"]


def test_resume_command_flow_owns_identity_versions_and_lifecycle(
    client: TestClient,
) -> None:
    create_response = client.post(
        "/api/resumes",
        json={"title": "新建简历1"},
    )

    assert create_response.status_code == 200
    created = create_response.json()["data"]
    resume_id = created["resume"]["id"]
    assert re.fullmatch(r"[A-Za-z0-9]{16}", resume_id)
    assert created["resume"]["title"] == "新建简历1"
    assert created["versionId"] == "1"

    save_payload = {
        **created["resume"],
        "title": "Backend Managed Resume",
        "resume": {
            **created["resume"]["resume"],
            "basic": {
                **created["resume"]["resume"]["basic"],
                "name": "Backend Managed",
            },
        },
        "templateSettings": None,
    }
    first_save = client.put(f"/api/resumes/{resume_id}", json=save_payload)
    second_save = client.put(f"/api/resumes/{resume_id}", json=save_payload)
    versions_response = client.get(f"/api/resumes/{resume_id}/versions")

    assert first_save.status_code == 200
    assert second_save.status_code == 200
    assert first_save.json()["data"]["versionId"] == "2"
    assert second_save.json()["data"]["versionId"] == "2"
    version_ids = [
        item["versionId"] for item in versions_response.json()["data"]["versions"]
    ]
    assert version_ids == ["2", "1"]

    trash_response = client.post(f"/api/resumes/{resume_id}/trash")
    deleted_list_response = client.get("/api/resumes?status=deleted")
    save_deleted_response = client.put(f"/api/resumes/{resume_id}", json=save_payload)

    assert trash_response.status_code == 200
    assert trash_response.json()["data"]["resume"]["deletedAt"]
    assert trash_response.json()["data"]["resume"]["resume"]["sections"] == []
    assert deleted_list_response.json()["data"]["resumes"][0]["id"] == resume_id
    assert save_deleted_response.json()["code"] != 0

    restore_response = client.post(f"/api/resumes/{resume_id}/restore")

    assert restore_response.status_code == 200
    assert restore_response.json()["data"]["resume"]["id"] == resume_id
    assert (
        restore_response.json()["data"]["resume"]["title"]
        == "Backend Managed Resume"
    )

    client.post(f"/api/resumes/{resume_id}/trash")
    delete_response = client.delete(f"/api/resumes/{resume_id}")
    detail_after_delete_response = client.get(f"/api/resumes/{resume_id}")
    resume_dir = get_settings().storage_dir / "resumes" / resume_id

    assert delete_response.status_code == 200
    assert delete_response.json()["data"]["id"] == resume_id
    assert detail_after_delete_response.json()["code"] != 0
    assert not resume_dir.exists()


def test_empty_resume_trash_physically_deletes_resumes_and_agent_sessions(
    client: TestClient,
) -> None:
    first_id = client.post(
        "/api/resumes",
        json={"title": "First"},
    ).json()["data"]["resume"]["id"]
    second_id = client.post(
        "/api/resumes",
        json={"title": "Second"},
    ).json()["data"]["resume"]["id"]
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO agent_sessions (id, resume_id, locale, title)
            VALUES (?, ?, 'en', 'Trash Session')
            """,
            (first_id, first_id),
        )

    client.post(f"/api/resumes/{first_id}/trash")
    client.post(f"/api/resumes/{second_id}/trash")

    response = client.delete("/api/resumes/trash")

    assert response.status_code == 200
    assert response.json()["data"]["deletedCount"] == 2
    assert not (get_settings().storage_dir / "resumes" / first_id).exists()
    assert not (get_settings().storage_dir / "resumes" / second_id).exists()
    with connect() as conn:
        resume_count = conn.execute(
            "SELECT COUNT(*) AS count FROM resumes",
        ).fetchone()["count"]
        session_count = conn.execute(
            "SELECT COUNT(*) AS count FROM agent_sessions",
        ).fetchone()["count"]

    assert resume_count == 0
    assert session_count == 0


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


def test_template_command_flow_owns_identity_and_lifecycle(
    client: TestClient,
) -> None:
    create_response = client.post(
        "/api/templates",
        json={"template": minimal_template_definition()},
    )

    assert create_response.status_code == 200
    created = create_response.json()["data"]["template"]
    template_id = created["id"]
    assert template_id != "template-client-id"
    assert re.fullmatch(r"template-[A-Za-z0-9]{16}", template_id)
    assert created["isBuiltIn"] is False

    update_payload = {**created, "name": "Backend Template"}
    update_response = client.put(
        f"/api/templates/{template_id}",
        json={"template": update_payload},
    )
    active_response = client.get("/api/templates")

    assert update_response.status_code == 200
    assert update_response.json()["data"]["template"]["name"] == "Backend Template"
    assert active_response.json()["data"]["templates"][0]["id"] == template_id

    default_response = client.put(
        "/api/workspace/default-template",
        json={"templateId": template_id},
    )
    trash_response = client.post(f"/api/templates/{template_id}/trash")
    bootstrap_response = client.get("/api/workspace/bootstrap?locale=en")
    deleted_response = client.get("/api/templates?status=deleted")
    set_deleted_default_response = client.put(
        "/api/workspace/default-template",
        json={"templateId": template_id},
    )

    assert default_response.status_code == 200
    assert default_response.json()["data"]["defaultTemplateId"] == template_id
    assert trash_response.status_code == 200
    assert trash_response.json()["data"]["template"]["deletedAt"]
    assert bootstrap_response.json()["data"]["defaultTemplateId"] == "minimal"
    assert deleted_response.json()["data"]["templates"][0]["id"] == template_id
    assert set_deleted_default_response.json()["code"] != 0

    restore_response = client.post(f"/api/templates/{template_id}/restore")

    assert restore_response.status_code == 200
    assert restore_response.json()["data"]["template"]["id"] == template_id

    client.post(f"/api/templates/{template_id}/trash")
    delete_response = client.delete(f"/api/templates/{template_id}")
    template_dir = get_settings().storage_dir / "templates" / template_id

    assert delete_response.status_code == 200
    assert delete_response.json()["data"]["id"] == template_id
    assert not template_dir.exists()


def test_empty_template_trash_physically_deletes_templates(
    client: TestClient,
) -> None:
    first_id = client.post(
        "/api/templates",
        json={"template": minimal_template_definition(name="First")},
    ).json()["data"]["template"]["id"]
    second_id = client.post(
        "/api/templates",
        json={"template": minimal_template_definition(name="Second")},
    ).json()["data"]["template"]["id"]

    client.post(f"/api/templates/{first_id}/trash")
    client.post(f"/api/templates/{second_id}/trash")

    response = client.delete("/api/templates/trash")

    assert response.status_code == 200
    assert response.json()["data"]["deletedCount"] == 2
    assert not (get_settings().storage_dir / "templates" / first_id).exists()
    assert not (get_settings().storage_dir / "templates" / second_id).exists()


def test_user_settings_endpoint_persists_json_preferences(
    client: TestClient,
) -> None:
    settings = {
        "theme": "system",
        "agentSettings": {
            "defaultModelId": "llm-settings",
            "responseLanguage": "zh",
            "behaviorMode": "strict",
            "confirmationMode": "suggestOnly",
            "autoRunMatch": True,
        },
    }

    response = client.put(
        "/api/workspace/user-settings?locale=zh",
        json={"settings": settings},
    )
    bootstrap_response = client.get("/api/workspace/bootstrap?locale=zh")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "agentSettings": {
            "defaultModelId": "llm-settings",
            "responseLanguage": "zh",
            "behaviorMode": "strict",
            "confirmationMode": "suggestOnly",
        },
        "locale": "zh",
        "theme": "system",
    }
    assert bootstrap_response.status_code == 200
    bootstrap_data = bootstrap_response.json()["data"]
    assert bootstrap_data["theme"] == "system"
    assert bootstrap_data["agentSettings"] == response.json()["data"]["agentSettings"]

    persisted_settings = json.loads(
        get_settings().user_settings_path.read_text(encoding="utf-8")
    )
    assert persisted_settings["agentSettings"] == response.json()["data"][
        "agentSettings"
    ]
    assert persisted_settings["locale"] == "zh"
    assert persisted_settings["theme"] == "system"


def test_identical_resume_hash_does_not_create_new_version(
    client: TestClient,
) -> None:
    create_response = client.post(
        "/api/resumes",
        json={
            "title": "Hash Stable",
            "resume": minimal_resume_item("ignored", "Hash Stable")["resume"],
            "template": "minimal",
        },
    )
    resume = create_response.json()["data"]["resume"]
    resume_id = resume["id"]
    save_payload = {
        **resume,
        "updatedAt": "2026-05-17T01:00:00.000Z",
        "templateSettings": None,
    }

    first_response = client.put(f"/api/resumes/{resume_id}", json=save_payload)
    second_response = client.put(f"/api/resumes/{resume_id}", json=save_payload)

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
            (resume_id,),
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
    model_config_id = response.json()["data"]["id"]
    delete_response = client.delete(f"/api/model-configs/{model_config_id}")
    empty_list_response = client.get("/api/model-configs")

    assert response.status_code == 200
    assert model_config_id != "llm-api"
    assert re.fullmatch(r"llm-[A-Za-z0-9]{16}", model_config_id)
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
            (model_config_id,),
        ).fetchone()

    assert row is not None
    assert row["encrypted_api_key"] != "sk-new-secret"
    assert row["api_key_preview"] == "sk-new****"
    assert row["enabled"] == 0


def test_model_config_resolves_litellm_token_limits(
    client: TestClient,
    monkeypatch,
) -> None:
    from app.services import model_metadata

    model_metadata._CATALOG_CACHE = None
    monkeypatch.setattr(
        model_metadata,
        "_fetch_catalog",
        lambda: {
            "openai/gpt-5.1": {
                "litellm_provider": "openai",
                "max_input_tokens": 131072,
                "max_output_tokens": 8192,
            },
        },
    )
    assert model_metadata.refresh_model_metadata_cache() is True

    response = client.post(
        "/api/model-configs",
        json={
            "id": "llm-token-limits",
            "provider": "openai",
            "nickname": "Token Limits",
            "apiKey": "sk-token-secret",
            "model": "gpt-5.1",
            "apiUrl": "https://api.openai.com/v1",
            "temperature": 0.4,
            "topP": 0.9,
            "maxTokens": 999999,
            "systemPrompt": "test",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] != "llm-token-limits"
    assert re.fullmatch(r"llm-[A-Za-z0-9]{16}", data["id"])
    assert data["contextWindowTokens"] == 131072
    assert data["maxTokens"] == 8192

    with connect() as conn:
        row = conn.execute(
            """
            SELECT max_tokens, context_window_tokens
            FROM llm_configs
            WHERE client_id = ?
            """,
            (data["id"],),
        ).fetchone()

    assert row is not None
    assert row["context_window_tokens"] == 131072
    assert row["max_tokens"] == 8192


def test_model_metadata_cache_is_prepared_before_config_save(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.services import model_metadata

    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    model_metadata._CATALOG_CACHE = None
    monkeypatch.setattr(
        model_metadata,
        "_fetch_catalog",
        lambda: {
            "openai/gpt-5.1": {
                "litellm_provider": "openai",
                "max_input_tokens": 131072,
                "max_output_tokens": 8192,
            },
        },
    )

    assert model_metadata.ensure_model_metadata_cache() is True
    assert (tmp_path / model_metadata.MODEL_METADATA_CACHE_NAME).exists()

    metadata = model_metadata.resolve_model_metadata("openai", "gpt-5.1")

    assert metadata is not None
    assert metadata.context_window_tokens == 131072
    assert metadata.max_output_tokens == 8192
    get_settings.cache_clear()


def test_model_metadata_cache_is_reused_without_refresh(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.services import model_metadata

    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    cache_path = tmp_path / model_metadata.MODEL_METADATA_CACHE_NAME
    cache_path.write_text(
        json.dumps(
            {
                "openai/gpt-5.1": {
                    "litellm_provider": "openai",
                    "max_input_tokens": 131072,
                    "max_output_tokens": 8192,
                },
            },
        ),
        encoding="utf-8",
    )
    model_metadata._CATALOG_CACHE = None

    def fail_fetch() -> dict[str, object]:
        raise AssertionError("cached model metadata should not refresh implicitly")

    monkeypatch.setattr(model_metadata, "_fetch_catalog", fail_fetch)

    assert model_metadata.ensure_model_metadata_cache() is True
    assert model_metadata.resolve_model_metadata("openai", "gpt-5.1") is not None
    get_settings.cache_clear()


def test_model_config_save_does_not_fetch_model_metadata(
    client: TestClient,
    monkeypatch,
) -> None:
    from app.services import model_metadata

    model_metadata._CATALOG_CACHE = {}

    def fail_fetch() -> dict[str, object]:
        raise AssertionError("model metadata fetch should not run during save")

    monkeypatch.setattr(model_metadata, "_fetch_catalog", fail_fetch)

    response = client.post(
        "/api/model-configs",
        json={
            "id": "llm-no-fetch",
            "provider": "openai",
            "nickname": "No Fetch",
            "apiKey": "sk-no-fetch-secret",
            "model": "unknown-model",
            "apiUrl": "https://api.openai.com/v1",
            "temperature": 0.4,
            "topP": 0.9,
            "maxTokens": 4096,
            "systemPrompt": "test",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["contextWindowTokens"] is None
    assert data["maxTokens"] == 4096


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
    model_config_id = first_response.json()["data"]["id"]
    assert model_config_id != "llm-noop"
    update_payload = {
        **payload,
        "id": model_config_id,
    }

    with connect() as conn:
        conn.execute(
            """
            UPDATE llm_configs
            SET updated_at = ?
            WHERE client_id = ?
            """,
            ("2000-01-01 00:00:00", model_config_id),
        )
        row_before = conn.execute(
            """
            SELECT encrypted_api_key, updated_at
            FROM llm_configs
            WHERE client_id = ?
            """,
            (model_config_id,),
        ).fetchone()

    second_response = client.post("/api/model-configs", json=update_payload)

    assert second_response.status_code == 200

    with connect() as conn:
        row_after = conn.execute(
            """
            SELECT encrypted_api_key, updated_at
            FROM llm_configs
            WHERE client_id = ?
            """,
            (model_config_id,),
        ).fetchone()

    assert row_before is not None
    assert row_after is not None
    assert row_after["encrypted_api_key"] == row_before["encrypted_api_key"]
    assert row_after["updated_at"] == row_before["updated_at"]


def test_agent_chat_guides_when_model_is_missing(client: TestClient) -> None:
    _, message = post_agent_chat_stream(
        client,
        {
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
        },
    )

    assert "No usable model configuration" in message["text"]
    assert message["edits"] == []
    assert message["tools"] == []


def test_agent_chat_persists_and_loads_session(client: TestClient) -> None:
    _, response_message = post_agent_chat_stream(
        client,
        {
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
        },
    )
    session_response = client.get("/api/agent/resumes/resume-test/session")

    assert session_response.status_code == 200
    session_data = session_response.json()["data"]
    messages = session_data["messages"]
    assert session_data["resumeId"] == "resume-test"
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[0]["id"] == "agent-user-session-1"
    assert messages[0]["text"] == "帮我检查项目经历"
    assert messages[1]["response"]["role"] == "assistant"
    assert messages[1]["response"]["text"] == response_message["text"]


def test_agent_session_put_replaces_persisted_messages(
    client: TestClient,
) -> None:
    first_response = client.put(
        "/api/agent/resumes/resume-edit/session",
        json={
            "locale": "zh",
            "messages": [
                {
                    "id": "agent-user-original",
                    "role": "user",
                    "text": "原来的问题",
                },
                {
                    "id": "agent-assistant-original",
                    "role": "assistant",
                    "text": "原来的回答",
                    "response": {
                        "id": "agent-assistant-original",
                        "role": "assistant",
                        "text": "原来的回答",
                        "quickReplies": ["继续"],
                    },
                },
                {
                    "id": "agent-user-tail",
                    "role": "user",
                    "text": "后续问题",
                },
            ],
        },
    )
    second_response = client.put(
        "/api/agent/resumes/resume-edit/session",
        json={
            "locale": "zh",
            "messages": [
                {
                    "id": "agent-user-original",
                    "role": "user",
                    "text": "修改后的问题",
                },
            ],
        },
    )

    assert first_response.status_code == 200
    first_messages = first_response.json()["data"]["messages"]
    assert [message["id"] for message in first_messages] == [
        "agent-user-original",
        "agent-assistant-original",
        "agent-user-tail",
    ]
    assert first_messages[1]["response"]["quickReplies"] == ["继续"]

    assert second_response.status_code == 200
    second_messages = second_response.json()["data"]["messages"]
    assert [message["id"] for message in second_messages] == [
        "agent-user-original",
    ]
    assert second_messages[0]["text"] == "修改后的问题"

    with connect() as conn:
        stored_count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM agent_messages
            WHERE session_id = 'resume-edit'
            """,
        ).fetchone()["count"]

    assert stored_count == 1


def test_agent_messages_include_compressed_history_and_latest_draft() -> None:
    config = AgentLlmConfig(
        client_id="llm-test",
        name="Test Model",
        provider="openai",
        model="gpt-test",
        base_url="https://example.test/v1",
        api_key="sk-test",
        temperature=0.4,
        top_p=0.9,
        max_tokens=None,
        timeout_seconds=60,
        system_prompt="",
        context_window_tokens=1600,
    )
    conversation = [
        {
            "id": "agent-user-0",
            "role": "user",
            "text": "先帮我写一个项目经历草稿",
        },
        {
            "id": "agent-assistant-draft",
            "role": "assistant",
            "text": "已生成项目经历草稿。",
            "response": {
                "id": "agent-assistant-draft",
                "role": "assistant",
                "text": "已生成项目经历草稿。",
                "actions": ["execute"],
                "edits": [
                    {
                        "id": "edit-project-1",
                        "title": "新增项目经历模块",
                        "target": "sections.project",
                        "reason": "根据用户提供的项目经历生成草稿。",
                        "status": "executed",
                        "operation": {
                            "type": "insert_section",
                            "sectionId": "project",
                        },
                    },
                ],
            },
        },
    ]
    conversation.extend(
        {
            "id": f"agent-user-followup-{index}",
            "role": "user",
            "text": f"后续补充 {index}",
        }
        for index in range(8)
    )
    conversation.append(
        {
            "id": "agent-user-current",
            "role": "user",
            "text": "把刚才那个版本的第二条再短一点",
        },
    )
    request = AgentChatRequest(
        prompt="把刚才那个版本的第二条再短一点",
        messages=conversation,
        conversation=conversation,
        files=[],
        locale="zh",
        resume={"basic": {"name": "王小明"}, "sections": []},
        draftState={
            "id": "draft-current",
            "status": "pending",
            "sourceMessageId": "agent-assistant-draft",
            "resume": {
                "basic": {"name": "王小明", "summary": "草稿简介"},
                "sections": [
                    {
                        "id": "project",
                        "kind": "project",
                        "customTitle": "项目经历",
                        "items": [
                            {
                                "id": "project-item-1",
                                "title": "ResuMate",
                                "subtitle": "AI 简历编辑器",
                            },
                        ],
                    },
                ],
            },
            "editCount": 1,
            "edits": [
                {
                    "id": "edit-project-1",
                    "title": "新增项目经历模块",
                    "target": "sections.project",
                    "reason": "根据用户提供的项目经历生成草稿。",
                    "status": "executed",
                    "operation": {
                        "type": "insert_section",
                        "sectionId": "project",
                    },
                },
            ],
            "diffs": [
                {
                    "id": "diff-project-1",
                    "operationId": "edit-project-1",
                    "path": "sections.project",
                    "kind": "added",
                    "label": "新增项目经历模块",
                    "after": "ResuMate",
                },
            ],
        },
        jobBrief="",
        keywordMatch={"matched": [], "missing": [], "score": 0},
        appliedActions=["execute"],
        modelConfig=None,
        settings={},
    )

    messages = build_agent_messages(request, config, mode="tools")
    payload = json.loads(messages[1]["content"])
    context = payload["conversationContext"]

    assert context["compression"]["applied"] is True
    assert context["compression"]["inputBudgetTokens"] < context["totalMessages"] * 200
    assert context["compressedMessageCount"] > 0
    assert context["exactMessageCount"] == len(payload["conversation"])
    assert context["totalMessages"] == len(conversation)
    assert context["latestDraft"]["messageId"] == "agent-assistant-draft"
    assert context["latestDraft"]["editCount"] == 1
    assert context["latestDraft"]["edits"][0]["title"] == "新增项目经历模块"
    assert context["latestDraft"]["edits"][0]["sectionId"] == "project"
    assert context["currentDraft"]["id"] == "draft-current"
    assert context["currentDraft"]["status"] == "pending"
    assert context["currentDraft"]["diffs"][0]["after"] == "ResuMate"
    assert context["activeDraft"]["id"] == "draft-current"
    assert payload["resume"]["sections"][0]["id"] == "project"
    assert context["appliedActions"] == ["execute"]
    assert any(
        item.get("assistantState", {}).get("editCount") == 1
        for item in context["olderSummary"]
    )


def test_agent_executor_analyzes_pending_draft_resume() -> None:
    request = AgentChatRequest(
        prompt="继续修改刚才的草稿",
        messages=[],
        conversation=[],
        files=[],
        locale="zh",
        resume={"basic": {"name": "王小明"}, "sections": []},
        draftState={
            "id": "draft-current",
            "status": "pending",
            "resume": {
                "basic": {
                    "name": "王小明",
                    "summary": "草稿里的个人简介",
                },
                "sections": [
                    {
                        "id": "project",
                        "kind": "project",
                        "customTitle": "项目经历",
                        "items": [
                            {
                                "id": "project-item-1",
                                "title": "ResuMate",
                                "subtitle": "AI 简历编辑器",
                                "description": "支持草稿预览和多轮修改。",
                            },
                        ],
                    },
                ],
            },
        },
        jobBrief="",
        keywordMatch={"matched": [], "missing": [], "score": 0},
        appliedActions=[],
        modelConfig=None,
        settings={},
    )

    analysis = AgentPlanExecutor(request).analyze_resume()

    assert analysis.summary == "草稿里的个人简介"
    assert [section["id"] for section in analysis.sections] == ["project"]


def test_agent_resume_lookup_finds_target_item() -> None:
    request = AgentChatRequest(
        prompt="缩短 ResuMate 项目",
        locale="zh",
        resume={
            "basic": {"name": "王小明"},
            "sections": [
                {
                    "id": "project",
                    "kind": "project",
                    "layout": "timeline",
                    "items": [
                        {
                            "id": "project-1",
                            "title": "ResuMate",
                            "subtitle": "AI 简历编辑器",
                            "meta": "React",
                            "period": "2026",
                            "description": "支持多轮 Agent 草稿编辑。",
                            "highlights": ["实现可预览、可撤回的简历草稿。"],
                        },
                    ],
                },
            ],
        },
    )
    runner = AgentToolRunner(AgentPlanExecutor(request))

    tool, result = runner._run_local_tool(
        tool_call("call-lookup", "resume_lookup", {"query": "ResuMate"}),
    )

    assert tool.title == "resume_lookup"
    assert result["output"]["sectionCount"] == 1
    assert result["output"]["itemCount"] == 1
    assert result["output"]["items"][0]["id"] == "project-1"
    assert result["output"]["items"][0]["sectionId"] == "project"


def test_agent_edit_move_item_generates_incremental_draft_edits() -> None:
    request = AgentChatRequest(
        prompt="把项目移动到其他经历",
        locale="zh",
        resume={
            "basic": {"name": "王小明"},
            "sections": [
                {
                    "id": "project",
                    "kind": "project",
                    "layout": "timeline",
                    "items": [
                        {
                            "id": "project-1",
                            "title": "ResuMate",
                            "subtitle": "前端开发",
                            "meta": "React",
                            "period": "2026",
                            "description": "",
                            "highlights": ["实现 Agent 草稿预览。"],
                        },
                    ],
                },
                {
                    "id": "other",
                    "kind": "other",
                    "layout": "list",
                    "items": [],
                },
            ],
        },
    )
    runner = AgentToolRunner(AgentPlanExecutor(request))

    tool, result = runner._run_local_tool(
        tool_call(
            "call-move",
            "edit_move_item",
            {
                "fromSectionId": "project",
                "toSectionId": "other",
                "itemId": "project-1",
                "reason": "用户要求移动该项目条目。",
            },
        ),
    )

    assert tool.title == "edit_move_item"
    assert tool.state == "output-available"
    assert result["output"]["editCount"] == 2
    assert [edit.operation["type"] for edit in runner.edits] == [
        "insert_item",
        "delete_item",
    ]
    project_items = runner.draft_resume["sections"][0]["items"]
    other_items = runner.draft_resume["sections"][1]["items"]
    assert project_items == []
    assert other_items[0]["id"] == "project-1"


def test_agent_draft_rewrite_uses_pending_draft_resume() -> None:
    request = AgentChatRequest(
        prompt="把刚才草稿里的项目描述再短一点",
        locale="zh",
        resume={"basic": {"name": "王小明"}, "sections": []},
        draftState={
            "id": "draft-current",
            "status": "pending",
            "resume": {
                "basic": {"name": "王小明"},
                "sections": [
                    {
                        "id": "project",
                        "kind": "project",
                        "layout": "timeline",
                        "items": [
                            {
                                "id": "project-1",
                                "title": "ResuMate",
                                "subtitle": "前端开发",
                                "description": "支持复杂的 Agent 草稿编辑流程。",
                                "highlights": ["实现可预览、可应用、可撤回草稿。"],
                            },
                        ],
                    },
                ],
            },
        },
    )
    runner = AgentToolRunner(AgentPlanExecutor(request))

    tool, result = runner._run_local_tool(
        tool_call(
            "call-rewrite",
            "draft_rewrite",
            {
                "edits": [
                    {
                        "title": "缩短项目描述",
                        "target": "sections.project.items.project-1",
                        "reason": "用户要求缩短上一版草稿。",
                        "operation": {
                            "type": "update_item",
                            "sectionId": "project",
                            "itemId": "project-1",
                            "patch": {"description": "支持 Agent 草稿编辑。"},
                        },
                    },
                ],
            },
        ),
    )

    item = runner.draft_resume["sections"][0]["items"][0]
    assert tool.title == "draft_rewrite"
    assert result["output"]["editCount"] == 1
    assert item["description"] == "支持 Agent 草稿编辑。"


def test_agent_chat_supports_json(client: TestClient, monkeypatch) -> None:
    model_config = create_agent_model_config(client)
    monkeypatch.setattr(
        "app.services.agent.complete_chat_stream",
        stub_stream_text(
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

    _, message = post_agent_chat_stream(
        client,
        {
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
        },
    )

    assert message["role"] == "assistant"
    assert message["text"] == "Real model response"
    assert message["actions"]
    assert message["tools"]
    assert message["sources"]
    assert message["edits"]
    assert message["quickReplies"]
    assert any(
        source["sourceType"] == "jobBrief" for source in message["sources"]
    )
    assert any(
        source["sourceType"] == "attachment"
        and source["excerpt"] == "TypeScript JD attachment text"
        for source in message["sources"]
    )
    assert not any(
        source["sourceType"] in {"resume", "system"}
        for source in message["sources"]
    )
    assert message["edits"][0]["status"] == "executed"
    assert message["edits"][0]["operation"]["type"] == "replace_field"
    assert any(
        tool["title"] == "jd_reference_search" for tool in message["tools"]
    )


def test_agent_chat_executes_model_selected_item_edit_without_jd_search(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    monkeypatch.setattr(
        "app.services.agent.complete_chat_stream",
        stub_stream_text('{"text":"已生成项目经历修改草稿"}'),
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

    _, message = post_agent_chat_stream(
        client,
        {
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
        },
    )

    tool_titles = [tool["title"] for tool in message["tools"]]
    assert tool_titles == ["edit_execute"]
    observations = message["tools"][0]["output"]["observations"]
    assert observations[0]["target"] == "sections.project.items.project-1"
    assert observations[0]["before"]["description"] == "负责推荐算法迭代。"
    assert (
        observations[0]["after"]["description"] == "负责推荐链路优化，点击率提升 12%。"
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
        "app.services.agent.complete_chat_stream",
        stub_stream_text('{"text":"已生成项目经历草稿"}'),
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

    _, message = post_agent_chat_stream(
        client,
        {
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
        },
    )

    tool_titles = [tool["title"] for tool in message["tools"]]
    assert tool_titles == ["resume_analysis", "edit_plan", "edit_execute"]
    assert message["edits"]
    observations = message["tools"][2]["output"]["observations"]
    assert observations[0]["before"] is None
    assert "电商后台管理系统" in observations[0]["after"]
    assert "2023.03 - 2023.06" in observations[0]["after"]
    assert "sectionCount" not in json.dumps(observations, ensure_ascii=False)
    operation = message["edits"][0]["operation"]
    assert operation["type"] == "insert_section"
    assert operation["section"]["kind"] == "project"
    assert operation["section"]["customTitle"] == ""
    assert operation["section"]["items"][0]["title"] == "电商后台管理系统"
    assert operation["section"]["items"][0]["period"] == "2023.03 - 2023.06"
    assert operation["section"]["items"][0]["description"] == ""
    assert operation["section"]["items"][0]["highlights"] == [
        "负责 Spring Boot、MySQL、Redis、Docker 和 SQL 优化",
    ]
    assert "帮我" not in json.dumps(operation, ensure_ascii=False)
    assert "项目名称" not in json.dumps(
        operation["section"]["items"][0]["highlights"],
        ensure_ascii=False,
    )


def test_agent_chat_normalizes_model_inserted_resume_fields(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    prompt = (
        "帮我添加项目经历：项目名称：电商后台管理系统 时间：2023.03 - 2023.06 "
        "角色：后端开发 技术栈：Spring Boot, MySQL, Redis, Docker 工作内容："
        "设计并实现订单模块，通过 SQL 优化将查询时间从 2s 降至 0.3s。"
    )
    monkeypatch.setattr(
        "app.services.agent.complete_chat_stream",
        stub_stream_text('{"text":"已生成项目经历草稿"}'),
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
                                "title": "新增项目经历",
                                "target": "sections",
                                "reason": "用户提供的是项目内容，应归入项目经历。",
                                "operation": {
                                    "type": "insert_section",
                                    "section": {
                                        "section_type": "custom",
                                        "layout": "timeline",
                                        "customTitle": "岗位相关项目",
                                        "items": [
                                            {
                                                "title": "电商后台管理系统",
                                                "subtitle": "后端开发",
                                                "meta": (
                                                    "Spring Boot, MySQL, Redis, Docker"
                                                ),
                                                "period": "2023.03 - 2023.06",
                                                "description": (
                                                    "项目名称：电商后台管理系统 时间："
                                                    "2023.03 - 2023.06 角色：后端开发 "
                                                    "技术栈：Spring Boot, MySQL, "
                                                    "Redis, Docker"
                                                ),
                                                "highlights": [
                                                    (
                                                        "项目名称：电商后台管理系统 "
                                                        "时间：2023.03 - 2023.06 "
                                                        "角色：后端开发"
                                                    ),
                                                    (
                                                        "工作内容：设计并实现订单模块，"
                                                        "通过 SQL 优化将查询时间从 "
                                                        "2s 降至 0.3s"
                                                    ),
                                                ],
                                            },
                                        ],
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
                        "reason": "Observation shows the project section was added.",
                    },
                ),
            ],
        ),
    )

    _, message = post_agent_chat_stream(
        client,
        {
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
        },
    )

    operation = message["edits"][0]["operation"]
    section = operation["section"]
    item = section["items"][0]
    assert section["kind"] == "project"
    assert section["customTitle"] == ""
    assert item["title"] == "电商后台管理系统"
    assert item["subtitle"] == "后端开发"
    assert item["meta"] == "Spring Boot, MySQL, Redis, Docker"
    assert item["period"] == "2023.03 - 2023.06"
    assert item["description"] == ""
    assert item["highlights"] == [
        "设计并实现订单模块，通过 SQL 优化将查询时间从 2s 降至 0.3s",
    ]


def test_agent_section_registry_drives_schema_and_prompt() -> None:
    assert tool_registry.SECTION_KIND_ENUM == SECTION_KIND_ENUM
    assert (
        f"Allowed section_type values are: {', '.join(SECTION_KIND_ENUM)}."
        in EDIT_OPERATION_GUIDE
    )
    assert (
        f"允许的 section_type 值是：{', '.join(SECTION_KIND_ENUM)}。"
        in EDIT_OPERATION_GUIDES["zh"]
    )
    for kind in SECTION_KIND_ENUM:
        assert f"- {kind}:" in EDIT_OPERATION_GUIDE
        assert f"- {kind}:" in EDIT_OPERATION_GUIDES["zh"]


def test_agent_fine_grained_tools_are_registered() -> None:
    tool_names = {
        schema["function"]["name"] for schema in tool_registry.AGENT_TOOL_SCHEMAS
    }

    assert {
        "resume_lookup",
        "draft_diff_summary",
        "edit_move_item",
        "edit_split_item",
        "edit_merge_items",
        "skills_classify",
        "draft_rewrite",
    } <= tool_names


def test_agent_edit_operation_schema_requires_operation_specific_fields() -> None:
    variants = tool_registry.OPERATION_SCHEMA["oneOf"]
    by_type = {
        variant["properties"]["type"]["enum"][0]: variant for variant in variants
    }

    assert set(by_type) == {
        "replace_field",
        "update_item",
        "insert_item",
        "update_section",
        "insert_section",
        "delete_item",
        "delete_section",
        "reorder_sections",
        "reorder_items",
    }
    assert set(by_type["replace_field"]["required"]) == {"type", "path", "value"}
    assert set(by_type["insert_section"]["required"]) == {"type", "section"}
    assert set(by_type["update_section"]["required"]) == {
        "type",
        "sectionId",
        "patch",
    }
    assert set(by_type["update_item"]["required"]) == {
        "type",
        "sectionId",
        "itemId",
        "patch",
    }
    assert set(by_type["reorder_items"]["required"]) == {
        "type",
        "sectionId",
        "itemIds",
    }


def test_agent_section_registry_matches_local_contract() -> None:
    assert [section["kind"] for section in SECTION_REGISTRY] == SECTION_KIND_ENUM
    assert {
        section["kind"]: section["defaultLayout"] for section in SECTION_REGISTRY
    } == SECTION_DEFAULT_LAYOUTS


def test_agent_chat_accepts_other_section_kind() -> None:
    assert "other" in SECTION_KIND_ENUM

    edits = _model_edit_suggestions(
        {"basic": {"name": "姓名", "summary": ""}, "sections": []},
        [
            {
                "title": "新增其他经历",
                "target": "sections",
                "reason": "用户提供的内容适合放入其他经历。",
                "operation": {
                    "type": "insert_section",
                    "section": {
                        "section_type": "other",
                        "layout": "list",
                        "customTitle": "其他经历",
                        "items": [
                            {
                                "title": "开源贡献",
                                "subtitle": "",
                                "meta": "",
                                "period": "",
                                "description": "",
                                "highlights": ["维护项目文档"],
                            },
                        ],
                    },
                },
            },
        ],
        locale="zh",
    )

    assert edits
    section = edits[0].operation["section"]
    assert section["kind"] == "other"
    assert section["customTitle"] == ""
    assert section["layout"] == "list"
    assert section["items"][0]["title"] == "开源贡献"


def test_agent_chat_plain_message_does_not_return_tools(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    monkeypatch.setattr(
        "app.services.agent.complete_chat_tool_call",
        lambda *_: LlmToolCallResponse(
            content="你好，我可以回答简历相关问题。",
            tool_calls=[],
        ),
    )
    monkeypatch.setattr(
        "app.services.agent.complete_chat_stream",
        stub_stream_text("你好，我可以回答简历相关问题。"),
    )

    _, message = post_agent_chat_stream(
        client,
        {
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
        },
    )

    assert message["text"] == "你好，我可以回答简历相关问题。"
    assert message["tools"] == []
    assert message["edits"] == []
    assert message["actions"] == []


def test_agent_chat_plain_stream_uses_final_completion(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    monkeypatch.setattr(
        "app.services.agent.complete_chat_tool_call",
        lambda *_: LlmToolCallResponse(
            content="工具选择阶段的半截回答",
            tool_calls=[],
        ),
    )

    def stream_response(*_: object) -> object:
        yield LlmStreamDelta(kind="text", delta="最终")
        yield LlmStreamDelta(kind="text", delta="完整回答")

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
    assert "最终完整回答" in body
    assert "工具选择阶段的半截回答" not in body


def test_agent_chat_finish_blocked_without_visible_tools_returns_message(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)

    def unexpected_final_completion(*_: object) -> str:
        raise AssertionError("finish-only responses should not call final completion")

    monkeypatch.setattr("app.services.agent.complete_chat", unexpected_final_completion)
    monkeypatch.setattr(
        "app.services.agent.complete_chat_tool_call",
        stub_tool_call_batches(
            [
                tool_call(
                    "call-finish",
                    "finish",
                    {
                        "status": "blocked",
                        "reason": "缺少要修改的目标模块或条目。",
                    },
                ),
            ],
        ),
    )

    _, message = post_agent_chat_stream(
        client,
        {
            "prompt": "帮我修改简历",
            "message": {"role": "user", "text": "帮我修改简历"},
            "messages": [{"role": "user", "text": "帮我修改简历"}],
            "conversation": [{"role": "user", "text": "帮我修改简历"}],
            "files": [],
            "locale": "zh",
            "resume": {"basic": {"name": "王小明"}, "sections": []},
            "jobBrief": "",
            "keywordMatch": {"matched": [], "missing": [], "score": 0},
            "appliedActions": [],
            "modelConfig": model_config,
            "settings": {},
        },
    )

    assert "不能生成可靠" in message["text"]
    assert "缺少要修改的目标模块或条目" in message["text"]
    assert message["tools"] == []
    assert message["edits"] == []


def test_agent_chat_reports_invalid_model_edit_operation(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)

    def unexpected_final_completion(*_: object) -> str:
        raise AssertionError("terminal loop text should not call final completion")

    monkeypatch.setattr("app.services.agent.complete_chat", unexpected_final_completion)
    monkeypatch.setattr(
        "app.services.agent.complete_chat_tool_call",
        stub_tool_call_responses(
            LlmToolCallResponse(
                content="",
                tool_calls=[
                    tool_call(
                        "call-execute",
                        "edit_execute",
                        {
                            "edits": [
                                {
                                    "title": "补充项目结果",
                                    "target": "sections.project.items.project-1",
                                    "reason": "用户要求补强项目。",
                                    "operation": {
                                        "type": "update_item",
                                        "sectionId": "project",
                                        "patch": {
                                            "highlights": ["补充可验证业务结果"],
                                        },
                                    },
                                },
                            ],
                        },
                    ),
                ],
            ),
            LlmToolCallResponse(
                content="需要补充 itemId 后才能继续生成可预览草稿。",
                tool_calls=[],
            ),
        ),
    )

    _, message = post_agent_chat_stream(
        client,
        {
            "prompt": "补强项目结果",
            "message": {"role": "user", "text": "补强项目结果"},
            "messages": [{"role": "user", "text": "补强项目结果"}],
            "conversation": [{"role": "user", "text": "补强项目结果"}],
            "files": [],
            "locale": "zh",
            "resume": {
                "basic": {"name": "王小明", "summary": "前端开发。"},
                "sections": [
                    {
                        "id": "project",
                        "kind": "project",
                        "layout": "timeline",
                        "customTitle": "",
                        "items": [
                            {
                                "id": "project-1",
                                "title": "后台系统",
                                "subtitle": "前端开发",
                                "meta": "React",
                                "period": "2025",
                                "description": "",
                                "highlights": ["负责列表页开发"],
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
        },
    )

    tool = message["tools"][0]
    rejected_edit = tool["output"]["rejectedEdits"][0]
    assert message["text"] == "需要补充 itemId 后才能继续生成可预览草稿。"
    assert message["edits"] == []
    assert tool["state"] == "output-error"
    assert tool["output"]["rejectedEditCount"] == 1
    assert "itemId" in rejected_edit["reason"]
    assert "没有可执行的修改被接受" in tool["errorText"]


def test_agent_model_error_does_not_return_llm_tool(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)

    def raise_provider_error(*_: object) -> str:
        raise LlmRequestError("provider unavailable")

    monkeypatch.setattr(
        "app.services.agent.complete_chat_tool_call",
        raise_provider_error,
    )

    _, message = post_agent_chat_stream(
        client,
        {
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
        },
    )

    assert "调用模型失败" in message["text"]
    assert "provider unavailable" in message["text"]
    assert message["tools"] == []


def test_agent_chat_uses_provided_jd_url(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    monkeypatch.setattr(
        "app.services.agent.complete_chat_stream",
        stub_stream_text('{"text":"Real model response for JD URL"}'),
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

    _, message = post_agent_chat_stream(
        client,
        {
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
        },
    )

    assert any(tool["title"] == "jd_url_fetch" for tool in message["tools"])
    assert message["sources"] == [
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
        for edit in message["edits"]
    )


def test_agent_chat_cleans_chinese_target_role(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    monkeypatch.setattr(
        "app.services.agent.complete_chat_stream",
        stub_stream_text('{"text":"已分析目标岗位"}'),
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

    _, message = post_agent_chat_stream(
        client,
        {
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
        },
    )

    jd_tool = next(
        tool for tool in message["tools"] if tool["title"] == "jd_reference_search"
    )
    assert jd_tool["output"]["role"] == "AI应用开发"
    assert jd_tool["input"]["query"] == "AI应用开发 岗位 JD 职责 任职要求"
    assert message["knowledge"][0]["title"] == "AI应用开发"
    assert not any("的职位是" in suggestion for suggestion in message["suggestions"])


def test_agent_chat_streams_tool_and_source_metadata(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    monkeypatch.setattr(
        "app.services.agent._async_search_jd_reference",
        async_stub_jd_search,
    )
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


def test_agent_chat_streams_finish_blocked_without_visible_tools(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)

    def unexpected_stream(*_: object) -> object:
        raise AssertionError("finish-only responses should not stream final completion")

    monkeypatch.setattr("app.services.agent.complete_chat_stream", unexpected_stream)
    monkeypatch.setattr(
        "app.services.agent.complete_chat_tool_call",
        stub_tool_call_batches(
            [
                tool_call(
                    "call-finish",
                    "finish",
                    {
                        "status": "blocked",
                        "reason": "缺少真实经历内容。",
                    },
                ),
            ],
        ),
    )

    with client.stream(
        "POST",
        "/api/agent/chat",
        headers={"accept": "text/event-stream"},
        json={
            "prompt": "帮我生成项目经历",
            "message": {"role": "user", "text": "帮我生成项目经历"},
            "messages": [{"role": "user", "text": "帮我生成项目经历"}],
            "conversation": [{"role": "user", "text": "帮我生成项目经历"}],
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
    message = json.loads(message_done_data)["message"]
    assert "不能生成可靠" in message["text"]
    assert "缺少真实经历内容" in message["text"]
    assert message["tools"] == []
    assert message["edits"] == []


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
    assert [part["toolIds"] for part in timeline if part["type"] == "tool_group"] == [
        ["call-analysis"],
        ["call-plan"],
    ]


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
        "text",
    ]
    assert [part["toolIds"] for part in timeline if part["type"] == "tool_group"] == [
        ["call-analysis", "call-jd"]
    ]


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
    assert [part["type"] for part in timeline] == ["tool_group", "text"]
    assert timeline[0]["toolIds"] == [
        "call-jd",
        "call-analysis",
        "call-plan",
        "call-execute",
    ]


def test_agent_chat_streams_plain_model_tokens(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    monkeypatch.setattr(
        "app.services.agent.complete_chat_tool_call",
        lambda *_: LlmToolCallResponse(
            content="你好，我可以帮你看简历。",
            tool_calls=[],
        ),
    )

    def stream_response(*_: object) -> object:
        yield LlmStreamDelta(kind="text", delta="你好，")
        yield LlmStreamDelta(kind="text", delta="我可以帮你看简历。")

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
    assert "event: text_delta" in body
    assert "你好，我可以帮你看简历。" in body
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
    resume = response.json()["data"]["resumes"][0]
    assert re.fullmatch(r"[A-Za-z0-9]{16}", resume["id"])
    assert resume["resume"]["basic"]["name"] == "Avery"


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

    create_response = client.post(
        "/api/resumes",
        json={
            "title": "Export Resume",
            "resume": minimal_resume_item(title="Export Resume")["resume"],
            "template": "minimal",
        },
    )
    assert create_response.status_code == 200
    resume_id = create_response.json()["data"]["resume"]["id"]

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
