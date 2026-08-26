import asyncio
import json
from collections.abc import AsyncIterator

import pytest

from app.schemas.agent import AgentChatMessage, AgentChatRequest, AgentConversationItem
from app.services import agent_runs, agent_sessions
from app.services.agent.runtime import streaming
from app.services.agent.runtime.context import (
    AgentConversationState,
    AgentRuntimeContext,
)
from app.services.agent_runs import AgentRunManager


class _FakeConnection:
    def close(self) -> None:
        pass


def _event_payload(frame: str) -> dict[str, object]:
    data = "\n".join(
        line.removeprefix("data:").strip()
        for line in frame.splitlines()
        if line.startswith("data:")
    )
    parsed = json.loads(data)
    assert isinstance(parsed, dict)
    return parsed


def test_long_run_compacts_to_reconnectable_message_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        async def fake_stream(
            request: AgentChatRequest,
            conn: _FakeConnection,
            runtime: AgentRuntimeContext,
        ) -> AsyncIterator[streaming.AgentRuntimeEvent]:
            del request, conn, runtime
            yield streaming.AgentMessageStarted(
                message={
                    "id": "message-1",
                    "role": "assistant",
                    "text": "",
                },
            )
            for delta in ("one", " two", " three", " four", " five"):
                yield streaming.AgentTextDelta(
                    delta=delta,
                    timeline_part_id="timeline-text-1",
                )
            yield streaming.AgentCompleted(
                message=AgentChatMessage.model_validate(
                    {
                        "id": "message-1",
                        "role": "assistant",
                        "text": "one two three four five",
                        "timeline": [
                            {
                                "id": "timeline-text-1",
                                "type": "text",
                                "text": "one two three four five",
                                "toolIds": [],
                            },
                        ],
                        "transactionState": "committed",
                    },
                ),
                persist=True,
            )

        monkeypatch.setattr(agent_runs, "connect", _FakeConnection)
        monkeypatch.setattr(agent_runs, "async_iter_agent_events", fake_stream)
        monkeypatch.setattr(agent_runs, "MAX_BUFFERED_AGENT_EVENTS", 3)
        monkeypatch.setattr(
            agent_runs,
            "_prepare_run_request",
            lambda request, run_id: agent_sessions.AcceptedAgentTurn(
                request=request,
                run_id=run_id,
                session_id=None,
                turn_id=request.message.id,
                revision=None,
                conversation_state=AgentConversationState(),
            ),
        )

        manager = AgentRunManager()
        run = await manager.start(
            AgentChatRequest(
                resumeId="resumereplaybuffer",
                expectedRevision="synthetic-bypassed-revision",
                message=AgentConversationItem(
                    id="turn-run-replay-buffer",
                    role="user",
                    text="Improve this resume.",
                ),
                resume={"basic": {}, "sections": []},
            ),
        )
        assert run.task is not None
        await asyncio.wait_for(run.task, timeout=1)

        frames = [frame async for frame in manager.subscribe(run.id)]
        message_frames = [frame for frame in frames if "event: message_done" in frame]
        assert len(message_frames) == 1
        assert _event_payload(message_frames[0])["message"] == {
            "id": "message-1",
            "role": "assistant",
            "text": "one two three four five",
            "tone": "default",
            "timeline": [
                {
                    "id": "timeline-text-1",
                    "type": "text",
                    "text": "one two three four five",
                    "toolIds": [],
                },
            ],
            "tools": [],
            "sources": [],
            "edits": [],
            "draft": None,
            "transactionState": "committed",
        }
        assert "event: run_done" in frames[-1]
        assert len(run.events) <= 3

    asyncio.run(scenario())
