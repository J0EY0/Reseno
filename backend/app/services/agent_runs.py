from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from collections.abc import AsyncIterator
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import monotonic
from typing import Final
from uuid import uuid4

from app.db.connection import connect
from app.schemas.agent import (
    AgentChatMessage,
    AgentChatRequest,
    AgentRunResponse,
    AgentRunStatus,
    AgentTurnErrorCode,
    AgentTurnExecutionStatus,
)
from app.services.agent.draft import DraftTransaction
from app.services.agent.runtime.context import AgentRuntimeContext
from app.services.agent.runtime.streaming import async_stream_agent_response
from app.services.agent_sessions import (
    append_agent_exchange,
    finish_agent_turn_execution,
    prepare_agent_turn,
)
from app.services.llm import LlmUsage

logger = logging.getLogger("uvicorn.error")

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
            baseResume=DraftTransaction.from_request(self.request).base_resume,
            status=self.status,
            executionState=self.execution_state,
            errorCode=self.error_code,
            lastEventId=self.next_sequence - 1,
        )


@dataclass
class _AgentRunMetrics:
    run_started_monotonic: float = field(default_factory=monotonic, repr=False)
    model_attempts: int = 0
    model_responses: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cached_input_tokens: int | None = None
    cache_write_input_tokens: int | None = None
    reasoning_tokens: int | None = None
    first_event_elapsed_ms: int | None = None
    _model_started_monotonic: float | None = field(default=None, repr=False)
    _model_elapsed_seconds: float = field(default=0.0, repr=False)
    _tool_intervals_by_name: dict[str, list[tuple[float, float]]] = field(
        default_factory=dict,
        repr=False,
    )
    _observed_tool_ids: set[str] = field(default_factory=set, repr=False)

    def record_model_attempt(self) -> None:
        self.model_attempts += 1
        if self._model_started_monotonic is None:
            self._model_started_monotonic = monotonic()

    def record_model_response(
        self,
        usage: LlmUsage | None,
        _stop_reason: object,
    ) -> None:
        self.model_responses += 1
        self.finish_model_timing()
        if usage is None:
            return
        self.input_tokens = _add_optional_usage(
            self.input_tokens,
            usage.input_tokens,
        )
        self.output_tokens = _add_optional_usage(
            self.output_tokens,
            usage.output_tokens,
        )
        self.total_tokens = _add_optional_usage(
            self.total_tokens,
            usage.total_tokens,
        )
        self.cached_input_tokens = _add_optional_usage(
            self.cached_input_tokens,
            usage.cached_input_tokens,
        )
        self.cache_write_input_tokens = _add_optional_usage(
            self.cache_write_input_tokens,
            usage.cache_write_input_tokens,
        )
        self.reasoning_tokens = _add_optional_usage(
            self.reasoning_tokens,
            usage.reasoning_tokens,
        )

    def finish_model_timing(self) -> None:
        """Close one model interval, including retries before its response."""

        if self._model_started_monotonic is None:
            return
        self._model_elapsed_seconds += monotonic() - self._model_started_monotonic
        self._model_started_monotonic = None

    def record_tool_loop_event(self, event: object) -> None:
        """Observe timings only; never inspect tool input or output payloads."""

        if (
            self.first_event_elapsed_ms is None
            and getattr(event, "kind", None) != "done"
        ):
            self.first_event_elapsed_ms = round(
                (monotonic() - self.run_started_monotonic) * 1000,
            )

        tools = getattr(event, "tools", None)
        if not isinstance(tools, list):
            return
        for tool in tools:
            tool_id = getattr(tool, "id", None)
            name = getattr(tool, "title", None)
            started_at = _timestamp_seconds(getattr(tool, "started_at", None))
            completed_at = _timestamp_seconds(getattr(tool, "completed_at", None))
            if (
                not isinstance(tool_id, str)
                or not tool_id
                or tool_id in self._observed_tool_ids
                or not isinstance(name, str)
                or not name
                or started_at is None
                or completed_at is None
                or completed_at < started_at
            ):
                continue
            self._observed_tool_ids.add(tool_id)
            self._tool_intervals_by_name.setdefault(name, []).append(
                (started_at, completed_at),
            )

    @property
    def model_elapsed_ms(self) -> int:
        return round(self._model_elapsed_seconds * 1000)

    @property
    def tool_elapsed_ms(self) -> int:
        return _merged_interval_ms(
            [
                interval
                for intervals in self._tool_intervals_by_name.values()
                for interval in intervals
            ],
        )

    @property
    def tool_elapsed_ms_by_name(self) -> dict[str, int]:
        return {
            name: _merged_interval_ms(intervals)
            for name, intervals in sorted(self._tool_intervals_by_name.items())
        }

    @property
    def tool_calls_by_name(self) -> dict[str, int]:
        return {
            name: len(intervals)
            for name, intervals in sorted(self._tool_intervals_by_name.items())
        }


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
        started_monotonic = monotonic()
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
                started_monotonic=started_monotonic,
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
            if run.task is not None and (
                self._shutting_down
                or (not run.has_terminal_message and not run.terminalizing)
            ):
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

        metrics = _AgentRunMetrics(run_started_monotonic=run.started_monotonic)
        runtime = AgentRuntimeContext(
            is_aborted=is_cancelled,
            on_llm_attempt=metrics.record_model_attempt,
            on_llm_response=metrics.record_model_response,
            on_tool_loop_event=metrics.record_tool_loop_event,
        )
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
            # A failed/cancelled provider turn has no response callback. Close
            # its interval before terminal persistence so it is not counted as
            # model latency.
            metrics.finish_model_timing()
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
                        "Agent run summary %s",
                        json.dumps(
                            {
                                "event": "agent_run_finished",
                                "run_id": run.id,
                                "resume_id": run.resume_id,
                                "status": run.status,
                                "error_code": run.error_code,
                                "duration_ms": round(
                                    (monotonic() - run.started_monotonic) * 1000,
                                ),
                                "first_event_elapsed_ms": (
                                    metrics.first_event_elapsed_ms
                                ),
                                "model_elapsed_ms": metrics.model_elapsed_ms,
                                "model_attempts": metrics.model_attempts,
                                "model_responses": metrics.model_responses,
                                "input_tokens": metrics.input_tokens,
                                "output_tokens": metrics.output_tokens,
                                "total_tokens": metrics.total_tokens,
                                "cached_input_tokens": metrics.cached_input_tokens,
                                "cache_write_input_tokens": (
                                    metrics.cache_write_input_tokens
                                ),
                                "reasoning_tokens": metrics.reasoning_tokens,
                                "tool_calls_by_name": metrics.tool_calls_by_name,
                                "tool_elapsed_ms": metrics.tool_elapsed_ms,
                                "tool_elapsed_ms_by_name": (
                                    metrics.tool_elapsed_ms_by_name
                                ),
                                "tools": _replay_tool_states(run.replay_message),
                            },
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
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
        cancelled_message = (
            _cancelled_replay_message(run)
            if status == "cancelled" and not run.has_terminal_message
            else None
        )
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
                        cancelled_message,
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

        if cancelled_message is not None:
            run.has_terminal_message = True
            await self._publish(
                run,
                _sse_frame(
                    "message_done",
                    {
                        "type": "message_done",
                        "message": cancelled_message.model_dump(
                            mode="json",
                            by_alias=True,
                        ),
                    },
                ),
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
    assistant_message: AgentChatMessage | None,
) -> None:
    """Persist one terminal transition on its own worker connection."""

    with closing(connect()) as conn:
        finish_agent_turn_execution(
            conn,
            request,
            run_id=run_id,
            status=status,
            error_code=error_code,
            assistant_message=assistant_message,
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


def _add_optional_usage(current: int | None, value: int | None) -> int | None:
    if value is None:
        return current
    return (current or 0) + value


def _timestamp_seconds(value: object) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _merged_interval_ms(intervals: list[tuple[float, float]]) -> int:
    """Return wall time covered by intervals without double-counting overlap."""

    if not intervals:
        return 0

    ordered = sorted(intervals)
    current_start, current_end = ordered[0]
    elapsed_seconds = 0.0
    for started_at, completed_at in ordered[1:]:
        if started_at > current_end:
            elapsed_seconds += current_end - current_start
            current_start, current_end = started_at, completed_at
        else:
            current_end = max(current_end, completed_at)
    elapsed_seconds += current_end - current_start
    return round(elapsed_seconds * 1000)


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


def _append_replay_timeline_text(
    message: dict[str, object],
    part_id: object,
    delta: str,
) -> None:
    if not isinstance(part_id, str) or not part_id:
        return

    timeline = message.get("timeline")
    parts = (
        [part for part in timeline if isinstance(part, dict)]
        if isinstance(timeline, list)
        else []
    )
    if parts and parts[-1].get("id") == part_id:
        current_text = parts[-1].get("text")
        prefix = current_text if isinstance(current_text, str) else ""
        parts[-1]["text"] = f"{prefix}{delta}"
    else:
        parts.append(
            {
                "id": part_id,
                "type": "text",
                "text": delta,
                "toolIds": [],
            },
        )
    message["timeline"] = parts


def _append_replay_timeline_tool(
    message: dict[str, object],
    part_id: object,
    tool_id: object,
) -> None:
    if (
        not isinstance(part_id, str)
        or not part_id
        or not isinstance(tool_id, str)
        or not tool_id
    ):
        return

    timeline = message.get("timeline")
    parts = (
        [part for part in timeline if isinstance(part, dict)]
        if isinstance(timeline, list)
        else []
    )
    if parts and parts[-1].get("id") == part_id:
        raw_tool_ids = parts[-1].get("toolIds")
        tool_ids = (
            [value for value in raw_tool_ids if isinstance(value, str)]
            if isinstance(raw_tool_ids, list)
            else []
        )
        if tool_id not in tool_ids:
            parts[-1]["toolIds"] = [*tool_ids, tool_id]
    else:
        parts.append(
            {
                "id": part_id,
                "type": "tool_group",
                "text": "",
                "toolIds": [tool_id],
            },
        )
    message["timeline"] = parts


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
            _append_replay_timeline_text(
                message,
                payload.get("timelinePartId"),
                delta,
            )
    elif event_name in {"tool_start", "tool_delta", "tool_done"}:
        tool = payload.get("tool")
        if isinstance(tool, dict):
            _merge_replay_tool(message, tool)
            _append_replay_timeline_tool(
                message,
                payload.get("timelinePartId"),
                tool.get("id"),
            )
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


def _cancelled_replay_message(run: AgentRun) -> AgentChatMessage | None:
    """Return the visible, non-actionable assistant snapshot for a stopped run."""

    text = run.replay_message.get("text")
    message_id = run.replay_message.get("id")
    if (
        not isinstance(text, str)
        or not text.strip()
        or not isinstance(message_id, str)
        or not message_id.strip()
    ):
        return None

    payload = dict(run.replay_message)
    tools = payload.get("tools")
    if isinstance(tools, list):
        completed_at = datetime.now(UTC).isoformat()
        payload["tools"] = [
            {
                **tool,
                "state": "output-error",
                "errorText": "Cancelled.",
                "completedAt": completed_at,
            }
            if isinstance(tool, dict)
            and tool.get("state")
            in {
                "approval-requested",
                "approval-responded",
                "input-available",
                "input-streaming",
            }
            else tool
            for tool in tools
        ]
    payload.update(
        {
            "draft": None,
            "edits": [],
        },
    )
    return AgentChatMessage.model_validate(payload)


def _event_name(frame: str) -> str:
    first_line = frame.splitlines()[0] if frame else ""
    return first_line.removeprefix("event:").strip()


def _provider_error_code(frame: str) -> AgentTurnErrorCode:
    """Classify a public provider error without persisting its free-form text."""

    _, payload = _event_payload(frame)
    explicit_code = payload.get("errorCode")
    if explicit_code == "AGENT_INTERNAL_ERROR":
        return "AGENT_INTERNAL_ERROR"
    if explicit_code == "AGENT_PROVIDER_AUTH_ERROR":
        return "AGENT_PROVIDER_AUTH_ERROR"
    if explicit_code == "AGENT_PROVIDER_TIMEOUT":
        return "AGENT_PROVIDER_TIMEOUT"
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
