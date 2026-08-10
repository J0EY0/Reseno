import json
import re
from collections.abc import AsyncIterator, Callable, Iterator
from sqlite3 import Connection
from typing import Any
from uuid import uuid4

from app.schemas.agent import (
    AgentChatMessage,
    AgentChatRequest,
    AgentKnowledgeItem,
    AgentTimelinePart,
)
from app.services.agent.request_context import accumulated_transaction_edits
from app.services.llm import (
    AgentLlmConfig,
    LlmAssistantMessage,
    LlmRequestError,
    LlmStreamEvent,
    LlmTimeoutError,
    async_complete_chat,
    async_stream_chat,
    resolve_agent_llm_config,
)

from ..editing import _string_list
from ..localization import agent_text
from ..parsing_patterns import agent_patterns
from .context import AgentRunAborted, AgentRuntimeContext
from .loop import async_iter_agent_tool_call_loop
from .messages import (
    build_agent_messages,
    has_native_current_request_attachments,
    is_native_attachment_unsupported,
)


def _parse_json_object(text: str) -> dict[str, Any] | None:
    """Parse a JSON object from a model response when possible."""

    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?", "", value, flags=re.IGNORECASE).strip()
        value = re.sub(r"```$", "", value).strip()

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None

    return parsed if isinstance(parsed, dict) else None


def _knowledge_items(value: object) -> list[AgentKnowledgeItem]:
    """Convert model-provided knowledge items into schema objects."""

    if not isinstance(value, list):
        return []

    items: list[AgentKnowledgeItem] = []
    for item in value:
        if not isinstance(item, dict):
            continue

        title = item.get("title")
        detail = item.get("detail")
        if isinstance(title, str) and isinstance(detail, str):
            items.append(AgentKnowledgeItem(title=title, detail=detail))

    return items


def _merge_llm_response(
    draft: AgentChatMessage,
    raw_text: str,
) -> AgentChatMessage:
    """Merge real model text with deterministic executable draft operations."""

    parsed = _parse_json_object(raw_text)
    text = raw_text
    suggestions = draft.suggestions
    knowledge = draft.knowledge
    quick_replies = draft.quick_replies

    if parsed:
        parsed_text = parsed.get("text")
        parsed_suggestions = _string_list(parsed.get("suggestions"))
        parsed_quick_replies = _string_list(parsed.get("quickReplies"))
        parsed_knowledge = _knowledge_items(parsed.get("knowledge"))

        if isinstance(parsed_text, str) and parsed_text.strip():
            text = parsed_text.strip()
        if parsed_suggestions:
            suggestions = parsed_suggestions[:4]
        if parsed_quick_replies:
            quick_replies = parsed_quick_replies[:4]
        if parsed_knowledge:
            knowledge = parsed_knowledge[:4]

    return draft.model_copy(
        update={
            "text": text,
            "suggestions": suggestions,
            "knowledge": knowledge,
            "quick_replies": quick_replies,
        },
    )


def _direct_llm_response(
    raw_text: str,
    *,
    message_id: str | None = None,
    reasoning: str = "",
) -> AgentChatMessage:
    """Return a plain assistant response with no tool-call metadata."""

    return AgentChatMessage(
        id=message_id or f"agent-msg-{uuid4().hex[:12]}",
        role="assistant",
        tone="default",
        text=raw_text,
        reasoning=reasoning,
        updates=[],
        plan=[],
        suggestions=[],
        knowledge=[],
        tools=[],
        sources=[],
        edits=[],
        quickReplies=[],
        actions=[],
    )


def _model_setup_message(request: AgentChatRequest) -> AgentChatMessage:
    """Build a direct setup guide when no usable model config exists."""

    text = agent_text(request.locale, "model.setup.text")
    quick_replies = [agent_text(request.locale, "model.setup.quick_reply")]

    return AgentChatMessage(
        id=f"agent-msg-{uuid4().hex[:12]}",
        role="assistant",
        tone="default",
        text=text,
        updates=[],
        plan=[],
        suggestions=[],
        knowledge=[],
        tools=[],
        sources=[],
        edits=[],
        quickReplies=quick_replies,
        actions=[],
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
        updates=[],
        plan=[],
        suggestions=[],
        knowledge=[],
        tools=[],
        sources=[],
        edits=[],
        quickReplies=[],
        actions=[],
    )


def _llm_error_detail(error: LlmRequestError) -> str:
    """Return a stable error without exposing provider-controlled text."""

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

    if error.status_code in {401, 403}:
        return "AGENT_PROVIDER_AUTH_ERROR"
    if isinstance(error, LlmTimeoutError):
        return "AGENT_PROVIDER_TIMEOUT"
    return "AGENT_PROVIDER_ERROR"


def _sse_event(event_name: str, payload: dict[str, object]) -> str:
    """Serialize one server-sent event frame."""

    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event_name}\ndata: {data}\n\n"


def _message_delta_payload(message: AgentChatMessage) -> dict[str, object]:
    """Return mutable assistant fields for an SSE message_delta event."""

    message_payload = message.model_dump(mode="json", by_alias=True)
    return {
        "text": message_payload["text"],
        "reasoning": message_payload["reasoning"],
        "updates": message_payload["updates"],
        "timeline": message_payload["timeline"],
        "plan": message_payload["plan"],
        "suggestions": message_payload["suggestions"],
        "knowledge": message_payload["knowledge"],
        "tools": message_payload["tools"],
        "sources": message_payload["sources"],
        "edits": message_payload["edits"],
        "transactionState": message_payload["transactionState"],
        "quickReplies": message_payload["quickReplies"],
        "actions": message_payload["actions"],
    }


def _message_delta_event(event_name: str, **fields: object) -> str:
    """Return an SSE event that patches visible assistant message fields."""

    return _sse_event(
        event_name,
        {
            "type": event_name,
            "message": fields,
        },
    )


def _tool_stream_event(event_name: str, tool: dict[str, object]) -> str:
    return _sse_event(
        event_name,
        {
            "type": event_name,
            "tool": tool,
        },
    )


async def _complete_chat_stream_events(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
    runtime: AgentRuntimeContext,
) -> AsyncIterator[LlmStreamEvent]:
    """Yield provider stream events inside the agent cancellation budget."""

    if not config.supports_streaming:
        await runtime.checkpoint()
        message = await async_complete_chat(config, messages)
        await runtime.checkpoint()
        if message.content:
            yield LlmStreamEvent(type="text_delta", delta=message.content)
        yield LlmStreamEvent(type="done", message=message)
        return

    await runtime.checkpoint()
    async for event in async_stream_chat(config, messages):
        await runtime.checkpoint()
        yield event


def _is_tool_running_state(state: str) -> bool:
    """Return whether a tool state represents a pending/running action."""

    return state in {
        "approval-requested",
        "input-available",
        "input-streaming",
    }


def _visible_loop_text(text: str | None) -> str:
    """Return safe user-visible loop narration from a tool-choice response."""

    if not text:
        return ""

    blocked_prefixes = agent_patterns("streaming.blocked_visible_loop_prefixes")
    lines = []
    for raw_line in text.strip().splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lowered = line.lower()
        if any(lowered.startswith(prefix) for prefix in blocked_prefixes):
            continue
        lines.append(line)

    visible = "\n".join(lines).strip()
    if len(visible) <= 220:
        return visible

    sentence_parts = re.split(r"(?<=[。！？.!?])\s*", visible)
    compact = ""
    for sentence in sentence_parts:
        if not sentence:
            continue
        next_text = f"{compact}{sentence}" if compact else sentence
        if len(next_text) > 220:
            break
        compact = next_text

    if compact:
        return compact

    return f"{visible[:220].rstrip()}..."


def _text_delta(text: str) -> str:
    """Return one visible text delta SSE frame."""

    return _sse_event(
        "text_delta",
        {
            "type": "text_delta",
            "delta": text,
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


def _timeline_payload(parts: list[AgentTimelinePart]) -> list[dict[str, object]]:
    """Return timeline parts as SSE-safe JSON payloads."""

    return [part.model_dump(mode="json", by_alias=True) for part in parts]


def _append_timeline_text(
    parts: list[AgentTimelinePart],
    text: str,
) -> None:
    """Append text at the current stream position."""

    if not text.strip():
        return

    if parts and parts[-1].type == "text":
        separator = "\n\n" if parts[-1].text.strip() else ""
        parts[-1].text = f"{parts[-1].text}{separator}{text}"
        return

    part_id = f"timeline-text-{len(parts) + 1}"
    parts.append(_timeline_text_part(part_id, text))


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
        yield _sse_event(
            "text_delta",
            {
                "type": "text_delta",
                "delta": text[index : index + chunk_size],
            },
        )

    yield _sse_event(
        "message_delta",
        {
            "type": "message_delta",
            "message": _message_delta_payload(message),
        },
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
    draft: AgentChatMessage | None = None
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
                "reasoning": "",
            },
        },
    )

    raw_parts: list[str] = []
    timeline_parts: list[AgentTimelinePart] = []
    tool_part_ids: dict[str, str] = {}
    started_tool_ids: set[str] = set()
    completed_tool_ids: set[str] = set()

    try:
        runner = None
        terminal_loop_text = False
        async for event in async_iter_agent_tool_call_loop(
            request,
            config,
            runtime,
        ):
            if event.kind == "text":
                visible_text = _visible_loop_text(event.text)
                if visible_text:
                    if event.terminal and not timeline_parts:
                        terminal_loop_text = True
                        continue

                    separator = "\n\n" if raw_parts else ""
                    visible_delta = f"{separator}{visible_text}"
                    raw_parts.append(visible_delta)
                    _append_timeline_text(timeline_parts, visible_text)
                    yield _message_delta_event(
                        "timeline",
                        text="".join(raw_parts),
                        timeline=_timeline_payload(timeline_parts),
                    )
                terminal_loop_text = terminal_loop_text or event.terminal
                continue
            if event.kind == "tools":
                tool_payloads = [
                    tool.model_dump(mode="json", by_alias=True)
                    for tool in event.tools or []
                ]
                for tool_payload in tool_payloads:
                    tool_id = str(tool_payload.get("id") or "")
                    if not tool_id:
                        continue
                    if tool_id not in started_tool_ids:
                        started_tool_ids.add(tool_id)
                        yield _tool_stream_event("tool_start", tool_payload)
                    yield _tool_stream_event("tool_delta", tool_payload)
                    state = str(tool_payload.get("state") or "")
                    if (
                        state.startswith("output-")
                        and tool_id not in completed_tool_ids
                    ):
                        completed_tool_ids.add(tool_id)
                        yield _tool_stream_event("tool_done", tool_payload)
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
                # Tool state is streamed through the ID-addressed events above.
                # Only the timeline needs a message patch here; the terminal
                # message still carries a complete tool snapshot for replay.
                yield _message_delta_event(
                    "timeline",
                    text="".join(raw_parts),
                    timeline=_timeline_payload(timeline_parts),
                )
                continue
            if event.kind == "edits":
                streamed_edits = accumulated_transaction_edits(
                    request,
                    event.edits or [],
                )
                yield _message_delta_event(
                    "edits",
                    edits=[
                        edit.model_dump(mode="json", by_alias=True)
                        for edit in streamed_edits
                    ],
                    transactionState=event.transaction_state,
                )
                continue
            if event.kind == "done":
                runner = event.runner

        if runner and (runner.tools or runner.finish_status):
            draft = runner.build_message(message_id=message_id)
            if draft.edits:
                draft = draft.model_copy(
                    update={
                        "edits": accumulated_transaction_edits(
                            request,
                            draft.edits,
                        ),
                    },
                )

        if draft and runner and runner.transaction_failed:
            yield _sse_event(
                "message_delta",
                {
                    "type": "message_delta",
                    "message": _message_delta_payload(draft),
                },
            )
            on_complete_message(on_complete, draft)
            yield _sse_event(
                "message_done",
                {
                    "type": "message_done",
                    "message": draft.model_dump(mode="json", by_alias=True),
                },
            )
            return

        if draft and runner and runner.finish_status and not runner.tools:
            yield _sse_event(
                "message_delta",
                {
                    "type": "message_delta",
                    "message": _message_delta_payload(draft),
                },
            )
            on_complete_message(on_complete, draft)
            yield _sse_event(
                "message_done",
                {
                    "type": "message_done",
                    "message": draft.model_dump(mode="json", by_alias=True),
                },
            )
            return

        if terminal_loop_text and (draft or (runner and runner.tools)):
            raw_response = "".join(raw_parts).strip()
            if not raw_response:
                raise LlmRequestError("Model provider returned an empty response.")
            message = (
                draft.model_copy(
                    update={
                        "text": raw_response,
                        "timeline": timeline_parts,
                    },
                )
                if draft
                else _direct_llm_response(raw_response, message_id=message_id)
            )
            yield _sse_event(
                "message_delta",
                {
                    "type": "message_delta",
                    "message": _message_delta_payload(message),
                },
            )
            on_complete_message(on_complete, message)
            yield _sse_event(
                "message_done",
                {
                    "type": "message_done",
                    "message": message.model_dump(mode="json", by_alias=True),
                },
            )
            return

        if raw_parts:
            raw_parts.append("\n\n")
        final_part_id = ""
        stream_message: LlmAssistantMessage | None = None
        force_attachment_text = bool(
            runner and runner.native_attachment_text_fallback_used
        )
        native_fallback_available = (
            not force_attachment_text
            and has_native_current_request_attachments(request, config)
        )
        final_timeout_retry_available = True

        while True:
            messages = build_agent_messages(
                request,
                config,
                mode="streaming_final",
                draft=draft,
                force_attachment_text=force_attachment_text,
            )
            final_output_started = False
            try:
                async for stream_event in _complete_chat_stream_events(
                    config,
                    messages,
                    runtime,
                ):
                    if stream_event.type == "done":
                        stream_message = stream_event.message
                        continue
                    if stream_event.type == "reasoning_delta":
                        # Reasoning is transient backend metadata; it is
                        # intentionally not persisted or shown to users.
                        continue

                    if not stream_event.delta:
                        continue

                    final_output_started = True
                    raw_parts.append(stream_event.delta)
                    if timeline_parts:
                        if not final_part_id:
                            final_part_id = f"timeline-text-{len(timeline_parts) + 1}"
                            timeline_parts.append(
                                _timeline_text_part(final_part_id, ""),
                            )
                        timeline_parts[-1].text = (
                            timeline_parts[-1].text + stream_event.delta
                        )
                        yield _message_delta_event(
                            "timeline",
                            text="".join(raw_parts),
                            timeline=_timeline_payload(timeline_parts),
                        )
                        continue

                    yield _sse_event(
                        "text_delta",
                        {
                            "type": "text_delta",
                            "delta": stream_event.delta,
                        },
                    )
                break
            except LlmTimeoutError:
                if final_output_started or not final_timeout_retry_available:
                    raise

                # A final request that timed out before its first visible token
                # has no tool or UI side effect and is safe to replay once.
                final_timeout_retry_available = False
                stream_message = None
                continue
            except LlmRequestError as exc:
                if (
                    final_output_started
                    or not native_fallback_available
                    or not is_native_attachment_unsupported(exc)
                ):
                    raise

                # A provider may advertise a compatible API family while
                # rejecting native files for one endpoint/model. Retry once
                # with the cached complete extraction before any visible text.
                force_attachment_text = True
                native_fallback_available = False
                if runner:
                    runner.native_attachment_text_fallback_used = True
                stream_message = None
                continue

        if stream_message and stream_message.stop_reason == "length":
            raise LlmRequestError(
                "Model output was truncated. Increase max output tokens or use "
                "a model with a larger output budget.",
            )

        raw_response = "".join(raw_parts).strip()
        if not raw_response:
            raise LlmRequestError("Model provider returned an empty response.")
    except AgentRunAborted:
        return
    except LlmRequestError as exc:
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
            "message_delta",
            {
                "type": "message_delta",
                "message": _message_delta_payload(message),
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

    if draft:
        message = _merge_llm_response(
            draft.model_copy(update={"timeline": timeline_parts}),
            raw_response,
        )
    else:
        message = _direct_llm_response(
            raw_response,
            message_id=message_id,
        )

    yield _sse_event(
        "message_delta",
        {
            "type": "message_delta",
            "message": _message_delta_payload(message),
        },
    )
    # `message_done` tells clients the turn is authoritative. Run persistence
    # first so a failed SQLite/filesystem commit cannot look completed in UI.
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
