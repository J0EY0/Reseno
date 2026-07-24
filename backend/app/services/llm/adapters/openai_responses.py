from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError

from ..common import (
    async_openai_client,
    attr_or_item,
    close_async_stream,
    image_data_url,
    map_stop_reason,
    message_content_parts,
    message_content_text,
    object_dict,
    openai_style_function_tools,
    parsed_tool_call,
    raise_openai_error,
    responses_usage,
    system_and_messages,
    tool_function,
)
from ..errors import LlmRequestError
from ..types import (
    AgentLlmConfig,
    LlmAssistantMessage,
    LlmStopReason,
    LlmStreamEvent,
    LlmToolCall,
)


def supports_native_attachment(media_type: str) -> bool:
    """Responses accepts PDF originals as current-request input files."""

    return media_type == "application/pdf"


async def complete(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
) -> LlmAssistantMessage:
    """Call the OpenAI Responses API and require visible text."""

    try:
        response = await async_openai_client(config).responses.create(
            **responses_params(config, messages),
        )
    except (APIStatusError, APITimeoutError, APIConnectionError, APIError) as exc:
        raise_openai_error(exc)

    message = _message_from_response(response)
    if message.content:
        return message

    raise LlmRequestError("Model provider returned an empty response.")


async def complete_tool_call(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> LlmAssistantMessage:
    """Ask the Responses API to choose zero or more function tools."""

    try:
        response = await async_openai_client(config).responses.create(
            **responses_params(config, messages, tools=tools),
        )
    except (APIStatusError, APITimeoutError, APIConnectionError, APIError) as exc:
        raise_openai_error(exc)

    return _message_from_response(response)


async def stream(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
) -> AsyncIterator[LlmStreamEvent]:
    """Stream OpenAI Responses events into the provider-independent contract."""

    stream_response = None
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    # The terminal Responses stream event carries authoritative usage, response
    # id, and stop status. Deltas are emitted immediately for UX, then the final
    # response object becomes the unified `done` message.
    final_response: object | None = None
    try:
        stream_response = await async_openai_client(config).responses.create(
            **responses_params(config, messages, stream=True),
        )
        async for event in stream_response:
            event_type = str(attr_or_item(event, "type") or "")
            if event_type == "response.output_text.delta":
                delta = attr_or_item(event, "delta")
                if isinstance(delta, str) and delta:
                    content_parts.append(delta)
                    yield LlmStreamEvent(type="text_delta", delta=delta)
                continue

            if event_type in {
                "response.reasoning_text.delta",
                "response.reasoning_summary_text.delta",
            }:
                delta = attr_or_item(event, "delta")
                if isinstance(delta, str) and delta:
                    reasoning_parts.append(delta)
                    yield LlmStreamEvent(type="reasoning_delta", delta=delta)
                continue

            if event_type in {"response.completed", "response.incomplete"}:
                final_response = attr_or_item(event, "response")
                continue

            if event_type in {"response.failed", "error"}:
                raise LlmRequestError(_stream_error_message(event))
    except (APIStatusError, APITimeoutError, APIConnectionError, APIError) as exc:
        raise_openai_error(exc)
    finally:
        if stream_response is not None:
            await close_async_stream(stream_response)

    message = (
        _message_from_response(final_response)
        if final_response is not None
        else LlmAssistantMessage(
            content="".join(content_parts).strip(),
            reasoning="".join(reasoning_parts).strip(),
            stop_reason="unknown",
        )
    )
    if reasoning_parts and not message.reasoning:
        message = LlmAssistantMessage(
            content=message.content,
            tool_calls=message.tool_calls,
            validation_errors=message.validation_errors,
            reasoning="".join(reasoning_parts).strip(),
            usage=message.usage,
            stop_reason=message.stop_reason,
            response_id=message.response_id,
            provider_state=message.provider_state,
        )
    yield LlmStreamEvent(type="done", message=message)


def responses_params(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    stream: bool = False,
) -> dict[str, Any]:
    instructions, input_items = responses_input(messages)
    # Responses uses `instructions` plus typed `input` items instead of Chat
    # Completions' flat message array. Keep that split here so agent messages
    # remain provider-independent.
    params: dict[str, Any] = {
        "model": config.model,
        "input": input_items,
        "store": False,
        "stream": stream,
    }
    if instructions:
        params["instructions"] = instructions
    if config.temperature is not None:
        params["temperature"] = config.temperature
    if config.top_p is not None:
        params["top_p"] = config.top_p
    if config.max_tokens:
        params["max_output_tokens"] = config.max_tokens
    if config.supports_thinking and config.thinking_enabled:
        params["reasoning"] = {"effort": "medium"}
    if tools:
        params["tools"] = openai_style_function_tools(tools)
        params["tool_choice"] = "auto"
        params["parallel_tool_calls"] = False

    return params


def responses_input(
    messages: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    system, non_system = system_and_messages(messages)
    input_items: list[dict[str, Any]] = []
    for message in non_system:
        role = message.get("role")
        if role == "tool":
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": str(message.get("tool_call_id") or ""),
                    "output": message_content_text(message.get("content")),
                },
            )
            continue

        if role == "assistant":
            content = message_content_text(message.get("content")).strip()
            if content:
                input_items.append({"role": "assistant", "content": content})
            # Tool-call history must be replayed as completed `function_call`
            # input items so later `function_call_output` items have a call_id
            # to attach to.
            for tool_call in message.get("tool_calls") or []:
                function = tool_function(tool_call)
                call_id = str(tool_call.get("id") or "")
                name = str(function.get("name") or "").strip()
                raw_arguments = str(function.get("arguments") or "{}")
                if call_id and name:
                    input_items.append(
                        {
                            "type": "function_call",
                            "call_id": call_id,
                            "name": name,
                            "arguments": raw_arguments,
                            "status": "completed",
                        },
                    )
            continue

        if role in {"user", "developer"}:
            input_items.append(
                {
                    "role": role,
                    "content": _responses_content(message.get("content")),
                },
            )

    return system, input_items


def _responses_content(content: Any) -> str | list[dict[str, str]]:
    parts = message_content_parts(content)
    if not any(part["type"] in {"image", "file"} for part in parts):
        return message_content_text(content)

    converted: list[dict[str, str]] = []
    for part in parts:
        if part["type"] == "text":
            converted.append({"type": "input_text", "text": part["text"]})
        elif part["type"] == "image":
            converted.append(
                {
                    "type": "input_image",
                    "image_url": image_data_url(part),
                },
            )
        elif supports_native_attachment(part["media_type"]):
            converted.append(
                {
                    "type": "input_file",
                    "filename": part["filename"],
                    "file_data": image_data_url(part),
                },
            )
        else:
            raise LlmRequestError(
                f"Responses does not support native {part['media_type']} files.",
            )
    return converted


def _message_from_response(response: object) -> LlmAssistantMessage:
    content = _response_output_text(response)
    tool_calls = _response_tool_calls(response)
    stop_reason = _response_stop_reason(response, has_tool_calls=bool(tool_calls))

    return LlmAssistantMessage(
        content=content,
        tool_calls=tool_calls,
        usage=responses_usage(response),
        stop_reason=stop_reason,
        response_id=getattr(response, "id", None),
    )


def _response_output_text(response: object) -> str:
    output_text = getattr(response, "output_text", "")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    output = getattr(response, "output", None)
    if not isinstance(output, list):
        return ""

    parts: list[str] = []
    for item in output:
        data = object_dict(item)
        if data.get("type") != "message":
            continue
        for block in data.get("content") or []:
            if not isinstance(block, dict):
                continue
            text = block.get("text") or block.get("output_text")
            if isinstance(text, str):
                parts.append(text)

    return "".join(parts).strip()


def _response_tool_calls(response: object) -> list[LlmToolCall]:
    output = getattr(response, "output", None)
    if not isinstance(output, list):
        return []

    tool_calls: list[LlmToolCall] = []
    for item in output:
        data = object_dict(item)
        if data.get("type") != "function_call":
            continue

        name = str(data.get("name") or "").strip()
        call_id = str(data.get("call_id") or data.get("id") or "").strip()
        raw_arguments = str(data.get("arguments") or "{}")
        if not name or not call_id:
            continue

        tool_calls.append(
            parsed_tool_call(
                call_id=call_id,
                name=name,
                raw_arguments=raw_arguments,
            ),
        )

    return tool_calls


def _response_stop_reason(
    response: object,
    *,
    has_tool_calls: bool,
) -> LlmStopReason:
    if has_tool_calls:
        return "tool_calls"

    incomplete_details = getattr(response, "incomplete_details", None)
    # Truncation is reported through `incomplete_details.reason`, not only the
    # top-level status. Preserve it so the agent can ask for a larger budget.
    reason = getattr(incomplete_details, "reason", None)
    if reason:
        return map_stop_reason(reason)

    status = getattr(response, "status", None)
    return map_stop_reason(status) if status else "stop"


def _stream_error_message(event: object) -> str:
    error = attr_or_item(event, "error")
    if error is None:
        response = attr_or_item(event, "response")
        error = attr_or_item(response, "error")

    message = attr_or_item(error, "message")
    if isinstance(message, str) and message.strip():
        return message.strip()

    code = attr_or_item(error, "code") or attr_or_item(error, "type")
    if code:
        return f"Model provider stream failed: {code}"

    return "Model provider stream failed."
