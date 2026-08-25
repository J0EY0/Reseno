import json
from collections.abc import AsyncIterator, Callable, Iterator
from sqlite3 import Connection
from uuid import uuid4

from app.schemas.agent import (
    AgentChatMessage,
    AgentChatRequest,
    AgentTimelinePart,
)
from app.services.llm import (
    AgentLlmConfig,
    LlmRequestError,
    LlmTimeoutError,
    resolve_agent_llm_config,
)

from ..localization import agent_text
from .context import (
    AgentRunAborted,
    AgentRuntimeContext,
)
from .loop import AgentModelTurnLimitError, async_iter_agent_tool_call_loop


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


def _llm_error_code(error: LlmRequestError) -> str:
    """Return the durable public classification for one provider failure."""

    if isinstance(error, AgentModelTurnLimitError):
        return "AGENT_INTERNAL_ERROR"
    if error.status_code in {401, 403}:
        return "AGENT_PROVIDER_AUTH_ERROR"
    if isinstance(error, LlmTimeoutError):
        return "AGENT_PROVIDER_TIMEOUT"
    return "AGENT_PROVIDER_ERROR"


def _sse_event(event_name: str, payload: dict[str, object]) -> str:
    """Serialize one server-sent event frame."""

    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event_name}\ndata: {data}\n\n"


def _message_patch_event(event_name: str, **fields: object) -> str:
    """Return an SSE event that patches visible assistant message fields."""

    return _sse_event(
        event_name,
        {
            "type": event_name,
            "message": fields,
        },
    )


def _text_stream_event(delta: str, timeline_part_id: str) -> str:
    return _sse_event(
        "text_delta",
        {
            "type": "text_delta",
            "delta": delta,
            "timelinePartId": timeline_part_id,
        },
    )


def _tool_stream_event(
    event_name: str,
    tool: dict[str, object],
    timeline_part_id: str,
) -> str:
    return _sse_event(
        event_name,
        {
            "type": event_name,
            "tool": tool,
            "timelinePartId": timeline_part_id,
        },
    )


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
    on_complete: Callable[[AgentChatMessage], None] | None = None,
) -> Iterator[str]:
    """Yield a chat message and persist it before the terminal SSE event."""

    message_payload = message.model_dump(mode="json", by_alias=True)
    text = message.text

    yield _sse_event(
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": message.id,
                "role": message.role,
                "tone": message.tone,
                "text": "",
            },
        },
    )

    chunk_size = 24
    for index in range(0, len(text), chunk_size):
        yield _text_stream_event(
            text[index : index + chunk_size],
            "timeline-text-1",
        )

    on_complete_message(on_complete, message)
    yield _sse_event(
        "message_done",
        {"type": "message_done", "message": message_payload},
    )


async def async_stream_agent_response(
    request: AgentChatRequest,
    conn: Connection,
    on_complete: Callable[[AgentChatMessage], None] | None = None,
    runtime: AgentRuntimeContext | None = None,
) -> AsyncIterator[str]:
    """Stream an agent response through async provider calls."""

    # Import lazily because importing the attachment submodule initializes the
    # Agent package, whose public runtime imports this streaming module.
    from app.services.agent_sessions import persist_agent_user_message

    # The user turn is authoritative before provider work begins. Cancellation
    # or provider failure therefore leaves a recoverable prompt, while the
    # completion callback remains responsible only for successful assistants.
    persist_agent_user_message(conn, request)
    runtime = runtime or AgentRuntimeContext()
    config = resolve_agent_llm_config(conn, request.model_config_data)
    if config is None:
        message = _model_setup_message(request)
        for chunk in stream_agent_message(message, on_complete):
            yield chunk
        return

    async for frame in async_stream_resolved_agent_response(
        request,
        config,
        on_complete=on_complete,
        runtime=runtime,
    ):
        yield frame


async def async_stream_resolved_agent_response(
    request: AgentChatRequest,
    config: AgentLlmConfig,
    on_complete: Callable[[AgentChatMessage], None] | None = None,
    runtime: AgentRuntimeContext | None = None,
) -> AsyncIterator[str]:
    """Project one model/tool loop into the public SSE protocol."""

    runtime = runtime or AgentRuntimeContext()
    message_id = f"agent-msg-{uuid4().hex[:12]}"

    yield _sse_event(
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": message_id,
                "role": "assistant",
                "tone": "default",
                "text": "",
            },
        },
    )

    timeline_parts: list[AgentTimelinePart] = []
    timeline_text_chunks: dict[str, list[str]] = {}
    tool_part_ids: dict[str, str] = {}
    started_tool_ids: set[str] = set()
    completed_tool_ids: set[str] = set()

    try:
        turn_result = None
        terminal_loop_text = ""
        async for event in async_iter_agent_tool_call_loop(
            request,
            config,
            runtime,
        ):
            if event.kind == "text_delta":
                delta = event.text or ""
                if delta:
                    part_id = _append_timeline_delta(
                        timeline_parts,
                        timeline_text_chunks,
                        delta,
                    )
                    yield _text_stream_event(delta, part_id)
                continue
            if event.kind == "terminal":
                terminal_loop_text = (event.text or "").strip()
                continue
            if event.kind == "tools":
                tool_payloads = [
                    tool.model_dump(mode="json", by_alias=True)
                    for tool in event.tools or []
                ]
                new_tool_ids = [
                    tool.id
                    for tool in event.tools or []
                    if tool.id not in tool_part_ids
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
                        event_name = "tool_done" if terminal else "tool_start"
                        if terminal:
                            completed_tool_ids.add(tool_id)
                        yield _tool_stream_event(
                            event_name,
                            tool_payload,
                            timeline_part_id,
                        )
                    elif terminal and tool_id not in completed_tool_ids:
                        completed_tool_ids.add(tool_id)
                        yield _tool_stream_event(
                            "tool_done",
                            tool_payload,
                            timeline_part_id,
                        )
                    elif not terminal:
                        yield _tool_stream_event(
                            "tool_delta",
                            tool_payload,
                            timeline_part_id,
                        )
                continue
            if event.kind == "edits":
                yield _message_patch_event(
                    "edits",
                    edits=[
                        edit.model_dump(mode="json", by_alias=True)
                        for edit in event.edits or []
                    ],
                    transactionState=event.transaction_state,
                )
                continue
            if event.kind == "done":
                turn_result = event.result
                if turn_result and not terminal_loop_text:
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
        else:
            message = _model_error_message(request, config, exc)
        yield _sse_event(
            "error",
            {
                "type": "error",
                "error": _llm_error_detail(exc) or "Agent request failed.",
                "errorCode": _llm_error_code(exc),
            },
        )
        yield _sse_event(
            "message_done",
            {
                "type": "message_done",
                "message": message.model_dump(mode="json", by_alias=True),
            },
        )
        # Provider and attachment failures are terminal for this request, but
        # they are not a completed conversation turn. Keeping the completion
        # hook untouched here would persist both the optimistic user message
        # and this transient error, making a retry duplicate the prompt.
        return

    # Persist before telling clients that the turn is authoritative.
    on_complete_message(on_complete, message)
    yield _sse_event(
        "message_done",
        {
            "type": "message_done",
            "message": message.model_dump(mode="json", by_alias=True),
        },
    )


def on_complete_message(
    callback: Callable[[AgentChatMessage], None] | None,
    message: AgentChatMessage,
) -> None:
    """Call the streaming completion hook when the router needs persistence."""

    if callback:
        callback(message)
