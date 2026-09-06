from __future__ import annotations

from collections.abc import AsyncIterator
from copy import deepcopy
from dataclasses import replace
from typing import Any

from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError

from app.services.thinking import can_project_thinking_off

from ..common import (
    DEFAULT_OPENAI_BASE_URL,
    async_openai_client,
    attr_or_item,
    close_async_client,
    close_async_stream,
    image_data_url,
    make_web_source,
    map_stop_reason,
    message_content_parts,
    message_content_text,
    object_dict,
    openai_prompt_cache_key,
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
    LlmInputMessage,
    LlmPrompt,
    LlmRequestContext,
    LlmStopReason,
    LlmStreamEvent,
    LlmToolCall,
    LlmWebSource,
)

_CONTINUATION_ITEMS_STATE_KEY = "continuation_items"
_INVALID_CONTINUATION_STATE = "OpenAI Responses continuation state is invalid."
_REASONING_STATUSES = {"in_progress", "completed", "incomplete"}
_WEB_SEARCH_STATUSES = {"in_progress", "searching", "completed", "failed"}
_EXPLICIT_CACHE_BREAKPOINT = {"mode": "explicit"}
_ENCRYPTED_REASONING_BASE_URLS = {
    "openai": DEFAULT_OPENAI_BASE_URL,
    "xai": "https://api.x.ai/v1",
}


def supports_native_attachment(media_type: str) -> bool:
    """Responses accepts PDF originals as current-request input files."""

    return media_type == "application/pdf"


async def complete(
    config: AgentLlmConfig,
    prompt: LlmPrompt,
    *,
    request_context: LlmRequestContext | None = None,
) -> LlmAssistantMessage:
    """Call the OpenAI Responses API and require visible text."""

    client = async_openai_client(config)
    try:
        try:
            response = await client.responses.create(
                **responses_params(
                    config,
                    prompt,
                    request_context=request_context,
                ),
            )
        except (
            APIStatusError,
            APITimeoutError,
            APIConnectionError,
            APIError,
        ) as exc:
            raise_openai_error(exc)

        message = _message_from_response(response)
        if message.content:
            return message

        raise LlmRequestError("Model provider returned an empty response.")
    finally:
        await close_async_client(client)


async def complete_tool_call(
    config: AgentLlmConfig,
    prompt: LlmPrompt,
    tools: list[dict[str, Any]],
    *,
    request_context: LlmRequestContext | None = None,
) -> LlmAssistantMessage:
    """Ask the Responses API to choose zero or more function tools."""

    client = async_openai_client(config)
    try:
        try:
            response = await client.responses.create(
                **responses_params(
                    config,
                    prompt,
                    tools=tools,
                    request_context=request_context,
                ),
            )
        except (
            APIStatusError,
            APITimeoutError,
            APIConnectionError,
            APIError,
        ) as exc:
            raise_openai_error(exc)

        return _message_from_response(response)
    finally:
        await close_async_client(client)


async def stream(
    config: AgentLlmConfig,
    prompt: LlmPrompt,
    *,
    request_context: LlmRequestContext | None = None,
) -> AsyncIterator[LlmStreamEvent]:
    """Stream OpenAI Responses events into the provider-independent contract."""

    events = _stream_events(
        config,
        prompt,
        request_context=request_context,
    )
    try:
        async for event in events:
            yield event
    finally:
        await close_async_stream(events)


async def stream_tool_call(
    config: AgentLlmConfig,
    prompt: LlmPrompt,
    tools: list[dict[str, Any]],
    *,
    request_context: LlmRequestContext | None = None,
) -> AsyncIterator[LlmStreamEvent]:
    """Stream tool-call activity without exposing partial executable calls."""

    events = _stream_events(
        config,
        prompt,
        tools=tools,
        request_context=request_context,
    )
    try:
        async for event in events:
            yield event
    finally:
        await close_async_stream(events)


async def _stream_events(
    config: AgentLlmConfig,
    prompt: LlmPrompt,
    *,
    tools: list[dict[str, Any]] | None = None,
    request_context: LlmRequestContext | None = None,
) -> AsyncIterator[LlmStreamEvent]:
    """Own one Responses stream and publish only provider-authoritative state."""

    client = async_openai_client(config)
    stream_response = None
    reasoning_parts: list[str] = []
    # The terminal Responses stream event carries authoritative usage, response
    # id, and stop status. Deltas are emitted immediately for UX, then the final
    # response object becomes the unified `done` message.
    final_response: object | None = None
    terminal_event_type = ""
    try:
        stream_response = await client.responses.create(
            **responses_params(
                config,
                prompt,
                tools=tools,
                stream=True,
                request_context=request_context,
            ),
        )
        async for event in stream_response:
            event_type = str(attr_or_item(event, "type") or "")
            if event_type == "response.output_text.delta":
                delta = attr_or_item(event, "delta")
                if isinstance(delta, str) and delta:
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

            if event_type in {
                "response.function_call_arguments.delta",
                "response.function_call_arguments.done",
                "response.web_search_call.in_progress",
                "response.web_search_call.searching",
                "response.web_search_call.completed",
            }:
                yield LlmStreamEvent(type="activity")
                continue

            if event_type in {
                "response.output_item.added",
                "response.output_item.done",
            }:
                yield LlmStreamEvent(type="activity")
                continue

            if event_type in {"response.completed", "response.incomplete"}:
                final_response = attr_or_item(event, "response")
                terminal_event_type = event_type
                break

            if event_type in {"response.failed", "error"}:
                raise LlmRequestError(_stream_error_message(event))
    except (APIStatusError, APITimeoutError, APIConnectionError, APIError) as exc:
        raise_openai_error(exc)
    finally:
        try:
            if stream_response is not None:
                await close_async_stream(stream_response)
        finally:
            await close_async_client(client)

    if final_response is None:
        raise LlmRequestError(
            "Model provider stream ended before a terminal response.",
        )

    message = _message_from_response(final_response)
    if terminal_event_type != "response.completed" and message.tool_calls:
        message = replace(message, tool_calls=[])
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
            sources=message.sources,
        )
    yield LlmStreamEvent(type="done", message=message)


def responses_params(
    config: AgentLlmConfig,
    prompt: LlmPrompt,
    *,
    tools: list[dict[str, Any]] | None = None,
    stream: bool = False,
    request_context: LlmRequestContext | None = None,
) -> dict[str, Any]:
    instructions, input_items = responses_input(prompt.messages)
    cache_key = openai_prompt_cache_key(config, request_context)
    explicit_cache = (
        _supports_explicit_prompt_cache(config)
        and bool(prompt.stable_prefix_message_counts)
        and _apply_cache_breakpoints(prompt, input_items)
    )
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
    if config.request_max_output_tokens:
        params["max_output_tokens"] = config.request_max_output_tokens

    expected_reasoning_base_url = _ENCRYPTED_REASONING_BASE_URLS.get(config.provider)
    official_reasoning_request = (
        expected_reasoning_base_url is not None
        and config.provider_kind == "cloud"
        and config.api_family == "openai_responses"
        and config.base_url.strip().rstrip("/") == expected_reasoning_base_url
    )
    # Model discovery is the authority for whether ``none`` is an accepted
    # reasoning effort. ``native_off`` therefore maps to the protocol's exact
    # disable value on the official OpenAI or xAI Responses endpoint; every
    # other control omits the field so Auto uses the provider-managed default.
    # Off is never approximated with low/minimal, which can still reason.
    if config.thinking_control == "native_off":
        if not can_project_thinking_off(
            provider=config.provider,
            provider_kind=config.provider_kind,
            api_family=config.api_family,
            base_url=config.base_url,
            model=config.model,
        ):
            # Never turn an explicit Off preference into parameter omission:
            # omission delegates to the provider and may still enable reasoning.
            raise LlmRequestError(
                "Thinking Off is unavailable for this model configuration.",
            )
        params["reasoning"] = {"effort": "none"}
    # The encrypted item is continuation state for stateless Responses calls,
    # not a user-facing thinking control. Request it only from the two official
    # endpoints that define this wire field, regardless of capability metadata.
    include: list[str] = []
    if official_reasoning_request:
        include.append("reasoning.encrypted_content")
    if config.use_native_web_search:
        include.append("web_search_call.action.sources")
    if include:
        params["include"] = include
    if cache_key:
        params["prompt_cache_key"] = cache_key
    if explicit_cache:
        # The installed SDK predates this GPT-5.6 request field, but forwards
        # `extra_body` verbatim. Keep the vendor extension at this Adapter edge.
        params["extra_body"] = {
            "prompt_cache_options": {"mode": "explicit"},
        }
    provider_tools = openai_style_function_tools(tools or [])
    if config.use_native_web_search:
        provider_tools.insert(0, {"type": "web_search"})
    if provider_tools:
        params["tools"] = provider_tools
    if tools:
        # The Agent loop can execute independent reads concurrently and defers
        # writes that would depend on unseen observations.
        params["parallel_tool_calls"] = True

    return params


def _supports_explicit_prompt_cache(config: AgentLlmConfig) -> bool:
    """Restrict GPT-5.6 cache policy to the official Responses endpoint."""

    model = config.model.strip().lower()
    return (
        config.provider == "openai"
        and config.provider_kind == "cloud"
        and config.api_family == "openai_responses"
        and config.base_url.strip().rstrip("/") == DEFAULT_OPENAI_BASE_URL
        and (model == "gpt-5.6" or model.startswith("gpt-5.6-"))
    )


def _apply_cache_breakpoints(
    prompt: LlmPrompt,
    input_items: list[dict[str, Any]],
) -> bool:
    """Project replayable compiler boundaries into OpenAI content blocks.

    Replaying prior boundaries lets GPT-5.6 read an older cached turn while it
    writes the newest prefix, instead of paying for a new isolated cache entry
    on every request. OpenAI considers the latest 50 breakpoints for reads and
    limits writes independently. The compiler owns stability; this Adapter
    never guesses it from list positions or parses product JSON envelopes.
    """

    boundary_counts = set(prompt.stable_prefix_message_counts)
    # Responses hoists every system message into one leading `instructions`
    # string. A system message after a neutral boundary would therefore move
    # changing content before that boundary on the wire, so the declared
    # neutral prefix cannot be represented faithfully.
    earliest_boundary = prompt.stable_prefix_message_counts[0]
    if any(
        message["role"] == "system" for message in prompt.messages[earliest_boundary:]
    ):
        raise LlmRequestError(
            "Declared stable prompt prefix cannot be mapped to an OpenAI "
            "Responses cache breakpoint.",
        )
    boundary_targets: list[tuple[int, list[dict[str, Any]]]] = []
    projected_item_count = 0
    for message_count, message in enumerate(prompt.messages, start=1):
        _, projected_items = responses_input([message])
        projected_item_count += len(projected_items)
        if message_count not in boundary_counts:
            continue

        if not projected_items:
            raise LlmRequestError(
                "Declared stable prompt prefix cannot be mapped to an OpenAI "
                "Responses cache breakpoint.",
            )
        item_index = projected_item_count - 1
        if item_index < 0 or item_index >= len(input_items):
            raise LlmRequestError(
                "Declared stable prompt prefix cannot be mapped to an OpenAI "
                "Responses cache breakpoint.",
            )
        item = input_items[item_index]
        content = (
            _responses_cacheable_content(item.get("content"))
            if item.get("role") in {"user", "assistant"}
            else []
        )
        if not content:
            raise LlmRequestError(
                "Declared stable prompt prefix cannot be mapped to an OpenAI "
                "Responses cache breakpoint.",
            )
        boundary_targets.append((item_index, content))

    if projected_item_count != len(input_items):
        raise LlmRequestError(
            "OpenAI Responses prompt projection is inconsistent.",
        )

    for item_index, content in boundary_targets[-50:]:
        item = input_items[item_index]
        content[-1]["prompt_cache_breakpoint"] = _EXPLICIT_CACHE_BREAKPOINT.copy()
        item["content"] = content
    return bool(boundary_targets)


def _responses_cacheable_content(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "input_text", "text": content}]
    if not isinstance(content, list):
        return []
    blocks = [dict(block) for block in content if isinstance(block, dict)]
    if not blocks or blocks[-1].get("type") not in {
        "input_text",
        "input_image",
        "input_file",
    }:
        return []
    return blocks


def responses_input(
    messages: list[LlmInputMessage],
) -> tuple[str, list[dict[str, Any]]]:
    system, non_system = system_and_messages(messages)
    input_items: list[dict[str, Any]] = []
    for message in non_system:
        if message["role"] == "tool":
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": str(message.get("tool_call_id") or ""),
                    "output": message_content_text(message.get("content")),
                },
            )
            continue

        if message["role"] == "assistant":
            input_items.extend(
                _continuation_items_from_state(message.get("provider_state")),
            )
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

        if message["role"] == "user":
            input_items.append(
                {
                    "role": "user",
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
    content, sources = _response_output(response)
    tool_calls = _response_tool_calls(response)
    stop_reason = _response_stop_reason(response, has_tool_calls=bool(tool_calls))

    return LlmAssistantMessage(
        content=content,
        tool_calls=tool_calls,
        usage=responses_usage(response),
        stop_reason=stop_reason,
        response_id=getattr(response, "id", None),
        provider_state=_continuation_provider_state(response),
        sources=sources,
    )


def _continuation_provider_state(response: object) -> dict[str, Any]:
    output = getattr(response, "output", None)
    if not isinstance(output, list):
        return {}

    continuation_items = [
        deepcopy(item_data)
        for item in output
        for item_data in [object_dict(item)]
        if item_data.get("type") in {"reasoning", "web_search_call"}
    ]
    return (
        {_CONTINUATION_ITEMS_STATE_KEY: continuation_items}
        if continuation_items
        else {}
    )


def _continuation_items_from_state(provider_state: Any) -> list[dict[str, Any]]:
    # `store=False` prevents OpenAI from recovering server tool calls and hidden
    # reasoning by response id. Replay the ordered items unchanged; this state
    # belongs solely to the Responses adapter.
    if provider_state is None or provider_state == {}:
        return []

    if not isinstance(provider_state, dict) or set(provider_state) != {
        _CONTINUATION_ITEMS_STATE_KEY,
    }:
        raise LlmRequestError(_INVALID_CONTINUATION_STATE)

    items = provider_state.get(_CONTINUATION_ITEMS_STATE_KEY)
    if not isinstance(items, list) or not items:
        raise LlmRequestError(_INVALID_CONTINUATION_STATE)

    validated: list[dict[str, Any]] = []
    for item in items:
        if not _valid_continuation_item(item):
            raise LlmRequestError(_INVALID_CONTINUATION_STATE)
        validated.append(deepcopy(item))
    return validated


def _valid_continuation_item(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    if item.get("type") == "reasoning":
        return _valid_reasoning_item(item)
    if item.get("type") == "web_search_call":
        return _valid_web_search_item(item)
    return False


def _valid_reasoning_item(item: Any) -> bool:
    if not isinstance(item, dict) or item.get("type") != "reasoning":
        return False
    if not isinstance(item.get("id"), str) or not item["id"].strip():
        return False
    if not isinstance(item.get("encrypted_content"), str):
        return False
    if not item["encrypted_content"].strip():
        return False

    summary = item.get("summary")
    if not isinstance(summary, list) or any(
        not isinstance(block, dict) for block in summary
    ):
        return False

    status = item.get("status")
    if status is not None and status not in _REASONING_STATUSES:
        return False
    content = item.get("content")
    return content is None or (
        isinstance(content, list) and all(isinstance(block, dict) for block in content)
    )


def _valid_web_search_item(item: dict[str, Any]) -> bool:
    if not isinstance(item.get("id"), str) or not item["id"].strip():
        return False
    if item.get("status") not in _WEB_SEARCH_STATUSES:
        return False
    action = item.get("action")
    return isinstance(action, dict) and action.get("type") in {
        "search",
        "open_page",
        "find_in_page",
    }


def _response_output(response: object) -> tuple[str, list[LlmWebSource]]:
    sources_by_id = {source.id: source for source in _web_search_call_sources(response)}
    text, annotation_sources = _response_text_annotations(response)
    for source in annotation_sources:
        sources_by_id[source.id] = source
    return text.strip(), list(sources_by_id.values())


def _response_text_annotations(
    response: object,
) -> tuple[str, list[LlmWebSource]]:
    """Return output text plus URL annotations in combined-text coordinates."""

    output = getattr(response, "output", None)
    if not isinstance(output, list):
        output_text = getattr(response, "output_text", "")
        return (output_text if isinstance(output_text, str) else ""), []

    parts: list[str] = []
    sources: list[LlmWebSource] = []
    for item in output:
        data = object_dict(item)
        if data.get("type") != "message":
            continue
        for block in data.get("content") or []:
            if not isinstance(block, dict):
                continue
            text = block.get("text") or block.get("output_text")
            if not isinstance(text, str):
                continue
            parts.append(text)
            for annotation in block.get("annotations") or []:
                annotation_data = object_dict(annotation)
                if annotation_data.get("type") != "url_citation":
                    continue
                url = annotation_data.get("url")
                if not isinstance(url, str) or not url.strip():
                    continue
                source = make_web_source(
                    url,
                    title=str(annotation_data.get("title") or ""),
                )
                sources.append(source)

    if parts:
        return "".join(parts), sources
    output_text = getattr(response, "output_text", "")
    return (output_text if isinstance(output_text, str) else ""), sources


def _web_search_call_sources(response: object) -> list[LlmWebSource]:
    output = getattr(response, "output", None)
    if not isinstance(output, list):
        return []

    sources: list[LlmWebSource] = []
    for item in output:
        data = object_dict(item)
        if data.get("type") != "web_search_call":
            continue
        action = data.get("action")
        if not isinstance(action, dict):
            continue
        candidates = action.get("sources") or []
        if not isinstance(candidates, list):
            candidates = []
        action_url = action.get("url")
        if isinstance(action_url, str) and action_url.strip():
            candidates = [*candidates, {"url": action_url}]
        for candidate in candidates:
            candidate_data = object_dict(candidate)
            url = candidate_data.get("url")
            if isinstance(url, str) and url.strip():
                sources.append(make_web_source(url))

    return sources


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
        call_id = str(data.get("call_id") or "").strip()
        raw_arguments = str(data.get("arguments") or "{}")
        if not name or not call_id:
            # Responses output is an atomic terminal batch. If one function
            # block cannot be correlated to a name and call id, exposing only
            # its valid siblings could execute an incomplete provider intent.
            raise LlmRequestError(
                "Model provider returned an invalid function call batch.",
            )

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
    incomplete_details = getattr(response, "incomplete_details", None)
    # Truncation is reported through `incomplete_details.reason`, not only the
    # top-level status. Preserve it so the agent can ask for a larger budget.
    reason = getattr(incomplete_details, "reason", None)
    if reason:
        return map_stop_reason(reason)

    status = getattr(response, "status", None)
    status_reason = map_stop_reason(status) if status else "stop"
    if status_reason in {"length", "content_filter", "error"}:
        return status_reason
    if has_tool_calls:
        return "tool_calls"
    return status_reason


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
