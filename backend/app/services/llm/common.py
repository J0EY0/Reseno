from __future__ import annotations

import json
from collections.abc import AsyncIterator
from copy import deepcopy
from inspect import isawaitable
from typing import Any

import httpx
from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
)

from .errors import LlmRequestError
from .tool_schema import portable_tool_schema
from .types import LlmStopReason, LlmToolCall, LlmUsage

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
REQUEST_TIMEOUT_SECONDS = 60
DEFAULT_MAX_OUTPUT_TOKENS = 4096
ANTHROPIC_VERSION = "2023-06-01"


def openai_base_url(base_url: str) -> str:
    """Return the OpenAI SDK base URL from either a root or completions URL."""

    normalized = base_url.strip().rstrip("/") or DEFAULT_OPENAI_BASE_URL
    if normalized.endswith("/chat/completions"):
        return normalized[: -len("/chat/completions")].rstrip("/")

    return normalized


def async_openai_client(config: Any) -> AsyncOpenAI:
    """Build an async SDK client for one request-scoped model config."""

    return AsyncOpenAI(
        api_key=config.api_key or "local",
        base_url=openai_base_url(config.base_url),
        timeout=max(5, config.timeout_seconds),
    )


async def close_async_stream(stream: object) -> None:
    """Close provider streams regardless of sync or async close semantics."""

    close = getattr(stream, "close", None)
    if not callable(close):
        return

    result = close()
    if isawaitable(result):
        await result


def provider_error_excerpt(error: APIStatusError) -> str:
    """Build a bounded provider error message without headers or secrets."""

    response_text = error.response.text.strip()
    if not response_text:
        return f"Model provider returned HTTP {error.status_code}."

    return f"Model provider returned HTTP {error.status_code}: {response_text[:240]}"


def raise_openai_error(error: Exception) -> None:
    """Normalize SDK exceptions to the runtime's public error type."""

    if isinstance(error, APIStatusError):
        raise LlmRequestError(
            provider_error_excerpt(error),
            status_code=error.status_code,
        ) from error
    if isinstance(error, APITimeoutError):
        raise LlmRequestError("Model provider request timed out.") from error
    if isinstance(error, APIConnectionError):
        raise LlmRequestError(f"Model provider request failed: {error}") from error
    if isinstance(error, APIError):
        raise LlmRequestError(f"Model provider request failed: {error}") from error
    raise error


def unsupported_parallel_tool_calls(error: APIStatusError) -> bool:
    """Return whether an OpenAI-compatible provider rejected this parameter."""

    response_text = error.response.text.lower()
    if "parallel_tool_calls" not in response_text:
        return False

    return any(
        marker in response_text
        for marker in (
            "unsupported",
            "not supported",
            "unknown",
            "unrecognized",
            "invalid parameter",
            "extra inputs",
        )
    )


def chat_completion_params(
    config: Any,
    messages: list[dict[str, Any]],
    *,
    stream: bool,
) -> dict[str, Any]:
    """Build OpenAI-compatible chat params, omitting unset optional knobs."""

    params: dict[str, Any] = {
        "model": config.model,
        "messages": openai_chat_messages(messages),
        "stream": stream,
    }
    if config.temperature is not None:
        params["temperature"] = config.temperature
    if config.top_p is not None:
        params["top_p"] = config.top_p
    if config.max_tokens:
        params["max_tokens"] = config.max_tokens

    return params


def openai_style_function_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return flat function-tool payloads for Responses/Gemini-style APIs.

    Chat Completions keeps tools nested under `{"type": "function", "function": ...}`.
    Responses and Gemini interactions use a flat function object instead, so keep
    that provider family shape here rather than reusing chat-completion payloads.
    """

    function_tools: list[dict[str, Any]] = []
    for tool in tools:
        function = tool_function(tool)
        name = str(function.get("name") or "").strip()
        if not name:
            continue

        function_tools.append(
            {
                "type": "function",
                "name": name,
                "description": str(function.get("description") or ""),
                "parameters": portable_tool_schema(function.get("parameters")),
                "strict": False,
            },
        )

    return function_tools


def openai_chat_function_tools(
    tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Copy Chat Completions tools and project only their input schemas."""

    provider_tools: list[dict[str, Any]] = []
    for tool in tools:
        function = tool_function(tool)
        name = str(function.get("name") or "").strip()
        if not name:
            continue

        provider_tool = deepcopy(tool)
        provider_function = provider_tool.get("function")
        if not isinstance(provider_function, dict):
            continue
        provider_function["parameters"] = portable_tool_schema(
            function.get("parameters"),
        )
        provider_tools.append(provider_tool)

    return provider_tools


def delta_text(delta: object, field_names: tuple[str, ...]) -> str:
    """Read streamed SDK delta fields, including provider-specific extras."""

    for field_name in field_names:
        value = attr_or_item(delta, field_name)
        if value is None and hasattr(delta, "model_extra"):
            extra = delta.model_extra
            if isinstance(extra, dict):
                value = extra.get(field_name)

        if isinstance(value, str) and value:
            return value

    return ""


def parsed_tool_call(
    *,
    call_id: str,
    name: str,
    raw_arguments: str,
) -> LlmToolCall:
    """Parse tool JSON while preserving invalid raw arguments for repair."""

    if not raw_arguments.strip():
        return LlmToolCall(id=call_id, name=name, arguments={}, raw_arguments="")

    try:
        parsed = json.loads(raw_arguments)
    except json.JSONDecodeError as exc:
        return LlmToolCall(
            id=call_id,
            name=name,
            arguments={},
            raw_arguments=raw_arguments,
            parse_error=str(exc),
        )

    if not isinstance(parsed, dict):
        return LlmToolCall(
            id=call_id,
            name=name,
            arguments={},
            raw_arguments=raw_arguments,
            parse_error="Tool arguments must be a JSON object.",
        )

    return LlmToolCall(
        id=call_id,
        name=name,
        arguments=parsed,
        raw_arguments=raw_arguments,
    )


def provider_base_url(base_url: str) -> str:
    return base_url.strip().rstrip("/")


def request_max_output_tokens(config: Any) -> int:
    return config.max_tokens or DEFAULT_MAX_OUTPUT_TOKENS


def http_error_message(exc: httpx.HTTPStatusError) -> str:
    text = exc.response.text.strip()
    if not text:
        return f"Model provider returned HTTP {exc.response.status_code}."

    return f"Model provider returned HTTP {exc.response.status_code}: {text[:240]}"


async def async_post_json(
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    """POST JSON and normalize transport errors for non-SDK providers."""

    try:
        async with httpx.AsyncClient(timeout=max(5, timeout_seconds)) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        raise LlmRequestError(
            http_error_message(exc),
            status_code=exc.response.status_code,
        ) from exc
    except httpx.TimeoutException as exc:
        raise LlmRequestError("Model provider request timed out.") from exc
    except httpx.HTTPError as exc:
        raise LlmRequestError(f"Model provider request failed: {exc}") from exc
    except ValueError as exc:
        raise LlmRequestError("Model provider returned invalid JSON.") from exc

    if not isinstance(data, dict):
        raise LlmRequestError("Model provider returned an unsupported response.")

    return data


async def async_stream_json(
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_seconds: int,
) -> AsyncIterator[dict[str, Any]]:
    """POST JSON and yield server-sent JSON events."""

    try:
        async with httpx.AsyncClient(timeout=max(5, timeout_seconds)) as client:
            async with client.stream(
                "POST",
                url,
                headers=headers,
                json=payload,
            ) as response:
                response.raise_for_status()
                async for event in _aiter_sse_json(response):
                    yield event
    except httpx.HTTPStatusError as exc:
        raise LlmRequestError(
            http_error_message(exc),
            status_code=exc.response.status_code,
        ) from exc
    except httpx.TimeoutException as exc:
        raise LlmRequestError("Model provider request timed out.") from exc
    except httpx.HTTPError as exc:
        raise LlmRequestError(f"Model provider request failed: {exc}") from exc


async def _aiter_sse_json(response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
    event_name = ""
    data_lines: list[str] = []

    async for line in response.aiter_lines():
        if not line:
            payload = _sse_json_payload(event_name, data_lines)
            event_name = ""
            data_lines = []
            if payload is not None:
                yield payload
            continue

        if line.startswith(":"):
            continue

        field, separator, value = line.partition(":")
        if not separator:
            continue
        if value.startswith(" "):
            value = value[1:]

        if field == "event":
            event_name = value
        elif field == "data":
            data_lines.append(value)

    payload = _sse_json_payload(event_name, data_lines)
    if payload is not None:
        yield payload


def _sse_json_payload(
    event_name: str,
    data_lines: list[str],
) -> dict[str, Any] | None:
    if not data_lines:
        return None

    data = "\n".join(data_lines)
    if data == "[DONE]":
        return None

    try:
        payload = json.loads(data)
    except json.JSONDecodeError as exc:
        raise LlmRequestError("Model provider returned invalid stream JSON.") from exc

    if not isinstance(payload, dict):
        raise LlmRequestError("Model provider returned an unsupported stream event.")
    if event_name and "_event" not in payload:
        # Anthropic sends event names in the SSE `event:` field while Gemini
        # often includes enough type data in JSON. Preserve the SSE event name
        # under a private key so adapters can handle both shapes uniformly.
        payload["_event"] = event_name

    return payload


def attr_or_item(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)

    return getattr(value, key, None)


def object_dict(item: object) -> dict[str, Any]:
    if isinstance(item, dict):
        return item

    model_dump = getattr(item, "model_dump", None)
    if callable(model_dump):
        value = model_dump()
        if isinstance(value, dict):
            return value

    return {}


def positive_int(value: Any) -> int | None:
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, float) and value >= 0 and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def usage_from_values(
    *,
    input_tokens: Any = None,
    output_tokens: Any = None,
    total_tokens: Any = None,
    cached_input_tokens: Any = None,
    reasoning_tokens: Any = None,
) -> LlmUsage | None:
    usage = LlmUsage(
        input_tokens=positive_int(input_tokens),
        output_tokens=positive_int(output_tokens),
        total_tokens=positive_int(total_tokens),
        cached_input_tokens=positive_int(cached_input_tokens),
        reasoning_tokens=positive_int(reasoning_tokens),
    )
    if (
        usage.input_tokens is None
        and usage.output_tokens is None
        and usage.total_tokens is None
        and usage.cached_input_tokens is None
        and usage.reasoning_tokens is None
    ):
        return None

    return usage


def openai_chat_usage(response: object) -> LlmUsage | None:
    usage = attr_or_item(response, "usage")
    if usage is None:
        return None

    prompt_details = attr_or_item(usage, "prompt_tokens_details")
    completion_details = attr_or_item(usage, "completion_tokens_details")
    return usage_from_values(
        input_tokens=attr_or_item(usage, "prompt_tokens"),
        output_tokens=attr_or_item(usage, "completion_tokens"),
        total_tokens=attr_or_item(usage, "total_tokens"),
        cached_input_tokens=attr_or_item(prompt_details, "cached_tokens"),
        reasoning_tokens=attr_or_item(completion_details, "reasoning_tokens"),
    )


def responses_usage(response: object) -> LlmUsage | None:
    usage = attr_or_item(response, "usage")
    if usage is None:
        return None

    input_details = attr_or_item(usage, "input_tokens_details")
    output_details = attr_or_item(usage, "output_tokens_details")
    return usage_from_values(
        input_tokens=attr_or_item(usage, "input_tokens"),
        output_tokens=attr_or_item(usage, "output_tokens"),
        total_tokens=attr_or_item(usage, "total_tokens"),
        cached_input_tokens=attr_or_item(input_details, "cached_tokens"),
        reasoning_tokens=attr_or_item(output_details, "reasoning_tokens"),
    )


def anthropic_usage(payload: dict[str, Any]) -> LlmUsage | None:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None

    input_tokens = positive_int(usage.get("input_tokens"))
    output_tokens = positive_int(usage.get("output_tokens"))
    total_tokens = (
        input_tokens + output_tokens
        if input_tokens is not None and output_tokens is not None
        else None
    )
    return usage_from_values(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


def gemini_usage(payload: dict[str, Any]) -> LlmUsage | None:
    usage = payload.get("usageMetadata") or payload.get("usage")
    if not isinstance(usage, dict):
        return None

    input_tokens = usage.get("promptTokenCount") or usage.get("input_tokens")
    output_tokens = usage.get("candidatesTokenCount") or usage.get("output_tokens")
    total_tokens = usage.get("totalTokenCount") or usage.get("total_tokens")
    return usage_from_values(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


def map_stop_reason(value: Any) -> LlmStopReason:
    reason = str(value or "").strip().lower()
    if reason in {"stop", "end_turn", "stop_sequence", "completed"}:
        return "stop"
    if reason in {"tool_calls", "tool_use", "function_call"}:
        return "tool_calls"
    if reason in {"length", "max_tokens", "max_output_tokens", "incomplete"}:
        return "length"
    if reason in {"content_filter", "safety", "blocked"}:
        return "content_filter"
    if reason in {"error", "failed"}:
        return "error"
    return "unknown"


def tool_function(tool: dict[str, Any]) -> dict[str, Any]:
    value = tool.get("function")
    return value if isinstance(value, dict) else {}


def message_content_text(content: Any) -> str:
    """Return only textual content from the runtime's neutral message shape."""

    return "".join(
        part["text"]
        for part in message_content_parts(content)
        if part["type"] == "text"
    )


def message_content_parts(content: Any) -> list[dict[str, str]]:
    """Normalize text, image, and file blocks without provider wire shapes."""

    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if not isinstance(content, list):
        return []

    parts: list[dict[str, str]] = []
    for value in content:
        if not isinstance(value, dict):
            continue

        part_type = value.get("type")
        if part_type == "text" and isinstance(value.get("text"), str):
            parts.append({"type": "text", "text": value["text"]})
            continue

        media_type = value.get("media_type")
        data = value.get("data")
        if (
            part_type == "image"
            and isinstance(media_type, str)
            and media_type.startswith("image/")
            and isinstance(data, str)
            and data
        ):
            parts.append(
                {
                    "type": "image",
                    "media_type": media_type,
                    "data": data,
                },
            )
            continue

        filename = value.get("filename")
        if (
            part_type == "file"
            and isinstance(filename, str)
            and filename
            and isinstance(media_type, str)
            and media_type
            and isinstance(data, str)
            and data
        ):
            parts.append(
                {
                    "type": "file",
                    "filename": filename,
                    "media_type": media_type,
                    "data": data,
                },
            )

    return parts


def image_data_url(part: dict[str, str]) -> str:
    """Build a data URL from one validated provider-neutral image part."""

    return f"data:{part['media_type']};base64,{part['data']}"


def openai_chat_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Map neutral image blocks to OpenAI-compatible Chat Completions parts."""

    converted: list[dict[str, Any]] = []
    for message in messages:
        content = message.get("content")
        parts = message_content_parts(content)
        if any(part["type"] == "file" for part in parts):
            raise LlmRequestError(
                "OpenAI-compatible Chat Completions does not support native files.",
            )
        if not any(part["type"] == "image" for part in parts):
            converted.append(message)
            continue

        provider_content: list[dict[str, Any]] = []
        for part in parts:
            if part["type"] == "text":
                provider_content.append({"type": "text", "text": part["text"]})
            else:
                provider_content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": image_data_url(part)},
                    },
                )

        converted.append({**message, "content": provider_content})

    return converted


def system_and_messages(
    messages: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    system_parts: list[str] = []
    non_system: list[dict[str, Any]] = []
    for message in messages:
        if message.get("role") == "system":
            text = message_content_text(message.get("content")).strip()
            if text:
                system_parts.append(text)
        else:
            non_system.append(message)

    return "\n\n".join(system_parts), non_system
