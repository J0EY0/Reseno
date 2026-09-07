from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.services.llm import AgentLlmConfig, LlmPrompt, async_stream_tool_call
from app.services.llm.adapters import anthropic_messages
from app.services.llm.errors import LlmRequestError
from app.services.llm.types import LlmStreamEvent


def _config(*, model: str = "claude-sonnet-4-6") -> AgentLlmConfig:
    return AgentLlmConfig(
        client_id="anthropic-ordered-continuation-test",
        name="Claude Test",
        provider="anthropic",
        provider_kind="cloud",
        model=model,
        base_url="https://api.anthropic.com/v1",
        api_key="sk-test-secret",
        temperature=None,
        top_p=None,
        max_tokens=512,
        timeout_seconds=12,
        api_family="anthropic_messages",
        supports_streaming=False,
    )


def _tool() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "resume_lookup",
            "description": "Lookup resume content",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    }


async def _collect(
    events: AsyncIterator[LlmStreamEvent],
) -> list[LlmStreamEvent]:
    return [event async for event in events]


def test_nonstream_tool_turn_replays_the_exact_ordered_assistant_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_payloads: list[dict[str, Any]] = []
    ordered_content = [
        {
            "type": "thinking",
            "thinking": "Inspect the project first.",
            "signature": "signed-first-thought",
        },
        {"type": "text", "text": "I’ll inspect it."},
        {
            "type": "redacted_thinking",
            "data": "opaque-redacted-thought",
        },
        {
            "type": "tool_use",
            "id": "toolu-project",
            "name": "resume_lookup",
            "input": {"query": "project"},
        },
    ]

    async def fake_post_json(_: str, **kwargs: Any) -> dict[str, Any]:
        captured_payloads.append(kwargs["payload"])
        if len(captured_payloads) == 1:
            return {
                "id": "msg-ordered-tool",
                "stop_reason": "tool_use",
                "content": ordered_content,
            }
        return {
            "id": "msg-after-tool",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Done"}],
        }

    monkeypatch.setattr(anthropic_messages, "async_post_json", fake_post_json)
    config = _config()

    first_events = asyncio.run(
        _collect(
            async_stream_tool_call(
                config,
                LlmPrompt(messages=[{"role": "user", "content": "Inspect it."}]),
                [_tool()],
            )
        ),
    )
    assert first_events[-1].type == "done"
    first = first_events[-1].message
    assert first is not None

    assert first.provider_state == {
        "model": config.model,
        "content_blocks": ordered_content,
    }

    asyncio.run(
        _collect(
            async_stream_tool_call(
                config,
                LlmPrompt(
                    messages=[
                        {"role": "user", "content": "Inspect it."},
                        {
                            "role": "assistant",
                            "content": first.content,
                            "tool_calls": [
                                {
                                    "id": first.tool_calls[0].id,
                                    "type": "function",
                                    "function": {
                                        "name": first.tool_calls[0].name,
                                        "arguments": first.tool_calls[0].raw_arguments,
                                    },
                                },
                            ],
                            "provider_state": first.provider_state,
                        },
                        {
                            "role": "tool",
                            "tool_call_id": first.tool_calls[0].id,
                            "content": '{"matches":["Project A"]}',
                        },
                    ],
                ),
                [_tool()],
            )
        ),
    )

    assert captured_payloads[1]["messages"][1] == {
        "role": "assistant",
        "content": ordered_content,
    }


def test_stream_tool_turn_preserves_and_replays_every_block_in_provider_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_stream_json(
        _: str,
        **__: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        provider_events: list[dict[str, Any]] = [
            {
                "type": "message_start",
                "message": {"id": "msg-stream-ordered"},
            },
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "thinking", "thinking": ""},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "thinking_delta", "thinking": "Inspect first."},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "signature_delta", "signature": "signed-stream"},
            },
            {"type": "content_block_stop", "index": 0},
            {
                "type": "content_block_start",
                "index": 1,
                "content_block": {"type": "text", "text": ""},
            },
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "text_delta", "text": "Checking"},
            },
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "text_delta", "text": " now."},
            },
            {"type": "content_block_stop", "index": 1},
            {
                "type": "content_block_start",
                "index": 2,
                "content_block": {
                    "type": "redacted_thinking",
                    "data": "opaque-stream-thought",
                },
            },
            {"type": "content_block_stop", "index": 2},
            {
                "type": "content_block_start",
                "index": 3,
                "content_block": {
                    "type": "tool_use",
                    "id": "toolu-stream-ordered",
                    "name": "resume_lookup",
                    "input": {},
                },
            },
            {
                "type": "content_block_delta",
                "index": 3,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": '{"query":"experience"}',
                },
            },
            {"type": "content_block_stop", "index": 3},
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use"},
            },
            {"type": "message_stop"},
        ]
        for event in provider_events:
            yield event

    monkeypatch.setattr(anthropic_messages, "async_stream_json", fake_stream_json)
    config = _config()
    events = asyncio.run(
        _collect(
            anthropic_messages.stream_tool_call(
                config,
                [{"role": "user", "content": "Inspect experience."}],
                [_tool()],
            ),
        ),
    )

    terminal = events[-1].message
    assert terminal is not None
    expected_content = [
        {
            "type": "thinking",
            "thinking": "Inspect first.",
            "signature": "signed-stream",
        },
        {"type": "text", "text": "Checking now."},
        {
            "type": "redacted_thinking",
            "data": "opaque-stream-thought",
        },
        {
            "type": "tool_use",
            "id": "toolu-stream-ordered",
            "name": "resume_lookup",
            "input": {"query": "experience"},
        },
    ]
    assert terminal.provider_state == {
        "model": config.model,
        "content_blocks": expected_content,
    }

    _, replayed = anthropic_messages.anthropic_messages(
        [
            {
                "role": "assistant",
                "content": terminal.content,
                "tool_calls": [
                    {
                        "id": terminal.tool_calls[0].id,
                        "type": "function",
                        "function": {
                            "name": terminal.tool_calls[0].name,
                            "arguments": terminal.tool_calls[0].raw_arguments,
                        },
                    },
                ],
                "provider_state": terminal.provider_state,
            },
        ],
        model=config.model,
    )
    assert replayed == [{"role": "assistant", "content": expected_content}]


@pytest.mark.parametrize(
    "provider_state",
    [
        {
            "model": "claude-opus-4-6",
            "content_blocks": [
                {
                    "type": "tool_use",
                    "id": "toolu-foreign",
                    "name": "resume_lookup",
                    "input": {"query": "skills"},
                },
            ],
        },
        {
            "model": "claude-sonnet-4-6",
            "content_blocks": [{"type": "future_unknown_block", "value": "x"}],
        },
        {
            "model": "claude-sonnet-4-6",
            "content_blocks": [
                {
                    "type": "tool_use",
                    "id": "toolu-malformed",
                    "name": "resume_lookup",
                    "input": "not-an-object",
                },
            ],
        },
        {
            "model": "claude-sonnet-4-6",
            "content_blocks": [],
        },
        {
            "model": "claude-sonnet-4-6",
            "content_blocks": [
                {
                    "type": "thinking",
                    "thinking": "Unsigned thought.",
                },
            ],
        },
        {"thinking_blocks": []},
        [],
    ],
)
def test_malformed_or_foreign_continuation_fails_before_provider_request(
    monkeypatch: pytest.MonkeyPatch,
    provider_state: Any,
) -> None:
    called = False

    async def fake_post_json(_: str, **__: Any) -> dict[str, Any]:
        nonlocal called
        called = True
        return {
            "id": "unexpected-response",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "unexpected"}],
        }

    monkeypatch.setattr(anthropic_messages, "async_post_json", fake_post_json)

    with pytest.raises(
        LlmRequestError,
        match="Anthropic continuation state is invalid",
    ):
        asyncio.run(
            _collect(
                async_stream_tool_call(
                    _config(),
                    LlmPrompt(
                        messages=[
                            {"role": "user", "content": "Inspect it."},
                            {
                                "role": "assistant",
                                "content": "Checking.",
                                "tool_calls": [],
                                "provider_state": provider_state,
                            },
                            {"role": "user", "content": "Continue."},
                        ],
                    ),
                    [_tool()],
                )
            ),
        )

    assert called is False


def test_parallel_tool_results_share_one_ordered_anthropic_user_message() -> None:
    model = "claude-sonnet-4-6"
    assistant_content = [
        {
            "type": "thinking",
            "thinking": "Inspect both sections.",
            "signature": "signed-parallel",
        },
        {
            "type": "tool_use",
            "id": "toolu-projects",
            "name": "resume_lookup",
            "input": {"query": "projects"},
        },
        {
            "type": "tool_use",
            "id": "toolu-skills",
            "name": "resume_lookup",
            "input": {"query": "skills"},
        },
    ]
    _, converted = anthropic_messages.anthropic_messages(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [],
                "provider_state": {
                    "model": model,
                    "content_blocks": assistant_content,
                },
            },
            {
                "role": "tool",
                "tool_call_id": "toolu-projects",
                "content": '{"matches":["Project A"]}',
            },
            {
                "role": "tool",
                "tool_call_id": "toolu-skills",
                "content": '{"matches":["TypeScript"]}',
            },
        ],
        model=model,
    )

    assert converted == [
        {"role": "assistant", "content": assistant_content},
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu-projects",
                    "content": '{"matches":["Project A"]}',
                },
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu-skills",
                    "content": '{"matches":["TypeScript"]}',
                },
            ],
        },
    ]


def test_stream_ping_is_activity_while_adaptive_thinking_is_not_displayed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_stream_json(
        _: str,
        **__: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        provider_events: list[dict[str, Any]] = [
            {
                "type": "message_start",
                "message": {"id": "msg-omitted-thinking"},
            },
            {"type": "ping"},
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "Done"},
            },
            {"type": "content_block_stop", "index": 0},
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn"},
            },
            {"type": "message_stop"},
        ]
        for event in provider_events:
            yield event

    monkeypatch.setattr(anthropic_messages, "async_stream_json", fake_stream_json)

    events = asyncio.run(
        _collect(
            anthropic_messages.stream(
                _config(),
                [{"role": "user", "content": "Review it."}],
            ),
        ),
    )

    assert [event.type for event in events] == [
        "activity",
        "activity",
        "text_delta",
        "activity",
        "done",
    ]
