import hashlib
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
    AgentTurnErrorCode,
    AgentTurnExecution,
    AgentTurnExecutionStatus,
)
from app.services.agent.attachments import (
    AgentAttachmentError,
    AgentAttachmentSentReceipt,
    StoredAgentAttachment,
    mark_agent_attachments_sent,
    prevalidate_agent_attachments,
    prune_sent_agent_attachments,
    rollback_agent_attachments_sent,
)
from app.services.llm.config import resolve_agent_llm_config
from app.services.llm.dispatch import supports_native_attachment

RESUME_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UserAgentMessage:
    """Normalized user message ready for persistence."""

    id: str
    text: str
    files: list[dict[str, Any]]
    created_at: str


class AgentSessionRevisionConflictError(RuntimeError):
    """Raised when a client replaces history from a stale session snapshot."""

    def __init__(self, current_revision: str) -> None:
        super().__init__("The Agent session was modified by another client.")
        self.current_revision = current_revision


class AgentSessionTurnConflictError(RuntimeError):
    """Raised when a completed run no longer owns the persisted user turn."""

    def __init__(self, expected_revision: str, current_revision: str) -> None:
        super().__init__(
            "The Agent session changed while the run was active; "
            "the stale assistant response was discarded.",
        )
        self.expected_revision = expected_revision
        self.current_revision = current_revision


class AgentSessionTurnReplayError(RuntimeError):
    """Raised when a client turn id cannot be safely executed again."""

    def __init__(self, current_revision: str) -> None:
        super().__init__(
            "The Agent turn was already completed or its payload changed.",
        )
        self.current_revision = current_revision


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
    # Timestamps are persisted at millisecond precision. SQLite row order keeps
    # rapid retries deterministic when two executions share the same timestamp.
    execution_rows = conn.execute(
        """
        SELECT run_id, turn_id, status, error_code, started_at, completed_at
        FROM agent_turn_executions
        WHERE session_id = ?
        ORDER BY started_at ASC, rowid ASC
        """,
        (resume_id,),
    ).fetchall()
    executions = [
        AgentTurnExecution(
            runId=row["run_id"],
            turnId=row["turn_id"],
            status=row["status"],
            errorCode=row["error_code"],
            startedAt=row["started_at"],
            completedAt=row["completed_at"],
        )
        for row in execution_rows
    ]

    return AgentSessionResponse(
        resumeId=resume_id,
        revision=_session_revision(conn, resume_id),
        messages=messages,
        executions=executions,
    )


def prepare_agent_turn(
    conn: Connection,
    request: AgentChatRequest,
    *,
    run_id: str | None = None,
) -> AgentChatRequest:
    """Accept one user turn and replace client history with authoritative history.

    This is the acceptance boundary for a run. The user message is committed
    before provider work starts, while the history sent to the provider is
    rebuilt from SQLite so stale or forged client conversation entries cannot
    influence the model.
    """

    if not request.resume_id:
        return request

    resume_id = request.resume_id.strip()
    if not is_valid_resume_id(resume_id):
        return request

    now = _now_iso()
    user_message = _current_user_message(request, now)
    if user_message is None:
        return request

    if request.client_turn_id and request.client_turn_id != user_message.id:
        raise AgentSessionTurnReplayError(_session_revision(conn, resume_id))

    _prevalidate_current_turn_attachments(
        conn,
        request,
        resume_id,
        user_message.files,
    )

    receipt: AgentAttachmentSentReceipt | None = None
    try:
        with _transaction(conn):
            current_revision = _session_revision(conn, resume_id)
            existing = _message_by_id(conn, user_message.id)

            if existing is not None:
                if not _is_matching_retry(existing, resume_id, user_message):
                    raise AgentSessionTurnReplayError(current_revision)
                if _has_later_message(conn, resume_id, int(existing["sequence"])):
                    raise AgentSessionTurnReplayError(current_revision)
            else:
                if (
                    request.expected_revision is not None
                    and request.expected_revision != current_revision
                ):
                    raise AgentSessionRevisionConflictError(current_revision)
                # Legacy callers may omit a revision for the first turn only.
                # Once history exists, accepting such a request would re-open
                # the stale-client race this protocol is designed to prevent.
                if request.expected_revision is None and _session_has_messages(
                    conn,
                    resume_id,
                ):
                    raise AgentSessionRevisionConflictError(current_revision)

                _upsert_session(conn, request, resume_id, user_message, now)
                inserted = _insert_message(
                    conn,
                    session_id=resume_id,
                    message_id=user_message.id,
                    role="user",
                    text=user_message.text,
                    files=user_message.files,
                    response=None,
                    sequence=_next_message_sequence(conn, resume_id),
                    created_at=user_message.created_at,
                )
                if not inserted:
                    raise AgentSessionTurnReplayError(current_revision)
                receipt = mark_agent_attachments_sent(
                    resume_id,
                    user_message.files,
                )

            if run_id is not None:
                _insert_agent_turn_execution(
                    conn,
                    run_id=run_id,
                    session_id=resume_id,
                    turn_id=user_message.id,
                    started_at=now,
                )
            authoritative_revision = _session_revision(conn, resume_id)
            authoritative_messages = _load_conversation_items(conn, resume_id)
    except BaseException:
        _compensate_attachment_state(receipt)
        raise

    prepared = request.model_copy(
        update={
            "conversation": authoritative_messages,
            "messages": authoritative_messages,
        },
    )
    object.__setattr__(
        prepared,
        "_persisted_session_revision",
        authoritative_revision,
    )
    object.__setattr__(
        prepared,
        "_persisted_user_message_id",
        user_message.id,
    )
    return prepared


def finish_agent_turn_execution(
    conn: Connection,
    request: AgentChatRequest,
    *,
    run_id: str,
    status: AgentTurnExecutionStatus,
    error_code: AgentTurnErrorCode | None,
) -> None:
    """Persist one terminal execution state without changing message history."""

    if not request.resume_id:
        return

    resume_id = request.resume_id.strip()
    turn_id = getattr(request, "_persisted_user_message_id", None)
    if not is_valid_resume_id(resume_id) or not isinstance(turn_id, str):
        return

    completed_at = _now_iso()
    with _transaction(conn):
        conn.execute(
            """
            UPDATE agent_turn_executions
            SET status = ?, error_code = ?, completed_at = ?, updated_at = ?
            WHERE run_id = ? AND session_id = ? AND turn_id = ?
              AND status = 'running'
            """,
            (
                status,
                error_code,
                completed_at,
                completed_at,
                run_id,
                resume_id,
                turn_id,
            ),
        )


def fail_interrupted_agent_turn_executions(conn: Connection) -> int:
    """Fail executions that cannot survive an application process restart.

    Agent work is process-local. Once startup begins, any database row still
    marked as running has lost its worker and must become retryable instead of
    leaving the conversation permanently stranded.
    """

    completed_at = _now_iso()
    with _transaction(conn):
        cursor = conn.execute(
            """
            UPDATE agent_turn_executions
            SET status = 'failed',
                error_code = 'AGENT_INTERNAL_ERROR',
                completed_at = ?,
                updated_at = ?
            WHERE status = 'running'
            """,
            (completed_at, completed_at),
        )
    return max(cursor.rowcount, 0)


def persist_agent_user_message(
    conn: Connection,
    request: AgentChatRequest,
) -> str | None:
    """Persist the user turn and bind its authoritative revision to the run."""

    persisted_revision = _request_session_revision(request)
    if persisted_revision is not None:
        return persisted_revision

    if not request.resume_id:
        return None

    resume_id = request.resume_id.strip()
    if not is_valid_resume_id(resume_id):
        return None

    now = _now_iso()
    user_message = _current_user_message(request, now)
    if user_message is None:
        return None

    _prevalidate_current_turn_attachments(
        conn,
        request,
        resume_id,
        user_message.files,
    )

    receipt: AgentAttachmentSentReceipt | None = None
    authoritative_revision: str | None = None
    try:
        with _transaction(conn):
            _upsert_session(conn, request, resume_id, user_message, now)
            _insert_message(
                conn,
                session_id=resume_id,
                message_id=user_message.id,
                role="user",
                text=user_message.text,
                files=user_message.files,
                response=None,
                sequence=_next_message_sequence(conn, resume_id),
                created_at=user_message.created_at,
            )
            # SQLite and attachment metadata live in separate stores. Keeping
            # the receipt until commit lets ordinary write/commit failures
            # restore sentAt without introducing a persistent job/outbox.
            receipt = mark_agent_attachments_sent(resume_id, user_message.files)
            authoritative_revision = _session_revision(conn, resume_id)
    except BaseException:
        _compensate_attachment_state(receipt)
        raise

    if authoritative_revision is not None:
        object.__setattr__(
            request,
            "_persisted_session_revision",
            authoritative_revision,
        )
    return authoritative_revision


def append_agent_exchange(
    conn: Connection,
    request: AgentChatRequest,
    assistant_message: AgentChatMessage,
) -> None:
    """Append a successful assistant response without duplicating the user turn."""

    if not request.resume_id:
        return

    resume_id = request.resume_id.strip()
    if not is_valid_resume_id(resume_id):
        return

    expected_revision = persist_agent_user_message(conn, request)
    if expected_revision is None:
        return

    with _transaction(conn):
        current_revision = _session_revision(conn, resume_id)
        if current_revision != expected_revision:
            if _message_exists(conn, resume_id, assistant_message.id):
                return
            raise AgentSessionTurnConflictError(
                expected_revision,
                current_revision,
            )

        now = _now_iso()
        _insert_message(
            conn,
            session_id=resume_id,
            message_id=assistant_message.id,
            role="assistant",
            text=assistant_message.text,
            files=[],
            response=assistant_message,
            sequence=_next_message_sequence(conn, resume_id),
            created_at=now,
        )


def replace_agent_session_messages(
    conn: Connection,
    resume_id: str,
    *,
    locale: str,
    messages: list[AgentConversationItem],
    revision: str | None = None,
) -> AgentSessionResponse:
    """Replace history if the caller still owns the supplied revision."""

    safe_resume_id = resume_id.strip()
    if not safe_resume_id or not is_valid_resume_id(safe_resume_id):
        return AgentSessionResponse(
            resumeId=resume_id,
            revision=_session_revision(conn, resume_id),
            messages=[],
        )

    now = _now_iso()
    normalized_messages = _normalize_replacement_messages(messages)
    retained_files = [
        file
        for message in normalized_messages
        for file in message["files"]
        if isinstance(file, dict)
    ]
    # History replacement does not send bytes to a provider. It still validates
    # the complete retained set before the DB transaction so a broken file
    # cannot leave message history and attachment metadata out of sync.
    prevalidate_agent_attachments(
        safe_resume_id,
        retained_files,
        can_consume_native=lambda _attachment: True,
    )

    receipt: AgentAttachmentSentReceipt | None = None
    try:
        with _transaction(conn):
            current_revision = _session_revision(conn, safe_resume_id)
            if revision is not None and revision != current_revision:
                raise AgentSessionRevisionConflictError(current_revision)

            _upsert_replacement_session(
                conn,
                safe_resume_id,
                locale,
                _replacement_session_title(normalized_messages),
                now,
            )
            conn.execute(
                "DELETE FROM agent_turn_executions WHERE session_id = ?",
                (safe_resume_id,),
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
            receipt = mark_agent_attachments_sent(safe_resume_id, retained_files)
    except BaseException:
        _compensate_attachment_state(receipt)
        raise

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


def _prevalidate_current_turn_attachments(
    conn: Connection,
    request: AgentChatRequest,
    resume_id: str,
    files: list[dict[str, Any]],
) -> None:
    """Prove the whole attachment batch is provider-consumable before commit."""

    if not files:
        return

    config = resolve_agent_llm_config(conn, request.model_config_data)

    def can_consume_native(attachment: StoredAgentAttachment) -> bool:
        if config is None:
            return False
        if attachment.kind == "image":
            return config.supports_image
        return supports_native_attachment(config, attachment.media_type)

    prevalidate_agent_attachments(
        resume_id,
        files,
        can_consume_native=can_consume_native,
    )


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
        try:
            conn.commit()
        except BaseException:
            if conn.in_transaction:
                conn.rollback()
            raise


def _now_iso() -> str:
    """Return a compact UTC timestamp for persisted chat records."""

    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _json_dumps(value: object) -> str:
    """Serialize persisted message fragments without ASCII escaping."""

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _session_revision(conn: Connection, resume_id: str) -> str:
    """Hash authoritative message history into a stable optimistic revision.

    Execution state is deliberately excluded: a background terminal update
    must not make a client holding the same messages appear stale.
    """

    session = conn.execute(
        """
        SELECT locale, title
        FROM agent_sessions
        WHERE id = ?
        """,
        (resume_id,),
    ).fetchone()
    messages = conn.execute(
        """
        SELECT id, role, text, files_json, response_json, sequence, created_at
        FROM agent_messages
        WHERE session_id = ?
        ORDER BY sequence ASC
        """,
        (resume_id,),
    ).fetchall()
    payload = {
        "session": (
            {"locale": session["locale"], "title": session["title"]}
            if session is not None
            else None
        ),
        "messages": [
            {
                "id": row["id"],
                "role": row["role"],
                "text": row["text"],
                "files": row["files_json"],
                "response": row["response_json"],
                "sequence": row["sequence"],
                "createdAt": row["created_at"],
            }
            for row in messages
        ],
    }
    return hashlib.sha256(_json_dumps(payload).encode("utf-8")).hexdigest()


def _load_conversation_items(
    conn: Connection,
    resume_id: str,
) -> list[AgentConversationItem]:
    """Load normalized history for the provider-facing request."""

    rows = conn.execute(
        """
        SELECT id, role, text, files_json, response_json, created_at
        FROM agent_messages
        WHERE session_id = ?
        ORDER BY sequence ASC
        """,
        (resume_id,),
    ).fetchall()
    return [
        AgentConversationItem(
            id=row["id"],
            role=row["role"],
            text=row["text"],
            files=_decode_files(row["files_json"]),
            response=(
                response.model_dump(mode="json", by_alias=True)
                if (response := _decode_assistant_response(row["response_json"]))
                else None
            ),
            createdAt=row["created_at"],
        )
        for row in rows
    ]


def _message_by_id(conn: Connection, message_id: str) -> Any | None:
    """Load a globally unique message id for idempotency validation."""

    return conn.execute(
        """
        SELECT session_id, role, text, files_json, sequence
        FROM agent_messages
        WHERE id = ?
        """,
        (message_id,),
    ).fetchone()


def _is_matching_retry(
    row: Any,
    resume_id: str,
    user_message: UserAgentMessage,
) -> bool:
    """Return whether an existing user row is the exact same client turn."""

    return bool(
        row["session_id"] == resume_id
        and row["role"] == "user"
        and row["text"] == user_message.text
        and _decode_files(row["files_json"]) == user_message.files
    )


def _has_later_message(
    conn: Connection,
    resume_id: str,
    sequence: int,
) -> bool:
    """A completed or superseded turn must never execute a second time."""

    row = conn.execute(
        """
        SELECT 1
        FROM agent_messages
        WHERE session_id = ? AND sequence > ?
        LIMIT 1
        """,
        (resume_id, sequence),
    ).fetchone()
    return row is not None


def _session_has_messages(conn: Connection, resume_id: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM agent_messages
        WHERE session_id = ?
        LIMIT 1
        """,
        (resume_id,),
    ).fetchone()
    return row is not None


def _compensate_attachment_state(
    receipt: AgentAttachmentSentReceipt | None,
) -> None:
    """Restore file metadata when the paired SQLite transaction did not commit."""

    try:
        rollback_agent_attachments_sent(receipt)
    except Exception as exc:
        logger.exception("Failed to compensate Agent attachment metadata.")
        raise AgentAttachmentError(
            "Attachment state could not be restored after a message write failure.",
        ) from exc


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
        message_id = request.message.id or _request_user_message_id(request)
        return UserAgentMessage(
            id=message_id,
            text=request.message.text.strip(),
            files=request.message.files,
            created_at=request.message.created_at or created_at,
        )

    prompt = request.prompt.strip()
    if not prompt and not request.files:
        return None

    text = prompt or _attachment_summary(request.files)
    return UserAgentMessage(
        id=_request_user_message_id(request),
        text=text,
        files=request.files,
        created_at=created_at,
    )


def _request_user_message_id(request: AgentChatRequest) -> str:
    """Keep a generated id stable across start and completion callbacks."""

    existing = getattr(request, "_persisted_user_message_id", None)
    if isinstance(existing, str):
        return existing

    message_id = (
        request.client_turn_id.strip()
        if request.client_turn_id and request.client_turn_id.strip()
        else f"agent-user-{uuid4().hex[:12]}"
    )
    object.__setattr__(request, "_persisted_user_message_id", message_id)
    return message_id


def _request_session_revision(request: AgentChatRequest) -> str | None:
    """Return the user-turn revision captured before provider execution."""

    revision = getattr(request, "_persisted_session_revision", None)
    return revision if isinstance(revision, str) else None


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


def _insert_agent_turn_execution(
    conn: Connection,
    *,
    run_id: str,
    session_id: str,
    turn_id: str,
    started_at: str,
) -> None:
    """Create the running state inside the accepted-user-turn transaction."""

    conn.execute(
        """
        INSERT INTO agent_turn_executions (
            run_id,
            session_id,
            turn_id,
            status,
            error_code,
            started_at,
            completed_at,
            updated_at
        )
        VALUES (?, ?, ?, 'running', NULL, ?, NULL, ?)
        """,
        (run_id, session_id, turn_id, started_at, started_at),
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
) -> bool:
    """Insert one message and ignore duplicate ids from client retries."""

    response_json = (
        _json_dumps(response.model_dump(mode="json", by_alias=True))
        if response
        else None
    )
    cursor = conn.execute(
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
    return cursor.rowcount > 0


def _message_exists(
    conn: Connection,
    session_id: str,
    message_id: str,
) -> bool:
    """Return whether an idempotent completion already reached this session."""

    row = conn.execute(
        """
        SELECT 1
        FROM agent_messages
        WHERE session_id = ? AND id = ?
        """,
        (session_id, message_id),
    ).fetchone()
    return row is not None
