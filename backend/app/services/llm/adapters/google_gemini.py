from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

from ..common import (
    async_post_json,
    async_stream_json,
    gemini_usage,
    map_stop_reason,
    message_content_text,
    openai_style_function_tools,
    parsed_tool_call,
    provider_base_url,
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


async def complete(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
) -> LlmAssistantMessage:
    """Call Gemini's interaction endpoint and require visible text."""

    payload = await _post_interaction(config, messages)
    message = _message_from_payload(payload)
    if message.content:
        return message

    raise LlmRequestError("Model provider returned an empty response.")


async def complete_tool_call(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> LlmAssistantMessage:
    """Ask Gemini to choose zero or more tools."""

    payload = await _post_interaction(config, messages, tools)
    return _message_from_payload(payload)


async def stream(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
) -> AsyncIterator[LlmStreamEvent]:
    """Stream Gemini interaction SSE events into the shared LLM contract."""

    payload = {**gemini_payload(config, messages), "stream": True}
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    # Gemini interaction chunks may contain cumulative output snapshots instead
    # of strict deltas. Track already emitted text so the agent still receives
    # true incremental deltas.
    emitted_text = ""
    emitted_reasoning = ""
    # The last stream payload is the only place that may include final usage,
    # stop reason, and provider continuation steps.
    final_payload: dict[str, Any] | None = None

    async for event in async_stream_json(
        f"{provider_base_url(config.base_url)}/interactions?alt=sse",
        headers=_headers(config),
        payload=payload,
        timeout_seconds=config.timeout_seconds,
    ):
        if _is_error_event(event):
            raise LlmRequestError(_stream_error_message(event))

        final_payload = event
        text, emitted_text = _stream_delta(
            _stream_text(event),
            emitted_text,
        )
        if text:
            content_parts.append(text)
            yield LlmStreamEvent(type="text_delta", delta=text)

        reasoning, emitted_reasoning = _stream_delta(
            _stream_reasoning(event),
            emitted_reasoning,
        )
        if reasoning:
            reasoning_parts.append(reasoning)
            yield LlmStreamEvent(type="reasoning_delta", delta=reasoning)

    if final_payload is None:
        raise LlmRequestError("Model provider returned an empty stream.")

    message = _message_from_payload(final_payload)
    stream_content = "".join(content_parts).strip()
    stream_reasoning = "".join(reasoning_parts).strip()
    if stream_content and not message.content:
        message = replace(message, content=stream_content)
    if stream_reasoning and not message.reasoning:
        message = replace(message, reasoning=stream_reasoning)

    yield LlmStreamEvent(type="done", message=message)


async def _post_interaction(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return await async_post_json(
        f"{provider_base_url(config.base_url)}/interactions",
        headers=_headers(config),
        payload=gemini_payload(config, messages, tools),
        timeout_seconds=config.timeout_seconds,
    )


def gemini_payload(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    system, non_system = system_and_messages(messages)
    payload: dict[str, Any] = {
        "model": config.model,
        "store": False,
        "input": gemini_input(non_system),
    }
    if system:
        # Interactions accepts system instructions as a first-class field. Do
        # not fold them into user text or the agent's hard rules lose weight.
        payload["system_instruction"] = system
    if tools:
        payload["tools"] = openai_style_function_tools(tools)

    return payload


def gemini_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    input_items: list[dict[str, Any]] = []
    tool_call_names: dict[str, str] = {}

    for message in messages:
        role = message.get("role")
        if role == "tool":
            tool_call_id = str(message.get("tool_call_id") or "")
            # Gemini function results need the function name as well as the id.
            # Recover the name from earlier replayed function_call steps.
            input_items.append(
                {
                    "type": "function_result",
                    "name": tool_call_names.get(tool_call_id, "tool_result"),
                    "call_id": tool_call_id,
                    "result": [
                        {
                            "type": "text",
                            "text": message_content_text(message.get("content")),
                        },
                    ],
                },
            )
            continue

        if role == "assistant":
            provider_state = message.get("provider_state")
            continuation_steps = (
                provider_state.get("steps")
                if isinstance(provider_state, dict)
                else None
            )
            if isinstance(continuation_steps, list):
                appended_provider_step = False
                for step in continuation_steps:
                    if not isinstance(step, dict):
                        continue
                    # Interactions are stateless. Gemini expects prior model-
                    # generated thought/function_call steps before matching
                    # function_result items, so replay only the compact
                    # continuation state stored by `_message_from_payload`.
                    input_items.append(step)
                    appended_provider_step = True
                    if step.get("type") == "function_call":
                        call_id = str(step.get("id") or step.get("call_id") or "")
                        name = str(step.get("name") or "").strip()
                        if call_id and name:
                            tool_call_names[call_id] = name
                if appended_provider_step:
                    continue

            for tool_call in message.get("tool_calls") or []:
                function = tool_function(tool_call)
                tool_id = str(tool_call.get("id") or "")
                name = str(function.get("name") or "").strip()
                raw_arguments = str(function.get("arguments") or "{}")
                if not tool_id or not name:
                    continue
                tool_call_names[tool_id] = name
                input_items.append(
                    {
                        "type": "function_call",
                        "id": tool_id,
                        "name": name,
                        "arguments": parsed_tool_call(
                            call_id=tool_id,
                            name=name,
                            raw_arguments=raw_arguments,
                        ).arguments,
                    },
                )
            continue

        if role == "user":
            text = message_content_text(message.get("content"))
            input_items.append(
                {
                    "type": "user_input",
                    "content": [{"type": "text", "text": text}],
                },
            )

    return input_items


def _headers(config: AgentLlmConfig) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "x-goog-api-key": config.api_key,
    }


def _message_from_payload(payload: dict[str, Any]) -> LlmAssistantMessage:
    tool_calls = _tool_calls(payload)
    provider_steps = _provider_steps(payload)
    return LlmAssistantMessage(
        content=_text(payload),
        tool_calls=tool_calls,
        usage=gemini_usage(payload),
        stop_reason="tool_calls" if tool_calls else _stop_reason(payload),
        response_id=str(payload.get("id") or "") or None,
        # Gemini requires prior thought/function steps to be replayed before
        # tool results; store only those continuation steps, not the raw payload.
        provider_state={"steps": provider_steps} if provider_steps else {},
    )


def _text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text") or payload.get("outputText")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    parts: list[str] = []
    for step in payload.get("steps") or []:
        if not isinstance(step, dict):
            continue
        text = step.get("text")
        if isinstance(text, str):
            parts.append(text)
        for block in step.get("content") or []:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])

    return "".join(parts).strip()


def _tool_calls(payload: dict[str, Any]) -> list[LlmToolCall]:
    tool_calls: list[LlmToolCall] = []
    for step in payload.get("steps") or []:
        if not isinstance(step, dict) or step.get("type") != "function_call":
            continue
        call_id = str(step.get("id") or step.get("call_id") or "")
        name = str(step.get("name") or "").strip()
        arguments = step.get("arguments")
        if not isinstance(arguments, dict) or not call_id or not name:
            continue
        import json

        raw_arguments = json.dumps(arguments, ensure_ascii=False)
        tool_calls.append(
            LlmToolCall(
                id=call_id,
                name=name,
                arguments=arguments,
                raw_arguments=raw_arguments,
            ),
        )

    return tool_calls


def _provider_steps(payload: dict[str, Any]) -> list[dict[str, Any]]:
    steps = payload.get("steps")
    if not isinstance(steps, list):
        return []

    return [dict(step) for step in steps if isinstance(step, dict)]


def _stop_reason(payload: dict[str, Any]) -> LlmStopReason:
    for key in ("finishReason", "finish_reason", "stopReason", "stop_reason"):
        reason = payload.get(key)
        if reason:
            return map_stop_reason(reason)

    return "stop"


def _stream_text(payload: dict[str, Any]) -> str:
    for key in ("delta", "text", "output_text", "outputText"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value

    candidates = payload.get("candidates")
    if isinstance(candidates, list):
        parts: list[str] = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content")
            if not isinstance(content, dict):
                continue
            for part in content.get("parts") or []:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    parts.append(part["text"])
        if parts:
            return "".join(parts)

    return _text(payload)


def _stream_reasoning(payload: dict[str, Any]) -> str:
    reasoning = payload.get("reasoning") or payload.get("thought")
    if isinstance(reasoning, str) and reasoning:
        return reasoning

    parts: list[str] = []
    for step in payload.get("steps") or []:
        if (
            isinstance(step, dict)
            and step.get("type") == "thought"
            and isinstance(step.get("text"), str)
        ):
            parts.append(step["text"])

    return "".join(parts)


def _stream_delta(value: str, emitted: str) -> tuple[str, str]:
    if not value:
        return "", emitted
    if value.startswith(emitted):
        delta = value[len(emitted) :]
        return delta, value

    return value, f"{emitted}{value}"


def _is_error_event(payload: dict[str, Any]) -> bool:
    event_type = str(payload.get("type") or payload.get("_event") or "").lower()
    return event_type in {"error", "failed"} or isinstance(payload.get("error"), dict)


def _stream_error_message(payload: dict[str, Any]) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
        code = error.get("code") or error.get("status") or error.get("type")
        if code:
            return f"Model provider stream failed: {code}"

    return "Model provider stream failed."
