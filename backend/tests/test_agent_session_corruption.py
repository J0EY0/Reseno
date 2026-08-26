import json
import logging
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.services import agent_sessions

PRIVATE_VALUE = "private-phone-13800138000"


@pytest.fixture
def agent_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    schema_path = Path(__file__).parents[1] / "app" / "db" / "schema.sql"
    conn.executescript(schema_path.read_text(encoding="utf-8"))
    try:
        yield conn
    finally:
        conn.close()


def _insert_stored_message(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    message_id: str,
    role: str,
    files_json: str = "[]",
    response_json: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO resumes (id, title, saved_at)
        VALUES (?, 'Corruption test resume', '2026-08-10T00:00:00Z')
        """,
        (session_id,),
    )
    conn.execute(
        """
        INSERT INTO agent_sessions (id, resume_id, locale, title)
        VALUES (?, ?, 'zh', '')
        """,
        (session_id, session_id),
    )
    conn.execute(
        """
        INSERT INTO agent_messages (
            id, session_id, role, text, files_json, response_json, sequence
        )
        VALUES (?, ?, ?, '', ?, ?, 1)
        """,
        (message_id, session_id, role, files_json, response_json),
    )


@pytest.mark.parametrize(
    ("field", "files_json", "response_json"),
    [
        ("files", f'["{PRIVATE_VALUE}"', None),
        ("files", f'{{"phone":"{PRIVATE_VALUE}"}}', None),
        ("files", f'[{{"id":"valid"}},"{PRIVATE_VALUE}"]', None),
        ("response", "[]", f'{{"text":"{PRIVATE_VALUE}"'),
        ("response", "[]", f'{{"text":"{PRIVATE_VALUE}"}}'),
        ("response", "[]", f'"{PRIVATE_VALUE}"'),
    ],
)
def test_load_agent_session_rejects_invalid_stored_message_fields_without_pii(
    agent_conn: sqlite3.Connection,
    caplog: pytest.LogCaptureFixture,
    field: str,
    files_json: str,
    response_json: str | None,
) -> None:
    session_id = f"resumecorrupt{field}"
    message_id = f"message-corrupt-{field}"
    _insert_stored_message(
        agent_conn,
        session_id=session_id,
        message_id=message_id,
        role="assistant" if field == "response" else "user",
        files_json=files_json,
        response_json=response_json,
    )
    caplog.set_level(logging.ERROR, logger=agent_sessions.__name__)

    with pytest.raises(agent_sessions.AgentSessionDataError) as exc_info:
        agent_sessions.load_agent_session(agent_conn, session_id)

    error = exc_info.value
    assert error.session_id == session_id
    assert error.message_id == message_id
    assert error.field == field
    assert str(error) == "Stored Agent session data is invalid."
    records = [
        record for record in caplog.records if record.name == agent_sessions.__name__
    ]
    assert len(records) == 1
    assert records[0].getMessage() == "Stored Agent message field is invalid."
    assert getattr(records[0], "agent_session_id", None) == session_id
    assert getattr(records[0], "agent_message_id", None) == message_id
    assert getattr(records[0], "agent_message_field", None) == field
    assert PRIVATE_VALUE not in str(error)
    assert PRIVATE_VALUE not in caplog.text


def test_load_agent_session_allows_absent_assistant_response(
    agent_conn: sqlite3.Connection,
) -> None:
    session_id = "resumeplainassistant"
    _insert_stored_message(
        agent_conn,
        session_id=session_id,
        message_id="message-plain-assistant",
        role="assistant",
        response_json=None,
    )

    session = agent_sessions.load_agent_session(agent_conn, session_id)

    assert session.messages[0].response is None


def test_load_agent_session_rejects_checkpoint_with_unknown_boundary(
    agent_conn: sqlite3.Connection,
) -> None:
    session_id = "resumecheckpointmissingboundary"
    message_id = "assistant-checkpoint-missing-boundary"
    response_json = (
        '{"id":"assistant-checkpoint-missing-boundary",'
        '"role":"assistant","text":"Stored response",'
        '"_conversationCheckpoint":{'
        '"throughMessageId":"missing-history-message",'
        '"summary":{"trust":"untrusted_history_data","events":[]}}}'
    )
    _insert_stored_message(
        agent_conn,
        session_id=session_id,
        message_id=message_id,
        role="assistant",
        response_json=response_json,
    )
    with pytest.raises(agent_sessions.AgentSessionDataError) as exc_info:
        agent_sessions.load_agent_session(agent_conn, session_id)

    error = exc_info.value
    assert error.session_id == session_id
    assert error.message_id == message_id
    assert error.field == "conversationCheckpoint"


def test_load_agent_session_rejects_malformed_conversation_checkpoint(
    agent_conn: sqlite3.Connection,
) -> None:
    session_id = "resumemalformedcheckpoint"
    message_id = "assistant-malformed-checkpoint"
    response_json = (
        '{"id":"assistant-malformed-checkpoint",'
        '"role":"assistant","text":"Stored response",'
        '"_conversationCheckpoint":{'
        '"throughMessageId":"history-message",'
        '"summary":{"trust":"untrusted_history_data","events":[]},'
        '"unexpectedField":[]}}'
    )
    _insert_stored_message(
        agent_conn,
        session_id=session_id,
        message_id=message_id,
        role="assistant",
        response_json=response_json,
    )

    with pytest.raises(agent_sessions.AgentSessionDataError) as exc_info:
        agent_sessions.load_agent_session(agent_conn, session_id)

    assert exc_info.value.session_id == session_id
    assert exc_info.value.message_id == message_id
    assert exc_info.value.field == "conversationCheckpoint"


@pytest.mark.parametrize("summary", ["plain text", [], {}])
def test_load_agent_session_rejects_unstructured_checkpoint_summary(
    agent_conn: sqlite3.Connection,
    summary: object,
) -> None:
    session_id = "resumeunstructuredcheckpoint"
    _insert_stored_message(
        agent_conn,
        session_id=session_id,
        message_id="checkpoint-boundary",
        role="user",
    )
    response_json = json.dumps(
        {
            "id": "assistant-unstructured-checkpoint",
            "role": "assistant",
            "text": "Stored response",
            "_conversationCheckpoint": {
                "throughMessageId": "checkpoint-boundary",
                "summary": summary,
            },
        },
    )
    agent_conn.execute(
        """
        INSERT INTO agent_messages (
            id, session_id, role, text, files_json, response_json, sequence
        )
        VALUES (?, ?, 'assistant', '', '[]', ?, 2)
        """,
        ("assistant-unstructured-checkpoint", session_id, response_json),
    )

    with pytest.raises(agent_sessions.AgentSessionDataError) as exc_info:
        agent_sessions.load_agent_session(agent_conn, session_id)

    assert exc_info.value.field == "conversationCheckpoint"


def test_load_agent_session_rejects_regressed_conversation_checkpoint(
    agent_conn: sqlite3.Connection,
) -> None:
    session_id = "resumeregressedcheckpoint"
    _insert_stored_message(
        agent_conn,
        session_id=session_id,
        message_id="checkpoint-boundary-old",
        role="user",
    )

    rows = [
        ("checkpoint-boundary-new", "user", None, 2),
        (
            "assistant-checkpoint-new",
            "assistant",
            json.dumps(
                {
                    "id": "assistant-checkpoint-new",
                    "role": "assistant",
                    "text": "Stored newer checkpoint",
                    "_conversationCheckpoint": {
                        "throughMessageId": "checkpoint-boundary-new",
                        "summary": {
                            "trust": "untrusted_history_data",
                            "events": [],
                        },
                    },
                },
            ),
            3,
        ),
        (
            "assistant-checkpoint-regressed",
            "assistant",
            json.dumps(
                {
                    "id": "assistant-checkpoint-regressed",
                    "role": "assistant",
                    "text": "Stored regressed checkpoint",
                    "_conversationCheckpoint": {
                        "throughMessageId": "checkpoint-boundary-old",
                        "summary": {
                            "trust": "untrusted_history_data",
                            "events": [],
                        },
                    },
                },
            ),
            4,
        ),
    ]
    agent_conn.executemany(
        """
        INSERT INTO agent_messages (
            id, session_id, role, text, files_json, response_json, sequence
        )
        VALUES (?, ?, ?, '', '[]', ?, ?)
        """,
        [
            (message_id, session_id, role, response_json, sequence)
            for message_id, role, response_json, sequence in rows
        ],
    )

    with pytest.raises(agent_sessions.AgentSessionDataError) as exc_info:
        agent_sessions.load_agent_session(agent_conn, session_id)

    error = exc_info.value
    assert error.session_id == session_id
    assert error.message_id == "assistant-checkpoint-regressed"
    assert error.field == "conversationCheckpoint"


def test_replace_agent_session_cannot_delete_existing_corrupt_message(
    agent_conn: sqlite3.Connection,
) -> None:
    session_id = "resumecorruptreplacement"
    message_id = "message-corrupt-replacement"
    corrupt_files = f'["{PRIVATE_VALUE}"'
    _insert_stored_message(
        agent_conn,
        session_id=session_id,
        message_id=message_id,
        role="user",
        files_json=corrupt_files,
    )
    raw_revision = agent_sessions._session_revision(agent_conn, session_id)

    with pytest.raises(agent_sessions.AgentSessionDataError) as exc_info:
        agent_sessions.replace_agent_session_messages(
            agent_conn,
            session_id,
            locale="zh",
            messages=[],
            revision=raw_revision,
        )

    assert exc_info.value.session_id == session_id
    assert exc_info.value.message_id == message_id
    assert exc_info.value.field == "files"
    stored = agent_conn.execute(
        """
        SELECT id, files_json
        FROM agent_messages
        WHERE session_id = ?
        """,
        (session_id,),
    ).fetchall()
    assert [(row["id"], row["files_json"]) for row in stored] == [
        (message_id, corrupt_files),
    ]
