from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from ..common import (
    async_post_json,
    async_stream_json,
    close_async_stream,
    make_web_source,
    map_stop_reason,
    message_content_parts,
    message_content_text,
    parsed_tool_call,
    provider_base_url,
    system_and_messages,
    tool_function,
    usage_from_values,
)
from ..errors import LlmRequestError
from ..tool_schema import portable_tool_schema
from ..types import (
    AgentLlmConfig,
    LlmAssistantMessage,
    LlmInputMessage,
    LlmStopReason,
    LlmStreamEvent,
    LlmToolCall,
    LlmUsage,
    LlmWebSource,
)

_NATIVE_WEB_STEP_TYPES = {
    "google_search_call",
    "google_search_result",
    "url_context_call",
    "url_context_result",
}


def supports_native_attachment(media_type: str) -> bool:
    """The current Gemini Interactions adapter exposes image input only."""

    return False


async def complete(
    config: AgentLlmConfig,
    messages: list[LlmInputMessage],
) -> LlmAssistantMessage:
    """Call Gemini's interaction endpoint and require visible text."""

    payload = await _post_interaction(config, messages)
    message = _message_from_payload(payload)
    if message.content:
        return message

    raise LlmRequestError("Model provider returned an empty response.")


async def complete_tool_call(
    config: AgentLlmConfig,
    messages: list[LlmInputMessage],
    tools: list[dict[str, Any]],
) -> LlmAssistantMessage:
    """Ask Gemini to choose zero or more tools."""

    payload = await _post_interaction(config, messages, tools)
    return _message_from_payload(payload)


def stream(
    config: AgentLlmConfig,
    messages: list[LlmInputMessage],
) -> AsyncIterator[LlmStreamEvent]:
    """Stream Gemini interaction SSE events into the shared LLM contract."""

    return _stream_interaction(config, messages)


def stream_tool_call(
    config: AgentLlmConfig,
    messages: list[LlmInputMessage],
    tools: list[dict[str, Any]],
) -> AsyncIterator[LlmStreamEvent]:
    """Stream a Gemini tool selection without exposing partial calls."""

    return _stream_interaction(config, messages, tools)


async def _stream_interaction(
    config: AgentLlmConfig,
    messages: list[LlmInputMessage],
    tools: list[dict[str, Any]] | None = None,
) -> AsyncIterator[LlmStreamEvent]:
    provider_stream = async_stream_json(
        f"{provider_base_url(config.base_url)}/interactions",
        headers={**_headers(config), "Accept": "text/event-stream"},
        payload={
            **gemini_payload(config, messages, tools),
            "stream": True,
        },
        timeout_seconds=config.timeout_seconds,
    )
    steps: dict[int, dict[str, Any]] = {}
    text_parts: dict[int, list[str]] = {}
    reasoning_parts: dict[int, list[str]] = {}
    argument_parts: dict[int, list[str]] = {}
    thought_signatures: dict[int, str] = {}
    text_annotations: dict[int, list[dict[str, Any]]] = {}
    stopped_steps: set[int] = set()

    try:
        async for event in provider_stream:
            if _is_error_event(event):
                raise LlmRequestError("Model provider stream failed.")

            event_type = _stream_event_type(event)
            if event_type == "interaction.created":
                yield LlmStreamEvent(type="activity")
                continue
            if event_type in {
                "interaction.status_update",
                "interaction.in_progress",
                "interaction.requires_action",
            }:
                if event.get("status") in {"in_progress", "requires_action"}:
                    yield LlmStreamEvent(type="activity")
                elif event_type != "interaction.status_update":
                    yield LlmStreamEvent(type="activity")
                continue

            if event_type == "step.start":
                index = _stream_step_index(event)
                if index in steps:
                    raise LlmRequestError(
                        "Model provider returned an invalid stream step lifecycle.",
                    )
                step = event.get("step")
                if not isinstance(step, dict):
                    raise LlmRequestError(
                        "Model provider returned an invalid stream step.",
                    )
                steps[index] = dict(step)
                if step.get("type") == "function_call":
                    initial_arguments = step.get("arguments")
                    if isinstance(initial_arguments, dict) and initial_arguments:
                        argument_parts[index] = [
                            json.dumps(initial_arguments, ensure_ascii=False),
                        ]
                initial_texts, initial_annotations = _initial_stream_text(step)
                if initial_annotations:
                    text_annotations[index] = initial_annotations
                if initial_texts:
                    text_parts[index] = initial_texts
                    for text in initial_texts:
                        yield LlmStreamEvent(type="text_delta", delta=text)
                else:
                    yield LlmStreamEvent(type="activity")
                continue

            if event_type == "step.delta":
                index = _stream_step_index(event)
                if index not in steps:
                    raise LlmRequestError(
                        "Model provider returned an out-of-order stream step.",
                    )
                if index in stopped_steps:
                    raise LlmRequestError(
                        "Model provider returned an invalid stream step lifecycle.",
                    )
                delta = event.get("delta")
                if not isinstance(delta, dict):
                    raise LlmRequestError(
                        "Model provider returned an invalid stream delta.",
                    )
                delta_type = delta.get("type")
                if delta_type == "text" and isinstance(delta.get("text"), str):
                    text = delta["text"]
                    if text:
                        text_parts.setdefault(index, []).append(text)
                        yield LlmStreamEvent(type="text_delta", delta=text)
                elif delta_type == "thought_summary":
                    content = delta.get("content")
                    reasoning = (
                        content.get("text")
                        if isinstance(content, dict)
                        and content.get("type") == "text"
                        and isinstance(content.get("text"), str)
                        else ""
                    )
                    if reasoning:
                        reasoning_parts.setdefault(index, []).append(reasoning)
                        yield LlmStreamEvent(
                            type="reasoning_delta",
                            delta=reasoning,
                        )
                elif delta_type == "thought_signature" and isinstance(
                    delta.get("signature"),
                    str,
                ):
                    signature = delta["signature"]
                    if signature:
                        thought_signatures[index] = signature
                        yield LlmStreamEvent(type="activity")
                elif delta_type == "arguments_delta" and isinstance(
                    delta.get("arguments"),
                    str,
                ):
                    arguments = delta["arguments"]
                    if arguments:
                        argument_parts.setdefault(index, []).append(arguments)
                        yield LlmStreamEvent(type="activity")
                elif delta_type == "text_annotation":
                    annotations = delta.get("annotations")
                    if isinstance(annotations, list):
                        text_annotations.setdefault(index, []).extend(
                            annotation
                            for annotation in annotations
                            if isinstance(annotation, dict)
                        )
                    yield LlmStreamEvent(type="activity")
                elif delta_type in _NATIVE_WEB_STEP_TYPES:
                    _merge_native_web_delta(steps[index], delta)
                    yield LlmStreamEvent(type="activity")
                continue

            if event_type == "step.stop":
                index = _stream_step_index(event)
                if index not in steps:
                    raise LlmRequestError(
                        "Model provider returned an out-of-order stream step.",
                    )
                if index in stopped_steps:
                    raise LlmRequestError(
                        "Model provider returned an invalid stream step lifecycle.",
                    )
                stopped_steps.add(index)
                yield LlmStreamEvent(type="activity")
                continue

            if event_type == "interaction.completed":
                interaction = event.get("interaction")
                if not isinstance(interaction, dict):
                    raise LlmRequestError(
                        "Model provider returned an invalid completed interaction.",
                    )
                if stopped_steps != set(steps):
                    raise LlmRequestError(
                        "Model provider returned an incomplete stream step.",
                    )
                payload = _stream_payload(
                    interaction,
                    steps,
                    text_parts,
                    reasoning_parts,
                    argument_parts,
                    thought_signatures,
                    text_annotations,
                )
                message = _message_from_payload(payload)
                yield LlmStreamEvent(
                    type="done",
                    message=message,
                )
                return

    finally:
        await close_async_stream(provider_stream)

    raise LlmRequestError("Model provider stream ended before completion.")


async def _post_interaction(
    config: AgentLlmConfig,
    messages: list[LlmInputMessage],
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
    messages: list[LlmInputMessage],
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
    provider_tools = _gemini_function_tools(tools or [])
    if config.use_native_web_search:
        provider_tools[:0] = [
            {"type": "google_search"},
            {"type": "url_context"},
        ]
    if provider_tools:
        payload["tools"] = provider_tools
    if config.request_max_output_tokens:
        # Gemini Interactions v1 defines this under generation_config rather
        # than as a top-level field. Merge instead of replacing so future
        # provider-owned generation settings remain intact.
        generation_config = dict(payload.get("generation_config") or {})
        generation_config["max_output_tokens"] = config.request_max_output_tokens
        payload["generation_config"] = generation_config

    return payload


def _gemini_function_tools(
    tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    declarations: list[dict[str, Any]] = []
    for tool in tools:
        function = tool_function(tool)
        name = str(function.get("name") or "").strip()
        if not name:
            continue
        declarations.append(
            {
                "type": "function",
                "name": name,
                "description": str(function.get("description") or ""),
                "parameters": portable_tool_schema(function.get("parameters")),
            },
        )
    return declarations


def gemini_input(messages: list[LlmInputMessage]) -> list[dict[str, Any]]:
    input_items: list[dict[str, Any]] = []
    tool_call_names: dict[str, str] = {}

    for message in messages:
        if message["role"] == "tool":
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

        if message["role"] == "assistant":
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
                    # Interactions are stateless. Replay Gemini's generated
                    # steps exactly once and in their original order.
                    input_items.append(step)
                    appended_provider_step = True
                    if step.get("type") == "function_call":
                        call_id = str(step.get("id") or step.get("call_id") or "")
                        name = str(step.get("name") or "").strip()
                        if call_id and name:
                            tool_call_names[call_id] = name
                if appended_provider_step:
                    continue

            content = _gemini_content(message.get("content"))
            if content:
                input_items.append(
                    {
                        "type": "model_output",
                        "content": content,
                    },
                )

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

        if message["role"] == "user":
            input_items.append(
                {
                    "type": "user_input",
                    "content": _gemini_content(message.get("content")),
                },
            )

    return input_items


def _gemini_content(content: Any) -> list[dict[str, str]]:
    converted: list[dict[str, str]] = []
    for part in message_content_parts(content):
        if part["type"] == "text":
            converted.append({"type": "text", "text": part["text"]})
        elif part["type"] == "image":
            converted.append(
                {
                    "type": "image",
                    "data": part["data"],
                    "mime_type": part["media_type"],
                },
            )
        else:
            raise LlmRequestError(
                "Gemini Interactions does not support native file input.",
            )
    return converted


def _headers(config: AgentLlmConfig) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "x-goog-api-key": config.api_key,
    }


def _message_from_payload(payload: dict[str, Any]) -> LlmAssistantMessage:
    status = payload.get("status")
    if status not in {
        "completed",
        "requires_action",
        "incomplete",
    }:
        raise LlmRequestError(
            "Model provider interaction did not complete successfully.",
        )
    if status == "incomplete":
        payload = {
            **payload,
            "steps": [
                step
                for step in payload.get("steps") or []
                if isinstance(step, dict) and step.get("type") != "function_call"
            ],
        }
    tool_calls = _tool_calls(payload)
    # In Gemini Interactions v1, a client function call is actionable only
    # when the authoritative terminal status is `requires_action`. Treat a
    # call inside `completed` as a malformed batch instead of executing work
    # that the provider explicitly declared finished.
    if status == "completed" and tool_calls:
        raise LlmRequestError(
            "Model provider returned a function call with invalid terminal status.",
        )
    if status == "requires_action" and not tool_calls:
        raise LlmRequestError(
            "Model provider requested action without a valid function call.",
        )
    provider_steps = _provider_steps(payload)
    content, sources = _text_and_sources(payload)
    return LlmAssistantMessage(
        content=content,
        tool_calls=tool_calls,
        reasoning=_reasoning(payload),
        usage=_usage(payload),
        stop_reason="tool_calls" if tool_calls else _stop_reason(payload),
        # Stateless replay needs Gemini's generated and hosted-tool steps in
        # order, without user input or client function results.
        provider_state={"steps": provider_steps} if provider_steps else {},
        sources=sources,
    )


def _text_and_sources(
    payload: dict[str, Any],
) -> tuple[str, list[LlmWebSource]]:
    sources: dict[str, LlmWebSource] = {}
    for step in payload.get("steps") or []:
        if not isinstance(step, dict) or step.get("type") not in {
            "google_search_result",
            "url_context_result",
        }:
            continue
        results = step.get("result")
        if not isinstance(results, list):
            continue
        for result in results:
            if not isinstance(result, dict):
                continue
            url = result.get("url")
            if not isinstance(url, str) or not url.strip():
                continue
            source = make_web_source(
                url=url,
                title=str(result.get("title") or "").strip(),
                excerpt=str(result.get("snippet") or "").strip(),
            )
            sources[source.id] = source

    parts: list[str] = []
    for step in payload.get("steps") or []:
        if not isinstance(step, dict):
            continue
        text = step.get("text")
        if isinstance(text, str):
            parts.append(text)
        for block in step.get("content") or []:
            if not isinstance(block, dict) or not isinstance(block.get("text"), str):
                continue
            text = block["text"]
            for annotation in block.get("annotations") or []:
                if (
                    not isinstance(annotation, dict)
                    or annotation.get("type") != "url_citation"
                ):
                    continue
                url = annotation.get("url")
                if not isinstance(url, str) or not url.strip():
                    continue
                bounds = _gemini_byte_range(
                    text,
                    annotation.get("start_index"),
                    annotation.get("end_index"),
                )
                excerpt = text[bounds[0] : bounds[1]] if bounds else ""
                source = make_web_source(
                    url=url,
                    title=str(annotation.get("title") or "").strip(),
                    excerpt=excerpt,
                )
                existing = sources.get(source.id)
                if existing is None or (not existing.excerpt and source.excerpt):
                    sources[source.id] = source
            parts.append(text)

    return "".join(parts).strip(), list(sources.values())


def _gemini_byte_range(
    text: str,
    start_index: Any,
    end_index: Any,
) -> tuple[int, int] | None:
    if (
        isinstance(start_index, bool)
        or not isinstance(start_index, int)
        or isinstance(end_index, bool)
        or not isinstance(end_index, int)
        or start_index < 0
        or end_index <= start_index
    ):
        return None

    encoded = text.encode("utf-8")
    if end_index > len(encoded):
        return None
    try:
        start = len(encoded[:start_index].decode("utf-8"))
        end = len(encoded[:end_index].decode("utf-8"))
    except UnicodeDecodeError:
        return None
    return start, end


def _reasoning(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for step in payload.get("steps") or []:
        if not isinstance(step, dict) or step.get("type") != "thought":
            continue
        for block in step.get("summary") or []:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])

    return "".join(parts).strip()


def _tool_calls(payload: dict[str, Any]) -> list[LlmToolCall]:
    tool_calls: list[LlmToolCall] = []
    seen_call_ids: set[str] = set()
    for step in payload.get("steps") or []:
        if not isinstance(step, dict) or step.get("type") != "function_call":
            continue
        call_id = str(step.get("id") or step.get("call_id") or "")
        name = str(step.get("name") or "").strip()
        arguments = step.get("arguments")
        if (
            not isinstance(arguments, dict)
            or not call_id
            or not name
            or call_id in seen_call_ids
        ):
            raise LlmRequestError(
                "Model provider returned an invalid function call batch.",
            )
        seen_call_ids.add(call_id)
        raw_arguments = step.get("_raw_arguments")
        if not isinstance(raw_arguments, str):
            raw_arguments = json.dumps(arguments, ensure_ascii=False)
        tool_calls.append(
            parsed_tool_call(
                call_id=call_id,
                name=name,
                raw_arguments=raw_arguments,
            ),
        )

    return tool_calls


def _provider_steps(payload: dict[str, Any]) -> list[dict[str, Any]]:
    steps = payload.get("steps")
    if not isinstance(steps, list):
        return []

    provider_steps: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict) or step.get("type") not in {
            "thought",
            "function_call",
            "google_search_call",
            "google_search_result",
            "model_output",
            "url_context_call",
            "url_context_result",
        }:
            continue
        provider_step = dict(step)
        provider_step.pop("_raw_arguments", None)
        provider_steps.append(provider_step)

    return provider_steps


def _stop_reason(payload: dict[str, Any]) -> LlmStopReason:
    status = payload.get("status")
    if status:
        return map_stop_reason(status)

    for key in ("finishReason", "finish_reason", "stopReason", "stop_reason"):
        reason = payload.get(key)
        if reason:
            return map_stop_reason(reason)

    return "stop"


def _usage(payload: dict[str, Any]) -> LlmUsage | None:
    usage = payload.get("usage")
    if isinstance(usage, dict) and any(
        key in usage
        for key in (
            "total_input_tokens",
            "total_output_tokens",
            "total_cached_tokens",
            "total_thought_tokens",
        )
    ):
        return usage_from_values(
            input_tokens=usage.get("total_input_tokens"),
            output_tokens=usage.get("total_output_tokens"),
            total_tokens=usage.get("total_tokens"),
            cached_input_tokens=usage.get("total_cached_tokens"),
            reasoning_tokens=usage.get("total_thought_tokens"),
        )

    return None


def _stream_event_type(payload: dict[str, Any]) -> str:
    return str(payload.get("event_type") or payload.get("_event") or "").lower()


def _stream_step_index(payload: dict[str, Any]) -> int:
    index = payload.get("index")
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise LlmRequestError("Model provider returned an invalid stream step index.")
    return index


def _stream_payload(
    interaction: dict[str, Any],
    steps: dict[int, dict[str, Any]],
    text_parts: dict[int, list[str]],
    reasoning_parts: dict[int, list[str]],
    argument_parts: dict[int, list[str]],
    thought_signatures: dict[int, str],
    text_annotations: dict[int, list[dict[str, Any]]],
) -> dict[str, Any]:
    assembled_steps: list[dict[str, Any]] = []
    for index in sorted(steps):
        step = dict(steps[index])
        text = "".join(text_parts.get(index, []))
        if text:
            text_block: dict[str, Any] = {"type": "text", "text": text}
            annotations = text_annotations.get(index)
            if annotations:
                text_block["annotations"] = annotations
            step["content"] = [text_block]
        reasoning = "".join(reasoning_parts.get(index, []))
        if reasoning:
            step["summary"] = [{"type": "text", "text": reasoning}]
        signature = thought_signatures.get(index)
        if signature:
            step["signature"] = signature
        raw_arguments = "".join(argument_parts.get(index, []))
        if step.get("type") == "function_call" and raw_arguments:
            call = parsed_tool_call(
                call_id=str(step.get("id") or step.get("call_id") or ""),
                name=str(step.get("name") or "").strip(),
                raw_arguments=raw_arguments,
            )
            if call.parse_error:
                raise LlmRequestError(
                    "Model provider returned invalid function call arguments.",
                )
            step["arguments"] = call.arguments
            step["_raw_arguments"] = raw_arguments
        assembled_steps.append(step)

    return {**interaction, "steps": assembled_steps}


def _initial_stream_text(
    step: dict[str, Any],
) -> tuple[list[str], list[dict[str, Any]]]:
    content = step.get("content")
    if step.get("type") != "model_output" or not isinstance(content, list):
        return [], []

    texts: list[str] = []
    annotations: list[dict[str, Any]] = []
    byte_offset = 0
    for block in content:
        if (
            not isinstance(block, dict)
            or block.get("type") != "text"
            or not isinstance(block.get("text"), str)
        ):
            continue
        text = block["text"]
        if text:
            texts.append(text)
        for annotation in block.get("annotations") or []:
            if not isinstance(annotation, dict):
                continue
            adjusted = dict(annotation)
            for key in ("start_index", "end_index"):
                value = adjusted.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    adjusted[key] = value + byte_offset
            annotations.append(adjusted)
        byte_offset += len(text.encode("utf-8"))
    return texts, annotations


def _merge_native_web_delta(
    step: dict[str, Any],
    delta: dict[str, Any],
) -> None:
    for key, value in delta.items():
        if key == "type":
            continue
        existing = step.get(key)
        if isinstance(existing, list) and isinstance(value, list):
            existing.extend(value)
        elif isinstance(existing, dict) and isinstance(value, dict):
            existing.update(value)
        else:
            step[key] = value


def _is_error_event(payload: dict[str, Any]) -> bool:
    return _stream_event_type(payload) == "error" or isinstance(
        payload.get("error"),
        dict,
    )
