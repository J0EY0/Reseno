from collections.abc import Callable
from contextlib import closing
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.db.connection import connect
from app.schemas.agent import AgentChatRequest, AgentConversationItem
from app.services import agent_sessions
from app.services.agent import attachments


class _AfterCommitConnection:
    def __init__(self, conn: Any, after_commit: Callable[[], None]) -> None:
        self.conn = conn
        self.after_commit = after_commit

    def __getattr__(self, name: str) -> Any:
        return getattr(self.conn, name)

    def commit(self) -> None:
        self.conn.commit()
        callback, self.after_commit = self.after_commit, lambda: None
        callback()


def test_history_cleanup_preserves_attachments_of_a_turn_accepted_after_commit(
    client: TestClient,
) -> None:
    created = client.post("/api/resumes", json={"documentLocale": "en"}).json()["data"]
    resume_id = created["resume"]["id"]
    old_file, new_file = [
        attachments.store_resume_agent_attachment(
            resume_id=resume_id,
            filename=f"{label}.txt",
            media_type="text/plain",
            payload=f"{label} evidence".encode(),
        ).model_dump(mode="json", by_alias=True)
        for label in ("old", "new")
    ]
    with closing(connect()) as conn:
        initial = agent_sessions.load_agent_session(conn, resume_id)
        old_session = agent_sessions.replace_agent_session_messages(
            conn,
            resume_id,
            locale="en",
            revision=initial.revision,
            messages=[
                AgentConversationItem(
                    id="old-turn", role="user", text="Old", files=[old_file]
                )
            ],
        )

        def accept_new_turn() -> None:
            with closing(connect()) as writer:
                current = agent_sessions.load_agent_session(writer, resume_id)
                agent_sessions.accept_agent_turn(
                    writer,
                    AgentChatRequest(
                        resumeId=resume_id,
                        expectedRevision=current.revision,
                        locale="en",
                        resume=created["resume"]["resume"],
                        message={
                            "id": "new-turn",
                            "role": "user",
                            "text": "New",
                            "files": [new_file],
                        },
                    ),
                    run_id="new-run",
                    resolved_config=None,
                )

        result = agent_sessions.replace_agent_session_messages(
            _AfterCommitConnection(conn, accept_new_turn),
            resume_id,
            locale="en",
            messages=[],
            revision=old_session.revision,
        )

    assert [message.id for message in result.messages] == ["new-turn"]
    assert result.messages[0].files == [new_file]
    assert attachments.load_agent_attachment(resume_id, new_file) is not None
    assert attachments.load_agent_attachment(resume_id, old_file) is None


def test_session_read_keeps_messages_executions_and_revision_in_one_snapshot(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.schemas.agent import AgentChatMessage

    created = client.post("/api/resumes", json={"documentLocale": "en"}).json()["data"]
    resume_id = created["resume"]["id"]
    with closing(connect()) as conn:
        turn = agent_sessions.accept_agent_turn(
            conn,
            AgentChatRequest(
                resumeId=resume_id,
                expectedRevision=agent_sessions.load_agent_session(
                    conn, resume_id
                ).revision,
                message={"id": "snapshot-user", "role": "user", "text": "Hello"},
            ),
            run_id="snapshot-run",
            resolved_config=None,
        )
        before = agent_sessions.load_agent_session(conn, resume_id)

    original = agent_sessions._load_message_rows
    completed = False

    def complete_after_message_read(conn, session_id):
        nonlocal completed
        rows = original(conn, session_id)
        if not completed:
            completed = True
            with closing(connect()) as writer:
                agent_sessions.persist_agent_terminal_outcome(
                    writer,
                    turn,
                    agent_sessions.AgentTerminalOutcome(
                        status="succeeded",
                        error_code=None,
                        checkpoint=None,
                        assistant=AgentChatMessage(
                            id="snapshot-answer", role="assistant", text="Saved answer"
                        ),
                    ),
                )
        return rows

    monkeypatch.setattr(
        agent_sessions, "_load_message_rows", complete_after_message_read
    )
    with closing(connect()) as reader:
        snapshot = agent_sessions.load_agent_session(reader, resume_id)
        assert not reader.in_transaction
        latest = agent_sessions.load_agent_session(reader, resume_id)
    assert snapshot == before
    assert latest.executions[0].status == "succeeded"
    assert [message.id for message in latest.messages] == [
        "snapshot-user",
        "snapshot-answer",
    ]
    assert latest.revision != snapshot.revision


def test_recovery_reloads_a_turn_completed_after_its_session_snapshot(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from app.schemas.agent import AgentChatMessage
    from app.services import agent_runs
    from app.services.agent.runtime.streaming import AgentCompleted

    created = client.post("/api/resumes", json={"documentLocale": "en"}).json()["data"]
    resume_id = created["resume"]["id"]
    with closing(connect()) as conn:
        revision = agent_sessions.load_agent_session(conn, resume_id).revision
    monkeypatch.setattr(agent_runs, "resolve_agent_llm_config", lambda *_args: None)

    async def exercise() -> None:
        release = asyncio.Event()
        loop = asyncio.get_running_loop()

        async def events(*_args):
            await release.wait()
            yield AgentCompleted(
                message=AgentChatMessage(
                    id="recovered-answer", role="assistant", text="Durable answer"
                ),
                persist=True,
            )

        monkeypatch.setattr(agent_runs, "async_iter_agent_events", events)
        manager = agent_runs.AgentRunManager()
        try:
            run = await manager.start(
                AgentChatRequest(
                    resumeId=resume_id,
                    expectedRevision=revision,
                    message={"id": "recovery-user", "role": "user", "text": "Hello"},
                    resume=created["resume"]["resume"],
                )
            )
            original = agent_sessions._load_message_rows
            completed = False

            async def finish() -> None:
                release.set()
                await run.task

            def finish_after_rows(conn, session_id):
                nonlocal completed
                rows = original(conn, session_id)
                if not completed:
                    completed = True
                    asyncio.run_coroutine_threadsafe(finish(), loop).result(timeout=3)
                return rows

            monkeypatch.setattr(agent_sessions, "_load_message_rows", finish_after_rows)
            recovered = await manager.recover_session(resume_id)
            assert recovered.run is None
            assert [message.id for message in recovered.session.messages] == [
                "recovery-user",
                "recovered-answer",
            ]
            assert recovered.session.executions[0].status == "succeeded"
        finally:
            await manager.shutdown()

    asyncio.run(exercise())


def test_history_cleanup_does_not_delete_files_before_an_outer_commit(
    client: TestClient,
) -> None:
    created = client.post("/api/resumes", json={"documentLocale": "en"}).json()["data"]
    resume_id = created["resume"]["id"]
    file = attachments.store_resume_agent_attachment(
        resume_id=resume_id,
        filename="retained.txt",
        media_type="text/plain",
        payload=b"Retained facts",
    ).model_dump(mode="json", by_alias=True)
    with closing(connect()) as conn:
        initial = agent_sessions.load_agent_session(conn, resume_id)
        saved = agent_sessions.replace_agent_session_messages(
            conn,
            resume_id,
            locale="en",
            revision=initial.revision,
            messages=[
                AgentConversationItem(
                    id="retained-turn", role="user", text="Facts", files=[file]
                )
            ],
        )
        conn.execute("BEGIN IMMEDIATE")
        agent_sessions.replace_agent_session_messages(
            conn,
            resume_id,
            locale="en",
            revision=saved.revision,
            messages=[],
        )
        assert conn.in_transaction
        conn.rollback()
        assert agent_sessions.load_agent_session(conn, resume_id) == saved
    assert attachments.load_agent_attachment(resume_id, file) is not None


def test_recovery_waits_for_registration_without_cancelling_the_accepted_run(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    from threading import Event

    from app.schemas.agent import AgentChatMessage
    from app.services import agent_runs
    from app.services.agent.runtime.streaming import AgentCompleted

    created = client.post("/api/resumes", json={"documentLocale": "en"}).json()["data"]
    resume_id = created["resume"]["id"]
    with closing(connect()) as conn:
        revision = agent_sessions.load_agent_session(conn, resume_id).revision
    original_prepare = agent_runs._prepare_run_request
    accepted, register = Event(), Event()
    original_read = agent_runs._read_agent_session
    snapshot_read = Event()

    def prepare(request, run_id):
        result = original_prepare(request, run_id)
        accepted.set()
        assert register.wait(timeout=4)
        return result

    def read_session(session_id):
        session = original_read(session_id)
        snapshot_read.set()
        return session

    monkeypatch.setattr(agent_runs, "resolve_agent_llm_config", lambda *_args: None)
    monkeypatch.setattr(agent_runs, "_prepare_run_request", prepare)
    monkeypatch.setattr(agent_runs, "_read_agent_session", read_session)

    async def exercise() -> None:
        release = asyncio.Event()

        async def events(*_args):
            await release.wait()
            yield AgentCompleted(
                message=AgentChatMessage(
                    id="registered-answer", role="assistant", text="Done"
                ),
                persist=True,
            )

        monkeypatch.setattr(agent_runs, "async_iter_agent_events", events)
        manager = agent_runs.AgentRunManager()
        start = asyncio.create_task(
            manager.start(
                AgentChatRequest(
                    resumeId=resume_id,
                    expectedRevision=revision,
                    message={"id": "registered-user", "role": "user", "text": "Hello"},
                    resume=created["resume"]["resume"],
                )
            )
        )
        try:
            assert await asyncio.to_thread(accepted.wait, 3)
            cancelled = asyncio.create_task(manager.recover_session(resume_id))
            assert await asyncio.to_thread(snapshot_read.wait, 3)
            await asyncio.sleep(0)
            assert not cancelled.done()
            cancelled.cancel()
            with pytest.raises(asyncio.CancelledError):
                await cancelled
            assert not start.done()
            recovering = asyncio.create_task(manager.recover_session(resume_id))
            register.set()
            run = await start
            recovered = await recovering
            assert recovered.run is not None
            assert recovered.run.id == run.id
            assert recovered.run.status == "active"
            assert recovered.session.executions[0].run_id == run.id
            release.set()
            await run.task
            terminal = await manager.recover_session(resume_id)
            assert terminal.run is None
            assert [message.id for message in terminal.session.messages] == [
                "registered-user",
                "registered-answer",
            ]
        finally:
            register.set()
            await start
            await manager.shutdown()

    asyncio.run(exercise())


def test_recovery_endpoint_returns_session_and_run_together(client: TestClient) -> None:
    created = client.post("/api/resumes", json={"documentLocale": "en"}).json()["data"]
    resume_id = created["resume"]["id"]
    response = client.get(f"/api/agent/resumes/{resume_id}/recovery")
    assert response.status_code == 200
    assert response.json()["data"] == {
        "session": client.get(f"/api/agent/resumes/{resume_id}/session").json()["data"],
        "run": None,
    }
    assert client.get(f"/api/agent/resumes/{resume_id}/run").status_code == 404


def test_history_cleanup_lock_failure_keeps_the_committed_history_and_files(
    client: TestClient,
) -> None:
    created = client.post("/api/resumes", json={"documentLocale": "en"}).json()["data"]
    resume_id = created["resume"]["id"]
    file = attachments.store_resume_agent_attachment(
        resume_id=resume_id,
        filename="retained.txt",
        media_type="text/plain",
        payload=b"Retained facts",
    ).model_dump(mode="json", by_alias=True)
    with closing(connect()) as conn, closing(connect()) as writer:
        initial = agent_sessions.load_agent_session(conn, resume_id)
        saved = agent_sessions.replace_agent_session_messages(
            conn,
            resume_id,
            locale="en",
            revision=initial.revision,
            messages=[
                AgentConversationItem(
                    id="retained-turn", role="user", text="Facts", files=[file]
                )
            ],
        )
        conn.execute("PRAGMA busy_timeout = 0")
        try:
            cleared = agent_sessions.replace_agent_session_messages(
                _AfterCommitConnection(conn, lambda: writer.execute("BEGIN IMMEDIATE")),
                resume_id,
                locale="en",
                revision=saved.revision,
                messages=[],
            )
            assert cleared.messages == []
            assert cleared.revision != saved.revision
            assert agent_sessions.load_agent_session(conn, resume_id) == cleared
            assert attachments.load_agent_attachment(resume_id, file) is not None
        finally:
            writer.rollback()
