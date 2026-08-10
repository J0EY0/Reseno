import asyncio

import httpx
import pytest
from openai import APIConnectionError, APIStatusError

from app.schemas.agent import AgentChatRequest, AgentConversationItem
from app.services import agent_sessions
from app.services.agent.runtime import streaming
from app.services.agent.runtime.messages import is_native_attachment_unsupported
from app.services.llm import AgentLlmConfig, LlmRequestError
from app.services.llm import common as llm_common
from app.services.llm.common import http_error_message, raise_openai_error


def _config() -> AgentLlmConfig:
    return AgentLlmConfig(
        client_id="provider-error-test",
        name="Provider Error Test",
        provider="openai",
        model="test-model",
        base_url="https://provider.test/v1",
        api_key="secret-key",
        temperature=None,
        top_p=None,
        max_tokens=None,
        timeout_seconds=30,
    )


def test_provider_response_body_never_enters_agent_sse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_body = "upstream trace: Bearer provider-secret customer@example.com"

    async def failing_loop(*args: object, **kwargs: object):
        del args, kwargs
        raise LlmRequestError(raw_body, status_code=429)
        yield  # pragma: no cover - keeps this an async iterator

    monkeypatch.setattr(
        agent_sessions,
        "persist_agent_user_message",
        lambda conn, request: None,
    )
    monkeypatch.setattr(
        streaming,
        "resolve_agent_llm_config",
        lambda conn, model_config: _config(),
    )
    monkeypatch.setattr(streaming, "async_iter_agent_tool_call_loop", failing_loop)

    async def collect() -> str:
        frames: list[str] = []
        async for frame in streaming.async_stream_agent_response(
            AgentChatRequest(
                message=AgentConversationItem(
                    id="turn-provider-error-sse",
                    role="user",
                    text="Improve my resume",
                ),
                resume={"basic": {}, "sections": []},
            ),
            object(),
        ):
            frames.append(frame)
        return "".join(frames)

    frames = asyncio.run(collect())

    assert raw_body not in frames
    assert "provider-secret" not in frames
    assert "customer@example.com" not in frames
    assert "Model provider returned HTTP 429." in frames


def test_http_provider_error_discards_response_body() -> None:
    request = httpx.Request("POST", "https://provider.test/messages")
    response = httpx.Response(
        500,
        request=request,
        text='{"error":"Bearer upstream-secret"}',
    )
    error = httpx.HTTPStatusError(
        "provider failed",
        request=request,
        response=response,
    )

    message = http_error_message(error)

    assert message == "Model provider returned HTTP 500."
    assert "upstream-secret" not in message


def test_openai_sdk_error_discards_response_body() -> None:
    request = httpx.Request("POST", "https://provider.test/responses")
    response = httpx.Response(
        401,
        request=request,
        text='{"error":"api_key=sk-upstream-secret"}',
    )
    error = APIStatusError(
        "provider failed",
        response=response,
        body={"error": "api_key=sk-upstream-secret"},
    )

    with pytest.raises(LlmRequestError) as captured:
        raise_openai_error(error)

    assert str(captured.value) == "Model provider returned HTTP 401."
    assert captured.value.status_code == 401
    assert "sk-upstream-secret" not in str(captured.value)


def test_provider_connection_error_discards_sdk_detail() -> None:
    request = httpx.Request("POST", "https://provider.test/responses")
    error = APIConnectionError(
        message="connection failed with Bearer upstream-secret",
        request=request,
    )

    with pytest.raises(LlmRequestError) as captured:
        raise_openai_error(error)

    assert str(captured.value) == "Model provider request failed."
    assert "upstream-secret" not in str(captured.value)


def test_request_scoped_client_close_supports_sync_and_async_sdks() -> None:
    closed: list[str] = []

    class SyncClient:
        def close(self) -> None:
            closed.append("sync")

    class AsyncClient:
        async def close(self) -> None:
            closed.append("async")

    async def close_clients() -> None:
        await llm_common.close_async_client(SyncClient())
        await llm_common.close_async_client(AsyncClient())

    asyncio.run(close_clients())

    assert closed == ["sync", "async"]


def test_redacted_provider_error_preserves_attachment_fallback_signal() -> None:
    request = httpx.Request("POST", "https://provider.test/responses")
    response = httpx.Response(
        400,
        request=request,
        text=(
            "input_file application/pdf is unsupported; trace Bearer upstream-secret"
        ),
    )
    error = APIStatusError("provider failed", response=response, body={})

    with pytest.raises(LlmRequestError) as captured:
        raise_openai_error(error)

    assert is_native_attachment_unsupported(captured.value) is True
    assert "upstream-secret" not in str(captured.value)
