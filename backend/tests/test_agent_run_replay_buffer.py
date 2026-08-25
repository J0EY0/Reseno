import asyncio
import json
from collections.abc import AsyncIterator

import pytest

from app.schemas.agent import AgentChatRequest, AgentConversationItem
from app.services import agent_runs
from app.services.agent.runtime.context import AgentRuntimeContext
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
            persist_message: object,
            runtime: AgentRuntimeContext,
        ) -> AsyncIterator[str]:
            del request, conn, persist_message, runtime
            yield agent_runs._sse_frame(
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": "message-1",
                        "role": "assistant",
                        "text": "",
                    },
                },
            )
            for delta in ("one", " two", " three", " four", " five"):
                yield agent_runs._sse_frame(
                    "text_delta",
                    {
                        "type": "text_delta",
                        "delta": delta,
                        "timelinePartId": "timeline-text-1",
                    },
                )
            yield agent_runs._sse_frame(
                "message_done",
                {
                    "type": "message_done",
                    "message": {
                        "id": "message-1",
                        "role": "assistant",
                        "text": "one two three four five",
                        "transactionState": "committed",
                    },
                },
            )

        monkeypatch.setattr(agent_runs, "connect", _FakeConnection)
        monkeypatch.setattr(agent_runs, "async_stream_agent_response", fake_stream)
        monkeypatch.setattr(agent_runs, "MAX_BUFFERED_AGENT_EVENTS", 3)
        monkeypatch.setattr(
            agent_runs,
            "_prepare_run_request",
            lambda request, run_id: request,
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
            "timeline": [
                {
                    "id": "timeline-text-1",
                    "type": "text",
                    "text": "one two three four five",
                    "toolIds": [],
                },
            ],
            "transactionState": "committed",
        }
        assert "event: run_done" in frames[-1]
        assert len(run.events) <= 3

    asyncio.run(scenario())
