from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from copy import deepcopy
from hashlib import sha256
from inspect import isawaitable
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit

import httpx
from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
)

from .errors import LlmRequestError, LlmTimeoutError
from .tool_schema import portable_tool_schema
from .types import (
    LlmContentPart,
    LlmFilePart,
    LlmImagePart,
    LlmInputMessage,
    LlmPrompt,
    LlmRequestContext,
    LlmStopReason,
    LlmToolCall,
    LlmUsage,
    LlmWebSource,
)

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
_PROMPT_CACHE_KEY_TARGETS = {
    ("openai", "openai_responses"): DEFAULT_OPENAI_BASE_URL,
    ("xai", "openai_responses"): "https://api.x.ai/v1",
    ("moonshot", "openai_compatible_chat"): "https://api.moonshot.ai/v1",
}
REQUEST_TIMEOUT_SECONDS = 60
PROVIDER_CONNECT_TIMEOUT_SECONDS = 30.0
ANTHROPIC_VERSION = "2023-06-01"
QWEN_EXPLICIT_CACHE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
# DashScope explicit caching is not a generic OpenAI-compatible extension. It
# is currently limited to this documented China (Beijing) endpoint/model set,
# so an unknown deployment must stay on the provider's implicit cache instead
# of receiving an unsupported wire field.
QWEN_EXPLICIT_CACHE_MODELS = frozenset(
    {
        "qwen3.7-max",
        "qwen3.7-max-2026-05-20",
        "qwen3.7-max-2026-06-08",
        "qwen3.6-max-preview",
        "qwen3-max",
        "qwen3.7-plus",
        "qwen3.7-plus-2026-05-26",
        "qwen3.6-plus",
        "qwen3.5-plus",
        "qwen3.5-plus-2026-04-20",
        "qwen-plus",
        "qwen3.6-flash",
        "qwen3.5-flash",
        "qwen-flash",
        "qwen3-coder-plus",
        "qwen3-coder-flash",
        "qwen3-vl-plus",
        "qwen3-vl-flash",
        "deepseek-v3.2",
        "kimi-k2.7-code",
        "kimi-k2.6",
        "kimi-k2.5",
        "glm-5.1",
    },
)


def make_web_source(
    url: str,
    title: str = "",
    excerpt: str = "",
) -> LlmWebSource:
    """Normalize one provider citation into ResuMate's stable source identity."""

    normalized_url = _normalized_web_source_url(url)
    digest = sha256(normalized_url.encode("utf-8")).hexdigest()[:16]
    return LlmWebSource(
        id=f"source-web-{digest}",
        title=title.strip() or normalized_url,
        url=normalized_url,
        excerpt=excerpt.strip(),
    )


def _normalized_web_source_url(url: str) -> str:
    candidate = url.strip()
    parsed = urlsplit(candidate)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
        return candidate
    return urlunsplit(
        (
            parsed.scheme.casefold(),
            parsed.netloc.casefold(),
            parsed.path or "/",
            parsed.query,
            "",
        ),
    )


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
        # The agent loop owns one bounded retry before visible output. Disable
        # the SDK's hidden retries so one timeout cannot multiply into several
        # minutes across both layers.
        max_retries=0,
        timeout=provider_http_timeout(config.timeout_seconds),
    )


def provider_http_timeout(idle_timeout_seconds: int) -> httpx.Timeout:
    """Separate connection setup from per-read provider inactivity."""

    return httpx.Timeout(
        max(5, idle_timeout_seconds),
        connect=PROVIDER_CONNECT_TIMEOUT_SECONDS,
    )


async def close_async_stream(stream: object) -> None:
    """Close provider streams regardless of sync or async close semantics."""

    close = getattr(stream, "aclose", None)
    if not callable(close):
        close = getattr(stream, "close", None)
    if not callable(close):
        return

    result = close()
    if isawaitable(result):
        await result


async def close_async_client(client: object) -> None:
    """Deterministically release one request-scoped provider SDK client.

    SDK implementations expose either synchronous or asynchronous ``close``;
    both must finish before the request returns so transports are not leaked.
    """

    await close_async_stream(client)


def provider_status_error_message(error: APIStatusError) -> str:
    """Return an SDK HTTP failure without provider-controlled response text."""

    return _provider_http_error_message(
        error.status_code,
        error.response.text,
    )


def _provider_http_error_message(status_code: int, response_text: str) -> str:
    """Reduce a raw HTTP failure to a small public classification."""

    if status_code in {400, 415} and _is_unsupported_attachment_response(
        response_text,
    ):
        # Preserve the local text-extraction fallback signal without retaining
        # or returning any provider-controlled response content.
        return f"Model provider returned HTTP {status_code}: unsupported attachment."
    return f"Model provider returned HTTP {status_code}."


def _is_unsupported_attachment_response(response_text: str) -> bool:
    message = response_text.casefold()
    subjects = (
        "attachment",
        "document",
        "file_data",
        "input_file",
        "application/pdf",
        "media type",
        "mime",
        "pdf",
    )
    rejections = (
        "unsupported",
        "not supported",
        "not allowed",
        "invalid content",
        "invalid media",
        "invalid type",
        "unknown type",
        "unrecognized",
    )
    return any(subject in message for subject in subjects) and any(
        rejection in message for rejection in rejections
    )


def raise_openai_error(error: Exception) -> None:
    """Normalize SDK exceptions to the runtime's public error type."""

    if isinstance(error, APIStatusError):
        raise LlmRequestError(
            provider_status_error_message(error),
            status_code=error.status_code,
        ) from error
    if isinstance(error, APITimeoutError):
        raise LlmTimeoutError("Model provider request timed out.") from error
    if isinstance(error, APIConnectionError):
        raise LlmRequestError("Model provider request failed.") from error
    if isinstance(error, APIError):
        raise LlmRequestError("Model provider request failed.") from error
    raise error


def chat_completion_params(
    config: Any,
    prompt: LlmPrompt,
    *,
    stream: bool,
    request_context: LlmRequestContext | None = None,
) -> dict[str, Any]:
    """Build OpenAI-compatible chat params, omitting unset optional knobs."""

    params: dict[str, Any] = {
        "model": config.model,
        "messages": _qwen_chat_messages(config, prompt),
        "stream": stream,
    }
    if config.temperature is not None:
        params["temperature"] = config.temperature
    if config.top_p is not None:
        params["top_p"] = config.top_p
    if config.request_max_output_tokens:
        params["max_tokens"] = config.request_max_output_tokens
    cache_key = openai_prompt_cache_key(config, request_context)
    if cache_key:
        params["prompt_cache_key"] = cache_key
    extra_body = _openai_chat_thinking_body(config)
    if extra_body:
        params["extra_body"] = extra_body

    return params


def _openai_chat_thinking_body(config: Any) -> dict[str, Any]:
    """Project runtime Auto onto one verified OpenAI-compatible protocol."""

    if official_minimax_reasoning_split(config):
        # MiniMax otherwise embeds `<think>` text in visible content. Its
        # official split mode returns a replayable reasoning_details sequence,
        # keeping display text and continuation state separate.
        body: dict[str, Any] = {"reasoning_split": True}
        if str(config.model).casefold() == "minimax-m3":
            if config.thinking_control == "native_auto":
                body["thinking"] = {"type": "adaptive"}
        return body
    if config.thinking_control != "native_auto":
        return {}
    if (
        config.provider == "qwen"
        and config.provider_kind == "cloud"
        and config.api_family == "openai_compatible_chat"
        and provider_base_url(config.base_url) == QWEN_EXPLICIT_CACHE_BASE_URL
    ):
        # DashScope exposes a boolean thinking switch outside the OpenAI schema.
        # Do not send a budget or effort tier: the provider/model keeps ownership
        # of its native Auto depth, including future tiers we do not know about.
        return {"enable_thinking": True}
    if (
        config.provider == "vllm"
        and config.provider_kind == "local"
        and config.api_family == "openai_compatible_chat"
    ):
        # vLLM's request-level chat-template switch is model-agnostic: unknown
        # template kwargs are filtered by the runtime, so capability selection
        # remains in discovery/config rather than becoming a model-name table.
        return {"chat_template_kwargs": {"enable_thinking": True}}
    if (
        config.provider == "sglang"
        and config.provider_kind == "local"
        and config.api_family == "openai_compatible_chat"
    ):
        # SGLang expands this provider-native boolean to both common template
        # keys (`thinking` and `enable_thinking`) without choosing an effort.
        return {"reasoning": {"enabled": True}}

    return {}


def _qwen_chat_messages(
    config: Any,
    prompt: LlmPrompt,
) -> list[dict[str, Any]]:
    messages = openai_chat_messages(prompt.messages, config=config)
    if not _supports_qwen_explicit_cache(config):
        return messages

    # Qwen accepts at most four explicit breakpoints. The compiler supplies
    # semantic prefix boundaries as message counts; the Adapter alone owns the
    # provider-specific content-block projection. Copy before annotating so a
    # later provider attempt sees the original neutral transcript.
    cached_messages = deepcopy(messages)
    for message_count in prompt.stable_prefix_message_counts[-4:]:
        message = cached_messages[message_count - 1]
        content = message.get("content")
        cache_control = {"type": "ephemeral"}
        if isinstance(content, str) and content:
            message["content"] = [
                {
                    "type": "text",
                    "text": content,
                    "cache_control": cache_control,
                },
            ]
            continue
        if isinstance(content, list) and content and isinstance(content[-1], dict):
            blocks = deepcopy(content)
            blocks[-1]["cache_control"] = cache_control
            message["content"] = blocks
            continue

        raise LlmRequestError(
            "Qwen cache boundary must end on a non-empty content block.",
        )

    return cached_messages


def _supports_qwen_explicit_cache(config: Any) -> bool:
    return (
        config.provider == "qwen"
        and config.provider_kind == "cloud"
        and config.api_family == "openai_compatible_chat"
        and provider_base_url(config.base_url) == QWEN_EXPLICIT_CACHE_BASE_URL
        and config.model.strip() in QWEN_EXPLICIT_CACHE_MODELS
    )


def openai_prompt_cache_key(
    config: Any,
    request_context: LlmRequestContext | None,
) -> str | None:
    """Return an opaque key only where the provider officially supports it."""

    if request_context is None or not supports_prompt_cache_key(config):
        return None

    return request_context.cache_key


def supports_prompt_cache_key(config: Any) -> bool:
    """Return whether this config is the provider's official cache-key target."""

    if config.provider_kind != "cloud":
        return False

    expected_base_url = _PROMPT_CACHE_KEY_TARGETS.get(
        (config.provider, config.api_family),
    )
    return (
        expected_base_url is not None
        and provider_base_url(config.base_url) == expected_base_url
    )


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


def http_error_message(exc: httpx.HTTPStatusError) -> str:
    """Return an HTTP failure without provider-controlled response text."""

    return _provider_http_error_message(
        exc.response.status_code,
        exc.response.text,
    )


async def async_post_json(
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    """POST JSON and normalize transport errors for non-SDK providers."""

    try:
        async with httpx.AsyncClient(
            timeout=provider_http_timeout(timeout_seconds),
        ) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        raise LlmRequestError(
            http_error_message(exc),
            status_code=exc.response.status_code,
        ) from exc
    except httpx.TimeoutException as exc:
        raise LlmTimeoutError("Model provider request timed out.") from exc
    except httpx.HTTPError as exc:
        raise LlmRequestError("Model provider request failed.") from exc
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
        async with httpx.AsyncClient(
            timeout=provider_http_timeout(timeout_seconds),
        ) as client:
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
        raise LlmTimeoutError("Model provider request timed out.") from exc
    except httpx.HTTPError as exc:
        raise LlmRequestError("Model provider request failed.") from exc


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
    cache_write_input_tokens: Any = None,
    reasoning_tokens: Any = None,
) -> LlmUsage | None:
    usage = LlmUsage(
        input_tokens=positive_int(input_tokens),
        output_tokens=positive_int(output_tokens),
        total_tokens=positive_int(total_tokens),
        cached_input_tokens=positive_int(cached_input_tokens),
        cache_write_input_tokens=positive_int(cache_write_input_tokens),
        reasoning_tokens=positive_int(reasoning_tokens),
    )
    if (
        usage.input_tokens is None
        and usage.output_tokens is None
        and usage.total_tokens is None
        and usage.cached_input_tokens is None
        and usage.cache_write_input_tokens is None
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
    cached_input_tokens = attr_or_item(prompt_details, "cached_tokens")
    if cached_input_tokens is None:
        # DeepSeek's OpenAI-compatible API reports its automatic disk-cache
        # hits directly on `usage`, rather than in `prompt_tokens_details`.
        cached_input_tokens = attr_or_item(usage, "prompt_cache_hit_tokens")
    if cached_input_tokens is None:
        # Moonshot's Chat Completions response follows its documented compact
        # shape and reports cache hits directly as `usage.cached_tokens`.
        cached_input_tokens = attr_or_item(usage, "cached_tokens")
    cache_write_input_tokens = attr_or_item(prompt_details, "cache_write_tokens")
    if cache_write_input_tokens is None:
        # DashScope names tokens written by an explicit Qwen cache breakpoint
        # `cache_creation_input_tokens` in its OpenAI-compatible usage block.
        cache_write_input_tokens = attr_or_item(
            prompt_details,
            "cache_creation_input_tokens",
        )
    if cache_write_input_tokens is None:
        # Some OpenAI-compatible runtimes report newly materialized prefix
        # cache tokens as `created_cache_tokens`. Keep it after the standard
        # and Qwen fields so their documented meanings remain authoritative.
        cache_write_input_tokens = attr_or_item(
            prompt_details,
            "created_cache_tokens",
        )
    return usage_from_values(
        input_tokens=attr_or_item(usage, "prompt_tokens"),
        output_tokens=attr_or_item(usage, "completion_tokens"),
        total_tokens=attr_or_item(usage, "total_tokens"),
        cached_input_tokens=cached_input_tokens,
        cache_write_input_tokens=cache_write_input_tokens,
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
        cache_write_input_tokens=attr_or_item(input_details, "cache_write_tokens"),
        reasoning_tokens=attr_or_item(output_details, "reasoning_tokens"),
    )


def anthropic_usage(payload: dict[str, Any]) -> LlmUsage | None:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None

    input_parts = (
        positive_int(usage.get("input_tokens")),
        positive_int(usage.get("cache_creation_input_tokens")),
        positive_int(usage.get("cache_read_input_tokens")),
    )
    input_tokens = (
        sum(value for value in input_parts if value is not None)
        if any(value is not None for value in input_parts)
        else None
    )
    output_tokens = positive_int(usage.get("output_tokens"))
    output_details = usage.get("output_tokens_details")
    reasoning_tokens = (
        output_details.get("thinking_tokens")
        if isinstance(output_details, dict)
        else None
    )
    total_tokens = (
        input_tokens + output_tokens
        if input_tokens is not None and output_tokens is not None
        else None
    )
    return usage_from_values(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cached_input_tokens=usage.get("cache_read_input_tokens"),
        cache_write_input_tokens=usage.get("cache_creation_input_tokens"),
        reasoning_tokens=reasoning_tokens,
    )


def map_stop_reason(value: Any) -> LlmStopReason:
    reason = str(value or "").strip().lower()
    if reason in {"stop", "end_turn", "stop_sequence", "completed"}:
        return "stop"
    if reason in {"tool_calls", "tool_use", "function_call"}:
        return "tool_calls"
    if reason in {
        "length",
        "max_tokens",
        "max_output_tokens",
        "incomplete",
        "model_context_window_exceeded",
    }:
        return "length"
    if reason in {"content_filter", "safety", "blocked"}:
        return "content_filter"
    if reason in {"error", "failed"}:
        return "error"
    return "unknown"


def tool_function(tool: Mapping[str, Any]) -> dict[str, Any]:
    value = tool.get("function")
    return value if isinstance(value, dict) else {}


def message_content_text(content: Any) -> str:
    """Return only textual content from the runtime's neutral message shape."""

    return "".join(
        part["text"]
        for part in message_content_parts(content)
        if part["type"] == "text"
    )


def message_content_parts(content: Any) -> list[LlmContentPart]:
    """Normalize text, image, and file blocks without provider wire shapes."""

    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if not isinstance(content, list):
        return []

    parts: list[LlmContentPart] = []
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


def image_data_url(part: LlmImagePart | LlmFilePart) -> str:
    """Build a data URL from one validated provider-neutral image part."""

    return f"data:{part['media_type']};base64,{part['data']}"


def openai_chat_messages(
    messages: list[LlmInputMessage],
    *,
    config: Any = None,
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
            # TypedDict messages are ordinary dicts at runtime; this cast only
            # marks the point where the neutral transcript becomes SDK input.
            provider_message = dict(cast(dict[str, Any], message))
            provider_state = provider_message.pop("provider_state", None)
            if (
                official_minimax_reasoning_split(config)
                and message["role"] == "assistant"
            ):
                # reasoning_content is the runtime's display-neutral summary;
                # MiniMax requires its complete ordered provider objects for a
                # tool continuation, not a reconstructed text approximation.
                provider_message.pop("reasoning_content", None)
                reasoning_details = minimax_reasoning_details(
                    provider_state,
                    model=config.model,
                )
                if reasoning_details:
                    provider_message["reasoning_details"] = reasoning_details
            if (
                official_deepseek_thinking(config)
                and message["role"] == "assistant"
                and provider_message.get("tool_calls")
            ):
                # DeepSeek requires every thinking tool turn to replay the full
                # reasoning chain and rejects null assistant content. Copy only
                # at the Adapter projection so neutral history stays portable.
                provider_message = dict(provider_message)
                if provider_message.get("content") is None:
                    provider_message["content"] = ""
            converted.append(provider_message)
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


def official_deepseek_thinking(config: Any) -> bool:
    return (
        config is not None
        and config.provider == "deepseek"
        and config.provider_kind == "cloud"
        and config.api_family == "openai_compatible_chat"
        and provider_base_url(config.base_url) == "https://api.deepseek.com"
        and config.thinking_control != "none"
    )


def official_minimax_reasoning_split(config: Any) -> bool:
    """Identify MiniMax's official split-reasoning response protocol.

    ``reasoning_split`` changes response representation; it does not enable
    reasoning. Keep it active even when capability discovery has not populated
    a thinking control, otherwise MiniMax places ``<think>`` in visible text.
    """

    return (
        config is not None
        and config.provider == "minimax"
        and config.provider_kind == "cloud"
        and config.api_family == "openai_compatible_chat"
        and provider_base_url(config.base_url) == "https://api.minimaxi.com/v1"
    )


def minimax_reasoning_details(
    provider_state: object,
    *,
    model: str,
) -> list[dict[str, Any]]:
    """Return same-model MiniMax continuation blocks or fail closed."""

    if provider_state is None:
        return []
    if not isinstance(provider_state, dict) or provider_state.get("model") != model:
        raise LlmRequestError("MiniMax reasoning continuation state is invalid.")
    raw_details = provider_state.get("reasoning_details")
    if not isinstance(raw_details, list):
        raise LlmRequestError("MiniMax reasoning continuation state is invalid.")

    details: list[dict[str, Any]] = []
    for value in raw_details:
        detail = object_dict(value)
        if not detail or not isinstance(detail.get("text"), str):
            raise LlmRequestError("MiniMax reasoning continuation state is invalid.")
        details.append(deepcopy(detail))
    return details


def system_and_messages(
    messages: list[LlmInputMessage],
) -> tuple[str, list[LlmInputMessage]]:
    system_parts: list[str] = []
    non_system: list[LlmInputMessage] = []
    for message in messages:
        if message["role"] == "system":
            text = message_content_text(message.get("content")).strip()
            if text:
                system_parts.append(text)
        else:
            non_system.append(message)

    return "\n\n".join(system_parts), non_system
