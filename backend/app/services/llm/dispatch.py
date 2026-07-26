from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from .adapters import anthropic_messages, google_gemini, openai_chat, openai_responses
from .types import (
    AgentLlmConfig,
    LlmAssistantMessage,
    LlmStreamEvent,
    LlmToolCall,
    LlmToolValidationError,
)
from .validation import validate_tool_calls


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
    messages: list[dict[str, Any]],
) -> LlmAssistantMessage:
    """Call the configured provider family and return one assistant message."""

    if config.api_family == "openai_responses":
        return await openai_responses.complete(config, messages)
    if config.api_family == "anthropic_messages":
        return await anthropic_messages.complete(config, messages)
    if config.api_family == "google_gemini":
        return await google_gemini.complete(config, messages)

    return await openai_chat.complete(config, messages)


async def async_complete_tool_call(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> LlmAssistantMessage:
    """Ask the configured provider family to choose tools, then validate them."""

    if config.api_family == "openai_responses":
        message = await openai_responses.complete_tool_call(config, messages, tools)
    elif config.api_family == "anthropic_messages":
        message = await anthropic_messages.complete_tool_call(config, messages, tools)
    elif config.api_family == "google_gemini":
        message = await google_gemini.complete_tool_call(config, messages, tools)
    else:
        message = await openai_chat.complete_tool_call(config, messages, tools)

    valid_tool_calls, validation_errors = validate_tool_calls(message.tool_calls, tools)
    if validation_errors:
        # Tool execution is all-or-nothing for one assistant turn. Executing only
        # the valid subset risks duplicate side effects when the model retries.
        # Return one observation for every proposed call so the retry history
        # explicitly records that the valid calls were not executed either.
        valid_tool_calls = []
        validation_errors = _complete_batch_retry_errors(
            message.tool_calls,
            validation_errors,
        )

    return LlmAssistantMessage(
        content=message.content,
        tool_calls=valid_tool_calls,
        validation_errors=validation_errors,
        reasoning=message.reasoning,
        usage=message.usage,
        stop_reason=message.stop_reason,
        response_id=message.response_id,
        provider_state=_provider_state_for_validation_retry(
            message.provider_state,
            validation_errors,
        ),
    )


def _complete_batch_retry_errors(
    tool_calls: list[LlmToolCall],
    validation_errors: list[LlmToolValidationError],
) -> list[LlmToolValidationError]:
    """Describe an all-or-nothing retry without losing valid tool proposals."""

    errors_by_call_id = {error.tool_call.id: error for error in validation_errors}
    return [
        errors_by_call_id.get(tool_call.id)
        or LlmToolValidationError(
            tool_call=tool_call,
            message=(
                "This tool call was not executed because another call in the "
                "same batch failed validation. Resubmit the complete batch "
                "after correcting every invalid call."
            ),
        )
        for tool_call in tool_calls
    ]


async def async_stream_chat(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
) -> AsyncIterator[LlmStreamEvent]:
    """Stream provider events; final event contains the unified message."""

    if config.api_family == "openai_responses":
        stream = openai_responses.stream(config, messages)
    elif config.api_family == "anthropic_messages":
        stream = anthropic_messages.stream(config, messages)
    elif config.api_family == "google_gemini":
        stream = google_gemini.stream(config, messages)
    else:
        stream = openai_chat.stream(config, messages)

    async for event in stream:
        yield event


def _provider_state_for_validation_retry(
    provider_state: dict[str, Any],
    validation_errors: list[LlmToolValidationError],
) -> dict[str, Any]:
    """Keep provider continuation state aligned with all-or-nothing validation.

    The agent never executes a partial set of tool calls: if any call is invalid,
    every call must be retried. Gemini provider state can contain several
    function_call steps, so retain the complete rejected batch for the model's
    repair turn; every retained call has a matching "not executed" observation.
    """

    if not provider_state or not validation_errors:
        return provider_state

    retry_call_ids = {error.tool_call.id for error in validation_errors}
    steps = provider_state.get("steps")
    if not isinstance(steps, list):
        return provider_state

    filtered_steps: list[dict[str, Any]] = []
    retained_function_call = False
    for step in steps:
        if not isinstance(step, dict):
            continue
        if step.get("type") == "function_call":
            call_id = str(step.get("id") or step.get("call_id") or "")
            if call_id not in retry_call_ids:
                continue
            retained_function_call = True
        filtered_steps.append(step)

    if not retained_function_call:
        return {}

    return {**provider_state, "steps": filtered_steps}
