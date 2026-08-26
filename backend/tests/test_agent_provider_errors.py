import asyncio
from dataclasses import replace

import httpx
import pytest
from openai import APIConnectionError, APIStatusError

from app.schemas.agent import AgentChatRequest, AgentConversationItem
from app.services.agent.runtime import loop as agent_loop
from app.services.agent.runtime import streaming
from app.services.agent.runtime.context import (
    AgentContextWindowError,
    AgentRuntimeContext,
    agent_llm_request_context,
)
from app.services.llm import (
    AgentLlmConfig,
    LlmAssistantMessage,
    LlmRequestContext,
    LlmRequestError,
    LlmStreamEvent,
    LlmTimeoutError,
    LlmToolCall,
    LlmUsage,
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
        streaming,
        "resolve_agent_llm_config",
        lambda conn, model_config: _config(),
    )
    monkeypatch.setattr(streaming, "async_iter_agent_tool_call_loop", failing_loop)

    async def collect() -> str:
        frames: list[str] = []
        async for event in streaming.async_iter_agent_events(
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
            frames.append(streaming.serialize_agent_event(event))
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


def test_redacted_provider_error_preserves_public_status() -> None:
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

    assert captured.value.status_code == 400
    assert "upstream-secret" not in str(captured.value)


def test_provider_timeout_has_a_distinct_public_error_code() -> None:
    error = LlmTimeoutError("Model provider request timed out.")

    assert streaming._llm_error_code(error) == "AGENT_PROVIDER_TIMEOUT"
    assert streaming._llm_error_detail(error) == ("Model provider request timed out.")
    event = streaming.AgentStreamError(
        message="Model provider request timed out.",
        error_code=streaming._llm_error_code(error),
    )
    assert event.error_code == "AGENT_PROVIDER_TIMEOUT"
    assert '"errorCode":"AGENT_PROVIDER_TIMEOUT"' in (
        streaming.serialize_agent_event(event)
    )


def test_local_context_window_error_keeps_actionable_detail() -> None:
    error = AgentContextWindowError(
        "The current resume and request exceed the selected model context window. "
        "Shorten the current input or choose a model with a larger context window.",
    )

    assert streaming._llm_error_code(error) == "AGENT_INTERNAL_ERROR"
    assert streaming._llm_error_detail(error) == str(error)


def test_local_context_window_error_is_not_presented_as_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_loop(*args: object, **kwargs: object):
        del args, kwargs
        raise AgentContextWindowError("local context overflow")
        yield  # pragma: no cover - keeps this an async iterator

    monkeypatch.setattr(
        streaming,
        "resolve_agent_llm_config",
        lambda conn, model_config: _config(),
    )
    monkeypatch.setattr(streaming, "async_iter_agent_tool_call_loop", failing_loop)

    async def collect() -> str:
        frames = [
            streaming.serialize_agent_event(event)
            async for event in streaming.async_iter_agent_events(
                AgentChatRequest(
                    message=AgentConversationItem(
                        id="turn-context-window-error",
                        role="user",
                        text="请修改简历",
                    ),
                    locale="zh",
                    resume={"basic": {}, "sections": []},
                ),
                object(),
            )
        ]
        return "".join(frames)

    frames = asyncio.run(collect())

    assert "上下文窗口" in frames
    assert "缩短本次输入" in frames
    assert "调用模型失败" not in frames
    assert "API Key" not in frames


def test_agent_tool_loop_does_not_apply_a_total_provider_wall_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        provider_calls = 0

        async def stream_model_response(*args: object, **kwargs: object):
            nonlocal provider_calls
            del args, kwargs
            provider_calls += 1
            response = LlmAssistantMessage(content="done", stop_reason="stop")
            yield LlmStreamEvent(type="text_delta", delta=response.content)
            yield LlmStreamEvent(type="done", message=response)

        monkeypatch.setattr(
            agent_loop,
            "_async_iter_model_response",
            stream_model_response,
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
        assert any(
            isinstance(event, agent_loop.AgentToolLoopTextDelta)
            and event.text == "done"
            for event in events
        )

    asyncio.run(scenario())


def test_agent_loop_reports_normalized_usage_to_the_runtime_observer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        response = LlmAssistantMessage(
            content="done",
            usage=LlmUsage(input_tokens=50, output_tokens=10, total_tokens=60),
            stop_reason="stop",
        )

        async def stream_tool_call(*_args: object, **kwargs: object):
            callback = kwargs["on_provider_attempt"]
            assert callable(callback)
            callback()
            yield LlmStreamEvent(type="text_delta", delta=response.content)
            yield LlmStreamEvent(type="done", message=response)

        monkeypatch.setattr(agent_loop, "async_stream_tool_call", stream_tool_call)
        observed: list[tuple[LlmUsage | None, str]] = []
        runtime = AgentRuntimeContext(
            on_llm_response=lambda usage, stop_reason: observed.append(
                (usage, stop_reason),
            ),
        )

        events = [
            event
            async for event in agent_loop.async_iter_agent_tool_call_loop(
                AgentChatRequest(
                    message=AgentConversationItem(
                        id="turn-usage-observer",
                        role="user",
                        text="Hello",
                    ),
                    resume={"basic": {}, "sections": []},
                ),
                replace(_config(), supports_streaming=False),
                runtime,
            )
        ]

        assert isinstance(events[-1], agent_loop.AgentToolLoopCompleted)
        assert observed == [(response.usage, "stop")]

    asyncio.run(scenario())


def test_initial_tool_choice_timeout_propagates_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        attempts = 0
        responses: list[tuple[object, str]] = []

        def record_attempt() -> None:
            nonlocal attempts
            attempts += 1

        async def timeout_tool_response(*_args: object, **kwargs: object):
            nonlocal attempts
            callback = kwargs["on_provider_attempt"]
            assert callable(callback)
            callback()
            raise LlmTimeoutError("Model provider request timed out.")
            yield  # pragma: no cover - keeps this an async iterator

        monkeypatch.setattr(
            agent_loop,
            "async_stream_tool_call",
            timeout_tool_response,
        )
        runtime = AgentRuntimeContext(
            on_llm_attempt=record_attempt,
            on_llm_response=lambda usage, stop_reason: responses.append(
                (usage, stop_reason),
            ),
        )
        request = AgentChatRequest(
            message=AgentConversationItem(
                id="turn-provider-timeout",
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
                runtime,
            ):
                pass

        assert attempts == 1
        assert responses == []

    asyncio.run(scenario())


def test_timeout_after_a_tool_result_propagates_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        attempts = 0

        async def timeout_after_tool(
            *args: object,
            **kwargs: object,
        ):
            nonlocal attempts
            del args, kwargs
            attempts += 1
            if attempts == 1:
                response = LlmAssistantMessage(
                    tool_calls=[
                        LlmToolCall(
                            id="call-unauthorized-fetch",
                            name="web_fetch",
                            arguments={"url": "https://example.test/not-authorized"},
                            raw_arguments='{"url":"https://example.test/not-authorized"}',
                        ),
                    ],
                    stop_reason="tool_calls",
                )
                yield LlmStreamEvent(type="done", message=response)
                return
            raise LlmTimeoutError("Model provider request timed out.")

        monkeypatch.setattr(
            agent_loop,
            "_async_iter_model_response",
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


def test_agent_reuses_opaque_prompt_cache_key_across_model_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        current_resume_id = ""
        turns: dict[str, int] = {}
        contexts: dict[str, list[LlmRequestContext | None]] = {}

        async def tool_loop_response(
            *args: object,
            request_context: LlmRequestContext | None = None,
            **kwargs: object,
        ):
            del args, kwargs
            contexts[current_resume_id].append(request_context)
            turns[current_resume_id] += 1
            if turns[current_resume_id] == 1:
                response = LlmAssistantMessage(
                    tool_calls=[
                        LlmToolCall(
                            id=f"call-{current_resume_id}",
                            name="web_fetch",
                            arguments={"url": "http://127.0.0.1/private"},
                            raw_arguments='{"url":"http://127.0.0.1/private"}',
                        ),
                    ],
                    stop_reason="tool_calls",
                )
                yield LlmStreamEvent(type="done", message=response)
                return
            response = LlmAssistantMessage(
                content="Tool loop done.",
                stop_reason="stop",
            )
            yield LlmStreamEvent(type="text_delta", delta=response.content)
            yield LlmStreamEvent(type="done", message=response)

        monkeypatch.setattr(
            streaming,
            "resolve_agent_llm_config",
            lambda conn, model_config: replace(
                _config(),
                base_url="https://api.openai.com/v1",
                provider_kind="cloud",
                api_family="openai_responses",
            ),
        )
        monkeypatch.setattr(
            agent_loop,
            "async_stream_tool_call",
            tool_loop_response,
        )
        for resume_id in ("resumecachea", "resumecacheb"):
            current_resume_id = resume_id
            turns[resume_id] = 0
            contexts[resume_id] = []
            frames = [
                streaming.serialize_agent_event(event)
                async for event in streaming.async_iter_agent_events(
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
            assert "Tool loop done." in "".join(frames)

        first_keys = [
            context.cache_key
            for context in contexts["resumecachea"]
            if context is not None
        ]
        second_keys = [
            context.cache_key
            for context in contexts["resumecacheb"]
            if context is not None
        ]
        assert len(first_keys) == 2
        assert len(set(first_keys)) == 1
        assert len(first_keys[0]) == 64
        assert "resumecachea" not in first_keys[0]
        assert len(second_keys) == 2
        assert len(set(second_keys)) == 1
        assert first_keys[0] != second_keys[0]
        assert "resumecacheb" not in second_keys[0]

    asyncio.run(scenario())


def test_agent_prompt_cache_context_accepts_only_official_cache_provider() -> None:
    anonymous_request = AgentChatRequest(
        message=AgentConversationItem(
            id="turn-anonymous-cache",
            role="user",
            text="Review this resume.",
        ),
        resume={"basic": {}, "sections": []},
    )
    persisted_request = AgentChatRequest(
        resumeId="resumecacheproviderboundary",
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
            replace(
                _config(),
                base_url="https://api.openai.com/v1",
                provider_kind="cloud",
                api_family="openai_responses",
            ),
        )
        is not None
    )
    assert (
        agent_llm_request_context(
            persisted_request,
            replace(
                _config(),
                provider_kind="cloud",
                api_family="openai_compatible_chat",
            ),
        )
        is None
    )
    assert (
        agent_llm_request_context(
            persisted_request,
            replace(
                _config(),
                provider="xai",
                base_url="https://api.x.ai/v1",
                provider_kind="cloud",
                api_family="openai_responses",
            ),
        )
        is not None
    )
    assert (
        agent_llm_request_context(
            persisted_request,
            replace(
                _config(),
                provider="moonshot",
                base_url="https://api.moonshot.ai/v1",
                provider_kind="custom",
                api_family="openai_compatible_chat",
            ),
        )
        is None
    )
    assert (
        agent_llm_request_context(
            persisted_request,
            replace(
                _config(),
                provider="moonshot",
                base_url="https://api.moonshot.ai/v1",
                provider_kind="cloud",
                api_family="openai_responses",
            ),
        )
        is None
    )
    assert (
        agent_llm_request_context(
            persisted_request,
            replace(
                _config(),
                provider="moonshot",
                base_url="https://api.moonshot.ai/v1",
                provider_kind="cloud",
                api_family="openai_compatible_chat",
            ),
        )
        is not None
    )
    assert (
        agent_llm_request_context(
            persisted_request,
            replace(
                _config(),
                provider="xai",
                base_url="https://api.x.ai/v1",
                provider_kind="custom",
                api_family="openai_responses",
            ),
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
