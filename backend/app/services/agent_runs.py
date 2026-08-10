from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from collections.abc import AsyncIterator
from contextlib import closing
from dataclasses import dataclass, field
from time import monotonic
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
from app.services.agent.request_context import active_resume
from app.services.agent.runtime.context import AgentRuntimeContext
from app.services.agent.runtime.streaming import async_stream_agent_response
from app.services.agent_sessions import (
    append_agent_exchange,
    finish_agent_turn_execution,
    prepare_agent_turn,
)

logger = logging.getLogger(__name__)

MAX_RETAINED_AGENT_RUNS: Final = 24
MAX_ACTIVE_AGENT_RUNS: Final = 4
MAX_BUFFERED_AGENT_EVENTS: Final = 512
MAX_BUFFERED_AGENT_EVENT_BYTES: Final = 4 * 1024 * 1024
AGENT_SSE_HEARTBEAT_SECONDS: Final = 12.0
AGENT_TERMINAL_RETRY_INITIAL_SECONDS: Final = 0.25
AGENT_TERMINAL_RETRY_MAX_SECONDS: Final = 5.0


class AgentRunConflictError(Exception):
    """Raised when a resume already has an active Agent run."""


class AgentRunCapacityError(Exception):
    """Raised when this process is already running its Agent work budget."""


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
    terminalizing: bool = False
    started_monotonic: float = field(default_factory=monotonic, repr=False)

    def response(self) -> AgentRunResponse:
        return AgentRunResponse(
            id=self.id,
            resumeId=self.resume_id,
            baseResume=active_resume(self.request),
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
        # Reservations cover both request preparation and provider work. This
        # keeps expensive preparation off the event loop without reopening the
        # same-resume or global admission races.
        self._reserved_run_ids: set[str] = set()
        self._completed_order: deque[str] = deque()
        self._lock = asyncio.Lock()
        self._shutting_down = False

    async def start(self, request: AgentChatRequest) -> AgentRun:
        resume_id = request.resume_id.strip() if request.resume_id else None
        run_id = f"agent-run-{uuid4().hex[:16]}"
        async with self._lock:
            if resume_id and resume_id in self._active_by_resume:
                raise AgentRunConflictError
            if len(self._reserved_run_ids) >= MAX_ACTIVE_AGENT_RUNS:
                raise AgentRunCapacityError

            self._reserved_run_ids.add(run_id)
            if resume_id:
                self._active_by_resume[resume_id] = run_id

        cancelled_error: asyncio.CancelledError | None = None
        preparation_task = asyncio.create_task(
            asyncio.to_thread(_prepare_run_request, request, run_id),
            name=f"agent-run-prepare:{run_id}",
        )
        try:
            # Cancellation must not abandon a worker that may already have
            # accepted the user turn. Finish preparation, register the run,
            # then propagate cancellation to the HTTP caller.
            while True:
                try:
                    request = await asyncio.shield(preparation_task)
                    break
                except asyncio.CancelledError as exc:
                    if preparation_task.cancelled():
                        raise
                    cancelled_error = cancelled_error or exc

            run = AgentRun(
                id=run_id,
                request=request,
                resume_id=resume_id,
            )
            async with self._lock:
                self._runs[run.id] = run
                run.task = asyncio.create_task(
                    self._execute(run),
                    name=f"agent-run:{run.id}",
                )
            logger.info(
                "Accepted Agent run run_id=%s resume_id=%s",
                run.id,
                run.resume_id or "-",
            )
        except BaseException:
            async with self._lock:
                self._reserved_run_ids.discard(run_id)
                if resume_id and self._active_by_resume.get(resume_id) == run_id:
                    self._active_by_resume.pop(resume_id, None)
            raise

        if cancelled_error is not None:
            raise cancelled_error
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

    async def purge_resume(self, resume_id: str) -> None:
        """Forget replay state owned by a permanently deleted resume."""

        async with self._lock:
            purge_ids = {
                run_id
                for run_id, run in self._runs.items()
                if run.resume_id == resume_id
            }
            self._purge_runs_unlocked(purge_ids)

    async def purge_missing_resume_runs(self) -> None:
        """Forget runs whose resume rows were deleted in one batch."""

        async with self._lock:
            candidate_ids = {
                run.resume_id
                for run in self._runs.values()
                if run.resume_id is not None
            }
        if not candidate_ids:
            return

        existing_ids = await asyncio.to_thread(
            _existing_resume_ids,
            tuple(candidate_ids),
        )
        missing_ids = candidate_ids - existing_ids
        if not missing_ids:
            return

        async with self._lock:
            purge_ids = {
                run_id
                for run_id, run in self._runs.items()
                if run.resume_id in missing_ids
            }
            self._purge_runs_unlocked(purge_ids)

    async def stop(self, run_id: str) -> AgentRun:
        run = await self.get(run_id)
        if run.status == "active":
            run.cancel_event.set()
            # Provider work may need task cancellation to unblock promptly.
            # Durable terminalization is different: a user stop must not turn
            # its retry into a running DB ghost.
            if run.task is not None and (self._shutting_down or not run.terminalizing):
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
            self._shutting_down = True
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
            logger.exception("Unexpected failure in Agent run %s", run.id)
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
            terminal_published = False
            try:
                await self._publish_terminal(
                    run,
                    final_status,
                )
                terminal_published = True
            finally:
                if terminal_published:
                    await self._release(run)
                    logger.info(
                        "Finished Agent run run_id=%s resume_id=%s status=%s "
                        "error_code=%s duration_ms=%d tools=%s",
                        run.id,
                        run.resume_id or "-",
                        run.status,
                        run.error_code or "-",
                        round((monotonic() - run.started_monotonic) * 1000),
                        _replay_tool_states(run.replay_message),
                    )

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

        run.terminalizing = True
        execution_state = _execution_state(status)
        error_code = None if execution_state == "succeeded" else run.error_code
        retry_delay = AGENT_TERMINAL_RETRY_INITIAL_SECONDS
        failed_attempts = 0
        while True:
            try:
                # Commit durable state before exposing run_done. Every retry
                # uses a fresh connection and the exact run/session/turn CAS.
                # SQLite work stays off the ASGI event loop.
                persistence_task = asyncio.create_task(
                    asyncio.to_thread(
                        _finish_agent_run_execution,
                        run.request,
                        run.id,
                        execution_state,
                        error_code,
                    ),
                )
                try:
                    await asyncio.shield(persistence_task)
                except asyncio.CancelledError:
                    if self._shutting_down:
                        raise
                    # A stop cancellation may already be queued as provider
                    # work ends. Do not abandon the in-flight durable barrier.
                    await persistence_task
                break
            except Exception:
                failed_attempts += 1
                status = "failed"
                execution_state = "failed"
                error_code = "AGENT_INTERNAL_ERROR"
                run.has_error = True
                if failed_attempts == 1:
                    logger.exception("Failed to persist terminal Agent run %s", run.id)
                elif failed_attempts & (failed_attempts - 1) == 0:
                    logger.warning(
                        "Terminal Agent run persistence is still unavailable "
                        "run_id=%s attempts=%d retry_seconds=%.2f",
                        run.id,
                        failed_attempts,
                        retry_delay,
                    )
                await asyncio.sleep(retry_delay)
                retry_delay = min(
                    retry_delay * 2,
                    AGENT_TERMINAL_RETRY_MAX_SECONDS,
                )

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
            run.terminalizing = False
            _compact_terminal_replay_buffer(run, terminal_event)
            run.condition.notify_all()

    async def _release(self, run: AgentRun) -> None:
        async with self._lock:
            self._reserved_run_ids.discard(run.id)
            if run.resume_id and self._active_by_resume.get(run.resume_id) == run.id:
                self._active_by_resume.pop(run.resume_id, None)
            if self._runs.get(run.id) is not run:
                return
            self._completed_order.append(run.id)
            while len(self._completed_order) > MAX_RETAINED_AGENT_RUNS:
                expired_id = self._completed_order.popleft()
                self._runs.pop(expired_id, None)

    def _purge_runs_unlocked(self, run_ids: set[str]) -> None:
        """Drop process-local run state while ``_lock`` is held."""

        if not run_ids:
            return
        for run_id in run_ids:
            run = self._runs.pop(run_id, None)
            self._reserved_run_ids.discard(run_id)
            if (
                run is not None
                and run.resume_id
                and self._active_by_resume.get(run.resume_id) == run_id
            ):
                self._active_by_resume.pop(run.resume_id, None)
        self._completed_order = deque(
            run_id for run_id in self._completed_order if run_id not in run_ids
        )


def _existing_resume_ids(resume_ids: tuple[str, ...]) -> set[str]:
    """Resolve retained resume owners off the event loop."""

    existing_ids: set[str] = set()
    with closing(connect()) as conn:
        for resume_id in resume_ids:
            row = conn.execute(
                "SELECT 1 FROM resumes WHERE id = ?",
                (resume_id,),
            ).fetchone()
            if row is not None:
                existing_ids.add(resume_id)
    return existing_ids


def _prepare_run_request(
    request: AgentChatRequest,
    run_id: str,
) -> AgentChatRequest:
    """Accept one turn on a worker so SQLite and parsing never block asyncio."""

    with closing(connect()) as conn:
        return prepare_agent_turn(conn, request, run_id=run_id)


def _finish_agent_run_execution(
    request: AgentChatRequest,
    run_id: str,
    status: AgentTurnExecutionStatus,
    error_code: AgentTurnErrorCode | None,
) -> None:
    """Persist one terminal transition on its own worker connection."""

    with closing(connect()) as conn:
        finish_agent_turn_execution(
            conn,
            request,
            run_id=run_id,
            status=status,
            error_code=error_code,
        )


def _replay_tool_states(message: dict[str, object]) -> str:
    """Summarize tool outcomes without logging tool input or output payloads."""

    tools = message.get("tools")
    if not isinstance(tools, list):
        return "-"

    outcomes = [
        f"{tool.get('type', 'tool')}:{tool.get('state', 'unknown')}"
        for tool in tools
        if isinstance(tool, dict)
    ]
    return ",".join(outcomes) or "-"


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
