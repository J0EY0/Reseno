from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from app.db.connection import connect
from app.schemas.agent import (
    AgentChatMessage,
    AgentChatRequest,
    AgentConversationCheckpoint,
)
from app.services import agent_sessions


@pytest.mark.parametrize("operation", ["load", "accept"])
def test_history_snapshot_decodes_once_and_reuses_raw_rows(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    session_id = "historysnapshot"
    with closing(connect()) as conn:
        conn.execute(
            "INSERT INTO resumes(id,saved_at) VALUES (?,?)",
            (session_id, "2026-09-07"),
        )
        conn.execute(
            "INSERT INTO agent_sessions(id,resume_id,locale,title) VALUES (?,?,?,?)",
            (session_id, session_id, "en", "History"),
        )
        for index in range(10):
            role = "user" if index % 2 == 0 else "assistant"
            response = None
            if role == "assistant":
                response = agent_sessions._encode_persisted_assistant_response(
                    AgentChatMessage(
                        id=f"message-{index}", role="assistant", text="Done"
                    ),
                    AgentConversationCheckpoint(
                        throughMessageId=f"message-{index - 1}",
                        summary={"trust": "untrusted_history_data", "events": []},
                    ),
                )
            conn.execute(
                "INSERT INTO agent_messages "
                "(id,session_id,role,text,response_json,sequence) VALUES (?,?,?,?,?,?)",
                (f"message-{index}", session_id, role, "Text", response, index),
            )
        revision = agent_sessions._session_revision(conn, session_id)
        calls = 0
        original = agent_sessions._decode_persisted_assistant_response

        def decode(*args, **kwargs):
            nonlocal calls
            if args[0] is not None:
                calls += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(
            agent_sessions, "_decode_persisted_assistant_response", decode
        )
        queries: list[str] = []
        conn.set_trace_callback(queries.append)
        if operation == "load":
            loaded = agent_sessions.load_agent_session(conn, session_id)
            assert loaded.revision == revision
            assert len(loaded.messages) == 10
        else:
            turn = agent_sessions.accept_agent_turn(
                conn,
                AgentChatRequest(
                    resumeId=session_id,
                    expectedRevision=revision,
                    message={"id": "current", "role": "user", "text": "Continue"},
                ),
                run_id="run-snapshot",
                resolved_config=None,
            )
            assert len(turn.request.messages) == 10
            checkpoint = turn.conversation_state.active_checkpoint
            assert checkpoint is not None
            assert checkpoint.through_message_id == "message-8"
        conn.set_trace_callback(None)
        assert calls == 5
        assert (
            sum(
                "FROM agent_messages" in sql and "ORDER BY sequence ASC" in sql
                for sql in queries
            )
            == 1
        )
        assert not any("SELECT sequence" in sql for sql in queries)
        if operation == "accept":
            assert turn.revision == agent_sessions._session_revision(conn, session_id)
