import asyncio
from collections.abc import AsyncIterator
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from app.db.connection import connect
from app.schemas.agent import AgentChatRequest, AgentConversationItem
from app.services import agent_runs, agent_sessions
from app.services.agent.runtime import streaming
from app.services.agent.runtime.context import AgentRuntimeContext
from app.services.agent_runs import AgentRunConflictError, AgentRunManager
from app.services.llm import AgentLlmConfig


class _FakeConnection:
    def close(self) -> None:
        pass


def _bypass_turn_preparation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep stream-only run tests independent from SQLite session acceptance."""

    monkeypatch.setattr(
        agent_runs,
        "prepare_agent_turn",
        lambda conn, request, *, run_id=None: request,
    )


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


def test_subscribe_heartbeat_does_not_advance_replay_cursor(
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
            await release_stream.wait()
            yield agent_runs._sse_frame(
                "message_done",
                {
                    "type": "message_done",
                    "message": {
                        "id": "message-heartbeat",
                        "text": "Done",
                        "transactionState": "committed",
                    },
                },
            )

        monkeypatch.setattr(agent_runs, "connect", _FakeConnection)
        monkeypatch.setattr(agent_runs, "async_stream_agent_response", fake_stream)
        monkeypatch.setattr(agent_runs, "AGENT_SSE_HEARTBEAT_SECONDS", 0.01)
        _bypass_turn_preparation(monkeypatch)

        manager = AgentRunManager()
        run = await manager.start(_request("resume-heartbeat"))
        subscription = manager.subscribe(run.id)

        heartbeat = await asyncio.wait_for(anext(subscription), timeout=0.2)
        assert heartbeat == ": ping\n\n"
        assert run.next_sequence == 1
        assert run.events == []

        release_stream.set()
        first_business_event = await asyncio.wait_for(
            anext(subscription),
            timeout=0.2,
        )
        assert "event: message_done" in first_business_event
        assert "id: 1" in first_business_event

        assert run.task is not None
        await asyncio.wait_for(run.task, timeout=1)
        terminal_event = await asyncio.wait_for(anext(subscription), timeout=0.2)
        assert "event: run_done" in terminal_event
        assert "id: 2" in terminal_event
        await subscription.aclose()

    asyncio.run(scenario())


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
        _bypass_turn_preparation(monkeypatch)

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
            agent_sessions,
            "persist_agent_user_message",
            lambda conn, request: None,
        )
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


def test_user_message_is_persisted_before_cancelled_provider_work(
    client: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del client

    async def scenario() -> None:
        provider_started = asyncio.Event()
        provider_blocked = asyncio.Event()
        request = AgentChatRequest(
            resumeId="resume-cancelled-persistence",
            message=AgentConversationItem(
                id="agent-user-before-cancel",
                role="user",
                text="Inspect this resume.",
            ),
            resume={"basic": {}, "sections": []},
        )
        config = AgentLlmConfig(
            client_id="cancel-test",
            name="Cancel Test",
            provider="openai",
            model="test-model",
            base_url="https://example.test/v1",
            api_key="sk-test",
            temperature=None,
            top_p=None,
            max_tokens=None,
            timeout_seconds=30,
        )

        async def blocked_loop(
            *args: object,
            **kwargs: object,
        ) -> AsyncIterator[object]:
            del args, kwargs
            provider_started.set()
            await provider_blocked.wait()
            if False:
                yield object()

        monkeypatch.setattr(
            streaming,
            "resolve_agent_llm_config",
            lambda conn, model_config: config,
        )
        monkeypatch.setattr(
            streaming,
            "async_iter_agent_tool_call_loop",
            blocked_loop,
        )

        conn = connect()

        async def consume() -> None:
            async for _frame in streaming.async_stream_agent_response(
                request,
                conn,
            ):
                pass

        task = asyncio.create_task(consume())
        await asyncio.wait_for(provider_started.wait(), timeout=1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

        rows = conn.execute(
            """
            SELECT id, role
            FROM agent_messages
            WHERE session_id = ?
            ORDER BY sequence
            """,
            ("resume-cancelled-persistence",),
        ).fetchall()
        conn.close()

        assert [(row["id"], row["role"]) for row in rows] == [
            ("agent-user-before-cancel", "user"),
        ]

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
        _bypass_turn_preparation(monkeypatch)

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
        _bypass_turn_preparation(monkeypatch)

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


def test_successful_execution_state_is_persisted(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        async def fake_stream(
            request: AgentChatRequest,
            conn: object,
            persist_message: object,
            runtime: AgentRuntimeContext,
        ) -> AsyncIterator[str]:
            del request, conn, persist_message, runtime
            yield agent_runs._sse_frame(
                "message_done",
                {
                    "type": "message_done",
                    "message": {
                        "id": "agent-success-message",
                        "text": "Done",
                        "transactionState": "committed",
                    },
                },
            )

        monkeypatch.setattr(agent_runs, "async_stream_agent_response", fake_stream)

        manager = AgentRunManager()
        run = await manager.start(
            AgentChatRequest(
                resumeId="resume-success-state",
                message=AgentConversationItem(
                    id="agent-user-success-state",
                    role="user",
                    text="Improve this resume.",
                ),
                resume={"basic": {}, "sections": []},
            ),
        )
        assert run.task is not None
        await asyncio.wait_for(run.task, timeout=1)

    asyncio.run(scenario())

    response = client.get("/api/agent/resumes/resume-success-state/session")
    assert response.status_code == 200
    execution = response.json()["data"]["executions"][-1]
    assert execution["status"] == "succeeded"
    assert execution["errorCode"] is None
    assert execution["completedAt"] is not None


def test_terminal_persistence_failure_still_finalizes_in_memory_run(
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
                "message_done",
                {
                    "type": "message_done",
                    "message": {
                        "id": "message-terminal-persistence-failure",
                        "text": "Done",
                        "transactionState": "committed",
                    },
                },
            )

        def fail_terminal_persistence(*args: object, **kwargs: object) -> None:
            del args, kwargs
            raise OSError("terminal database commit failed")

        monkeypatch.setattr(agent_runs, "connect", _FakeConnection)
        monkeypatch.setattr(agent_runs, "async_stream_agent_response", fake_stream)
        monkeypatch.setattr(
            agent_runs,
            "finish_agent_turn_execution",
            fail_terminal_persistence,
        )
        _bypass_turn_preparation(monkeypatch)

        manager = AgentRunManager()
        run = await manager.start(_request("resume-terminal-persistence-failure"))
        subscription = asyncio.create_task(_collect_events(manager, run.id))

        assert run.task is not None
        task_results = await asyncio.wait_for(
            asyncio.gather(run.task, return_exceptions=True),
            timeout=1,
        )
        events = await asyncio.wait_for(subscription, timeout=0.2)

        assert task_results == [None]
        assert run.status == "failed"
        assert run.execution_state == "failed"
        assert run.error_code == "AGENT_INTERNAL_ERROR"
        assert await manager.active_for_resume(run.resume_id or "") is None
        assert run.resume_id not in manager._active_by_resume
        assert "event: run_done" in events[-1]
        assert sum("event: run_done" in frame for frame in events) == 1
        assert '"status":"failed"' in events[-1]
        assert '"errorCode":"AGENT_INTERNAL_ERROR"' in events[-1]

    asyncio.run(scenario())


def test_provider_401_execution_state_is_persisted(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        async def fake_stream(
            request: AgentChatRequest,
            conn: object,
            persist_message: object,
            runtime: AgentRuntimeContext,
        ) -> AsyncIterator[str]:
            del request, conn, persist_message, runtime
            yield agent_runs._sse_frame(
                "error",
                {
                    "type": "error",
                    "error": "Model provider returned HTTP 401.",
                },
            )

        monkeypatch.setattr(agent_runs, "async_stream_agent_response", fake_stream)

        manager = AgentRunManager()
        run = await manager.start(
            AgentChatRequest(
                resumeId="resume-provider-401",
                message=AgentConversationItem(
                    id="agent-user-provider-401",
                    role="user",
                    text="Improve this resume.",
                ),
                resume={"basic": {}, "sections": []},
            ),
        )
        assert run.task is not None
        await asyncio.wait_for(run.task, timeout=1)

    asyncio.run(scenario())

    response = client.get("/api/agent/resumes/resume-provider-401/session")
    assert response.status_code == 200
    payload = response.json()["data"]
    assert [message["role"] for message in payload["messages"]] == ["user"]
    assert payload["executions"] == [
        {
            "runId": payload["executions"][0]["runId"],
            "turnId": "agent-user-provider-401",
            "status": "failed",
            "errorCode": "AGENT_PROVIDER_AUTH_ERROR",
            "startedAt": payload["executions"][0]["startedAt"],
            "completedAt": payload["executions"][0]["completedAt"],
        },
    ]


def test_unexpected_run_failure_execution_state_is_persisted(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        async def fake_stream(
            request: AgentChatRequest,
            conn: object,
            persist_message: object,
            runtime: AgentRuntimeContext,
        ) -> AsyncIterator[str]:
            del request, conn, persist_message, runtime
            if False:
                yield ""
            raise RuntimeError("sensitive implementation detail")

        monkeypatch.setattr(agent_runs, "async_stream_agent_response", fake_stream)

        manager = AgentRunManager()
        run = await manager.start(
            AgentChatRequest(
                resumeId="resume-unexpected-failure",
                message=AgentConversationItem(
                    id="agent-user-unexpected-failure",
                    role="user",
                    text="Improve this resume.",
                ),
                resume={"basic": {}, "sections": []},
            ),
        )
        assert run.task is not None
        await asyncio.wait_for(run.task, timeout=1)

    asyncio.run(scenario())

    response = client.get("/api/agent/resumes/resume-unexpected-failure/session")
    assert response.status_code == 200
    execution = response.json()["data"]["executions"][-1]
    assert execution["status"] == "failed"
    assert execution["errorCode"] == "AGENT_INTERNAL_ERROR"
    assert "sensitive" not in str(execution)


def test_cancelled_execution_state_is_persisted(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        provider_started = asyncio.Event()
        provider_blocked = asyncio.Event()

        async def fake_stream(
            request: AgentChatRequest,
            conn: object,
            persist_message: object,
            runtime: AgentRuntimeContext,
        ) -> AsyncIterator[str]:
            del request, conn, persist_message, runtime
            provider_started.set()
            await provider_blocked.wait()
            if False:
                yield ""

        monkeypatch.setattr(agent_runs, "async_stream_agent_response", fake_stream)

        manager = AgentRunManager()
        run = await manager.start(
            AgentChatRequest(
                resumeId="resume-cancelled-state",
                message=AgentConversationItem(
                    id="agent-user-cancelled-state",
                    role="user",
                    text="Improve this resume.",
                ),
                resume={"basic": {}, "sections": []},
            ),
        )
        await asyncio.wait_for(provider_started.wait(), timeout=1)

        running_response = client.get(
            "/api/agent/resumes/resume-cancelled-state/session",
        )
        assert running_response.status_code == 200
        running_execution = running_response.json()["data"]["executions"][-1]
        assert running_execution["status"] == "running"
        assert running_execution["errorCode"] is None
        assert running_execution["completedAt"] is None

        await manager.stop(run.id)
        assert run.task is not None
        await asyncio.wait_for(run.task, timeout=1)

    asyncio.run(scenario())

    response = client.get("/api/agent/resumes/resume-cancelled-state/session")
    assert response.status_code == 200
    execution = response.json()["data"]["executions"][-1]
    assert execution["status"] == "cancelled"
    assert execution["errorCode"] == "AGENT_RUN_CANCELLED"
    assert execution["completedAt"] is not None


def test_interrupted_running_execution_becomes_retryable(
    client: TestClient,
) -> None:
    del client
    request = AgentChatRequest(
        resumeId="resume-interrupted-state",
        message=AgentConversationItem(
            id="agent-user-interrupted-state",
            role="user",
            text="Improve this resume.",
        ),
        resume={"basic": {}, "sections": []},
    )

    with closing(connect()) as conn:
        agent_sessions.prepare_agent_turn(
            conn,
            request,
            run_id="run-interrupted-state",
        )
        assert agent_sessions.fail_interrupted_agent_turn_executions(conn) == 1
        assert agent_sessions.fail_interrupted_agent_turn_executions(conn) == 0

        session = agent_sessions.load_agent_session(
            conn,
            "resume-interrupted-state",
        )

    execution = session.executions[-1]
    assert execution.status == "failed"
    assert execution.error_code == "AGENT_INTERNAL_ERROR"
    assert execution.completed_at is not None


def test_same_millisecond_retry_is_latest_execution(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del client
    monkeypatch.setattr(
        agent_sessions,
        "_now_iso",
        lambda: "2026-07-28T00:00:00.000Z",
    )
    request = AgentChatRequest(
        resumeId="resume-same-millisecond-retry",
        message=AgentConversationItem(
            id="agent-user-same-millisecond-retry",
            role="user",
            text="Improve this resume.",
        ),
        resume={"basic": {}, "sections": []},
    )

    with closing(connect()) as conn:
        failed_request = agent_sessions.prepare_agent_turn(
            conn,
            request,
            run_id="run-z-first",
        )
        agent_sessions.finish_agent_turn_execution(
            conn,
            failed_request,
            run_id="run-z-first",
            status="failed",
            error_code="AGENT_INTERNAL_ERROR",
        )
        agent_sessions.prepare_agent_turn(
            conn,
            request,
            run_id="run-a-retry",
        )
        session = agent_sessions.load_agent_session(
            conn,
            "resume-same-millisecond-retry",
        )

    assert [execution.run_id for execution in session.executions] == [
        "run-z-first",
        "run-a-retry",
    ]
    assert session.executions[-1].status == "running"


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
        _bypass_turn_preparation(monkeypatch)

        manager = AgentRunManager()
        run = await manager.start(_request())

        with pytest.raises(AgentRunConflictError):
            await manager.start(_request())

        await manager.stop(run.id)
        assert run.task is not None
        await asyncio.wait_for(run.task, timeout=1)

    asyncio.run(scenario())
