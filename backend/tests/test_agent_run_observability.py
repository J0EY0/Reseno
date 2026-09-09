import asyncio
import json
import logging
from collections.abc import AsyncIterator

import pytest

from app.schemas.agent import (
    AgentChatMessage,
    AgentChatRequest,
    AgentConversationItem,
    AgentToolInvocation,
)
from app.services import agent_runs, agent_sessions
from app.services.agent.runtime import streaming
from app.services.agent.runtime.context import (
    AgentConversationState,
    AgentRuntimeContext,
)
from app.services.agent.runtime.loop import (
    AgentToolLoopCompleted,
    AgentToolLoopTools,
    AgentTurnResult,
)
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
        runtime: AgentRuntimeContext,
    ) -> AsyncIterator[streaming.AgentRuntimeEvent]:
        del request, conn
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
        tool = AgentToolInvocation(
            id="tool-search",
            type="tool-web_search",
            title="web_search",
            state="output-available",
            startedAt="2026-08-23T01:00:00.000Z",
            completedAt="2026-08-23T01:00:01.250Z",
        )
        runtime.record_tool_result(tool)
        runtime.record_tool_loop_event(AgentToolLoopTools(tools=[tool]))
        runtime.record_llm_attempt()
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
        yield streaming.AgentToolUpdate(
            kind="tool_done",
            tool={
                "id": "tool-search",
                "type": "tool-web_search",
                "state": "output-available",
                "input": {"query": PRIVATE_PROMPT},
            },
            timeline_part_id="timeline-tool-1",
        )
        if failed:
            yield streaming.AgentStreamError(
                message=PRIVATE_PROMPT,
                error_code="AGENT_PROVIDER_ERROR",
            )
        else:
            yield streaming.AgentCompleted(
                message=AgentChatMessage.model_validate(
                    {
                        "id": "assistant-observability",
                        "role": "assistant",
                        "text": PRIVATE_PROMPT,
                        "tools": [
                            {
                                "id": "tool-search",
                                "type": "tool-web_search",
                                "title": "web_search",
                                "state": "output-available",
                                "input": {"query": PRIVATE_PROMPT},
                            },
                        ],
                        "transactionState": "committed",
                    },
                ),
                persist=True,
            )

    monkeypatch.setattr(agent_runs, "connect", _FakeConnection)
    monkeypatch.setattr(agent_runs, "async_iter_agent_events", fake_stream)
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
        turn=agent_sessions.AcceptedAgentTurn(
            request=request,
            run_id=f"run-observability-{expected_status}",
            session_id=None,
            turn_id=request.message.id,
            revision=None,
            model_snapshot=None,
            conversation_state=AgentConversationState(),
        ),
        resume_id=request.resume_id,
    )

    asyncio.run(agent_runs.AgentRunManager()._execute(run, None))

    tool_frames = [
        json.loads(line.removeprefix("data: "))
        for event in run.events
        if "event: tool_done\n" in event.frame
        for line in event.frame.splitlines()
        if line.startswith("data: ")
    ]
    assert [frame["tool"]["type"] for frame in tool_frames] == ["tool-web_search"]
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
    model_turns = summary.pop("model_turns")
    assert summary == {
        "cache_write_input_tokens": 10,
        "cached_input_tokens": 60,
        "error_code": "AGENT_PROVIDER_ERROR" if failed else None,
        "event": "agent_run_finished",
        "input_tokens": 150,
        "model_attempts": 4,
        "model_responses": 2,
        "output_tokens": 30,
        "reasoning_tokens": 7,
        "resume_id": "resumeobservability",
        "run_id": f"run-observability-{expected_status}",
        "status": expected_status,
        "tool_calls_by_name": {"web_search": 1},
        "tool_elapsed_ms": 1250,
        "tool_elapsed_ms_by_name": {"web_search": 1250},
        "edit_batch_outcomes": {
            "accepted": 0,
            "deferred": 0,
            "rejected": 0,
        },
        "edit_batches": [],
        "tools": "tool-web_search:output-available",
        "total_tokens": 180,
    }
    assert isinstance(duration_ms, int)
    assert duration_ms >= 0
    assert isinstance(first_event_elapsed_ms, int)
    assert first_event_elapsed_ms >= 0
    assert isinstance(model_elapsed_ms, int)
    assert model_elapsed_ms >= 0
    assert [turn.pop("duration_ms") for turn in model_turns] == [
        pytest.approx(0, abs=100),
        pytest.approx(0, abs=100),
    ]
    assert model_turns == [
        {
            "attempts": 3,
            "cache_write_input_tokens": 10,
            "cached_input_tokens": 40,
            "index": 1,
            "input_tokens": 100,
            "output_tokens": 20,
            "reasoning_tokens": 5,
            "stop_reason": "tool_calls",
            "total_tokens": 120,
        },
        {
            "attempts": 1,
            "cache_write_input_tokens": None,
            "cached_input_tokens": 20,
            "index": 2,
            "input_tokens": 50,
            "output_tokens": 10,
            "reasoning_tokens": 2,
            "stop_reason": "stop",
            "total_tokens": 60,
        },
    ]
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
    event = AgentToolLoopTools(tools=[fetch_one, fetch_two, edit])
    metrics.record_tool_loop_event(event)
    metrics.record_tool_loop_event(event)
    for tool in event.tools:
        metrics.record_tool_result(tool)
        metrics.record_tool_result(tool)

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


def test_completed_loop_event_does_not_start_first_event_latency() -> None:
    metrics = agent_runs._AgentRunMetrics(run_started_monotonic=0.0)
    metrics.record_tool_loop_event(
        AgentToolLoopCompleted(
            result=AgentTurnResult(
                message=None,
                tools=(),
                edits=(),
                transaction_state="none",
                terminal_text="Done.",
            ),
        ),
    )

    assert metrics.first_event_elapsed_ms is None


def test_edit_batch_metrics_keep_only_counts_outcomes_and_machine_codes() -> None:
    metrics = agent_runs._AgentRunMetrics(run_started_monotonic=0.0)
    rejected = AgentToolInvocation(
        id="edit-rejected",
        type="tool-edit_execute",
        title="edit_execute",
        state="output-error",
        input={"edits": [{"replacement": PRIVATE_PROMPT}]},
        output={
            "status": "rejected",
            "editCount": 0,
            "rejectedEditCount": 2,
            "rejectedEdits": [
                {
                    "reason": PRIVATE_PROMPT,
                    "qualityIssue": {
                        "code": "unsupported_edit_claim",
                        "claims": [PRIVATE_PROMPT],
                    },
                },
                {"reason": PRIVATE_PROMPT},
            ],
        },
        errorText=PRIVATE_PROMPT,
        startedAt="2026-08-23T01:00:00.000Z",
        completedAt="2026-08-23T01:00:00.010Z",
    )
    accepted = AgentToolInvocation(
        id="edit-accepted",
        type="tool-edit_execute",
        title="edit_execute",
        state="output-available",
        input={"editCount": 2},
        output={"editCount": 2, "observations": [PRIVATE_PROMPT]},
        startedAt="2026-08-23T01:00:01.000Z",
        completedAt="2026-08-23T01:00:01.010Z",
    )
    deferred = AgentToolInvocation(
        id="edit-deferred",
        type="tool-edit_execute",
        title="edit_execute",
        state="output-available",
        input={"editCount": 1},
        output={"status": "not_executed", "reason": PRIVATE_PROMPT},
        startedAt="2026-08-23T01:00:02.000Z",
        completedAt="2026-08-23T01:00:02.010Z",
    )

    for tool in (rejected, accepted, deferred):
        metrics.record_tool_result(tool)

    assert metrics.edit_batch_outcomes == {
        "accepted": 1,
        "rejected": 1,
        "deferred": 1,
    }
    assert metrics.edit_batch_log_values == [
        {
            "index": 1,
            "outcome": "rejected",
            "edit_count": 2,
            "repair_depth": 1,
            "error_codes": ["unsupported_edit_claim"],
        },
        {
            "index": 2,
            "outcome": "accepted",
            "edit_count": 2,
            "repair_depth": 1,
            "error_codes": [],
        },
        {
            "index": 3,
            "outcome": "deferred",
            "edit_count": 1,
            "repair_depth": 0,
            "error_codes": [],
        },
    ]
    assert PRIVATE_PROMPT not in json.dumps(metrics.edit_batch_log_values)
