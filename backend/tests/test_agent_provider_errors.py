import asyncio
from dataclasses import replace

import httpx
import pytest
from openai import APIConnectionError, APIStatusError

from app.schemas.agent import AgentChatRequest, AgentConversationItem
from app.services import agent_runs, agent_sessions
from app.services.agent.runtime import loop as agent_loop
from app.services.agent.runtime import streaming
from app.services.agent.runtime.context import (
    AgentRuntimeContext,
    agent_llm_request_context,
)
from app.services.agent.runtime.messages import is_native_attachment_unsupported
from app.services.llm import (
    AgentLlmConfig,
    LlmAssistantMessage,
    LlmRequestContext,
    LlmRequestError,
    LlmStreamEvent,
    LlmTimeoutError,
    LlmToolCall,
)
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


def test_provider_timeout_has_a_distinct_public_error_code() -> None:
    error = LlmTimeoutError("Model provider request timed out.")

    assert streaming._llm_error_code(error) == "AGENT_PROVIDER_TIMEOUT"
    assert streaming._llm_error_detail(error) == ("Model provider request timed out.")
    assert (
        agent_runs._provider_error_code(
            "event: error\n"
            'data: {"type":"error","errorCode":"AGENT_PROVIDER_TIMEOUT"}\n\n',
        )
        == "AGENT_PROVIDER_TIMEOUT"
    )


def test_agent_tool_loop_does_not_apply_a_total_provider_wall_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        provider_calls = 0

        async def complete_tool_call(*args: object, **kwargs: object):
            nonlocal provider_calls
            del args, kwargs
            provider_calls += 1
            return LlmAssistantMessage(content="done", stop_reason="stop")

        monkeypatch.setattr(
            agent_loop,
            "async_complete_tool_call",
            complete_tool_call,
        )
        request = AgentChatRequest(
            message=AgentConversationItem(
                id="turn-provider-no-wall-clock",
                role="user",
                text="Hello.",
            ),
            locale="en",
            resume={"basic": {}, "sections": []},
        )

        events = [
            event
            async for event in agent_loop.async_iter_agent_tool_call_loop(
                request,
                _config(),
                AgentRuntimeContext(),
            )
        ]

        assert provider_calls == 1
        assert any(event.text == "done" for event in events)

    asyncio.run(scenario())


def test_initial_tool_choice_timeout_is_retried_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        attempts = 0

        async def flaky_tool_response(
            *args: object,
            **kwargs: object,
        ) -> LlmAssistantMessage:
            nonlocal attempts
            del args, kwargs
            attempts += 1
            if attempts == 1:
                raise LlmTimeoutError("Model provider request timed out.")
            return LlmAssistantMessage(
                content="诊断完成。",
                stop_reason="stop",
            )

        monkeypatch.setattr(
            agent_loop,
            "_async_tool_call_response",
            flaky_tool_response,
        )
        request = AgentChatRequest(
            message=AgentConversationItem(
                id="turn-provider-timeout-retry",
                role="user",
                text="诊断这份简历。",
            ),
            locale="zh",
            resume={"basic": {}, "sections": []},
        )

        events = [
            event
            async for event in agent_loop.async_iter_agent_tool_call_loop(
                request,
                _config(),
            )
        ]

        assert attempts == 2
        assert not any(event.text == "诊断完成。" for event in events)
        assert any(
            event.tools and any(tool.title == "resume_analysis" for tool in event.tools)
            for event in events
        )
        done_event = next(event for event in events if event.kind == "done")
        assert done_event.runner is not None
        assert any(tool.title == "resume_analysis" for tool in done_event.runner.tools)

    asyncio.run(scenario())


def test_timeout_after_a_tool_result_is_never_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        attempts = 0

        async def timeout_after_tool(
            *args: object,
            **kwargs: object,
        ) -> LlmAssistantMessage:
            nonlocal attempts
            del args, kwargs
            attempts += 1
            if attempts == 1:
                return LlmAssistantMessage(
                    tool_calls=[
                        LlmToolCall(
                            id="call-resume-analysis",
                            name="resume_analysis",
                            arguments={},
                            raw_arguments="{}",
                        ),
                    ],
                    stop_reason="tool_calls",
                )
            raise LlmTimeoutError("Model provider request timed out.")

        monkeypatch.setattr(
            agent_loop,
            "_async_tool_call_response",
            timeout_after_tool,
        )
        request = AgentChatRequest(
            message=AgentConversationItem(
                id="turn-provider-timeout-after-tool",
                role="user",
                text="诊断这份简历。",
            ),
            locale="zh",
            resume={"basic": {}, "sections": []},
        )

        with pytest.raises(LlmTimeoutError):
            async for _event in agent_loop.async_iter_agent_tool_call_loop(
                request,
                _config(),
            ):
                pass

        assert attempts == 2

    asyncio.run(scenario())


def test_initial_final_response_timeout_is_retried_before_visible_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        attempts = 0

        async def no_tool_events(*args: object, **kwargs: object):
            del args, kwargs
            if False:
                yield object()

        async def flaky_final_stream(*args: object, **kwargs: object):
            nonlocal attempts
            del args, kwargs
            attempts += 1
            if attempts == 1:
                raise LlmTimeoutError("Model provider request timed out.")
            message = LlmAssistantMessage(
                content="Recovered response.",
                stop_reason="stop",
            )
            yield LlmStreamEvent(type="text_delta", delta=message.content)
            yield LlmStreamEvent(type="done", message=message)

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
        monkeypatch.setattr(
            streaming,
            "async_iter_agent_tool_call_loop",
            no_tool_events,
        )
        monkeypatch.setattr(
            streaming,
            "_complete_chat_stream_events",
            flaky_final_stream,
        )
        frames = [
            frame
            async for frame in streaming.async_stream_agent_response(
                AgentChatRequest(
                    message=AgentConversationItem(
                        id="turn-final-timeout-retry",
                        role="user",
                        text="Review this resume.",
                    ),
                    resume={"basic": {}, "sections": []},
                ),
                object(),
            )
        ]

        assert attempts == 2
        assert "Recovered response." in "".join(frames)
        assert "AGENT_PROVIDER_TIMEOUT" not in "".join(frames)

    asyncio.run(scenario())


def test_agent_reuses_opaque_prompt_cache_key_across_retries_and_final_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        current_resume_id = ""
        attempts: dict[str, int] = {}
        contexts: dict[str, list[LlmRequestContext | None]] = {}

        async def flaky_tool_response(
            *args: object,
            request_context: LlmRequestContext | None = None,
            **kwargs: object,
        ) -> LlmAssistantMessage:
            del args, kwargs
            contexts[current_resume_id].append(request_context)
            attempts[current_resume_id] += 1
            if attempts[current_resume_id] == 1:
                raise LlmTimeoutError("Model provider request timed out.")
            return LlmAssistantMessage(content="Tool loop done.", stop_reason="stop")

        async def final_stream(
            *args: object,
            request_context: LlmRequestContext | None = None,
            **kwargs: object,
        ):
            del args, kwargs
            contexts[current_resume_id].append(request_context)
            message = LlmAssistantMessage(content="Final answer.", stop_reason="stop")
            yield LlmStreamEvent(type="text_delta", delta=message.content)
            yield LlmStreamEvent(type="done", message=message)

        monkeypatch.setattr(
            agent_sessions,
            "persist_agent_user_message",
            lambda conn, request: None,
        )
        monkeypatch.setattr(
            streaming,
            "resolve_agent_llm_config",
            lambda conn, model_config: replace(_config(), provider_kind="cloud"),
        )
        monkeypatch.setattr(
            agent_loop,
            "async_complete_tool_call",
            flaky_tool_response,
        )
        monkeypatch.setattr(streaming, "async_stream_chat", final_stream)

        for resume_id in ("resume-cache-a", "resume-cache-b"):
            current_resume_id = resume_id
            attempts[resume_id] = 0
            contexts[resume_id] = []
            frames = [
                frame
                async for frame in streaming.async_stream_agent_response(
                    AgentChatRequest(
                        resumeId=resume_id,
                        expectedRevision="revision-1",
                        message=AgentConversationItem(
                            id=f"turn-{resume_id}",
                            role="user",
                            text="Review this resume.",
                        ),
                        locale="en",
                        resume={"basic": {}, "sections": []},
                    ),
                    object(),
                )
            ]
            assert "Final answer." in "".join(frames)

        first_keys = [
            context.cache_key
            for context in contexts["resume-cache-a"]
            if context is not None
        ]
        second_keys = [
            context.cache_key
            for context in contexts["resume-cache-b"]
            if context is not None
        ]
        assert len(first_keys) == 3
        assert len(set(first_keys)) == 1
        assert len(first_keys[0]) == 64
        assert "resume-cache-a" not in first_keys[0]
        assert len(second_keys) == 3
        assert len(set(second_keys)) == 1
        assert first_keys[0] != second_keys[0]
        assert "resume-cache-b" not in second_keys[0]

    asyncio.run(scenario())


def test_agent_prompt_cache_context_requires_official_openai_resume_session() -> None:
    anonymous_request = AgentChatRequest(
        message=AgentConversationItem(
            id="turn-anonymous-cache",
            role="user",
            text="Review this resume.",
        ),
        resume={"basic": {}, "sections": []},
    )
    persisted_request = AgentChatRequest(
        resumeId="resume-cache-provider-boundary",
        expectedRevision="revision-1",
        message=AgentConversationItem(
            id="turn-provider-cache",
            role="user",
            text="Review this resume.",
        ),
        resume={"basic": {}, "sections": []},
    )

    assert agent_llm_request_context(anonymous_request, _config()) is None
    assert (
        agent_llm_request_context(
            persisted_request,
            replace(_config(), provider_kind="cloud"),
        )
        is not None
    )
    assert (
        agent_llm_request_context(
            persisted_request,
            replace(_config(), provider="xai", api_family="openai_responses"),
        )
        is None
    )
    assert (
        agent_llm_request_context(
            persisted_request,
            replace(_config(), provider="custom-cloud"),
        )
        is None
    )
    assert (
        agent_llm_request_context(
            persisted_request,
            replace(_config(), provider_kind="custom"),
        )
        is None
    )
