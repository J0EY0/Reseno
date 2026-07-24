import asyncio
from collections.abc import AsyncIterator

import pytest

from app.schemas.agent import AgentChatRequest
from app.services import agent_runs
from app.services.agent.runtime import streaming
from app.services.agent.runtime.context import AgentRuntimeContext
from app.services.agent_runs import AgentRunConflictError, AgentRunManager


class _FakeConnection:
    def close(self) -> None:
        pass


def _request(resume_id: str = "resume-1") -> AgentChatRequest:
    return AgentChatRequest(
        resumeId=resume_id,
        prompt="优化项目经历",
        resume={"basic": {"summary": "原始简介"}, "sections": []},
    )


async def _collect_events(
    manager: AgentRunManager,
    run_id: str,
    *,
    after: int = 0,
) -> list[str]:
    return [frame async for frame in manager.subscribe(run_id, after=after)]


def test_run_survives_subscriber_disconnect_and_replays_from_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        release_stream = asyncio.Event()

        async def fake_stream(
            request: AgentChatRequest,
            conn: _FakeConnection,
            persist_message: object,
            runtime: AgentRuntimeContext,
        ) -> AsyncIterator[str]:
            del request, conn, persist_message, runtime
            yield agent_runs._sse_frame(
                "message_start",
                {"type": "message_start", "message": {"id": "message-1"}},
            )
            await release_stream.wait()
            yield agent_runs._sse_frame(
                "message_done",
                {
                    "type": "message_done",
                    "message": {
                        "id": "message-1",
                        "text": "完成",
                        "transactionState": "committed",
                    },
                },
            )

        monkeypatch.setattr(agent_runs, "connect", _FakeConnection)
        monkeypatch.setattr(agent_runs, "async_stream_agent_response", fake_stream)

        manager = AgentRunManager()
        run = await manager.start(_request())
        first_subscription = manager.subscribe(run.id)
        first_frame = await anext(first_subscription)
        await first_subscription.aclose()

        assert "id: 1" in first_frame
        release_stream.set()
        assert run.task is not None
        await asyncio.wait_for(run.task, timeout=1)

        replayed = await _collect_events(manager, run.id, after=1)
        assert any("event: message_done" in frame for frame in replayed)
        assert "event: run_done" in replayed[-1]
        assert '"status":"completed"' in replayed[-1]

    asyncio.run(scenario())


def test_message_done_is_not_emitted_before_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(
            streaming,
            "resolve_agent_llm_config",
            lambda conn, model_config: None,
        )
        frames: list[str] = []

        def fail_persistence(message: object) -> None:
            del message
            raise OSError("database write failed")

        with pytest.raises(OSError, match="database write failed"):
            async for frame in streaming.async_stream_agent_response(
                _request(),
                _FakeConnection(),
                fail_persistence,
            ):
                frames.append(frame)

        assert any("event: message_delta" in frame for frame in frames)
        assert not any("event: message_done" in frame for frame in frames)

    asyncio.run(scenario())


def test_explicit_stop_rolls_back_provisional_edits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        blocked_stream = asyncio.Event()

        async def fake_stream(
            request: AgentChatRequest,
            conn: _FakeConnection,
            persist_message: object,
            runtime: AgentRuntimeContext,
        ) -> AsyncIterator[str]:
            del request, conn, persist_message, runtime
            yield agent_runs._sse_frame(
                "edits",
                {
                    "type": "edits",
                    "message": {
                        "id": "message-1",
                        "edits": [{"id": "edit-1"}],
                        "transactionState": "provisional",
                    },
                },
            )
            # Simulate a provider blocked while waiting for another chunk. Stop
            # must cancel the task without relying on a cooperative checkpoint.
            await blocked_stream.wait()

        monkeypatch.setattr(agent_runs, "connect", _FakeConnection)
        monkeypatch.setattr(agent_runs, "async_stream_agent_response", fake_stream)

        manager = AgentRunManager()
        run = await manager.start(_request())
        subscription = manager.subscribe(run.id)
        provisional_frame = await anext(subscription)
        await subscription.aclose()
        assert '"transactionState":"provisional"' in provisional_frame

        await manager.stop(run.id)
        assert run.task is not None
        await asyncio.wait_for(run.task, timeout=1)

        events = await _collect_events(manager, run.id)
        rollback_index = next(
            index
            for index, frame in enumerate(events)
            if '"transactionState":"rolled_back"' in frame
        )
        terminal_index = next(
            index for index, frame in enumerate(events) if "event: run_done" in frame
        )
        assert rollback_index < terminal_index
        assert '"status":"cancelled"' in events[terminal_index]
        assert run.status == "cancelled"

    asyncio.run(scenario())


def test_provider_error_rolls_back_provisional_edits(
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
                "edits",
                {
                    "type": "edits",
                    "message": {
                        "id": "message-1",
                        "edits": [{"id": "edit-1"}],
                        "transactionState": "provisional",
                    },
                },
            )
            yield agent_runs._sse_frame(
                "error",
                {"type": "error", "error": "Provider request failed."},
            )
            yield agent_runs._sse_frame(
                "message_done",
                {
                    "type": "message_done",
                    "message": {
                        "id": "message-1",
                        "text": "请求失败",
                        "transactionState": "none",
                    },
                },
            )

        monkeypatch.setattr(agent_runs, "connect", _FakeConnection)
        monkeypatch.setattr(agent_runs, "async_stream_agent_response", fake_stream)

        manager = AgentRunManager()
        run = await manager.start(_request())
        assert run.task is not None
        await asyncio.wait_for(run.task, timeout=1)

        events = await _collect_events(manager, run.id)
        rollback_index = next(
            index
            for index, frame in enumerate(events)
            if '"transactionState":"rolled_back"' in frame
        )
        terminal_index = next(
            index for index, frame in enumerate(events) if "event: run_done" in frame
        )
        assert rollback_index < terminal_index
        assert '"status":"failed"' in events[terminal_index]
        assert run.status == "failed"
        assert not run.has_provisional_edits

    asyncio.run(scenario())


def test_only_one_active_run_is_allowed_per_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        async def fake_stream(
            request: AgentChatRequest,
            conn: _FakeConnection,
            persist_message: object,
            runtime: AgentRuntimeContext,
        ) -> AsyncIterator[str]:
            del request, conn, persist_message
            while not await runtime.is_aborted():
                await asyncio.sleep(0)
            if False:
                yield ""

        monkeypatch.setattr(agent_runs, "connect", _FakeConnection)
        monkeypatch.setattr(agent_runs, "async_stream_agent_response", fake_stream)

        manager = AgentRunManager()
        run = await manager.start(_request())

        with pytest.raises(AgentRunConflictError):
            await manager.start(_request())

        await manager.stop(run.id)
        assert run.task is not None
        await asyncio.wait_for(run.task, timeout=1)

    asyncio.run(scenario())
