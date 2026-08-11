import asyncio
import json
import threading
from collections.abc import AsyncIterator
from contextlib import closing
from datetime import UTC, datetime
from time import perf_counter
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.db.connection import connect
from app.routers import agent as agent_router
from app.routers import resumes as resumes_router
from app.schemas.agent import (
    AgentChatMessage,
    AgentChatRequest,
    AgentConversationItem,
    AgentDraftState,
)
from app.services import agent_runs, agent_sessions, resumes
from app.services.agent.runtime import streaming
from app.services.agent.runtime.context import AgentRuntimeContext
from app.services.agent_runs import AgentRunConflictError, AgentRunManager
from app.services.llm import AgentLlmConfig, LlmTimeoutError


class _FakeConnection:
    def close(self) -> None:
        pass


def _bypass_turn_preparation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep stream-only run tests independent from SQLite session acceptance."""

    monkeypatch.setattr(
        agent_runs,
        "_prepare_run_request",
        lambda request, run_id: request,
    )


def _request(resume_id: str = "resume-1") -> AgentChatRequest:
    return AgentChatRequest(
        resumeId=resume_id,
        expectedRevision="synthetic-bypassed-revision",
        message=AgentConversationItem(
            id=f"turn-agent-run-{resume_id}",
            role="user",
            text="优化项目经历",
        ),
        resume={"basic": {"summary": "原始简介"}, "sections": []},
    )


def _current_session_revision(resume_id: str) -> str:
    """Read the optimistic revision used by real run-acceptance tests."""

    with closing(connect()) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO resumes (id, title, saved_at)
            VALUES (?, 'Agent run test resume', ?)
            """,
            (resume_id, datetime.now(UTC).isoformat()),
        )
        return agent_sessions.load_agent_session(conn, resume_id).revision


async def _collect_events(
    manager: AgentRunManager,
    run_id: str,
    *,
    after: int = 0,
) -> list[str]:
    return [frame async for frame in manager.subscribe(run_id, after=after)]


def test_run_response_preserves_the_pending_transaction_base() -> None:
    request_resume = {
        "basic": {"headline": "Engineer"},
        "sections": [],
    }
    pending_draft_resume = {
        "basic": {"headline": "Staff Engineer"},
        "sections": [],
    }
    request = _request("resume-run-pending-draft-base").model_copy(
        update={
            "resume": request_resume,
            "draft_state": AgentDraftState(
                id="draft-run-pending-base",
                status="pending",
                sourceMessageId="assistant-pending-draft-base",
                resume=pending_draft_resume,
            ),
            "messages": [
                AgentConversationItem(
                    id="assistant-pending-draft-base",
                    role="assistant",
                    text="The first draft is ready.",
                    response={
                        "draft": {
                            "baseResume": request_resume,
                            "status": "pending",
                        },
                    },
                ),
            ],
        },
    )
    run = agent_runs.AgentRun(
        id="run-pending-draft-base",
        request=request,
        resume_id=request.resume_id,
    )

    assert run.response().base_resume == request_resume


def test_follow_up_stream_keeps_prior_edits_in_every_draft_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        prior_edit = {
            "id": "edit-prior-summary",
            "title": "Update summary",
            "target": "basic.summary",
            "reason": "Keep the first draft edit.",
            "operation": {
                "type": "replace_field",
                "path": "basic.summary",
                "value": "Focused summary",
            },
            "status": "executed",
        }
        next_edit = {
            "id": "edit-next-headline",
            "title": "Refine headline",
            "target": "basic.headline",
            "reason": "Apply the follow-up request.",
            "operation": {
                "type": "replace_field",
                "path": "basic.headline",
                "value": "Principal Engineer",
            },
            "status": "executed",
        }
        stale_client_edit = {
            **prior_edit,
            "id": "edit-stale-client-copy",
            "operation": {
                **prior_edit["operation"],
                "value": "Stale client summary",
            },
        }
        request = _request("resume-follow-up-stream").model_copy(
            update={
                "messages": [
                    AgentConversationItem(
                        id="assistant-prior-stream-draft",
                        role="assistant",
                        text="The first draft is ready.",
                        response={
                            "draft": {
                                "baseResume": {
                                    "basic": {
                                        "headline": "Engineer",
                                        "summary": "Original summary",
                                    },
                                    "sections": [],
                                },
                                "status": "pending",
                            },
                            "edits": [prior_edit],
                            "transactionState": "committed",
                        },
                    ),
                ],
                "draft_state": AgentDraftState(
                    id="draft-prior-stream",
                    status="pending",
                    sourceMessageId="assistant-prior-stream-draft",
                    resume={
                        "basic": {
                            "headline": "Engineer",
                            "summary": "Focused summary",
                        },
                        "sections": [],
                    },
                    editCount=1,
                    edits=[stale_client_edit],
                ),
            },
        )
        next_message = AgentChatMessage(
            id="assistant-follow-up-stream-draft",
            role="assistant",
            text="The follow-up draft is ready.",
            edits=[next_edit],
            transactionState="committed",
        )

        async def fake_loop(*_args: object, **_kwargs: object) -> AsyncIterator[object]:
            yield SimpleNamespace(
                kind="edits",
                edits=next_message.edits,
                transaction_state="provisional",
            )
            yield SimpleNamespace(
                kind="done",
                runner=SimpleNamespace(
                    build_message=lambda **_kwargs: next_message,
                    finish_status="ready",
                    tools=[],
                    transaction_failed=False,
                ),
            )

        monkeypatch.setattr(
            agent_sessions,
            "persist_agent_user_message",
            lambda conn, prepared: None,
        )
        monkeypatch.setattr(
            streaming,
            "resolve_agent_llm_config",
            lambda conn, config: SimpleNamespace(provider="custom"),
        )
        monkeypatch.setattr(
            streaming,
            "async_iter_agent_tool_call_loop",
            fake_loop,
        )

        completed: list[AgentChatMessage] = []
        frames = [
            frame
            async for frame in streaming.async_stream_agent_response(
                request,
                _FakeConnection(),
                completed.append,
            )
        ]
        provisional = next(
            frame for frame in frames if '"transactionState":"provisional"' in frame
        )
        message_done = next(
            frame for frame in frames if frame.startswith("event: message_done")
        )

        for snapshot in [provisional, message_done]:
            assert '"id":"edit-prior-summary"' in snapshot
            assert '"id":"edit-next-headline"' in snapshot
        assert [edit.id for edit in completed[0].edits] == [
            "edit-prior-summary",
            "edit-next-headline",
        ]
        assert completed[0].transaction_state == "committed"
        assert '"transactionState":"rolled_back"' not in "".join(frames)

    asyncio.run(scenario())


def test_permanent_resume_delete_purges_completed_run_replay(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/resumes",
        json={"title": "Completed run owner"},
    ).json()["data"]["resume"]
    resume_id = created["id"]
    revision = client.get(
        f"/api/agent/resumes/{resume_id}/session",
    ).json()["data"]["revision"]
    private_summary = "private-summary-must-not-survive-hard-delete"
    run_response = client.post(
        "/api/agent/chat",
        json={
            "resumeId": resume_id,
            "expectedRevision": revision,
            "message": {
                "id": "turn-completed-run-purge",
                "role": "user",
                "text": "Review my private resume.",
            },
            "messages": [],
            "locale": "en",
            "resume": {
                "basic": {"summary": private_summary},
                "sections": [],
            },
        },
    )
    run_id = run_response.headers["x-agent-run-id"]
    retained_response = client.delete(f"/api/agent/runs/{run_id}")
    assert retained_response.status_code == 200
    assert (
        retained_response.json()["data"]["baseResume"]["basic"]["summary"]
        == private_summary
    )

    assert client.post(f"/api/resumes/{resume_id}/trash").status_code == 200
    assert client.delete(f"/api/resumes/{resume_id}").status_code == 200

    assert client.delete(f"/api/agent/runs/{run_id}").status_code == 404
    assert client.get(f"/api/agent/runs/{run_id}/events").status_code == 404


def test_empty_trash_purges_completed_run_replay(client: TestClient) -> None:
    created = client.post(
        "/api/resumes",
        json={"title": "Trash purge run owner"},
    ).json()["data"]["resume"]
    resume_id = created["id"]
    revision = client.get(
        f"/api/agent/resumes/{resume_id}/session",
    ).json()["data"]["revision"]
    run_response = client.post(
        "/api/agent/chat",
        json={
            "resumeId": resume_id,
            "expectedRevision": revision,
            "message": {
                "id": "turn-empty-trash-run-purge",
                "role": "user",
                "text": "Review this resume.",
            },
            "messages": [],
            "locale": "en",
            "resume": {"basic": {"summary": "private"}, "sections": []},
        },
    )
    run_id = run_response.headers["x-agent-run-id"]

    assert client.post(f"/api/resumes/{resume_id}/trash").status_code == 200
    empty_response = client.delete("/api/resumes/trash")

    assert empty_response.status_code == 200
    assert empty_response.json()["data"]["deletedCount"] == 1
    assert client.delete(f"/api/agent/runs/{run_id}").status_code == 404
    assert client.get(f"/api/agent/runs/{run_id}/events").status_code == 404


def test_partially_failed_empty_trash_purges_runs_already_hard_deleted(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_ids_by_resume: dict[str, str] = {}
    for index in range(2):
        resume_id = client.post(
            "/api/resumes",
            json={"title": f"Partial purge owner {index}"},
        ).json()["data"]["resume"]["id"]
        revision = client.get(
            f"/api/agent/resumes/{resume_id}/session",
        ).json()["data"]["revision"]
        run_response = client.post(
            "/api/agent/chat",
            json={
                "resumeId": resume_id,
                "expectedRevision": revision,
                "message": {
                    "id": f"turn-partial-purge-{index}",
                    "role": "user",
                    "text": "Review this private resume.",
                },
                "messages": [],
                "locale": "en",
                "resume": {
                    "basic": {"summary": f"private replay {index}"},
                    "sections": [],
                },
            },
        )
        run_ids_by_resume[resume_id] = run_response.headers["x-agent-run-id"]
        assert client.post(f"/api/resumes/{resume_id}/trash").status_code == 200

    original_delete_storage = resumes._delete_resume_storage
    deleted_ids: list[str] = []

    def delete_first_then_fail(resume_id: str) -> None:
        if deleted_ids:
            raise PermissionError("forced later resume deletion failure")
        original_delete_storage(resume_id)
        deleted_ids.append(resume_id)

    monkeypatch.setattr(
        resumes,
        "_delete_resume_storage",
        delete_first_then_fail,
    )

    with pytest.raises(
        PermissionError,
        match="forced later resume deletion failure",
    ):
        client.delete("/api/resumes/trash")

    deleted_resume_id = deleted_ids[0]
    retained_resume_id = next(
        resume_id for resume_id in run_ids_by_resume if resume_id != deleted_resume_id
    )
    assert (
        client.delete(
            f"/api/agent/runs/{run_ids_by_resume[deleted_resume_id]}"
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/agent/runs/{run_ids_by_resume[retained_resume_id]}"
        ).status_code
        == 200
    )


def test_hard_delete_purges_durably_finished_run_before_memory_terminal(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resume_id = client.post(
        "/api/resumes",
        json={"title": "Terminal purge race"},
    ).json()["data"]["resume"]["id"]
    stream_may_finish = asyncio.Event()
    durable_finish_committed = threading.Event()
    real_finish = agent_sessions.finish_agent_turn_execution

    async def fake_stream(
        request: AgentChatRequest,
        conn: object,
        persist_message: object,
        runtime: AgentRuntimeContext,
    ) -> AsyncIterator[str]:
        del request, conn, persist_message, runtime
        await stream_may_finish.wait()
        if False:
            yield ""

    def finish_and_signal(*args: object, **kwargs: object) -> None:
        real_finish(*args, **kwargs)
        durable_finish_committed.set()

    monkeypatch.setattr(agent_runs, "async_stream_agent_response", fake_stream)
    monkeypatch.setattr(
        agent_runs,
        "finish_agent_turn_execution",
        finish_and_signal,
    )

    async def scenario() -> None:
        manager = AgentRunManager()
        run = await manager.start(
            AgentChatRequest(
                resumeId=resume_id,
                expectedRevision=_current_session_revision(resume_id),
                message=AgentConversationItem(
                    id="turn-terminal-purge-race",
                    role="user",
                    text="Keep private replay out of deleted resumes.",
                ),
                resume={
                    "basic": {"summary": "private terminal-window replay"},
                    "sections": [],
                },
            ),
        )
        assert run.task is not None

        # Hold the in-memory terminal publication after its durable execution
        # has committed. Permanent deletion is valid in this exact window.
        async with run.condition:
            stream_may_finish.set()
            committed = await asyncio.to_thread(
                durable_finish_committed.wait,
                1,
            )
            assert committed
            assert run.status == "active"

            resumes.trash_resume(resume_id)
            await asyncio.to_thread(resumes.delete_resume_forever, resume_id)
            await manager.purge_resume(resume_id)

            with pytest.raises(agent_runs.AgentRunNotFoundError):
                await manager.get(run.id)

        await asyncio.wait_for(run.task, timeout=1)
        with pytest.raises(agent_runs.AgentRunNotFoundError):
            await manager.get(run.id)
        assert run.id not in manager._completed_order

    asyncio.run(scenario())


def test_cancelled_hard_delete_waits_for_completed_run_purge(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resume_id = client.post(
        "/api/resumes",
        json={"title": "Cancelled hard delete"},
    ).json()["data"]["resume"]["id"]
    delete_committed = threading.Event()
    deletion_may_return = threading.Event()

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
                    "id": "message-cancelled-hard-delete",
                    "text": "Done",
                    "transactionState": "committed",
                },
            },
        )

    real_delete = resumes.delete_resume_forever

    def delete_then_wait(resume_id: str) -> dict[str, object]:
        result = real_delete(resume_id)
        delete_committed.set()
        assert deletion_may_return.wait(timeout=1)
        return result

    monkeypatch.setattr(agent_runs, "async_stream_agent_response", fake_stream)
    monkeypatch.setattr(
        resumes_router,
        "delete_resume_forever",
        delete_then_wait,
    )

    async def scenario() -> None:
        manager = AgentRunManager()
        run = await manager.start(
            AgentChatRequest(
                resumeId=resume_id,
                expectedRevision=_current_session_revision(resume_id),
                message=AgentConversationItem(
                    id="turn-cancelled-hard-delete",
                    role="user",
                    text="Do not retain this replay after deletion.",
                ),
                resume={
                    "basic": {"summary": "private cancelled-delete replay"},
                    "sections": [],
                },
            ),
        )
        assert run.task is not None
        await asyncio.wait_for(run.task, timeout=1)
        resumes.trash_resume(resume_id)

        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(agent_runs=manager),
            ),
        )
        delete_task = asyncio.create_task(
            resumes_router.delete_resume(resume_id, request),
        )
        committed = await asyncio.to_thread(delete_committed.wait, 1)
        assert committed

        delete_task.cancel()
        deletion_may_return.set()
        with pytest.raises(asyncio.CancelledError):
            await delete_task

        with pytest.raises(agent_runs.AgentRunNotFoundError):
            await manager.get(run.id)

    try:
        asyncio.run(scenario())
    finally:
        deletion_may_return.set()


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


def test_turn_preparation_does_not_block_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        preparation_started = threading.Event()
        release_preparation = threading.Event()

        def blocking_prepare(
            request: AgentChatRequest,
            run_id: str,
        ) -> AgentChatRequest:
            del run_id
            preparation_started.set()
            assert release_preparation.wait(timeout=1)
            return request

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
                        "id": "message-nonblocking-preparation",
                        "text": "Done",
                        "transactionState": "committed",
                    },
                },
            )

        monkeypatch.setattr(agent_runs, "connect", _FakeConnection)
        monkeypatch.setattr(agent_runs, "_prepare_run_request", blocking_prepare)
        monkeypatch.setattr(agent_runs, "async_stream_agent_response", fake_stream)

        manager = AgentRunManager()
        release_timer = threading.Timer(0.3, release_preparation.set)
        release_timer.start()
        try:
            start_task = asyncio.create_task(
                manager.start(_request("resume-nonblocking-preparation")),
            )
            started_at = perf_counter()
            await asyncio.sleep(0.01)
            elapsed = perf_counter() - started_at

            assert preparation_started.is_set()
            assert elapsed < 0.1

            release_preparation.set()
            run = await asyncio.wait_for(start_task, timeout=1)
            assert run.task is not None
            await asyncio.wait_for(run.task, timeout=1)
        finally:
            release_preparation.set()
            release_timer.cancel()

    asyncio.run(scenario())


def test_terminal_persistence_does_not_block_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        persistence_started = threading.Event()
        release_persistence = threading.Event()

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
                        "id": "message-nonblocking-terminal",
                        "text": "Done",
                        "transactionState": "committed",
                    },
                },
            )

        def blocking_finish(*args: object, **kwargs: object) -> None:
            del args, kwargs
            persistence_started.set()
            assert release_persistence.wait(timeout=1)

        monkeypatch.setattr(agent_runs, "connect", _FakeConnection)
        monkeypatch.setattr(agent_runs, "async_stream_agent_response", fake_stream)
        monkeypatch.setattr(
            agent_runs,
            "finish_agent_turn_execution",
            blocking_finish,
        )
        _bypass_turn_preparation(monkeypatch)

        manager = AgentRunManager()
        release_timer = threading.Timer(0.3, release_persistence.set)
        release_timer.start()
        try:
            run = await manager.start(_request("resume-nonblocking-terminal"))
            started_at = perf_counter()
            await asyncio.sleep(0.01)
            elapsed = perf_counter() - started_at

            assert persistence_started.is_set()
            assert elapsed < 0.1

            release_persistence.set()
            assert run.task is not None
            await asyncio.wait_for(run.task, timeout=1)
        finally:
            release_persistence.set()
            release_timer.cancel()

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
        conn = connect()
        revision = _current_session_revision("resume-cancelled-persistence")
        request = AgentChatRequest(
            resumeId="resume-cancelled-persistence",
            expectedRevision=revision,
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


def test_explicit_stop_persists_visible_partial_message(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resume_id = "resume-cancelled-partial-message"
    partial_text = "已完成岗位分析，正在整理改写建议。"

    async def scenario() -> tuple[str, list[str]]:
        partial_published = asyncio.Event()
        blocked_stream = asyncio.Event()

        async def fake_stream(
            request: AgentChatRequest,
            conn: object,
            persist_message: object,
            runtime: AgentRuntimeContext,
        ) -> AsyncIterator[str]:
            del request, conn, persist_message, runtime
            yield agent_runs._sse_frame(
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": "message-cancelled-partial",
                        "role": "assistant",
                        "text": "",
                    },
                },
            )
            yield agent_runs._sse_frame(
                "text_delta",
                {"type": "text_delta", "delta": partial_text},
            )
            for tool_id, state in (
                ("tool-input-streaming", "input-streaming"),
                ("tool-input-available", "input-available"),
                ("tool-approval-requested", "approval-requested"),
                ("tool-approval-responded", "approval-responded"),
            ):
                yield agent_runs._sse_frame(
                    "tool_start",
                    {
                        "type": "tool_start",
                        "tool": {
                            "id": tool_id,
                            "type": "tool-web_search",
                            "title": "web_search",
                            "state": state,
                            "input": {"query": "staff frontend engineer"},
                            "startedAt": "2026-08-10T10:00:00Z",
                        },
                    },
                )
            yield agent_runs._sse_frame(
                "tool_done",
                {
                    "type": "tool_done",
                    "tool": {
                        "id": "tool-already-complete",
                        "type": "tool-resume_analysis",
                        "title": "resume_analysis",
                        "state": "output-available",
                        "output": {"score": 90},
                        "startedAt": "2026-08-10T09:59:58Z",
                        "completedAt": "2026-08-10T09:59:59Z",
                    },
                },
            )
            yield agent_runs._sse_frame(
                "edits",
                {
                    "type": "edits",
                    "message": {
                        "edits": [{"id": "uncommitted-edit"}],
                        "transactionState": "provisional",
                    },
                },
            )
            partial_published.set()
            await blocked_stream.wait()

        monkeypatch.setattr(agent_runs, "async_stream_agent_response", fake_stream)

        manager = AgentRunManager()
        run = await manager.start(
            AgentChatRequest(
                resumeId=resume_id,
                expectedRevision=_current_session_revision(resume_id),
                message=AgentConversationItem(
                    id="turn-cancelled-partial",
                    role="user",
                    text="请优化这份简历。",
                ),
                resume={"basic": {}, "sections": []},
            ),
        )
        await asyncio.wait_for(partial_published.wait(), timeout=1)

        await manager.stop(run.id)
        assert run.task is not None
        await asyncio.wait_for(run.task, timeout=1)

        return run.id, await _collect_events(manager, run.id)

    run_id, events = asyncio.run(scenario())

    rollback_index = next(
        index
        for index, frame in enumerate(events)
        if '"transactionState":"rolled_back"' in frame
    )
    message_done_index = next(
        index for index, frame in enumerate(events) if "event: message_done" in frame
    )
    terminal_index = next(
        index for index, frame in enumerate(events) if "event: run_done" in frame
    )
    assert rollback_index < message_done_index < terminal_index
    assert partial_text in events[message_done_index]
    assert "uncommitted-edit" not in events[message_done_index]
    cancelled_message_payload = agent_runs._event_payload(
        events[message_done_index],
    )[1]["message"]
    cancelled_tools = {tool["id"]: tool for tool in cancelled_message_payload["tools"]}
    for tool_id in (
        "tool-input-streaming",
        "tool-input-available",
        "tool-approval-requested",
        "tool-approval-responded",
    ):
        assert cancelled_tools[tool_id]["state"] == "output-error"
        assert cancelled_tools[tool_id]["errorText"] == "Cancelled."
        assert cancelled_tools[tool_id]["completedAt"] is not None
    assert cancelled_tools["tool-already-complete"]["state"] == ("output-available")
    assert cancelled_tools["tool-already-complete"]["output"] == {"score": 90}
    assert '"status":"cancelled"' in events[terminal_index]

    session_response = client.get(f"/api/agent/resumes/{resume_id}/session")
    assert session_response.status_code == 200
    session = session_response.json()["data"]
    assert [message["role"] for message in session["messages"]] == [
        "user",
        "assistant",
    ]
    assistant = session["messages"][-1]
    assert assistant["text"] == partial_text
    assert assistant["response"]["transactionState"] == "rolled_back"
    assert assistant["response"]["edits"] == []
    assert assistant["response"].get("draft") is None
    assert assistant["response"]["tools"] == cancelled_message_payload["tools"]
    execution = session["executions"][-1]
    assert execution["runId"] == run_id
    assert execution["turnId"] == "turn-cancelled-partial"
    assert execution["status"] == "cancelled"
    assert execution["errorCode"] == "AGENT_RUN_CANCELLED"
    assert execution["completedAt"] is not None

    refreshed = client.get(f"/api/agent/resumes/{resume_id}/session").json()["data"]
    assert refreshed["revision"] == session["revision"]
    assert refreshed["messages"] == session["messages"]


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
                expectedRevision=_current_session_revision(
                    "resume-success-state",
                ),
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


def test_shutdown_interrupts_terminal_retry_for_startup_cleanup(
    client: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del client
    resume_id = "resume-terminal-persistence-shutdown"

    async def scenario() -> str:
        failure_seen = asyncio.Event()

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
                        "id": "message-terminal-persistence-shutdown",
                        "text": "Done",
                        "transactionState": "committed",
                    },
                },
            )

        def fail_terminal_persistence(*args: object, **kwargs: object) -> None:
            del args, kwargs
            failure_seen.set()
            raise OSError("terminal database commit failed")

        monkeypatch.setattr(agent_runs, "async_stream_agent_response", fake_stream)
        monkeypatch.setattr(
            agent_runs,
            "finish_agent_turn_execution",
            fail_terminal_persistence,
        )
        monkeypatch.setattr(
            agent_runs,
            "AGENT_TERMINAL_RETRY_INITIAL_SECONDS",
            0.001,
        )
        monkeypatch.setattr(
            agent_runs,
            "AGENT_TERMINAL_RETRY_MAX_SECONDS",
            0.005,
        )

        manager = AgentRunManager()
        run = await manager.start(
            AgentChatRequest(
                resumeId=resume_id,
                expectedRevision=_current_session_revision(resume_id),
                message=AgentConversationItem(
                    id="turn-terminal-persistence-shutdown",
                    role="user",
                    text="Leave startup cleanup an owned running row.",
                ),
            ),
        )
        assert run.task is not None
        await asyncio.wait_for(failure_seen.wait(), timeout=1)
        assert run.terminalizing

        await manager.shutdown()

        assert run.task.cancelled()
        assert run.status == "active"
        assert run.id in manager._reserved_run_ids
        assert not any("event: run_done" in event.frame for event in run.events)
        return run.id

    run_id = asyncio.run(scenario())

    with closing(connect()) as conn:
        before_cleanup = agent_sessions.load_agent_session(conn, resume_id)
        assert before_cleanup.executions[-1].run_id == run_id
        assert before_cleanup.executions[-1].status == "running"
        assert agent_sessions.fail_interrupted_agent_turn_executions(conn) == 1
        after_cleanup = agent_sessions.load_agent_session(conn, resume_id)

    assert after_cleanup.executions[-1].status == "failed"
    assert after_cleanup.executions[-1].error_code == "AGENT_INTERNAL_ERROR"


def test_terminal_persistence_failure_recovers_only_its_durable_execution(
    client: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del client
    resume_id = "resume-terminal-persistence-recovery"
    unaffected_resume_id = "resume-terminal-persistence-unaffected"
    unaffected_run_id = "run-terminal-persistence-unaffected"
    unaffected_revision = _current_session_revision(unaffected_resume_id)

    with closing(connect()) as conn:
        agent_sessions.prepare_agent_turn(
            conn,
            AgentChatRequest(
                resumeId=unaffected_resume_id,
                expectedRevision=unaffected_revision,
                message=AgentConversationItem(
                    id="turn-terminal-persistence-unaffected",
                    role="user",
                    text="Keep this unrelated execution running.",
                ),
            ),
            run_id=unaffected_run_id,
        )

    real_finish = agent_sessions.finish_agent_turn_execution
    finish_attempts = 0

    def fail_first_finish(*args: object, **kwargs: object) -> None:
        nonlocal finish_attempts
        finish_attempts += 1
        if finish_attempts == 1:
            raise OSError("terminal database commit failed")
        real_finish(*args, **kwargs)

    async def scenario() -> str:
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
                        "id": "message-terminal-persistence-recovery",
                        "text": "Done",
                        "transactionState": "committed",
                    },
                },
            )

        monkeypatch.setattr(agent_runs, "async_stream_agent_response", fake_stream)
        monkeypatch.setattr(
            agent_runs,
            "finish_agent_turn_execution",
            fail_first_finish,
        )

        manager = AgentRunManager()
        run = await manager.start(
            AgentChatRequest(
                resumeId=resume_id,
                expectedRevision=_current_session_revision(resume_id),
                message=AgentConversationItem(
                    id="turn-terminal-persistence-recovery",
                    role="user",
                    text="Recover this execution if terminal persistence fails.",
                ),
            ),
        )
        assert run.task is not None
        await asyncio.wait_for(run.task, timeout=1)
        assert run.status == "failed"
        assert run.execution_state == "failed"
        assert run.error_code == "AGENT_INTERNAL_ERROR"
        return run.id

    recovered_run_id = asyncio.run(scenario())

    with closing(connect()) as conn:
        recovered = agent_sessions.load_agent_session(conn, resume_id)
        unaffected = agent_sessions.load_agent_session(conn, unaffected_resume_id)

    assert finish_attempts == 2
    assert [
        (execution.run_id, execution.status, execution.error_code)
        for execution in recovered.executions
    ] == [(recovered_run_id, "failed", "AGENT_INTERNAL_ERROR")]
    assert [
        (execution.run_id, execution.status, execution.error_code)
        for execution in unaffected.executions
    ] == [(unaffected_run_id, "running", None)]


def test_terminal_persistence_retries_while_run_stays_active(
    client: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del client
    resume_id = "resume-terminal-persistence-retries"
    real_finish = agent_sessions.finish_agent_turn_execution
    allow_finish = threading.Event()
    finish_attempts = 0

    async def scenario() -> str:
        third_failure = asyncio.Event()

        def unavailable_finish(*args: object, **kwargs: object) -> None:
            nonlocal finish_attempts
            finish_attempts += 1
            if not allow_finish.is_set():
                if finish_attempts >= 3:
                    third_failure.set()
                raise OSError("terminal database remains unavailable")
            real_finish(*args, **kwargs)

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
                        "id": "message-terminal-persistence-retries",
                        "text": "Done",
                        "transactionState": "committed",
                    },
                },
            )

        monkeypatch.setattr(agent_runs, "async_stream_agent_response", fake_stream)
        monkeypatch.setattr(
            agent_runs,
            "finish_agent_turn_execution",
            unavailable_finish,
        )
        monkeypatch.setattr(
            agent_runs,
            "AGENT_TERMINAL_RETRY_INITIAL_SECONDS",
            0.001,
            raising=False,
        )
        monkeypatch.setattr(
            agent_runs,
            "AGENT_TERMINAL_RETRY_MAX_SECONDS",
            0.005,
            raising=False,
        )

        manager = AgentRunManager()
        run = await manager.start(
            AgentChatRequest(
                resumeId=resume_id,
                expectedRevision=_current_session_revision(resume_id),
                message=AgentConversationItem(
                    id="turn-terminal-persistence-retries",
                    role="user",
                    text="Keep retrying terminal persistence.",
                ),
            ),
        )
        assert run.task is not None
        third_failure_task = asyncio.create_task(third_failure.wait())
        done, _ = await asyncio.wait(
            {third_failure_task, run.task},
            timeout=1,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if third_failure_task not in done:
            allow_finish.set()
            await asyncio.gather(run.task, return_exceptions=True)
            pytest.fail("The run stopped retrying before the third failure.")

        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(agent_runs=manager),
            ),
        )
        active_response = await agent_router.get_active_agent_run(
            request,
            resume_id,
        )
        assert active_response.data is not None
        assert active_response.data.id == run.id
        assert active_response.data.status == "active"
        assert active_response.data.execution_state == "running"
        assert active_response.data.error_code is None
        assert run.id in manager._reserved_run_ids
        assert not any("event: run_done" in event.frame for event in run.events)
        with closing(connect()) as conn:
            execution = agent_sessions.load_agent_session(
                conn,
                resume_id,
            ).executions[-1]
        assert execution.status == "running"

        attempts_before_stop = finish_attempts
        await manager.stop(run.id)
        await asyncio.sleep(0.02)
        assert not run.task.done()
        assert finish_attempts > attempts_before_stop
        assert await manager.active_for_resume(resume_id) is run
        assert run.id in manager._reserved_run_ids

        allow_finish.set()
        await asyncio.wait_for(run.task, timeout=1)
        assert await manager.active_for_resume(resume_id) is None
        assert run.id not in manager._reserved_run_ids
        assert sum("event: run_done" in event.frame for event in run.events) == 1
        return run.id

    run_id = asyncio.run(scenario())

    with closing(connect()) as conn:
        execution = agent_sessions.load_agent_session(
            conn,
            resume_id,
        ).executions[-1]
    assert finish_attempts >= 4
    assert execution.run_id == run_id
    assert execution.status == "failed"
    assert execution.error_code == "AGENT_INTERNAL_ERROR"


def test_provider_timeout_error_code_is_consistent_across_run_and_reload(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resume_id = "resume-provider-timeout-state"
    timeout_detail = "Model provider request timed out."
    config = AgentLlmConfig(
        client_id="provider-timeout-state",
        name="Provider Timeout State",
        provider="openai",
        model="test-model",
        base_url="https://example.test/v1",
        api_key="sk-test",
        temperature=None,
        top_p=None,
        max_tokens=None,
        timeout_seconds=30,
    )

    async def timeout_tool_loop(
        *args: object,
        **kwargs: object,
    ) -> AsyncIterator[object]:
        del args, kwargs
        if False:
            yield object()
        raise LlmTimeoutError(timeout_detail)

    monkeypatch.setattr(
        streaming,
        "resolve_agent_llm_config",
        lambda conn, model_config: config,
    )
    monkeypatch.setattr(
        streaming,
        "async_iter_agent_tool_call_loop",
        timeout_tool_loop,
    )

    async def scenario() -> tuple[str, dict[str, object]]:
        manager = AgentRunManager()
        run = await manager.start(
            AgentChatRequest(
                resumeId=resume_id,
                expectedRevision=_current_session_revision(resume_id),
                message=AgentConversationItem(
                    id="agent-user-provider-timeout-state",
                    role="user",
                    text="Review this resume.",
                ),
                resume={"basic": {}, "sections": []},
            ),
        )
        assert run.task is not None
        await asyncio.wait_for(run.task, timeout=2)
        frames = await _collect_events(manager, run.id)

        def event_payload(event_name: str) -> dict[str, object]:
            for frame in frames:
                lines = frame.splitlines()
                if not lines or lines[0] != f"event: {event_name}":
                    continue
                data = "\n".join(
                    line.removeprefix("data:").strip()
                    for line in lines
                    if line.startswith("data:")
                )
                payload = json.loads(data)
                assert isinstance(payload, dict)
                return payload
            pytest.fail(f"Missing {event_name} event")

        error_payload = event_payload("error")
        message_payload = event_payload("message_done")
        run_payload = event_payload("run_done")
        assert error_payload["errorCode"] == "AGENT_PROVIDER_TIMEOUT"
        assert timeout_detail in str(message_payload["message"])
        assert run_payload["errorCode"] == "AGENT_PROVIDER_TIMEOUT"
        assert run.response().error_code == "AGENT_PROVIDER_TIMEOUT"
        return run.id, run_payload

    run_id, _ = asyncio.run(scenario())

    with closing(connect()) as conn:
        execution = agent_sessions.load_agent_session(
            conn,
            resume_id,
        ).executions[-1]
    assert execution.run_id == run_id
    assert execution.status == "failed"
    assert execution.error_code == "AGENT_PROVIDER_TIMEOUT"

    reloaded = client.get(f"/api/agent/resumes/{resume_id}/session")
    assert reloaded.status_code == 200
    reloaded_execution = reloaded.json()["data"]["executions"][-1]
    assert reloaded_execution["runId"] == run_id
    assert reloaded_execution["errorCode"] == "AGENT_PROVIDER_TIMEOUT"


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
                expectedRevision=_current_session_revision(
                    "resume-provider-401",
                ),
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
                expectedRevision=_current_session_revision(
                    "resume-unexpected-failure",
                ),
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
                expectedRevision=_current_session_revision(
                    "resume-cancelled-state",
                ),
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
    revision = _current_session_revision("resume-interrupted-state")
    with closing(connect()) as conn:
        request = AgentChatRequest(
            resumeId="resume-interrupted-state",
            expectedRevision=revision,
            message=AgentConversationItem(
                id="agent-user-interrupted-state",
                role="user",
                text="Improve this resume.",
            ),
            resume={"basic": {}, "sections": []},
        )
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

    def retry_request(revision: str) -> AgentChatRequest:
        return AgentChatRequest(
            resumeId="resume-same-millisecond-retry",
            expectedRevision=revision,
            message=AgentConversationItem(
                id="agent-user-same-millisecond-retry",
                role="user",
                text="Improve this resume.",
            ),
            resume={"basic": {}, "sections": []},
        )

    _current_session_revision("resume-same-millisecond-retry")
    with closing(connect()) as conn:
        failed_request = agent_sessions.prepare_agent_turn(
            conn,
            retry_request(
                agent_sessions.load_agent_session(
                    conn,
                    "resume-same-millisecond-retry",
                ).revision,
            ),
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
            retry_request(
                agent_sessions.load_agent_session(
                    conn,
                    "resume-same-millisecond-retry",
                ).revision,
            ),
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


def test_global_active_run_capacity_is_enforced(
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
        monkeypatch.setattr(agent_runs, "MAX_ACTIVE_AGENT_RUNS", 2)
        _bypass_turn_preparation(monkeypatch)

        manager = AgentRunManager()
        first = await manager.start(_request("resume-capacity-1"))
        second = await manager.start(_request("resume-capacity-2"))

        with pytest.raises(agent_runs.AgentRunCapacityError):
            await manager.start(_request("resume-capacity-3"))

        await manager.stop(first.id)
        assert first.task is not None
        await asyncio.wait_for(first.task, timeout=1)

        third = await manager.start(_request("resume-capacity-3"))
        for run in (second, third):
            await manager.stop(run.id)
            assert run.task is not None
            await asyncio.wait_for(run.task, timeout=1)

    asyncio.run(scenario())
