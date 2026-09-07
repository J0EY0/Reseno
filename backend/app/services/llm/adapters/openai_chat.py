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
    minimax_reasoning_details,
    object_dict,
    official_deepseek_thinking,
    official_minimax_reasoning_split,
    openai_chat_function_tools,
    openai_chat_usage,
    parsed_tool_call,
    raise_openai_error,
)
from ..errors import LlmRequestError
from ..types import (
    AgentLlmConfig,
    LlmAssistantMessage,
    LlmPrompt,
    LlmRequestContext,
    LlmStopReason,
    LlmStreamEvent,
    LlmToolCall,
)

_STREAM_USAGE_TARGETS = frozenset(
    {
        ("cloud", "deepseek"),
        ("cloud", "minimax"),
        ("cloud", "moonshot"),
        ("cloud", "qwen"),
        ("local", "ollama"),
        ("local", "sglang"),
        ("local", "vllm"),
    },
)


def supports_native_attachment(media_type: str) -> bool:
    """OpenAI-compatible Chat Completions exposes no generic file contract."""

    return False


async def complete(
    config: AgentLlmConfig,
    prompt: LlmPrompt,
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
                    prompt,
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

        message = _message_from_response(response, config=config)
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
    """Ask an OpenAI-compatible chat endpoint to choose zero or more tools."""

    # Let the model batch independent reads. The Agent loop validates the whole
    # batch, runs reads concurrently, and defers writes that would depend on
    # observations the model has not seen yet.
    client = async_openai_client(config)
    params = _tool_completion_params(
        config,
        prompt,
        tools,
        request_context=request_context,
    )
    try:
        try:
            response = await client.chat.completions.create(**params)
        except (
            APIStatusError,
            APITimeoutError,
            APIConnectionError,
            APIError,
        ) as exc:
            raise_openai_error(exc)

        return _message_from_response(response, config=config)
    finally:
        await close_async_client(client)


def _tool_completion_params(
    config: AgentLlmConfig,
    prompt: LlmPrompt,
    tools: list[dict[str, Any]],
    *,
    request_context: LlmRequestContext | None = None,
) -> dict[str, Any]:
    """Build provider-facing params without weakening local tool validation."""

    params = {
        **chat_completion_params(
            config,
            prompt,
            stream=False,
            request_context=request_context,
        ),
        "tools": openai_chat_function_tools(tools),
    }
    if not official_deepseek_thinking(config):
        # `auto` permits either text or tools; it does not force a call. Keep it
        # for compatible runtimes such as vLLM whose protocol default is `none`.
        # Official DeepSeek thinking rejects the field, so only a thinking-on
        # request to that exact endpoint relies on its default tool selection.
        # A native Off request uses ordinary non-thinking tool semantics.
        params["tool_choice"] = "auto"
    return params


async def stream(
    config: AgentLlmConfig,
    prompt: LlmPrompt,
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
    usage = None
    terminal_seen = False
    minimax_reasoning = ""
    try:
        stream_response = await client.chat.completions.create(
            **_stream_completion_params(
                config,
                prompt,
                request_context=request_context,
            ),
        )
        async for chunk in stream_response:
            if chunk_usage := openai_chat_usage(chunk):
                usage = chunk_usage
            if not chunk.choices:
                continue

            choice = chunk.choices[0]
            finish_reason = getattr(choice, "finish_reason", None)
            if finish_reason:
                terminal_seen = True
                stop_reason = map_stop_reason(finish_reason)

            delta = choice.delta
            reasoning = delta_text(delta, ("reasoning_content", "reasoning"))
            if official_minimax_reasoning_split(config):
                details = object_dict(delta).get("reasoning_details")
                if details is not None:
                    verified_details = minimax_reasoning_details(
                        {
                            "model": config.model,
                            "reasoning_details": details,
                        },
                        model=config.model,
                    )
                    current_reasoning = "".join(
                        str(detail["text"]) for detail in verified_details
                    )
                    reasoning = (
                        current_reasoning[len(minimax_reasoning) :]
                        if current_reasoning.startswith(minimax_reasoning)
                        else current_reasoning
                    )
                    minimax_reasoning = current_reasoning
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
            reasoning=(minimax_reasoning or "".join(reasoning_parts)).strip(),
            usage=usage,
            stop_reason=stop_reason,
        ),
    )


def _stream_completion_params(
    config: AgentLlmConfig,
    prompt: LlmPrompt,
    *,
    request_context: LlmRequestContext | None = None,
) -> dict[str, Any]:
    params = chat_completion_params(
        config,
        prompt,
        stream=True,
        request_context=request_context,
    )
    if _supports_stream_usage(config):
        params["stream_options"] = {"include_usage": True}
    return params


def _supports_stream_usage(config: AgentLlmConfig) -> bool:
    return (
        config.provider_kind,
        config.provider,
    ) in _STREAM_USAGE_TARGETS and config.api_family == "openai_compatible_chat"


async def stream_tool_call(
    config: AgentLlmConfig,
    prompt: LlmPrompt,
    tools: list[dict[str, Any]],
    *,
    request_context: LlmRequestContext | None = None,
) -> AsyncIterator[LlmStreamEvent]:
    """Stream tool-call activity and publish only one complete terminal call."""

    client = async_openai_client(config)
    stream_response = None
    state = ChatCompletionStreamState()
    terminal_reason: LlmStopReason | None = None
    minimax_details: list[dict[str, Any]] = []
    minimax_reasoning = ""
    params = {
        **_tool_completion_params(
            config,
            prompt,
            tools,
            request_context=request_context,
        ),
        "stream": True,
    }
    if _supports_stream_usage(config):
        params["stream_options"] = {"include_usage": True}
    try:
        stream_response = await client.chat.completions.create(**params)

        async for chunk in stream_response:
            if official_minimax_reasoning_split(config):
                for choice in chunk.choices:
                    details = object_dict(choice.delta).get("reasoning_details")
                    if details is not None:
                        # MiniMax emits cumulative reasoning_details snapshots,
                        # while OpenAI's generic accumulator expects indexed
                        # list deltas. Preserve the latest verified snapshot
                        # here and remove it before generic tool accumulation.
                        minimax_details = minimax_reasoning_details(
                            {
                                "model": config.model,
                                "reasoning_details": details,
                            },
                            model=config.model,
                        )
                        current_reasoning = "".join(
                            str(detail["text"]) for detail in minimax_details
                        )
                        reasoning_delta = (
                            current_reasoning[len(minimax_reasoning) :]
                            if current_reasoning.startswith(minimax_reasoning)
                            else current_reasoning
                        )
                        minimax_reasoning = current_reasoning
                        choice.delta.model_extra.pop("reasoning_details", None)
                        if reasoning_delta:
                            yield LlmStreamEvent(
                                type="reasoning_delta",
                                delta=reasoning_delta,
                            )
                        else:
                            yield LlmStreamEvent(type="activity")
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

    message = _message_from_response(
        state.current_completion_snapshot,
        config=config,
    )
    if minimax_details:
        message = replace(
            message,
            reasoning="".join(str(detail["text"]) for detail in minimax_details),
            provider_state={
                "model": config.model,
                "reasoning_details": minimax_details,
            },
        )
    if terminal_reason != "tool_calls" and message.tool_calls:
        message = replace(message, tool_calls=[])
    yield LlmStreamEvent(
        type="done",
        message=message,
    )


def _message_from_response(
    response: object,
    *,
    config: AgentLlmConfig,
) -> LlmAssistantMessage:
    choices = getattr(response, "choices", None)
    if not choices:
        raise LlmRequestError("Model provider returned an empty response.")

    choice = choices[0]
    sdk_message = choice.message
    content = sdk_message.content if isinstance(sdk_message.content, str) else ""
    raw_reasoning_details = getattr(sdk_message, "reasoning_details", None)
    if raw_reasoning_details is None:
        raw_reasoning_details = object_dict(sdk_message).get("reasoning_details")
    reasoning_details = (
        minimax_reasoning_details(
            {
                "model": config.model,
                "reasoning_details": raw_reasoning_details,
            },
            model=config.model,
        )
        if official_minimax_reasoning_split(config)
        and raw_reasoning_details is not None
        else []
    )
    reasoning = (
        "".join(str(detail["text"]) for detail in reasoning_details)
        if reasoning_details
        else delta_text(sdk_message, ("reasoning_content", "reasoning"))
    )
    tool_calls = _tool_calls_from_message(sdk_message)
    finish_reason = getattr(choice, "finish_reason", None)
    stop_reason = map_stop_reason(finish_reason)

    return LlmAssistantMessage(
        content=content.strip(),
        tool_calls=tool_calls,
        reasoning=reasoning.strip(),
        usage=openai_chat_usage(response),
        stop_reason=stop_reason,
        provider_state=(
            {
                "model": config.model,
                "reasoning_details": reasoning_details,
            }
            if reasoning_details
            else {}
        ),
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
