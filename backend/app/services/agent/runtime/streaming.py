import json
import re
from collections.abc import Callable, Iterator
from sqlite3 import Connection
from typing import Any
from uuid import uuid4

from app.schemas.agent import (
    AgentChatMessage,
    AgentChatRequest,
    AgentKnowledgeItem,
    AgentTimelinePart,
)
from app.services.llm_client import (
    AgentLlmConfig,
    LlmRequestError,
    resolve_agent_llm_config,
)

from ..compat import get_agent_api
from ..editing import _string_list
from .loop import (
    iter_agent_tool_call_loop,
    run_agent_tool_call_loop,
)
from .messages import build_agent_messages


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

    return AgentChatMessage(
        id=draft.id,
        role=draft.role,
        tone=draft.tone,
        text=text,
        plan=draft.plan,
        updates=draft.updates,
        timeline=draft.timeline,
        suggestions=suggestions,
        knowledge=knowledge,
        tools=draft.tools,
        sources=draft.sources,
        edits=draft.edits,
        quickReplies=quick_replies,
        actions=draft.actions,
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

    is_zh = request.locale == "zh"
    text = (
        "当前还没有可用的大模型配置。请先在「大模型配置」中新增模型、填写 API Key "
        "并设为默认模型，然后再让 Agent 分析或修改简历。"
        if is_zh
        else (
            "No usable model configuration is available yet. Add a model, "
            "enter its API key, and set it as the default model before asking "
            "the agent to analyze or edit the resume."
        )
    )
    quick_replies = ["去配置模型"] if is_zh else ["Configure model"]

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

    is_zh = request.locale == "zh"
    detail = _llm_error_detail(error)
    text = (
        f"已找到模型配置「{config.name}」，但调用模型失败。请检查 API 地址、"
        "API Key、模型名称和网络连通性后重试。"
        if is_zh
        else (
            f'Model config "{config.name}" was found, but the provider request '
            "failed. Check the API URL, API key, model name, and network access."
        )
    )
    if detail:
        label = "提供方返回" if is_zh else "Provider response"
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
    """Return a bounded provider error excerpt safe for user-facing messages."""

    detail = str(error).replace("\n", " ").strip()
    if not detail:
        return ""

    return detail[:320]


def build_agent_message(
    request: AgentChatRequest,
    conn: Connection,
) -> AgentChatMessage:
    """Build a real model-backed ReAct assistant message."""

    config = resolve_agent_llm_config(conn, request.model_config_data)
    if config is None:
        return _model_setup_message(request)

    draft: AgentChatMessage | None = None
    try:
        runner = run_agent_tool_call_loop(request, config)
        if runner.tools:
            draft = runner.build_message()
        if runner.terminal_text.strip():
            terminal_text = runner.terminal_text.strip()
            if draft:
                return draft.model_copy(update={"text": terminal_text})

            return _direct_llm_response(terminal_text)
        if not draft:
            raise LlmRequestError("Model provider returned an empty response.")

        messages = build_agent_messages(request, config, mode="final", draft=draft)

        raw_response = get_agent_api().complete_chat(config, messages)
    except LlmRequestError as exc:
        return _model_error_message(request, config, exc)

    if draft:
        return _merge_llm_response(draft, raw_response)

    return _direct_llm_response(raw_response)


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

    blocked_prefixes = (
        "thought:",
        "reasoning:",
        "action:",
        "observation:",
        "工具:",
        "工具名:",
        "字段路径:",
    )
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


def stream_agent_message(message: AgentChatMessage) -> Iterator[str]:
    """Yield a chat message as incremental SSE events."""

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
    yield _sse_event(
        "message_done",
        {"type": "message_done", "message": message_payload},
    )


def stream_agent_response(
    request: AgentChatRequest,
    conn: Connection,
    on_complete: Callable[[AgentChatMessage], None] | None = None,
) -> Iterator[str]:
    """Stream an agent response while the provider is still generating text."""

    config = resolve_agent_llm_config(conn, request.model_config_data)
    if config is None:
        message = _model_setup_message(request)
        yield from stream_agent_message(message)
        on_complete_message(on_complete, message)
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
    reasoning_parts: list[str] = []
    timeline_parts: list[AgentTimelinePart] = []
    tool_part_ids: dict[str, str] = {}

    try:
        runner = None
        terminal_loop_text = False
        for event in iter_agent_tool_call_loop(request, config):
            if event.kind == "text":
                visible_text = _visible_loop_text(event.text)
                if visible_text:
                    if event.terminal and not timeline_parts:
                        raw_parts.append(visible_text)
                        yield _text_delta(visible_text)
                    else:
                        separator = "\n\n" if raw_parts else ""
                        delta = f"{separator}{visible_text}"
                        raw_parts.append(delta)
                        _append_timeline_text(timeline_parts, visible_text)
                        yield _message_delta_event(
                            "timeline",
                            text="".join(raw_parts),
                            timeline=_timeline_payload(timeline_parts),
                        )
                terminal_loop_text = terminal_loop_text or event.terminal
                continue
            if event.kind == "tools":
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
                yield _message_delta_event(
                    "tools",
                    text="".join(raw_parts),
                    tools=[
                        tool.model_dump(mode="json", by_alias=True)
                        for tool in event.tools or []
                    ],
                    timeline=_timeline_payload(timeline_parts),
                )
                continue
            if event.kind == "edits":
                yield _message_delta_event(
                    "edits",
                    edits=[
                        edit.model_dump(mode="json", by_alias=True)
                        for edit in event.edits or []
                    ],
                )
                continue
            if event.kind == "done":
                runner = event.runner

        if runner and runner.tools:
            draft = runner.build_message(message_id=message_id)

        if terminal_loop_text:
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
            yield _sse_event(
                "message_done",
                {
                    "type": "message_done",
                    "message": message.model_dump(mode="json", by_alias=True),
                },
            )
            on_complete_message(on_complete, message)
            return

        if not draft:
            raise LlmRequestError("Model provider returned an empty response.")

        messages = build_agent_messages(
            request,
            config,
            mode="streaming_final",
            draft=draft,
        )
        if raw_parts:
            raw_parts.append("\n\n")
        final_part_id = ""
        for delta in get_agent_api().complete_chat_stream(config, messages):
            if delta.kind == "reasoning":
                reasoning_parts.append(delta.delta)
                yield _sse_event(
                    "reasoning_delta",
                    {
                        "type": "reasoning_delta",
                        "delta": delta.delta,
                    },
                )
                continue

            raw_parts.append(delta.delta)
            if timeline_parts:
                if not final_part_id:
                    final_part_id = f"timeline-text-{len(timeline_parts) + 1}"
                    timeline_parts.append(_timeline_text_part(final_part_id, ""))
                timeline_parts[-1].text = timeline_parts[-1].text + delta.delta
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
                    "delta": delta.delta,
                },
            )

        raw_response = "".join(raw_parts).strip()
        if not raw_response:
            raise LlmRequestError("Model provider returned an empty response.")
    except LlmRequestError as exc:
        message = _model_error_message(request, config, exc)
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
        on_complete_message(on_complete, message)
        return

    reasoning = "".join(reasoning_parts).strip()
    message = (
        draft.model_copy(
            update={
                "text": raw_response,
                "timeline": timeline_parts,
            },
        )
        if draft
        else _direct_llm_response(
            raw_response,
            message_id=message_id,
            reasoning=reasoning,
        )
    )
    if draft and reasoning:
        message = message.model_copy(update={"reasoning": reasoning})

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
    on_complete_message(on_complete, message)


def on_complete_message(
    callback: Callable[[AgentChatMessage], None] | None,
    message: AgentChatMessage,
) -> None:
    """Call the streaming completion hook when the router needs persistence."""

    if callback:
        callback(message)
