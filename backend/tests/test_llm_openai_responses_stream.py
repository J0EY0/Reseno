import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

from app.services.llm.adapters import openai_responses
from app.services.llm.errors import LlmRequestError
from app.services.llm.types import (
    AgentLlmConfig,
    LlmPrompt,
    LlmRequestContext,
    LlmStreamEvent,
)


class AsyncStream:
    def __init__(self, events: list[object]) -> None:
        self._events = events
        self.close_count = 0

    def __aiter__(self) -> "AsyncStream":
        return self

    async def __anext__(self) -> object:
        if not self._events:
            raise StopAsyncIteration
        return self._events.pop(0)

    async def close(self) -> None:
        self.close_count += 1


def _config() -> AgentLlmConfig:
    return AgentLlmConfig(
        client_id="responses-stream-test",
        name="Responses stream test",
        provider="openai",
        model="gpt-test",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        temperature=None,
        top_p=None,
        max_tokens=None,
        timeout_seconds=12,
        provider_kind="cloud",
        api_family="openai_responses",
    )


def _tool() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "edit_execute",
            "description": "Apply one edit",
            "parameters": {
                "type": "object",
                "properties": {"section": {"type": "string"}},
                "required": ["section"],
                "additionalProperties": False,
            },
        },
    }


async def _collect(events: AsyncIterator[LlmStreamEvent]) -> list[LlmStreamEvent]:
    return [event async for event in events]


def test_tool_stream_exposes_calls_only_from_completed_response(monkeypatch) -> None:
    provider_stream = AsyncStream(
        [
            SimpleNamespace(
                type="response.output_item.added",
                item={
                    "type": "function_call",
                    "id": "item-1",
                    "call_id": "call-authoritative",
                    "name": "edit_execute",
                    "arguments": "",
                },
            ),
            SimpleNamespace(
                type="response.function_call_arguments.delta",
                item_id="item-1",
                delta='{"section":',
            ),
            SimpleNamespace(
                type="response.function_call_arguments.done",
                item_id="item-1",
                name="edit_execute",
                arguments='{"section":"summary"}',
            ),
            SimpleNamespace(
                type="response.output_item.done",
                item={
                    "type": "function_call",
                    "id": "item-1",
                    "call_id": "call-authoritative",
                    "name": "edit_execute",
                    "arguments": '{"section":"summary"}',
                },
            ),
            SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(
                    id="response-1",
                    output_text="",
                    output=[
                        {
                            "type": "function_call",
                            "id": "item-1",
                            "call_id": "call-authoritative",
                            "name": "edit_execute",
                            "arguments": '{"section":"summary"}',
                        },
                    ],
                    status="completed",
                    incomplete_details=None,
                    usage=None,
                ),
            ),
        ],
    )

    class FakeClient:
        def __init__(self) -> None:
            self.params: dict[str, Any] = {}
            self.responses = SimpleNamespace(create=self.create)

        async def create(self, **params: Any) -> AsyncStream:
            self.params = params
            return provider_stream

        async def close(self) -> None:
            pass

    client = FakeClient()
    monkeypatch.setattr(openai_responses, "async_openai_client", lambda _: client)

    events = asyncio.run(
        _collect(
            openai_responses.stream_tool_call(
                _config(),
                LlmPrompt(messages=[{"role": "user", "content": "Improve my summary"}]),
                [_tool()],
                request_context=LlmRequestContext(cache_key="resume-session-1"),
            ),
        ),
    )

    assert [event.type for event in events] == [
        "activity",
        "activity",
        "activity",
        "activity",
        "done",
    ]
    assert all(event.message is None for event in events[:-1])
    assert events[-1].message is not None
    assert events[-1].message.tool_calls[0].id == "call-authoritative"
    assert events[-1].message.tool_calls[0].arguments == {"section": "summary"}
    assert events[-1].message.stop_reason == "tool_calls"
    assert client.params["stream"] is True
    assert client.params["prompt_cache_key"] == "resume-session-1"
    assert client.params["tools"][0]["name"] == "edit_execute"


def test_native_web_search_is_hosted_and_coexists_with_client_tools() -> None:
    params = openai_responses.responses_params(
        replace(_config(), use_native_web_search=True),
        LlmPrompt(messages=[{"role": "user", "content": "Find current roles"}]),
        tools=[_tool()],
    )

    assert params["tools"] == [
        {"type": "web_search"},
        {
            "type": "function",
            "name": "edit_execute",
            "description": "Apply one edit",
            "parameters": _tool()["function"]["parameters"],
            "strict": False,
        },
    ]
    assert params["include"] == [
        "reasoning.encrypted_content",
        "web_search_call.action.sources",
    ]
    assert params["parallel_tool_calls"] is True


def test_native_web_search_normalizes_activity_sources_citations_and_state(
    monkeypatch,
) -> None:
    cited_text = "Current backend roles"
    text = f"{cited_text} emphasize Python."
    cited_url = "https://jobs.example.com/backend-role"
    consulted_url = "https://engineering.example.com/hiring"
    web_search_call = {
        "type": "web_search_call",
        "id": "search-1",
        "status": "completed",
        "action": {
            "type": "search",
            "query": "current backend engineer jobs",
            "sources": [
                {"type": "url", "url": cited_url},
                {"type": "url", "url": consulted_url},
            ],
        },
    }
    provider_stream = AsyncStream(
        [
            SimpleNamespace(type="response.web_search_call.in_progress"),
            SimpleNamespace(type="response.web_search_call.searching"),
            SimpleNamespace(type="response.web_search_call.completed"),
            SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(
                    id="response-search-1",
                    output_text=text,
                    output=[
                        web_search_call,
                        {
                            "type": "message",
                            "id": "message-search-1",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": text,
                                    "annotations": [
                                        {
                                            "type": "url_citation",
                                            "start_index": 0,
                                            "end_index": len(cited_text),
                                            "url": cited_url,
                                            "title": "Backend Engineer",
                                        },
                                    ],
                                },
                            ],
                            "status": "completed",
                            "role": "assistant",
                        },
                    ],
                    status="completed",
                    incomplete_details=None,
                    usage=None,
                ),
            ),
        ],
    )

    class FakeClient:
        def __init__(self) -> None:
            self.responses = SimpleNamespace(create=self.create)

        async def create(self, **_: Any) -> AsyncStream:
            return provider_stream

        async def close(self) -> None:
            pass

    monkeypatch.setattr(
        openai_responses,
        "async_openai_client",
        lambda _: FakeClient(),
    )

    events = asyncio.run(
        _collect(
            openai_responses.stream_tool_call(
                replace(_config(), use_native_web_search=True),
                LlmPrompt(messages=[{"role": "user", "content": "Find roles"}]),
                [_tool()],
            ),
        ),
    )

    assert [event.type for event in events] == [
        "activity",
        "activity",
        "activity",
        "done",
    ]
    message = events[-1].message
    assert message is not None
    cited_source = openai_responses.make_web_source(
        cited_url,
        title="Backend Engineer",
    )
    assert message.content == f"{cited_text} emphasize Python."
    assert message.sources == [
        cited_source,
        openai_responses.make_web_source(consulted_url),
    ]
    assert message.provider_state == {
        "continuation_items": [web_search_call],
    }
    assert openai_responses.responses_input(
        [
            {
                "role": "assistant",
                "content": message.content,
                "provider_state": message.provider_state,
            },
        ],
    )[1] == [
        web_search_call,
        {"role": "assistant", "content": message.content},
    ]


def test_incomplete_response_never_exposes_partial_tool_calls(monkeypatch) -> None:
    provider_stream = AsyncStream(
        [
            SimpleNamespace(
                type="response.function_call_arguments.done",
                item_id="item-partial",
                name="edit_execute",
                arguments='{"section":"summary"}',
            ),
            SimpleNamespace(
                type="response.incomplete",
                response=SimpleNamespace(
                    id="response-incomplete",
                    output_text="",
                    output=[
                        {
                            "type": "function_call",
                            "id": "item-partial",
                            "call_id": "call-partial",
                            "name": "edit_execute",
                            "arguments": '{"section":"summary"}',
                        },
                    ],
                    status="incomplete",
                    incomplete_details=SimpleNamespace(
                        reason="max_output_tokens",
                    ),
                    usage=None,
                ),
            ),
        ],
    )

    class FakeClient:
        def __init__(self) -> None:
            self.responses = SimpleNamespace(create=self.create)

        async def create(self, **_: Any) -> AsyncStream:
            return provider_stream

        async def close(self) -> None:
            pass

    monkeypatch.setattr(
        openai_responses,
        "async_openai_client",
        lambda _: FakeClient(),
    )

    events = asyncio.run(
        _collect(
            openai_responses.stream_tool_call(
                _config(),
                LlmPrompt(messages=[{"role": "user", "content": "Improve my summary"}]),
                [_tool()],
            ),
        ),
    )

    assert [event.type for event in events] == ["activity", "done"]
    assert events[-1].message is not None
    assert events[-1].message.tool_calls == []
    assert events[-1].message.stop_reason == "length"


def test_completed_response_rejects_item_id_without_call_id(monkeypatch) -> None:
    provider_stream = AsyncStream(
        [
            SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(
                    id="response-without-call-id",
                    output_text="",
                    output=[
                        {
                            "type": "function_call",
                            "id": "item-only",
                            "name": "edit_execute",
                            "arguments": '{"section":"summary"}',
                        },
                    ],
                    status="completed",
                    incomplete_details=None,
                    usage=None,
                ),
            ),
        ],
    )

    class FakeClient:
        def __init__(self) -> None:
            self.responses = SimpleNamespace(create=self.create)

        async def create(self, **_: Any) -> AsyncStream:
            return provider_stream

        async def close(self) -> None:
            pass

    monkeypatch.setattr(
        openai_responses,
        "async_openai_client",
        lambda _: FakeClient(),
    )

    with pytest.raises(LlmRequestError, match="invalid function call batch"):
        asyncio.run(
            _collect(
                openai_responses.stream_tool_call(
                    _config(),
                    LlmPrompt(
                        messages=[{"role": "user", "content": "Improve my summary"}]
                    ),
                    [_tool()],
                ),
            ),
        )


def test_output_item_events_are_activity_without_exposing_provider_items(
    monkeypatch,
) -> None:
    provider_stream = AsyncStream(
        [
            SimpleNamespace(
                type="response.output_item.added",
                item={"type": "message", "id": "message-item"},
            ),
            SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(
                    id="response-message",
                    output_text="No tool needed",
                    output=[],
                    status="completed",
                    incomplete_details=None,
                    usage=None,
                ),
            ),
        ],
    )

    class FakeClient:
        def __init__(self) -> None:
            self.responses = SimpleNamespace(create=self.create)

        async def create(self, **_: Any) -> AsyncStream:
            return provider_stream

        async def close(self) -> None:
            pass

    monkeypatch.setattr(
        openai_responses,
        "async_openai_client",
        lambda _: FakeClient(),
    )

    events = asyncio.run(
        _collect(
            openai_responses.stream_tool_call(
                _config(),
                LlmPrompt(messages=[{"role": "user", "content": "Improve my summary"}]),
                [_tool()],
            ),
        ),
    )

    assert [event.type for event in events] == ["activity", "done"]
    assert events[0].message is None
    assert events[0].delta == ""
    assert events[-1].message is not None
    assert events[-1].message.content == "No tool needed"


def test_tool_stream_rejects_eof_without_authoritative_terminal(monkeypatch) -> None:
    provider_stream = AsyncStream(
        [
            SimpleNamespace(
                type="response.function_call_arguments.done",
                item_id="item-orphaned",
                name="edit_execute",
                arguments='{"section":"summary"}',
            ),
        ],
    )

    class FakeClient:
        def __init__(self) -> None:
            self.close_count = 0
            self.responses = SimpleNamespace(create=self.create)

        async def create(self, **_: Any) -> AsyncStream:
            return provider_stream

        async def close(self) -> None:
            self.close_count += 1

    client = FakeClient()
    monkeypatch.setattr(openai_responses, "async_openai_client", lambda _: client)

    with pytest.raises(LlmRequestError, match="before a terminal response"):
        asyncio.run(
            _collect(
                openai_responses.stream_tool_call(
                    _config(),
                    LlmPrompt(
                        messages=[{"role": "user", "content": "Improve my summary"}]
                    ),
                    [_tool()],
                ),
            ),
        )

    assert provider_stream.close_count == 1
    assert client.close_count == 1


def test_tool_stream_early_close_releases_provider_stream_and_client(
    monkeypatch,
) -> None:
    provider_stream = AsyncStream(
        [
            SimpleNamespace(
                type="response.function_call_arguments.delta",
                item_id="item-1",
                delta="{",
            ),
        ],
    )

    class FakeClient:
        def __init__(self) -> None:
            self.close_count = 0
            self.responses = SimpleNamespace(create=self.create)

        async def create(self, **_: Any) -> AsyncStream:
            return provider_stream

        async def close(self) -> None:
            self.close_count += 1

    client = FakeClient()
    monkeypatch.setattr(openai_responses, "async_openai_client", lambda _: client)

    async def consume_one_event() -> None:
        events = openai_responses.stream_tool_call(
            _config(),
            LlmPrompt(messages=[{"role": "user", "content": "Improve my summary"}]),
            [_tool()],
        )
        event = await anext(events)
        assert event.type == "activity"
        await events.aclose()

    asyncio.run(consume_one_event())

    assert provider_stream.close_count == 1
    assert client.close_count == 1


def test_tool_stream_cancellation_releases_provider_stream_and_client(
    monkeypatch,
) -> None:
    class BlockingStream:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.close_count = 0

        def __aiter__(self) -> "BlockingStream":
            return self

        async def __anext__(self) -> object:
            self.started.set()
            await asyncio.Event().wait()
            raise StopAsyncIteration

        async def close(self) -> None:
            self.close_count += 1

    provider_stream = BlockingStream()

    class FakeClient:
        def __init__(self) -> None:
            self.close_count = 0
            self.responses = SimpleNamespace(create=self.create)

        async def create(self, **_: Any) -> BlockingStream:
            return provider_stream

        async def close(self) -> None:
            self.close_count += 1

    client = FakeClient()
    monkeypatch.setattr(openai_responses, "async_openai_client", lambda _: client)

    async def cancel_consumer() -> None:
        consumer = asyncio.create_task(
            _collect(
                openai_responses.stream_tool_call(
                    _config(),
                    LlmPrompt(
                        messages=[{"role": "user", "content": "Improve my summary"}]
                    ),
                    [_tool()],
                ),
            ),
        )
        await asyncio.wait_for(provider_stream.started.wait(), timeout=1)
        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(consumer, timeout=1)

    asyncio.run(cancel_consumer())

    assert provider_stream.close_count == 1
    assert client.close_count == 1
