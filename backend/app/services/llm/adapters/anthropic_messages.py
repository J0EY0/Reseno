from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from ..common import (
    ANTHROPIC_VERSION,
    anthropic_usage,
    async_post_json,
    async_stream_json,
    close_async_stream,
    map_stop_reason,
    message_content_parts,
    message_content_text,
    parsed_tool_call,
    provider_base_url,
    request_max_output_tokens,
    system_and_messages,
    tool_function,
)
from ..errors import LlmRequestError
from ..tool_schema import portable_tool_schema
from ..types import (
    AgentLlmConfig,
    LlmAssistantMessage,
    LlmStopReason,
    LlmStreamEvent,
    LlmToolCall,
)


def supports_native_attachment(media_type: str) -> bool:
    """Anthropic Messages accepts PDF document blocks."""

    return media_type == "application/pdf"


async def complete(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
) -> LlmAssistantMessage:
    """Call Anthropic Messages and require visible text."""

    payload = await _post_messages(config, messages)
    message = _message_from_payload(payload)
    if message.content:
        return message

    raise LlmRequestError("Model provider returned an empty response.")


async def complete_tool_call(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> LlmAssistantMessage:
    """Ask Anthropic Messages to choose zero or more tools."""

    payload = await _post_messages(config, messages, tools)
    return _message_from_payload(payload)


async def stream_tool_call(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> AsyncIterator[LlmStreamEvent]:
    """Stream tool input privately until Anthropic authoritatively completes."""

    events = _stream_messages(config, messages, tools)
    try:
        async for event in events:
            yield event
    finally:
        await close_async_stream(events)


async def stream(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
) -> AsyncIterator[LlmStreamEvent]:
    """Stream Anthropic Messages SSE events into the shared LLM contract."""

    events = _stream_messages(config, messages)
    try:
        async for event in events:
            yield event
    finally:
        await close_async_stream(events)


async def _stream_messages(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> AsyncIterator[LlmStreamEvent]:
    payload = {**_payload(config, messages, tools), "stream": True}
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    thinking_blocks_by_index: dict[int, dict[str, Any]] = {}
    tool_inputs_by_index: dict[int, dict[str, Any]] = {}
    response_id: str | None = None
    stop_reason: LlmStopReason = "unknown"
    usage: dict[str, Any] = {}
    provider_stream = async_stream_json(
        f"{provider_base_url(config.base_url)}/messages",
        headers=_headers(config),
        payload=payload,
        timeout_seconds=config.timeout_seconds,
    )

    try:
        async for event in provider_stream:
            event_type = str(event.get("type") or "")
            if event_type == "message_start":
                message = event.get("message")
                if not isinstance(message, dict):
                    continue
                response_id = str(message.get("id") or "") or response_id
                message_usage = message.get("usage")
                if isinstance(message_usage, dict):
                    usage.update(message_usage)
                if response_id or message_usage:
                    yield LlmStreamEvent(type="activity")
                continue

            if event_type == "content_block_start":
                block = event.get("content_block")
                if not isinstance(block, dict):
                    continue
                index = _content_block_index(event)
                thinking_block = _thinking_block(block)
                if thinking_block:
                    thinking_blocks_by_index[index] = thinking_block
                    if thinking_block.get("type") == "redacted_thinking":
                        yield LlmStreamEvent(type="activity")
                    continue
                if block.get("type") != "tool_use":
                    continue
                if tools is None:
                    raise LlmRequestError(
                        "Model provider returned an unexpected tool call.",
                    )
                tool_id = str(block.get("id") or "")
                name = str(block.get("name") or "").strip()
                if not tool_id or not name or index in tool_inputs_by_index:
                    raise LlmRequestError(
                        "Model provider returned an invalid tool stream.",
                    )
                tool_inputs_by_index[index] = {
                    "id": tool_id,
                    "name": name,
                    "raw_parts": [],
                    "closed": False,
                }
                yield LlmStreamEvent(type="activity")
                continue

            if event_type == "content_block_delta":
                delta = event.get("delta")
                if not isinstance(delta, dict):
                    continue
                delta_type = str(delta.get("type") or "")
                if delta_type == "text_delta":
                    text = delta.get("text")
                    if isinstance(text, str) and text:
                        content_parts.append(text)
                        yield LlmStreamEvent(type="text_delta", delta=text)
                    continue
                if delta_type == "thinking_delta":
                    thinking = delta.get("thinking")
                    if isinstance(thinking, str) and thinking:
                        reasoning_parts.append(thinking)
                        block = thinking_blocks_by_index.setdefault(
                            _content_block_index(event),
                            {"type": "thinking", "thinking": ""},
                        )
                        block["thinking"] = str(block.get("thinking") or "") + thinking
                        yield LlmStreamEvent(
                            type="reasoning_delta",
                            delta=thinking,
                        )
                    continue
                if delta_type == "signature_delta":
                    signature = delta.get("signature")
                    if isinstance(signature, str) and signature:
                        block = thinking_blocks_by_index.setdefault(
                            _content_block_index(event),
                            {"type": "thinking", "thinking": ""},
                        )
                        block["signature"] = (
                            str(block.get("signature") or "") + signature
                        )
                        yield LlmStreamEvent(type="activity")
                    continue
                if delta_type != "input_json_delta":
                    continue
                tool_input = tool_inputs_by_index.get(_content_block_index(event))
                if tool_input is None or bool(tool_input["closed"]):
                    raise LlmRequestError(
                        "Model provider returned an invalid tool stream.",
                    )
                partial_json = delta.get("partial_json")
                if isinstance(partial_json, str) and partial_json:
                    tool_input["raw_parts"].append(partial_json)
                    yield LlmStreamEvent(type="activity")
                continue

            if event_type == "content_block_stop":
                tool_input = tool_inputs_by_index.get(_content_block_index(event))
                if tool_input is not None:
                    if bool(tool_input["closed"]):
                        raise LlmRequestError(
                            "Model provider returned an invalid tool stream.",
                        )
                    tool_input["closed"] = True
                    yield LlmStreamEvent(type="activity")
                continue

            if event_type == "message_delta":
                delta = event.get("delta")
                stop_reason_value = (
                    delta.get("stop_reason") if isinstance(delta, dict) else None
                )
                has_stop_reason = stop_reason_value is not None
                if has_stop_reason:
                    stop_reason = map_stop_reason(stop_reason_value)
                event_usage = event.get("usage")
                if isinstance(event_usage, dict):
                    usage.update(event_usage)
                if has_stop_reason or event_usage:
                    yield LlmStreamEvent(type="activity")
                continue

            if event_type == "error":
                raise LlmRequestError(_stream_error_message(event))

            if event_type != "message_stop":
                continue

            if stop_reason == "unknown" or (
                tool_inputs_by_index and stop_reason == "stop"
            ):
                raise LlmRequestError(
                    "Model provider returned an invalid stream completion.",
                )

            tool_calls: list[LlmToolCall] = []
            if stop_reason == "tool_calls":
                if not tool_inputs_by_index or any(
                    not bool(tool_input["closed"])
                    for tool_input in tool_inputs_by_index.values()
                ):
                    raise LlmRequestError(
                        "Model provider stream ended with an incomplete tool call.",
                    )
                tool_calls = [
                    parsed_tool_call(
                        call_id=str(tool_input["id"]),
                        name=str(tool_input["name"]),
                        raw_arguments="".join(tool_input["raw_parts"]),
                    )
                    for _, tool_input in sorted(tool_inputs_by_index.items())
                ]

            yield LlmStreamEvent(
                type="done",
                message=LlmAssistantMessage(
                    content="".join(content_parts).strip(),
                    tool_calls=tool_calls,
                    reasoning="".join(reasoning_parts).strip(),
                    usage=anthropic_usage({"usage": usage}),
                    stop_reason=stop_reason,
                    response_id=response_id,
                    provider_state=_thinking_provider_state(
                        [
                            block
                            for _, block in sorted(
                                thinking_blocks_by_index.items(),
                            )
                        ],
                    ),
                ),
            )
            return
    finally:
        await close_async_stream(provider_stream)

    raise LlmRequestError("Model provider stream ended before completion.")


async def _post_messages(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return await async_post_json(
        f"{provider_base_url(config.base_url)}/messages",
        headers=_headers(config),
        payload=_payload(config, messages, tools),
        timeout_seconds=config.timeout_seconds,
    )


def _payload(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    system, provider_messages = anthropic_messages(messages)
    max_tokens = request_max_output_tokens(config)
    payload: dict[str, Any] = {
        "model": config.model,
        "max_tokens": max_tokens,
        "messages": provider_messages,
    }
    if system:
        payload["system"] = system

    # Anthropic extended thinking forbids temperature/top_p; keep that provider
    # rule inside the adapter instead of leaking it into agent code.
    if config.supports_thinking and config.thinking_enabled:
        payload["thinking"] = {
            "type": "enabled",
            "budget_tokens": min(1024, max(128, max_tokens // 2)),
        }
    else:
        if config.temperature is not None:
            payload["temperature"] = config.temperature
        if config.top_p is not None:
            payload["top_p"] = config.top_p
    if tools:
        payload["tools"] = _tools(tools)
        payload["tool_choice"] = {"type": "auto"}

    return payload


def anthropic_messages(
    messages: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    system, non_system = system_and_messages(messages)
    converted: list[dict[str, Any]] = []

    for message in non_system:
        role = message.get("role")
        if role == "tool":
            tool_use_id = str(message.get("tool_call_id") or "")
            # Anthropic represents tool results as user-role content blocks
            # keyed by the original tool_use id, not as a separate `tool` role.
            converted.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": message_content_text(message.get("content")),
                        },
                    ],
                },
            )
            continue

        if role == "assistant":
            # Signed thinking blocks are continuation state, not display text.
            # Anthropic requires the original block to precede the matching
            # tool_use block when the tool result is sent back.
            blocks = _thinking_blocks_from_state(message.get("provider_state"))
            text = message_content_text(message.get("content")).strip()
            if text:
                blocks.append({"type": "text", "text": text})
            for tool_call in message.get("tool_calls") or []:
                function = tool_function(tool_call)
                tool_id = str(tool_call.get("id") or "")
                name = str(function.get("name") or "").strip()
                raw_arguments = str(function.get("arguments") or "{}")
                if not tool_id or not name:
                    continue
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tool_id,
                        "name": name,
                        "input": _safe_json_object(raw_arguments),
                    },
                )
            if blocks:
                converted.append({"role": "assistant", "content": blocks})
            continue

        if role == "user":
            converted.append(
                {
                    "role": "user",
                    "content": _anthropic_content(message.get("content")),
                },
            )

    return system, converted


def _anthropic_content(content: Any) -> str | list[dict[str, Any]]:
    parts = message_content_parts(content)
    if not any(part["type"] in {"image", "file"} for part in parts):
        return message_content_text(content)

    converted: list[dict[str, Any]] = []
    for part in parts:
        if part["type"] == "text":
            converted.append({"type": "text", "text": part["text"]})
        elif part["type"] == "image":
            converted.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": part["media_type"],
                        "data": part["data"],
                    },
                },
            )
        elif supports_native_attachment(part["media_type"]):
            converted.append(
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": part["media_type"],
                        "data": part["data"],
                    },
                },
            )
        else:
            raise LlmRequestError(
                f"Anthropic Messages does not support native "
                f"{part['media_type']} files.",
            )
    return converted


def _headers(config: AgentLlmConfig) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "x-api-key": config.api_key,
        "anthropic-version": ANTHROPIC_VERSION,
    }


def _tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    anthropic_tools: list[dict[str, Any]] = []
    for tool in tools:
        function = tool_function(tool)
        name = str(function.get("name") or "").strip()
        if not name:
            continue

        anthropic_tools.append(
            {
                "name": name,
                "description": str(function.get("description") or ""),
                "input_schema": portable_tool_schema(function.get("parameters")),
                "eager_input_streaming": True,
            },
        )

    return anthropic_tools


def _message_from_payload(payload: dict[str, Any]) -> LlmAssistantMessage:
    tool_calls = _tool_calls(payload)
    thinking_blocks = _thinking_blocks_from_content(payload.get("content"))
    return LlmAssistantMessage(
        content=_text(payload),
        tool_calls=tool_calls,
        reasoning=_thinking_text(thinking_blocks),
        usage=anthropic_usage(payload),
        stop_reason="tool_calls"
        if tool_calls
        else map_stop_reason(payload.get("stop_reason")),
        response_id=str(payload.get("id") or "") or None,
        provider_state={"thinking_blocks": thinking_blocks} if thinking_blocks else {},
    )


def _text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for block in payload.get("content") or []:
        if not isinstance(block, dict) or block.get("type") != "text":
            continue
        text = block.get("text")
        if isinstance(text, str):
            parts.append(text)

    return "".join(parts).strip()


def _tool_calls(payload: dict[str, Any]) -> list[LlmToolCall]:
    tool_calls: list[LlmToolCall] = []
    for block in payload.get("content") or []:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        tool_id = str(block.get("id") or "")
        name = str(block.get("name") or "").strip()
        arguments = block.get("input")
        if not isinstance(arguments, dict) or not tool_id or not name:
            continue
        tool_calls.append(
            LlmToolCall(
                id=tool_id,
                name=name,
                arguments=arguments,
                raw_arguments=_json_object(arguments),
            ),
        )

    return tool_calls


def _thinking_blocks_from_content(content: Any) -> list[dict[str, Any]]:
    if not isinstance(content, list):
        return []

    blocks: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        normalized = _thinking_block(block)
        if normalized:
            blocks.append(normalized)
    return blocks


def _thinking_blocks_from_state(provider_state: Any) -> list[dict[str, Any]]:
    if not isinstance(provider_state, dict):
        return []
    return _thinking_blocks_from_content(provider_state.get("thinking_blocks"))


def _thinking_block(block: dict[str, Any]) -> dict[str, Any] | None:
    block_type = block.get("type")
    if block_type == "thinking":
        thinking = block.get("thinking")
        signature = block.get("signature")
        if not isinstance(thinking, str):
            return None
        normalized: dict[str, Any] = {
            "type": "thinking",
            "thinking": thinking,
        }
        if isinstance(signature, str):
            normalized["signature"] = signature
        return normalized

    if block_type == "redacted_thinking":
        data = block.get("data")
        if isinstance(data, str):
            return {"type": "redacted_thinking", "data": data}

    return None


def _thinking_text(blocks: list[dict[str, Any]]) -> str:
    return "".join(
        str(block["thinking"]) for block in blocks if block.get("type") == "thinking"
    ).strip()


def _thinking_provider_state(
    blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    normalized = [
        thinking_block
        for block in blocks
        if (thinking_block := _thinking_block(block)) is not None
    ]
    return {"thinking_blocks": normalized} if normalized else {}


def _content_block_index(event: dict[str, Any]) -> int:
    index = event.get("index")
    return index if isinstance(index, int) else 0


def _safe_json_object(raw_arguments: str) -> dict[str, Any]:
    tool_call = parsed_tool_call(
        call_id="anthropic-replay",
        name="replayed_tool",
        raw_arguments=raw_arguments,
    )
    return tool_call.arguments


def _json_object(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


def _stream_error_message(event: dict[str, Any]) -> str:
    error = event.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
        error_type = error.get("type")
        if error_type:
            return f"Model provider stream failed: {error_type}"

    return "Model provider stream failed."
