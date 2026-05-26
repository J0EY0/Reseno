import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from sqlite3 import Connection
from typing import Any
from uuid import uuid4

from app.schemas.agent import (
    AgentChatMessage,
    AgentChatRequest,
    AgentSessionResponse,
    AgentStoredMessage,
)

MAX_AGENT_SESSION_MESSAGES = 80
RESUME_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")


@dataclass(frozen=True)
class UserAgentMessage:
    """Normalized user message ready for persistence."""

    id: str
    text: str
    files: list[dict[str, Any]]
    created_at: str


def is_valid_resume_id(resume_id: str) -> bool:
    """Return whether a resume id is safe to use as an Agent DB key."""

    return bool(RESUME_ID_PATTERN.fullmatch(resume_id))


def load_agent_session(conn: Connection, resume_id: str) -> AgentSessionResponse:
    """Load the Agent conversation attached to one resume."""

    rows = conn.execute(
        """
        SELECT id, role, text, files_json, response_json, created_at
        FROM agent_messages
        WHERE session_id = ?
        ORDER BY sequence ASC
        """,
        (resume_id,),
    ).fetchall()

    messages = [
        AgentStoredMessage(
            id=row["id"],
            role=row["role"],
            text=row["text"],
            files=_decode_files(row["files_json"]),
            response=_decode_assistant_response(row["response_json"]),
            createdAt=row["created_at"],
        )
        for row in rows
    ]

    return AgentSessionResponse(resumeId=resume_id, messages=messages)


def append_agent_exchange(
    conn: Connection,
    request: AgentChatRequest,
    assistant_message: AgentChatMessage,
) -> None:
    """Persist the user message and generated assistant response for a resume."""

    if not request.resume_id:
        return

    resume_id = request.resume_id.strip()
    if not is_valid_resume_id(resume_id):
        return

    now = _now_iso()
    user_message = _current_user_message(request, now)

    with conn:
        _upsert_session(conn, request, resume_id, user_message, now)
        next_sequence = _next_message_sequence(conn, resume_id)

        if user_message:
            _insert_message(
                conn,
                session_id=resume_id,
                message_id=user_message.id,
                role="user",
                text=user_message.text,
                files=user_message.files,
                response=None,
                sequence=next_sequence,
                created_at=user_message.created_at,
            )
            next_sequence += 1

        _insert_message(
            conn,
            session_id=resume_id,
            message_id=assistant_message.id,
            role="assistant",
            text=assistant_message.text,
            files=[],
            response=assistant_message,
            sequence=next_sequence,
            created_at=now,
        )
        _trim_session_messages(conn, resume_id)


def _now_iso() -> str:
    """Return a compact UTC timestamp for persisted chat records."""

    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _json_dumps(value: object) -> str:
    """Serialize persisted message fragments without ASCII escaping."""

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _decode_files(raw_value: str) -> list[dict[str, Any]]:
    """Decode the persisted files list while tolerating legacy bad rows."""

    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        return []

    if not isinstance(value, list):
        return []

    return [item for item in value if isinstance(item, dict)]


def _decode_assistant_response(raw_value: str | None) -> AgentChatMessage | None:
    """Decode a stored assistant payload into the public response schema."""

    if not raw_value:
        return None

    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        return None

    if not isinstance(value, dict):
        return None

    try:
        return AgentChatMessage.model_validate(value)
    except ValueError:
        return None


def _current_user_message(
    request: AgentChatRequest,
    created_at: str,
) -> UserAgentMessage | None:
    """Build the persisted user message from the current chat request."""

    if request.message and request.message.text.strip():
        return UserAgentMessage(
            id=request.message.id or f"agent-user-{uuid4().hex[:12]}",
            text=request.message.text.strip(),
            files=request.message.files,
            created_at=request.message.created_at or created_at,
        )

    prompt = request.prompt.strip()
    if not prompt and not request.files:
        return None

    text = prompt or _attachment_summary(request.files)
    return UserAgentMessage(
        id=f"agent-user-{uuid4().hex[:12]}",
        text=text,
        files=request.files,
        created_at=created_at,
    )


def _attachment_summary(files: list[dict[str, Any]]) -> str:
    """Create visible text for a file-only user message."""

    names = [
        str(file.get("filename") or file.get("url") or "Attachment")
        for file in files
        if isinstance(file, dict)
    ]
    return ", ".join(names) or "Attachment"


def _session_title(user_message: UserAgentMessage | None) -> str:
    """Use the first user message as a short session title."""

    if not user_message:
        return ""

    return user_message.text[:80]


def _upsert_session(
    conn: Connection,
    request: AgentChatRequest,
    resume_id: str,
    user_message: UserAgentMessage | None,
    updated_at: str,
) -> None:
    """Create or refresh the parent Agent session row for a resume."""

    conn.execute(
        """
        INSERT INTO agent_sessions (
            id,
            resume_id,
            locale,
            title,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            resume_id = excluded.resume_id,
            locale = excluded.locale,
            updated_at = excluded.updated_at
        """,
        (
            resume_id,
            resume_id,
            request.locale,
            _session_title(user_message),
            updated_at,
            updated_at,
        ),
    )


def _next_message_sequence(conn: Connection, session_id: str) -> int:
    """Return the next append-only sequence number for a session."""

    row = conn.execute(
        """
        SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence
        FROM agent_messages
        WHERE session_id = ?
        """,
        (session_id,),
    ).fetchone()

    return int(row["next_sequence"])


def _insert_message(
    conn: Connection,
    *,
    session_id: str,
    message_id: str,
    role: str,
    text: str,
    files: list[dict[str, Any]],
    response: AgentChatMessage | None,
    sequence: int,
    created_at: str,
) -> None:
    """Insert one message and ignore duplicate ids from client retries."""

    response_json = (
        _json_dumps(response.model_dump(mode="json", by_alias=True))
        if response
        else None
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO agent_messages (
            id,
            session_id,
            role,
            text,
            files_json,
            response_json,
            sequence,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            message_id,
            session_id,
            role,
            text,
            _json_dumps(files),
            response_json,
            sequence,
            created_at,
        ),
    )


def _trim_session_messages(conn: Connection, session_id: str) -> None:
    """Keep recent history bounded so Agent context queries stay quick."""

    conn.execute(
        """
        DELETE FROM agent_messages
        WHERE session_id = ?
          AND id NOT IN (
            SELECT id
            FROM agent_messages
            WHERE session_id = ?
            ORDER BY sequence DESC
            LIMIT ?
          )
        """,
        (session_id, session_id, MAX_AGENT_SESSION_MESSAGES),
    )
