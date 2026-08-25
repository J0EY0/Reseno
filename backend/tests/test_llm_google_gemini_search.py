import asyncio
from typing import Any

from app.services.llm.adapters import google_gemini
from app.services.llm.common import make_web_source
from app.services.llm.types import AgentLlmConfig


def _config(**overrides: Any) -> AgentLlmConfig:
    values: dict[str, Any] = {
        "client_id": "gemini-search-test",
        "name": "Gemini Search Test",
        "provider": "google",
        "model": "gemini-3.7-flash",
        "base_url": "https://generativelanguage.googleapis.com/v1",
        "api_key": "test-key",
        "temperature": None,
        "top_p": None,
        "max_tokens": None,
        "timeout_seconds": 12,
        "provider_kind": "cloud",
        "api_family": "google_gemini",
        "use_native_web_search": True,
    }
    values.update(overrides)
    return AgentLlmConfig(**values)


def _edit_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "edit_execute",
            "description": "Edit the resume",
            "parameters": {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
                "required": ["summary"],
            },
        },
    }


def test_gemini_native_web_tools_coexist_with_client_functions() -> None:
    payload = google_gemini.gemini_payload(
        _config(),
        [{"role": "user", "content": "Find a current JD and tailor my resume."}],
        [_edit_tool()],
    )

    assert payload["tools"] == [
        {"type": "google_search"},
        {"type": "url_context"},
        {
            "type": "function",
            "name": "edit_execute",
            "description": "Edit the resume",
            "parameters": {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
                "required": ["summary"],
            },
        },
    ]


def test_gemini_native_search_normalizes_sources_citations_and_replay(
    monkeypatch,
) -> None:
    jd_url = "https://jobs.example.com/frontend#description"
    school_url = "https://school.example.edu/program"
    raw_steps = [
        {
            "type": "google_search_call",
            "id": "search-1",
            "arguments": {"queries": ["2026 frontend internship JD"]},
            "signature": "search-signature",
        },
        {
            "type": "google_search_result",
            "call_id": "search-1",
            "result": [
                {
                    "title": "Frontend Internship",
                    "url": jd_url,
                    "snippet": "Current role requirements for 2026.",
                },
            ],
            "signature": "result-signature",
        },
        {
            "type": "url_context_call",
            "id": "url-1",
            "arguments": {"urls": [school_url]},
            "signature": "url-signature",
        },
        {
            "type": "url_context_result",
            "call_id": "url-1",
            "result": [
                {
                    "title": "Program Requirements",
                    "url": school_url,
                    "snippet": "Official admissions requirements.",
                },
            ],
            "signature": "url-result-signature",
        },
        {
            "type": "model_output",
            "content": [
                {
                    "type": "text",
                    "text": "岗位要求最新React经验",
                    "annotations": [
                        {
                            "type": "url_citation",
                            "url": jd_url,
                            "title": "Frontend Internship",
                            # Gemini citation indices are UTF-8 byte offsets.
                            "start_index": 12,
                            "end_index": 23,
                        },
                    ],
                },
            ],
        },
        {
            "type": "function_call",
            "id": "edit-1",
            "name": "edit_execute",
            "arguments": {"summary": "Tailor to the current React JD"},
        },
    ]

    async def fake_post_json(_: str, **__: Any) -> dict[str, Any]:
        return {
            "id": "interaction-search",
            "status": "requires_action",
            "steps": raw_steps,
        }

    monkeypatch.setattr(google_gemini, "async_post_json", fake_post_json)
    message = asyncio.run(
        google_gemini.complete_tool_call(
            _config(),
            [{"role": "user", "content": "Tailor my resume."}],
            [_edit_tool()],
        ),
    )

    jd_source = make_web_source(
        jd_url,
        "Frontend Internship",
        "Current role requirements for 2026.",
    )
    school_source = make_web_source(
        school_url,
        "Program Requirements",
        "Official admissions requirements.",
    )
    assert message.content == "岗位要求最新React经验"
    assert message.sources == [jd_source, school_source]
    assert message.tool_calls[0].name == "edit_execute"
    assert message.provider_state == {"steps": raw_steps}

    replay = google_gemini.gemini_input(
        [
            {"role": "user", "content": "Tailor my resume."},
            {
                "role": "assistant",
                "content": message.content,
                "tool_calls": [
                    {
                        "id": "edit-1",
                        "type": "function",
                        "function": {
                            "name": "edit_execute",
                            "arguments": '{"summary":"Tailor to the current React JD"}',
                        },
                    },
                ],
                "provider_state": message.provider_state,
            },
            {
                "role": "tool",
                "tool_call_id": "edit-1",
                "content": '{"status":"applied"}',
            },
        ],
    )
    assert replay[1:-1] == raw_steps
    assert replay[-1] == {
        "type": "function_result",
        "name": "edit_execute",
        "call_id": "edit-1",
        "result": [{"type": "text", "text": '{"status":"applied"}'}],
    }


def test_gemini_native_search_streams_activity_and_preserves_sources(
    monkeypatch,
) -> None:
    captured: dict[str, Any] = {}
    jd_url = "https://jobs.example.com/current"

    async def fake_stream_json(url: str, **kwargs: Any) -> Any:
        captured["url"] = url
        captured.update(kwargs)
        for event in [
            {
                "event_type": "interaction.created",
                "interaction": {"id": "stream-search", "status": "in_progress"},
            },
            {
                "event_type": "step.start",
                "index": 0,
                "step": {"type": "google_search_call", "id": "search-1"},
            },
            {
                "event_type": "step.delta",
                "index": 0,
                "delta": {
                    "type": "google_search_call",
                    "arguments": {"queries": ["current frontend JD"]},
                    "signature": "search-signature",
                },
            },
            {"event_type": "step.stop", "index": 0},
            {
                "event_type": "step.start",
                "index": 1,
                "step": {
                    "type": "google_search_result",
                    "call_id": "search-1",
                },
            },
            {
                "event_type": "step.delta",
                "index": 1,
                "delta": {
                    "type": "google_search_result",
                    "result": [
                        {
                            "title": "Current Frontend JD",
                            "url": jd_url,
                            "snippet": "React and TypeScript are required.",
                        },
                    ],
                    "signature": "result-signature",
                },
            },
            {"event_type": "step.stop", "index": 1},
            {
                "event_type": "step.start",
                "index": 2,
                "step": {"type": "model_output", "content": []},
            },
            {
                "event_type": "step.delta",
                "index": 2,
                "delta": {"type": "text", "text": "最新React岗位"},
            },
            {
                "event_type": "step.delta",
                "index": 2,
                "delta": {
                    "type": "text_annotation",
                    "annotations": [
                        {
                            "type": "url_citation",
                            "url": jd_url,
                            "title": "Current Frontend JD",
                            "start_index": 0,
                            "end_index": 11,
                        },
                    ],
                },
            },
            {"event_type": "step.stop", "index": 2},
            {
                "event_type": "interaction.completed",
                "interaction": {"id": "stream-search", "status": "completed"},
            },
        ]:
            yield event

    monkeypatch.setattr(google_gemini, "async_stream_json", fake_stream_json)

    async def collect() -> list[Any]:
        return [
            event
            async for event in google_gemini.stream(
                _config(),
                [{"role": "user", "content": "Find a current frontend JD."}],
            )
        ]

    events = asyncio.run(collect())
    source = make_web_source(
        jd_url,
        "Current Frontend JD",
        "React and TypeScript are required.",
    )

    assert captured["payload"]["tools"] == [
        {"type": "google_search"},
        {"type": "url_context"},
    ]
    assert [event.type for event in events] == [
        "activity",
        "activity",
        "activity",
        "activity",
        "activity",
        "activity",
        "activity",
        "activity",
        "text_delta",
        "activity",
        "activity",
        "done",
    ]
    message = events[-1].message
    assert message is not None
    assert message.content == "最新React岗位"
    assert message.sources == [source]
    assert message.provider_state["steps"][0] == {
        "type": "google_search_call",
        "id": "search-1",
        "arguments": {"queries": ["current frontend JD"]},
        "signature": "search-signature",
    }
    assert message.provider_state["steps"][1] == {
        "type": "google_search_result",
        "call_id": "search-1",
        "result": [
            {
                "title": "Current Frontend JD",
                "url": jd_url,
                "snippet": "React and TypeScript are required.",
            },
        ],
        "signature": "result-signature",
    }
