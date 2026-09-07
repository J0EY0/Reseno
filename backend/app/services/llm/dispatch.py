from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

from .activity import iter_with_activity_timeout
from .adapters import anthropic_messages, google_gemini, openai_chat, openai_responses
from .common import close_async_stream, tool_function
from .errors import LlmRequestError
from .output_budget import resolve_request_output_budget
from .tool_schema import portable_tool_schema
from .types import (
    AgentLlmConfig,
    LlmAssistantMessage,
    LlmPrompt,
    LlmRequestContext,
    LlmStreamEvent,
)
from .validation import validate_tool_calls

PROVIDER_FIRST_EVENT_TIMEOUT_SECONDS = 30.0


def supports_native_attachment(
    config: AgentLlmConfig,
    media_type: str,
) -> bool:
    """Return adapter-owned support for one current-request original file."""

    if config.api_family == "openai_responses":
        return openai_responses.supports_native_attachment(media_type)
    if config.api_family == "anthropic_messages":
        return anthropic_messages.supports_native_attachment(media_type)
    if config.api_family == "google_gemini":
        return google_gemini.supports_native_attachment(media_type)

    return openai_chat.supports_native_attachment(media_type)


async def async_complete_chat(
    config: AgentLlmConfig,
    prompt: LlmPrompt,
    *,
    request_context: LlmRequestContext | None = None,
    on_provider_attempt: Callable[[], None] | None = None,
) -> LlmAssistantMessage:
    """Call the configured provider family and return one assistant message."""

    config = resolve_request_output_budget(config, prompt)
    _record_provider_attempt(on_provider_attempt)
    if config.api_family == "openai_responses":
        return await openai_responses.complete(
            config,
            prompt,
            request_context=request_context,
        )
    if config.api_family == "anthropic_messages":
        return await anthropic_messages.complete(config, prompt.messages)
    if config.api_family == "google_gemini":
        return await google_gemini.complete(config, prompt.messages)

    return await openai_chat.complete(
        config,
        prompt,
        request_context=request_context,
    )


async def async_stream_tool_call(
    config: AgentLlmConfig,
    prompt: LlmPrompt,
    tools: list[dict[str, Any]],
    *,
    request_context: LlmRequestContext | None = None,
    on_provider_attempt: Callable[[], None] | None = None,
) -> AsyncIterator[LlmStreamEvent]:
    """Stream one provider-neutral, validated model turn with tools available."""

    config = resolve_request_output_budget(config, prompt, tools)
    _record_provider_attempt(on_provider_attempt)

    if not config.supports_streaming:
        message = await _complete_provider_tool_call(
            config,
            prompt,
            tools,
            request_context=request_context,
        )
        validated = _validated_tool_message(message, tools)
        yield LlmStreamEvent(type="text_delta", delta=validated.content)
        yield LlmStreamEvent(type="done", message=validated)
        return

    stream = _provider_tool_stream(
        config,
        prompt,
        tools,
        request_context=request_context,
    )
    guarded_stream = iter_with_activity_timeout(
        stream,
        first_event_timeout_seconds=PROVIDER_FIRST_EVENT_TIMEOUT_SECONDS,
        idle_timeout_seconds=config.timeout_seconds,
    )
    terminal_seen = False
    try:
        async for event in guarded_stream:
            if terminal_seen:
                raise LlmRequestError(
                    "Model provider returned events after completion.",
                )
            if event.type != "done":
                yield event
                continue
            if event.message is None:
                raise LlmRequestError("Model provider returned an empty response.")
            terminal_seen = True
            yield LlmStreamEvent(
                type="done",
                message=_validated_tool_message(event.message, tools),
            )

        if not terminal_seen:
            raise LlmRequestError("Model provider stream ended before completion.")
    finally:
        await close_async_stream(guarded_stream)


def _provider_tool_stream(
    config: AgentLlmConfig,
    prompt: LlmPrompt,
    tools: list[dict[str, Any]],
    *,
    request_context: LlmRequestContext | None,
) -> AsyncIterator[LlmStreamEvent]:
    if config.api_family == "openai_responses":
        return openai_responses.stream_tool_call(
            config,
            prompt,
            tools,
            request_context=request_context,
        )
    if config.api_family == "anthropic_messages":
        return anthropic_messages.stream_tool_call(config, prompt.messages, tools)
    if config.api_family == "google_gemini":
        return google_gemini.stream_tool_call(config, prompt.messages, tools)
    return openai_chat.stream_tool_call(
        config,
        prompt,
        tools,
        request_context=request_context,
    )


async def _complete_provider_tool_call(
    config: AgentLlmConfig,
    prompt: LlmPrompt,
    tools: list[dict[str, Any]],
    *,
    request_context: LlmRequestContext | None,
) -> LlmAssistantMessage:
    if config.api_family == "openai_responses":
        return await openai_responses.complete_tool_call(
            config,
            prompt,
            tools,
            request_context=request_context,
        )
    if config.api_family == "anthropic_messages":
        return await anthropic_messages.complete_tool_call(
            config,
            prompt.messages,
            tools,
        )
    if config.api_family == "google_gemini":
        return await google_gemini.complete_tool_call(
            config,
            prompt.messages,
            tools,
        )
    return await openai_chat.complete_tool_call(
        config,
        prompt,
        tools,
        request_context=request_context,
    )


def _validated_tool_message(
    message: LlmAssistantMessage,
    tools: list[dict[str, Any]],
) -> LlmAssistantMessage:
    _, validation_errors = validate_tool_calls(
        message.tool_calls,
        _portable_validation_tools(tools),
    )

    return LlmAssistantMessage(
        content=message.content,
        tool_calls=list(message.tool_calls),
        validation_errors=validation_errors,
        reasoning=message.reasoning,
        usage=message.usage,
        stop_reason=message.stop_reason,
        provider_state=message.provider_state,
        sources=list(message.sources),
    )


def _portable_validation_tools(
    tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Validate model output against the same schema subset it received."""

    projected: list[dict[str, Any]] = []
    for tool in tools:
        function = tool_function(tool)
        if not function:
            continue
        projected.append(
            {
                **tool,
                "function": {
                    **function,
                    "parameters": portable_tool_schema(function.get("parameters")),
                },
            },
        )
    return projected


async def async_stream_chat(
    config: AgentLlmConfig,
    prompt: LlmPrompt,
    *,
    request_context: LlmRequestContext | None = None,
    on_provider_attempt: Callable[[], None] | None = None,
) -> AsyncIterator[LlmStreamEvent]:
    """Stream provider events; final event contains the unified message."""

    config = resolve_request_output_budget(config, prompt)
    _record_provider_attempt(on_provider_attempt)
    if config.api_family == "openai_responses":
        stream = openai_responses.stream(
            config,
            prompt,
            request_context=request_context,
        )
    elif config.api_family == "anthropic_messages":
        stream = anthropic_messages.stream(config, prompt.messages)
    elif config.api_family == "google_gemini":
        stream = google_gemini.stream(config, prompt.messages)
    else:
        stream = openai_chat.stream(
            config,
            prompt,
            request_context=request_context,
        )

    guarded_stream = iter_with_activity_timeout(
        stream,
        first_event_timeout_seconds=PROVIDER_FIRST_EVENT_TIMEOUT_SECONDS,
        idle_timeout_seconds=config.timeout_seconds,
    )
    try:
        async for event in guarded_stream:
            yield event
    finally:
        await close_async_stream(guarded_stream)


def _record_provider_attempt(callback: Callable[[], None] | None) -> None:
    """Record one outbound transport attempt without coupling to evaluation."""

    if callback is not None:
        callback()
