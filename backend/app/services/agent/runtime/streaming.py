import json
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from app.schemas.agent import (
    AgentChatMessage,
    AgentChatRequest,
    AgentTimelinePart,
    AgentTransactionState,
    AgentTurnErrorCode,
)
from app.services.llm import (
    AgentLlmConfig,
    LlmRequestError,
    LlmTimeoutError,
)

from ..localization import agent_text
from .context import (
    AgentContextWindowError,
    AgentRunAborted,
    AgentRuntimeContext,
)
from .loop import (
    AgentModelTurnLimitError,
    AgentToolLoopCompleted,
    AgentToolLoopEdits,
    AgentToolLoopTerminalText,
    AgentToolLoopTextDelta,
    AgentToolLoopTools,
    AgentTurnResult,
    async_iter_agent_tool_call_loop,
)


@dataclass(frozen=True)
class AgentMessageStarted:
    message: dict[str, object]


@dataclass(frozen=True)
class AgentTextDelta:
    delta: str
    timeline_part_id: str


@dataclass(frozen=True)
class AgentToolUpdate:
    kind: Literal["tool_start", "tool_delta", "tool_done"]
    tool: dict[str, object]
    timeline_part_id: str


@dataclass(frozen=True)
class AgentEditsUpdate:
    edits: list[dict[str, object]]
    transaction_state: AgentTransactionState


@dataclass(frozen=True)
class AgentStreamError:
    message: str
    error_code: AgentTurnErrorCode


@dataclass(frozen=True)
class AgentCompleted:
    """A visible terminal message plus whether it belongs in durable history."""

    message: AgentChatMessage
    persist: bool


type AgentRuntimeEvent = (
    AgentMessageStarted
    | AgentTextDelta
    | AgentToolUpdate
    | AgentEditsUpdate
    | AgentStreamError
    | AgentCompleted
)


def _merge_llm_response(
    draft: AgentChatMessage,
    raw_text: str,
) -> AgentChatMessage:
    """Merge real model text with deterministic executable draft operations."""

    return draft.model_copy(
        update={
            "text": raw_text,
        },
    )


def _direct_llm_response(
    raw_text: str,
    *,
    message_id: str | None = None,
) -> AgentChatMessage:
    """Return a plain assistant response with no tool-call metadata."""

    return AgentChatMessage(
        id=message_id or f"agent-msg-{uuid4().hex[:12]}",
        role="assistant",
        tone="default",
        text=raw_text,
        tools=[],
        sources=[],
        edits=[],
    )


def _model_setup_message(request: AgentChatRequest) -> AgentChatMessage:
    """Build a direct setup guide when no usable model config exists."""

    text = agent_text(request.locale, "model.setup.text")

    return AgentChatMessage(
        id=f"agent-msg-{uuid4().hex[:12]}",
        role="assistant",
        tone="default",
        text=text,
        tools=[],
        sources=[],
        edits=[],
    )


def _model_error_message(
    request: AgentChatRequest,
    config: AgentLlmConfig,
    error: LlmRequestError,
) -> AgentChatMessage:
    """Build a provider failure message without falling back to mock output."""

    detail = _llm_error_detail(error)
    text = agent_text(
        request.locale,
        "model.error.text",
        name=config.name,
    )
    if detail:
        label = agent_text(request.locale, "model.error.label")
        text = f"{text}\n\n{label}: {detail}"

    return AgentChatMessage(
        id=f"agent-msg-{uuid4().hex[:12]}",
        role="assistant",
        tone="default",
        text=text,
        tools=[],
        sources=[],
        edits=[],
    )


def _llm_error_detail(error: LlmRequestError) -> str:
    """Return a stable error without exposing provider-controlled text."""

    if isinstance(error, AgentContextWindowError):
        return str(error)
    if isinstance(error, AgentModelTurnLimitError):
        return "Agent model turn limit reached."
    if isinstance(error.status_code, int):
        return f"Model provider returned HTTP {error.status_code}."

    detail = str(error).casefold()
    if "timed out" in detail:
        return "Model provider request timed out."
    if "empty response" in detail or "empty stream" in detail:
        return "Model provider returned an empty response."
    if "invalid json" in detail or "unsupported response" in detail:
        return "Model provider returned an invalid response."
    return "Model provider request failed."


def _llm_error_code(error: LlmRequestError) -> AgentTurnErrorCode:
    """Return the durable public classification for one provider failure."""

    if isinstance(error, (AgentContextWindowError, AgentModelTurnLimitError)):
        return "AGENT_INTERNAL_ERROR"
    if error.status_code in {401, 403}:
        return "AGENT_PROVIDER_AUTH_ERROR"
    if isinstance(error, LlmTimeoutError):
        return "AGENT_PROVIDER_TIMEOUT"
    return "AGENT_PROVIDER_ERROR"


def serialize_agent_event(event: AgentRuntimeEvent) -> str:
    """Serialize one internal runtime event into the stable public SSE shape."""

    event_name, payload = agent_event_payload(event)
    return serialize_sse_event(event_name, payload)


def serialize_sse_event(event_name: str, payload: dict[str, object]) -> str:
    """Serialize one server-sent event frame."""

    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event_name}\ndata: {data}\n\n"


def agent_event_payload(event: AgentRuntimeEvent) -> tuple[str, dict[str, object]]:
    """Project a typed runtime event into the public wire contract."""

    if isinstance(event, AgentMessageStarted):
        return "message_start", {"type": "message_start", "message": event.message}
    if isinstance(event, AgentTextDelta):
        return "text_delta", {
            "type": "text_delta",
            "delta": event.delta,
            "timelinePartId": event.timeline_part_id,
        }
    if isinstance(event, AgentToolUpdate):
        return event.kind, {
            "type": event.kind,
            "tool": event.tool,
            "timelinePartId": event.timeline_part_id,
        }
    if isinstance(event, AgentEditsUpdate):
        return "edits", {
            "type": "edits",
            "message": {
                "edits": event.edits,
                "transactionState": event.transaction_state,
            },
        }
    if isinstance(event, AgentStreamError):
        return "error", {
            "type": "error",
            "error": event.message,
            "errorCode": event.error_code,
        }
    return "message_done", {
        "type": "message_done",
        "message": event.message.model_dump(mode="json", by_alias=True),
    }


def _timeline_text_part(part_id: str, text: str) -> AgentTimelinePart:
    """Return one text timeline part."""

    return AgentTimelinePart(id=part_id, type="text", text=text, toolIds=[])


def _timeline_tool_part(part_id: str, tool_ids: list[str]) -> AgentTimelinePart:
    """Return one tool timeline part."""

    return AgentTimelinePart(
        id=part_id,
        type="tool_group",
        text="",
        toolIds=tool_ids,
    )


def _append_timeline_delta(
    parts: list[AgentTimelinePart],
    text_chunks: dict[str, list[str]],
    delta: str,
) -> str:
    """Append one model delta at the current stream position."""

    if not delta:
        return ""

    if parts and parts[-1].type == "text":
        part_id = parts[-1].id
    else:
        part_id = f"timeline-text-{len(parts) + 1}"
        parts.append(_timeline_text_part(part_id, ""))

    text_chunks.setdefault(part_id, []).append(delta)
    return part_id


def _materialize_timeline_text(
    parts: list[AgentTimelinePart],
    text_chunks: dict[str, list[str]],
) -> list[AgentTimelinePart]:
    """Join streamed text once when building the terminal snapshot."""

    return [
        part.model_copy(update={"text": "".join(text_chunks.get(part.id, []))})
        if part.type == "text"
        else part
        for part in parts
    ]


def _append_timeline_tools(
    parts: list[AgentTimelinePart],
    tool_ids: list[str],
) -> str:
    """Append tools at the current stream position."""

    if not tool_ids:
        return ""

    if parts and parts[-1].type == "tool_group":
        parts[-1].tool_ids.extend(tool_ids)
        return parts[-1].id

    tool_group_count = sum(1 for part in parts if part.type == "tool_group")
    part_id = f"timeline-tool-{tool_group_count + 1}"
    parts.append(_timeline_tool_part(part_id, tool_ids))
    return part_id


def stream_agent_message(
    message: AgentChatMessage,
) -> Iterator[AgentRuntimeEvent]:
    """Yield a direct response through the same typed runtime protocol."""

    text = message.text

    yield AgentMessageStarted(
        message={
            "id": message.id,
            "role": message.role,
            "tone": message.tone,
            "text": "",
        },
    )

    chunk_size = 24
    for index in range(0, len(text), chunk_size):
        yield AgentTextDelta(
            delta=text[index : index + chunk_size],
            timeline_part_id="timeline-text-1",
        )

    yield AgentCompleted(message=message, persist=True)


async def async_iter_agent_events(
    request: AgentChatRequest,
    resolved_config: AgentLlmConfig | None,
    runtime: AgentRuntimeContext | None = None,
) -> AsyncIterator[AgentRuntimeEvent]:
    """Run one accepted turn against its immutable model configuration.

    Resolution belongs to the acceptance seam. Keeping this function free of
    database lookups guarantees that every model/tool iteration observes the
    same provider, context window, thinking mode, and request limits.
    """

    runtime = runtime or AgentRuntimeContext()
    if resolved_config is None:
        message = _model_setup_message(request)
        for event in stream_agent_message(message):
            yield event
        return

    async for event in async_iter_resolved_agent_events(
        request,
        resolved_config,
        runtime=runtime,
    ):
        yield event


async def async_iter_resolved_agent_events(
    request: AgentChatRequest,
    config: AgentLlmConfig,
    runtime: AgentRuntimeContext | None = None,
) -> AsyncIterator[AgentRuntimeEvent]:
    """Project one model/tool loop into typed runtime events."""

    runtime = runtime or AgentRuntimeContext()
    message_id = f"agent-msg-{uuid4().hex[:12]}"

    yield AgentMessageStarted(
        message={
            "id": message_id,
            "role": "assistant",
            "tone": "default",
            "text": "",
        },
    )

    timeline_parts: list[AgentTimelinePart] = []
    timeline_text_chunks: dict[str, list[str]] = {}
    tool_part_ids: dict[str, str] = {}
    started_tool_ids: set[str] = set()
    completed_tool_ids: set[str] = set()

    try:
        turn_result: AgentTurnResult | None = None
        terminal_loop_text = ""
        async for event in async_iter_agent_tool_call_loop(
            request,
            config,
            runtime,
        ):
            if isinstance(event, AgentToolLoopTextDelta):
                part_id = _append_timeline_delta(
                    timeline_parts,
                    timeline_text_chunks,
                    event.text,
                )
                yield AgentTextDelta(delta=event.text, timeline_part_id=part_id)
                continue
            if isinstance(event, AgentToolLoopTerminalText):
                terminal_loop_text = event.text.strip()
                continue
            if isinstance(event, AgentToolLoopTools):
                tool_payloads = [
                    tool.model_dump(mode="json", by_alias=True) for tool in event.tools
                ]
                new_tool_ids = [
                    tool.id for tool in event.tools if tool.id not in tool_part_ids
                ]
                if new_tool_ids:
                    part_id = _append_timeline_tools(
                        timeline_parts,
                        new_tool_ids,
                    )
                    for tool_id in new_tool_ids:
                        tool_part_ids[tool_id] = part_id
                for tool_payload in tool_payloads:
                    tool_id = str(tool_payload.get("id") or "")
                    if not tool_id:
                        continue
                    timeline_part_id = tool_part_ids[tool_id]
                    state = str(tool_payload.get("state") or "")
                    terminal = state.startswith("output-")
                    if tool_id not in started_tool_ids:
                        started_tool_ids.add(tool_id)
                        event_name: Literal["tool_start", "tool_done"] = (
                            "tool_done" if terminal else "tool_start"
                        )
                        if terminal:
                            completed_tool_ids.add(tool_id)
                        yield AgentToolUpdate(
                            kind=event_name,
                            tool=tool_payload,
                            timeline_part_id=timeline_part_id,
                        )
                    elif terminal and tool_id not in completed_tool_ids:
                        completed_tool_ids.add(tool_id)
                        yield AgentToolUpdate(
                            kind="tool_done",
                            tool=tool_payload,
                            timeline_part_id=timeline_part_id,
                        )
                    elif not terminal:
                        yield AgentToolUpdate(
                            kind="tool_delta",
                            tool=tool_payload,
                            timeline_part_id=timeline_part_id,
                        )
                continue
            if isinstance(event, AgentToolLoopEdits):
                yield AgentEditsUpdate(
                    edits=[
                        edit.model_dump(mode="json", by_alias=True)
                        for edit in event.edits
                    ],
                    transaction_state=event.transaction_state,
                )
                continue
            if isinstance(event, AgentToolLoopCompleted):
                turn_result = event.result
                if not terminal_loop_text:
                    terminal_loop_text = turn_result.terminal_text.strip()

        if turn_result is None:
            raise LlmRequestError("Agent loop ended before completion.")
        if not terminal_loop_text:
            raise LlmRequestError("Model provider returned an empty response.")

        if turn_result.message is not None:
            message = turn_result.message.model_copy(update={"id": message_id})
            message = _merge_llm_response(message, terminal_loop_text)
        else:
            message = _direct_llm_response(
                terminal_loop_text,
                message_id=message_id,
            )
        message = message.model_copy(
            update={
                "timeline": _materialize_timeline_text(
                    timeline_parts,
                    timeline_text_chunks,
                ),
            },
        )
    except AgentRunAborted:
        return
    except LlmRequestError as exc:
        error_detail = _llm_error_detail(exc)
        if isinstance(exc, AgentModelTurnLimitError):
            if exc.result.message is not None:
                message = exc.result.message.model_copy(update={"id": message_id})
                message = _merge_llm_response(message, exc.result.terminal_text)
            else:
                message = _direct_llm_response(
                    exc.result.terminal_text,
                    message_id=message_id,
                )
            message = message.model_copy(
                update={
                    "timeline": _materialize_timeline_text(
                        timeline_parts,
                        timeline_text_chunks,
                    ),
                },
            )
        elif isinstance(exc, AgentContextWindowError):
            error_detail = agent_text(
                request.locale,
                "error.context_window_exceeded",
            )
            message = _direct_llm_response(
                error_detail,
                message_id=message_id,
            )
        else:
            message = _model_error_message(request, config, exc)
        yield AgentStreamError(
            message=error_detail or "Agent request failed.",
            error_code=_llm_error_code(exc),
        )
        # Provider failures remain visible but do not become conversation
        # history, so the accepted user turn can be retried without duplication.
        yield AgentCompleted(message=message, persist=False)
        return

    yield AgentCompleted(message=message, persist=True)
