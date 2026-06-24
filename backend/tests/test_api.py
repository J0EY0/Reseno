import asyncio
import json
import re
from pathlib import Path

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app import config as app_config
from app.agent_locales import DEFAULT_AGENT_LOCALE, SUPPORTED_AGENT_LOCALES
from app.config import get_settings
from app.db.connection import connect
from app.schemas.agent import AgentChatRequest
from app.schemas.exports import ExportResumePdfRequest
from app.services.agent import WebReference, WebSearchReference, WebSearchResult
from app.services.agent.editing.operations import (
    _model_edit_suggestions,
    _model_edit_suggestions_with_diagnostics,
)
from app.services.agent.executor import AgentPlanExecutor
from app.services.agent.integrations import web as agent_web
from app.services.agent.intent_patterns import (
    INTENT_PATTERN_FILE,
    matches_intent_pattern,
)
from app.services.agent.localization import (
    TEXT as AGENT_LOCALIZED_TEXT,
)
from app.services.agent.localization import (
    supported_agent_text_locales,
)
from app.services.agent.parsing_patterns import (
    PARSING_PATTERN_FILE,
    matches_agent_pattern,
)
from app.services.agent.policy import (
    AgentCapabilityMode,
    AgentTaskIntent,
    capability_policy_for_request,
)
from app.services.agent.prompts import (
    EDIT_OPERATION_GUIDE,
    EDIT_OPERATION_GUIDES,
    FINAL_RESPONSE_PROMPTS,
    STREAMING_FINAL_RESPONSE_PROMPTS,
    SYSTEM_PROMPTS,
)
from app.services.agent.runtime.context import AgentRuntimeContext
from app.services.agent.runtime.messages import build_agent_messages
from app.services.agent.section_registry import (
    SECTION_DEFAULT_LAYOUTS,
    SECTION_KIND_ENUM,
    SECTION_REGISTRY,
)
from app.services.agent.tools import registry as tool_registry
from app.services.agent.tools.runner import AgentToolRunner
from app.services.auth_tokens import create_access_token
from app.services.llm_client import (
    AgentLlmConfig,
    LlmRequestError,
    LlmStreamDelta,
    LlmToolCall,
    LlmToolCallResponse,
)
from app.services.model_discovery_cache import (
    MODEL_DISCOVERY_CACHE_NAME,
    write_cached_provider_models,
)
from app.services.model_providers import DiscoveredModel


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
            "providerKind": "custom",
            "apiFamily": "openai_compatible_chat",
            "nickname": "Agent Model",
            "apiKey": "sk-agent-secret",
            "model": "gpt-5.1",
            "apiUrl": "https://api.openai.com/v1",
            "temperature": 0.4,
            "topP": 0.9,
            "maxTokens": 1200,
        },
    )
    assert response.status_code == 200
    return response.json()["data"]


def test_model_provider_manifest_includes_local_runtimes(
    client: TestClient,
) -> None:
    response = client.get("/api/model-providers")

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    providers = payload["data"]["providers"]
    provider_ids = [provider["id"] for provider in providers]

    assert "ollama" in provider_ids
    assert "vllm" in provider_ids
    assert "sglang" in provider_ids
    assert "local" not in provider_ids

    ollama = next(provider for provider in providers if provider["id"] == "ollama")
    assert ollama["label"] == "Ollama"
    assert ollama["kind"] == "local"
    assert ollama["supportsModelDiscovery"] is False


def test_model_provider_manifest_includes_requested_cloud_providers(
    client: TestClient,
) -> None:
    response = client.get("/api/model-providers")

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    providers = payload["data"]["providers"]
    providers_by_id = {provider["id"]: provider for provider in providers}

    assert providers_by_id["moonshot"]["label"] == "Moonshot AI"
    assert providers_by_id["moonshot"]["kind"] == "cloud"
    assert providers_by_id["glm"]["label"] == "Z.ai"
    assert providers_by_id["glm"]["kind"] == "cloud"
    assert providers_by_id["xai"]["label"] == "xAI"
    assert providers_by_id["xai"]["kind"] == "cloud"


def test_local_model_provider_does_not_offer_model_discovery(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/model-providers/discover-models",
        json={
            "provider": "ollama",
            "apiFamily": "openai_compatible_chat",
            "apiUrl": "http://localhost:11434/v1",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 40000
    assert payload["message"] == "MODEL_DISCOVERY_FAILED"


def test_deepseek_model_provider_discovers_from_deepseek_route(
    client: TestClient,
    monkeypatch,
) -> None:
    def fake_get_json(url: str, *, headers: dict[str, str]) -> dict:
        assert url == "https://api.deepseek.com/models"
        assert headers["Authorization"] == "Bearer sk-deepseek-secret"
        return {"data": [{"id": "deepseek-chat"}]}

    monkeypatch.setattr("app.services.model_providers._get_json", fake_get_json)

    response = client.post(
        "/api/model-providers/discover-models",
        json={
            "provider": "deepseek",
            "apiFamily": "openai_compatible_chat",
            "apiUrl": "https://api.deepseek.com",
            "apiKey": "sk-deepseek-secret",
            "refresh": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    assert payload["data"]["models"][0]["id"] == "deepseek-chat"


def test_model_provider_discovery_uses_manifest_routes_for_all_providers(
    client: TestClient,
    monkeypatch,
) -> None:
    class ForbiddenOpenAIClient:
        def __init__(self, *_: object, **__: object) -> None:
            raise AssertionError("Model discovery routes must be explicit.")

    expected_routes = {
        "openai": (
            "openai_responses",
            "https://api.openai.com/v1",
            "https://api.openai.com/v1/models",
        ),
        "anthropic": (
            "anthropic_messages",
            "https://api.anthropic.com/v1",
            "https://api.anthropic.com/v1/models",
        ),
        "google": (
            "google_gemini",
            "https://generativelanguage.googleapis.com/v1beta",
            "https://generativelanguage.googleapis.com/v1beta/models",
        ),
        "deepseek": (
            "openai_compatible_chat",
            "https://api.deepseek.com",
            "https://api.deepseek.com/models",
        ),
        "qwen": (
            "openai_compatible_chat",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "https://dashscope.aliyuncs.com/compatible-mode/v1/models",
        ),
        "minimax": (
            "openai_compatible_chat",
            "https://api.minimax.io/v1",
            "https://api.minimax.io/v1/models",
        ),
        "glm": (
            "openai_compatible_chat",
            "https://open.bigmodel.cn/api/paas/v4",
            "https://open.bigmodel.cn/api/paas/v4/models",
        ),
        "moonshot": (
            "openai_compatible_chat",
            "https://api.moonshot.ai/v1",
            "https://api.moonshot.ai/v1/models",
        ),
        "xai": (
            "openai_responses",
            "https://api.x.ai/v1",
            "https://api.x.ai/v1/models",
        ),
    }
    calls: list[tuple[str, dict[str, str]]] = []

    def fake_get_json(url: str, *, headers: dict[str, str]) -> dict:
        calls.append((url, dict(headers)))
        return {
            "data": [{"id": "test-chat"}],
            "models": [
                {
                    "name": "models/test-chat",
                    "supportedGenerationMethods": ["generateContent"],
                },
            ],
        }

    monkeypatch.setattr(
        "app.services.model_providers.OpenAI",
        ForbiddenOpenAIClient,
        raising=False,
    )
    monkeypatch.setattr("app.services.model_providers._get_json", fake_get_json)

    for provider_id, (api_family, api_url, expected_url) in expected_routes.items():
        payload = {
            "provider": provider_id,
            "apiFamily": api_family,
            "apiUrl": api_url,
            "refresh": True,
        }
        payload["apiKey"] = f"sk-{provider_id}-secret"

        response = client.post("/api/model-providers/discover-models", json=payload)

        assert response.status_code == 200
        assert response.json()["code"] == 0
        assert calls[-1][0] == expected_url
        headers = calls[-1][1]
        if provider_id == "anthropic":
            assert headers["x-api-key"] == payload["apiKey"]
            assert headers["anthropic-version"]
        elif provider_id == "google":
            assert headers["x-goog-api-key"] == payload["apiKey"]
        else:
            assert headers["Authorization"] == f"Bearer {payload['apiKey']}"


def test_model_provider_discovery_reads_cached_models_without_refresh(
    client: TestClient,
    monkeypatch,
) -> None:
    write_cached_provider_models(
        "deepseek",
        [
            DiscoveredModel(
                id="deepseek-cached",
                label="deepseek-cached",
                context_window_tokens=65536,
                max_output_tokens=4096,
                supports_image=False,
                supports_thinking=True,
                metadata_source="provider",
            ),
        ],
    )

    def fail_discovery(**_: object) -> list[DiscoveredModel]:
        raise AssertionError("cached discovery should not call provider")

    monkeypatch.setattr(
        "app.routers.model_providers.discover_provider_models",
        fail_discovery,
    )

    response = client.post(
        "/api/model-providers/discover-models",
        json={
            "provider": "deepseek",
            "apiFamily": "openai_compatible_chat",
            "apiUrl": "https://api.deepseek.com",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["source"] == "cache"
    assert data["models"][0]["id"] == "deepseek-cached"


def test_model_provider_discovery_refresh_writes_cache(
    client: TestClient,
    monkeypatch,
) -> None:
    def fake_discovery(**_: object) -> list[DiscoveredModel]:
        return [
            DiscoveredModel(
                id="deepseek-live",
                label="deepseek-live",
                context_window_tokens=131072,
                max_output_tokens=8192,
                supports_image=True,
                supports_thinking=True,
                metadata_source="provider",
            ),
        ]

    monkeypatch.setattr(
        "app.routers.model_providers.discover_provider_models",
        fake_discovery,
    )

    response = client.post(
        "/api/model-providers/discover-models",
        json={
            "provider": "deepseek",
            "apiFamily": "openai_compatible_chat",
            "apiUrl": "https://api.deepseek.com",
            "apiKey": "sk-deepseek-secret",
            "refresh": True,
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["source"] == "provider"
    assert data["models"][0]["id"] == "deepseek-live"
    assert (get_settings().data_dir / MODEL_DISCOVERY_CACHE_NAME).exists()

    def fail_discovery(**_: object) -> list[DiscoveredModel]:
        raise AssertionError("cache read should not call provider after refresh")

    monkeypatch.setattr(
        "app.routers.model_providers.discover_provider_models",
        fail_discovery,
    )

    cached_response = client.post(
        "/api/model-providers/discover-models",
        json={
            "provider": "deepseek",
            "apiFamily": "openai_compatible_chat",
            "apiUrl": "https://api.deepseek.com",
        },
    )

    assert cached_response.status_code == 200
    assert cached_response.json()["data"]["source"] == "cache"
    assert cached_response.json()["data"]["models"][0]["id"] == "deepseek-live"


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


def stub_web_search_summary(
    queries: list[str],
    max_results: int = 10,
) -> WebSearchReference:
    return WebSearchReference(
        query=queries[0],
        results=(
            WebSearchResult(
                title="AI Application Developer Responsibilities",
                url="https://example.test/roles/ai-application-developer",
                excerpt="AI application developers build LLM features and workflows.",
            ),
            WebSearchResult(
                title="AI Application Developer Skills",
                url="https://example.test/roles/ai-application-developer-skills",
                excerpt=(
                    "Common requirements include Python, APIs, evaluation, and RAG."
                ),
            ),
        ),
        query_count=len(queries),
        result_count=max_results,
    )


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
            "providerKind": "custom",
            "apiFamily": "openai_compatible_chat",
            "nickname": "API",
            "apiKey": "sk-new-secret",
            "model": "gpt-5.1",
            "apiUrl": "https://api.openai.com/v1",
            "temperature": 0.4,
            "topP": 0.9,
            "maxTokens": None,
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
            "providerKind": "custom",
            "apiFamily": "openai_compatible_chat",
            "nickname": "Token Limits",
            "apiKey": "sk-token-secret",
            "model": "gpt-5.1",
            "apiUrl": "https://api.openai.com/v1",
            "temperature": 0.4,
            "topP": 0.9,
            "maxTokens": 999999,
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


def test_cloud_model_config_stores_provider_defaults(
    client: TestClient,
) -> None:
    write_cached_provider_models(
        "openai",
        [
            DiscoveredModel(
                id="gpt-cloud",
                label="gpt-cloud",
                context_window_tokens=131072,
                max_output_tokens=8192,
                supports_image=True,
                supports_thinking=True,
                metadata_source="provider",
            ),
        ],
    )

    response = client.post(
        "/api/model-configs",
        json={
            "provider": "openai",
            "providerKind": "cloud",
            "apiFamily": "openai_responses",
            "nickname": "Cloud",
            "apiKey": "sk-cloud-secret",
            "model": "gpt-cloud",
            "apiUrl": "https://api.openai.com/v1",
            "temperature": 0.4,
            "topP": 0.9,
            "maxTokens": 4096,
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["temperature"] is None
    assert data["topP"] is None
    assert data["maxTokens"] is None
    assert data["contextWindowTokens"] == 131072
    assert data["supportsImage"] is True
    assert data["supportsThinking"] is True
    assert data["thinkingEnabled"] is True

    with connect() as conn:
        row = conn.execute(
            """
            SELECT temperature, top_p, max_tokens
            FROM llm_configs
            WHERE client_id = ?
            """,
            (data["id"],),
        ).fetchone()

    assert row is not None
    assert row["temperature"] is None
    assert row["top_p"] is None
    assert row["max_tokens"] is None


def test_local_model_config_stores_manual_capabilities(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/model-configs",
        json={
            "provider": "ollama",
            "providerKind": "local",
            "apiFamily": "openai_compatible_chat",
            "nickname": "Local Vision",
            "model": "llava:latest",
            "apiUrl": "http://localhost:11434/v1",
            "contextWindowTokens": 65536,
            "maxTokens": 4096,
            "supportsImage": True,
            "supportsThinking": True,
            "thinkingEnabled": True,
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["provider"] == "ollama"
    assert data["providerKind"] == "local"
    assert data["temperature"] is None
    assert data["topP"] is None
    assert data["contextWindowTokens"] == 65536
    assert data["maxTokens"] == 4096
    assert data["supportsImage"] is True
    assert data["supportsThinking"] is True
    assert data["thinkingEnabled"] is True


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
            "providerKind": "custom",
            "apiFamily": "openai_compatible_chat",
            "nickname": "No Fetch",
            "apiKey": "sk-no-fetch-secret",
            "model": "unknown-model",
            "apiUrl": "https://api.openai.com/v1",
            "temperature": 0.4,
            "topP": 0.9,
            "maxTokens": 4096,
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["contextWindowTokens"] == 32768
    assert data["maxTokens"] == 4096


def test_identical_model_config_does_not_update_row(client: TestClient) -> None:
    payload = {
        "id": "llm-noop",
        "provider": "openai",
        "providerKind": "custom",
        "apiFamily": "openai_compatible_chat",
        "nickname": "Noop",
        "apiKey": "sk-noop-secret",
        "model": "gpt-5.1",
        "apiUrl": "https://api.openai.com/v1",
        "temperature": 0.4,
        "topP": 0.9,
        "maxTokens": None,
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


def test_agent_messages_hide_personal_identity_from_model_payload() -> None:
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
        context_window_tokens=4096,
    )
    request = AgentChatRequest(
        prompt="帮王小明优化简介，电话 13800138000",
        messages=[
            {
                "id": "agent-user-1",
                "role": "user",
                "text": "王小明的邮箱是 xiaoming@example.com",
            },
        ],
        conversation=[],
        files=[
            {
                "filename": "note.txt",
                "mediaType": "text/plain",
                "content": "联系人 王小明，邮箱 xiaoming@example.com，电话 13800138000",
            },
        ],
        locale="zh",
        resume={
            "basic": {
                "name": "王小明",
                "headline": "前端工程师",
                "phone": "13800138000",
                "email": "xiaoming@example.com",
                "location": "上海",
                "avatar": "https://avatar.example/wxm.png",
                "summary": (
                    "前端工程师，可通过 xiaoming@example.com 或 13800138000 联系。"
                ),
            },
            "sections": [],
        },
        jobBrief="候选人邮箱 xiaoming@example.com",
        keywordMatch={"matched": [], "missing": [], "score": 0},
        appliedActions=[],
        modelConfig=None,
        settings={},
    )

    messages = build_agent_messages(request, config, mode="tools")
    content = messages[1]["content"]
    payload = json.loads(content)

    assert "王小明" not in content
    assert "13800138000" not in content
    assert "xiaoming@example.com" not in content
    assert "https://avatar.example/wxm.png" not in content
    assert payload["resume"]["basic"]["name"] == ""
    assert payload["resume"]["basic"]["phone"] == ""
    assert payload["resume"]["basic"]["email"] == ""
    assert payload["resume"]["basic"]["avatar"] == ""
    assert payload["resume"]["basicFieldStatus"]["name"] == "present"
    assert payload["resume"]["basicFieldStatus"]["phone"] == "present"
    assert payload["resume"]["basicFieldStatus"]["email"] == "present"
    assert "[redacted_email]" in payload["resume"]["basic"]["summary"]
    assert "[redacted_phone]" in payload["resume"]["basic"]["summary"]
    assert "[redacted_email]" in payload["files"][0]["excerpt"]
    assert "[redacted_phone]" in payload["files"][0]["excerpt"]


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
            "basic": {
                "name": "王小明",
                "phone": "13800138000",
                "email": "xiaoming@example.com",
            },
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
                            "description": (
                                "支持多轮 Agent 草稿编辑，联系 13800138000。"
                            ),
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
    output_text = json.dumps(result["output"], ensure_ascii=False)
    assert "13800138000" not in output_text
    assert "xiaoming@example.com" not in output_text
    assert "[redacted_phone]" in output_text


def test_agent_draft_diff_summary_hides_personal_identity() -> None:
    request = AgentChatRequest(
        prompt="解释刚才的草稿",
        locale="zh",
        resume={
            "basic": {
                "name": "王小明",
                "phone": "13800138000",
                "email": "xiaoming@example.com",
            },
            "sections": [],
        },
        draftState={
            "id": "draft-current",
            "status": "pending",
            "resume": {"basic": {"name": "王小明"}, "sections": []},
            "editCount": 1,
            "edits": [
                {
                    "id": "edit-summary",
                    "title": "优化王小明简介",
                    "target": "basic.summary",
                    "replacement": "联系 xiaoming@example.com 或 13800138000。",
                },
            ],
            "diffs": [
                {
                    "id": "diff-summary",
                    "label": "王小明简介",
                    "before": "邮箱 xiaoming@example.com",
                    "after": "电话 13800138000",
                },
            ],
        },
    )
    runner = AgentToolRunner(AgentPlanExecutor(request))

    _, result = runner._run_local_tool(
        tool_call("call-diff", "draft_diff_summary", {}),
    )

    output_text = json.dumps(result["output"], ensure_ascii=False)
    assert "王小明" not in output_text
    assert "13800138000" not in output_text
    assert "xiaoming@example.com" not in output_text
    assert "[redacted_name]" in output_text
    assert "[redacted_phone]" in output_text
    assert "[redacted_email]" in output_text


def test_agent_rejects_replace_field_for_hidden_personal_fields() -> None:
    edits, rejected = _model_edit_suggestions_with_diagnostics(
        {"basic": {"email": "xiaoming@example.com"}, "sections": []},
        [
            {
                "title": "更新邮箱",
                "target": "basic.email",
                "reason": "用户要求修改邮箱。",
                "operation": {
                    "type": "replace_field",
                    "path": "basic.email",
                    "value": "new@example.com",
                },
            },
        ],
        locale="zh",
    )

    assert edits == []
    assert len(rejected) == 1
    assert "hidden personal fields" in rejected[0]["reason"]


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


def test_agent_edit_split_item_rejects_missing_target_without_partial_insert() -> None:
    request = AgentChatRequest(
        prompt="拆分项目经历",
        locale="zh",
        resume={
            "basic": {},
            "sections": [
                {
                    "id": "project",
                    "kind": "project",
                    "layout": "timeline",
                    "items": [{"id": "project-1", "title": "ResuMate"}],
                },
            ],
        },
    )
    runner = AgentToolRunner(AgentPlanExecutor(request))

    tool, result = runner._run_local_tool(
        tool_call(
            "call-split",
            "edit_split_item",
            {
                "sectionId": "project",
                "itemId": "missing",
                "first": {"description": "第一段"},
                "second": {"title": "第二段"},
            },
        ),
    )

    assert tool.state == "output-error"
    assert result["output"]["editCount"] == 0
    assert runner.edits == []
    assert runner.draft_resume["sections"][0]["items"] == [
        {"id": "project-1", "title": "ResuMate"},
    ]


def test_agent_edit_split_item_generates_fresh_second_item_id() -> None:
    request = AgentChatRequest(
        prompt="拆分项目经历",
        locale="zh",
        resume={
            "basic": {},
            "sections": [
                {
                    "id": "project",
                    "kind": "project",
                    "layout": "timeline",
                    "items": [{"id": "project-1", "title": "ResuMate"}],
                },
            ],
        },
    )
    runner = AgentToolRunner(AgentPlanExecutor(request))

    tool, result = runner._run_local_tool(
        tool_call(
            "call-split",
            "edit_split_item",
            {
                "sectionId": "project",
                "itemId": "project-1",
                "first": {"description": "负责 Agent 草稿流程。"},
                "second": {
                    "id": "project-1",
                    "title": "ResuMate 指标优化",
                    "highlights": ["优化草稿预览链路。"],
                },
                "index": 1,
            },
        ),
    )

    items = runner.draft_resume["sections"][0]["items"]
    assert tool.state == "output-available"
    assert result["output"]["editCount"] == 2
    assert items[0]["description"] == "负责 Agent 草稿流程。"
    assert items[1]["title"] == "ResuMate 指标优化"
    assert items[1]["id"] != "project-1"


def test_agent_edit_merge_items_rejects_missing_target_without_partial_delete() -> None:
    request = AgentChatRequest(
        prompt="合并项目经历",
        locale="zh",
        resume={
            "basic": {},
            "sections": [
                {
                    "id": "project",
                    "kind": "project",
                    "layout": "timeline",
                    "items": [
                        {"id": "project-1", "title": "ResuMate A"},
                        {"id": "project-2", "title": "ResuMate B"},
                    ],
                },
            ],
        },
    )
    runner = AgentToolRunner(AgentPlanExecutor(request))

    tool, result = runner._run_local_tool(
        tool_call(
            "call-merge",
            "edit_merge_items",
            {
                "sectionId": "project",
                "itemIds": ["project-1", "missing"],
                "mergedItem": {"description": "合并后的项目经历。"},
            },
        ),
    )

    assert tool.state == "output-error"
    assert result["output"]["editCount"] == 0
    assert runner.edits == []
    assert [item["id"] for item in runner.draft_resume["sections"][0]["items"]] == [
        "project-1",
        "project-2",
    ]


def test_agent_edit_merge_items_rejects_duplicate_item_ids() -> None:
    request = AgentChatRequest(
        prompt="合并项目经历",
        locale="zh",
        resume={
            "basic": {},
            "sections": [
                {
                    "id": "project",
                    "kind": "project",
                    "layout": "timeline",
                    "items": [{"id": "project-1", "title": "ResuMate"}],
                },
            ],
        },
    )
    runner = AgentToolRunner(AgentPlanExecutor(request))

    tool, result = runner._run_local_tool(
        tool_call(
            "call-merge",
            "edit_merge_items",
            {
                "sectionId": "project",
                "itemIds": ["project-1", "project-1"],
                "mergedItem": {"description": "合并后的项目经历。"},
            },
        ),
    )

    assert tool.state == "output-error"
    assert result["output"]["editCount"] == 0
    assert runner.edits == []
    assert runner.draft_resume["sections"][0]["items"] == [
        {"id": "project-1", "title": "ResuMate"},
    ]


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
                    "web_search",
                    {
                        "query": "frontend engineer job description",
                        "purpose": "jd",
                    },
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
    monkeypatch.setattr("app.services.agent._search_web_reference", stub_jd_search)

    _, message = post_agent_chat_stream(
        client,
        {
            "prompt": "Find missing keywords and edit my summary",
            "message": {
                "id": "agent-user-1",
                "role": "user",
                "text": "Find missing keywords and edit my summary",
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
                {
                    "role": "user",
                    "text": "Find missing keywords and edit my summary",
                },
            ],
            "conversation": [
                {
                    "role": "user",
                    "text": "Find missing keywords and edit my summary",
                },
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
        tool["title"] == "web_search" for tool in message["tools"]
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


def _assert_language_pattern_schema(
    patterns: dict[str, object],
    *,
    locale_required_groups: set[str],
) -> None:
    allowed_keys = {"common", *SUPPORTED_AGENT_LOCALES}

    for group_name, group in patterns.items():
        assert isinstance(group, dict), group_name
        assert set(group) <= allowed_keys, group_name

        for key, value in group.items():
            assert isinstance(key, str)
            assert isinstance(value, list), f"{group_name}.{key}"
            assert all(isinstance(item, str) and item for item in value)

        if group_name in locale_required_groups:
            for locale in SUPPORTED_AGENT_LOCALES:
                assert group.get(locale), f"{group_name}.{locale}"


def test_agent_supported_locales_cover_resources() -> None:
    supported = set(SUPPORTED_AGENT_LOCALES)
    prompt_dir = Path(__file__).parents[1] / "app/services/agent/prompts"
    system_core = (prompt_dir / "system.md").read_text(encoding="utf-8").strip()

    assert DEFAULT_AGENT_LOCALE in supported
    assert set(supported_agent_text_locales()) == supported
    assert set(AGENT_LOCALIZED_TEXT) == supported
    assert set(SYSTEM_PROMPTS) == supported
    assert set(FINAL_RESPONSE_PROMPTS) == supported
    assert set(STREAMING_FINAL_RESPONSE_PROMPTS) == supported
    assert set(EDIT_OPERATION_GUIDES) == supported
    assert EDIT_OPERATION_GUIDE == EDIT_OPERATION_GUIDES[DEFAULT_AGENT_LOCALE]
    assert not (prompt_dir / "system.en.md").exists()
    assert not (prompt_dir / "system.zh.md").exists()

    for locale in SUPPORTED_AGENT_LOCALES:
        locale_addendum = (
            prompt_dir / f"system.locale.{locale}.md"
        ).read_text(encoding="utf-8").strip()
        assert SYSTEM_PROMPTS[locale] == f"{system_core}\n\n{locale_addendum}"


def test_agent_intent_patterns_are_externalized() -> None:
    patterns = json.loads(INTENT_PATTERN_FILE.read_text(encoding="utf-8"))
    required_groups = {
        "explain_draft",
        "previous_draft_reference",
        "draft_reference",
        "draft_revision",
        "job_request",
        "role_research",
        "jd_gap_diagnosis",
        "analyze_resume",
        "edit_resume",
        "material_generation_request",
        "delete_intent",
        "reorder_intent",
        "merge_intent",
    }
    policy_source = (
        Path(__file__).parents[1] / "app/services/agent/policy.py"
    ).read_text(encoding="utf-8")

    assert required_groups <= set(patterns)
    _assert_language_pattern_schema(
        patterns,
        locale_required_groups=required_groups,
    )
    assert matches_intent_pattern("帮我生成一个项目经历草稿", "edit_resume")
    assert matches_intent_pattern("拆分项目经历", "edit_resume")
    assert matches_intent_pattern("合并项目经历", "edit_resume")
    assert matches_intent_pattern("整理技能分组", "edit_resume")
    assert matches_intent_pattern(
        "帮我生成一个项目经历草稿",
        "material_generation_request",
    )
    assert matches_intent_pattern("帮我了解 AI应用开发工程师", "role_research")
    assert matches_intent_pattern("这份简历和 JD 的差距在哪里", "jd_gap_diagnosis")
    assert matches_intent_pattern("把刚才的草稿再短一点", "draft_revision")
    assert matches_intent_pattern("rewrite my summary", "edit_resume", locale="en")
    assert not matches_intent_pattern("rewrite my summary", "edit_resume", locale="zh")
    assert not re.search(r"[\u4e00-\u9fff]", policy_source)


def test_agent_parsing_patterns_are_externalized() -> None:
    patterns = json.loads(PARSING_PATTERN_FILE.read_text(encoding="utf-8"))
    required_groups = {
        "visible_plan.job_context",
        "visible_plan.export",
        "role.explicit",
        "role.cleanup_prefix",
        "role.trailing_context",
        "plan.add",
        "plan.delete",
        "plan.reorder",
        "plan.summary",
        "plan.bullet",
        "project.stop_labels",
        "editing.field_only_label",
        "streaming.blocked_visible_loop_prefixes",
        "web.blocked_excerpt_markers",
    }
    source_paths = [
        Path(__file__).parents[1] / "app/services/agent/executor.py",
        Path(__file__).parents[1] / "app/services/agent/editing/operations.py",
        Path(__file__).parents[1] / "app/services/agent/runtime/streaming.py",
        Path(__file__).parents[1] / "app/services/agent/integrations/web.py",
    ]

    assert required_groups <= set(patterns)
    _assert_language_pattern_schema(
        patterns,
        locale_required_groups={
            "visible_plan.job_context",
            "visible_plan.export",
            "role.explicit",
            "plan.add",
            "plan.delete",
            "plan.reorder",
            "plan.summary",
            "plan.bullet",
            "project.stop_labels",
        },
    )
    assert matches_agent_pattern("目标岗位是前端工程师", "visible_plan.job_context")
    assert matches_agent_pattern("导出 PDF", "visible_plan.export")
    assert matches_agent_pattern("export", "visible_plan.export", locale="en")
    assert not matches_agent_pattern("export", "visible_plan.export", locale="zh")
    for source_path in source_paths:
        source = source_path.read_text(encoding="utf-8")
        assert not re.search(r"[\u4e00-\u9fff]", source)


def test_agent_web_tools_replace_legacy_jd_schema_names() -> None:
    tool_names = {
        schema["function"]["name"] for schema in tool_registry.AGENT_TOOL_SCHEMAS
    }

    assert {"web_fetch", "web_search"} <= tool_names
    assert "jd_url_fetch" not in tool_names
    assert "jd_reference_search" not in tool_names


def test_agent_tool_specs_match_schema_and_runner_handlers() -> None:
    spec_names = [spec.name for spec in tool_registry.AGENT_TOOL_SPECS]
    schema_names = [
        schema["function"]["name"] for schema in tool_registry.AGENT_TOOL_SCHEMAS
    ]

    assert len(spec_names) == len(set(spec_names))
    assert schema_names == spec_names
    assert tool_registry.ALL_KNOWN_TOOL_NAMES == set(spec_names)
    for spec in tool_registry.AGENT_TOOL_SPECS:
        assert spec.schema["function"]["name"] == spec.name
        assert hasattr(AgentToolRunner, spec.handler_name)


def test_agent_web_search_schema_supports_multi_queries() -> None:
    schema = next(
        schema
        for schema in tool_registry.AGENT_TOOL_SCHEMAS
        if schema["function"]["name"] == "web_search"
    )
    parameters = schema["function"]["parameters"]

    assert parameters["required"] == ["purpose"]
    assert parameters["properties"]["queries"]["maxItems"] == 5
    assert parameters["properties"]["queries"]["items"]["type"] == "string"
    assert parameters["properties"]["maxResults"]["maximum"] == 10


def test_agent_web_fetch_requires_explicit_purpose() -> None:
    request = AgentChatRequest(
        prompt="参考这个链接 https://example.test/project",
        locale="zh",
        resume={"basic": {}, "sections": []},
    )
    runner = AgentToolRunner(AgentPlanExecutor(request))

    tool, result = asyncio.run(
        runner.run(
            tool_call(
                "call-web-fetch",
                "web_fetch",
                {"url": "https://example.test/project"},
            ),
            AgentRuntimeContext(),
        ),
    )

    assert tool.title == "web_fetch"
    assert tool.state == "output-error"
    assert result["output"]["blocked"] is True
    assert "链接用途" in tool.error_text


def test_agent_web_search_uses_explicit_reference_purpose(monkeypatch) -> None:
    monkeypatch.setattr("app.services.agent._search_web_reference", stub_jd_search)
    request = AgentChatRequest(
        prompt="帮我了解 AI application developer 岗位",
        locale="zh",
        resume={"basic": {}, "sections": []},
    )
    runner = AgentToolRunner(AgentPlanExecutor(request))

    tool, result = asyncio.run(
        runner.run(
            tool_call(
                "call-web-search",
                "web_search",
                {
                    "query": "AI application developer responsibilities",
                    "purpose": "target_context",
                },
            ),
            AgentRuntimeContext(),
        ),
    )

    assert tool.title == "web_search"
    assert tool.state == "output-available"
    assert result["output"]["purpose"] == "target_context"
    assert result["output"]["personalExperienceEvidence"] is False


def test_agent_web_search_accepts_multi_query_target_context(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.agent._search_web_reference_summary",
        stub_web_search_summary,
    )
    request = AgentChatRequest(
        prompt="帮我了解 AI application developer 岗位",
        locale="zh",
        resume={"basic": {}, "sections": []},
    )
    runner = AgentToolRunner(AgentPlanExecutor(request))

    tool, result = asyncio.run(
        runner.run(
            tool_call(
                "call-web-search",
                "web_search",
                {
                    "queries": [
                        "AI application developer responsibilities",
                        "AI application developer skills",
                        "AI application developer resume keywords",
                    ],
                    "maxResults": 10,
                    "purpose": "target_context",
                },
            ),
            AgentRuntimeContext(),
        ),
    )

    assert tool.title == "web_search"
    assert tool.state == "output-available"
    assert result["input"]["query"] == "AI application developer responsibilities"
    assert result["input"]["maxResults"] == 10
    assert result["output"]["queryCount"] == 3
    assert result["output"]["maxResults"] == 10
    assert len(result["output"]["results"]) == 2
    assert result["output"]["url"] == "https://example.test/roles/ai-application-developer"
    assert result["output"]["personalExperienceEvidence"] is False


def test_agent_web_search_context_is_visible_to_final_response(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.agent._search_web_reference_summary",
        stub_web_search_summary,
    )
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
        context_window_tokens=4096,
    )
    request = AgentChatRequest(
        prompt="帮我了解 AI application developer 岗位",
        locale="zh",
        resume={"basic": {}, "sections": []},
    )
    runner = AgentToolRunner(AgentPlanExecutor(request))

    asyncio.run(
        runner.run(
            tool_call(
                "call-web-search",
                "web_search",
                {
                    "queries": [
                        "AI application developer responsibilities",
                        "AI application developer skills",
                    ],
                    "purpose": "target_context",
                },
            ),
            AgentRuntimeContext(),
        ),
    )
    draft = runner.build_message()
    messages = build_agent_messages(
        request,
        config,
        mode="streaming_final",
        draft=draft,
    )
    payload = json.loads(messages[1]["content"])
    web_context = payload["toolContext"]["webSearch"][0]

    assert draft.edits == []
    assert draft.sources[0].url == "https://example.test/roles/ai-application-developer"
    assert web_context["purpose"] == "target_context"
    assert len(web_context["results"]) == 2
    assert "LLM features" in web_context["results"][0]["excerpt"]
    assert "evaluation" in web_context["results"][1]["excerpt"]


def test_agent_web_search_falls_back_to_search_snippet(monkeypatch) -> None:
    monkeypatch.setattr(
        agent_web,
        "_search_web_results",
        lambda _query: (
            [
                WebSearchResult(
                    title="Frontend engineer JD",
                    url="https://example.test/jobs/frontend",
                    excerpt=(
                        "Frontend engineer responsibilities include React, "
                        "TypeScript, performance optimization, collaboration "
                        "with product teams, and accessible UI delivery."
                    ),
                ),
            ],
            None,
        ),
    )
    monkeypatch.setattr(agent_web, "_fetch_web_reference", lambda _url: None)

    result, count, error = agent_web._search_web_reference("frontend engineer jd")

    assert error is None
    assert count == 1
    assert result is not None
    assert result.url == "https://example.test/jobs/frontend"
    assert "React" in result.excerpt


def test_agent_web_search_summary_dedupes_and_limits_queries(monkeypatch) -> None:
    calls: list[tuple[str, int]] = []

    def fake_search(
        query: str,
        max_results: int,
    ) -> tuple[list[WebSearchResult], int, None]:
        calls.append((query, max_results))
        available_results = [
            WebSearchResult(
                title=f"{query} unique",
                url=f"https://example.test/{query}",
                excerpt=f"Unique context for {query}.",
            ),
            WebSearchResult(
                title=f"{query} shared",
                url="https://example.test/shared",
                excerpt=f"Shared context for {query}.",
            ),
        ]
        return (
            available_results[:max_results],
            len(available_results),
            None,
        )

    monkeypatch.setattr(agent_web, "_search_web_reference_results", fake_search)

    summary = agent_web._search_web_reference_summary(
        ["first", "first", "second", "third", "fourth", "fifth", "sixth"],
        max_results=3,
    )

    assert calls == [("first", 3), ("second", 1)]
    assert summary.query == "first"
    assert summary.query_count == 5
    assert summary.result_count == 4
    assert len(summary.results) == 3


def test_agent_web_headers_are_browser_compatible() -> None:
    headers = agent_web._web_headers("text/html")

    assert headers["Accept"] == "text/html"
    assert "Mozilla/5.0" in headers["User-Agent"]
    assert "resumate.local" not in headers["User-Agent"]
    assert headers["Accept-Language"]


def test_agent_suggest_only_filters_and_blocks_edit_tools() -> None:
    request = AgentChatRequest(
        prompt="优化个人简介",
        locale="zh",
        resume={
            "basic": {"summary": "已有简介"},
            "sections": [],
        },
        settings={"confirmationMode": "suggestOnly"},
    )

    policy = capability_policy_for_request(request)
    schemas = tool_registry.agent_tool_schemas_for_names(policy.allowed_tools)
    schema_names = {schema["function"]["name"] for schema in schemas}

    assert policy.mode == AgentCapabilityMode.READ_ONLY
    assert "resume_analysis" in schema_names
    assert "edit_execute" not in schema_names

    runner = AgentToolRunner(AgentPlanExecutor(request))
    tool, result = runner._run_local_tool(
        tool_call(
            "call-execute",
            "edit_execute",
            {
                "edits": [
                    {
                        "title": "优化简介",
                        "target": "basic.summary",
                        "reason": "用户要求优化。",
                        "operation": {
                            "type": "replace_field",
                            "path": "basic.summary",
                            "value": "新的简介",
                        },
                    },
                ],
            },
        ),
    )

    assert tool.state == "output-error"
    assert result["output"]["blocked"] is True
    assert "仅给建议" in tool.error_text
    assert runner.edits == []
    assert runner.draft_resume["basic"]["summary"] == "已有简介"


def test_agent_explain_draft_policy_allows_diff_summary_only() -> None:
    request = AgentChatRequest(
        prompt="解释刚才的草稿改了什么",
        locale="zh",
        resume={"basic": {}, "sections": []},
        draftState={
            "id": "draft-current",
            "status": "pending",
            "resume": {"basic": {}, "sections": []},
            "editCount": 1,
            "edits": [
                {
                    "id": "edit-summary",
                    "title": "优化简介",
                    "target": "basic.summary",
                    "replacement": "新的简介",
                },
            ],
            "diffs": [],
        },
    )

    policy = capability_policy_for_request(request)
    schemas = tool_registry.agent_tool_schemas_for_names(policy.allowed_tools)
    schema_names = {schema["function"]["name"] for schema in schemas}

    assert policy.intent == AgentTaskIntent.EXPLAIN_DRAFT
    assert schema_names == {"draft_diff_summary", "finish"}

    runner = AgentToolRunner(AgentPlanExecutor(request))
    diff_tool, _ = runner._run_local_tool(
        tool_call("call-diff", "draft_diff_summary", {}),
    )
    message = runner.build_message()
    edit_tool, _ = runner._run_local_tool(
        tool_call(
            "call-execute",
            "edit_execute",
            {
                "edits": [
                    {
                        "title": "不应执行",
                        "target": "basic.summary",
                        "operation": {
                            "type": "replace_field",
                            "path": "basic.summary",
                            "value": "新的简介",
                        },
                    },
                ],
            },
        ),
    )

    assert diff_tool.state == "output-available"
    assert "不会生成新的简历修改" in message.text
    assert edit_tool.state == "output-error"
    assert "只读任务" in edit_tool.error_text
    assert runner.edits == []


def test_agent_rewrite_draft_requires_pending_draft() -> None:
    request = AgentChatRequest(
        prompt="把刚才的草稿再短一点",
        locale="zh",
        resume={"basic": {"summary": "已有简介"}, "sections": []},
    )

    policy = capability_policy_for_request(request)
    schemas = tool_registry.agent_tool_schemas_for_names(policy.allowed_tools)
    schema_names = {schema["function"]["name"] for schema in schemas}

    assert policy.intent == AgentTaskIntent.REWRITE_DRAFT
    assert policy.mode == AgentCapabilityMode.CLARIFY_ONLY
    assert schema_names == {"finish"}

    runner = AgentToolRunner(AgentPlanExecutor(request))
    tool, _ = runner._run_local_tool(
        tool_call(
            "call-rewrite",
            "draft_rewrite",
            {"edits": [{"operation": {"type": "replace_field"}}]},
        ),
    )

    assert tool.state == "output-error"
    assert "待确认草稿" in tool.error_text
    assert runner.edits == []


def test_agent_plain_edit_phrase_does_not_require_pending_draft() -> None:
    request = AgentChatRequest(
        prompt="把项目标题改成更像后端工程师",
        locale="zh",
        resume={"basic": {}, "sections": []},
    )

    policy = capability_policy_for_request(request)
    schemas = tool_registry.agent_tool_schemas_for_names(policy.allowed_tools)
    schema_names = {schema["function"]["name"] for schema in schemas}

    assert policy.intent == AgentTaskIntent.EDIT_RESUME
    assert policy.mode == AgentCapabilityMode.CAN_DRAFT
    assert "edit_execute" in schema_names
    assert "draft_rewrite" not in schema_names

    runner = AgentToolRunner(AgentPlanExecutor(request))
    tool, result = runner._run_local_tool(
        tool_call(
            "call-rewrite",
            "draft_rewrite",
            {"edits": [{"operation": {"type": "replace_field"}}]},
        ),
    )

    assert tool.state == "output-error"
    assert result["output"]["blocked"] is True


def test_agent_new_draft_request_does_not_require_pending_draft() -> None:
    request = AgentChatRequest(
        prompt=(
            "帮我生成一个项目经历草稿：项目名称：智能客服系统；"
            "职责：负责 RAG 检索和接口开发；技术：Python、FastAPI、Milvus。"
        ),
        locale="zh",
        resume={"basic": {}, "sections": []},
    )

    policy = capability_policy_for_request(request)
    schemas = tool_registry.agent_tool_schemas_for_names(policy.allowed_tools)
    schema_names = {schema["function"]["name"] for schema in schemas}

    assert policy.intent == AgentTaskIntent.EDIT_RESUME
    assert policy.mode == AgentCapabilityMode.CAN_DRAFT
    assert "edit_plan" in schema_names
    assert "edit_execute" in schema_names
    assert "draft_rewrite" not in schema_names


def test_agent_material_generation_requires_user_evidence() -> None:
    request = AgentChatRequest(
        prompt="帮我生成一个项目经历草稿",
        locale="zh",
        resume={"basic": {}, "sections": []},
    )

    policy = capability_policy_for_request(request)
    schemas = tool_registry.agent_tool_schemas_for_names(policy.allowed_tools)
    schema_names = {schema["function"]["name"] for schema in schemas}

    assert policy.intent == AgentTaskIntent.EDIT_RESUME
    assert policy.mode == AgentCapabilityMode.CLARIFY_ONLY
    assert policy.reason == "source_material"
    assert schema_names == {"finish"}


def test_agent_revising_named_draft_requires_pending_draft() -> None:
    request = AgentChatRequest(
        prompt="把草稿改短一点",
        locale="zh",
        resume={"basic": {}, "sections": []},
    )

    policy = capability_policy_for_request(request)
    schemas = tool_registry.agent_tool_schemas_for_names(policy.allowed_tools)
    schema_names = {schema["function"]["name"] for schema in schemas}

    assert policy.intent == AgentTaskIntent.REWRITE_DRAFT
    assert policy.mode == AgentCapabilityMode.CLARIFY_ONLY
    assert schema_names == {"finish"}


def test_agent_keyword_match_missing_does_not_force_jd_intent() -> None:
    request = AgentChatRequest(
        prompt="这份简历整体怎么样？",
        locale="zh",
        resume={"basic": {}, "sections": []},
        keywordMatch={"matched": [], "missing": ["TypeScript"], "score": 0},
    )

    policy = capability_policy_for_request(request)
    schemas = tool_registry.agent_tool_schemas_for_names(policy.allowed_tools)
    schema_names = {schema["function"]["name"] for schema in schemas}

    assert policy.intent == AgentTaskIntent.ANALYZE_RESUME
    assert policy.mode == AgentCapabilityMode.READ_ONLY
    assert "resume_analysis" in schema_names
    assert "edit_execute" not in schema_names
    assert "web_search" not in schema_names


def test_agent_role_research_policy_allows_web_search_without_edits() -> None:
    request = AgentChatRequest(
        prompt="帮我了解 AI应用开发工程师",
        locale="zh",
        resume={"basic": {}, "sections": []},
    )

    policy = capability_policy_for_request(request)
    schemas = tool_registry.agent_tool_schemas_for_names(policy.allowed_tools)
    schema_names = {schema["function"]["name"] for schema in schemas}

    assert policy.intent == AgentTaskIntent.RESEARCH_ROLE
    assert policy.mode == AgentCapabilityMode.READ_ONLY
    assert "web_search" in schema_names
    assert "web_fetch" not in schema_names
    assert "edit_plan" not in schema_names
    assert "edit_execute" not in schema_names


def test_agent_jd_gap_diagnosis_policy_is_read_only() -> None:
    request = AgentChatRequest(
        prompt="这份简历和 JD 的差距在哪里？",
        locale="zh",
        resume={"basic": {}, "sections": []},
        jobBrief="AI application developer requires Python, RAG, and evaluation.",
    )

    policy = capability_policy_for_request(request)
    schemas = tool_registry.agent_tool_schemas_for_names(policy.allowed_tools)
    schema_names = {schema["function"]["name"] for schema in schemas}

    assert policy.intent == AgentTaskIntent.DIAGNOSE_JD_GAP
    assert policy.mode == AgentCapabilityMode.READ_ONLY
    assert "resume_analysis" in schema_names
    assert "web_search" in schema_names
    assert "web_fetch" in schema_names
    assert "edit_plan" not in schema_names
    assert "edit_execute" not in schema_names


def test_agent_jd_optimization_request_can_still_draft() -> None:
    request = AgentChatRequest(
        prompt="根据这个 JD 优化简历，并看一下差距",
        locale="zh",
        resume={"basic": {}, "sections": []},
        jobBrief="AI application developer requires Python, RAG, and evaluation.",
    )

    policy = capability_policy_for_request(request)
    schemas = tool_registry.agent_tool_schemas_for_names(policy.allowed_tools)
    schema_names = {schema["function"]["name"] for schema in schemas}

    assert policy.intent == AgentTaskIntent.MATCH_JD
    assert policy.mode == AgentCapabilityMode.CAN_DRAFT
    assert "edit_plan" in schema_names
    assert "edit_execute" in schema_names


def test_agent_delete_operations_require_explicit_delete_intent() -> None:
    request = AgentChatRequest(
        prompt="优化项目经历",
        locale="zh",
        resume={
            "basic": {},
            "sections": [
                {
                    "id": "project",
                    "kind": "project",
                    "items": [{"id": "project-1", "title": "ResuMate"}],
                },
            ],
        },
    )
    runner = AgentToolRunner(AgentPlanExecutor(request))

    tool, result = runner._run_local_tool(
        tool_call(
            "call-delete",
            "edit_execute",
            {
                "edits": [
                    {
                        "title": "删除项目",
                        "target": "sections.project.items.project-1",
                        "operation": {
                            "type": "delete_item",
                            "sectionId": "project",
                            "itemId": "project-1",
                        },
                    },
                ],
            },
        ),
    )

    assert tool.state == "output-error"
    assert result["output"]["blocked"] is True
    assert "明确提出删除" in tool.error_text
    assert runner.edits == []


def test_agent_skills_classify_replaces_existing_groups_without_delete_prompt() -> None:
    request = AgentChatRequest(
        prompt="整理技能分组",
        locale="zh",
        resume={
            "basic": {},
            "sections": [
                {
                    "id": "skills",
                    "kind": "skills",
                    "layout": "list",
                    "items": [
                        {
                            "id": "skill-1",
                            "title": "旧技能",
                            "highlights": ["HTML"],
                        },
                    ],
                },
            ],
        },
    )
    runner = AgentToolRunner(AgentPlanExecutor(request))

    tool, result = runner._run_local_tool(
        tool_call(
            "call-skills",
            "skills_classify",
            {
                "groups": [
                    {"title": "前端", "skills": ["React", "TypeScript"]},
                    {"title": "后端", "skills": ["Python"]},
                ],
            },
        ),
    )

    items = runner.draft_resume["sections"][0]["items"]
    assert tool.state == "output-available"
    assert result["output"]["editCount"] == 3
    assert [item["title"] for item in items] == ["前端", "后端"]
    assert items[0]["highlights"] == ["React", "TypeScript"]
    assert items[1]["highlights"] == ["Python"]


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


def test_agent_chat_material_gap_asks_followup_questions(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)

    def unexpected_final_completion(*_: object) -> str:
        raise AssertionError(
            "finish-only material gap should not call final completion"
        )

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
                        "reason": "缺少可写入简历的项目事实。",
                        "missing": ["source_material", "user_evidence"],
                    },
                ),
            ],
        ),
    )

    _, message = post_agent_chat_stream(
        client,
        {
            "prompt": "帮我生成一个项目经历草稿",
            "message": {"role": "user", "text": "帮我生成一个项目经历草稿"},
            "messages": [{"role": "user", "text": "帮我生成一个项目经历草稿"}],
            "conversation": [{"role": "user", "text": "帮我生成一个项目经历草稿"}],
            "files": [],
            "locale": "zh",
            "resume": {"basic": {}, "sections": []},
            "jobBrief": "",
            "keywordMatch": {"matched": [], "missing": [], "score": 0},
            "appliedActions": [],
            "modelConfig": model_config,
            "settings": {},
        },
    )

    assert message["tools"] == []
    assert message["edits"] == []
    assert message["finishMissing"] == ["source_material", "user_evidence"]
    assert "你本人具体负责哪一部分" in message["text"]
    assert "用了哪些技术" in message["text"]
    assert "有没有结果" in message["text"]


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

    body, message = post_agent_chat_stream(
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
    assert "event: error" in body
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
                    "web_fetch",
                    {
                        "url": "https://example.test/jobs/frontend",
                        "purpose": "jd",
                    },
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

    assert any(tool["title"] == "web_fetch" for tool in message["tools"])
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
                    "web_search",
                    {
                        "query": "AI应用开发 岗位 JD 职责 任职要求",
                        "purpose": "jd",
                    },
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
    monkeypatch.setattr("app.services.agent._search_web_reference", stub_jd_search)

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
        tool for tool in message["tools"] if tool["title"] == "web_search"
    )
    assert jd_tool["output"]["role"] == "AI应用开发"
    assert jd_tool["input"]["query"] == "AI应用开发 岗位 JD 职责 任职要求"
    assert message["knowledge"][0]["title"] == "AI应用开发"
    assert not any("的职位是" in suggestion for suggestion in message["suggestions"])


def test_agent_chat_streams_role_research_web_summary(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    monkeypatch.setattr(
        "app.services.agent._search_web_reference_summary",
        stub_web_search_summary,
    )
    monkeypatch.setattr(
        "app.services.agent.complete_chat_tool_call",
        stub_tool_call_batches(
            [
                tool_call(
                    "call-role-research",
                    "web_search",
                    {
                        "queries": [
                            "AI application developer responsibilities",
                            "AI application developer skills",
                            "AI application developer resume keywords",
                        ],
                        "maxResults": 10,
                        "purpose": "target_context",
                    },
                ),
            ],
        ),
    )

    def stream_response(
        _config: AgentLlmConfig,
        messages: list[dict],
        *_: object,
        **__: object,
    ) -> object:
        payload = json.loads(messages[1]["content"])
        web_context = payload["toolContext"]["webSearch"][0]
        assert web_context["purpose"] == "target_context"
        assert len(web_context["results"]) == 2
        yield LlmStreamDelta(
            kind="text",
            delta="岗位情报：核心职责、技能要求、简历关键词。",
        )

    monkeypatch.setattr("app.services.agent.complete_chat_stream", stream_response)

    _, message = post_agent_chat_stream(
        client,
        {
            "prompt": "帮我了解 AI应用开发工程师",
            "message": {
                "role": "user",
                "text": "帮我了解 AI应用开发工程师",
            },
            "messages": [{"role": "user", "text": "帮我了解 AI应用开发工程师"}],
            "conversation": [{"role": "user", "text": "帮我了解 AI应用开发工程师"}],
            "files": [],
            "locale": "zh",
            "resume": {"basic": {}, "sections": []},
            "jobBrief": "",
            "keywordMatch": {"matched": [], "missing": [], "score": 0},
            "appliedActions": [],
            "modelConfig": model_config,
            "settings": {},
        },
    )

    web_tool = next(
        tool for tool in message["tools"] if tool["title"] == "web_search"
    )
    assert message["edits"] == []
    assert "岗位情报" in message["text"]
    assert web_tool["input"]["maxResults"] == 10
    assert web_tool["output"]["queryCount"] == 3
    assert web_tool["output"]["personalExperienceEvidence"] is False


def test_agent_chat_streams_jd_gap_diagnosis_without_edits(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    monkeypatch.setattr(
        "app.services.agent._search_web_reference_summary",
        stub_web_search_summary,
    )
    monkeypatch.setattr(
        "app.services.agent.complete_chat_tool_call",
        stub_tool_call_batches(
            [
                tool_call(
                    "call-target-context",
                    "web_search",
                    {
                        "queries": [
                            "AI application developer JD requirements",
                            "AI application developer resume keywords",
                        ],
                        "purpose": "target_context",
                        "maxResults": 10,
                    },
                ),
            ],
            [tool_call("call-analysis", "resume_analysis")],
        ),
    )

    def stream_response(
        _config: AgentLlmConfig,
        messages: list[dict],
        *_: object,
        **__: object,
    ) -> object:
        payload = json.loads(messages[1]["content"])
        analysis_context = payload["toolContext"]["resumeAnalysis"][0]
        assert analysis_context["matchedKeywords"] == ["Python"]
        assert analysis_context["missingKeywords"] == ["RAG", "evaluation"]
        assert analysis_context["targetFit"]["hasTargetContext"] is True
        assert payload["toolContext"]["webSearch"][0]["purpose"] == "target_context"
        yield LlmStreamDelta(
            kind="text",
            delta=(
                "差距诊断：已匹配 Python；缺少 RAG 和 evaluation；"
                "需要补充项目证据。"
            ),
        )

    monkeypatch.setattr("app.services.agent.complete_chat_stream", stream_response)

    _, message = post_agent_chat_stream(
        client,
        {
            "prompt": "这份简历和 JD 的差距在哪里？",
            "message": {
                "role": "user",
                "text": "这份简历和 JD 的差距在哪里？",
            },
            "messages": [{"role": "user", "text": "这份简历和 JD 的差距在哪里？"}],
            "conversation": [
                {"role": "user", "text": "这份简历和 JD 的差距在哪里？"},
            ],
            "files": [],
            "locale": "zh",
            "resume": {
                "basic": {"headline": "AI 应用开发工程师", "summary": "熟悉 Python"},
                "sections": [
                    {
                        "id": "project",
                        "kind": "project",
                        "layout": "list",
                        "items": [
                            {
                                "id": "project-1",
                                "title": "智能客服项目",
                                "subtitle": "后端开发",
                                "meta": "Python",
                                "period": "2025",
                                "description": "负责 API 开发。",
                                "highlights": ["使用 Python 实现业务接口。"],
                            },
                        ],
                    },
                ],
            },
            "jobBrief": (
                "AI application developer requires Python, RAG, and evaluation."
            ),
            "keywordMatch": {
                "matched": ["Python"],
                "missing": ["RAG", "evaluation"],
                "score": 34,
            },
            "appliedActions": [],
            "modelConfig": model_config,
            "settings": {},
        },
    )

    tool_titles = [tool["title"] for tool in message["tools"]]
    assert message["edits"] == []
    assert "差距诊断" in message["text"]
    assert tool_titles == ["web_search", "resume_analysis"]
    assert "edit_plan" not in tool_titles
    assert "edit_execute" not in tool_titles


def test_agent_chat_streams_tool_and_source_metadata(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    monkeypatch.setattr(
        "app.services.agent._async_search_web_reference",
        async_stub_jd_search,
    )
    monkeypatch.setattr(
        "app.services.agent.complete_chat_tool_call",
        stub_tool_call_batches(
            [
                tool_call(
                    "call-jd",
                    "web_search",
                    {
                        "query": "前端开发工程师 岗位 JD 职责 任职要求",
                        "purpose": "jd",
                    },
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
            "prompt": "针对前端开发工程师岗位优化个人简介",
            "message": {
                "role": "user",
                "text": "针对前端开发工程师岗位优化个人简介",
            },
            "messages": [
                {"role": "user", "text": "针对前端开发工程师岗位优化个人简介"},
            ],
            "conversation": [
                {"role": "user", "text": "针对前端开发工程师岗位优化个人简介"},
            ],
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
    assert "event: tool_start" in body
    assert "event: tool_delta" in body
    assert "event: tool_done" in body
    assert '"state":"input-available"' in body
    assert '"state":"output-available"' in body
    assert "event: message_delta" in body
    assert "event: message_done" in body
    assert "流式真实模型响应" in body
    assert body.index("web_search") < body.index("resume_analysis")
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
    monkeypatch.setattr("app.services.agent._search_web_reference", stub_jd_search)
    monkeypatch.setattr(
        "app.services.agent.complete_chat_tool_call",
        stub_tool_call_responses(
            LlmToolCallResponse(
                content="我先同时检查简历结构和岗位参考。",
                tool_calls=[
                    tool_call("call-analysis", "resume_analysis"),
                    tool_call(
                        "call-jd",
                        "web_search",
                        {
                            "query": "前端开发工程师 岗位 JD 职责 任职要求",
                            "purpose": "jd",
                        },
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
    assert body.index("resume_analysis") < body.index("web_search")
    assert body.index("web_search") < body.index(
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
    monkeypatch.setattr("app.services.agent._search_web_reference", stub_jd_search)
    monkeypatch.setattr(
        "app.services.agent.complete_chat_tool_call",
        stub_tool_call_batches(
            [
                tool_call(
                    "call-jd",
                    "web_search",
                    {
                        "query": "前端开发工程师 岗位 JD 职责 任职要求",
                        "purpose": "jd",
                    },
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
