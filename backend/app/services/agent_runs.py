from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import AsyncIterator
from contextlib import closing
from dataclasses import dataclass, field
from typing import Final
from uuid import uuid4

from app.db.connection import connect
from app.schemas.agent import AgentChatRequest, AgentRunResponse, AgentRunStatus
from app.services.agent.runtime.context import AgentRuntimeContext
from app.services.agent.runtime.streaming import async_stream_agent_response
from app.services.agent_sessions import append_agent_exchange

MAX_RETAINED_AGENT_RUNS: Final = 24


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

    def response(self) -> AgentRunResponse:
        return AgentRunResponse(
            id=self.id,
            resumeId=self.resume_id,
            baseResume=self.request.resume,
            status=self.status,
            lastEventId=self.next_sequence - 1,
        )


class AgentRunManager:
    """Own background Agent runs independently from HTTP stream subscribers.

    Runs intentionally remain process-local: reconnects survive browser/network
    interruption, while a backend restart aborts unfinished work without a
    durable queue or partial draft persistence.
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

            run = AgentRun(
                id=f"agent-run-{uuid4().hex[:16]}",
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
            async with run.condition:
                pending = [event for event in run.events if event.sequence > cursor]
                if not pending and run.status != "active":
                    return
                if not pending:
                    await run.condition.wait()
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
                    run.has_error = run.has_error or event_name == "error"
                    await self._publish(run, frame)

            if run.cancel_event.is_set() and not run.has_terminal_message:
                await self._rollback_provisional_edits(run)
                final_status = "cancelled"
            elif run.has_error or run.has_provisional_edits:
                # A normal completion must resolve every provisional edit with
                # an explicit commit or rollback. Provider failures can still
                # emit a user-facing message_done, so that event alone is not a
                # valid transaction commit signal.
                await self._rollback_provisional_edits(run)
                final_status = "failed"
            else:
                final_status = "completed"
        except asyncio.CancelledError:
            run.cancel_event.set()
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
            await self._rollback_provisional_edits(run)
            final_status = "failed"
        finally:
            await self._publish_terminal(
                run,
                final_status,
            )
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
            run.events.append(
                BufferedAgentEvent(
                    sequence=sequence,
                    frame=_with_event_id(frame, sequence),
                ),
            )
            run.condition.notify_all()

    async def _publish_terminal(
        self,
        run: AgentRun,
        status: AgentRunStatus,
    ) -> None:
        """Publish the terminal cursor and status as one observable state change."""

        frame = _sse_frame(
            "run_done",
            {"type": "run_done", "runId": run.id, "status": status},
        )
        async with run.condition:
            sequence = run.next_sequence
            run.next_sequence += 1
            run.events.append(
                BufferedAgentEvent(
                    sequence=sequence,
                    frame=_with_event_id(frame, sequence),
                ),
            )
            run.status = status
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


def _sse_frame(event_name: str, payload: dict[str, object]) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event_name}\ndata: {data}\n\n"
