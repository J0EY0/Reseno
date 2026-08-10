import asyncio
import threading

import pytest

from app.schemas.agent import (
    AgentChatRequest,
    AgentConversationItem,
    AgentResumeEditSuggestion,
    AgentToolInvocation,
)
from app.services.agent.executor import AgentPlanExecutor
from app.services.agent.runtime.context import AgentRuntimeContext
from app.services.agent.tools.runner import AgentToolRunner
from app.services.llm import LlmRequestError, LlmToolCall


def _runner() -> AgentToolRunner:
    request = AgentChatRequest(
        message=AgentConversationItem(
            id="turn-local-tool-cancellation",
            role="user",
            text="Analyze this resume.",
        ),
        locale="en",
        resume={"basic": {"name": "Original"}, "sections": []},
    )
    return AgentToolRunner(AgentPlanExecutor(request))


def _analysis_call() -> LlmToolCall:
    return LlmToolCall(
        id="call-resume-analysis",
        name="resume_analysis",
        arguments={},
        raw_arguments="{}",
    )


def test_cancelled_local_tool_thread_cannot_mutate_live_runner(monkeypatch) -> None:
    runner = _runner()
    worker_started = threading.Event()
    release_worker = threading.Event()
    worker_finished = threading.Event()

    def blocked_analysis(
        worker_runner: AgentToolRunner,
        tool_call: LlmToolCall,
    ) -> AgentToolInvocation:
        tool = AgentToolInvocation(
            id=tool_call.id,
            type="tool-resume_analysis",
            title="resume_analysis",
            state="output-available",
            input={},
            output={"status": "late"},
        )
        worker_runner.draft_resume["basic"]["name"] = "Thread mutation"
        worker_runner.edits.append(
            AgentResumeEditSuggestion(
                id="late-edit",
                title="Late edit",
                target="basic.name",
                reason="Cancellation regression marker.",
            ),
        )
        worker_runner.tools.append(tool)
        worker_runner.finished = True
        worker_runner.finish_reason = "late finish"
        worker_runner.transaction_failed = True
        worker_runner.transaction_committed = True
        worker_runner.executor.prompt = "Thread-only prompt"
        worker_started.set()
        try:
            release_worker.wait(timeout=2)
            worker_runner.draft_resume["basic"]["name"] = "Post-cancel mutation"
            return tool
        finally:
            worker_finished.set()

    monkeypatch.setattr(AgentToolRunner, "run_resume_analysis", blocked_analysis)

    async def cancel_at_barrier() -> None:
        task = asyncio.create_task(
            runner.run(_analysis_call(), AgentRuntimeContext()),
        )
        assert await asyncio.to_thread(worker_started.wait, 1)
        task.cancel()
        try:
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            release_worker.set()
            assert await asyncio.to_thread(worker_finished.wait, 1)

    asyncio.run(cancel_at_barrier())

    assert runner.draft_resume["basic"]["name"] == "Original"
    assert runner.edits == []
    assert runner.tools == []
    assert runner.finished is False
    assert runner.finish_reason == ""
    assert runner.transaction_failed is False
    assert runner.transaction_committed is False
    assert runner.executor.prompt == "Analyze this resume."


def test_timed_out_local_tool_thread_cannot_mutate_live_runner(monkeypatch) -> None:
    runner = _runner()
    worker_started = threading.Event()
    release_worker = threading.Event()
    worker_finished = threading.Event()

    def blocked_analysis(
        worker_runner: AgentToolRunner,
        tool_call: LlmToolCall,
    ) -> AgentToolInvocation:
        worker_started.set()
        try:
            release_worker.wait(timeout=2)
            worker_runner.draft_resume["basic"]["name"] = "Late timeout mutation"
            worker_runner.finished = True
            return AgentToolInvocation(
                id=tool_call.id,
                type="tool-resume_analysis",
                title="resume_analysis",
                state="output-available",
                input={},
                output={"status": "late"},
            )
        finally:
            worker_finished.set()

    monkeypatch.setattr(AgentToolRunner, "run_resume_analysis", blocked_analysis)

    async def time_out_at_barrier() -> None:
        task = asyncio.create_task(
            runner.run(
                _analysis_call(),
                AgentRuntimeContext(blocking_timeout_seconds=0.02),
            ),
        )
        assert await asyncio.to_thread(worker_started.wait, 1)
        try:
            with pytest.raises(LlmRequestError, match="timed out"):
                await task
        finally:
            release_worker.set()
            assert await asyncio.to_thread(worker_finished.wait, 1)

    asyncio.run(time_out_at_barrier())

    assert runner.draft_resume["basic"]["name"] == "Original"
    assert runner.finished is False
    assert runner.tools == []
