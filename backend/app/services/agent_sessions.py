import hashlib
import json
import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from sqlite3 import Connection
from typing import Any, Literal, NoReturn
from uuid import uuid4

from app.schemas.agent import (
    AgentChatMessage,
    AgentChatRequest,
    AgentCommittedDraft,
    AgentConversationItem,
    AgentDraftDecisionStatus,
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
    prepare_agent_history_attachments,
    prevalidate_agent_attachments,
    prune_sent_agent_attachments,
    rollback_agent_attachments_sent,
)
from app.services.agent.request_context import active_resume
from app.services.agent.resume_owner import require_active_resume
from app.services.llm.config import resolve_agent_llm_config
from app.services.llm.dispatch import supports_native_attachment

RESUME_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
logger = logging.getLogger(__name__)
AgentStoredMessageField = Literal["files", "response"]


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


class AgentSessionActiveRunConflictError(RuntimeError):
    """Raised when history replacement would invalidate a running turn."""

    def __init__(self, current_revision: str, run_id: str) -> None:
        super().__init__("The Agent session has an active run.")
        self.current_revision = current_revision
        self.run_id = run_id


class AgentSessionTurnConflictError(RuntimeError):
    """Raised when a completed run no longer owns the persisted user turn."""

    def __init__(self, expected_revision: str, current_revision: str) -> None:
        super().__init__(
            "The Agent session changed while the run was active; "
            "the stale assistant response was discarded.",
        )
        self.expected_revision = expected_revision
        self.current_revision = current_revision


class AgentSessionPersistenceError(RuntimeError):
    """Raised when a durable turn transition no longer owns its database row."""


class AgentSessionDataError(RuntimeError):
    """Raised when a stored message field cannot be decoded safely."""

    def __init__(
        self,
        session_id: str,
        message_id: str,
        field: AgentStoredMessageField,
    ) -> None:
        super().__init__("Stored Agent session data is invalid.")
        self.session_id = session_id
        self.message_id = message_id
        self.field = field


class AgentSessionTurnReplayError(RuntimeError):
    """Raised when a message id cannot be safely accepted into session history."""

    def __init__(self, current_revision: str) -> None:
        super().__init__(
            "The Agent turn was already completed or its payload changed.",
        )
        self.current_revision = current_revision


class AgentDraftDecisionConflictError(RuntimeError):
    """Raised when a committed draft already has the opposite decision."""

    def __init__(self, current_revision: str, current_status: str) -> None:
        super().__init__("The committed Agent draft was already resolved.")
        self.current_revision = current_revision
        self.current_status = current_status


class AgentDraftUnavailableConflictError(RuntimeError):
    """Raised when the current session no longer contains the target draft."""

    def __init__(self, current_revision: str) -> None:
        super().__init__("The committed Agent draft is unavailable.")
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
            files=_decode_files(
                row["files_json"],
                session_id=resume_id,
                message_id=str(row["id"]),
            ),
            response=_decode_assistant_response(
                row["response_json"],
                session_id=resume_id,
                message_id=str(row["id"]),
            ),
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

    _prevalidate_current_turn_attachments(
        conn,
        request,
        resume_id,
        user_message.files,
    )

    receipt: AgentAttachmentSentReceipt | None = None
    try:
        with _transaction(conn):
            require_active_resume(conn, resume_id)
            current_revision = _session_revision(conn, resume_id)
            existing = _message_by_id(conn, user_message.id)

            if existing is not None:
                if not _is_matching_retry(existing, resume_id, user_message):
                    raise AgentSessionTurnReplayError(current_revision)
                if _has_later_message(conn, resume_id, int(existing["sequence"])):
                    raise AgentSessionTurnReplayError(current_revision)
            else:
                if request.expected_revision != current_revision:
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
            # `message` is the singular current turn. Provider history must be
            # authoritative, prior-only state even though the turn is already
            # durable before provider work starts.
            authoritative_messages = [
                message
                for message in _load_conversation_items(conn, resume_id)
                if message.id != user_message.id
            ]
    except BaseException:
        _compensate_attachment_state(receipt)
        raise

    prepared = request.model_copy(update={"messages": authoritative_messages})
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
        cursor = conn.execute(
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
        if cursor.rowcount != 1:
            raise AgentSessionPersistenceError(
                "The running Agent execution no longer owns its durable row.",
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
            require_active_resume(conn, resume_id)
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
        require_active_resume(conn, resume_id)
        current_revision = _session_revision(conn, resume_id)
        if current_revision != expected_revision:
            if _message_exists(conn, resume_id, assistant_message.id):
                return
            raise AgentSessionTurnConflictError(
                expected_revision,
                current_revision,
            )

        persisted_message = _attach_committed_draft(request, assistant_message)
        now = _now_iso()
        _insert_message(
            conn,
            session_id=resume_id,
            message_id=persisted_message.id,
            role="assistant",
            text=persisted_message.text,
            files=[],
            response=persisted_message,
            sequence=_next_message_sequence(conn, resume_id),
            created_at=now,
        )


def _attach_committed_draft(
    request: AgentChatRequest,
    message: AgentChatMessage,
) -> AgentChatMessage:
    """Bind the immutable edit base to a committed response before storage."""

    if message.transaction_state != "committed" or not message.edits:
        return message

    # Store the same snapshot tools edited so the next turn cannot restart
    # from the pre-draft request.resume.
    return message.model_copy(
        update={"draft": AgentCommittedDraft(baseResume=active_resume(request))},
    )


def update_agent_draft_decision(
    conn: Connection,
    resume_id: str,
    *,
    message_id: str,
    status: AgentDraftDecisionStatus,
    revision: str,
) -> AgentSessionResponse:
    """Atomically resolve one committed draft without replacing its session."""

    with _transaction(conn):
        require_active_resume(conn, resume_id)
        current_revision = _session_revision(conn, resume_id)
        # CAS ownership is session-wide. Check it before resolving the target,
        # which may already have been removed by a concurrent replacement.
        if revision != current_revision:
            raise AgentSessionRevisionConflictError(current_revision)

        row = conn.execute(
            """
            SELECT response_json
            FROM agent_messages
            WHERE session_id = ? AND id = ? AND role = 'assistant'
            """,
            (resume_id, message_id),
        ).fetchone()
        response = (
            _decode_assistant_response(
                row["response_json"],
                session_id=resume_id,
                message_id=message_id,
            )
            if row is not None
            else None
        )
        if response is None or response.draft is None:
            raise AgentDraftUnavailableConflictError(current_revision)
        if response.draft.status == status:
            return load_agent_session(conn, resume_id)

        running_execution = conn.execute(
            """
            SELECT run_id
            FROM agent_turn_executions
            WHERE session_id = ? AND status = 'running'
            ORDER BY started_at ASC, rowid ASC
            LIMIT 1
            """,
            (resume_id,),
        ).fetchone()
        if running_execution is not None:
            raise AgentSessionActiveRunConflictError(
                current_revision,
                str(running_execution["run_id"]),
            )

        if response.draft.status != "pending":
            raise AgentDraftDecisionConflictError(
                current_revision,
                response.draft.status,
            )

        updated_response = response.model_copy(
            update={
                "draft": response.draft.model_copy(update={"status": status}),
            },
        )
        cursor = conn.execute(
            """
            UPDATE agent_messages
            SET response_json = ?
            WHERE session_id = ? AND id = ? AND role = 'assistant'
            """,
            (
                _json_dumps(
                    updated_response.model_dump(mode="json", by_alias=True),
                ),
                resume_id,
                message_id,
            ),
        )
        if cursor.rowcount != 1:
            raise AgentSessionPersistenceError(
                "The committed Agent draft response could not be updated.",
            )

    return load_agent_session(conn, resume_id)


def replace_agent_session_messages(
    conn: Connection,
    resume_id: str,
    *,
    locale: str,
    messages: list[AgentConversationItem],
    revision: str,
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
    receipt: AgentAttachmentSentReceipt | None = None
    try:
        with _transaction(conn):
            require_active_resume(conn, safe_resume_id)
            current_revision = _session_revision(conn, safe_resume_id)
            if revision != current_revision:
                raise AgentSessionRevisionConflictError(current_revision)

            # A matching raw revision proves ownership, not that persisted JSON
            # is usable. Decode the current session before any destructive DB
            # write or external attachment-state transition.
            load_agent_session(conn, safe_resume_id)

            running_execution = conn.execute(
                """
                SELECT run_id
                FROM agent_turn_executions
                WHERE session_id = ? AND status = 'running'
                ORDER BY started_at ASC, rowid ASC
                LIMIT 1
                """,
                (safe_resume_id,),
            ).fetchone()
            if running_execution is not None:
                raise AgentSessionActiveRunConflictError(
                    current_revision,
                    str(running_execution["run_id"]),
                )

            # History persistence only verifies that retained references still
            # resolve. Provider-bound request quotas do not apply here.
            prepare_agent_history_attachments(safe_resume_id, retained_files)

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
                inserted = _insert_message(
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
                if not inserted:
                    # Message ids are globally unique. Never commit a partial
                    # replacement when another session already owns one.
                    raise AgentSessionTurnReplayError(current_revision)
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
            files=_decode_files(
                row["files_json"],
                session_id=resume_id,
                message_id=str(row["id"]),
            ),
            response=(
                response.model_dump(mode="json", by_alias=True)
                if (
                    response := _decode_assistant_response(
                        row["response_json"],
                        session_id=resume_id,
                        message_id=str(row["id"]),
                    )
                )
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
        and _decode_files(
            row["files_json"],
            session_id=resume_id,
            message_id=user_message.id,
        )
        == user_message.files
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


def _raise_invalid_stored_message_field(
    *,
    session_id: str,
    message_id: str,
    field: AgentStoredMessageField,
) -> NoReturn:
    """Report corruption using identifiers only, never stored field contents."""

    logger.error(
        "Stored Agent message field is invalid.",
        extra={
            "agent_session_id": session_id,
            "agent_message_id": message_id,
            "agent_message_field": field,
        },
    )
    raise AgentSessionDataError(session_id, message_id, field) from None


def _decode_files(
    raw_value: str,
    *,
    session_id: str,
    message_id: str,
) -> list[dict[str, Any]]:
    """Decode a complete persisted files list or fail visibly."""

    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        _raise_invalid_stored_message_field(
            session_id=session_id,
            message_id=message_id,
            field="files",
        )

    if not isinstance(value, list):
        _raise_invalid_stored_message_field(
            session_id=session_id,
            message_id=message_id,
            field="files",
        )

    files: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            _raise_invalid_stored_message_field(
                session_id=session_id,
                message_id=message_id,
                field="files",
            )
        files.append(item)
    return files


def _decode_assistant_response(
    raw_value: str | None,
    *,
    session_id: str,
    message_id: str,
) -> AgentChatMessage | None:
    """Decode a stored assistant payload into the public response schema."""

    if raw_value is None:
        return None

    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        _raise_invalid_stored_message_field(
            session_id=session_id,
            message_id=message_id,
            field="response",
        )

    if not isinstance(value, dict):
        _raise_invalid_stored_message_field(
            session_id=session_id,
            message_id=message_id,
            field="response",
        )

    try:
        return AgentChatMessage.model_validate(value)
    except ValueError:
        _raise_invalid_stored_message_field(
            session_id=session_id,
            message_id=message_id,
            field="response",
        )


def _current_user_message(
    request: AgentChatRequest,
    created_at: str,
) -> UserAgentMessage:
    """Build the persisted turn from the validated canonical message."""

    assert request.message.id is not None
    return UserAgentMessage(
        id=request.message.id,
        text=request.message.text.strip(),
        files=request.message.files,
        created_at=request.message.created_at or created_at,
    )


def _request_session_revision(request: AgentChatRequest) -> str | None:
    """Return the user-turn revision captured before provider execution."""

    revision = getattr(request, "_persisted_session_revision", None)
    return revision if isinstance(revision, str) else None


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
