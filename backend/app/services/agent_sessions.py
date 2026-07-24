import json
import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from sqlite3 import Connection
from typing import Any
from uuid import uuid4

from app.schemas.agent import (
    AgentChatMessage,
    AgentChatRequest,
    AgentConversationItem,
    AgentSessionResponse,
    AgentStoredMessage,
)
from app.services.agent.attachments import (
    mark_agent_attachments_sent,
    prune_sent_agent_attachments,
)

RESUME_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
logger = logging.getLogger(__name__)


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

    with _transaction(conn):
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
        if user_message:
            # Protect originals before committing their message references.
            # A metadata write failure therefore rolls back the SQLite turn
            # instead of leaving history that cleanup may later invalidate.
            mark_agent_attachments_sent(resume_id, user_message.files)


def replace_agent_session_messages(
    conn: Connection,
    resume_id: str,
    *,
    locale: str,
    messages: list[AgentConversationItem],
) -> AgentSessionResponse:
    """Replace persisted messages for a resume Agent session."""

    safe_resume_id = resume_id.strip()
    if not safe_resume_id or not is_valid_resume_id(safe_resume_id):
        return AgentSessionResponse(resumeId=resume_id, messages=[])

    now = _now_iso()
    normalized_messages = _normalize_replacement_messages(messages)
    retained_files = [
        file
        for message in normalized_messages
        for file in message["files"]
        if isinstance(file, dict)
    ]

    with _transaction(conn):
        _upsert_replacement_session(
            conn,
            safe_resume_id,
            locale,
            _replacement_session_title(normalized_messages),
            now,
        )
        conn.execute(
            "DELETE FROM agent_messages WHERE session_id = ?",
            (safe_resume_id,),
        )

        for sequence, message in enumerate(normalized_messages, start=1):
            _insert_message(
                conn,
                session_id=safe_resume_id,
                message_id=message["id"],
                role=message["role"],
                text=message["text"],
                files=message["files"],
                response=message["response"],
                sequence=sequence,
                created_at=message["created_at"] or now,
            )
        mark_agent_attachments_sent(safe_resume_id, retained_files)

    # Pruning is post-commit garbage collection. It must not turn a completed
    # replacement into an API failure after the new history is authoritative.
    try:
        prune_sent_agent_attachments(safe_resume_id, retained_files)
    except OSError:
        logger.warning(
            "Failed to prune unreferenced Agent attachments for session %s.",
            safe_resume_id,
            exc_info=True,
        )
    return load_agent_session(conn, safe_resume_id)


@contextmanager
def _transaction(conn: Connection) -> Iterator[None]:
    """Make a group of writes atomic on the project's autocommit connection.

    Connections intentionally use ``isolation_level=None``, so ``with conn``
    does not start a transaction. A savepoint keeps this helper safe if a
    caller already owns a wider transaction.
    """

    if conn.in_transaction:
        savepoint = f"agent_session_{uuid4().hex}"
        conn.execute(f"SAVEPOINT {savepoint}")
        try:
            yield
        except BaseException:
            conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            raise
        else:
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        return

    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()


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

    if request.message and (request.message.text.strip() or request.message.files):
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


def _replacement_session_title(
    messages: list[dict[str, Any]],
) -> str:
    """Use the first replacement user message as the session title."""

    for message in messages:
        if message["role"] == "user":
            return str(message["text"])[:80]

    return ""


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


def _upsert_replacement_session(
    conn: Connection,
    resume_id: str,
    locale: str,
    title: str,
    updated_at: str,
) -> None:
    """Create or refresh a session row while replacing its messages."""

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
            title = excluded.title,
            updated_at = excluded.updated_at
        """,
        (
            resume_id,
            resume_id,
            locale,
            title,
            updated_at,
            updated_at,
        ),
    )


def _normalize_replacement_messages(
    messages: list[AgentConversationItem],
) -> list[dict[str, Any]]:
    """Normalize client-supplied messages before storing them."""

    normalized: list[dict[str, Any]] = []
    used_ids: set[str] = set()

    for message in messages:
        text = message.text.strip()
        files = [file for file in message.files if isinstance(file, dict)]

        if not text and not files and not message.response:
            continue

        raw_id = (message.id or "").strip()
        message_id = (
            raw_id
            if raw_id and raw_id not in used_ids
            else f"agent-{message.role}-{uuid4().hex[:12]}"
        )
        used_ids.add(message_id)

        normalized.append(
            {
                "id": message_id,
                "role": message.role,
                "text": text,
                "files": files,
                "response": _replacement_assistant_response(
                    message_id,
                    text,
                    message.response,
                )
                if message.role == "assistant"
                else None,
                "created_at": message.created_at,
            },
        )

    return normalized


def _replacement_assistant_response(
    message_id: str,
    text: str,
    response: dict[str, Any] | None,
) -> AgentChatMessage:
    """Build a valid assistant payload from replacement history."""

    payload = response if isinstance(response, dict) else {}
    fallback_text = text or str(payload.get("text") or "")
    response_id = payload.get("id")

    try:
        return AgentChatMessage.model_validate(
            {
                **payload,
                "id": response_id if isinstance(response_id, str) else message_id,
                "role": "assistant",
                "text": fallback_text,
            },
        )
    except ValueError:
        return AgentChatMessage(
            id=message_id,
            role="assistant",
            text=fallback_text,
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
