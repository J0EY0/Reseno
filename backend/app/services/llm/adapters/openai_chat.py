from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError

from ..common import (
    async_openai_client,
    chat_completion_params,
    close_async_stream,
    delta_text,
    map_stop_reason,
    openai_chat_usage,
    parsed_tool_call,
    raise_openai_error,
    unsupported_parallel_tool_calls,
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
    """OpenAI-compatible Chat Completions exposes no generic file contract."""

    return False


async def complete(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
) -> LlmAssistantMessage:
    """Call an OpenAI-compatible chat endpoint and require visible text."""

    try:
        response = await async_openai_client(config).chat.completions.create(
            **chat_completion_params(config, messages, stream=False),
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
    """Ask an OpenAI-compatible chat endpoint to choose zero or more tools."""

    # Disable parallel tool calls at the provider boundary. The agent loop
    # executes one assistant turn as a single transaction, then validates every
    # returned call before running any of them.
    params = {
        **chat_completion_params(config, messages, stream=False),
        "tools": tools,
        "tool_choice": "auto",
        "parallel_tool_calls": False,
    }
    try:
        response = await async_openai_client(config).chat.completions.create(**params)
    except APIStatusError as exc:
        if not unsupported_parallel_tool_calls(exc):
            raise_openai_error(exc)

        # Several OpenAI-compatible local/cloud endpoints reject the OpenAI
        # parallel-tool flag even though they support ordinary tool calls.
        params.pop("parallel_tool_calls", None)
        try:
            response = await async_openai_client(config).chat.completions.create(
                **params,
            )
        except (
            APIStatusError,
            APITimeoutError,
            APIConnectionError,
            APIError,
        ) as fallback_exc:
            raise_openai_error(fallback_exc)
    except (APITimeoutError, APIConnectionError, APIError) as exc:
        raise_openai_error(exc)

    return _message_from_response(response)


async def stream(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
) -> AsyncIterator[LlmStreamEvent]:
    """Stream OpenAI-compatible chat deltas into the internal event shape.

    OpenAI-compatible providers disagree on where reasoning deltas live. Read
    both common field names here so the agent stream does not need provider
    checks or provider-specific SSE payloads.
    """

    stream_response = None
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    stop_reason: LlmStopReason = "unknown"
    response_id: str | None = None
    try:
        stream_response = await async_openai_client(config).chat.completions.create(
            **chat_completion_params(config, messages, stream=True),
        )
        async for chunk in stream_response:
            if response_id is None:
                response_id = getattr(chunk, "id", None)
            if not chunk.choices:
                continue

            choice = chunk.choices[0]
            finish_reason = getattr(choice, "finish_reason", None)
            if finish_reason:
                stop_reason = map_stop_reason(finish_reason)

            delta = choice.delta
            reasoning = delta_text(delta, ("reasoning_content", "reasoning"))
            if reasoning:
                reasoning_parts.append(reasoning)
                yield LlmStreamEvent(type="reasoning_delta", delta=reasoning)

            content = delta_text(delta, ("content",))
            if content:
                content_parts.append(content)
                yield LlmStreamEvent(type="text_delta", delta=content)
    except (APIStatusError, APITimeoutError, APIConnectionError, APIError) as exc:
        raise_openai_error(exc)
    finally:
        if stream_response is not None:
            await close_async_stream(stream_response)

    yield LlmStreamEvent(
        type="done",
        message=LlmAssistantMessage(
            content="".join(content_parts).strip(),
            reasoning="".join(reasoning_parts).strip(),
            stop_reason=stop_reason,
            response_id=response_id,
        ),
    )


def _message_from_response(response: object) -> LlmAssistantMessage:
    choices = getattr(response, "choices", None)
    if not choices:
        raise LlmRequestError("Model provider returned an empty response.")

    choice = choices[0]
    sdk_message = choice.message
    content = sdk_message.content if isinstance(sdk_message.content, str) else ""
    tool_calls = _tool_calls_from_message(sdk_message)
    finish_reason = getattr(choice, "finish_reason", None)
    stop_reason: LlmStopReason = (
        "tool_calls" if tool_calls else map_stop_reason(finish_reason)
    )

    return LlmAssistantMessage(
        content=content.strip(),
        tool_calls=tool_calls,
        usage=openai_chat_usage(response),
        stop_reason=stop_reason,
        response_id=getattr(response, "id", None),
    )


def _tool_calls_from_message(message: object) -> list[LlmToolCall]:
    tool_calls: list[LlmToolCall] = []
    for tool_call in getattr(message, "tool_calls", None) or []:
        function = getattr(tool_call, "function", None)
        name = getattr(function, "name", "")
        raw_arguments = getattr(function, "arguments", "") or ""
        if not name:
            continue

        tool_calls.append(
            parsed_tool_call(
                call_id=tool_call.id,
                name=name,
                raw_arguments=raw_arguments,
            ),
        )

    return tool_calls
