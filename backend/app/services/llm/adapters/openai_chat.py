from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError
from openai.lib.streaming.chat import ChatCompletionStreamState

from ..common import (
    async_openai_client,
    chat_completion_params,
    close_async_client,
    close_async_stream,
    delta_text,
    map_stop_reason,
    openai_chat_function_tools,
    openai_chat_usage,
    parsed_tool_call,
    raise_openai_error,
    unsupported_parallel_tool_calls,
)
from ..errors import LlmRequestError
from ..types import (
    AgentLlmConfig,
    LlmAssistantMessage,
    LlmInputMessage,
    LlmRequestContext,
    LlmStopReason,
    LlmStreamEvent,
    LlmToolCall,
)


def supports_native_attachment(media_type: str) -> bool:
    """OpenAI-compatible Chat Completions exposes no generic file contract."""

    return False


async def complete(
    config: AgentLlmConfig,
    messages: list[LlmInputMessage],
    *,
    request_context: LlmRequestContext | None = None,
) -> LlmAssistantMessage:
    """Call an OpenAI-compatible chat endpoint and require visible text."""

    client = async_openai_client(config)
    try:
        try:
            response = await client.chat.completions.create(
                **chat_completion_params(
                    config,
                    messages,
                    stream=False,
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
    messages: list[LlmInputMessage],
    tools: list[dict[str, Any]],
    *,
    request_context: LlmRequestContext | None = None,
) -> LlmAssistantMessage:
    """Ask an OpenAI-compatible chat endpoint to choose zero or more tools."""

    # Disable parallel tool calls at the provider boundary. The agent loop
    # executes one assistant turn as a single transaction, then validates every
    # returned call before running any of them.
    client = async_openai_client(config)
    params = _tool_completion_params(
        config,
        messages,
        tools,
        request_context=request_context,
    )
    try:
        try:
            response = await client.chat.completions.create(**params)
        except APIStatusError as exc:
            if not unsupported_parallel_tool_calls(exc):
                raise_openai_error(exc)

            # Several OpenAI-compatible local/cloud endpoints reject the OpenAI
            # parallel-tool flag even though they support ordinary tool calls.
            params.pop("parallel_tool_calls", None)
            try:
                response = await client.chat.completions.create(**params)
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
    finally:
        await close_async_client(client)


def _tool_completion_params(
    config: AgentLlmConfig,
    messages: list[LlmInputMessage],
    tools: list[dict[str, Any]],
    *,
    request_context: LlmRequestContext | None = None,
) -> dict[str, Any]:
    """Build provider-facing params without weakening local tool validation."""

    return {
        **chat_completion_params(
            config,
            messages,
            stream=False,
            request_context=request_context,
        ),
        "tools": openai_chat_function_tools(tools),
        "tool_choice": "auto",
        "parallel_tool_calls": False,
    }


async def stream(
    config: AgentLlmConfig,
    messages: list[LlmInputMessage],
    *,
    request_context: LlmRequestContext | None = None,
) -> AsyncIterator[LlmStreamEvent]:
    """Stream OpenAI-compatible chat deltas into the internal event shape.

    OpenAI-compatible providers disagree on where reasoning deltas live. Read
    both common field names here so the agent stream does not need provider
    checks or provider-specific SSE payloads.
    """

    client = async_openai_client(config)
    stream_response = None
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    stop_reason: LlmStopReason = "unknown"
    response_id: str | None = None
    terminal_seen = False
    try:
        stream_response = await client.chat.completions.create(
            **chat_completion_params(
                config,
                messages,
                stream=True,
                request_context=request_context,
            ),
        )
        async for chunk in stream_response:
            if response_id is None:
                response_id = getattr(chunk, "id", None)
            if not chunk.choices:
                continue

            choice = chunk.choices[0]
            finish_reason = getattr(choice, "finish_reason", None)
            if finish_reason:
                terminal_seen = True
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
        try:
            if stream_response is not None:
                await close_async_stream(stream_response)
        finally:
            await close_async_client(client)

    if not terminal_seen:
        raise LlmRequestError("Model provider stream ended before completion.")

    yield LlmStreamEvent(
        type="done",
        message=LlmAssistantMessage(
            content="".join(content_parts).strip(),
            reasoning="".join(reasoning_parts).strip(),
            stop_reason=stop_reason,
            response_id=response_id,
        ),
    )


async def stream_tool_call(
    config: AgentLlmConfig,
    messages: list[LlmInputMessage],
    tools: list[dict[str, Any]],
    *,
    request_context: LlmRequestContext | None = None,
) -> AsyncIterator[LlmStreamEvent]:
    """Stream tool-call activity and publish only one complete terminal call."""

    client = async_openai_client(config)
    stream_response = None
    state = ChatCompletionStreamState()
    terminal_reason: LlmStopReason | None = None
    params = {
        **_tool_completion_params(
            config,
            messages,
            tools,
            request_context=request_context,
        ),
        "stream": True,
    }
    try:
        try:
            stream_response = await client.chat.completions.create(**params)
        except APIStatusError as exc:
            if not unsupported_parallel_tool_calls(exc):
                raise_openai_error(exc)
            params.pop("parallel_tool_calls", None)
            stream_response = await client.chat.completions.create(**params)

        async for chunk in stream_response:
            state.handle_chunk(chunk)
            if not chunk.choices:
                continue

            for choice in chunk.choices:
                finish_reason = getattr(choice, "finish_reason", None)
                if finish_reason:
                    terminal_reason = map_stop_reason(finish_reason)

                delta = choice.delta
                reasoning = delta_text(delta, ("reasoning_content", "reasoning"))
                if reasoning:
                    yield LlmStreamEvent(type="reasoning_delta", delta=reasoning)

                content = delta_text(delta, ("content",))
                if content:
                    yield LlmStreamEvent(type="text_delta", delta=content)

                if getattr(delta, "tool_calls", None):
                    yield LlmStreamEvent(type="activity")
    except (APIStatusError, APITimeoutError, APIConnectionError, APIError) as exc:
        raise_openai_error(exc)
    finally:
        try:
            if stream_response is not None:
                await close_async_stream(stream_response)
        finally:
            await close_async_client(client)

    if terminal_reason is None:
        raise LlmRequestError("Model provider stream ended before completion.")

    message = _message_from_response(state.current_completion_snapshot)
    if terminal_reason != "tool_calls" and message.tool_calls:
        message = replace(message, tool_calls=[])
    yield LlmStreamEvent(
        type="done",
        message=message,
    )


def _message_from_response(response: object) -> LlmAssistantMessage:
    choices = getattr(response, "choices", None)
    if not choices:
        raise LlmRequestError("Model provider returned an empty response.")

    choice = choices[0]
    sdk_message = choice.message
    content = sdk_message.content if isinstance(sdk_message.content, str) else ""
    reasoning = delta_text(sdk_message, ("reasoning_content", "reasoning"))
    tool_calls = _tool_calls_from_message(sdk_message)
    finish_reason = getattr(choice, "finish_reason", None)
    stop_reason = map_stop_reason(finish_reason)

    return LlmAssistantMessage(
        content=content.strip(),
        tool_calls=tool_calls,
        reasoning=reasoning.strip(),
        usage=openai_chat_usage(response),
        stop_reason=stop_reason,
        response_id=getattr(response, "id", None),
    )


def _tool_calls_from_message(message: object) -> list[LlmToolCall]:
    tool_calls: list[LlmToolCall] = []
    for tool_call in getattr(message, "tool_calls", None) or []:
        function = getattr(tool_call, "function", None)
        call_id = str(getattr(tool_call, "id", "") or "")
        name = str(getattr(function, "name", "") or "")
        raw_arguments = getattr(function, "arguments", "") or ""
        # A terminal tool batch is atomic. Silently dropping one malformed
        # provider block would expose the remaining calls for execution, so
        # reject the entire batch before schema validation or Agent dispatch.
        if not call_id.strip() or not name.strip():
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
