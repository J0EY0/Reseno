from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from copy import deepcopy
from typing import Any

import pytest

from app.services.llm.adapters import anthropic_messages
from app.services.llm.common import make_web_source
from app.services.llm.types import AgentLlmConfig, LlmStreamEvent


def _config() -> AgentLlmConfig:
    return AgentLlmConfig(
        client_id="anthropic-native-web-test",
        name="Claude Test",
        provider="anthropic",
        provider_kind="cloud",
        model="claude-sonnet-4-6",
        base_url="https://api.anthropic.com/v1",
        api_key="sk-test-secret",
        temperature=None,
        top_p=None,
        max_tokens=2_048,
        timeout_seconds=12,
        api_family="anthropic_messages",
        use_native_web_search=True,
    )


def _edit_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "edit_execute",
            "description": "Apply one resume edit",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
                "additionalProperties": False,
            },
        },
    }


async def _collect(
    events: AsyncIterator[LlmStreamEvent],
) -> list[LlmStreamEvent]:
    return [event async for event in events]


def test_native_web_tools_coexist_with_client_edit_tool() -> None:
    payload = anthropic_messages._payload(
        _config(),
        [{"role": "user", "content": "Find the latest role and tailor my CV."}],
        [_edit_tool()],
    )

    assert [tool["name"] for tool in payload["tools"]] == [
        "edit_execute",
        "web_search",
        "web_fetch",
    ]
    assert payload["tools"][1] == {
        "type": "web_search_20250305",
        "name": "web_search",
        "allowed_callers": ["direct"],
    }
    assert payload["tools"][2]["type"] == "web_fetch_20250910"
    assert payload["tools"][2]["citations"] == {"enabled": True}


def test_native_fetch_maps_document_citation_back_to_fetched_url() -> None:
    message = anthropic_messages._message_from_payload(
        {
            "id": "msg-fetch",
            "stop_reason": "end_turn",
            "content": [
                {
                    "type": "web_fetch_tool_result",
                    "tool_use_id": "srvtoolu-fetch",
                    "content": {
                        "type": "web_fetch_result",
                        "url": "https://jobs.example.com/backend",
                        "content": {
                            "type": "document",
                            "title": "Backend Engineer",
                            "source": {
                                "type": "text",
                                "media_type": "text/plain",
                                "data": "Build reliable Python services.",
                            },
                        },
                    },
                },
                {
                    "type": "text",
                    "text": "The role requires reliable Python services.",
                    "citations": [
                        {
                            "type": "char_location",
                            "document_index": 0,
                            "document_title": "Backend Engineer",
                            "start_char_index": 0,
                            "end_char_index": 31,
                            "cited_text": "Build reliable Python services.",
                        },
                    ],
                },
            ],
        },
        model=_config().model,
    )

    source = make_web_source(
        "https://jobs.example.com/backend",
        "Backend Engineer",
        "Build reliable Python services.",
    )
    assert message.sources == [source]
    assert message.content == "The role requires reliable Python services."


def test_mixed_server_and_client_calls_expose_only_client_edit() -> None:
    content = [
        {
            "type": "server_tool_use",
            "id": "srvtoolu-fetch",
            "name": "web_fetch",
            "input": {"url": "https://jobs.example.com/frontend"},
        },
        {
            "type": "tool_use",
            "id": "toolu-edit",
            "name": "edit_execute",
            "input": {"text": "Delivered React features with TypeScript."},
        },
    ]

    message = anthropic_messages._message_from_payload(
        {
            "id": "msg-mixed-tools",
            "stop_reason": "tool_use",
            "content": content,
        },
        model=_config().model,
    )

    assert [(call.id, call.name) for call in message.tool_calls] == [
        ("toolu-edit", "edit_execute"),
    ]
    assert message.provider_state["content_blocks"] == content


def test_nonstream_native_search_continues_pause_and_preserves_citations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_payloads: list[dict[str, Any]] = []
    paused_blocks = [
        {
            "type": "server_tool_use",
            "id": "srvtoolu-search",
            "name": "web_search",
            "input": {"query": "latest frontend engineer job description"},
        },
        {
            "type": "web_search_tool_result",
            "tool_use_id": "srvtoolu-search",
            "content": [
                {
                    "type": "web_search_result",
                    "url": "https://jobs.example.com/frontend",
                    "title": "Frontend Engineer",
                    "encrypted_content": "encrypted-search-result",
                },
            ],
        },
    ]

    async def fake_post_json(_: str, **kwargs: Any) -> dict[str, Any]:
        captured_payloads.append(deepcopy(kwargs["payload"]))
        if len(captured_payloads) == 1:
            return {
                "id": "msg-paused",
                "stop_reason": "pause_turn",
                "content": paused_blocks,
                "usage": {"input_tokens": 5, "output_tokens": 3},
            }
        return {
            "id": "msg-complete",
            "stop_reason": "end_turn",
            "content": [
                {
                    "type": "text",
                    "text": "The role emphasizes React and TypeScript.",
                    "citations": [
                        {
                            "type": "web_search_result_location",
                            "url": "https://jobs.example.com/frontend",
                            "title": "Frontend Engineer",
                            "cited_text": "Build production React applications.",
                            "encrypted_index": "encrypted-citation-index",
                        },
                    ],
                },
            ],
            "usage": {"input_tokens": 7, "output_tokens": 4},
        }

    monkeypatch.setattr(anthropic_messages, "async_post_json", fake_post_json)

    message = asyncio.run(
        anthropic_messages.complete_tool_call(
            _config(),
            [{"role": "user", "content": "Tailor my CV to the latest role."}],
            [_edit_tool()],
        ),
    )

    assert captured_payloads[1]["messages"][-1] == {
        "role": "assistant",
        "content": paused_blocks,
    }
    source = make_web_source(
        "https://jobs.example.com/frontend",
        "Frontend Engineer",
        "Build production React applications.",
    )
    assert message.content == "The role emphasizes React and TypeScript."
    assert message.sources == [source]
    assert message.provider_state["content_blocks"] == [
        *paused_blocks,
        {
            "type": "text",
            "text": "The role emphasizes React and TypeScript.",
            "citations": [
                {
                    "type": "web_search_result_location",
                    "url": "https://jobs.example.com/frontend",
                    "title": "Frontend Engineer",
                    "cited_text": "Build production React applications.",
                    "encrypted_index": "encrypted-citation-index",
                },
            ],
        },
    ]
    assert message.usage is not None
    assert message.usage.total_tokens == 19


def test_stream_native_search_emits_activity_and_continues_pause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_payloads: list[dict[str, Any]] = []

    async def fake_stream_json(
        _: str,
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        captured_payloads.append(deepcopy(kwargs["payload"]))
        if len(captured_payloads) == 1:
            events = [
                {
                    "type": "message_start",
                    "message": {"id": "msg-stream-paused"},
                },
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {
                        "type": "server_tool_use",
                        "id": "srvtoolu-stream-search",
                        "name": "web_search",
                    },
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": '{"query":"new graduate frontend jobs"}',
                    },
                },
                {"type": "content_block_stop", "index": 0},
                {
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": {
                        "type": "web_search_tool_result",
                        "tool_use_id": "srvtoolu-stream-search",
                        "content": [
                            {
                                "type": "web_search_result",
                                "url": "https://careers.example.com/new-grad",
                                "title": "New Grad Frontend Engineer",
                                "encrypted_content": "encrypted-stream-result",
                            },
                        ],
                    },
                },
                {"type": "content_block_stop", "index": 1},
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "pause_turn"},
                },
                {"type": "message_stop"},
            ]
        else:
            events = [
                {
                    "type": "message_start",
                    "message": {"id": "msg-stream-complete"},
                },
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {
                        "type": "text_delta",
                        "text": "Prioritize React delivery experience.",
                    },
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {
                        "type": "citations_delta",
                        "citation": {
                            "type": "web_search_result_location",
                            "url": "https://careers.example.com/new-grad",
                            "title": "New Grad Frontend Engineer",
                            "cited_text": "Ship React features with TypeScript.",
                            "encrypted_index": "encrypted-stream-index",
                        },
                    },
                },
                {"type": "content_block_stop", "index": 0},
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn"},
                },
                {"type": "message_stop"},
            ]
        for event in events:
            yield event

    monkeypatch.setattr(anthropic_messages, "async_stream_json", fake_stream_json)

    events = asyncio.run(
        _collect(
            anthropic_messages.stream_tool_call(
                _config(),
                [{"role": "user", "content": "Find a current target role."}],
                [_edit_tool()],
            ),
        ),
    )

    assert len(captured_payloads) == 2
    assert captured_payloads[1]["messages"][-1]["role"] == "assistant"
    assert any(event.type == "activity" for event in events[:-1])
    assert any(
        event.type == "text_delta"
        and event.delta == "Prioritize React delivery experience."
        for event in events[:-1]
    )
    terminal = events[-1].message
    assert terminal is not None
    source = make_web_source(
        "https://careers.example.com/new-grad",
        "New Grad Frontend Engineer",
        "Ship React features with TypeScript.",
    )
    assert terminal.sources == [source]
    assert terminal.content == "Prioritize React delivery experience."
    assert [block["type"] for block in terminal.provider_state["content_blocks"]] == [
        "server_tool_use",
        "web_search_tool_result",
        "text",
    ]
