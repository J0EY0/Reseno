import asyncio
import json
import logging
from collections.abc import AsyncIterator

import pytest

from app.schemas.agent import (
    AgentChatRequest,
    AgentConversationItem,
    AgentToolInvocation,
)
from app.services import agent_runs
from app.services.agent.runtime.context import AgentRuntimeContext
from app.services.agent.runtime.loop import AgentToolLoopEvent
from app.services.llm import LlmAssistantMessage, LlmUsage

PRIVATE_PROMPT = "private resume and job details"


class _FakeConnection:
    def close(self) -> None:
        pass


@pytest.mark.parametrize(
    ("failed", "expected_status"),
    [(False, "completed"), (True, "failed")],
)
def test_terminal_run_logs_one_privacy_safe_structured_usage_summary(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failed: bool,
    expected_status: str,
) -> None:
    async def fake_stream(
        request: AgentChatRequest,
        conn: object,
        persist_message: object,
        runtime: AgentRuntimeContext,
    ) -> AsyncIterator[str]:
        del request, conn, persist_message
        runtime.record_llm_attempt()
        runtime.record_llm_attempt()
        runtime.record_llm_attempt()
        runtime.record_llm_response(
            LlmAssistantMessage(
                usage=LlmUsage(
                    input_tokens=100,
                    output_tokens=20,
                    total_tokens=120,
                    cached_input_tokens=40,
                    cache_write_input_tokens=10,
                    reasoning_tokens=5,
                ),
                stop_reason="tool_calls",
            ),
        )
        runtime.record_tool_loop_event(
            AgentToolLoopEvent(
                kind="tools",
                tools=[
                    AgentToolInvocation(
                        id="tool-search",
                        type="tool-web_search",
                        title="web_search",
                        state="output-available",
                        startedAt="2026-08-23T01:00:00.000Z",
                        completedAt="2026-08-23T01:00:01.250Z",
                    ),
                ],
            ),
        )
        runtime.record_llm_response(
            LlmAssistantMessage(
                usage=LlmUsage(
                    input_tokens=50,
                    output_tokens=10,
                    total_tokens=60,
                    cached_input_tokens=20,
                    reasoning_tokens=2,
                ),
                stop_reason="stop",
            ),
        )
        yield agent_runs._sse_frame(
            "tool_done",
            {
                "type": "tool_done",
                "tool": {
                    "id": "tool-search",
                    "type": "web_search",
                    "state": "output-available",
                    "input": {"query": PRIVATE_PROMPT},
                },
            },
        )
        if failed:
            yield agent_runs._sse_frame(
                "error",
                {
                    "type": "error",
                    "errorCode": "AGENT_PROVIDER_ERROR",
                    "error": PRIVATE_PROMPT,
                },
            )
        else:
            yield agent_runs._sse_frame(
                "message_done",
                {
                    "type": "message_done",
                    "message": {
                        "id": "assistant-observability",
                        "role": "assistant",
                        "text": PRIVATE_PROMPT,
                        "transactionState": "committed",
                    },
                },
            )

    monkeypatch.setattr(agent_runs, "connect", _FakeConnection)
    monkeypatch.setattr(agent_runs, "async_stream_agent_response", fake_stream)
    monkeypatch.setattr(
        agent_runs,
        "_finish_agent_run_execution",
        lambda *_args, **_kwargs: None,
    )
    caplog.set_level(logging.INFO, logger=agent_runs.logger.name)

    request = AgentChatRequest(
        resumeId="resumeobservability",
        expectedRevision="synthetic-observability-revision",
        message=AgentConversationItem(
            id="turn-observability",
            role="user",
            text=PRIVATE_PROMPT,
        ),
        resume={"basic": {}, "sections": []},
    )
    run = agent_runs.AgentRun(
        id=f"run-observability-{expected_status}",
        request=request,
        resume_id=request.resume_id,
    )

    asyncio.run(agent_runs.AgentRunManager()._execute(run))

    summaries = [
        record.getMessage().removeprefix("Agent run summary ")
        for record in caplog.records
        if record.getMessage().startswith("Agent run summary ")
    ]
    assert len(summaries) == 1
    summary = json.loads(summaries[0])
    duration_ms = summary.pop("duration_ms")
    first_event_elapsed_ms = summary.pop("first_event_elapsed_ms")
    model_elapsed_ms = summary.pop("model_elapsed_ms")
    assert summary == {
        "cache_write_input_tokens": 10,
        "cached_input_tokens": 60,
        "error_code": "AGENT_PROVIDER_ERROR" if failed else None,
        "event": "agent_run_finished",
        "input_tokens": 150,
        "model_attempts": 3,
        "model_responses": 2,
        "output_tokens": 30,
        "reasoning_tokens": 7,
        "resume_id": "resumeobservability",
        "run_id": f"run-observability-{expected_status}",
        "status": expected_status,
        "tool_calls_by_name": {"web_search": 1},
        "tool_elapsed_ms": 1250,
        "tool_elapsed_ms_by_name": {"web_search": 1250},
        "tools": "web_search:output-available",
        "total_tokens": 180,
    }
    assert isinstance(duration_ms, int)
    assert duration_ms >= 0
    assert isinstance(first_event_elapsed_ms, int)
    assert first_event_elapsed_ms >= 0
    assert isinstance(model_elapsed_ms, int)
    assert model_elapsed_ms >= 0
    assert PRIVATE_PROMPT not in caplog.text


def test_run_metrics_merge_parallel_tool_time_and_keep_retry_in_one_model_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = iter((10.0, 15.0, 16.0))
    monkeypatch.setattr(agent_runs, "monotonic", lambda: next(clock))
    metrics = agent_runs._AgentRunMetrics(run_started_monotonic=0.0)

    metrics.record_model_attempt()
    metrics.record_model_attempt()
    metrics.record_model_response(None, "stop")

    fetch_one = AgentToolInvocation(
        id="fetch-1",
        type="tool-web_fetch",
        title="web_fetch",
        state="output-available",
        startedAt="2026-08-23T01:00:00.000Z",
        completedAt="2026-08-23T01:00:02.000Z",
    )
    fetch_two = AgentToolInvocation(
        id="fetch-2",
        type="tool-web_fetch",
        title="web_fetch",
        state="output-available",
        startedAt="2026-08-23T01:00:01.000Z",
        completedAt="2026-08-23T01:00:03.000Z",
    )
    edit = AgentToolInvocation(
        id="edit-1",
        type="tool-edit_execute",
        title="edit_execute",
        state="output-available",
        startedAt="2026-08-23T01:00:04.000Z",
        completedAt="2026-08-23T01:00:04.100Z",
    )
    event = AgentToolLoopEvent(kind="tools", tools=[fetch_one, fetch_two, edit])
    metrics.record_tool_loop_event(event)
    metrics.record_tool_loop_event(event)

    assert metrics.model_attempts == 2
    assert metrics.model_responses == 1
    assert metrics.model_elapsed_ms == 5000
    assert metrics.first_event_elapsed_ms == 16000
    assert metrics.tool_elapsed_ms == 3100
    assert metrics.tool_elapsed_ms_by_name == {
        "edit_execute": 100,
        "web_fetch": 3000,
    }
    assert metrics.tool_calls_by_name == {
        "edit_execute": 1,
        "web_fetch": 2,
    }
