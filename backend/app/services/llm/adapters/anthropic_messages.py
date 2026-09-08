from __future__ import annotations

from collections.abc import AsyncIterator
from copy import deepcopy
from dataclasses import replace
from typing import Any

from app.services.thinking import ThinkingControl, can_project_thinking_off

from ..common import (
    ANTHROPIC_VERSION,
    anthropic_usage,
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
)
from ..errors import LlmRequestError
from ..output_budget import (
    anthropic_request_output_tokens,
    resolve_request_output_budget,
)
from ..tool_schema import portable_tool_schema
from ..types import (
    AgentLlmConfig,
    LlmAssistantMessage,
    LlmInputMessage,
    LlmPrompt,
    LlmStopReason,
    LlmStreamEvent,
    LlmToolCall,
    LlmUsage,
    LlmWebSource,
)

_ANTHROPIC_OFFICIAL_BASE_URL = "https://api.anthropic.com/v1"
_ANTHROPIC_LEGACY_MIN_THINKING_TOKENS = 1_024
_ANTHROPIC_AUTO_LEGACY_THINKING_CEILING_TOKENS = 16_000
_ANTHROPIC_SERVER_TOOL_CONTINUATION_LIMIT = 4
_ANTHROPIC_WEB_TOOLS = (
    {
        "type": "web_search_20250305",
        "name": "web_search",
        "allowed_callers": ["direct"],
    },
    {
        "type": "web_fetch_20250910",
        "name": "web_fetch",
        "citations": {"enabled": True},
    },
)


def supports_native_attachment(media_type: str) -> bool:
    """Anthropic Messages accepts PDF document blocks."""

    return media_type == "application/pdf"


async def complete(
    config: AgentLlmConfig,
    messages: list[LlmInputMessage],
) -> LlmAssistantMessage:
    """Call Anthropic Messages and require visible text."""

    payload = await _post_messages(config, messages)
    message = _message_from_payload(payload, model=config.model)
    if message.content:
        return message

    raise LlmRequestError("Model provider returned an empty response.")


async def complete_tool_call(
    config: AgentLlmConfig,
    messages: list[LlmInputMessage],
    tools: list[dict[str, Any]],
) -> LlmAssistantMessage:
    """Ask Anthropic Messages to choose zero or more tools."""

    payload = await _post_messages(config, messages, tools)
    return _message_from_payload(payload, model=config.model)


async def stream_tool_call(
    config: AgentLlmConfig,
    messages: list[LlmInputMessage],
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
    messages: list[LlmInputMessage],
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
    messages: list[LlmInputMessage],
    tools: list[dict[str, Any]] | None = None,
) -> AsyncIterator[LlmStreamEvent]:
    continuation_messages = list(messages)
    content_blocks: list[dict[str, Any]] = []
    reasoning_parts: list[str] = []
    usage: LlmUsage | None = None

    for continuation_count in range(
        _ANTHROPIC_SERVER_TOOL_CONTINUATION_LIMIT + 1,
    ):
        terminal: LlmAssistantMessage | None = None
        request_config = resolve_request_output_budget(
            config, LlmPrompt(messages=continuation_messages), tools,
        )
        events = _stream_messages_once(request_config, continuation_messages, tools)
        try:
            async for event in events:
                if event.type == "done":
                    terminal = event.message
                    continue
                yield event
        finally:
            await close_async_stream(events)

        if terminal is None:
            raise LlmRequestError("Model provider stream ended before completion.")
        state_blocks = _content_blocks_from_state(
            terminal.provider_state,
            current_model=config.model,
        )
        content_blocks.extend(state_blocks)
        if terminal.reasoning:
            reasoning_parts.append(terminal.reasoning)
        usage = _sum_usage(usage, terminal.usage)

        if terminal.stop_reason != "unknown":
            content, sources = _text_and_sources(content_blocks)
            yield LlmStreamEvent(
                type="done",
                message=replace(
                    terminal,
                    content=content,
                    reasoning="".join(reasoning_parts).strip(),
                    usage=usage,
                    provider_state=_content_blocks_provider_state(
                        content_blocks,
                        model=config.model,
                    ),
                    sources=sources,
                ),
            )
            return

        if continuation_count == _ANTHROPIC_SERVER_TOOL_CONTINUATION_LIMIT:
            raise LlmRequestError(
                "Anthropic server tool exceeded its continuation limit.",
            )
        continuation_messages.append(
            {
                "role": "assistant",
                "content": None,
                "provider_state": terminal.provider_state,
            },
        )
        yield LlmStreamEvent(type="activity")

    raise AssertionError("unreachable")


async def _stream_messages_once(
    config: AgentLlmConfig,
    messages: list[LlmInputMessage],
    tools: list[dict[str, Any]] | None = None,
) -> AsyncIterator[LlmStreamEvent]:
    payload = {
        **_payload(config, messages, tools),
        "stream": True,
    }
    reasoning_parts: list[str] = []
    content_blocks_by_index: dict[int, dict[str, Any]] = {}
    thinking_blocks_by_index: dict[int, dict[str, Any]] = {}
    tool_inputs_by_index: dict[int, dict[str, Any]] = {}
    response_id: str | None = None
    stop_reason: LlmStopReason = "unknown"
    raw_stop_reason = ""
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
            if event_type == "ping":
                # A provider heartbeat is observable request activity even when
                # adaptive thinking is omitted from the visible stream. Passing
                # it through prevents the shared idle timer from aborting a
                # healthy long-running reasoning turn.
                yield LlmStreamEvent(type="activity")
                continue

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
                    preserved_block = deepcopy(block)
                    content_blocks_by_index[index] = preserved_block
                    thinking_blocks_by_index[index] = preserved_block
                    if thinking_block.get("type") == "redacted_thinking":
                        yield LlmStreamEvent(type="activity")
                    continue
                block_type = block.get("type")
                if block_type == "text":
                    content_blocks_by_index[index] = deepcopy(block)
                    continue
                if block_type in {
                    "web_search_tool_result",
                    "web_fetch_tool_result",
                }:
                    if not config.use_native_web_search:
                        raise LlmRequestError(
                            "Model provider returned an unexpected server tool result.",
                        )
                    content_blocks_by_index[index] = deepcopy(block)
                    yield LlmStreamEvent(type="activity")
                    continue
                if block_type not in {"tool_use", "server_tool_use"}:
                    raise LlmRequestError(
                        "Model provider returned invalid assistant content.",
                    )
                if block_type == "tool_use" and tools is None:
                    raise LlmRequestError(
                        "Model provider returned an unexpected tool call.",
                    )
                if block_type == "server_tool_use" and (
                    not config.use_native_web_search
                    or block.get("name") not in {"web_search", "web_fetch"}
                ):
                    raise LlmRequestError(
                        "Model provider returned an unexpected server tool call.",
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
                    "type": block_type,
                    "raw_parts": [],
                    "closed": False,
                }
                content_blocks_by_index[index] = deepcopy(block)
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
                        block = content_blocks_by_index.setdefault(
                            _content_block_index(event),
                            {"type": "text", "text": ""},
                        )
                        block["text"] = str(block.get("text") or "") + text
                        yield LlmStreamEvent(type="text_delta", delta=text)
                    continue
                if delta_type == "citations_delta":
                    citation = delta.get("citation")
                    block = content_blocks_by_index.get(
                        _content_block_index(event),
                    )
                    if isinstance(citation, dict) and block is not None:
                        citations = block.setdefault("citations", [])
                        if isinstance(citations, list):
                            citations.append(citation)
                            yield LlmStreamEvent(type="activity")
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
                    raw_stop_reason = str(stop_reason_value)
                    stop_reason = map_stop_reason(stop_reason_value)
                event_usage = event.get("usage")
                if isinstance(event_usage, dict):
                    _merge_usage(usage, event_usage)
                if has_stop_reason or event_usage:
                    yield LlmStreamEvent(type="activity")
                continue

            if event_type == "error":
                raise LlmRequestError(_stream_error_message(event))

            if event_type != "message_stop":
                continue

            if any(
                not bool(tool_input["closed"])
                for tool_input in tool_inputs_by_index.values()
            ):
                raise LlmRequestError(
                    "Model provider stream ended with an incomplete tool call.",
                )
            for index, tool_input in tool_inputs_by_index.items():
                content_blocks_by_index[index]["input"] = _safe_json_object(
                    "".join(tool_input["raw_parts"]),
                )

            client_tool_inputs = {
                index: tool_input
                for index, tool_input in tool_inputs_by_index.items()
                if tool_input["type"] == "tool_use"
            }
            if (stop_reason == "unknown" and raw_stop_reason != "pause_turn") or (
                client_tool_inputs and stop_reason == "stop"
            ):
                raise LlmRequestError(
                    "Model provider returned an invalid stream completion.",
                )

            tool_calls: list[LlmToolCall] = []
            if stop_reason == "tool_calls":
                if not client_tool_inputs:
                    raise LlmRequestError(
                        "Model provider returned an invalid stream completion.",
                    )
                tool_calls = [
                    parsed_tool_call(
                        call_id=str(tool_input["id"]),
                        name=str(tool_input["name"]),
                        raw_arguments="".join(tool_input["raw_parts"]),
                    )
                    for _, tool_input in sorted(client_tool_inputs.items())
                ]

            blocks = [
                block
                for _, block in sorted(
                    content_blocks_by_index.items(),
                )
            ]
            content, sources = _text_and_sources(blocks)
            yield LlmStreamEvent(
                type="done",
                message=LlmAssistantMessage(
                    content=content,
                    tool_calls=tool_calls,
                    reasoning="".join(reasoning_parts).strip(),
                    usage=anthropic_usage({"usage": usage}),
                    stop_reason=stop_reason,
                    provider_state=_content_blocks_provider_state(
                        blocks,
                        model=config.model,
                    ),
                    sources=sources,
                ),
            )
            return
    finally:
        await close_async_stream(provider_stream)

    raise LlmRequestError("Model provider stream ended before completion.")


async def _post_messages(
    config: AgentLlmConfig,
    messages: list[LlmInputMessage],
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    continuation_messages = list(messages)
    content_blocks: list[dict[str, Any]] = []
    usage: dict[str, Any] = {}

    for continuation_count in range(
        _ANTHROPIC_SERVER_TOOL_CONTINUATION_LIMIT + 1,
    ):
        request_config = resolve_request_output_budget(
            config, LlmPrompt(messages=continuation_messages), tools,
        )
        request_payload = _payload(request_config, continuation_messages, tools)
        response = await async_post_json(
            f"{provider_base_url(config.base_url)}/messages",
            headers=_headers(config),
            payload=request_payload,
            timeout_seconds=config.timeout_seconds,
        )
        response_content = response.get("content")
        if not isinstance(response_content, list):
            raise LlmRequestError(
                "Model provider returned invalid assistant content.",
            )
        response_blocks = deepcopy(response_content)
        content_blocks.extend(response_blocks)
        response_usage = response.get("usage")
        if isinstance(response_usage, dict):
            _add_usage(usage, response_usage)

        if response.get("stop_reason") != "pause_turn":
            completed = deepcopy(response)
            completed["content"] = content_blocks
            if usage:
                completed["usage"] = usage
            return completed

        if continuation_count == _ANTHROPIC_SERVER_TOOL_CONTINUATION_LIMIT:
            raise LlmRequestError(
                "Anthropic server tool exceeded its continuation limit.",
            )
        response_blocks = _validated_content_blocks(response_content)
        continuation_messages.append(
            {
                "role": "assistant",
                "content": None,
                "provider_state": _content_blocks_provider_state(
                    response_blocks, model=config.model,
                ),
            },
        )

    raise AssertionError("unreachable")


def _payload(
    config: AgentLlmConfig,
    messages: list[LlmInputMessage],
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    system, provider_messages = anthropic_messages(messages, model=config.model)
    official_anthropic_request = (
        config.provider == "anthropic"
        and config.provider_kind == "cloud"
        and config.api_family == "anthropic_messages"
        and provider_base_url(config.base_url) == _ANTHROPIC_OFFICIAL_BASE_URL
    )
    effective_thinking_control = (
        config.thinking_control if official_anthropic_request else "none"
    )
    if config.thinking_control == "native_off":
        if not can_project_thinking_off(
            provider=config.provider,
            provider_kind=config.provider_kind,
            api_family=config.api_family,
            base_url=config.base_url,
            model=config.model,
        ):
            # Omitting Anthropic's disabled object would restore provider-managed
            # reasoning, violating the saved preference. Stop before network I/O.
            raise LlmRequestError(
                "Thinking Off is unavailable for this model configuration.",
            )
        # The shared projection check is the authority for Off. Do not make the
        # disabled object depend on a second endpoint predicate that could drift.
        effective_thinking_control = "native_off"
    prompt_cache_enabled = official_anthropic_request
    max_tokens = anthropic_request_output_tokens(config)
    thinking = _anthropic_thinking(
        effective_thinking_control,
        max_tokens=max_tokens,
    )
    payload: dict[str, Any] = {
        "model": config.model,
        "max_tokens": max_tokens,
        "messages": provider_messages,
    }
    if prompt_cache_enabled:
        # Anthropic's automatic breakpoint follows the growing conversation
        # while the explicit system/tool breakpoints below preserve the two
        # slower-changing prefixes independently.
        payload["cache_control"] = {"type": "ephemeral"}
    if system:
        if prompt_cache_enabled:
            payload["system"] = [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                },
            ]
        else:
            payload["system"] = system

    if thinking is not None:
        # The discovery-selected action is already valid for this model. Keep
        # sampling and output_config effort absent for every explicit thinking
        # mode: current Anthropic models constrain those controls independently,
        # and Off must mean the exact disabled mode rather than an effort proxy.
        payload["thinking"] = thinking
    else:
        if config.temperature is not None:
            payload["temperature"] = config.temperature
        if config.top_p is not None:
            payload["top_p"] = config.top_p
    anthropic_tools = _tools(
        tools or [],
        include_native_web=config.use_native_web_search,
    )
    if anthropic_tools:
        if prompt_cache_enabled and anthropic_tools:
            anthropic_tools[-1]["cache_control"] = {"type": "ephemeral"}
        payload["tools"] = anthropic_tools

    return payload


def _anthropic_thinking(
    control: ThinkingControl,
    *,
    max_tokens: int,
) -> dict[str, Any] | None:
    """Project a discovered Anthropic thinking action onto one request.

    The runtime passes a capability-checked action, not a model name, so this
    Adapter never owns a model-ID table. ``native_off`` uses Anthropic's exact
    disabled request object. Adaptive models receive provider-managed Auto.
    Older enabled-only models need a manual budget: the API requires at least
    1,024 thinking tokens and, without interleaving, requires that budget to
    remain strictly below the request's inclusive ``max_tokens``.

    The 16K ceiling is Reseno's Auto quality policy. It prevents legacy
    thinking from consuming an arbitrarily large discovered output capability;
    it is distinct from both a user's max_tokens override and the durable
    visible-summary budget used by history compaction.
    """

    if control == "native_off":
        return {"type": "disabled"}
    if control == "native_auto":
        return {"type": "adaptive"}
    if control != "native_budget":
        return None

    if max_tokens <= _ANTHROPIC_LEGACY_MIN_THINKING_TOKENS:
        raise LlmRequestError(
            "Anthropic legacy thinking requires max_tokens greater than 1024.",
        )

    return {
        "type": "enabled",
        "budget_tokens": min(
            _ANTHROPIC_AUTO_LEGACY_THINKING_CEILING_TOKENS,
            max(
                _ANTHROPIC_LEGACY_MIN_THINKING_TOKENS,
                max_tokens // 2,
            ),
        ),
    }


def anthropic_messages(
    messages: list[LlmInputMessage],
    *,
    model: str | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    system, non_system = system_and_messages(messages)
    converted: list[dict[str, Any]] = []
    previous_was_tool = False

    for message in non_system:
        if message["role"] == "tool":
            tool_use_id = str(message.get("tool_call_id") or "")
            # Anthropic represents tool results as user-role content blocks
            # keyed by the original tool_use id, not as a separate `tool` role.
            # Results for one parallel tool batch must share the immediately
            # following user content array and retain neutral transcript order.
            tool_result = {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": message_content_text(message.get("content")),
            }
            if previous_was_tool:
                converted[-1]["content"].append(tool_result)
            else:
                converted.append(
                    {
                        "role": "user",
                        "content": [tool_result],
                    },
                )
            previous_was_tool = True
            continue

        previous_was_tool = False
        if message["role"] == "assistant":
            provider_state = message.get("provider_state")
            if provider_state is not None and provider_state != {}:
                # Adaptive thinking may interleave signed thinking, visible
                # text, redacted thinking, and tool calls. Anthropic requires
                # the exact assistant content sequence before tool results;
                # rebuilding it from the neutral transcript can invalidate the
                # continuation even when the visible text is unchanged.
                replay_blocks = _content_blocks_from_state(
                    provider_state,
                    current_model=model,
                )
                converted.append(
                    {"role": "assistant", "content": replay_blocks},
                )
                continue

            blocks: list[dict[str, Any]] = []
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

        if message["role"] == "user":
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


def _tools(
    tools: list[dict[str, Any]],
    *,
    include_native_web: bool = False,
) -> list[dict[str, Any]]:
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

    if include_native_web:
        anthropic_tools.extend(deepcopy(_ANTHROPIC_WEB_TOOLS))

    return anthropic_tools


def _message_from_payload(
    payload: dict[str, Any],
    *,
    model: str,
) -> LlmAssistantMessage:
    stop_reason = map_stop_reason(payload.get("stop_reason"))
    tool_calls = _tool_calls(payload) if stop_reason == "tool_calls" else []
    if stop_reason == "tool_calls" and not tool_calls:
        raise LlmRequestError("Model provider returned an invalid tool completion.")
    thinking_blocks = _thinking_blocks_from_content(payload.get("content"))
    text, sources = _text_and_sources(payload.get("content"))
    return LlmAssistantMessage(
        content=text,
        tool_calls=tool_calls,
        reasoning=_thinking_text(thinking_blocks),
        usage=anthropic_usage(payload),
        stop_reason=stop_reason,
        provider_state=_content_blocks_provider_state(
            payload.get("content"),
            model=model,
        ),
        sources=sources,
    )


def _text_and_sources(content: Any) -> tuple[str, list[LlmWebSource]]:
    if not isinstance(content, list):
        return "", []

    parts: list[str] = []
    sources_by_id: dict[str, LlmWebSource] = {}
    fetched_sources_by_title: dict[str, LlmWebSource] = {}

    for block in content:
        if not isinstance(block, dict):
            continue
        for source in _web_sources_from_block(block):
            _remember_source(sources_by_id, source)
            if block.get("type") == "web_fetch_tool_result":
                fetched_sources_by_title[source.title] = source

        if block.get("type") != "text":
            continue
        text = block.get("text")
        if not isinstance(text, str):
            continue

        parts.append(text)
        block_citations = block.get("citations")
        if not isinstance(block_citations, list):
            continue
        for citation in block_citations:
            citation_source = _web_source_from_citation(citation)
            if citation_source is None and isinstance(citation, dict):
                document_title = citation.get("document_title")
                fetched_source = (
                    fetched_sources_by_title.get(document_title)
                    if isinstance(document_title, str)
                    else None
                )
                if fetched_source is not None:
                    cited_text = citation.get("cited_text")
                    citation_source = make_web_source(
                        fetched_source.url,
                        fetched_source.title,
                        cited_text if isinstance(cited_text, str) else "",
                    )
            if citation_source is None:
                continue
            _remember_source(sources_by_id, citation_source)

    return "".join(parts).strip(), list(sources_by_id.values())


def _web_sources_from_block(block: dict[str, Any]) -> list[LlmWebSource]:
    block_type = block.get("type")
    content = block.get("content")
    if block_type == "web_search_tool_result" and isinstance(content, list):
        sources: list[LlmWebSource] = []
        for result in content:
            if (
                not isinstance(result, dict)
                or result.get("type") != "web_search_result"
            ):
                continue
            source = _make_source(
                url=result.get("url"),
                title=result.get("title"),
            )
            if source is not None:
                sources.append(source)
        return sources

    if block_type != "web_fetch_tool_result" or not isinstance(content, dict):
        return []
    if content.get("type") != "web_fetch_result":
        return []
    document = content.get("content")
    title = document.get("title") if isinstance(document, dict) else None
    source = _make_source(url=content.get("url"), title=title)
    return [source] if source is not None else []


def _web_source_from_citation(citation: Any) -> LlmWebSource | None:
    if not isinstance(citation, dict):
        return None
    return _make_source(
        url=citation.get("url"),
        title=citation.get("title"),
        excerpt=citation.get("cited_text"),
    )


def _make_source(
    *,
    url: Any,
    title: Any,
    excerpt: Any = "",
) -> LlmWebSource | None:
    if not isinstance(url, str) or not url.strip():
        return None
    return make_web_source(
        url=url,
        title=title if isinstance(title, str) else "",
        excerpt=excerpt if isinstance(excerpt, str) else "",
    )


def _remember_source(
    sources: dict[str, LlmWebSource],
    source: LlmWebSource,
) -> None:
    existing = sources.get(source.id)
    if existing is None or (not existing.excerpt and source.excerpt):
        sources[source.id] = source


def _tool_calls(payload: dict[str, Any]) -> list[LlmToolCall]:
    tool_calls: list[LlmToolCall] = []
    for block in payload.get("content") or []:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        tool_id = str(block.get("id") or "")
        name = str(block.get("name") or "").strip()
        arguments = block.get("input")
        # Tool-use blocks form one terminal batch. An unidentifiable block
        # cannot be paired with a later tool_result, so never discard it while
        # returning valid siblings for execution.
        if not tool_id.strip() or not name:
            raise LlmRequestError(
                "Model provider returned an invalid tool use batch.",
            )
        if not isinstance(arguments, dict):
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


def _content_blocks_from_state(
    provider_state: Any,
    *,
    current_model: str | None,
) -> list[dict[str, Any]]:
    if not isinstance(provider_state, dict) or set(provider_state) != {
        "model",
        "content_blocks",
    }:
        raise LlmRequestError("Anthropic continuation state is invalid.")

    producing_model = provider_state.get("model")
    blocks = provider_state.get("content_blocks")
    if (
        not isinstance(producing_model, str)
        or not producing_model
        or producing_model != current_model
        or not isinstance(blocks, list)
        or not blocks
        or any(not _valid_content_block(block) for block in blocks)
    ):
        raise LlmRequestError("Anthropic continuation state is invalid.")

    return deepcopy(blocks)


def _content_blocks_provider_state(
    content: Any,
    *,
    model: str,
) -> dict[str, Any]:
    if content is None or content == []:
        return {}
    blocks = _validated_content_blocks(content)

    return {"model": model, "content_blocks": blocks}


def _validated_content_blocks(
    content: Any,
) -> list[dict[str, Any]]:
    if not isinstance(content, list) or any(
        not _valid_content_block(block) for block in content
    ):
        raise LlmRequestError(
            "Model provider returned invalid assistant content.",
        )
    return deepcopy(content)


def _valid_content_block(block: Any) -> bool:
    """Validate replay-critical output without rewriting opaque block fields."""

    if not isinstance(block, dict):
        return False

    block_type = block.get("type")
    if block_type == "text":
        citations = block.get("citations")
        return isinstance(block.get("text"), str) and (
            "citations" not in block or citations is None or isinstance(citations, list)
        )
    if block_type == "thinking":
        return (
            isinstance(block.get("thinking"), str)
            and isinstance(block.get("signature"), str)
            and bool(block["signature"])
        )
    if block_type == "redacted_thinking":
        return isinstance(block.get("data"), str) and bool(block["data"])
    if block_type == "tool_use":
        return (
            isinstance(block.get("id"), str)
            and bool(block["id"])
            and isinstance(block.get("name"), str)
            and bool(block["name"].strip())
            and isinstance(block.get("input"), dict)
        )
    if block_type == "server_tool_use":
        return (
            isinstance(block.get("id"), str)
            and bool(block["id"])
            and block.get("name") in {"web_search", "web_fetch"}
            and isinstance(block.get("input"), dict)
        )
    if block_type in {"web_search_tool_result", "web_fetch_tool_result"}:
        return (
            isinstance(block.get("tool_use_id"), str)
            and bool(block["tool_use_id"])
            and "content" in block
        )

    return False


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


def _content_block_index(event: dict[str, Any]) -> int:
    index = event.get("index")
    return index if isinstance(index, int) else 0


def _merge_usage(target: dict[str, Any], update: dict[str, Any]) -> None:
    """Merge incremental Anthropic usage without dropping nested details."""

    for key, value in update.items():
        current = target.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            target[key] = {**current, **value}
        else:
            target[key] = value


def _add_usage(target: dict[str, Any], update: dict[str, Any]) -> None:
    """Accumulate usage from separate provider requests in one paused turn."""

    for key, value in update.items():
        current = target.get(key)
        if isinstance(value, dict):
            nested = current if isinstance(current, dict) else {}
            _add_usage(nested, value)
            target[key] = nested
        elif isinstance(value, int) and isinstance(current, int):
            target[key] = current + value
        else:
            target[key] = value


def _sum_usage(current: LlmUsage | None, update: LlmUsage | None) -> LlmUsage | None:
    if current is None:
        return update
    if update is None:
        return current

    def total(left: int | None, right: int | None) -> int | None:
        if left is None and right is None:
            return None
        return (left or 0) + (right or 0)

    return LlmUsage(
        input_tokens=total(current.input_tokens, update.input_tokens),
        output_tokens=total(current.output_tokens, update.output_tokens),
        total_tokens=total(current.total_tokens, update.total_tokens),
        cached_input_tokens=total(
            current.cached_input_tokens,
            update.cached_input_tokens,
        ),
        cache_write_input_tokens=total(
            current.cache_write_input_tokens,
            update.cache_write_input_tokens,
        ),
        reasoning_tokens=total(
            current.reasoning_tokens,
            update.reasoning_tokens,
        ),
    )


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
