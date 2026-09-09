import asyncio
import json
import re
import sqlite3
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier, Event, Lock
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet
from dotenv import dotenv_values
from fastapi.testclient import TestClient

from app.agent_locales import DEFAULT_AGENT_LOCALE, SUPPORTED_AGENT_LOCALES
from app.config import get_settings
from app.db.connection import connect
from app.schemas.agent import AgentChatRequest
from app.schemas.agent_settings import normalize_agent_settings
from app.schemas.exports import ExportResumeImagesRequest, ExportResumePdfRequest
from app.schemas.resumes import ResumeListResponse
from app.services import resumes as resume_service
from app.services import templates as template_service
from app.services import user_preferences, workspace_pages
from app.services.agent import contracts as agent_contracts
from app.services.agent import section_registry as section_registry_module
from app.services.agent.attachments import store_agent_attachment
from app.services.agent.editing.operations import (
    parse_edit_batch,
)
from app.services.agent.environment import ResumeToolEnvironment
from app.services.agent.evidence import historical_prompt_evidence_ref
from app.services.agent.integrations import web as agent_web
from app.services.agent.integrations.web import (
    WebReference,
)
from app.services.agent.localization import (
    TEXT as AGENT_LOCALIZED_TEXT,
)
from app.services.agent.preferences import prepare_agent_request
from app.services.agent.prompt import AGENT_PROMPT
from app.services.agent.runtime.context import AgentRuntimeContext
from app.services.agent.runtime.messages import AgentPromptCompiler
from app.services.agent.section_registry import SECTION_REGISTRY
from app.services.auth_accounts import get_auth_db_path
from app.services.auth_tokens import create_access_token, decode_access_token
from app.services.llm import (
    AgentLlmConfig,
    LlmAssistantMessage,
    LlmPrompt,
    LlmRequestError,
    LlmStreamEvent,
    LlmToolCall,
)
from app.services.model_discovery_cache import (
    MODEL_DISCOVERY_CACHE_NAME,
    get_cached_provider_model,
    write_cached_provider_models,
)
from app.services.model_providers import DiscoveredModel
from app.services.pdf import ResumeImageExportResult
from app.services.resume_document_contract import ITEM_FIELDS_BY_KIND
from app.services.template_presets import BUILTIN_TEMPLATE_PRESETS
from app.services.templates import TemplateCatalog

ASYNC_STREAM_TOOL_CALL_PATH = "app.services.agent.runtime.loop.async_stream_tool_call"
ASYNC_COMPLETE_CHAT_PATH = "app.services.agent.runtime.loop.async_complete_chat"
ASYNC_STREAM_CHAT_PATH = "app.services.agent.runtime.loop.async_stream_chat"


def minimal_resume_document(
    *,
    name: str = "Test Resume",
    summary: str = "",
) -> dict:
    return {
        "schemaVersion": 2,
        "basic": {
            "name": name,
            "headline": "",
            "phone": "",
            "email": "",
            "location": "",
            "avatar": "",
            "summary": summary,
            "customFields": [],
        },
        "sections": [],
    }


def minimal_resume_item(
    resume_id: str = "resumetest",
    title: str = "Test Resume",
) -> dict:
    return {
        "id": resume_id,
        "title": title,
        "updatedAt": "2026-05-16T01:00:00.000Z",
        "documentLocale": "en",
        "jobBrief": "",
        "typography": {"fontFamily": "inter", "fontSize": 16},
        "template": "minimal",
        "resume": minimal_resume_document(name=title),
    }


def resume_artifact_item(title: str = "Test Resume") -> dict:
    """Return the portable V1 fields accepted by the resume importer."""

    item = minimal_resume_item(title=title)
    return {
        "title": item["title"],
        "documentLocale": item["documentLocale"],
        "resume": item["resume"],
        "jobBrief": item["jobBrief"],
        "typography": item["typography"],
        "template": item["template"],
        "templateSettings": None,
    }


def noncanonical_list_resume() -> dict:
    resume = minimal_resume_item(title="Invalid List Resume")["resume"]
    resume["sections"] = [
        {
            "id": "skills",
            "kind": "skills",
            "layout": "list",
            "customTitle": "",
            "items": [
                {
                    "id": "skill-1",
                    "title": "前端",
                    "subtitle": "",
                    "meta": "",
                    "period": "",
                    "description": "",
                    "highlights": ["React", "TypeScript"],
                },
            ],
        },
    ]
    return resume


def template_artifact_item(name: str = "Custom Template") -> dict:
    """Return the portable V1 fields accepted by template write APIs."""

    return {
        "preset": "minimal",
        "name": name,
        "description": "Custom template",
        "layout": {
            "basicInfo": "centered",
            "section": "plain",
            "timelineItemLayout": "split",
            "listItemLayout": "list",
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
    }


def resume_save_payload(resume_item: dict, **overrides: object) -> dict:
    """Return the client-owned fields accepted by the resume save command."""

    payload = {
        key: resume_item.get(key)
        for key in (
            "title",
            "documentLocale",
            "resume",
            "jobBrief",
            "typography",
            "template",
            "templateSettings",
        )
    }
    payload.update(overrides)
    return payload


def portable_template_definition(template: dict) -> dict:
    """Strip backend-owned lifecycle fields from a template API payload."""

    return {
        "preset": template["preset"],
        "name": template["name"],
        "description": template["description"],
        "layout": template["layout"],
        "typography": template["typography"],
        "settings": template["settings"],
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
    return {"id": response.json()["data"]["id"]}


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
    assert ollama["supportsTools"] is True
    assert ollama["supportsStreaming"] is True


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
    assert providers_by_id["moonshot"]["supportsTools"] is True
    assert providers_by_id["moonshot"]["supportsStreaming"] is True
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

    assert response.status_code == 400
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


def test_model_provider_discovery_merges_litellm_metadata(
    client: TestClient,
    monkeypatch,
) -> None:
    from app.services import model_metadata

    def fake_get_json(url: str, *, headers: dict[str, str]) -> dict:
        assert url == "https://api.deepseek.com/models"
        assert headers["Authorization"] == "Bearer sk-deepseek-secret"
        return {"data": [{"id": "deepseek-v4-pro", "supports_vision": True}]}

    monkeypatch.setattr("app.services.model_providers._get_json", fake_get_json)
    model_metadata._CATALOG_CACHE = None
    monkeypatch.setattr(
        model_metadata,
        "_fetch_catalog",
        AsyncMock(
            return_value={
                "azure_ai/deepseek-v4-pro": {
                    "litellm_provider": "azure_ai",
                    "max_input_tokens": 200000,
                },
                "deepseek/deepseek-v4-pro": {
                    "litellm_provider": "deepseek",
                    "max_input_tokens": 1000000,
                    "max_output_tokens": 8192,
                    "supports_reasoning": True,
                    "supports_tool_choice": True,
                    "supports_vision": False,
                },
            }
        ),
    )

    assert asyncio.run(model_metadata.refresh_model_metadata_cache()) is True

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
    model = response.json()["data"]["models"][0]
    assert model["id"] == "deepseek-v4-pro"
    assert model["contextWindowTokens"] == 1000000
    assert model["maxOutputTokens"] == 8192
    assert model["supportsThinking"] is True
    assert model["supportsTools"] is True
    assert model["supportsImage"] is True
    assert model["metadataSource"] == "litellm"


def test_model_provider_discovery_uses_manifest_routes_for_all_providers(
    client: TestClient,
    monkeypatch,
) -> None:
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
            "https://generativelanguage.googleapis.com/v1",
            "https://generativelanguage.googleapis.com/v1/models",
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
            "https://api.minimaxi.com/v1",
            "https://api.minimaxi.com/v1/models",
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
        model_id = (
            "qwen-test-chat" if url == expected_routes["qwen"][2] else "test-chat"
        )
        return {
            "data": [{"id": model_id}],
            "models": [
                {
                    "name": f"models/{model_id}",
                    "supportedGenerationMethods": ["generateContent"],
                },
            ],
        }

    monkeypatch.setattr("app.services.model_providers._get_json", fake_get_json)

    for provider_id, (api_family, _api_url, expected_url) in expected_routes.items():
        payload = {
            "provider": provider_id,
            "apiFamily": api_family,
            "apiUrl": f"https://override.example/{provider_id}/v1",
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


def test_anthropic_discovery_caches_official_thinking_control(
    client: TestClient,
    monkeypatch,
) -> None:
    def fake_get_json(url: str, *, headers: dict[str, str]) -> dict:
        assert url == "https://api.anthropic.com/v1/models"
        assert headers["x-api-key"] == "sk-anthropic-secret"
        return {
            "data": [
                {
                    "id": "claude-sonnet-4-6",
                    "max_input_tokens": 200_000,
                    "max_tokens": 64_000,
                    "capabilities": {
                        "thinking": {
                            "supported": True,
                            "types": {
                                "adaptive": {"supported": True},
                                "enabled": {"supported": True},
                            },
                        },
                    },
                },
                {
                    "id": "claude-sonnet-4-5-20250929",
                    "capabilities": {
                        "thinking": {
                            "supported": True,
                            "types": {
                                "adaptive": {"supported": False},
                                "enabled": {"supported": True},
                            },
                        },
                    },
                },
                {
                    "id": "claude-sonnet-5-unknown-capability",
                },
            ],
        }

    monkeypatch.setattr("app.services.model_providers._get_json", fake_get_json)

    response = client.post(
        "/api/model-providers/discover-models",
        json={
            "provider": "anthropic",
            "apiFamily": "anthropic_messages",
            "apiUrl": "https://api.anthropic.com/v1",
            "apiKey": "sk-anthropic-secret",
            "refresh": True,
        },
    )

    assert response.status_code == 200
    models = {item["id"]: item for item in response.json()["data"]["models"]}
    assert models["claude-sonnet-4-6"]["supportsThinking"] is True
    assert models["claude-sonnet-4-6"]["contextWindowTokens"] == 200_000
    assert models["claude-sonnet-4-6"]["maxOutputTokens"] == 64_000
    assert models["claude-sonnet-4-5-20250929"]["supportsThinking"] is True
    assert models["claude-sonnet-5-unknown-capability"]["supportsThinking"] is False
    adaptive = get_cached_provider_model("anthropic", "claude-sonnet-4-6")
    budget = get_cached_provider_model(
        "anthropic",
        "claude-sonnet-4-5-20250929",
    )
    unsupported = get_cached_provider_model(
        "anthropic",
        "claude-sonnet-5-unknown-capability",
    )
    assert adaptive is not None and adaptive.thinking_control == "native_auto"
    assert budget is not None and budget.thinking_control == "native_budget"
    assert unsupported is not None and unsupported.thinking_control == "none"


def test_qwen_discovery_requires_capability_evidence_for_native_auto(
    client: TestClient,
    monkeypatch,
) -> None:
    def fake_get_json(url: str, *, headers: dict[str, str]) -> dict:
        assert url.endswith("/models")
        assert headers["Authorization"] == "Bearer sk-qwen-secret"
        return {
            "data": [
                {"id": "qwen-thinking-name-only"},
                {"id": "qwen-capable", "supports_reasoning": True},
            ],
        }

    monkeypatch.setattr("app.services.model_providers._get_json", fake_get_json)
    monkeypatch.setattr(
        "app.services.model_providers.resolve_models_metadata",
        lambda *_args: {},
    )

    response = client.post(
        "/api/model-providers/discover-models",
        json={
            "provider": "qwen",
            "apiFamily": "openai_compatible_chat",
            "apiUrl": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "apiKey": "sk-qwen-secret",
            "refresh": True,
        },
    )

    assert response.status_code == 200
    by_id = {item["id"]: item for item in response.json()["data"]["models"]}
    assert by_id["qwen-thinking-name-only"]["supportsThinking"] is False
    assert by_id["qwen-capable"]["supportsThinking"] is True
    incapable = get_cached_provider_model("qwen", "qwen-thinking-name-only")
    capable = get_cached_provider_model("qwen", "qwen-capable")
    assert incapable is not None and incapable.thinking_control == "none"
    assert capable is not None and capable.thinking_control == "native_auto"


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
                thinking_control="provider_default",
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
    assert data["models"][0]["supportsTools"] is True
    assert data["models"][0]["supportsStreaming"] is True


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
                thinking_control="provider_default",
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


def agent_workspace_context(prompt: LlmPrompt | list[dict]) -> dict:
    """Read the structured, untrusted workspace envelope from an LLM prompt."""

    messages = prompt.messages if isinstance(prompt, LlmPrompt) else prompt
    for message in reversed(messages):
        content = message.get("content")
        if message.get("role") != "user" or not isinstance(content, str):
            continue
        try:
            value = json.loads(content)
        except json.JSONDecodeError:
            continue
        workspace = value.get("workspaceContext")
        if isinstance(workspace, dict):
            return workspace
    raise AssertionError("Agent prompt has no workspaceContext envelope.")


def agent_current_request_files(prompt: LlmPrompt | list[dict]) -> list[dict]:
    """Read extracted files from the current user turn only."""

    messages = prompt.messages if isinstance(prompt, LlmPrompt) else prompt
    content = messages[-1]["content"]
    if not isinstance(content, list):
        return []
    for part in content:
        text = part.get("text")
        if part.get("type") != "text" or not isinstance(text, str):
            continue
        marker = '{"currentRequestFiles":'
        marker_index = text.find(marker)
        if marker_index < 0:
            continue
        return json.loads(text[marker_index:])["currentRequestFiles"]
    return []


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
    async def stream_response(*_: object, **__: object) -> object:
        yield LlmStreamEvent(type="text_delta", delta=text)
        yield LlmStreamEvent(
            type="done",
            message=LlmAssistantMessage(content=text, stop_reason="stop"),
        )

    return stream_response


async def async_stub_jd_fetch(url: str, *_context: str) -> WebReference:
    return WebReference(
        title="AI Application Developer JD",
        final_url=str(url),
        excerpt="AI application development responsibilities and requirements.",
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


def invoke_agent_tool(
    environment: ResumeToolEnvironment,
    call: LlmToolCall,
) -> tuple[object, dict[str, object]]:
    effect = asyncio.run(environment.invoke(call, AgentRuntimeContext()))
    return effect.invocation, effect.observation


def stub_tool_call_batches(
    *batches: list[LlmToolCall],
    terminal_text: str = "Done.",
):
    pending = list(batches)

    async def call_tools(*_: object, **__: object):
        response = (
            LlmAssistantMessage(content="", tool_calls=pending.pop(0))
            if pending
            else LlmAssistantMessage(content=terminal_text, tool_calls=[])
        )
        if response.content:
            yield LlmStreamEvent(type="text_delta", delta=response.content)
        yield LlmStreamEvent(type="done", message=response)

    return call_tools


def stub_tool_call_responses(
    *responses: LlmAssistantMessage,
):
    pending = list(responses)

    async def call_tools(*_: object, **__: object):
        response = (
            pending.pop(0)
            if pending
            else LlmAssistantMessage(content="Done.", tool_calls=[])
        )
        if response.content:
            yield LlmStreamEvent(type="text_delta", delta=response.content)
        yield LlmStreamEvent(type="done", message=response)

    return call_tools


async def fail_on_second_final_stream(*_: object, **__: object) -> object:
    raise AssertionError("the Pi-style loop must end on the model's natural stop")
    yield


def stub_terminal_tool_text(text: str):
    async def call_tools(*_: object, **__: object):
        response = LlmAssistantMessage(content=text, tool_calls=[])
        if text:
            yield LlmStreamEvent(type="text_delta", delta=text)
        yield LlmStreamEvent(type="done", message=response)

    return call_tools


@pytest.mark.parametrize(
    ("endpoint", "expected_fields", "expected_reads"),
    [
        (
            "/api/workspace/pages/resumes",
            {"defaultTemplateIds", "resumes", "customTemplates"},
            ["user-settings", "workspace-state", "templates:active", "resumes:active"],
        ),
        (
            "/api/workspace/pages/resume-editor",
            {
                "defaultTemplateIds",
                "customTemplates",
                "modelConfigs",
                "agentSettings",
            },
            ["user-settings", "workspace-state", "templates:active", "model-configs"],
        ),
        (
            "/api/workspace/pages/templates",
            {"defaultTemplateIds", "customTemplates"},
            ["user-settings", "workspace-state", "templates:active"],
        ),
        (
            "/api/workspace/pages/trash",
            {
                "defaultTemplateIds",
                "customTemplates",
                "deletedResumes",
                "deletedTemplates",
            },
            [
                "user-settings",
                "workspace-state",
                "templates:active",
                "resumes:deleted",
                "templates:deleted",
            ],
        ),
        (
            "/api/workspace/pages/models",
            {"modelConfigs", "agentSettings"},
            ["user-settings", "model-configs"],
        ),
        (
            "/api/workspace/pages/settings",
            {"modelConfigs", "agentSettings"},
            ["user-settings", "model-configs"],
        ),
    ],
    ids=[
        "resumes",
        "resume-editor",
        "templates",
        "trash",
        "models",
        "settings",
    ],
)
def test_workspace_page_endpoint_only_reads_owned_data(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
    expected_fields: set[str],
    expected_reads: list[str],
) -> None:
    reads: list[str] = []

    def load_user_settings() -> dict:
        reads.append("user-settings")
        return {}

    def load_template_catalog() -> TemplateCatalog:
        reads.extend(("workspace-state", "templates:active"))
        return TemplateCatalog(
            default_template_ids={"zh": "minimal", "en": "minimal"},
            templates=[],
        )

    def list_resumes(status_filter: str) -> ResumeListResponse:
        reads.append(f"resumes:{status_filter}")
        return ResumeListResponse(resumes=[])

    def list_templates(status_filter: str) -> dict[str, list[dict]]:
        reads.append(f"templates:{status_filter}")
        return {"templates": []}

    def list_model_configs() -> list:
        reads.append("model-configs")
        return []

    monkeypatch.setattr(workspace_pages, "load_user_settings", load_user_settings)
    monkeypatch.setattr(
        workspace_pages,
        "load_template_catalog",
        load_template_catalog,
    )
    monkeypatch.setattr(workspace_pages, "list_resumes", list_resumes)
    monkeypatch.setattr(workspace_pages, "list_templates", list_templates)
    monkeypatch.setattr(workspace_pages, "list_llm_configs", list_model_configs)

    response = client.get(endpoint)

    assert response.status_code == 200
    assert response.json()["code"] == 0
    assert set(response.json()["data"]) == expected_fields
    assert Counter(reads) == Counter(expected_reads)


def test_resumes_workspace_page_preserves_nullable_editor_fields(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/resumes",
        json={"documentLocale": "en"},
    ).json()["data"]["resume"]

    response = client.get("/api/workspace/pages/resumes")
    resume = next(
        item
        for item in response.json()["data"]["resumes"]
        if item["id"] == created["id"]
    )

    assert "templateSettings" in resume
    assert resume["templateSettings"] is None


def test_workspace_bootstrap_endpoint_is_removed(client: TestClient) -> None:
    response = client.get("/api/workspace/bootstrap?locale=zh&scope=models")

    assert response.status_code == 404
    assert response.json() == {
        "code": 40004,
        "message": "NOT_FOUND",
        "data": None,
        "requestId": None,
    }


def test_unhandled_api_exception_returns_500_envelope_and_is_logged(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_unhandled_error() -> None:
        raise RuntimeError("unhandled-error-sentinel")

    client.app.add_api_route(
        "/api/test/unhandled-error",
        raise_unhandled_error,
        methods=["GET"],
    )
    monkeypatch.setattr(client._transport, "raise_server_exceptions", False)

    response = client.get("/api/test/unhandled-error")

    assert response.status_code == 500
    assert response.json() == {
        "code": 50000,
        "message": "INTERNAL_SERVER_ERROR",
        "data": None,
        "requestId": None,
    }
    assert "unhandled-error-sentinel" not in response.text
    assert any(
        record.name == "app.exceptions"
        and record.exc_info is not None
        and str(record.exc_info[1]) == "unhandled-error-sentinel"
        for record in caplog.records
    )


@pytest.mark.parametrize(
    ("endpoint", "schema_name", "properties", "required"),
    [
        (
            "/api/workspace/pages/resumes",
            "ResumesPageResponse",
            {"theme", "defaultTemplateIds", "customTemplates", "resumes"},
            {"defaultTemplateIds", "customTemplates", "resumes"},
        ),
        (
            "/api/workspace/pages/resume-editor",
            "ResumeEditorPageResponse",
            {
                "theme",
                "defaultTemplateIds",
                "customTemplates",
                "modelConfigs",
                "agentSettings",
            },
            {
                "defaultTemplateIds",
                "customTemplates",
                "modelConfigs",
                "agentSettings",
            },
        ),
        (
            "/api/workspace/pages/templates",
            "TemplatesPageResponse",
            {"theme", "defaultTemplateIds", "customTemplates"},
            {"defaultTemplateIds", "customTemplates"},
        ),
        (
            "/api/workspace/pages/trash",
            "TrashPageResponse",
            {
                "theme",
                "defaultTemplateIds",
                "customTemplates",
                "deletedResumes",
                "deletedTemplates",
            },
            {
                "defaultTemplateIds",
                "customTemplates",
                "deletedResumes",
                "deletedTemplates",
            },
        ),
        (
            "/api/workspace/pages/models",
            "ModelsPageResponse",
            {"theme", "modelConfigs", "agentSettings"},
            {"modelConfigs", "agentSettings"},
        ),
        (
            "/api/workspace/pages/settings",
            "SettingsPageResponse",
            {"theme", "modelConfigs", "agentSettings"},
            {"modelConfigs", "agentSettings"},
        ),
    ],
    ids=[
        "resumes",
        "resume-editor",
        "templates",
        "trash",
        "models",
        "settings",
    ],
)
def test_workspace_page_openapi_uses_exact_response_contract(
    client: TestClient,
    endpoint: str,
    schema_name: str,
    properties: set[str],
    required: set[str],
) -> None:
    document = client.app.openapi()
    response_schema = document["paths"][endpoint]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    envelope_name = response_schema["$ref"].rsplit("/", 1)[-1]
    envelope = document["components"]["schemas"][envelope_name]
    data_ref = envelope["properties"]["data"]["$ref"]

    assert data_ref == f"#/components/schemas/{schema_name}"
    page_schema = document["components"]["schemas"][schema_name]
    assert set(page_schema["properties"]) == properties
    assert set(page_schema["required"]) == required
    assert page_schema["additionalProperties"] is False


@pytest.mark.parametrize(
    ("page_schema_name", "property_name", "item_schema_name"),
    [
        ("ResumesPageResponse", "resumes", "ResumeWorkspaceItemResponse"),
        (
            "ResumesPageResponse",
            "customTemplates",
            "TemplateDefinitionResponse",
        ),
        (
            "TrashPageResponse",
            "deletedResumes",
            "DeletedResumeWorkspaceItemResponse",
        ),
        (
            "TrashPageResponse",
            "deletedTemplates",
            "DeletedTemplateDefinitionResponse",
        ),
    ],
)
def test_workspace_page_openapi_uses_typed_collection_items(
    client: TestClient,
    page_schema_name: str,
    property_name: str,
    item_schema_name: str,
) -> None:
    schemas = client.app.openapi()["components"]["schemas"]
    item_ref = schemas[page_schema_name]["properties"][property_name]["items"]["$ref"]

    assert item_ref == f"#/components/schemas/{item_schema_name}"
    assert schemas[item_schema_name]["additionalProperties"] is False


def test_resume_workspace_contract_requires_current_appearance_fields(
    client: TestClient,
) -> None:
    schemas = client.app.openapi()["components"]["schemas"]
    create_required = set(schemas["ResumeCreateRequest"]["required"])
    workspace_required = set(schemas["ResumeWorkspaceItemResponse"]["required"])
    save_required = set(schemas["ResumeSaveRequest"]["required"])

    assert create_required == {"documentLocale"}
    assert {
        "documentLocale",
        "typography",
        "template",
        "templateSettings",
    } <= workspace_required
    assert save_required == {
        "title",
        "documentLocale",
        "resume",
        "jobBrief",
        "typography",
        "template",
        "templateSettings",
    }


@pytest.mark.parametrize("template_id", sorted(BUILTIN_TEMPLATE_PRESETS))
def test_new_resume_uses_workspace_default_template_typography(
    client: TestClient,
    template_id: str,
) -> None:
    expected_typography = dict(BUILTIN_TEMPLATE_PRESETS[template_id]["typography"])
    default_response = client.put(
        "/api/workspace/default-template",
        json={"documentLocale": "en", "templateId": template_id},
    )

    created_response = client.post(
        "/api/resumes",
        json={"documentLocale": "en", "title": "Workspace default"},
    )

    assert default_response.status_code == 200
    assert created_response.status_code == 200
    created = created_response.json()["data"]["resume"]
    assert created["template"] == template_id
    assert created["typography"] == expected_typography


@pytest.mark.parametrize("template_id", sorted(BUILTIN_TEMPLATE_PRESETS))
def test_new_resume_uses_explicit_template_typography(
    client: TestClient,
    template_id: str,
) -> None:
    expected_typography = dict(BUILTIN_TEMPLATE_PRESETS[template_id]["typography"])
    created_response = client.post(
        "/api/resumes",
        json={
            "documentLocale": "en",
            "title": "Explicit template",
            "template": template_id,
        },
    )

    assert created_response.status_code == 200
    created = created_response.json()["data"]["resume"]
    assert created["template"] == template_id
    assert created["typography"] == expected_typography


def test_new_resume_uses_explicit_custom_template_typography(
    client: TestClient,
) -> None:
    template_payload = template_artifact_item(name="Plex Default")
    template_payload["typography"] = {
        "fontFamily": "plex",
        "fontSize": 14,
    }
    template_response = client.post(
        "/api/templates",
        json={"template": template_payload},
    )
    template_id = template_response.json()["data"]["template"]["id"]

    created_response = client.post(
        "/api/resumes",
        json={
            "documentLocale": "en",
            "title": "Explicit custom template",
            "template": template_id,
        },
    )

    assert template_response.status_code == 200
    assert created_response.status_code == 200
    created = created_response.json()["data"]["resume"]
    assert created["template"] == template_id
    assert created["typography"] == template_payload["typography"]


def test_create_resume_preserves_explicit_typography_snapshot(
    client: TestClient,
) -> None:
    explicit_typography = {
        "fontFamily": "noto_sans_sc",
        "fontSize": 18,
    }

    created_response = client.post(
        "/api/resumes",
        json={
            "documentLocale": "en",
            "title": "Imported typography snapshot",
            "template": "academic",
            "typography": explicit_typography,
        },
    )

    assert created_response.status_code == 200
    created = created_response.json()["data"]["resume"]
    assert created["template"] == "academic"
    assert created["typography"] == explicit_typography


@pytest.mark.parametrize(
    "missing_field",
    [
        "title",
        "resume",
        "jobBrief",
        "typography",
        "template",
        "templateSettings",
    ],
)
def test_resume_save_rejects_incomplete_current_contract_without_new_version(
    client: TestClient,
    missing_field: str,
) -> None:
    created = client.post(
        "/api/resumes",
        json={"documentLocale": "en", "title": "Strict save contract"},
    ).json()["data"]["resume"]
    payload = resume_save_payload(created)
    del payload[missing_field]

    rejected = client.put(f"/api/resumes/{created['id']}", json=payload)
    versions = client.get(f"/api/resumes/{created['id']}/versions").json()["data"][
        "versions"
    ]

    assert rejected.status_code == 422
    assert rejected.json()["code"] == 40002
    assert rejected.json()["message"] == "VALIDATION_ERROR"
    assert [item["versionId"] for item in versions] == ["1"]


def test_resume_save_accepts_compact_section_gap(client: TestClient) -> None:
    created = client.post(
        "/api/resumes",
        json={"documentLocale": "en", "title": "Compact section gap"},
    ).json()["data"]["resume"]

    response = client.put(
        f"/api/resumes/{created['id']}",
        json=resume_save_payload(
            created,
            templateSettings={"sectionGap": 0.6},
        ),
    )

    assert response.status_code == 200
    assert response.json()["data"]["resume"]["templateSettings"]["sectionGap"] == 0.6


def test_resume_command_flow_owns_identity_versions_and_lifecycle(
    client: TestClient,
) -> None:
    create_response = client.post(
        "/api/resumes",
        json={"documentLocale": "en", "title": "新建简历1"},
    )

    assert create_response.status_code == 200
    created = create_response.json()["data"]
    resume_id = created["resume"]["id"]
    store_agent_attachment(
        session_id=resume_id,
        filename="resume-context.txt",
        media_type="text/plain",
        payload=b"resume context",
    )
    attachment_dir = get_settings().storage_dir / "agent-attachments" / resume_id
    assert re.fullmatch(r"[A-Za-z0-9]{16}", resume_id)
    assert created["resume"]["title"] == "新建简历1"
    assert created["versionId"] == "1"
    assert attachment_dir.exists()

    lifecycle_section = {
        "id": "lifecycle-skills",
        "kind": "simple_list",
        "title": "Skills",
        "items": [
            {
                "id": "lifecycle-skills-content",
                "content": "<ul><li>React</li><li>TypeScript</li></ul>",
            }
        ],
    }
    save_payload = resume_save_payload(
        created["resume"],
        title="Backend Managed Resume",
        resume={
            **created["resume"]["resume"],
            "basic": {
                **created["resume"]["resume"]["basic"],
                "name": "Backend Managed",
            },
            "sections": [lifecycle_section],
        },
        templateSettings=None,
    )
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
    trash_page_response = client.get("/api/workspace/pages/trash")
    save_deleted_response = client.put(f"/api/resumes/{resume_id}", json=save_payload)
    current_deleted_response = client.get(f"/api/resumes/{resume_id}")
    historical_response = client.get(f"/api/resumes/{resume_id}/versions/1")

    assert trash_response.status_code == 200
    assert trash_response.json()["data"]["resume"]["deletedAt"]
    saved_resume = first_save.json()["data"]["resume"]["resume"]
    assert trash_response.json()["data"]["resume"]["resume"] == saved_resume
    assert trash_response.json()["data"]["resume"]["templateSettings"] is None
    deleted_resume = deleted_list_response.json()["data"]["resumes"][0]
    assert deleted_resume["id"] == resume_id
    assert deleted_resume["resume"] == saved_resume
    trash_page_resume = trash_page_response.json()["data"]["deletedResumes"][0]
    assert trash_page_resume["id"] == resume_id
    assert trash_page_resume["resume"] == saved_resume
    assert save_deleted_response.json()["code"] != 0
    assert current_deleted_response.json()["code"] != 0
    assert historical_response.status_code == 200
    assert historical_response.json()["data"]["versionId"] == "1"

    restore_response = client.post(f"/api/resumes/{resume_id}/restore")

    assert restore_response.status_code == 200
    assert restore_response.json()["data"]["resume"]["id"] == resume_id
    assert (
        restore_response.json()["data"]["resume"]["title"] == "Backend Managed Resume"
    )

    client.post(f"/api/resumes/{resume_id}/trash")
    delete_response = client.delete(f"/api/resumes/{resume_id}")
    detail_after_delete_response = client.get(f"/api/resumes/{resume_id}")
    resume_dir = get_settings().storage_dir / "resumes" / resume_id

    assert delete_response.status_code == 200
    assert delete_response.json()["data"]["id"] == resume_id
    assert detail_after_delete_response.json()["code"] != 0
    assert not resume_dir.exists()
    assert not attachment_dir.exists()


def test_resume_title_length_limit_is_enforced_on_create_and_update(
    client: TestClient,
) -> None:
    accepted_title = "简" * 50
    created_response = client.post(
        "/api/resumes",
        json={"documentLocale": "en", "title": accepted_title},
    )

    assert created_response.json()["code"] == 0
    created = created_response.json()["data"]["resume"]
    assert created["title"] == accepted_title

    rejected_create_response = client.post(
        "/api/resumes",
        json={"documentLocale": "en", "title": "简" * 51},
    )
    rejected_update_response = client.put(
        f"/api/resumes/{created['id']}",
        json={"title": "简" * 51},
    )
    current_response = client.get(f"/api/resumes/{created['id']}")

    assert rejected_create_response.json()["code"] == 40002
    assert rejected_update_response.json()["code"] == 40002
    assert current_response.json()["data"]["resume"]["title"] == accepted_title

    derived_title_response = client.put(
        f"/api/resumes/{created['id']}",
        json=resume_save_payload(
            created,
            title="",
            resume=minimal_resume_document(name="姓" * 80),
        ),
    )

    assert derived_title_response.json()["code"] == 0
    assert derived_title_response.json()["data"]["resume"]["title"] == "姓" * 50


def test_resume_create_rejects_noncanonical_list_item_content(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/resumes",
        json={
            "documentLocale": "en",
            "title": "Invalid List Resume",
            "resume": noncanonical_list_resume(),
        },
    )

    assert response.json()["code"] == 40000
    assert response.json()["message"] == "RESUME_DOCUMENT_INVALID"


def test_resume_update_rejects_noncanonical_list_content_without_new_version(
    client: TestClient,
) -> None:
    canonical_resume = minimal_resume_item(title="Canonical List Resume")["resume"]
    canonical_resume["sections"] = [
        {
            "id": "skills",
            "kind": "simple_list",
            "title": "技能",
            "items": [
                {"id": "skill-1", "content": "前端：React、TypeScript"},
            ],
        },
    ]
    create_response = client.post(
        "/api/resumes",
        json={
            "documentLocale": "en",
            "title": "Canonical List Resume",
            "resume": canonical_resume,
        },
    )
    created = create_response.json()["data"]["resume"]

    update_response = client.put(
        f"/api/resumes/{created['id']}",
        json=resume_save_payload(
            created,
            resume=noncanonical_list_resume(),
        ),
    )
    current_response = client.get(f"/api/resumes/{created['id']}")
    versions_response = client.get(f"/api/resumes/{created['id']}/versions")

    assert update_response.json()["code"] == 40000
    assert update_response.json()["message"] == "RESUME_DOCUMENT_INVALID"
    current_item = current_response.json()["data"]["resume"]["resume"]["sections"][0][
        "items"
    ][0]
    assert current_item["content"] == "前端：React、TypeScript"
    assert [
        item["versionId"] for item in versions_response.json()["data"]["versions"]
    ] == ["1"]


def test_duplicate_resume_copies_content_without_history_or_agent_context(
    client: TestClient,
) -> None:
    source_payload = minimal_resume_item(title="Platform Resume")
    source_payload["jobBrief"] = "Private role context"
    source_payload["templateSettings"] = {"pagePaddingX": 9}
    create_response = client.post(
        "/api/resumes",
        json={
            **{
                key: value
                for key, value in source_payload.items()
                if key not in {"id", "updatedAt"}
            },
        },
    )
    source = create_response.json()["data"]["resume"]
    source_id = source["id"]
    source["resume"]["basic"]["headline"] = "Current source content"
    saved_source = client.put(
        f"/api/resumes/{source_id}",
        json=resume_save_payload(source),
    ).json()["data"]["resume"]
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO agent_sessions (id, resume_id, locale, title)
            VALUES (?, ?, 'en', 'Source Session')
            """,
            (source_id, source_id),
        )

    first_response = client.post(f"/api/resumes/{source_id}/duplicate")
    assert first_response.status_code == 200
    first = first_response.json()["data"]
    second_response = client.post(f"/api/resumes/{first['resume']['id']}/duplicate")
    assert second_response.status_code == 200
    second = second_response.json()["data"]
    third_response = client.post(f"/api/resumes/{second['resume']['id']}/duplicate")

    assert third_response.status_code == 200
    third = third_response.json()["data"]
    assert re.fullmatch(r"[A-Za-z0-9]{16}", first["resume"]["id"])
    assert first["resume"]["id"] not in {source_id, second["resume"]["id"]}
    assert first["resume"]["title"] == "Platform Resume - Copy"
    assert second["resume"]["title"] == "Platform Resume - Copy(1)"
    assert third["resume"]["title"] == "Platform Resume - Copy(2)"
    assert first["resume"]["resume"] == saved_source["resume"]
    assert first["resume"]["typography"] == saved_source["typography"]
    assert first["resume"]["template"] == saved_source["template"]
    assert first["resume"]["templateSettings"] == saved_source["templateSettings"]
    assert first["resume"]["documentLocale"] == "en"
    assert first["resume"]["jobBrief"] == ""
    assert first["versionId"] == "1"

    source_versions = client.get(f"/api/resumes/{source_id}/versions").json()["data"][
        "versions"
    ]
    duplicate_versions = client.get(
        f"/api/resumes/{first['resume']['id']}/versions"
    ).json()["data"]["versions"]
    assert [item["versionId"] for item in source_versions] == ["2", "1"]
    assert [item["versionId"] for item in duplicate_versions] == ["1"]
    with connect() as conn:
        session_resume_ids = [
            row["resume_id"]
            for row in conn.execute(
                "SELECT resume_id FROM agent_sessions ORDER BY resume_id"
            ).fetchall()
        ]
    assert session_resume_ids == [source_id]


def test_resume_commands_reject_invalid_template_references_and_rebind_copies(
    client: TestClient,
) -> None:
    unknown_create = client.post(
        "/api/resumes",
        json={
            "documentLocale": "en",
            "title": "Unknown template",
            "template": "template-missing",
        },
    )
    assert unknown_create.json()["message"] == "TEMPLATE_NOT_FOUND"

    template_response = client.post(
        "/api/templates",
        json={"template": template_artifact_item(name="Disposable template")},
    )
    template_id = template_response.json()["data"]["template"]["id"]
    source_response = client.post(
        "/api/resumes",
        json={
            "documentLocale": "en",
            "title": "Custom source",
            "template": template_id,
        },
    )
    source = source_response.json()["data"]["resume"]
    source_id = source["id"]
    deleted_source = client.post(
        "/api/resumes",
        json={
            "documentLocale": "en",
            "title": "Deleted custom source",
            "template": template_id,
        },
    ).json()["data"]["resume"]
    client.post(f"/api/resumes/{deleted_source['id']}/trash")

    client.post(f"/api/templates/{template_id}/trash")
    rebound_source = client.get(f"/api/resumes/{source_id}").json()["data"]["resume"]
    deleted_resumes = client.get("/api/resumes?status=deleted").json()["data"][
        "resumes"
    ]
    rebound_deleted_source = next(
        item for item in deleted_resumes if item["id"] == deleted_source["id"]
    )
    deleted_create = client.post(
        "/api/resumes",
        json={
            "documentLocale": "en",
            "title": "Deleted template",
            "template": template_id,
        },
    )
    rejected_save = client.put(
        f"/api/resumes/{source_id}",
        json=resume_save_payload(source, template=template_id),
    )
    versions_after_rejection = client.get(f"/api/resumes/{source_id}/versions").json()[
        "data"
    ]["versions"]
    accepted_save = client.put(
        f"/api/resumes/{source_id}",
        json=resume_save_payload(rebound_source),
    )
    duplicate = client.post(f"/api/resumes/{source_id}/duplicate")

    assert rebound_source["template"] == "minimal"
    assert rebound_deleted_source["template"] == "minimal"
    assert deleted_create.json()["message"] == "TEMPLATE_NOT_FOUND"
    assert rejected_save.json()["message"] == "TEMPLATE_NOT_FOUND"
    assert accepted_save.json()["code"] == 0
    assert [item["versionId"] for item in versions_after_rejection] == ["2", "1"]
    assert duplicate.json()["data"]["resume"]["template"] == "minimal"


def test_trash_template_rolls_back_rebind_files_when_a_resume_write_fails(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template_id = client.post(
        "/api/templates",
        json={"template": template_artifact_item(name="Rollback template")},
    ).json()["data"]["template"]["id"]
    resume_ids = [
        client.post(
            "/api/resumes",
            json={
                "documentLocale": "en",
                "title": title,
                "template": template_id,
            },
        ).json()["data"]["resume"]["id"]
        for title in ("First rollback resume", "Second rollback resume")
    ]
    original_write = resume_service._write_resume_json
    write_count = 0

    def fail_second_write(
        resume_id: str,
        version_id: int,
        resume_item: dict,
    ) -> None:
        nonlocal write_count
        write_count += 1
        if write_count == 2:
            raise OSError("simulated rebind write failure")
        original_write(resume_id, version_id, resume_item)

    monkeypatch.setattr(resume_service, "_write_resume_json", fail_second_write)

    with pytest.raises(OSError, match="simulated rebind write failure"):
        template_service.trash_template(template_id)

    with connect() as conn:
        template_row = conn.execute(
            "SELECT deleted FROM templates WHERE id = ?",
            (template_id,),
        ).fetchone()
        resume_rows = conn.execute(
            "SELECT id, current_version_id FROM resumes ORDER BY id"
        ).fetchall()
    assert template_row["deleted"] == 0
    assert {row["id"]: row["current_version_id"] for row in resume_rows} == {
        resume_id: 1 for resume_id in resume_ids
    }
    for resume_id in resume_ids:
        version_path = (
            get_settings().storage_dir / "resumes" / resume_id / "versions" / "2.json"
        )
        assert not version_path.exists()
        stored = client.get(f"/api/resumes/{resume_id}").json()["data"]["resume"]
        assert stored["template"] == template_id


def test_trash_template_cleans_rebind_files_when_default_update_fails(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template_id = client.post(
        "/api/templates",
        json={"template": template_artifact_item(name="Default rollback template")},
    ).json()["data"]["template"]["id"]
    client.put(
        "/api/workspace/default-template",
        json={"documentLocale": "en", "templateId": template_id},
    )
    resume_id = client.post(
        "/api/resumes",
        json={
            "documentLocale": "en",
            "title": "Default rollback resume",
            "template": template_id,
        },
    ).json()["data"]["resume"]["id"]

    def fail_default_update(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated default update failure")

    monkeypatch.setattr(
        template_service,
        "store_default_template_id",
        fail_default_update,
    )

    with pytest.raises(OSError, match="simulated default update failure"):
        template_service.trash_template(template_id)

    with connect() as conn:
        template_row = conn.execute(
            "SELECT deleted FROM templates WHERE id = ?",
            (template_id,),
        ).fetchone()
        resume_row = conn.execute(
            "SELECT current_version_id FROM resumes WHERE id = ?",
            (resume_id,),
        ).fetchone()
        default_template_id = template_service.load_default_template_ids(conn)["en"]
    assert template_row["deleted"] == 0
    assert resume_row["current_version_id"] == 1
    assert default_template_id == template_id
    version_path = (
        get_settings().storage_dir / "resumes" / resume_id / "versions" / "2.json"
    )
    assert not version_path.exists()
    stored = client.get(f"/api/resumes/{resume_id}").json()["data"]["resume"]
    assert stored["template"] == template_id


def test_duplicate_resume_title_keeps_copy_suffix_within_limit(
    client: TestClient,
) -> None:
    source_title = "A" * 50
    source = client.post(
        "/api/resumes",
        json={"documentLocale": "zh", "title": source_title},
    ).json()["data"]["resume"]

    first = client.post(
        f"/api/resumes/{source['id']}/duplicate",
    ).json()["data"]["resume"]
    second = client.post(
        f"/api/resumes/{first['id']}/duplicate",
    ).json()["data"]["resume"]
    third = client.post(
        f"/api/resumes/{second['id']}/duplicate",
    ).json()["data"]["resume"]

    assert len(first["title"]) == 50
    assert first["title"].endswith(" - 副本")
    assert len(second["title"]) == 50
    assert second["title"].endswith(" - 副本（1）")
    assert len(third["title"]) == 50
    assert third["title"].endswith(" - 副本（2）")


def test_concurrent_duplicate_resume_requests_allocate_distinct_titles(
    client: TestClient,
) -> None:
    source = client.post(
        "/api/resumes",
        json={"documentLocale": "en", "title": "Concurrent Resume"},
    ).json()["data"]["resume"]
    start_together = Barrier(2)

    def duplicate_from(test_client: TestClient):
        start_together.wait(timeout=2)
        return test_client.post(f"/api/resumes/{source['id']}/duplicate")

    with closing(TestClient(client.app)) as second_client:
        second_client.headers.update(client.headers)
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = [
                future.result(timeout=10)
                for future in (
                    executor.submit(duplicate_from, client),
                    executor.submit(duplicate_from, second_client),
                )
            ]

    assert [response.status_code for response in responses] == [200, 200]
    assert sorted(
        response.json()["data"]["resume"]["title"] for response in responses
    ) == ["Concurrent Resume - Copy", "Concurrent Resume - Copy(1)"]


def test_duplicate_resume_keeps_prefix_related_copy_families_separate(
    client: TestClient,
) -> None:
    longer_source = client.post(
        "/api/resumes",
        json={"documentLocale": "en", "title": "Backend Engineer"},
    ).json()["data"]["resume"]
    longer_copy = client.post(f"/api/resumes/{longer_source['id']}/duplicate").json()[
        "data"
    ]["resume"]
    shorter_source = client.post(
        "/api/resumes",
        json={"documentLocale": "en", "title": "Backend"},
    ).json()["data"]["resume"]
    shorter_copy = client.post(f"/api/resumes/{shorter_source['id']}/duplicate").json()[
        "data"
    ]["resume"]
    shorter_copy_1 = client.post(f"/api/resumes/{shorter_copy['id']}/duplicate").json()[
        "data"
    ]["resume"]
    shorter_copy_2 = client.post(
        f"/api/resumes/{shorter_copy_1['id']}/duplicate"
    ).json()["data"]["resume"]

    assert longer_copy["title"] == "Backend Engineer - Copy"
    assert shorter_copy_2["title"] == "Backend - Copy(2)"


def test_empty_resume_trash_physically_deletes_resumes_and_agent_sessions(
    client: TestClient,
) -> None:
    first_id = client.post(
        "/api/resumes",
        json={"documentLocale": "en", "title": "First"},
    ).json()["data"]["resume"]["id"]
    second_id = client.post(
        "/api/resumes",
        json={"documentLocale": "en", "title": "Second"},
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
        json={"username": "admin", "password": "TestPassword2026"},
    )
    invalid_response = unauthenticated_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "wrong-password"},
    )

    assert login_response.status_code == 200
    assert "TestPassword2026" not in login_response.text
    login_data = login_response.json()["data"]
    assert login_data["username"] == "admin"
    assert login_data["tokenType"] == "bearer"
    assert login_data["accessToken"]
    assert login_data["expiresAt"]
    assert invalid_response.status_code == 401
    assert invalid_response.json()["code"] == 40001
    assert invalid_response.json()["message"] == "INVALID_CREDENTIALS"


def test_protected_api_requires_jwt(unauthenticated_client: TestClient) -> None:
    response = unauthenticated_client.get("/api/workspace/pages/settings")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["code"] == 40001
    assert response.json()["message"] == "UNAUTHORIZED_REQUEST"
    assert response.json()["data"]["loginUrl"] == "/login"


def test_public_api_paths_only_include_authentication_entry_points() -> None:
    from app.middleware.auth import PUBLIC_API_PATHS

    assert PUBLIC_API_PATHS == {
        "/api/auth/login",
        "/api/auth/setup",
        "/api/auth/oauth/complete",
        "/api/auth/oauth/github/login",
        "/api/auth/oauth/github/callback",
        "/api/auth/oauth/github/setup/callback",
    }


def test_auth_setup_creates_hashed_owner_and_signs_in(
    uninitialized_client: TestClient,
) -> None:
    status_before = uninitialized_client.get("/api/auth/setup")
    setup_response = uninitialized_client.post(
        "/api/auth/setup",
        json={
            "username": " owner_1 ",
            "password": "OwnerPassword1",
            "confirmPassword": "OwnerPassword1",
        },
    )
    status_after = uninitialized_client.get("/api/auth/setup")
    token = setup_response.json()["data"]["accessToken"]
    protected_response = uninitialized_client.get(
        "/api/workspace/pages/settings",
        headers={"Authorization": f"Bearer {token}"},
    )
    with sqlite3.connect(get_auth_db_path()) as conn:
        owner = conn.execute(
            """
            SELECT username, password_hash, auth_revision
            FROM auth_owner
            WHERE id = 1
            """
        ).fetchone()

    settings = get_settings()
    env_content = settings.env_file_path.read_text(encoding="utf-8")

    assert status_before.json()["data"] == {
        "setupRequired": True,
        "githubLoginAvailable": False,
    }
    assert status_before.headers["Cache-Control"] == "no-store"
    assert setup_response.json()["code"] == 0
    assert setup_response.json()["data"]["username"] == "owner_1"
    assert "OwnerPassword1" not in setup_response.text
    assert status_after.json()["data"] == {
        "setupRequired": False,
        "githubLoginAvailable": False,
    }
    assert protected_response.json()["code"] == 0
    assert get_auth_db_path() == get_settings().data_dir / "auth.db"
    assert get_auth_db_path().stat().st_mode & 0o777 == 0o600
    assert owner[0] == "owner_1"
    assert owner[1].startswith("$argon2id$")
    assert "OwnerPassword1" not in owner[1]
    assert owner[2]
    with connect() as conn:
        business_tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_schema WHERE type = 'table'"
            )
        }
    assert "auth_owner" not in business_tables
    assert "AUTH_USERNAME" not in env_content
    assert "AUTH_PASSWORD" not in env_content
    assert "OwnerPassword1" not in env_content


def test_all_environments_require_authentication(
    uninitialized_client: TestClient,
) -> None:
    response = uninitialized_client.get("/api/workspace/pages/settings")

    assert response.status_code == 401
    assert response.json()["code"] == 40001
    assert response.json()["message"] == "UNAUTHORIZED_REQUEST"


def test_auth_setup_can_only_run_once(uninitialized_client: TestClient) -> None:
    first_response = uninitialized_client.post(
        "/api/auth/setup",
        json={
            "username": "first-owner",
            "password": "FirstPassword1",
            "confirmPassword": "FirstPassword1",
        },
    )
    second_response = uninitialized_client.post(
        "/api/auth/setup",
        json={
            "username": "second-owner",
            "password": "SecondPassword2",
            "confirmPassword": "SecondPassword2",
        },
    )
    second_login = uninitialized_client.post(
        "/api/auth/login",
        json={"username": "second-owner", "password": "SecondPassword2"},
    )

    assert first_response.json()["code"] == 0
    assert second_response.status_code == 409
    assert second_response.json()["code"] == 40000
    assert second_response.json()["message"] == "SETUP_ALREADY_COMPLETED"
    assert second_login.status_code == 401
    assert second_login.json()["message"] == "INVALID_CREDENTIALS"


@pytest.mark.parametrize(
    ("payload", "expected_message"),
    [
        (
            {
                "username": " ",
                "password": "ValidPassword1",
                "confirmPassword": "ValidPassword1",
            },
            "USERNAME_REQUIRED",
        ),
        (
            {
                "username": "a!",
                "password": "ValidPassword1",
                "confirmPassword": "ValidPassword1",
            },
            "USERNAME_INVALID",
        ),
        (
            {"username": "owner", "password": "", "confirmPassword": ""},
            "PASSWORD_REQUIRED",
        ),
        (
            {
                "username": "owner",
                "password": "Pass1",
                "confirmPassword": "Pass1",
            },
            "PASSWORD_TOO_SHORT",
        ),
        (
            {
                "username": "owner",
                "password": "OnlyLetters",
                "confirmPassword": "OnlyLetters",
            },
            "PASSWORD_COMPLEXITY_REQUIRED",
        ),
        (
            {
                "username": "owner",
                "password": "ValidPassword1",
                "confirmPassword": "DifferentPassword2",
            },
            "PASSWORD_CONFIRMATION_MISMATCH",
        ),
    ],
)
def test_auth_setup_validates_owner_credentials(
    uninitialized_client: TestClient,
    payload: dict[str, str],
    expected_message: str,
) -> None:
    response = uninitialized_client.post("/api/auth/setup", json=payload)

    assert response.status_code == 400
    assert response.json()["code"] == 40000
    assert response.json()["message"] == expected_message
    assert uninitialized_client.get("/api/auth/setup").json()["data"] == {
        "setupRequired": True,
        "githubLoginAvailable": False,
    }


def test_auth_setup_rejects_non_loopback_client(
    uninitialized_client: TestClient,
) -> None:
    remote_client = TestClient(
        uninitialized_client.app,
        client=("192.168.1.20", 50000),
    )
    try:
        response = remote_client.post(
            "/api/auth/setup",
            json={
                "username": "owner",
                "password": "OwnerPassword1",
                "confirmPassword": "OwnerPassword1",
            },
        )
    finally:
        remote_client.close()

    assert response.status_code == 403
    assert response.json()["code"] == 40000
    assert response.json()["message"] == "SETUP_LOCAL_ONLY"
    assert uninitialized_client.get("/api/auth/setup").json()["data"] == {
        "setupRequired": True,
        "githubLoginAvailable": False,
    }


def test_auth_database_must_not_share_the_business_database_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.main import create_app

    shared_db_path = tmp_path / "auth.db"
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_DB_PATH", str(shared_db_path))
    monkeypatch.setenv("APP_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("APP_ENV_FILE", str(tmp_path / ".env"))
    get_settings.cache_clear()

    with pytest.raises(
        RuntimeError,
        match="APP_DB_PATH must not point to APP_DATA_DIR/auth.db",
    ):
        with TestClient(
            create_app(),
            client=("127.0.0.1", 50000),
        ):
            pass

    get_settings.cache_clear()
    assert not shared_db_path.exists()


def test_auth_setup_preserves_password_whitespace(
    uninitialized_client: TestClient,
) -> None:
    password = " OwnerPassword1 "
    uninitialized_client.post(
        "/api/auth/setup",
        json={
            "username": "owner",
            "password": password,
            "confirmPassword": password,
        },
    )

    exact_login = uninitialized_client.post(
        "/api/auth/login",
        json={"username": "owner", "password": password},
    )
    trimmed_login = uninitialized_client.post(
        "/api/auth/login",
        json={"username": "owner", "password": password.strip()},
    )

    assert exact_login.json()["code"] == 0
    assert trimmed_login.json()["message"] == "INVALID_CREDENTIALS"


def test_auth_service_initializes_fresh_database_without_app_lifespan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.services.auth_accounts import (
        OwnerAlreadyExistsError,
        create_owner,
    )

    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("APP_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("APP_ENV_FILE", str(tmp_path / ".env"))
    get_settings.cache_clear()
    get_settings()
    barrier = Barrier(2)

    def create(username: str) -> str:
        barrier.wait(timeout=5)
        try:
            return create_owner(username, "ServicePassword1").username
        except OwnerAlreadyExistsError:
            return "already-exists"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(create, ("service-one", "service-two"), timeout=10))

    get_settings.cache_clear()
    assert get_auth_db_path().exists()
    assert results.count("already-exists") == 1


@pytest.mark.parametrize("_round", range(20))
def test_auth_setup_is_atomic_under_concurrent_requests(
    uninitialized_client: TestClient,
    _round: int,
) -> None:
    barrier = Barrier(2)

    def submit_setup(username: str) -> dict:
        barrier.wait(timeout=5)
        return uninitialized_client.post(
            "/api/auth/setup",
            json={
                "username": username,
                "password": "ConcurrentPassword1",
                "confirmPassword": "ConcurrentPassword1",
            },
        ).json()

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(submit_setup, ("owner-one", "owner-two"), timeout=10)
        )

    with sqlite3.connect(get_auth_db_path()) as conn:
        owner_count = conn.execute("SELECT COUNT(*) FROM auth_owner").fetchone()[0]

    assert sorted(response["code"] for response in responses) == [0, 40000]
    assert {response["message"] for response in responses if response["code"] != 0} == {
        "SETUP_ALREADY_COMPLETED"
    }
    assert owner_count == 1


def test_old_jwt_cannot_authenticate_against_replaced_auth_database(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.main import create_app

    env_file = tmp_path / ".env"
    monkeypatch.delenv("RESENO_MASTER_KEY", raising=False)
    monkeypatch.delenv("RESENO_JWT_SECRET", raising=False)
    first_data_dir = tmp_path / "first-data"
    replacement_data_dir = tmp_path / "replacement-data"
    business_db_path = tmp_path / "app.db"
    monkeypatch.setenv("APP_DATA_DIR", str(first_data_dir))
    monkeypatch.setenv("APP_STORAGE_DIR", str(first_data_dir / "storage"))
    monkeypatch.setenv("APP_ENV_FILE", str(env_file))
    monkeypatch.setenv("APP_DB_PATH", str(business_db_path))
    get_settings.cache_clear()

    with TestClient(
        create_app(),
        client=("127.0.0.1", 50000),
    ) as first_client:
        first_setup = first_client.post(
            "/api/auth/setup",
            json={
                "username": "first-owner",
                "password": "FirstPassword1",
                "confirmPassword": "FirstPassword1",
            },
        )
        old_token = first_setup.json()["data"]["accessToken"]

    original_env = env_file.read_bytes()
    monkeypatch.setenv("RESENO_MASTER_KEY", "")
    monkeypatch.setenv("RESENO_JWT_SECRET", "")
    monkeypatch.setenv("APP_DATA_DIR", str(replacement_data_dir))
    monkeypatch.setenv("APP_STORAGE_DIR", str(replacement_data_dir / "storage"))
    get_settings.cache_clear()

    with TestClient(
        create_app(),
        client=("127.0.0.1", 50000),
    ) as replacement_client:
        old_token_response = replacement_client.get(
            "/api/workspace/pages/settings",
            headers={"Authorization": f"Bearer {old_token}"},
        )
        setup_status = replacement_client.get("/api/auth/setup")
        replacement_setup = replacement_client.post(
            "/api/auth/setup",
            json={
                "username": "first-owner",
                "password": "FirstPassword1",
                "confirmPassword": "FirstPassword1",
            },
        )
        replacement_token = replacement_setup.json()["data"]["accessToken"]
        old_token_after_setup = replacement_client.get(
            "/api/workspace/pages/settings",
            headers={"Authorization": f"Bearer {old_token}"},
        )
        replacement_token_response = replacement_client.get(
            "/api/workspace/pages/settings",
            headers={"Authorization": f"Bearer {replacement_token}"},
        )

    get_settings.cache_clear()

    assert old_token_response.json()["code"] == 40001
    assert setup_status.json()["data"] == {
        "setupRequired": True,
        "githubLoginAvailable": False,
    }
    assert old_token_after_setup.json()["code"] == 40001
    assert replacement_token_response.json()["code"] == 0
    old_payload = decode_access_token(old_token)
    replacement_payload = decode_access_token(replacement_token)
    assert old_payload.subject == replacement_payload.subject == "first-owner"
    assert old_payload.auth_revision != replacement_payload.auth_revision
    assert env_file.read_bytes() == original_env


def test_auth_refresh_revokes_previous_jwt(
    unauthenticated_client: TestClient,
) -> None:
    login_response = unauthenticated_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "TestPassword2026"},
    )
    old_token = login_response.json()["data"]["accessToken"]
    refresh_response = unauthenticated_client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {old_token}"},
        json={},
    )
    new_token = refresh_response.json()["data"]["accessToken"]
    old_token_response = unauthenticated_client.get(
        "/api/workspace/pages/settings",
        headers={"Authorization": f"Bearer {old_token}"},
    )
    new_token_response = unauthenticated_client.get(
        "/api/workspace/pages/settings",
        headers={"Authorization": f"Bearer {new_token}"},
    )

    assert refresh_response.status_code == 200
    assert new_token != old_token
    assert old_token_response.status_code == 401
    assert old_token_response.json()["code"] == 40001
    assert old_token_response.json()["message"] == "UNAUTHORIZED_REQUEST"
    assert new_token_response.status_code == 200
    assert new_token_response.json()["code"] == 0


def test_auth_password_update_stores_hash_and_revokes_all_tokens(
    unauthenticated_client: TestClient,
) -> None:
    settings = get_settings()
    with sqlite3.connect(get_auth_db_path()) as conn:
        previous_revision = conn.execute(
            "SELECT auth_revision FROM auth_owner WHERE id = 1"
        ).fetchone()[0]
    first_login_response = unauthenticated_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "TestPassword2026"},
    )
    second_login_response = unauthenticated_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "TestPassword2026"},
    )
    first_token = first_login_response.json()["data"]["accessToken"]
    second_token = second_login_response.json()["data"]["accessToken"]
    update_response = unauthenticated_client.post(
        "/api/auth/password",
        headers={"Authorization": f"Bearer {first_token}"},
        json={
            "currentPassword": "TestPassword2026",
            "newPassword": "Changed@2026",
            "confirmPassword": "Changed@2026",
        },
    )
    old_login_response = unauthenticated_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "TestPassword2026"},
    )
    new_login_response = unauthenticated_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "Changed@2026"},
    )
    first_token_response = unauthenticated_client.get(
        "/api/workspace/pages/settings",
        headers={"Authorization": f"Bearer {first_token}"},
    )
    second_token_response = unauthenticated_client.get(
        "/api/workspace/pages/settings",
        headers={"Authorization": f"Bearer {second_token}"},
    )
    with sqlite3.connect(get_auth_db_path()) as conn:
        password_hash, current_revision = conn.execute(
            """
            SELECT password_hash, auth_revision
            FROM auth_owner
            WHERE id = 1
            """
        ).fetchone()
    env_content = settings.env_file_path.read_text(encoding="utf-8")

    assert update_response.status_code == 200
    assert update_response.json()["code"] == 0
    assert update_response.json()["data"] == {"username": "admin", "updated": True}
    assert password_hash.startswith("$argon2id$")
    assert "Changed@2026" not in password_hash
    assert current_revision != previous_revision
    assert "Changed@2026" not in env_content
    assert "TestPassword2026" not in env_content
    assert old_login_response.json()["code"] == 40001
    assert old_login_response.json()["message"] == "INVALID_CREDENTIALS"
    assert new_login_response.json()["code"] == 0
    assert first_token_response.json()["code"] == 40001
    assert second_token_response.json()["code"] == 40001


def test_auth_password_update_validates_confirmation(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/auth/password",
        json={
            "currentPassword": "TestPassword2026",
            "newPassword": "Changed@2026",
            "confirmPassword": "Mismatch@2026",
        },
    )

    assert response.status_code == 400
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
    session_response = client.get("/api/workspace/pages/settings")

    assert response.status_code == 400
    assert response.json()["code"] == 40000
    assert response.json()["message"] == "INVALID_CREDENTIALS"
    assert session_response.json()["code"] == 0


def test_expired_jwt_is_rejected(client: TestClient) -> None:
    expired_token, _ = create_access_token(
        "admin",
        "expired-revision",
        ttl_seconds=-1,
    )
    response = client.get(
        "/api/workspace/pages/settings",
        headers={"Authorization": f"Bearer {expired_token}"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == 40001
    assert response.json()["message"] == "UNAUTHORIZED_REQUEST"


def test_template_command_flow_owns_identity_and_lifecycle(
    client: TestClient,
) -> None:
    create_response = client.post(
        "/api/templates",
        json={"template": template_artifact_item()},
    )

    assert create_response.status_code == 200
    created = create_response.json()["data"]["template"]
    template_id = created["id"]
    assert re.fullmatch(r"template-[A-Za-z0-9]{16}", template_id)
    assert created["updatedAt"]
    assert created["isBuiltIn"] is False

    update_payload = {
        **portable_template_definition(created),
        "name": "Backend Template",
    }
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
        json={"documentLocale": "en", "templateId": template_id},
    )
    trash_response = client.post(f"/api/templates/{template_id}/trash")
    templates_page_response = client.get("/api/workspace/pages/templates")
    deleted_response = client.get("/api/templates?status=deleted")
    set_deleted_default_response = client.put(
        "/api/workspace/default-template",
        json={"documentLocale": "en", "templateId": template_id},
    )

    assert default_response.status_code == 200
    assert default_response.json()["data"]["defaultTemplateIds"] == {
        "zh": "minimal",
        "en": template_id,
    }
    assert trash_response.status_code == 200
    assert trash_response.json()["data"]["template"]["deletedAt"]
    assert templates_page_response.json()["data"]["defaultTemplateIds"] == {
        "zh": "minimal",
        "en": "minimal",
    }
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


def test_template_image_sources_require_uploaded_data_urls(
    client: TestClient,
) -> None:
    template = template_artifact_item(name="Template image sources")
    image = {
        "id": "image-1",
        "name": "Image 1",
        "src": "https://images.example.invalid/remote.png",
        "alt": "",
        "x": 14,
        "y": 18,
        "width": 30,
        "height": 20,
        "opacity": 1,
        "borderWidth": 0,
        "borderColor": "#d4d4d8",
        "borderRadius": 8,
        "objectFit": "contain",
        "visible": True,
    }
    template["layout"]["images"] = [image]

    remote_response = client.post(
        "/api/templates",
        json={"template": template},
    )

    assert remote_response.status_code == 422
    assert remote_response.json()["code"] == 40002
    assert remote_response.json()["message"] == "VALIDATION_ERROR"
    assert remote_response.json()["data"]["errors"][0]["loc"][-1] == "src"

    template["layout"]["images"] = [
        {
            **image,
            "src": "data:image/gif;base64,R0lGODlhAQABAAAAACw=",
        }
    ]
    upload_response = client.post(
        "/api/templates",
        json={"template": template},
    )

    assert upload_response.status_code == 200
    images = upload_response.json()["data"]["template"]["layout"]["images"]
    assert images[0]["src"] == "data:image/gif;base64,R0lGODlhAQABAAAAACw="


@pytest.mark.parametrize(
    ("x", "y", "width", "height", "message_fragment"),
    [
        (181, 18, 30, 20, "page width"),
        (14, 278, 30, 20, "page height"),
    ],
)
def test_template_images_must_fit_within_the_a4_page(
    client: TestClient,
    x: float,
    y: float,
    width: float,
    height: float,
    message_fragment: str,
) -> None:
    template = template_artifact_item(name="Bounded template image")
    template["layout"]["images"] = [
        {
            "id": "image-1",
            "name": "Image 1",
            "src": "",
            "alt": "",
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "opacity": 1,
            "borderWidth": 0,
            "borderColor": "#d4d4d8",
            "borderRadius": 8,
            "objectFit": "contain",
            "visible": True,
        }
    ]

    response = client.post("/api/templates", json={"template": template})

    assert response.status_code == 422
    assert response.json()["code"] == 40002
    error = response.json()["data"]["errors"][0]
    assert error["loc"][-3:] == ["layout", "images", 0]
    assert message_fragment in error["msg"]


def test_template_images_accept_the_exact_a4_page_edge(
    client: TestClient,
) -> None:
    template = template_artifact_item(name="Edge aligned template image")
    template["layout"]["images"] = [
        {
            "id": "image-1",
            "name": "Image 1",
            "src": "",
            "alt": "",
            "x": 180,
            "y": 277,
            "width": 30,
            "height": 20,
            "opacity": 1,
            "borderWidth": 0,
            "borderColor": "#d4d4d8",
            "borderRadius": 8,
            "objectFit": "contain",
            "visible": True,
        }
    ]

    response = client.post("/api/templates", json={"template": template})

    assert response.status_code == 200
    assert response.json()["code"] == 0


def test_template_save_does_not_create_resume_versions(
    client: TestClient,
) -> None:
    create_response = client.post(
        "/api/templates",
        json={"template": template_artifact_item(name="Versionless Template")},
    )

    assert create_response.status_code == 200
    created = create_response.json()["data"]["template"]
    template_id = created["id"]

    update_payload = {
        **portable_template_definition(created),
        "name": "Versionless Template Updated",
        "settings": {
            **created["settings"],
            "bodyLineHeight": 1.65,
        },
    }
    update_response = client.put(
        f"/api/templates/{template_id}",
        json={"template": update_payload},
    )

    assert update_response.status_code == 200
    assert (
        update_response.json()["data"]["template"]["name"]
        == "Versionless Template Updated"
    )

    template_path = (
        get_settings().storage_dir / "templates" / template_id / "current.json"
    )
    stored_template = json.loads(template_path.read_text(encoding="utf-8"))

    assert stored_template["name"] == "Versionless Template Updated"
    assert stored_template["settings"]["bodyLineHeight"] == 1.65

    with connect() as conn:
        version_count = conn.execute(
            "SELECT COUNT(*) AS version_count FROM resume_versions"
        ).fetchone()["version_count"]

    assert version_count == 0


def test_empty_template_trash_physically_deletes_templates(
    client: TestClient,
) -> None:
    first_id = client.post(
        "/api/templates",
        json={"template": template_artifact_item(name="First")},
    ).json()["data"]["template"]["id"]
    second_id = client.post(
        "/api/templates",
        json={"template": template_artifact_item(name="Second")},
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
            "defaultModelConfigId": "llm-settings",
            "responseLanguage": "zh",
            "behaviorMode": "strict",
            "confirmationMode": "suggestOnly",
        },
    }

    response = client.put(
        "/api/workspace/user-settings?locale=zh",
        json={"settings": settings},
    )
    settings_page_response = client.get("/api/workspace/pages/settings")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "agentSettings": {
            "defaultModelConfigId": "llm-settings",
            "responseLanguage": "zh",
            "behaviorMode": "strict",
            "confirmationMode": "suggestOnly",
        },
        "locale": "zh",
        "theme": "system",
    }
    assert settings_page_response.status_code == 200
    settings_page_data = settings_page_response.json()["data"]
    assert settings_page_data["theme"] == "system"
    assert (
        settings_page_data["agentSettings"] == response.json()["data"]["agentSettings"]
    )

    persisted_settings = json.loads(
        get_settings().user_settings_path.read_text(encoding="utf-8")
    )
    assert (
        persisted_settings["agentSettings"] == response.json()["data"]["agentSettings"]
    )
    assert persisted_settings["locale"] == "zh"
    assert persisted_settings["theme"] == "system"


def test_user_settings_endpoint_rejects_ambiguous_model_id_field(
    client: TestClient,
) -> None:
    response = client.put(
        "/api/workspace/user-settings?locale=zh",
        json={
            "settings": {
                "agentSettings": {
                    "defaultModelId": "llm-settings",
                },
            },
        },
    )

    assert response.status_code == 422


def test_settings_page_discards_unknown_persisted_agent_fields(
    client: TestClient,
) -> None:
    get_settings().user_settings_path.write_text(
        json.dumps(
            {
                "locale": "zh",
                "agentSettings": {
                    "defaultModelId": "llm-settings",
                },
            }
        ),
        encoding="utf-8",
    )

    response = client.get("/api/workspace/pages/settings")

    assert response.status_code == 200
    agent_settings = response.json()["data"]["agentSettings"]
    assert agent_settings["defaultModelConfigId"] == ""
    assert "defaultModelId" not in agent_settings


def test_user_settings_endpoint_rejects_workspace_resource_fields(
    client: TestClient,
) -> None:
    response = client.put(
        "/api/workspace/user-settings?locale=zh",
        json={"settings": {"resumes": []}},
    )

    assert response.status_code == 422
    assert response.json()["code"] != 0
    assert response.json()["message"] == "VALIDATION_ERROR"


def test_user_settings_updates_serialize_the_read_modify_write_transaction(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_load = user_preferences.load_user_settings
    first_load_entered = Event()
    second_load_entered = Event()
    allow_first_load = Event()
    call_lock = Lock()
    load_calls = 0

    def controlled_load() -> dict[str, object]:
        nonlocal load_calls
        with call_lock:
            load_calls += 1
            call_number = load_calls

        if call_number == 1:
            first_load_entered.set()
            assert allow_first_load.wait(timeout=2)
        elif call_number == 2:
            second_load_entered.set()

        return original_load()

    monkeypatch.setattr(user_preferences, "load_user_settings", controlled_load)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            user_preferences.save_user_settings,
            "en",
            {"theme": "dark"},
        )
        assert first_load_entered.wait(timeout=2)
        second = executor.submit(
            user_preferences.save_user_settings,
            "zh",
            {
                "agentSettings": {
                    "responseLanguage": "zh",
                    "behaviorMode": "strict",
                    "confirmationMode": "suggestOnly",
                }
            },
        )

        # The second request must wait outside the entire read-modify-write section.
        assert not second_load_entered.wait(timeout=0.05)
        allow_first_load.set()
        first.result(timeout=2)
        second.result(timeout=2)

    persisted = json.loads(
        get_settings().user_settings_path.read_text(encoding="utf-8")
    )
    assert persisted["locale"] == "zh"
    assert persisted["theme"] == "dark"
    assert persisted["agentSettings"]["behaviorMode"] == "strict"


def test_identical_resume_hash_does_not_create_new_version(
    client: TestClient,
) -> None:
    create_response = client.post(
        "/api/resumes",
        json={
            "documentLocale": "en",
            "title": "Hash Stable",
            "resume": minimal_resume_item("ignored", "Hash Stable")["resume"],
            "template": "minimal",
        },
    )
    resume = create_response.json()["data"]["resume"]
    resume_id = resume["id"]
    save_payload = resume_save_payload(resume, templateSettings=None)

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


def test_resume_autosave_persists_without_creating_history_version(
    client: TestClient,
) -> None:
    create_response = client.post(
        "/api/resumes",
        json={
            "documentLocale": "en",
            "title": "Autosave Draft",
            "resume": minimal_resume_item("ignored", "Initial Name")["resume"],
            "template": "minimal",
        },
    )
    created = create_response.json()["data"]
    resume = created["resume"]
    resume_id = resume["id"]
    autosave_payload = resume_save_payload(
        resume,
        resume={
            **resume["resume"],
            "basic": {
                **resume["resume"]["basic"],
                "name": "Latest Autosaved Name",
            },
        },
        templateSettings=None,
    )

    autosave_response = client.put(
        f"/api/resumes/{resume_id}?saveMode=autosave",
        json=autosave_payload,
    )
    detail_response = client.get(f"/api/resumes/{resume_id}")
    versions_after_autosave = client.get(f"/api/resumes/{resume_id}/versions")

    assert autosave_response.status_code == 200
    autosave_version_id = autosave_response.json()["data"]["versionId"]
    assert (
        detail_response.json()["data"]["resume"]["resume"]["basic"]["name"]
        == "Latest Autosaved Name"
    )
    assert [
        item["versionId"] for item in versions_after_autosave.json()["data"]["versions"]
    ] == ["1"]

    latest_autosave_payload = {
        **autosave_payload,
        "resume": {
            **autosave_payload["resume"],
            "basic": {
                **autosave_payload["resume"]["basic"],
                "name": "Newest Autosaved Name",
            },
        },
    }
    latest_autosave_response = client.put(
        f"/api/resumes/{resume_id}?saveMode=autosave",
        json=latest_autosave_payload,
    )
    latest_autosave_version_id = latest_autosave_response.json()["data"]["versionId"]
    versions_after_latest_autosave = client.get(f"/api/resumes/{resume_id}/versions")
    versions_dir = get_settings().storage_dir / "resumes" / resume_id / "versions"

    assert latest_autosave_version_id != autosave_version_id
    assert [
        item["versionId"]
        for item in versions_after_latest_autosave.json()["data"]["versions"]
    ] == ["1"]
    assert not (versions_dir / f"{autosave_version_id}.json").exists()
    assert (versions_dir / f"{latest_autosave_version_id}.json").exists()

    checkpoint_response = client.put(
        f"/api/resumes/{resume_id}?saveMode=checkpoint",
        json=latest_autosave_payload,
    )
    versions_after_checkpoint = client.get(f"/api/resumes/{resume_id}/versions")

    assert checkpoint_response.status_code == 200
    assert [
        item["versionId"]
        for item in versions_after_checkpoint.json()["data"]["versions"]
    ] == [latest_autosave_version_id, "1"]
    assert checkpoint_response.json()["data"]["versionId"] == latest_autosave_version_id


def test_env_secrets_generated_once(client: TestClient, monkeypatch) -> None:
    settings = get_settings()
    first_content = settings.env_file_path.read_bytes()
    secrets = dotenv_values(settings.env_file_path, interpolate=False)
    monkeypatch.setenv("RESENO_MASTER_KEY", "")
    monkeypatch.setenv("RESENO_JWT_SECRET", "")

    get_settings.cache_clear()
    second_settings = get_settings()

    assert second_settings.env_file_path == settings.env_file_path
    assert settings.env_file_path.read_bytes() == first_content
    assert set(secrets) == {"RESENO_MASTER_KEY", "RESENO_JWT_SECRET"}
    assert settings.env_file_path.stat().st_mode & 0o777 == 0o600
    assert secrets["RESENO_MASTER_KEY"]
    assert secrets["RESENO_JWT_SECRET"]
    Fernet(secrets["RESENO_MASTER_KEY"].encode("ascii"))
    assert len(secrets["RESENO_JWT_SECRET"].encode("utf-8")) >= 32


def test_existing_env_secrets_are_not_rewritten(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    original_config = (
        "CUSTOM_VALUE=preserved\n"
        f"RESENO_MASTER_KEY={Fernet.generate_key().decode('ascii')}\n"
        f"RESENO_JWT_SECRET={'x' * 48}\n"
    )
    monkeypatch.delenv("CUSTOM_VALUE", raising=False)
    env_file.write_text(original_config, encoding="utf-8")
    monkeypatch.delenv("RESENO_MASTER_KEY", raising=False)
    monkeypatch.delenv("RESENO_JWT_SECRET", raising=False)
    monkeypatch.setenv("APP_ENV_FILE", str(env_file))
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()

    first_settings = get_settings()
    get_settings.cache_clear()
    second_settings = get_settings()

    assert first_settings.env_file_path == second_settings.env_file_path == env_file
    assert env_file.read_text(encoding="utf-8") == original_config


def test_default_env_stays_separate_from_runtime_data(
    tmp_path, monkeypatch,
) -> None:
    from app import config

    default_env = tmp_path / "project" / ".env"
    data_dir = tmp_path / "data"
    monkeypatch.setattr(config, "DEFAULT_ENV_PATH", default_env)
    monkeypatch.delenv("APP_ENV_FILE", raising=False)
    monkeypatch.setenv("APP_DATA_DIR", str(data_dir))
    get_settings.cache_clear()

    settings = config.initialize_settings()

    assert settings.env_file_path == default_env
    assert settings.data_dir == data_dir
    assert set(dotenv_values(default_env, interpolate=False)) == {
        "RESENO_MASTER_KEY", "RESENO_JWT_SECRET",
    }
    assert not default_env.is_relative_to(data_dir)


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


def test_ensure_database_schema_rejects_unversioned_nonempty_database(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.db.schema import (
        UnsupportedDatabaseSchemaError,
        ensure_database_schema,
    )

    db_path = tmp_path / "app.db"
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_DB_PATH", str(db_path))
    monkeypatch.setenv("APP_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("APP_ENV_FILE", str(tmp_path / ".env"))
    get_settings.cache_clear()
    ensure_database_schema()

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA user_version = 0")
        conn.execute(
            """
            INSERT INTO workspace_state (id, default_template_zh)
            VALUES (1, 'classic')
            """
        )

    with pytest.raises(UnsupportedDatabaseSchemaError) as exc_info:
        ensure_database_schema()

    with sqlite3.connect(db_path) as conn:
        user_version = conn.execute("PRAGMA user_version").fetchone()[0]
        default_template_id = conn.execute(
            "SELECT default_template_zh FROM workspace_state WHERE id = 1"
        ).fetchone()[0]

    assert str(db_path) in str(exc_info.value)
    assert "data was left unchanged" in str(exc_info.value).lower()
    assert user_version == 0
    assert default_template_id == "classic"
    get_settings.cache_clear()


def test_ensure_database_schema_rejects_modified_index_without_repairing_it(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.db.schema import (
        UnsupportedDatabaseSchemaError,
        ensure_database_schema,
    )

    db_path = tmp_path / "app.db"
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_DB_PATH", str(db_path))
    monkeypatch.setenv("APP_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("APP_ENV_FILE", str(tmp_path / ".env"))
    get_settings.cache_clear()
    ensure_database_schema()

    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP INDEX idx_resumes_status")
        conn.execute("CREATE INDEX idx_resumes_status ON resumes(title)")

    with pytest.raises(UnsupportedDatabaseSchemaError):
        ensure_database_schema()

    with sqlite3.connect(db_path) as conn:
        indexed_columns = [
            row[2] for row in conn.execute("PRAGMA index_info(idx_resumes_status)")
        ]
        stored_user_version = conn.execute("PRAGMA user_version").fetchone()[0]

    assert indexed_columns == ["title"]
    assert stored_user_version == 1
    get_settings.cache_clear()


def test_ensure_database_schema_rejects_mismatched_version_without_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.db.schema import (
        UnsupportedDatabaseSchemaError,
        ensure_database_schema,
    )

    db_path = tmp_path / "app.db"
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_DB_PATH", str(db_path))
    monkeypatch.setenv("APP_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("APP_ENV_FILE", str(tmp_path / ".env"))
    get_settings.cache_clear()
    ensure_database_schema()

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA user_version = 2")

    with pytest.raises(UnsupportedDatabaseSchemaError):
        ensure_database_schema()

    with sqlite3.connect(db_path) as conn:
        user_version = conn.execute("PRAGMA user_version").fetchone()[0]

    assert user_version == 2
    get_settings.cache_clear()


def test_model_config_resolves_litellm_token_limits(
    client: TestClient,
    monkeypatch,
) -> None:
    from app.services import model_metadata

    model_metadata._CATALOG_CACHE = None
    monkeypatch.setattr(
        model_metadata,
        "_fetch_catalog",
        AsyncMock(
            return_value={
                "openai/gpt-5.1": {
                    "litellm_provider": "openai",
                    "max_input_tokens": 131072,
                    "max_output_tokens": 8192,
                },
                "openai/gpt-proxy": {
                    "litellm_provider": "azure_ai",
                    "max_input_tokens": 9999999,
                },
            }
        ),
    )
    assert asyncio.run(model_metadata.refresh_model_metadata_cache()) is True

    rejected = client.post(
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

    assert rejected.status_code == 400
    assert rejected.json()["message"] == "MODEL_CONFIG_MAX_TOKENS_EXCEEDS_LIMIT"

    invalid = client.post(
        "/api/model-configs",
        json={
            "provider": "openai",
            "providerKind": "custom",
            "apiFamily": "openai_compatible_chat",
            "nickname": "Unknown Model",
            "apiKey": "sk-custom-secret",
            "model": "unknown-model",
            "apiUrl": "https://example.test/v1",
            "maxTokens": 0,
        },
    )

    assert invalid.status_code == 422

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
            "maxTokens": 8192,
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


def test_model_config_rejects_output_limit_above_javascript_safe_integer(
    client: TestClient,
) -> None:
    payload = {
        "provider": "openai",
        "providerKind": "custom",
        "apiFamily": "openai_compatible_chat",
        "nickname": "Unknown Model",
        "apiKey": "sk-custom-secret",
        "model": "unknown-model",
        "apiUrl": "https://example.test/v1",
    }

    accepted = client.post(
        "/api/model-configs",
        json={**payload, "maxTokens": 9_007_199_254_740_991},
    )
    rejected = client.post(
        "/api/model-configs",
        json={**payload, "maxTokens": 9_007_199_254_740_992},
    )

    assert accepted.status_code == 200
    assert accepted.json()["data"]["maxTokens"] == 9_007_199_254_740_991
    assert rejected.status_code == 422
    assert rejected.json()["message"] == "VALIDATION_ERROR"


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
                thinking_control="provider_default",
                metadata_source="provider",
            ),
        ],
    )

    rejected = client.post(
        "/api/model-configs",
        json={
            "provider": "openai",
            "providerKind": "cloud",
            "apiFamily": "openai_responses",
            "nickname": "Cloud",
            "apiKey": "sk-cloud-secret",
            "model": "gpt-cloud",
            "apiUrl": "https://api.openai.com/v1",
            "maxTokens": 8193,
        },
    )

    assert rejected.status_code == 400
    assert rejected.json()["message"] == "MODEL_CONFIG_MAX_TOKENS_EXCEEDS_LIMIT"

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
    assert data["maxTokens"] == 4096
    assert data["contextWindowTokens"] == 131072
    assert data["supportsImage"] is True
    assert data["supportsThinking"] is True
    assert data["supportsTools"] is True
    assert data["supportsStreaming"] is True
    assert "thinkingEnabled" not in data

    with connect() as conn:
        row = conn.execute(
            """
            SELECT
                temperature,
                top_p,
                max_tokens,
                supports_tools,
                supports_streaming,
                encrypted_api_key
            FROM llm_configs
            WHERE client_id = ?
            """,
            (data["id"],),
        ).fetchone()

    assert row is not None
    assert row["temperature"] is None
    assert row["top_p"] is None
    assert row["max_tokens"] == 4096
    assert row["supports_tools"] == 1
    assert row["supports_streaming"] == 1
    encrypted_api_key = row["encrypted_api_key"]

    auto_response = client.post(
        "/api/model-configs",
        json={
            **data,
            "apiKey": "",
            "maxTokens": None,
        },
    )

    assert auto_response.status_code == 200
    assert auto_response.json()["data"]["maxTokens"] is None

    with connect() as conn:
        auto_row = conn.execute(
            """
            SELECT max_tokens, encrypted_api_key
            FROM llm_configs
            WHERE client_id = ?
            """,
            (data["id"],),
        ).fetchone()

    assert auto_row is not None
    assert auto_row["max_tokens"] is None
    assert auto_row["encrypted_api_key"] == encrypted_api_key


def test_anthropic_config_update_replaces_legacy_thinking_with_current_capability(
    client: TestClient,
) -> None:
    write_cached_provider_models(
        "anthropic",
        [
            DiscoveredModel(
                id="claude-example",
                label="claude-example",
                context_window_tokens=200_000,
                max_output_tokens=64_000,
                supports_image=True,
                thinking_control="none",
                metadata_source="provider",
            ),
        ],
    )
    response = client.post(
        "/api/model-configs",
        json={
            "provider": "anthropic",
            "providerKind": "cloud",
            "apiFamily": "anthropic_messages",
            "nickname": "Anthropic",
            "apiKey": "anthropic-secret",
            "model": "claude-example",
            "apiUrl": "https://api.anthropic.com/v1",
        },
    )
    assert response.status_code == 200
    saved = response.json()["data"]

    with connect() as conn:
        conn.execute(
            "UPDATE llm_configs SET supports_thinking = 1 WHERE client_id = ?",
            (saved["id"],),
        )

    updated = client.post(
        "/api/model-configs",
        json={
            **saved,
            "nickname": "Anthropic Updated",
            "apiKey": None,
        },
    )

    assert updated.status_code == 200
    assert updated.json()["data"]["supportsThinking"] is False

    with connect() as conn:
        persisted = conn.execute(
            "SELECT supports_thinking FROM llm_configs WHERE client_id = ?",
            (saved["id"],),
        ).fetchone()

    assert persisted is not None
    assert persisted["supports_thinking"] == 0


def test_google_cloud_config_uses_manifest_v1_end_to_end(
    client: TestClient,
) -> None:
    from app.services.llm.config import resolve_agent_llm_config

    write_cached_provider_models(
        "google",
        [
            DiscoveredModel(
                id="gemini-3.6-flash",
                label="gemini-3.6-flash",
                context_window_tokens=1_000_000,
                max_output_tokens=65_536,
                supports_image=True,
                thinking_control="provider_default",
                metadata_source="provider",
            ),
        ],
    )
    response = client.post(
        "/api/model-configs",
        json={
            "provider": "google",
            "providerKind": "cloud",
            "apiFamily": "google_gemini",
            "nickname": "Gemini Stable",
            "apiKey": "google-v1-secret",
            "model": "gemini-3.6-flash",
            "apiUrl": "https://obsolete.example/google",
        },
    )

    assert response.status_code == 200
    saved = response.json()["data"]
    assert saved["apiUrl"] == "https://generativelanguage.googleapis.com/v1"
    config_id = saved["id"]
    key_preview = saved["apiKeyPreview"]

    with connect() as conn:
        stored = conn.execute(
            "SELECT base_url FROM llm_configs WHERE client_id = ?",
            (config_id,),
        ).fetchone()
        assert stored is not None
        assert stored["base_url"] == "https://generativelanguage.googleapis.com/v1"
        conn.execute(
            "UPDATE llm_configs SET base_url = ? WHERE client_id = ?",
            ("https://stale.example/google", config_id),
        )
        runtime = resolve_agent_llm_config(conn, config_id)

    assert runtime is not None
    assert runtime.base_url == "https://generativelanguage.googleapis.com/v1"
    assert runtime.api_key == "google-v1-secret"

    listed = client.get("/api/model-configs").json()["data"]["configs"]
    listed_google = next(item for item in listed if item["id"] == config_id)
    assert listed_google["apiUrl"] == "https://generativelanguage.googleapis.com/v1"

    updated_response = client.post(
        "/api/model-configs",
        json={
            **saved,
            "nickname": "Gemini Stable Updated",
            "apiKey": None,
        },
    )
    assert updated_response.status_code == 200
    assert updated_response.json()["data"]["apiKeyPreview"] == key_preview

    with connect() as conn:
        updated_runtime = resolve_agent_llm_config(conn, config_id)
    assert updated_runtime is not None
    assert updated_runtime.base_url == "https://generativelanguage.googleapis.com/v1"
    assert updated_runtime.api_key == "google-v1-secret"


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
            "supportsTools": False,
            "supportsStreaming": False,
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
    assert data["supportsTools"] is False
    assert data["supportsStreaming"] is False
    assert "thinkingEnabled" not in data

    with connect() as conn:
        row = conn.execute(
            """
            SELECT supports_tools, supports_streaming
            FROM llm_configs
            WHERE client_id = ?
            """,
            (data["id"],),
        ).fetchone()

    assert row is not None
    assert row["supports_tools"] == 0
    assert row["supports_streaming"] == 0


def test_model_config_api_keeps_thinking_capability_without_obsolete_toggle(
    client: TestClient,
) -> None:
    schemas = client.app.openapi()["components"]["schemas"]
    request_properties = schemas["ModelConfigUpsertRequest"]["properties"]
    response_properties = schemas["ModelConfigResponse"]["properties"]
    assert "supportsThinking" in request_properties
    assert "supportsThinking" in response_properties
    assert request_properties["thinkingMode"]["default"] == "auto"
    assert "thinkingMode" in response_properties
    assert "availableThinkingModes" in response_properties
    assert "thinkingEnabled" not in request_properties
    assert "thinkingEnabled" not in response_properties

    create_response = client.post(
        "/api/model-configs",
        json={
            "provider": "openai",
            "providerKind": "custom",
            "apiFamily": "openai_compatible_chat",
            "nickname": "Manual Reasoning",
            "apiKey": "sk-runtime-auto-secret",
            "model": "reasoning-model",
            "apiUrl": "https://example.test/v1",
            "contextWindowTokens": 65536,
            "supportsThinking": True,
        },
    )

    assert create_response.status_code == 200
    created = create_response.json()["data"]
    assert created["supportsThinking"] is True
    assert "thinkingEnabled" not in created

    listed = client.get("/api/model-configs").json()["data"]["configs"]
    listed_config = next(item for item in listed if item["id"] == created["id"])
    assert listed_config["supportsThinking"] is True
    assert "thinkingEnabled" not in listed_config

    with connect() as conn:
        inserted = conn.execute(
            """
            SELECT supports_thinking, encrypted_api_key
            FROM llm_configs
            WHERE client_id = ?
            """,
            (created["id"],),
        ).fetchone()
        assert inserted is not None
        assert inserted["supports_thinking"] == 1
        encrypted_api_key = inserted["encrypted_api_key"]

    update_response = client.post(
        "/api/model-configs",
        json={
            **created,
            "nickname": "Manual Reasoning Updated",
            "apiKey": None,
        },
    )

    assert update_response.status_code == 200
    updated = update_response.json()["data"]
    assert updated["id"] == created["id"]
    assert updated["supportsThinking"] is True
    assert "thinkingEnabled" not in updated

    with connect() as conn:
        persisted = conn.execute(
            """
            SELECT supports_thinking, encrypted_api_key
            FROM llm_configs
            WHERE client_id = ?
            """,
            (created["id"],),
        ).fetchone()

    assert persisted is not None
    assert persisted["supports_thinking"] == 1
    assert persisted["encrypted_api_key"] == encrypted_api_key


def test_model_metadata_refresh_persists_normalized_capabilities(
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
        AsyncMock(
            return_value={
                "openai/gpt-5.1": {
                    "litellm_provider": "openai",
                    "max_input_tokens": 131072,
                    "max_output_tokens": 8192,
                    "supports_web_search": True,
                },
            }
        ),
    )

    assert asyncio.run(model_metadata.refresh_model_metadata_cache()) is True
    cache_path = tmp_path / model_metadata.MODEL_METADATA_CACHE_NAME
    assert cache_path.exists()
    cache_data = json.loads(cache_path.read_text(encoding="utf-8"))
    assert set(cache_data) == {"version", "source", "catalogs"}
    assert cache_data["catalogs"]["litellm"]["providers"]["openai"]["gpt-5.1"] == {
        "sourceKey": "openai/gpt-5.1",
        "contextWindowTokens": 131072,
        "maxOutputTokens": 8192,
        "supportsWebSearch": True,
    }
    assert "gpt-proxy" not in cache_data["catalogs"]["litellm"]["providers"]["openai"]
    assert cache_data["catalogs"]["modelsDev"] == {
        "contextModels": {},
        "fetchedAt": None,
        "providers": {},
    }

    metadata = model_metadata.resolve_model_metadata("openai", "gpt-5.1")

    assert metadata is not None
    assert metadata.context_window_tokens == 131072
    assert metadata.max_output_tokens == 8192
    assert metadata.supports_web_search is True
    get_settings.cache_clear()


def test_model_metadata_cache_is_reused_without_refresh(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.services import model_metadata

    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    fresh_time = datetime.now(UTC).isoformat(timespec="seconds")
    cache_path = tmp_path / model_metadata.MODEL_METADATA_CACHE_NAME
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "version": model_metadata.MODEL_METADATA_CACHE_VERSION,
                "source": model_metadata.MODEL_METADATA_CACHE_SOURCE,
                "catalogs": {
                    "litellm": {
                        "contextModels": {},
                        "fetchedAt": fresh_time,
                        "providers": {
                            "openai": {
                                "gpt-5.1": {
                                    "sourceKey": "openai/gpt-5.1",
                                    "contextWindowTokens": 131072,
                                    "maxOutputTokens": 8192,
                                },
                            },
                        },
                    },
                    "modelsDev": {
                        "contextModels": {},
                        "fetchedAt": fresh_time,
                        "providers": {},
                    },
                },
            },
        ),
        encoding="utf-8",
    )
    model_metadata._CATALOG_CACHE = None

    async def fail_fetch() -> dict[str, object]:
        raise AssertionError("cached model metadata should not refresh implicitly")

    fetch = AsyncMock(side_effect=fail_fetch)
    monkeypatch.setattr(model_metadata, "_fetch_catalog", fetch)
    monkeypatch.setattr(model_metadata, "_fetch_reasoning_catalog", fetch)

    assert model_metadata.resolve_model_metadata("openai", "gpt-5.1") is not None
    fetch.assert_not_called()
    get_settings.cache_clear()


def test_stale_model_metadata_cache_refreshes_deepseek_v4_limits(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.services import model_metadata

    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    cache_path = tmp_path / model_metadata.MODEL_METADATA_CACHE_NAME
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "version": model_metadata.MODEL_METADATA_CACHE_VERSION,
                "source": model_metadata.MODEL_METADATA_CACHE_SOURCE,
                "catalogs": {
                    "litellm": {
                        "contextModels": {},
                        "fetchedAt": "2026-06-01T00:00:00+00:00",
                        "providers": {
                            "deepseek": {
                                "deepseek-chat": {
                                    "sourceKey": "deepseek-chat",
                                    "contextWindowTokens": 131072,
                                    "maxOutputTokens": 8192,
                                },
                            },
                        },
                    },
                    "modelsDev": {
                        "contextModels": {},
                        "fetchedAt": "2026-06-01T00:00:00+00:00",
                        "providers": {},
                    },
                },
            },
        ),
        encoding="utf-8",
    )
    model_metadata._CATALOG_CACHE = None
    monkeypatch.setattr(model_metadata, "MODEL_METADATA_CACHE_TTL_SECONDS", -1)
    monkeypatch.setattr(
        model_metadata,
        "_fetch_catalog",
        AsyncMock(
            return_value={
                "deepseek-v4-pro": {
                    "litellm_provider": "deepseek",
                    "max_input_tokens": 1000000,
                    "max_output_tokens": 8192,
                    "supports_reasoning": True,
                    "supports_tool_choice": True,
                },
            }
        ),
    )

    assert asyncio.run(model_metadata.refresh_model_metadata_cache()) is True
    metadata = model_metadata.resolve_model_metadata("deepseek", "deepseek-v4-pro")

    assert metadata is not None
    assert metadata.context_window_tokens == 1000000
    assert metadata.max_output_tokens == 8192
    assert metadata.supports_thinking is True
    assert metadata.supports_tools is True
    get_settings.cache_clear()


def test_metadata_refresh_keeps_old_cache_when_source_parse_is_empty(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.services import model_metadata

    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    cache_path = tmp_path / model_metadata.MODEL_METADATA_CACHE_NAME
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "version": model_metadata.MODEL_METADATA_CACHE_VERSION,
                "source": model_metadata.MODEL_METADATA_CACHE_SOURCE,
                "catalogs": {
                    "litellm": {
                        "contextModels": {},
                        "fetchedAt": "2026-06-01T00:00:00+00:00",
                        "providers": {
                            "deepseek": {
                                "deepseek-v4-pro": {
                                    "sourceKey": "deepseek/deepseek-v4-pro",
                                    "contextWindowTokens": 1000000,
                                },
                            },
                        },
                    },
                    "modelsDev": {
                        "contextModels": {},
                        "fetchedAt": "2026-06-01T00:00:00+00:00",
                        "providers": {},
                    },
                },
            },
        ),
        encoding="utf-8",
    )
    model_metadata._CATALOG_CACHE = None
    monkeypatch.setattr(
        model_metadata,
        "_fetch_catalog",
        AsyncMock(
            return_value={
                "proxy/gpt-5.1": {
                    "litellm_provider": "unsupported-proxy",
                    "max_input_tokens": 131072,
                },
            }
        ),
    )

    assert asyncio.run(model_metadata.refresh_model_metadata_cache()) is False
    metadata = model_metadata.resolve_model_metadata("deepseek", "deepseek-v4-pro")

    assert metadata is not None
    assert metadata.context_window_tokens == 1000000
    get_settings.cache_clear()


def test_model_config_save_does_not_fetch_model_metadata(
    client: TestClient,
    monkeypatch,
) -> None:
    from app.services import model_metadata

    model_metadata._CATALOG_CACHE = {}

    async def fail_fetch() -> dict[str, object]:
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
            "message": {
                "id": "agent-user-chat-guides-when-model-is-missing",
                "role": "user",
                "text": "Find missing keywords",
            },
            "locale": "en",
            "resume": minimal_resume_document(
                name="Avery",
                summary="Frontend engineer with React project experience.",
            ),
            "modelConfig": None,
        },
    )

    assert "No usable model configuration" in message["text"]
    assert message["edits"] == []
    assert message["tools"] == []


def test_agent_chat_persists_and_loads_session(client: TestClient) -> None:
    create_response = client.post(
        "/api/resumes",
        json={"documentLocale": "en", "title": "王小明"},
    )
    assert create_response.status_code == 200
    created_resume = create_response.json()["data"]["resume"]
    resume_id = created_resume["id"]
    initial_session_response = client.get(
        f"/api/agent/resumes/{resume_id}/session",
    )
    expected_revision = initial_session_response.json()["data"]["revision"]

    _, response_message = post_agent_chat_stream(
        client,
        {
            "resumeId": resume_id,
            "expectedRevision": expected_revision,
            "message": {
                "id": "agent-user-session-1",
                "role": "user",
                "text": "帮我检查项目经历",
            },
            "messages": [],
            "locale": "zh",
            "resume": created_resume["resume"],
            "modelConfig": None,
        },
    )
    session_response = client.get(f"/api/agent/resumes/{resume_id}/session")

    assert session_response.status_code == 200
    session_data = session_response.json()["data"]
    messages = session_data["messages"]
    assert session_data["resumeId"] == resume_id
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert len({message["id"] for message in messages}) == 2
    assert messages[0]["id"] == "agent-user-session-1"
    assert messages[0]["text"] == "帮我检查项目经历"
    assert messages[1]["response"]["role"] == "assistant"
    assert messages[1]["response"]["text"] == response_message["text"]


def test_agent_session_put_replaces_persisted_messages(
    client: TestClient,
) -> None:
    create_response = client.post(
        "/api/resumes",
        json={"documentLocale": "en", "title": "Editable agent session"},
    )
    assert create_response.status_code == 200
    resume_id = create_response.json()["data"]["resume"]["id"]
    initial_session = client.get(
        f"/api/agent/resumes/{resume_id}/session",
    ).json()["data"]
    first_response = client.put(
        f"/api/agent/resumes/{resume_id}/session",
        json={
            "locale": "zh",
            "revision": initial_session["revision"],
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
                        "tools": [
                            {
                                "id": "tool-fetch-success",
                                "type": "tool-web_fetch",
                                "title": "web_fetch",
                                "state": "output-available",
                                "input": {"url": "https://example.com/job"},
                                "output": {"resultCount": 2},
                                "startedAt": "2026-08-10T10:00:00Z",
                                "completedAt": "2026-08-10T10:00:01Z",
                            },
                            {
                                "id": "tool-fetch-error",
                                "type": "tool-web_fetch",
                                "title": "web_fetch",
                                "state": "output-error",
                                "input": {"url": "https://example.com/job"},
                                "errorText": "Fetch failed",
                                "startedAt": "2026-08-10T10:00:02Z",
                                "completedAt": "2026-08-10T10:00:03Z",
                            },
                        ],
                        "sources": [
                            {
                                "id": "source-public-job",
                                "title": "Public job description",
                                "sourceType": "web",
                                "url": "https://example.com/job",
                                "excerpt": "Build accessible React products.",
                            },
                        ],
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

    assert first_response.status_code == 200
    first_session = first_response.json()["data"]
    first_messages = first_session["messages"]
    assert [message["id"] for message in first_messages] == [
        "agent-user-original",
        "agent-assistant-original",
        "agent-user-tail",
    ]
    assistant_response = first_messages[1]["response"]
    assert assistant_response["tools"][0]["input"] == {
        "url": "https://example.com/job",
    }
    assert assistant_response["tools"][0]["output"] == {"resultCount": 2}
    assert assistant_response["tools"][1]["errorText"] == "Fetch failed"
    assert assistant_response["tools"][1]["completedAt"] == ("2026-08-10T10:00:03Z")
    assert assistant_response["sources"][0]["excerpt"] == (
        "Build accessible React products."
    )
    refreshed_first_session = client.get(
        f"/api/agent/resumes/{resume_id}/session",
    ).json()["data"]
    assert refreshed_first_session["messages"] == first_messages

    second_response = client.put(
        f"/api/agent/resumes/{resume_id}/session",
        json={
            "locale": "zh",
            "revision": first_session["revision"],
            "messages": [
                {
                    "id": "agent-user-original",
                    "role": "user",
                    "text": "修改后的问题",
                },
            ],
        },
    )

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
            WHERE session_id = ?
            """,
            (resume_id,),
        ).fetchone()["count"]

    assert stored_count == 1


def test_agent_session_replace_rejects_stale_revision_without_pruning_files(
    client: TestClient,
) -> None:
    create_response = client.post(
        "/api/resumes",
        json={"documentLocale": "en", "title": "Concurrent agent session"},
    )
    assert create_response.status_code == 200
    resume_id = create_response.json()["data"]["resume"]["id"]
    winner_attachment = store_agent_attachment(
        session_id=resume_id,
        filename="winner.txt",
        media_type="text/plain",
        payload=b"winner",
    ).model_dump(mode="json", by_alias=True)
    stale_attachment = store_agent_attachment(
        session_id=resume_id,
        filename="stale.txt",
        media_type="text/plain",
        payload=b"stale",
    ).model_dump(mode="json", by_alias=True)
    empty_session = client.get(
        f"/api/agent/resumes/{resume_id}/session",
    ).json()["data"]

    initial_response = client.put(
        f"/api/agent/resumes/{resume_id}/session",
        json={
            "locale": "en",
            "revision": empty_session["revision"],
            "messages": [
                {
                    "id": "initial-message",
                    "role": "user",
                    "text": "Initial",
                },
            ],
        },
    )
    initial_revision = initial_response.json()["data"]["revision"]

    winner_response = client.put(
        f"/api/agent/resumes/{resume_id}/session",
        json={
            "locale": "en",
            "revision": initial_revision,
            "messages": [
                {
                    "id": "winner-message",
                    "role": "user",
                    "text": "Winner",
                    "files": [winner_attachment],
                },
            ],
        },
    )
    stale_response = client.put(
        f"/api/agent/resumes/{resume_id}/session",
        json={
            "locale": "en",
            "revision": initial_revision,
            "messages": [
                {
                    "id": "stale-message",
                    "role": "user",
                    "text": "Stale",
                    "files": [stale_attachment],
                },
            ],
        },
    )

    assert winner_response.status_code == 200
    assert winner_response.json()["data"]["revision"] != initial_revision
    assert stale_response.status_code == 409
    assert stale_response.json()["message"] == (
        "AGENT_SESSION_REVISION_CONFLICT"
    )

    persisted = client.get(f"/api/agent/resumes/{resume_id}/session")
    assert [message["id"] for message in persisted.json()["data"]["messages"]] == [
        "winner-message",
    ]
    assert (
        client.get(
            f"/api/agent/resumes/{resume_id}/attachments/{winner_attachment['id']}",
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/api/agent/resumes/{resume_id}/attachments/{stale_attachment['id']}",
        ).status_code
        == 200
    )


def test_agent_session_replace_serializes_two_concurrent_clients(
    client: TestClient,
) -> None:
    create_response = client.post(
        "/api/resumes",
        json={"documentLocale": "en", "title": "Simultaneous agent session"},
    )
    assert create_response.status_code == 200
    resume_id = create_response.json()["data"]["resume"]["id"]
    empty_session = client.get(
        f"/api/agent/resumes/{resume_id}/session",
    ).json()["data"]
    initial_response = client.put(
        f"/api/agent/resumes/{resume_id}/session",
        json={
            "locale": "en",
            "revision": empty_session["revision"],
            "messages": [
                {
                    "id": "simultaneous-initial",
                    "role": "user",
                    "text": "Initial",
                },
            ],
        },
    )
    initial_revision = initial_response.json()["data"]["revision"]
    start_together = Barrier(2)

    def replace_from_client(
        test_client: TestClient,
        client_number: int,
        expected_revision: str,
    ):
        start_together.wait(timeout=2)
        return test_client.put(
            f"/api/agent/resumes/{resume_id}/session",
            json={
                "locale": "en",
                "revision": expected_revision,
                "messages": [
                    {
                        "id": f"simultaneous-client-{client_number}",
                        "role": "user",
                        "text": f"Client {client_number}",
                    },
                ],
            },
        )

    with closing(TestClient(client.app)) as second_client:
        second_client.headers.update(client.headers)
        first_client_revision = client.get(
            f"/api/agent/resumes/{resume_id}/session",
        ).json()["data"]["revision"]
        second_client_revision = second_client.get(
            f"/api/agent/resumes/{resume_id}/session",
        ).json()["data"]["revision"]
        assert first_client_revision == second_client_revision == initial_revision

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    replace_from_client,
                    test_client,
                    client_number,
                    expected_revision,
                )
                for test_client, client_number, expected_revision in (
                    (client, 1, first_client_revision),
                    (second_client, 2, second_client_revision),
                )
            ]
            responses = [future.result(timeout=10) for future in futures]

    assert sorted(response.status_code for response in responses) == [200, 409]
    conflict = next(response for response in responses if response.status_code == 409)
    assert conflict.json()["message"] == "AGENT_SESSION_REVISION_CONFLICT"

    persisted = client.get(f"/api/agent/resumes/{resume_id}/session")
    persisted_ids = [message["id"] for message in persisted.json()["data"]["messages"]]
    assert persisted_ids in [
        ["simultaneous-client-1"],
        ["simultaneous-client-2"],
    ]


def test_provider_failure_keeps_user_message_without_assistant(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resume_id = client.post(
        "/api/resumes",
        json={"documentLocale": "en", "title": "Provider failure"},
    ).json()["data"]["resume"]["id"]
    initial_session = client.get(
        f"/api/agent/resumes/{resume_id}/session",
    ).json()["data"]
    model_config = create_agent_model_config(client)

    def raise_provider_error(*_: object, **__: object) -> str:
        raise LlmRequestError("provider unavailable")

    monkeypatch.setattr(
        ASYNC_STREAM_TOOL_CALL_PATH,
        raise_provider_error,
    )

    post_agent_chat_stream(
        client,
        {
            "resumeId": resume_id,
            "expectedRevision": initial_session["revision"],
            "message": {
                "id": "agent-user-provider-failure",
                "role": "user",
                "text": "Keep this prompt.",
            },
            "messages": [],
            "locale": "en",
            "resume": {"basic": {}, "sections": []},
            "modelConfig": model_config,
        },
    )

    session = client.get(
        f"/api/agent/resumes/{resume_id}/session",
    ).json()["data"]
    assert [(message["id"], message["role"]) for message in session["messages"]] == [
        ("agent-user-provider-failure", "user"),
    ]


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
        max_tokens=512,
        timeout_seconds=60,
        context_window_tokens=13000,
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
                "sources": [
                    {
                        "id": "source-project-brief",
                        "title": "Project brief",
                        "sourceType": "attachment",
                    },
                ],
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
    for index in range(6):
        conversation.extend(
            [
                {
                    "id": f"agent-user-followup-{index}",
                    "role": "user",
                    # Repeated test input keeps the user-authored semantic
                    # memory stable; assistant prose supplies the bulk needed
                    # to exercise deterministic checkpoint compaction.
                    "text": "继续检查项目经历。",
                },
                {
                    "id": f"agent-assistant-followup-{index}",
                    "role": "assistant",
                    "text": (
                        f"项目补充说明 {index}：" + ("用于触发上下文压缩。" * 80)
                        if index < 4
                        else f"最近项目补充说明 {index}。"
                    ),
                },
            ],
        )
    conversation.append(
        {
            "id": "agent-user-current",
            "role": "user",
            "text": "把刚才那个版本的第二条再短一点",
        },
    )
    request = AgentChatRequest(
        message=conversation[-1],
        messages=conversation[:-1],
        locale="zh",
        resume={"basic": {"name": "王小明"}, "sections": []},
        draftState={
            "id": "draft-current",
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
                                "title": "Reseno",
                                "subtitle": "AI 简历编辑器",
                            },
                        ],
                    },
                ],
            },
            "pendingCount": 1,
            "reviewItems": [
                {
                    "id": "agent-review-edit-project-1",
                    "editIds": ["edit-project-1"],
                    "status": "pending",
                },
            ],
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
                    "after": "Reseno",
                },
            ],
        },
        modelConfig=None,
    )

    messages = AgentPromptCompiler(request, config).build().messages
    workspace = agent_workspace_context(messages)
    context = workspace["conversationState"]

    assert workspace["responseLanguage"] == "Chinese"
    assert "responseLanguage" in messages[0]["content"]
    assert context["currentDraft"]["id"] == "draft-current"
    assert context["currentDraft"]["pendingCount"] == 1
    assert context["currentDraft"]["diffs"][0]["path"] == "sections.project"
    assert workspace["resume"]["sections"][0]["id"] == "project"
    assistant_state = next(
        json.loads(message["content"])["assistantResponseContext"]
        for message in messages
        if message["role"] == "user"
        and isinstance(message["content"], str)
        and message["content"].startswith('{"assistantResponseContext":')
    )
    assert assistant_state["editCount"] == 1
    assert assistant_state["edits"][0]["title"] == "新增项目经历模块"
    assert assistant_state["edits"][0]["sectionId"] == "project"
    assert assistant_state["sourceRefs"] == [
        {
            "id": "source-project-brief",
            "title": "Project brief",
            "sourceType": "attachment",
        },
    ]
    assert messages[-1] == {
        "role": "user",
        "content": "把刚才那个版本的第二条再短一点",
    }


def test_agent_message_builder_treats_historical_assistant_prose_as_data() -> None:
    config = AgentLlmConfig(
        client_id="llm-test",
        name="Test Model",
        provider="openai",
        model="gpt-test",
        base_url="https://example.test/v1",
        api_key="sk-test",
        temperature=0.4,
        top_p=0.9,
        max_tokens=512,
        timeout_seconds=60,
        context_window_tokens=12000,
    )
    conversation = [
        {
            "id": f"agent-history-{index}",
            "role": "assistant" if index % 2 else "user",
            "text": f"历史消息 {index} " + ("用于验证上下文压缩。" * 20),
        }
        for index in range(40)
    ]
    request = AgentChatRequest(
        message={
            "id": "agent-user-messages-drop-old-summaries-before-provider-call",
            "role": "user",
            "text": "只保留当前这条请求",
        },
        messages=conversation,
        locale="zh",
        resume={"basic": {"name": "测试用户"}, "sections": []},
        modelConfig=None,
    )

    messages = AgentPromptCompiler(request, config).build().messages

    expected_history: list[dict[str, str]] = []
    for item in conversation:
        if item["role"] == "assistant":
            expected_history.append(
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "assistantResponseContext": {
                                "text": item["text"],
                                "messageId": item["id"],
                            },
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            )
            continue
        expected_history.append({"role": "user", "content": item["text"]})
        expected_history.append(
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "historicalUserEvidence": {
                            "appliesToPreviousUserMessage": True,
                            "evidenceRef": historical_prompt_evidence_ref(
                                item["id"],
                            ),
                        },
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
        )
    assert messages[1 : 1 + len(expected_history)] == expected_history
    assert json.loads(messages[-2]["content"])["workspaceContext"]
    assert messages[-1] == {
        "role": "user",
        "content": "只保留当前这条请求",
    }
    assert conversation[1]["text"] in json.dumps(messages, ensure_ascii=False)


def test_agent_messages_reject_state_that_cannot_fit_context() -> None:
    config = AgentLlmConfig(
        client_id="llm-test",
        name="Tiny Model",
        provider="openai",
        model="tiny-test",
        base_url="https://example.test/v1",
        api_key="sk-test",
        temperature=0.4,
        top_p=0.9,
        max_tokens=None,
        timeout_seconds=60,
        context_window_tokens=128,
    )
    request = AgentChatRequest(
        message={
            "id": "agent-user-messages-reject-state-that-cannot-fit-context",
            "role": "user",
            "text": "继续",
        },
        messages=[],
        locale="zh",
        resume={
            "basic": {"name": "测试用户", "summary": "很长的简介" * 300},
            "sections": [],
        },
        modelConfig=None,
    )

    with pytest.raises(LlmRequestError, match="context window"):
        AgentPromptCompiler(request, config).build()


def test_agent_messages_hide_personal_identity_from_model_payload(
    client: TestClient,
) -> None:
    session_id = "agentmessageprivacy"
    session_revision = client.get(
        f"/api/agent/resumes/{session_id}/session",
    ).json()["data"]["revision"]
    attachment = store_agent_attachment(
        session_id=session_id,
        filename="note.txt",
        media_type="text/plain",
        payload=("联系人 王小明，邮箱 xiaoming@example.com，电话 13800138000").encode(),
    ).model_dump(mode="json", by_alias=True)
    config = AgentLlmConfig(
        client_id="llm-test",
        name="Test Model",
        provider="openai",
        model="gpt-test",
        base_url="https://example.test/v1",
        api_key="sk-test",
        temperature=0.4,
        top_p=0.9,
        max_tokens=512,
        timeout_seconds=60,
        context_window_tokens=24000,
    )
    request = AgentChatRequest(
        message={
            "id": "agent-user-messages-hide-personal-identity-from-model-payload",
            "role": "user",
            "text": "帮王小明优化简介，电话 13800138000",
            "files": [attachment],
        },
        messages=[
            {
                "id": "agent-user-1",
                "role": "user",
                "text": "王小明的邮箱是 xiaoming@example.com",
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
        modelConfig=None,
        resume_id=session_id,
        expected_revision=session_revision,
    )

    messages = AgentPromptCompiler(request, config).build().messages
    serialized = json.dumps(messages, ensure_ascii=False)
    workspace = agent_workspace_context(messages)
    files = agent_current_request_files(messages)

    assert "王小明" not in serialized
    assert "13800138000" not in serialized
    assert "xiaoming@example.com" not in serialized
    assert "https://avatar.example/wxm.png" not in serialized
    assert workspace["resume"]["basic"]["name"] == "[hidden]"
    assert workspace["resume"]["basic"]["phone"] == "[hidden]"
    assert workspace["resume"]["basic"]["email"] == "[hidden]"
    assert workspace["resume"]["basic"]["location"] == "[hidden]"
    assert workspace["resume"]["basic"]["avatar"] == "[hidden]"
    assert workspace["resume"]["basicFieldStatus"]["name"] == "present"
    assert workspace["resume"]["basicFieldStatus"]["phone"] == "present"
    assert workspace["resume"]["basicFieldStatus"]["email"] == "present"
    assert workspace["resume"]["basicFieldStatus"]["location"] == "present"
    assert "[redacted_email]" in workspace["resume"]["basic"]["summary"]
    assert "[redacted_phone]" in workspace["resume"]["basic"]["summary"]
    assert "[redacted_email]" in files[0]["excerpt"]
    assert "[redacted_phone]" in files[0]["excerpt"]


def test_agent_rejects_replace_field_for_hidden_personal_fields() -> None:
    edits, rejected = parse_edit_batch(
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
    assert "Canonical protocol error" in rejected[0]["reason"]


def test_agent_rejects_location_write_as_hidden_personal_data() -> None:
    resume = minimal_resume_item()["resume"]
    resume["basic"]["location"] = "杭州"
    request = AgentChatRequest(
        message={
            "id": "agent-user-rejects-location-write-as-hidden-personal-data",
            "role": "user",
            "text": "请修改这份简历，只把基本信息中的地点改为远程，并生成待确认草稿。",
        },
        locale="zh",
        resume=resume,
    )
    environment = ResumeToolEnvironment.open(request)

    tool, result = invoke_agent_tool(
        environment,
        tool_call(
            "call-location",
            "edit_execute",
            {
                "edits": [
                    {
                        "title": "更新地点",
                        "target": "basic.location",
                        "reason": "用户明确要求使用远程。",
                        "operation": {
                            "type": "replace_field",
                            "path": "basic.location",
                            "value": "远程",
                        },
                    },
                ],
            },
        ),
    )

    assert tool.state == "output-error"
    assert result["output"]["editCount"] == 0
    assert result["output"]["rejectedEditCount"] == 1
    reason = result["output"]["rejectedEdits"][0]["reason"]
    assert "Canonical protocol error" in reason
    assert "basic.location" in reason
    assert "杭州" not in json.dumps(result["output"], ensure_ascii=False)
    assert environment.close(completed=True).edits == ()


def test_agent_edit_execute_uses_pending_draft_resume() -> None:
    base_resume = minimal_resume_item()["resume"]
    base_resume["basic"]["name"] = "王小明"
    draft_resume = minimal_resume_item()["resume"]
    draft_resume["basic"]["name"] = "王小明"
    draft_resume["sections"] = [
        {
            "id": "project",
            "kind": "project",
            "title": "项目经历",
            "items": [
                {
                    "id": "project-1",
                    "name": "Reseno",
                    "role": "前端开发",
                    "techStack": [],
                    "period": "",
                    "url": "",
                    "description": "支持复杂的 Agent 草稿编辑流程。",
                    "highlights": ["实现可预览、可应用、可撤回草稿。"],
                },
            ],
        },
    ]
    request = AgentChatRequest(
        message={
            "id": "agent-user-draft-rewrite-uses-pending-draft-resume",
            "role": "user",
            "text": "把刚才草稿里的项目描述再短一点",
        },
        locale="zh",
        resume=base_resume,
        draftState={
            "id": "draft-current",
            "resume": draft_resume,
            "pendingCount": 1,
            "reviewItems": [
                {
                    "id": "agent-review-edit-project-1",
                    "editIds": ["edit-project-1"],
                    "status": "pending",
                },
            ],
        },
    )
    environment = ResumeToolEnvironment.open(request)

    tool, result = invoke_agent_tool(
        environment,
        tool_call(
            "call-rewrite",
            "edit_execute",
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

    assert tool.title == "edit_execute"
    assert result["output"]["editCount"] == 1
    edits = environment.close(completed=True).edits
    assert edits[0].operation["patch"]["description"] == "支持 Agent 草稿编辑。"


def test_agent_chat_uses_natural_completion_after_edit(
    client: TestClient,
    monkeypatch,
) -> None:
    session_id = client.post(
        "/api/resumes",
        json={"documentLocale": "en", "title": "Agent JSON chat"},
    ).json()["data"]["resume"]["id"]
    attachment_response = client.post(
        "/api/agent/attachments",
        data={"resumeId": session_id},
        files={
            "file": (
                "jd.txt",
                b"TypeScript JD attachment text",
                "text/plain",
            ),
        },
    )
    assert attachment_response.status_code == 200
    attachment = attachment_response.json()["data"]
    session_revision = client.get(
        f"/api/agent/resumes/{session_id}/session",
    ).json()["data"]["revision"]

    model_config = create_agent_model_config(client)
    monkeypatch.setattr(
        ASYNC_STREAM_CHAT_PATH,
        fail_on_second_final_stream,
    )
    monkeypatch.setattr(
        ASYNC_STREAM_TOOL_CALL_PATH,
        stub_tool_call_responses(
            LlmAssistantMessage(
                content="",
                tool_calls=[
                    tool_call(
                        "call-jd",
                        "web_fetch",
                        {"url": "https://example.test/jobs/frontend"},
                    ),
                ],
            ),
            LlmAssistantMessage(
                content="",
                tool_calls=[
                    tool_call(
                        "call-execute",
                        "edit_execute",
                        {
                            "edits": [
                                {
                                    "title": "Update summary",
                                    "target": "basic.summary",
                                    "reason": "Clarify the existing React experience.",
                                    "operation": {
                                        "type": "replace_field",
                                        "path": "basic.summary",
                                        "value": (
                                            "Frontend engineer focused on React "
                                            "project delivery."
                                        ),
                                    },
                                },
                            ],
                        },
                    ),
                ],
            ),
            LlmAssistantMessage(content="Draft is complete.", tool_calls=[]),
        ),
    )
    monkeypatch.setattr(
        agent_web,
        "_async_fetch_web_reference",
        async_stub_jd_fetch,
    )

    _, message = post_agent_chat_stream(
        client,
        {
            "message": {
                "id": "agent-user-1",
                "role": "user",
                "text": (
                    "Use https://example.test/jobs/frontend with the target role's "
                    "React and TypeScript requirements to find missing keywords "
                    "and edit my summary."
                ),
                "files": [attachment],
            },
            "messages": [],
            "locale": "en",
            "resume": minimal_resume_document(
                name="Avery",
                summary="Frontend engineer with React project experience.",
            ),
            "modelConfig": model_config,
            "resumeId": session_id,
            "expectedRevision": session_revision,
        },
    )

    assert message["role"] == "assistant"
    assert message["text"] == "Draft is complete."
    assert message["tools"]
    assert message["sources"]
    assert message["edits"]
    assert {source["sourceType"] for source in message["sources"]} == {"web"}
    assert message["edits"][0]["status"] == "executed"
    assert message["edits"][0]["operation"]["type"] == "replace_field"
    assert any(tool["title"] == "web_fetch" for tool in message["tools"])


def test_agent_chat_executes_model_selected_item_edit_without_jd_search(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    monkeypatch.setattr(
        ASYNC_STREAM_CHAT_PATH,
        fail_on_second_final_stream,
    )
    monkeypatch.setattr(
        ASYNC_STREAM_TOOL_CALL_PATH,
        stub_tool_call_responses(
            LlmAssistantMessage(
                content="",
                tool_calls=[
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
                                            "highlights": ["接口延迟降低 30%"],
                                        },
                                    },
                                },
                            ],
                        },
                    ),
                ],
            ),
            LlmAssistantMessage(
                content="已生成项目经历修改草稿。",
                tool_calls=[],
            ),
        ),
    )
    resume = minimal_resume_document(name="王小明")
    resume["sections"] = [
        {
            "id": "project",
            "kind": "project",
            "title": "项目经历",
            "items": [
                {
                    "id": "project-1",
                    "name": "电商推荐系统优化",
                    "role": "",
                    "techStack": [],
                    "period": "2023/06 - 2023/09",
                    "url": "",
                    "description": "负责推荐算法迭代。",
                    "highlights": [],
                },
            ],
        },
    ]

    _, message = post_agent_chat_stream(
        client,
        {
            "message": {
                "id": "agent-user-selected-item-edit",
                "role": "user",
                "text": (
                    "候选人事实：该项目点击率提升 12%，接口延迟降低 30%。"
                    "把项目经历写得更像推荐算法工程师。"
                ),
            },
            "messages": [],
            "locale": "zh",
            "resume": resume,
            "modelConfig": model_config,
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
    assert message["text"] == "已生成项目经历修改草稿。"
    assert message["edits"][0]["target"] == "sections.project.items.project-1"
    assert message["edits"][0]["operation"] == {
        "type": "update_item",
        "sectionId": "project",
        "itemId": "project-1",
        "patch": {
            "description": "负责推荐链路优化，点击率提升 12%。",
            "highlights": ["接口延迟降低 30%"],
        },
    }


def test_agent_chat_executes_explicit_project_insert_directly(
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
        ASYNC_STREAM_CHAT_PATH,
        fail_on_second_final_stream,
    )
    monkeypatch.setattr(
        ASYNC_STREAM_TOOL_CALL_PATH,
        stub_tool_call_responses(
            LlmAssistantMessage(
                content="",
                tool_calls=[
                    tool_call(
                        "call-execute",
                        "edit_execute",
                        {
                            "edits": [
                                {
                                    "title": "新增项目经历",
                                    "target": "sections",
                                    "reason": "用户提供了完整项目事实。",
                                    "evidenceRefs": ["prompt:current"],
                                    "operation": {
                                        "type": "insert_section",
                                        "section": {
                                            "id": "project-added",
                                            "kind": "project",
                                            "title": "项目经历",
                                            "items": [
                                                {
                                                    "id": "project-added-1",
                                                    "name": "电商后台管理系统",
                                                    "role": "",
                                                    "techStack": [],
                                                    "period": "2023.03 - 2023.06",
                                                    "url": "",
                                                    "description": "",
                                                    "highlights": [
                                                        (
                                                            "负责 Spring Boot、MySQL、"
                                                            "Redis、Docker 和 SQL 优化"
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
            ),
            LlmAssistantMessage(content="项目经历草稿已完成。", tool_calls=[]),
        ),
    )

    _, message = post_agent_chat_stream(
        client,
        {
            "message": {
                "id": "agent-user-chat-executes-explicit-project-insert-directly",
                "role": "user",
                "text": prompt,
            },
            "messages": [],
            "locale": "zh",
            "resume": minimal_resume_document(name="姓名"),
            "modelConfig": model_config,
        },
    )

    tool_titles = [tool["title"] for tool in message["tools"]]
    assert tool_titles == ["edit_execute"]
    assert message["edits"]
    observations = message["tools"][0]["output"]["observations"]
    assert observations[0]["before"] is None
    assert "电商后台管理系统" in observations[0]["after"]
    assert "2023.03 - 2023.06" in observations[0]["after"]
    assert "sectionCount" not in json.dumps(observations, ensure_ascii=False)
    operation = message["edits"][0]["operation"]
    assert operation["type"] == "insert_section"
    assert operation["section"]["kind"] == "project"
    assert operation["section"]["title"] == "项目经历"
    assert operation["section"]["items"][0]["name"] == "电商后台管理系统"
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


def test_agent_chat_retries_noncanonical_insert_with_canonical_operation(
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
        ASYNC_STREAM_CHAT_PATH,
        fail_on_second_final_stream,
    )
    monkeypatch.setattr(
        ASYNC_STREAM_TOOL_CALL_PATH,
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
                    "call-execute-repair",
                    "edit_execute",
                    {
                        "edits": [
                            {
                                "title": "新增项目经历",
                                "target": "sections",
                                "reason": "移除重复元数据后重新提交完整项目条目。",
                                "evidenceRefs": ["prompt:current"],
                                "operation": {
                                    "type": "insert_section",
                                    "section": {
                                        "id": "project-added",
                                        "kind": "project",
                                        "title": "项目经历",
                                        "items": [
                                            {
                                                "id": "project-added-1",
                                                "name": "电商后台管理系统",
                                                "role": "后端开发",
                                                "techStack": [
                                                    "Spring Boot",
                                                    "MySQL",
                                                    "Redis",
                                                    "Docker",
                                                ],
                                                "period": "2023.03 - 2023.06",
                                                "url": "",
                                                "description": "",
                                                "highlights": [
                                                    (
                                                        "设计并实现订单模块，通过 SQL "
                                                        "优化将查询时间从 2s 降至 0.3s"
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
        ),
    )

    _, message = post_agent_chat_stream(
        client,
        {
            "message": {
                "id": "agent-user-chat-normalizes-model-inserted-resume-fields",
                "role": "user",
                "text": prompt,
            },
            "messages": [],
            "locale": "zh",
            "resume": minimal_resume_document(name="姓名"),
            "modelConfig": model_config,
        },
    )

    operation = message["edits"][0]["operation"]
    section = operation["section"]
    item = section["items"][0]
    assert section["kind"] == "project"
    assert section["title"] == "项目经历"
    assert item["name"] == "电商后台管理系统"
    assert item["role"] == "后端开发"
    assert item["techStack"] == ["Spring Boot", "MySQL", "Redis", "Docker"]
    assert item["period"] == "2023.03 - 2023.06"
    assert item["description"] == ""
    assert item["highlights"] == [
        "设计并实现订单模块，通过 SQL 优化将查询时间从 2s 降至 0.3s",
    ]


def test_agent_supported_locales_cover_resources() -> None:
    supported = set(SUPPORTED_AGENT_LOCALES)
    prompt_dir = Path(__file__).parents[1] / "app/services/agent/prompts"
    expected_prompt_files = {
        "agent.md",
    }

    assert DEFAULT_AGENT_LOCALE in supported
    assert set(AGENT_LOCALIZED_TEXT) == supported
    assert {path.name for path in prompt_dir.glob("*.md")} == expected_prompt_files
    for prompt_path in prompt_dir.glob("*.md"):
        prompt_text = prompt_path.read_text(encoding="utf-8")
        assert re.search(r"[\u4e00-\u9fff]", prompt_text) is None
    assert AGENT_PROMPT == (prompt_dir / "agent.md").read_text(encoding="utf-8").strip()
    assert not (prompt_dir / "loader.py").exists()
    assert "confirmationMode" not in AGENT_PROMPT


def test_agent_web_tools_replace_legacy_jd_schema_names() -> None:
    tool_names = {
        schema["function"]["name"] for schema in agent_contracts.AGENT_TOOL_SCHEMAS
    }

    assert tool_names == {
        "web_search",
        "web_fetch",
        "attachment_read",
        "edit_execute",
    }
    assert "jd_url_fetch" not in tool_names
    assert "jd_reference_search" not in tool_names


def test_agent_web_fetch_schema_requires_only_url() -> None:
    schema = next(
        schema
        for schema in agent_contracts.AGENT_TOOL_SCHEMAS
        if schema["function"]["name"] == "web_fetch"
    )
    parameters = schema["function"]["parameters"]

    assert parameters["required"] == ["url"]
    assert set(parameters["properties"]) == {"url"}
    assert parameters["additionalProperties"] is False


def test_agent_web_fetch_returns_a_readable_public_page_observation(
    monkeypatch,
) -> None:
    async def fetch_reference(*_: object) -> WebReference:
        return WebReference(
            title="Example Graduate Program",
            excerpt="Official admissions requirements and research areas.",
            final_url="https://example.test/graduate-program",
            passages=(
                agent_web.WebPassage(
                    section="Admissions",
                    text="Official admissions requirements and research areas.",
                ),
            ),
        )

    monkeypatch.setattr(
        agent_web,
        "_async_fetch_web_reference",
        fetch_reference,
    )
    request = AgentChatRequest(
        message={
            "id": "agent-user-web-fetch-public-context-is-not-candidate-evidence",
            "role": "user",
            "text": "请参考 https://example.test/graduate-program 的申请要求",
        },
        locale="zh",
        resume={"basic": {}, "sections": []},
    )
    environment = ResumeToolEnvironment.open(request)

    tool, result = invoke_agent_tool(
        environment,
        tool_call(
            "call-web-fetch",
            "web_fetch",
            {"url": "https://example.test/graduate-program"},
        ),
    )

    assert tool.state == "output-available"
    assert result["output"]["references"][0]["title"] == ("Example Graduate Program")


def test_agent_suggest_only_filters_and_blocks_edit_tools() -> None:
    request = prepare_agent_request(
        AgentChatRequest(
            message={
                "id": "agent-user-suggest-only-filters-and-blocks-edit-tools",
                "role": "user",
                "text": "优化个人简介",
            },
            locale="zh",
            resume={
                "basic": {"summary": "已有简介"},
                "sections": [],
            },
        ),
        normalize_agent_settings({"confirmationMode": "suggestOnly"}),
    )

    environment = ResumeToolEnvironment.open(request)
    schema_names = {schema["function"]["name"] for schema in environment.tool_schemas}

    assert schema_names == {"web_search", "web_fetch"}

    tool, result = invoke_agent_tool(
        environment,
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
    assert environment.close(completed=True).edits == ()


def test_agent_delete_operations_are_previewed_without_text_intent_routing() -> None:
    resume = minimal_resume_document()
    resume["sections"] = [
        {
            "id": "project",
            "kind": "project",
            "title": "项目经历",
            "items": [
                {
                    "id": "project-1",
                    "name": "Reseno",
                    "role": "",
                    "techStack": [],
                    "period": "",
                    "url": "",
                    "description": "",
                    "highlights": [],
                },
            ],
        },
    ]
    request = AgentChatRequest(
        message={
            "id": "agent-user-delete-operations-require-explicit-delete-intent",
            "role": "user",
            "text": "优化项目经历",
        },
        locale="zh",
        resume=resume,
    )
    environment = ResumeToolEnvironment.open(request)

    tool, result = invoke_agent_tool(
        environment,
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

    assert tool.state == "output-available"
    assert tool.output["observations"][0]["after"] is None
    assert result["output"] == {"status": "accepted", "editCount": 1}
    assert len(environment.close(completed=True).edits) == 1


def test_agent_edit_operation_schema_requires_operation_specific_fields() -> None:
    variants = agent_contracts.OPERATION_SCHEMA["oneOf"]
    by_type = {variant["properties"]["type"]["const"]: variant for variant in variants}

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


def test_section_registry_endpoint_matches_document_contract(
    client: TestClient,
) -> None:
    response = client.get("/api/section-registry")

    assert response.status_code == 200
    sections = response.json()["data"]["sections"]
    assert sections == SECTION_REGISTRY
    assert {section["kind"] for section in sections} == set(ITEM_FIELDS_BY_KIND)


def _registry_section(kind: str, aliases: object) -> dict[str, object]:
    return {
        "kind": kind,
        "defaultLayout": "timeline",
        "labels": {"zh": kind, "en": kind},
        "aliases": aliases,
    }


def _load_test_section_registry(
    tmp_path: Path,
    monkeypatch,
    sections: list[dict[str, object]],
) -> list[dict[str, object]]:
    registry_path = tmp_path / "section_registry.json"
    registry_path.write_text(
        json.dumps({"sections": sections}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(section_registry_module, "REGISTRY_PATH", registry_path)
    return section_registry_module._load_section_registry()


def test_section_registry_rejects_non_object_payload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    registry_path = tmp_path / "section_registry.json"
    registry_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(section_registry_module, "REGISTRY_PATH", registry_path)

    with pytest.raises(ValueError, match="must contain an object"):
        section_registry_module._load_section_registry()


def test_section_registry_rejects_non_list_aliases(tmp_path: Path, monkeypatch) -> None:
    with pytest.raises(
        ValueError,
        match=r"Section kind education aliases must be a list\.",
    ):
        _load_test_section_registry(
            tmp_path,
            monkeypatch,
            [_registry_section("education", "education")],
        )


@pytest.mark.parametrize(
    "section",
    [
        {
            **_registry_section(" ", ["education"]),
            "labels": {"zh": "教育经历", "en": "Education"},
        },
        {
            **_registry_section("education", ["education"]),
            "labels": {"zh": " ", "en": "Education"},
        },
        {
            **_registry_section("education", ["education"]),
            "labels": {"zh": "教育经历", "en": " "},
        },
        {
            **_registry_section("education", ["education"]),
            "labels": {" ": "Education", "zh": "教育经历", "en": "Education"},
        },
        {
            **_registry_section(" education ", ["education"]),
            "labels": {"zh": "教育经历", "en": "Education"},
        },
    ],
)
def test_section_registry_rejects_whitespace_identifiers_and_labels(
    tmp_path: Path,
    monkeypatch,
    section: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        _load_test_section_registry(tmp_path, monkeypatch, [section])


@pytest.mark.parametrize("kind", ["Work", "work experience", "ｗｏｒｋ"])
def test_section_registry_rejects_noncanonical_kinds(
    tmp_path: Path,
    monkeypatch,
    kind: str,
) -> None:
    with pytest.raises(ValueError, match="canonical lowercase identifier"):
        _load_test_section_registry(
            tmp_path,
            monkeypatch,
            [_registry_section(kind, ["work"])],
        )


def test_section_registry_rejects_empty_aliases(tmp_path: Path, monkeypatch) -> None:
    with pytest.raises(ValueError, match="must be a non-empty list"):
        _load_test_section_registry(
            tmp_path,
            monkeypatch,
            [_registry_section("education", [])],
        )


@pytest.mark.parametrize("alias", [None, 7, "", " \t：: "])
def test_section_registry_rejects_invalid_alias_entries(
    tmp_path: Path,
    monkeypatch,
    alias: object,
) -> None:
    expected = (
        "is empty after normalization"
        if isinstance(alias, str) and alias.strip()
        else "must be a non-empty string"
    )
    with pytest.raises(
        ValueError,
        match=rf"Section kind education alias at index 0 {expected}",
    ):
        _load_test_section_registry(
            tmp_path,
            monkeypatch,
            [_registry_section("education", [alias])],
        )


def test_section_registry_rejects_normalized_duplicate_aliases(
    tmp_path: Path,
    monkeypatch,
) -> None:
    with pytest.raises(
        ValueError,
        match=(
            r"Section kind work alias at index 1 .* duplicates alias at index 0 "
            r".* after normalization\."
        ),
    ):
        _load_test_section_registry(
            tmp_path,
            monkeypatch,
            [
                _registry_section(
                    "work",
                    [" Work： Experience ", "workexperience"],
                )
            ],
        )


def test_section_registry_rejects_alias_conflicts_between_kinds(
    tmp_path: Path,
    monkeypatch,
) -> None:
    with pytest.raises(
        ValueError,
        match=(
            r"Section kind project alias at index 0 .* conflicts with section "
            r"kind work alias at index 0 .* after normalization\."
        ),
    ):
        _load_test_section_registry(
            tmp_path,
            monkeypatch,
            [
                _registry_section("work", ["Project Experience"]),
                _registry_section(
                    "project",
                    ["ＰＲＯＪＥＣＴ　ＥＸＰＥＲＩＥＮＣＥ："],
                ),
            ],
        )


def test_section_registry_rejects_pdf_compatibility_alias_conflicts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    with pytest.raises(ValueError, match="conflicts with section kind"):
        _load_test_section_registry(
            tmp_path,
            monkeypatch,
            [
                _registry_section("page", ["页"]),
                _registry_section("radical_page", ["⻚"]),
            ],
        )


def test_agent_chat_accepts_simple_list_section_kind() -> None:
    assert "simple_list" in {section["kind"] for section in SECTION_REGISTRY}

    edits, rejected = parse_edit_batch(
        minimal_resume_document(name="姓名"),
        [
            {
                "title": "新增其他经历",
                "target": "sections",
                "reason": "用户提供的内容适合放入其他经历。",
                "operation": {
                    "type": "insert_section",
                    "section": {
                        "id": "other-experience",
                        "kind": "simple_list",
                        "title": "其他经历",
                        "items": [
                            {
                                "id": "other-experience-1",
                                "content": "开源贡献：维护项目文档",
                            },
                        ],
                    },
                },
            },
        ],
        locale="zh",
    )

    assert rejected == []
    assert edits
    section = edits[0].operation["section"]
    assert section["kind"] == "simple_list"
    assert section["title"] == "其他经历"
    assert section["items"][0]["content"] == "开源贡献：维护项目文档"


def test_agent_chat_rejects_noncanonical_list_item_content() -> None:
    edits, rejected = parse_edit_batch(
        minimal_resume_document(name="姓名"),
        [
            {
                "title": "新增技能",
                "target": "sections",
                "reason": "添加技能分组。",
                "operation": {
                    "type": "insert_section",
                    "section": {
                        "section_type": "skills",
                        "layout": "list",
                        "items": [
                            {
                                "title": "前端",
                                "subtitle": "",
                                "meta": "",
                                "period": "",
                                "description": "",
                                "highlights": ["React"],
                            },
                        ],
                    },
                },
            },
        ],
        locale="zh",
    )

    assert edits == []
    assert len(rejected) == 1
    assert "Canonical protocol error" in rejected[0]["reason"]


def test_agent_chat_plain_message_does_not_return_tools(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    monkeypatch.setattr(
        ASYNC_STREAM_TOOL_CALL_PATH,
        stub_terminal_tool_text("你好，我可以回答简历相关问题。"),
    )
    monkeypatch.setattr(
        ASYNC_STREAM_CHAT_PATH,
        fail_on_second_final_stream,
    )

    _, message = post_agent_chat_stream(
        client,
        {
            "message": {
                "id": "agent-user-chat-plain-message-does-not-return-tools",
                "role": "user",
                "text": "你好",
            },
            "messages": [],
            "locale": "zh",
            "resume": {"basic": {"name": "王小明"}, "sections": []},
            "modelConfig": model_config,
        },
    )

    assert message["text"] == "你好，我可以回答简历相关问题。"
    assert message["tools"] == []
    assert message["edits"] == []


def test_agent_chat_plain_natural_stop_skips_second_completion(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    monkeypatch.setattr(
        ASYNC_STREAM_TOOL_CALL_PATH,
        stub_terminal_tool_text("工具选择阶段的半截回答"),
    )

    monkeypatch.setattr(ASYNC_STREAM_CHAT_PATH, fail_on_second_final_stream)

    with client.stream(
        "POST",
        "/api/agent/chat",
        headers={"accept": "text/event-stream"},
        json={
            "message": {
                "id": "agent-user-chat-plain-stream-uses-final-completion",
                "role": "user",
                "text": "你好",
            },
            "messages": [],
            "locale": "zh",
            "resume": {"basic": {"name": "王小明"}, "sections": []},
            "modelConfig": model_config,
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "工具选择阶段的半截回答" in body
    assert "event: text_delta" in body


def test_agent_chat_without_tool_support_still_streams_plain_response(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    with connect() as conn:
        conn.execute(
            """
            UPDATE llm_configs
            SET supports_tools = 0
            WHERE client_id = ?
            """,
            (model_config["id"],),
        )

    async def unexpected_tool_call(*_: object, **__: object) -> object:
        raise AssertionError("tool loop should be skipped for this model")

    monkeypatch.setattr(ASYNC_STREAM_TOOL_CALL_PATH, unexpected_tool_call)
    monkeypatch.setattr(
        ASYNC_STREAM_CHAT_PATH,
        stub_stream_text("这个模型不能调用工具，但可以直接回答问题。"),
    )

    _, message = post_agent_chat_stream(
        client,
        {
            "message": {
                "id": "agent-user-no-tool-support",
                "role": "user",
                "text": "你好",
            },
            "messages": [],
            "locale": "zh",
            "resume": {"basic": {"name": "王小明"}, "sections": []},
            "modelConfig": model_config,
        },
    )

    assert message["text"] == "这个模型不能调用工具，但可以直接回答问题。"
    assert message["tools"] == []
    assert message["edits"] == []


def test_agent_chat_without_streaming_support_uses_non_streaming_completion(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    with connect() as conn:
        conn.execute(
            """
            UPDATE llm_configs
            SET supports_tools = 0,
                supports_streaming = 0
            WHERE client_id = ?
            """,
            (model_config["id"],),
        )

    async def unexpected_tool_call(*_: object, **__: object) -> object:
        raise AssertionError("tool loop should be skipped for this model")

    async def unexpected_stream(*_: object, **__: object) -> object:
        raise AssertionError("provider stream should be skipped for this model")

    async def complete_response(*_: object, **__: object) -> LlmAssistantMessage:
        return LlmAssistantMessage(
            content="这个模型不支持流式，但仍然可以直接回答问题。",
            stop_reason="stop",
        )

    monkeypatch.setattr(ASYNC_STREAM_TOOL_CALL_PATH, unexpected_tool_call)
    monkeypatch.setattr(ASYNC_STREAM_CHAT_PATH, unexpected_stream)
    monkeypatch.setattr(ASYNC_COMPLETE_CHAT_PATH, complete_response)

    body, message = post_agent_chat_stream(
        client,
        {
            "message": {
                "id": "agent-user-no-stream-support",
                "role": "user",
                "text": "你好",
            },
            "messages": [],
            "locale": "zh",
            "resume": {"basic": {"name": "王小明"}, "sections": []},
            "modelConfig": model_config,
        },
    )

    assert "event: text_delta" in body
    assert "这个模型不支持流式，但仍然可以直接回答问题。" in body
    assert message["text"] == "这个模型不支持流式，但仍然可以直接回答问题。"
    assert message["tools"] == []
    assert message["edits"] == []


def test_agent_chat_material_gap_asks_followup_questions(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    monkeypatch.setattr(
        ASYNC_STREAM_TOOL_CALL_PATH,
        stub_terminal_tool_text(
            "请补充项目事实：你本人具体负责哪一部分、用了哪些技术、有没有结果。",
        ),
    )
    monkeypatch.setattr(
        ASYNC_STREAM_CHAT_PATH,
        fail_on_second_final_stream,
    )

    _, message = post_agent_chat_stream(
        client,
        {
            "message": {
                "id": "agent-user-chat-material-gap-asks-followup-questions",
                "role": "user",
                "text": "帮我生成一个项目经历草稿",
            },
            "messages": [],
            "locale": "zh",
            "resume": {"basic": {}, "sections": []},
            "modelConfig": model_config,
        },
    )

    assert message["tools"] == []
    assert message["edits"] == []
    assert "你本人具体负责哪一部分" in message["text"]
    assert "用了哪些技术" in message["text"]
    assert "有没有结果" in message["text"]


def test_agent_chat_reports_invalid_model_edit_operation(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    monkeypatch.setattr(
        ASYNC_STREAM_TOOL_CALL_PATH,
        stub_tool_call_responses(
            LlmAssistantMessage(
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
            LlmAssistantMessage(
                content="需要补充 itemId 后才能继续生成可预览草稿。",
                tool_calls=[],
            ),
        ),
    )

    _, message = post_agent_chat_stream(
        client,
        {
            "message": {
                "id": "agent-user-chat-reports-invalid-model-edit-operation",
                "role": "user",
                "text": "补强项目结果",
            },
            "messages": [],
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
            "modelConfig": model_config,
        },
    )

    tool = message["tools"][0]
    rejected_edit = tool["output"]["rejectedEdits"][0]
    assert "需要补充 itemId 后才能继续生成可预览草稿。" in message["text"]
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

    def raise_provider_error(*_: object, **__: object) -> str:
        raise LlmRequestError("provider unavailable")

    monkeypatch.setattr(
        ASYNC_STREAM_TOOL_CALL_PATH,
        raise_provider_error,
    )

    body, message = post_agent_chat_stream(
        client,
        {
            "message": {
                "id": "agent-user-model-error-does-not-return-llm-tool",
                "role": "user",
                "text": "你好",
            },
            "messages": [],
            "locale": "zh",
            "resume": {"basic": {"name": "王小明"}, "sections": []},
            "modelConfig": model_config,
        },
    )

    assert "调用模型失败" in message["text"]
    assert "provider unavailable" not in message["text"]
    assert "Model provider request failed." in message["text"]
    assert "event: error" in body
    assert '"errorCode":"AGENT_PROVIDER_ERROR"' in body
    assert message["tools"] == []


def test_agent_chat_uses_provided_jd_url(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    monkeypatch.setattr(
        ASYNC_STREAM_CHAT_PATH,
        fail_on_second_final_stream,
    )
    monkeypatch.setattr(
        ASYNC_STREAM_TOOL_CALL_PATH,
        stub_tool_call_responses(
            LlmAssistantMessage(
                content="",
                tool_calls=[
                    tool_call(
                        "call-jd",
                        "web_fetch",
                        {"url": "https://example.test/jobs/frontend"},
                    ),
                ],
            ),
            LlmAssistantMessage(
                content="",
                tool_calls=[
                    tool_call(
                        "call-execute",
                        "edit_execute",
                        {
                            "edits": [
                                {
                                    "title": "调整模块顺序",
                                    "target": "sections",
                                    "reason": "将项目经历前置。",
                                    "operation": {
                                        "type": "reorder_sections",
                                        "sectionIds": ["project", "education"],
                                    },
                                },
                            ],
                        },
                    ),
                ],
            ),
            LlmAssistantMessage(content="Draft is complete.", tool_calls=[]),
        ),
    )

    async def fetch_reference(*_: object) -> WebReference:
        return WebReference(
            title="Frontend Engineer Job",
            excerpt="React TypeScript responsibilities and requirements.",
            final_url="https://example.test/jobs/frontend",
            passages=(
                agent_web.WebPassage(
                    section="Requirements",
                    text="React TypeScript responsibilities and requirements.",
                ),
            ),
        )

    monkeypatch.setattr(
        agent_web,
        "_async_fetch_web_reference",
        fetch_reference,
    )
    resume = minimal_resume_document(name="王小明", summary="前端开发。")
    resume["sections"] = [
        {
            "id": "education",
            "kind": "education",
            "title": "教育经历",
            "items": [
                {
                    "id": "edu-1",
                    "school": "大学",
                    "degree": "",
                    "major": "",
                    "gpa": "",
                    "location": "",
                    "period": "",
                    "description": "",
                    "highlights": [],
                },
            ],
        },
        {
            "id": "project",
            "kind": "project",
            "title": "项目经历",
            "items": [
                {
                    "id": "project-1",
                    "name": "项目",
                    "role": "",
                    "techStack": [],
                    "period": "",
                    "url": "",
                    "description": "",
                    "highlights": [],
                },
            ],
        },
    ]

    _, message = post_agent_chat_stream(
        client,
        {
            "message": {
                "id": "agent-user-1",
                "role": "user",
                "text": "请基于 https://example.test/jobs/frontend 调整模块顺序",
            },
            "messages": [],
            "locale": "zh",
            "resume": resume,
            "modelConfig": model_config,
        },
    )

    assert any(tool["title"] == "web_fetch" for tool in message["tools"])
    assert len(message["sources"]) == 1
    source = message["sources"][0]
    assert re.fullmatch(r"source-web-[0-9a-f]{16}", source["id"])
    assert {key: value for key, value in source.items() if key != "id"} == {
        "title": "Frontend Engineer Job",
        "sourceType": "web",
        "url": "https://example.test/jobs/frontend",
        "excerpt": "React TypeScript responsibilities and requirements.",
    }
    assert any(
        edit["operation"]["type"] == "reorder_sections" for edit in message["edits"]
    )


def test_agent_chat_defers_sibling_edit_until_failed_read_is_observed(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    edit_arguments = {
        "edits": [
            {
                "title": "优化个人简介",
                "target": "basic.summary",
                "reason": "让已有经历表达更聚焦。",
                "operation": {
                    "type": "replace_field",
                    "path": "basic.summary",
                    "value": "聚焦复杂交互与工程质量。",
                },
            },
        ],
    }

    async def failed_fetch(
        _url: str,
        _relevance_query: str,
        _reference_title: str,
        _browser: object,
    ) -> None:
        return None

    monkeypatch.setattr(
        agent_web,
        "_async_fetch_web_reference",
        failed_fetch,
    )
    monkeypatch.setattr(
        ASYNC_STREAM_TOOL_CALL_PATH,
        stub_tool_call_batches(
            [
                tool_call(
                    "call-web-failure-before-edit",
                    "web_fetch",
                    {"url": "https://example.test/jobs/frontend"},
                ),
                tool_call(
                    "call-edit-after-timeout",
                    "edit_execute",
                    edit_arguments,
                ),
            ],
        ),
    )

    _, message = post_agent_chat_stream(
        client,
        {
            "message": {
                "id": "agent-user-chat-read-failure-before-edit",
                "role": "user",
                "text": (
                    "候选人事实：我关注复杂交互与工程质量。"
                    "请参考 https://example.test/jobs/frontend "
                    "针对前端工程师岗位优化个人简介。"
                ),
            },
            "messages": [],
            "locale": "zh",
            "resume": minimal_resume_document(
                name="王小明",
                summary="关注工程质量。",
            ),
            "modelConfig": model_config,
        },
    )

    assert [tool["title"] for tool in message["tools"]] == ["web_fetch"]
    assert message["tools"][0]["state"] == "output-error"
    assert message["transactionState"] == "none"
    assert message["edits"] == []


def test_agent_chat_lets_model_diagnose_jd_gap_from_workspace(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    monkeypatch.setattr(
        ASYNC_STREAM_TOOL_CALL_PATH,
        stub_terminal_tool_text(
            "差距诊断：已匹配 Python；缺少 RAG 和 evaluation；需要补充项目证据。",
        ),
    )

    _, message = post_agent_chat_stream(
        client,
        {
            "message": {
                "id": "agent-user-chat-streams-jd-gap-diagnosis-without-edits",
                "role": "user",
                "text": (
                    "目标 AI application developer 要求 Python、RAG 和 evaluation；"
                    "这份简历和 JD 的差距在哪里？"
                ),
            },
            "messages": [],
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
            "modelConfig": model_config,
        },
    )

    tool_titles = [tool["title"] for tool in message["tools"]]
    assert message["edits"] == []
    assert "差距诊断" in message["text"]
    assert tool_titles == []
    assert "edit_execute" not in tool_titles


def test_agent_chat_streams_tool_and_source_metadata(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    monkeypatch.setattr(
        agent_web,
        "_async_fetch_web_reference",
        async_stub_jd_fetch,
    )
    monkeypatch.setattr(
        ASYNC_STREAM_TOOL_CALL_PATH,
        stub_tool_call_responses(
            LlmAssistantMessage(
                content="",
                tool_calls=[
                    tool_call(
                        "call-jd",
                        "web_fetch",
                        {"url": "https://example.test/jobs/frontend"},
                    ),
                ],
            ),
            LlmAssistantMessage(
                content="流式真实模型响应",
                tool_calls=[],
            ),
        ),
    )

    with client.stream(
        "POST",
        "/api/agent/chat",
        headers={"accept": "text/event-stream"},
        json={
            "message": {
                "id": "agent-user-chat-streams-tool-and-source-metadata",
                "role": "user",
                "text": (
                    "基于 https://example.test/jobs/frontend 分析前端开发工程师"
                    "岗位与个人简介的匹配度，只分析不要修改"
                ),
            },
            "messages": [],
            "locale": "zh",
            "resume": {"basic": {"name": "王小明"}, "sections": []},
            "modelConfig": model_config,
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: message_start" in body
    assert "event: plan" not in body
    assert "event: timeline" not in body
    assert "event: text_delta" in body
    assert "我先分析目标岗位和当前简历" not in body
    assert "event: tool_start" in body
    assert "event: tool_delta" not in body
    assert "event: tool_done" in body
    assert '"state":"input-available"' in body
    assert '"state":"output-available"' in body
    assert "event: message_delta" not in body
    assert "event: message_done" in body
    assert "流式真实模型响应" in body
    assert body.index("web_fetch") < body.index("流式真实模型响应")
    assert body.index("event: tool_start") < body.index("流式真实模型响应")
    assert body.index('"source-web-') < body.index("流式真实模型响应")
    assert '"tools":' in body
    assert '"source-web-' in body
    assert '"edits":[]' in body
    assert "edit_execute" not in body


def test_agent_chat_streams_model_narration_during_edit_loop(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    monkeypatch.setattr(
        ASYNC_STREAM_TOOL_CALL_PATH,
        stub_tool_call_responses(
            LlmAssistantMessage(
                content="我发现简介比较短，现在直接生成修改草稿。",
                tool_calls=[
                    tool_call(
                        "call-execute",
                        "edit_execute",
                        {
                            "edits": [
                                {
                                    "title": "优化个人简介",
                                    "target": "basic.summary",
                                    "reason": "让已有经历表达更聚焦。",
                                    "operation": {
                                        "type": "replace_field",
                                        "path": "basic.summary",
                                        "value": "具备前端项目经验。",
                                    },
                                },
                            ],
                        },
                    ),
                ],
            ),
            LlmAssistantMessage(content="最后给出草稿建议。", tool_calls=[]),
        ),
    )

    with client.stream(
        "POST",
        "/api/agent/chat",
        headers={"accept": "text/event-stream"},
        json={
            "message": {
                "id": "agent-user-chat-streams-model-narration-between-tool-actions",
                "role": "user",
                "text": "优化个人简介",
            },
            "messages": [],
            "locale": "zh",
            "resume": minimal_resume_document(
                name="王小明",
                summary="有前端项目经验。",
            ),
            "modelConfig": model_config,
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: updates" not in body
    assert "event: timeline" not in body
    assert "event: text_delta" in body
    assert "我发现简介比较短，现在直接生成修改草稿。" in body
    expected_text = "最后给出草稿建议。"
    assert body.index("我发现简介比较短") < body.index("edit_execute")
    assert body.index("edit_execute") < body.index(expected_text)
    assert expected_text in body

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
        ["call-execute"],
    ]


def test_agent_chat_streams_model_tool_batch_as_ordered_timeline_operations(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    monkeypatch.setattr(
        agent_web,
        "_async_fetch_web_reference",
        async_stub_jd_fetch,
    )
    monkeypatch.setattr(
        ASYNC_STREAM_TOOL_CALL_PATH,
        stub_tool_call_responses(
            LlmAssistantMessage(
                content="我先同时检查简历结构和岗位参考。",
                tool_calls=[
                    tool_call(
                        "call-role",
                        "web_fetch",
                        {"url": "https://example.test/jobs/frontend"},
                    ),
                    tool_call(
                        "call-jd",
                        "web_fetch",
                        {"url": "https://example.test/jobs/frontend-details"},
                    ),
                ],
            ),
            LlmAssistantMessage(
                content="下一步会基于这些结果给出草稿。",
                tool_calls=[],
            ),
        ),
    )

    with client.stream(
        "POST",
        "/api/agent/chat",
        headers={"accept": "text/event-stream"},
        json={
            "message": {
                "id": "agent-user-tool-batch",
                "role": "user",
                "text": (
                    "参考 https://example.test/jobs/frontend 和 "
                    "https://example.test/jobs/frontend-details "
                    "针对前端开发工程师岗位优化个人简介"
                ),
            },
            "messages": [],
            "locale": "zh",
            "resume": {
                "basic": {"name": "王小明", "summary": "有前端项目经验。"},
                "sections": [],
            },
            "modelConfig": model_config,
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: plan" not in body
    assert "event: timeline" not in body
    assert "event: text_delta" in body
    assert "我先同时检查简历结构和岗位参考。" in body
    assert body.index("call-role") < body.index("call-jd")
    assert body.index("call-jd") < body.index(
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
        ["call-role", "call-jd"]
    ]


def test_agent_chat_streams_terminal_model_text_after_tool_observation(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    preface = "我先查阅公开的前端工程师简历建议。"
    terminal_text = (
        "P1：先修正腾讯经历中公司、职位和地点字段错位，确保招聘者能够快速识别"
        "任职主体与实际职责。\n\n"
        "P2：补全个人标题，并让简介同时覆盖教育背景、实习经历、项目经验和核心"
        "技能，但不要添加当前简历没有提供的数字。\n\n"
        "P3：将 Reseno 项目中散落在名称、角色、技术栈和描述里的内容归位，"
        "再用互不重复的亮点说明实现内容。\n\n"
        "P4：所有经历优先写清具体任务、采用的方法和已经存在的交付结果；缺少"
        "量化证据时应追问，而不是虚构性能提升或用户规模。\n\n"
        "P5：技能模块应拆分技术技能与语言能力，保留 React、TypeScript、"
        "Node.js、Prompt Engineering、英语 CET-6（544）和雅思 6.5。"
    )
    monkeypatch.setattr(
        agent_web,
        "_async_fetch_web_reference",
        async_stub_jd_fetch,
    )
    monkeypatch.setattr(
        ASYNC_STREAM_TOOL_CALL_PATH,
        stub_tool_call_responses(
            LlmAssistantMessage(
                content=preface,
                tool_calls=[
                    tool_call(
                        "call-fetch",
                        "web_fetch",
                        {"url": "https://example.test/resume-advice"},
                    ),
                ],
            ),
            LlmAssistantMessage(
                content=terminal_text,
                tool_calls=[],
            ),
        ),
    )
    monkeypatch.setattr(ASYNC_STREAM_CHAT_PATH, fail_on_second_final_stream)

    with client.stream(
        "POST",
        "/api/agent/chat",
        headers={"accept": "text/event-stream"},
        json={
            "message": {
                "id": "agent-user-terminal-model-text",
                "role": "user",
                "text": (
                    "结合 https://example.test/resume-advice 的前端工程师简历建议，"
                    "分析一下我的简历"
                ),
            },
            "messages": [],
            "locale": "zh",
            "resume": {
                "basic": {"name": "王小明", "summary": "有前端项目经验。"},
                "sections": [],
            },
            "modelConfig": model_config,
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert preface in body
    assert "P5：技能模块" in body
    assert body.index(preface) < body.index("web_fetch")
    assert body.index("web_fetch") < body.index("P5：技能模块")

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
    timeline = message["timeline"]
    assert message["text"] == terminal_text
    assert [part["type"] for part in timeline] == [
        "text",
        "tool_group",
        "text",
    ]
    assert timeline[0]["text"] == preface
    assert timeline[1]["toolIds"] == ["call-fetch"]
    assert timeline[-1]["text"] == terminal_text


def test_agent_chat_streams_edit_metadata_when_execute_finishes(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    monkeypatch.setattr(
        agent_web,
        "_async_fetch_web_reference",
        async_stub_jd_fetch,
    )
    monkeypatch.setattr(
        ASYNC_STREAM_TOOL_CALL_PATH,
        stub_tool_call_responses(
            LlmAssistantMessage(
                content="",
                tool_calls=[
                    tool_call(
                        "call-jd",
                        "web_fetch",
                        {"url": "https://example.test/jobs/frontend"},
                    ),
                ],
            ),
            LlmAssistantMessage(
                content="",
                tool_calls=[
                    tool_call(
                        "call-execute",
                        "edit_execute",
                        {
                            "edits": [
                                {
                                    "title": "优化个人简介",
                                    "target": "basic.summary",
                                    "reason": "让已有经历表达更聚焦。",
                                    "operation": {
                                        "type": "replace_field",
                                        "path": "basic.summary",
                                        "value": "具备前端项目经验。",
                                    },
                                },
                            ],
                        },
                    ),
                ],
            ),
            LlmAssistantMessage(content="草稿修改已完成。", tool_calls=[]),
        ),
    )

    monkeypatch.setattr(ASYNC_STREAM_CHAT_PATH, fail_on_second_final_stream)

    with client.stream(
        "POST",
        "/api/agent/chat",
        headers={"accept": "text/event-stream"},
        json={
            "message": {
                "id": "agent-user-chat-streams-edit-metadata-when-execute-finishes",
                "role": "user",
                "text": (
                    "参考 https://example.test/jobs/frontend "
                    "针对前端开发工程师岗位优化个人简介"
                ),
            },
            "messages": [],
            "locale": "zh",
            "resume": minimal_resume_document(
                name="王小明",
                summary="有前端项目经验。",
            ),
            "modelConfig": model_config,
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "我先分析目标岗位和当前简历" not in body
    assert "event: plan" not in body
    assert "event: tool_start" in body
    assert "event: tool_done" in body
    assert "event: edits" in body
    assert "event: text_delta" in body
    expected_text = "草稿修改已完成。"
    assert expected_text in body
    assert body.index("event: tool_start") < body.index(expected_text)
    assert body.index("event: edits") < body.index(expected_text)
    assert body.rindex('"edits":[{') > body.index(expected_text)
    assert '"edits":[{' in body
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
        "call-execute",
    ]


def test_agent_chat_streams_plain_model_tokens(
    client: TestClient,
    monkeypatch,
) -> None:
    model_config = create_agent_model_config(client)
    monkeypatch.setattr(
        ASYNC_STREAM_TOOL_CALL_PATH,
        stub_terminal_tool_text("你好，我可以帮你看简历。"),
    )

    with client.stream(
        "POST",
        "/api/agent/chat",
        headers={"accept": "text/event-stream"},
        json={
            "message": {
                "id": "agent-user-chat-streams-plain-model-tokens",
                "role": "user",
                "text": "你好",
            },
            "messages": [],
            "locale": "zh",
            "resume": {"basic": {"name": "王小明"}, "sections": []},
            "modelConfig": model_config,
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "正在等待模型返回" not in body
    assert "event: timeline" not in body
    assert "event: text_delta" in body
    assert "你好，我可以帮你看简历。" in body
    assert "event: tools" not in body


@pytest.mark.parametrize("body", [b"{not-json", b"\xff"])
def test_import_rejects_invalid_json_upload(
    client: TestClient,
    body: bytes,
) -> None:
    for endpoint in ("/api/import/resume", "/api/import/templates"):
        response = client.post(
            endpoint,
            files={
                "file": ("artifact.json", body, "application/json"),
            },
        )

        assert response.status_code == 400
        assert response.json()["code"] == 40000
        assert response.json()["message"] == "JSON_UPLOAD_INVALID"


def test_import_resume_accepts_v1_artifact(client: TestClient) -> None:
    resume_item = resume_artifact_item(title="Avery")
    response = client.post(
        "/api/import/resume",
        files={
            "file": (
                "resume.json",
                json.dumps(
                    {
                        "format": "reseno.resume",
                        "formatVersion": 1,
                        "templates": [],
                        "resumes": [resume_item],
                    }
                ).encode("utf-8"),
                "application/json",
            ),
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["templates"] == []
    resume = response.json()["data"]["resumes"][0]
    assert set(resume) == {
        "title",
        "documentLocale",
        "resume",
        "jobBrief",
        "typography",
        "template",
        "templateSettings",
    }
    assert resume["resume"]["basic"]["name"] == "Avery"
    assert resume["templateSettings"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"resumes": [resume_artifact_item(title="Missing envelope")]},
        {
            "format": "reseno.resume",
            "format_version": 1,
            "templates": [],
            "resumes": [resume_artifact_item(title="Snake case")],
        },
        {
            "format": "reseno.resume",
            "formatVersion": 2,
            "templates": [],
            "resumes": [resume_artifact_item(title="Unsupported version")],
        },
        {
            "format": "reseno.resume",
            "formatVersion": 1,
            "templates": [],
            "resumes": [],
        },
        {
            "format": "reseno.resume",
            "formatVersion": 1,
            "templates": [],
            "resumes": [{**resume_artifact_item(), "id": "server-owned-id"}],
        },
        {
            "format": "reseno.resume",
            "formatVersion": 1,
            "templates": [],
            "resumes": [
                {
                    key: value
                    for key, value in resume_artifact_item().items()
                    if key != "documentLocale"
                }
            ],
        },
        {
            "format": "reseno.resume",
            "formatVersion": 1,
            "templates": [],
            "resumes": [
                {
                    key: value
                    for key, value in resume_artifact_item().items()
                    if key != "templateSettings"
                }
            ],
        },
        {
            "format": "reseno.resume",
            "formatVersion": 1,
            "templates": [],
            "resumes": [
                {
                    **resume_artifact_item(),
                    "typography": {"fontFamily": "inter", "fontSize": 13},
                }
            ],
        },
        {
            "format": "reseno.resume",
            "formatVersion": 1,
            "templates": [],
            "resumes": [
                {
                    **resume_artifact_item(),
                    "templateSettings": {"unknownSetting": 1},
                }
            ],
        },
        {
            "format": "reseno.resume",
            "formatVersion": 1,
            "templates": [],
            "resumes": [
                {
                    **resume_artifact_item(),
                    "templateSettings": {"pagePaddingX": None},
                }
            ],
        },
    ],
)
def test_import_resume_rejects_invalid_or_non_v1_artifacts(
    client: TestClient,
    payload: object,
) -> None:
    response = client.post(
        "/api/import/resume",
        files={
            "file": (
                "resume.json",
                json.dumps(payload).encode("utf-8"),
                "application/json",
            ),
        },
    )

    assert response.status_code == 400
    assert response.json()["code"] == 40000
    assert response.json()["message"] in {
        "RESUME_ARTIFACT_INVALID",
        "RESUME_ARTIFACT_VERSION_UNSUPPORTED",
    }


def test_import_resume_rejects_noncanonical_list_item_content(
    client: TestClient,
) -> None:
    artifact_item = resume_artifact_item(title="Invalid List Resume")
    payload = {
        "format": "reseno.resume",
        "formatVersion": 1,
        "templates": [],
        "resumes": [{**artifact_item, "resume": noncanonical_list_resume()}],
    }
    response = client.post(
        "/api/import/resume",
        files={
            "file": (
                "resume.json",
                json.dumps(payload).encode("utf-8"),
                "application/json",
            ),
        },
    )

    assert response.json()["code"] == 40000
    assert response.json()["message"] == "RESUME_DOCUMENT_INVALID"


def test_import_resume_accepts_embedded_custom_template_bundle(
    client: TestClient,
) -> None:
    template = template_artifact_item(name="Portable custom template")
    resume = {
        **resume_artifact_item(title="Portable resume"),
        "template": "custom:0",
        "templateSettings": {"pagePaddingX": 10},
    }
    payload = {
        "format": "reseno.resume",
        "formatVersion": 1,
        "templates": [{"ref": "custom:0", "definition": template}],
        "resumes": [resume],
    }

    response = client.post(
        "/api/import/resume",
        files={
            "file": (
                "resume.json",
                json.dumps(payload).encode("utf-8"),
                "application/json",
            ),
        },
    )

    assert response.status_code == 200
    assert response.json()["code"] == 0
    assert response.json()["data"] == {
        "templates": [{"ref": "custom:0", "definition": template}],
        "resumes": [resume],
    }


def test_import_resume_accepts_multiple_resumes_sharing_embedded_template(
    client: TestClient,
) -> None:
    template = template_artifact_item(name="Shared portable template")
    resumes = [
        {
            **resume_artifact_item(title="First portable resume"),
            "template": "custom:0",
            "templateSettings": {"pagePaddingX": 10},
        },
        {
            **resume_artifact_item(title="Second portable resume"),
            "template": "custom:0",
            "templateSettings": None,
        },
    ]
    payload = {
        "format": "reseno.resume",
        "formatVersion": 1,
        "templates": [{"ref": "custom:0", "definition": template}],
        "resumes": resumes,
    }

    response = client.post(
        "/api/import/resume",
        files={
            "file": (
                "resume.json",
                json.dumps(payload).encode("utf-8"),
                "application/json",
            ),
        },
    )

    assert response.status_code == 200
    assert response.json()["code"] == 0
    assert response.json()["data"] == {
        "templates": [{"ref": "custom:0", "definition": template}],
        "resumes": resumes,
    }


@pytest.mark.parametrize(
    "templates, template_id",
    [
        ([], "custom:0"),
        (
            [{"ref": "custom:01", "definition": template_artifact_item()}],
            "custom:01",
        ),
        ([{"ref": "custom:0", "definition": template_artifact_item()}], "minimal"),
        (
            [
                {"ref": "custom:0", "definition": template_artifact_item()},
                {"ref": "custom:0", "definition": template_artifact_item()},
            ],
            "custom:0",
        ),
        ([], "template-local-id"),
    ],
)
def test_import_resume_rejects_invalid_custom_template_references(
    client: TestClient,
    templates: list[dict],
    template_id: str,
) -> None:
    payload = {
        "format": "reseno.resume",
        "formatVersion": 1,
        "templates": templates,
        "resumes": [{**resume_artifact_item(), "template": template_id}],
    }

    response = client.post(
        "/api/import/resume",
        files={
            "file": (
                "resume.json",
                json.dumps(payload).encode("utf-8"),
                "application/json",
            ),
        },
    )

    assert response.status_code == 400
    assert response.json()["code"] == 40000
    assert response.json()["message"] == "RESUME_ARTIFACT_INVALID"


def test_import_templates_accepts_v1_artifact(client: TestClient) -> None:
    template = template_artifact_item(name="Imported template")
    payload = {
        "format": "reseno.template",
        "formatVersion": 1,
        "templates": [template],
    }

    response = client.post(
        "/api/import/templates",
        files={
            "file": (
                "template.json",
                json.dumps(payload).encode("utf-8"),
                "application/json",
            ),
        },
    )
    assert response.status_code == 200
    assert response.json()["data"]["templates"] == [template]


@pytest.mark.parametrize(
    "payload, expected_message",
    [
        (
            {
                "format": "reseno.template",
                "formatVersion": 2,
                "templates": [template_artifact_item()],
            },
            "TEMPLATE_ARTIFACT_VERSION_UNSUPPORTED",
        ),
        (
            {
                "format": "reseno.template",
                "formatVersion": 1,
                "templates": [],
            },
            "TEMPLATE_ARTIFACT_INVALID",
        ),
        (
            {
                "format": "reseno.template",
                "formatVersion": 1,
                "templates": [
                    {**template_artifact_item(), "preset": "unknown-template"}
                ],
            },
            "TEMPLATE_ARTIFACT_INVALID",
        ),
        (
            {
                "format": "reseno.template",
                "formatVersion": 1,
                "templates": [
                    {
                        **template_artifact_item(),
                        "updatedAt": "2026-08-31T00:00:00.000Z",
                    }
                ],
            },
            "TEMPLATE_ARTIFACT_INVALID",
        ),
        (
            {
                "format": "reseno.template",
                "formatVersion": 1,
                "templates": [
                    {
                        **template_artifact_item(),
                        "layout": {
                            key: value
                            for key, value in template_artifact_item()["layout"].items()
                            if key != "timelineItemLayout"
                        },
                    }
                ],
            },
            "TEMPLATE_ARTIFACT_INVALID",
        ),
        (
            {
                "format": "reseno.template",
                "formatVersion": 1,
                "templates": [
                    {
                        **template_artifact_item(),
                        "settings": {
                            **template_artifact_item()["settings"],
                            "bodyColor": "not-a-color",
                        },
                    }
                ],
            },
            "TEMPLATE_ARTIFACT_INVALID",
        ),
    ],
)
def test_import_templates_rejects_non_v1_artifacts(
    client: TestClient,
    payload: object,
    expected_message: str,
) -> None:
    response = client.post(
        "/api/import/templates",
        files={
            "file": (
                "template.json",
                json.dumps(payload).encode("utf-8"),
                "application/json",
            ),
        },
    )

    assert response.status_code == 400
    assert response.json()["code"] == 40000
    assert response.json()["message"] == expected_message


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
        return export_path

    monkeypatch.setattr("app.routers.exports.write_resume_pdf", write_test_pdf)

    create_response = client.post(
        "/api/resumes",
        json={
            "documentLocale": "en",
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
            "fileNameSeed": "resume-en",
            "savedAt": "2026-05-16T00:00:00.000Z",
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


def test_export_pdf_rejects_client_render_base_url(
    client: TestClient,
    monkeypatch,
) -> None:
    render_called = False

    def unexpected_write(*_: object, **__: object) -> Path:
        nonlocal render_called
        render_called = True
        raise AssertionError("The renderer must not receive a client-controlled URL.")

    monkeypatch.setattr("app.routers.exports.write_resume_pdf", unexpected_write)

    create_response = client.post(
        "/api/resumes",
        json={
            "documentLocale": "en",
            "title": "Protected Export Resume",
            "resume": minimal_resume_item(title="Protected Export Resume")["resume"],
            "template": "minimal",
        },
    )
    resume_id = create_response.json()["data"]["resume"]["id"]

    response = client.post(
        "/api/exports/resume-pdf",
        json={
            "resumeId": resume_id,
            "fileNameSeed": "protected-export",
            "savedAt": "2026-05-16T00:00:00.000Z",
            "renderBaseUrl": "https://attacker.example",
        },
    )

    payload = response.json()
    assert response.status_code == 422
    assert payload["code"] == 40002
    assert payload["message"] == "VALIDATION_ERROR"
    assert any(
        error["loc"][-1] == "renderBaseUrl" and error["type"] == "extra_forbidden"
        for error in payload["data"]["errors"]
    )
    assert render_called is False


def test_export_render_url_uses_only_server_configuration(monkeypatch) -> None:
    from urllib.parse import parse_qs, urlsplit

    from app.services.pdf import build_render_url

    monkeypatch.setenv(
        "FRONTEND_RENDER_BASE_URL",
        "https://renderer.example/internal",
    )
    get_settings.cache_clear()

    try:
        render_url = build_render_url(
            ExportResumePdfRequest(
                resumeId="resumeconfiguredrenderer",
                fileNameSeed="resume",
                savedAt="2026-05-16T00:00:00.000Z",
                versionId="7",
            ),
            "en",
        )
    finally:
        get_settings.cache_clear()

    parsed = urlsplit(render_url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "renderer.example"
    assert parsed.path == "/internal/pdf-export"
    assert parse_qs(parsed.query) == {
        "documentLocale": ["en"],
        "resumeId": ["resumeconfiguredrenderer"],
        "savedAt": ["2026-05-16T00:00:00.000Z"],
        "versionId": ["7"],
    }


def test_export_pdf_uses_requested_resume_version_document_locale(
    client: TestClient,
    monkeypatch,
) -> None:
    document_locales: list[str] = []

    def write_test_pdf(
        export_id: str,
        _request: ExportResumePdfRequest,
        *,
        document_locale: str,
        **_: object,
    ) -> Path:
        from app.services.pdf import get_export_path

        document_locales.append(document_locale)
        export_path = get_export_path(export_id)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_bytes(b"%PDF-1.4\n% test\n")
        return export_path

    monkeypatch.setattr("app.routers.exports.write_resume_pdf", write_test_pdf)

    create_response = client.post(
        "/api/resumes",
        json={
            "documentLocale": "zh",
            "title": "Versioned export",
            "resume": minimal_resume_item(title="Versioned export")["resume"],
            "template": "minimal",
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()["data"]
    save_response = client.put(
        f"/api/resumes/{created['resume']['id']}",
        json=resume_save_payload(created["resume"], documentLocale="en"),
    )
    assert save_response.status_code == 200
    saved = save_response.json()["data"]

    current_response = client.post(
        "/api/exports/resume-pdf",
        json={
            "resumeId": created["resume"]["id"],
            "fileNameSeed": "current",
            "savedAt": saved["savedAt"],
        },
    )
    historical_response = client.post(
        "/api/exports/resume-pdf",
        json={
            "resumeId": created["resume"]["id"],
            "fileNameSeed": "historical",
            "savedAt": created["savedAt"],
            "versionId": created["versionId"],
        },
    )

    assert current_response.status_code == 200
    assert historical_response.status_code == 200
    assert document_locales == ["en", "zh"]


def test_export_pdf_rejects_client_document_locale(client: TestClient) -> None:
    response = client.post(
        "/api/exports/resume-pdf",
        json={
            "resumeId": "resumeclientlocale",
            "documentLocale": "en",
            "fileNameSeed": "resume",
            "savedAt": "2026-05-16T00:00:00.000Z",
        },
    )

    assert response.status_code == 422
    assert any(
        error["loc"][-1] == "documentLocale" and error["type"] == "extra_forbidden"
        for error in response.json()["data"]["errors"]
    )


def test_export_images_creates_png_download(client: TestClient, monkeypatch) -> None:
    def write_test_image(
        export_id: str,
        request: ExportResumeImagesRequest,
        **_: object,
    ) -> ResumeImageExportResult:
        from app.services.pdf import get_image_export_path

        export_path = get_image_export_path(export_id, is_archive=False)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_bytes(b"\x89PNG\r\n\x1a\n")
        return ResumeImageExportResult(
            path=export_path,
            page_count=1,
            is_archive=False,
        )

    monkeypatch.setattr(
        "app.routers.exports.write_resume_images",
        write_test_image,
    )
    create_response = client.post(
        "/api/resumes",
        json={
            "documentLocale": "en",
            "title": "Image Resume",
            "resume": minimal_resume_item(title="Image Resume")["resume"],
            "template": "minimal",
        },
    )
    resume_id = create_response.json()["data"]["resume"]["id"]

    response = client.post(
        "/api/exports/resume-images",
        json={
            "resumeId": resume_id,
            "fileNameSeed": "resume-images",
            "savedAt": "2026-05-16T00:00:00.000Z",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["fileName"] == "resume-images.png"
    assert data["pageCount"] == 1
    assert data["isArchive"] is False

    download_response = client.get(data["downloadUrl"])

    assert download_response.status_code == 200
    assert download_response.headers["content-type"] == "image/png"
    assert download_response.content.startswith(b"\x89PNG")


def test_export_images_archives_multiple_pages(
    client: TestClient,
    monkeypatch,
) -> None:
    def write_test_archive(
        export_id: str,
        _request: ExportResumeImagesRequest,
        **_: object,
    ) -> ResumeImageExportResult:
        from app.services.pdf import get_image_export_path

        export_path = get_image_export_path(export_id, is_archive=True)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_bytes(b"PK\x03\x04")
        return ResumeImageExportResult(
            path=export_path,
            page_count=2,
            is_archive=True,
        )

    monkeypatch.setattr(
        "app.routers.exports.write_resume_images",
        write_test_archive,
    )
    create_response = client.post(
        "/api/resumes",
        json={
            "documentLocale": "en",
            "title": "Multi Page Resume",
            "resume": minimal_resume_item(title="Multi Page Resume")["resume"],
            "template": "minimal",
        },
    )
    resume_id = create_response.json()["data"]["resume"]["id"]

    response = client.post(
        "/api/exports/resume-images",
        json={
            "resumeId": resume_id,
            "fileNameSeed": "multi-page",
            "savedAt": "2026-05-16T00:00:00.000Z",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["fileName"] == "multi-page.zip"
    assert data["pageCount"] == 2
    assert data["isArchive"] is True

    download_response = client.get(data["downloadUrl"])

    assert download_response.status_code == 200
    assert download_response.headers["content-type"] == "application/zip"
    assert download_response.content.startswith(b"PK")
