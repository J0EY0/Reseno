from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from collections.abc import AsyncIterator
from contextlib import closing
from dataclasses import dataclass, field
from typing import Final
from uuid import uuid4

from app.db.connection import connect
from app.schemas.agent import (
    AgentChatRequest,
    AgentRunResponse,
    AgentRunStatus,
    AgentTurnErrorCode,
    AgentTurnExecutionStatus,
)
from app.services.agent.runtime.context import AgentRuntimeContext
from app.services.agent.runtime.streaming import async_stream_agent_response
from app.services.agent_sessions import (
    append_agent_exchange,
    finish_agent_turn_execution,
    prepare_agent_turn,
)

logger = logging.getLogger(__name__)

MAX_RETAINED_AGENT_RUNS: Final = 24
MAX_BUFFERED_AGENT_EVENTS: Final = 512
MAX_BUFFERED_AGENT_EVENT_BYTES: Final = 4 * 1024 * 1024
AGENT_SSE_HEARTBEAT_SECONDS: Final = 12.0


class AgentRunConflictError(Exception):
    """Raised when a resume already has an active Agent run."""


class AgentRunNotFoundError(Exception):
    """Raised when a requested in-process run no longer exists."""


@dataclass(frozen=True)
class BufferedAgentEvent:
    sequence: int
    frame: str


@dataclass
class AgentRun:
    id: str
    request: AgentChatRequest
    resume_id: str | None
    status: AgentRunStatus = "active"
    events: list[BufferedAgentEvent] = field(default_factory=list)
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None
    next_sequence: int = 1
    has_provisional_edits: bool = False
    has_terminal_message: bool = False
    has_error: bool = False
    execution_state: AgentTurnExecutionStatus = "running"
    error_code: AgentTurnErrorCode | None = None
    buffered_event_bytes: int = 0
    replay_message: dict[str, object] = field(default_factory=dict)

    def response(self) -> AgentRunResponse:
        return AgentRunResponse(
            id=self.id,
            resumeId=self.resume_id,
            baseResume=self.request.resume,
            status=self.status,
            executionState=self.execution_state,
            errorCode=self.error_code,
            lastEventId=self.next_sequence - 1,
        )


class AgentRunManager:
    """Own background Agent runs independently from HTTP stream subscribers.

    Work and replay events intentionally remain process-local; only the turn
    lifecycle is durable. Reconnects survive browser/network interruption,
    while a backend restart still aborts work without a durable queue.
    """

    def __init__(self) -> None:
        self._runs: dict[str, AgentRun] = {}
        self._active_by_resume: dict[str, str] = {}
        self._completed_order: deque[str] = deque()
        self._lock = asyncio.Lock()

    async def start(self, request: AgentChatRequest) -> AgentRun:
        resume_id = request.resume_id.strip() if request.resume_id else None
        async with self._lock:
            if resume_id:
                active_id = self._active_by_resume.get(resume_id)
                active_run = self._runs.get(active_id or "")
                if active_run and active_run.status == "active":
                    raise AgentRunConflictError

            # Run reservation and user-turn acceptance share this lock. This
            # prevents a losing concurrent request from persisting a message
            # before it discovers another run already owns the resume.
            run_id = f"agent-run-{uuid4().hex[:16]}"
            with closing(connect()) as conn:
                request = prepare_agent_turn(conn, request, run_id=run_id)

            run = AgentRun(
                id=run_id,
                request=request,
                resume_id=resume_id,
            )
            self._runs[run.id] = run
            if resume_id:
                self._active_by_resume[resume_id] = run.id
            run.task = asyncio.create_task(
                self._execute(run),
                name=f"agent-run:{run.id}",
            )
            return run

    async def get(self, run_id: str) -> AgentRun:
        async with self._lock:
            run = self._runs.get(run_id)
        if run is None:
            raise AgentRunNotFoundError
        return run

    async def active_for_resume(self, resume_id: str) -> AgentRun | None:
        async with self._lock:
            run_id = self._active_by_resume.get(resume_id)
            run = self._runs.get(run_id or "")
            if run and run.status == "active":
                return run
        return None

    async def stop(self, run_id: str) -> AgentRun:
        run = await self.get(run_id)
        if run.status == "active":
            run.cancel_event.set()
            # Cancel the task as well as setting the cooperative flag. A model
            # stream may be blocked waiting for its next network chunk and
            # would otherwise not reach a runtime checkpoint promptly. Deferring
            # cancellation by one loop turn lets a newly-created task enter its
            # cleanup boundary before it can be interrupted.
            if run.task is not None:
                asyncio.get_running_loop().call_soon(run.task.cancel)
        return run

    async def subscribe(
        self,
        run_id: str,
        *,
        after: int = 0,
    ) -> AsyncIterator[str]:
        run = await self.get(run_id)
        cursor = max(after, 0)
        while True:
            emit_heartbeat = False
            async with run.condition:
                pending = [event for event in run.events if event.sequence > cursor]
                if not pending and run.status != "active":
                    return
                if not pending:
                    try:
                        await asyncio.wait_for(
                            run.condition.wait(),
                            timeout=AGENT_SSE_HEARTBEAT_SECONDS,
                        )
                    except TimeoutError:
                        emit_heartbeat = run.status == "active"
                    else:
                        continue

            if emit_heartbeat:
                # Comments keep idle transports alive without entering the
                # sequenced replay protocol or changing Last-Event-ID.
                yield ": ping\n\n"
                continue

            for event in pending:
                cursor = event.sequence
                yield event.frame

    async def shutdown(self) -> None:
        async with self._lock:
            active = [run for run in self._runs.values() if run.status == "active"]
        for run in active:
            run.cancel_event.set()
            if run.task is not None:
                asyncio.get_running_loop().call_soon(run.task.cancel)
        tasks = [run.task for run in active if run.task is not None]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute(self, run: AgentRun) -> None:
        async def is_cancelled() -> bool:
            return run.cancel_event.is_set()

        runtime = AgentRuntimeContext(is_aborted=is_cancelled)
        final_status: AgentRunStatus = "failed"
        try:
            with closing(connect()) as conn:
                iterator = async_stream_agent_response(
                    run.request,
                    conn,
                    lambda message: append_agent_exchange(conn, run.request, message),
                    runtime,
                )
                async for frame in iterator:
                    event_name = _event_name(frame)
                    transaction_state = _transaction_state(frame)
                    if transaction_state == "provisional":
                        run.has_provisional_edits = True
                    elif transaction_state in {"committed", "rolled_back"}:
                        run.has_provisional_edits = False
                    run.has_terminal_message = (
                        run.has_terminal_message or event_name == "message_done"
                    )
                    if event_name == "error":
                        run.has_error = True
                        run.error_code = run.error_code or _provider_error_code(frame)
                    await self._publish(run, frame)

            if run.cancel_event.is_set() and not run.has_terminal_message:
                await self._rollback_provisional_edits(run)
                run.error_code = "AGENT_RUN_CANCELLED"
                final_status = "cancelled"
            elif run.has_error or run.has_provisional_edits:
                # A normal completion must resolve every provisional edit with
                # an explicit commit or rollback. Provider failures can still
                # emit a user-facing message_done, so that event alone is not a
                # valid transaction commit signal.
                if run.error_code is None:
                    run.error_code = (
                        "AGENT_EDIT_TRANSACTION_INCOMPLETE"
                        if run.has_provisional_edits
                        else "AGENT_PROVIDER_ERROR"
                    )
                await self._rollback_provisional_edits(run)
                final_status = "failed"
            else:
                final_status = "completed"
        except asyncio.CancelledError:
            run.cancel_event.set()
            run.error_code = "AGENT_RUN_CANCELLED"
            await self._rollback_provisional_edits(run)
            final_status = "cancelled"
        except Exception:
            # Provider details are already normalized by the streaming layer.
            # This fallback prevents implementation details escaping from an
            # unexpected background-task failure.
            await self._publish(
                run,
                _sse_frame(
                    "error",
                    {"type": "error", "error": "Agent request failed."},
                ),
            )
            run.error_code = "AGENT_INTERNAL_ERROR"
            await self._rollback_provisional_edits(run)
            final_status = "failed"
        finally:
            try:
                await self._publish_terminal(
                    run,
                    final_status,
                )
            finally:
                # Never retain an in-memory reservation if terminal
                # persistence or publication fails unexpectedly.
                await self._release(run)

    async def _rollback_provisional_edits(self, run: AgentRun) -> None:
        """Resolve an unfinished transaction before publishing run_done."""

        if run.has_provisional_edits:
            await self._publish(
                run,
                _sse_frame(
                    "edits",
                    {
                        "type": "edits",
                        "message": {
                            "edits": [],
                            "transactionState": "rolled_back",
                        },
                    },
                ),
            )
            run.has_provisional_edits = False

    async def _publish(self, run: AgentRun, frame: str) -> None:
        async with run.condition:
            sequence = run.next_sequence
            run.next_sequence += 1
            buffered_event = BufferedAgentEvent(
                sequence=sequence,
                frame=_with_event_id(frame, sequence),
            )
            _merge_replay_message(run.replay_message, frame)
            run.events.append(buffered_event)
            run.buffered_event_bytes += _frame_size(buffered_event.frame)
            _compact_replay_buffer(run, sequence)
            run.condition.notify_all()

    async def _publish_terminal(
        self,
        run: AgentRun,
        status: AgentRunStatus,
    ) -> None:
        """Publish the terminal cursor and status as one observable state change."""

        execution_state = _execution_state(status)
        error_code = None if execution_state == "succeeded" else run.error_code
        try:
            # Commit the durable terminal state before exposing run_done. A client
            # that refreshes after that event must never observe the turn as running.
            with closing(connect()) as conn:
                finish_agent_turn_execution(
                    conn,
                    run.request,
                    run_id=run.id,
                    status=execution_state,
                    error_code=error_code,
                )
        except Exception:
            logger.exception("Failed to persist terminal Agent run %s", run.id)
            # Persistence failure must not strand the process-local run as active.
            # Publish a failed terminal event so subscribers and the resume lock
            # converge even though the durable execution could not be finalized.
            status = "failed"
            execution_state = "failed"
            error_code = "AGENT_INTERNAL_ERROR"
            run.has_error = True

        frame = _sse_frame(
            "run_done",
            {
                "type": "run_done",
                "runId": run.id,
                "status": status,
                "executionState": execution_state,
                "errorCode": error_code,
            },
        )
        async with run.condition:
            sequence = run.next_sequence
            run.next_sequence += 1
            terminal_event = BufferedAgentEvent(
                sequence=sequence,
                frame=_with_event_id(frame, sequence),
            )
            run.events.append(terminal_event)
            run.buffered_event_bytes += _frame_size(terminal_event.frame)
            run.status = status
            run.execution_state = execution_state
            run.error_code = error_code
            _compact_terminal_replay_buffer(run, terminal_event)
            run.condition.notify_all()

    async def _release(self, run: AgentRun) -> None:
        async with self._lock:
            if run.resume_id and self._active_by_resume.get(run.resume_id) == run.id:
                self._active_by_resume.pop(run.resume_id, None)
            self._completed_order.append(run.id)
            while len(self._completed_order) > MAX_RETAINED_AGENT_RUNS:
                expired_id = self._completed_order.popleft()
                self._runs.pop(expired_id, None)


def _with_event_id(frame: str, sequence: int) -> str:
    """Add a replay cursor without changing the existing event-first format."""

    lines = frame.rstrip("\r\n").splitlines()
    if lines and lines[0].startswith("event:"):
        lines.insert(1, f"id: {sequence}")
    else:
        lines.insert(0, f"id: {sequence}")
    return "\n".join(lines) + "\n\n"


def _frame_size(frame: str) -> int:
    return len(frame.encode("utf-8"))


def _event_payload(frame: str) -> tuple[str, dict[str, object]]:
    """Return the event name and JSON object carried by one SSE frame."""

    event_name = _event_name(frame)
    data_lines = [
        line.removeprefix("data:").strip()
        for line in frame.splitlines()
        if line.startswith("data:")
    ]
    if not data_lines:
        return event_name, {}

    try:
        payload = json.loads("\n".join(data_lines))
    except json.JSONDecodeError:
        return event_name, {}
    return event_name, payload if isinstance(payload, dict) else {}


def _merge_replay_tool(
    message: dict[str, object],
    incoming: dict[str, object],
) -> None:
    """Merge one tool event by id so a compacted replay keeps terminal state."""

    tool_id = incoming.get("id")
    if not isinstance(tool_id, str) or not tool_id:
        return

    tools = message.get("tools")
    current_tools = (
        [tool for tool in tools if isinstance(tool, dict)]
        if isinstance(tools, list)
        else []
    )
    for index, current in enumerate(current_tools):
        if current.get("id") == tool_id:
            current_tools[index] = {**current, **incoming}
            message["tools"] = current_tools
            return

    current_tools.append(incoming)
    message["tools"] = current_tools


def _merge_replay_message(
    message: dict[str, object],
    frame: str,
) -> None:
    """Fold incremental SSE events into one authoritative replay snapshot.

    A reconnecting subscriber either already owns events before its cursor or
    starts at zero. Replacing a long prefix with an absolute message snapshot
    is therefore lossless for both cases and avoids retaining every token delta.
    """

    event_name, payload = _event_payload(frame)
    patch = payload.get("message")
    if isinstance(patch, dict):
        message.update(patch)

    if event_name == "text_delta":
        delta = payload.get("delta")
        if isinstance(delta, str):
            message["text"] = f"{message.get('text', '')}{delta}"
    elif event_name == "reasoning_delta":
        delta = payload.get("delta")
        if isinstance(delta, str):
            message["reasoning"] = f"{message.get('reasoning', '')}{delta}"
    elif event_name in {"tool_start", "tool_delta", "tool_done"}:
        tool = payload.get("tool")
        if isinstance(tool, dict):
            _merge_replay_tool(message, tool)
    elif event_name == "error" and not message.get("text"):
        error_text = payload.get("message") or payload.get("error")
        if isinstance(error_text, str):
            message["text"] = error_text

    message.setdefault("role", "assistant")
    message.setdefault("text", "")


def _replay_snapshot_event(run: AgentRun, sequence: int) -> BufferedAgentEvent:
    event_name = "message_done" if run.has_terminal_message else "message_delta"
    frame = _sse_frame(
        event_name,
        {
            "type": event_name,
            "message": run.replay_message,
        },
    )
    return BufferedAgentEvent(
        sequence=sequence,
        frame=_with_event_id(frame, sequence),
    )


def _replay_buffer_exceeded(run: AgentRun) -> bool:
    return (
        len(run.events) > MAX_BUFFERED_AGENT_EVENTS
        or run.buffered_event_bytes > MAX_BUFFERED_AGENT_EVENT_BYTES
    )


def _compact_replay_buffer(run: AgentRun, sequence: int) -> None:
    """Replace a long active-run prefix with one absolute message snapshot."""

    if not _replay_buffer_exceeded(run):
        return

    snapshot = _replay_snapshot_event(run, sequence)
    run.events = [snapshot]
    run.buffered_event_bytes = _frame_size(snapshot.frame)


def _compact_terminal_replay_buffer(
    run: AgentRun,
    terminal_event: BufferedAgentEvent,
) -> None:
    """Bound completed-run replay while retaining both message and run status."""

    if not _replay_buffer_exceeded(run):
        return

    snapshot_sequence = max(terminal_event.sequence - 1, 1)
    snapshot = _replay_snapshot_event(run, snapshot_sequence)
    run.events = [snapshot, terminal_event]
    run.buffered_event_bytes = _frame_size(snapshot.frame) + _frame_size(
        terminal_event.frame,
    )


def _transaction_state(frame: str) -> str:
    for line in frame.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            payload = json.loads(line.removeprefix("data:").strip())
        except json.JSONDecodeError:
            return ""
        message = payload.get("message") if isinstance(payload, dict) else None
        if isinstance(message, dict):
            return str(message.get("transactionState") or "")
    return ""


def _event_name(frame: str) -> str:
    first_line = frame.splitlines()[0] if frame else ""
    return first_line.removeprefix("event:").strip()


def _provider_error_code(frame: str) -> AgentTurnErrorCode:
    """Classify a public provider error without persisting its free-form text."""

    _, payload = _event_payload(frame)
    explicit_code = payload.get("errorCode")
    if explicit_code == "AGENT_PROVIDER_AUTH_ERROR":
        return "AGENT_PROVIDER_AUTH_ERROR"
    if explicit_code == "AGENT_PROVIDER_ERROR":
        return "AGENT_PROVIDER_ERROR"

    error_text = payload.get("error") or payload.get("message")
    normalized = error_text.casefold() if isinstance(error_text, str) else ""
    if any(
        marker in normalized
        for marker in ("http 401", "http 403", "unauthorized", "forbidden")
    ):
        return "AGENT_PROVIDER_AUTH_ERROR"
    return "AGENT_PROVIDER_ERROR"


def _execution_state(status: AgentRunStatus) -> AgentTurnExecutionStatus:
    if status == "completed":
        return "succeeded"
    if status == "cancelled":
        return "cancelled"
    return "failed"


def _sse_frame(event_name: str, payload: dict[str, object]) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event_name}\ndata: {data}\n\n"
