import asyncio
import gc
import weakref
from collections.abc import AsyncIterator
from threading import Event

import pytest

from app.schemas.agent import (
    AgentChatMessage,
    AgentChatRequest,
    AgentConversationCheckpoint,
    AgentConversationItem,
    AgentRunStatus,
)
from app.services import agent_runs, agent_sessions
from app.services.agent.runtime import streaming
from app.services.agent.runtime.context import AgentConversationState


def _accepted_turn(
    request: AgentChatRequest, run_id: str
) -> agent_sessions.AcceptedAgentTurn:
    return agent_sessions.AcceptedAgentTurn(
        request=request,
        run_id=run_id,
        session_id=None,
        turn_id=request.message.id,
        revision=None,
        model_snapshot=None,
        conversation_state=AgentConversationState(
            active_checkpoint=AgentConversationCheckpoint(
                throughMessageId="previous-message",
                summary={"context": "Private checkpoint " * 1000},
            )
        ),
    )


def _request() -> AgentChatRequest:
    return AgentChatRequest(
        message=AgentConversationItem(
            id="current-user-message",
            role="user",
            text="Private current prompt " * 1000,
            files=[{"content": "Private attachment " * 1000}],
        ),
        messages=[
            AgentConversationItem(
                id="prior", role="user", text="Private history " * 1000
            )
        ],
        resume={"basic": {"headline": "Saved headline"}, "sections": []},
    )


@pytest.mark.parametrize("status", ["completed", "cancelled", "failed"])
@pytest.mark.parametrize("compact", [False, True])
def test_terminal_release_preserves_response_and_replay_while_freeing_payloads(
    monkeypatch: pytest.MonkeyPatch,
    status: AgentRunStatus,
    compact: bool,
) -> None:
    monkeypatch.setattr(agent_runs, "_finish_agent_run_execution", lambda *_: None)
    if compact:
        monkeypatch.setattr(agent_runs, "MAX_BUFFERED_AGENT_EVENTS", 2)

    async def scenario() -> None:
        request = _request()
        original_request = request.model_dump()
        turn = _accepted_turn(request, "retained-run")
        request_ref = weakref.ref(request)
        current_message_ref = weakref.ref(request.message)
        turn_ref = weakref.ref(turn)
        checkpoint_ref = weakref.ref(turn.conversation_state.active_checkpoint)
        run = agent_runs.AgentRun(id=turn.run_id, turn=turn, resume_id=None)
        manager = agent_runs.AgentRunManager()
        manager._runs[run.id] = run
        await manager._publish(
            run,
            streaming.AgentMessageStarted(
                message={"id": "assistant", "role": "assistant", "text": ""}
            ),
        )
        for delta in ("First paragraph. ", "Second paragraph. ", "Final paragraph."):
            await manager._publish(
                run, streaming.AgentTextDelta(delta=delta, timeline_part_id="text")
            )
        await manager._publish(
            run,
            streaming.AgentToolUpdate(
                kind="tool_done",
                timeline_part_id="tool-group",
                tool={
                    "id": "lookup",
                    "type": "tool-web_search",
                    "title": "Search",
                    "state": "output-available",
                    "output": {"result": "Complete tool output"},
                },
            ),
        )
        if status == "completed":
            run.completion = streaming.AgentCompleted(
                message=AgentChatMessage.model_validate(
                    {**run.replay_message, "transactionState": "committed"}
                ),
                persist=True,
            )
        elif status == "failed":
            run.error_code = "AGENT_PROVIDER_ERROR"
        else:
            run.error_code = "AGENT_RUN_CANCELLED"
        assert run.turn is turn
        assert run.turn.request is request
        await manager._publish_terminal(run, status)
        completion_ref = weakref.ref(run.completion) if run.completion else None
        response = run.response()
        cursors = (0, 1, response.last_event_id)
        frames = {
            cursor: [frame async for frame in manager.subscribe(run.id, after=cursor)]
            for cursor in cursors
        }
        assert frames[0]
        assert "event: run_done" in frames[0][-1]

        await manager._release(run)

        assert request.model_dump() == original_request
        del request, turn
        gc.collect()
        assert request_ref() is None
        assert current_message_ref() is None
        assert turn_ref() is None
        assert checkpoint_ref() is None
        assert completion_ref is None or completion_ref() is None
        assert run.turn is None
        assert run.completion is None
        assert run.replay_message == {}
        assert run.response() == response
        response.base_resume["basic"]["headline"] = "Client mutation"
        assert run.response().base_resume["basic"]["headline"] == "Saved headline"
        for cursor in cursors:
            assert [
                frame async for frame in manager.subscribe(run.id, after=cursor)
            ] == frames[cursor]
        assert await manager.get(run.id) is run

    asyncio.run(scenario())


def test_active_turn_is_retained_until_terminal_persistence_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = Event()
    finish = Event()

    def persist(*_args) -> None:
        entered.set()
        if not finish.wait(timeout=5):
            raise TimeoutError("Terminal persistence was not released")

    async def stream(*_args) -> AsyncIterator[streaming.AgentRuntimeEvent]:
        yield streaming.AgentCompleted(
            message=AgentChatMessage(id="assistant", role="assistant", text="Done"),
            persist=True,
        )

    monkeypatch.setattr(agent_runs, "_finish_agent_run_execution", persist)
    monkeypatch.setattr(agent_runs, "async_iter_agent_events", stream)
    monkeypatch.setattr(
        agent_runs,
        "_prepare_run_request",
        lambda request, run_id: (_accepted_turn(request, run_id), None),
    )

    async def scenario() -> None:
        request = _request()
        manager = agent_runs.AgentRunManager()
        run = await manager.start(request)
        assert run.task is not None
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            assert run.status == "active"
            assert run.turn is not None
            assert run.turn.request is request
            assert run.completion is not None
            assert not any("event: run_done" in event.frame for event in run.events)
        finally:
            finish.set()
            await asyncio.wait_for(run.task, timeout=5)
        assert run.status == "completed"
        assert run.turn is None
        assert run.completion is None
        assert run.replay_message == {}
        assert request.message.files

    asyncio.run(scenario())
