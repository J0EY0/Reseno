import json
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from inspect import isawaitable
from sqlite3 import Connection
from typing import Any, Literal

import httpx
from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    OpenAI,
)

from app.services.llm_secrets import decrypt_api_key

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
REQUEST_TIMEOUT_SECONDS = 60
DEFAULT_MAX_OUTPUT_TOKENS = 4096
ANTHROPIC_VERSION = "2023-06-01"


class LlmRequestError(RuntimeError):
    """Raised when an LLM provider request cannot return usable text."""


@dataclass(frozen=True)
class AgentLlmConfig:
    """Runtime-only LLM config with the decrypted key kept out of responses."""

    client_id: str
    name: str
    provider: str
    model: str
    base_url: str
    api_key: str
    temperature: float | None
    top_p: float | None
    max_tokens: int | None
    timeout_seconds: int
    context_window_tokens: int | None = None
    provider_kind: str = "custom"
    api_family: str = "openai_compatible_chat"
    supports_image: bool = False
    supports_thinking: bool = False
    thinking_enabled: bool = False


@dataclass(frozen=True)
class LlmStreamDelta:
    """One streamed provider delta split into visible text or reasoning."""

    kind: Literal["text", "reasoning"]
    delta: str


@dataclass(frozen=True)
class LlmToolCall:
    """One model-selected function tool call."""

    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str


@dataclass(frozen=True)
class LlmToolCallResponse:
    """Assistant response that may ask the backend to execute tools."""

    content: str
    tool_calls: list[LlmToolCall]
    reasoning: str = ""
    provider_steps: list[dict[str, Any]] = field(default_factory=list)


def resolve_agent_llm_config(
    conn: Connection,
    model_config_data: dict[str, Any] | None,
) -> AgentLlmConfig | None:
    """Load the selected enabled model config and decrypt its API key."""

    client_id = ""
    if model_config_data:
        raw_client_id = model_config_data.get("id") or model_config_data.get(
            "client_id",
        )
        client_id = str(raw_client_id or "").strip()

    if client_id:
        row = conn.execute(
            """
            SELECT
                client_id,
                name,
                provider,
                provider_kind,
                api_family,
                model,
                base_url,
                encrypted_api_key,
                temperature,
                top_p,
                max_tokens,
                context_window_tokens,
                timeout_seconds,
                supports_image,
                supports_thinking,
                thinking_enabled
            FROM llm_configs
            WHERE client_id = ? AND enabled = 1
            """,
            (client_id,),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT
                client_id,
                name,
                provider,
                provider_kind,
                api_family,
                model,
                base_url,
                encrypted_api_key,
                temperature,
                top_p,
                max_tokens,
                context_window_tokens,
                timeout_seconds,
                supports_image,
                supports_thinking,
                thinking_enabled
            FROM llm_configs
            WHERE enabled = 1
            ORDER BY is_default DESC, created_at DESC, id DESC
            LIMIT 1
            """,
        ).fetchone()

    if row is None:
        return None

    encrypted_api_key = row["encrypted_api_key"]
    api_key = decrypt_api_key(encrypted_api_key) if encrypted_api_key else ""

    return AgentLlmConfig(
        client_id=row["client_id"],
        name=row["name"],
        provider=row["provider"],
        provider_kind=row["provider_kind"],
        api_family=row["api_family"],
        model=row["model"],
        base_url=row["base_url"] or DEFAULT_OPENAI_BASE_URL,
        api_key=api_key,
        temperature=(
            float(row["temperature"]) if row["temperature"] is not None else None
        ),
        top_p=float(row["top_p"]) if row["top_p"] is not None else None,
        max_tokens=row["max_tokens"],
        timeout_seconds=int(row["timeout_seconds"] or REQUEST_TIMEOUT_SECONDS),
        context_window_tokens=row["context_window_tokens"],
        supports_image=bool(row["supports_image"]),
        supports_thinking=bool(row["supports_thinking"]),
        thinking_enabled=bool(row["thinking_enabled"]),
    )


def _openai_base_url(base_url: str) -> str:
    """Return the OpenAI-compatible API root expected by the SDK."""

    normalized = base_url.strip().rstrip("/") or DEFAULT_OPENAI_BASE_URL
    if normalized.endswith("/chat/completions"):
        return normalized[: -len("/chat/completions")].rstrip("/")

    return normalized


def _provider_error_excerpt(error: APIStatusError) -> str:
    """Build a short provider error message without request headers or secrets."""

    response_text = error.response.text.strip()
    if not response_text:
        return f"Model provider returned HTTP {error.status_code}."

    return f"Model provider returned HTTP {error.status_code}: {response_text[:240]}"


def _chat_completion_params(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
    *,
    stream: bool,
) -> dict[str, Any]:
    """Build SDK request params without logging or returning secret material."""

    params: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "stream": stream,
    }
    if config.temperature is not None:
        params["temperature"] = config.temperature
    if config.top_p is not None:
        params["top_p"] = config.top_p
    if config.max_tokens:
        params["max_tokens"] = config.max_tokens

    return params


def _unsupported_parallel_tool_calls(error: APIStatusError) -> bool:
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


def _client(config: AgentLlmConfig) -> OpenAI:
    """Build an SDK client for one request-scoped model config."""

    return OpenAI(
        api_key=config.api_key or "local",
        base_url=_openai_base_url(config.base_url),
        timeout=max(5, config.timeout_seconds),
    )


def _async_client(config: AgentLlmConfig) -> AsyncOpenAI:
    """Build an async SDK client for one request-scoped model config."""

    return AsyncOpenAI(
        api_key=config.api_key or "local",
        base_url=_openai_base_url(config.base_url),
        timeout=max(5, config.timeout_seconds),
    )


async def _close_async_stream(stream: object) -> None:
    """Close an SDK stream whether close is sync or async."""

    close = getattr(stream, "close", None)
    if not callable(close):
        return

    close_result = close()
    if isawaitable(close_result):
        await close_result


def _complete_openai_chat(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
) -> str:
    """Call an OpenAI-compatible chat completion endpoint through the SDK."""

    try:
        response = _client(config).chat.completions.create(
            **_chat_completion_params(config, messages, stream=False),
        )
    except APIStatusError as exc:
        raise LlmRequestError(_provider_error_excerpt(exc)) from exc
    except APITimeoutError as exc:
        raise LlmRequestError("Model provider request timed out.") from exc
    except APIConnectionError as exc:
        raise LlmRequestError(f"Model provider request failed: {exc}") from exc
    except APIError as exc:
        raise LlmRequestError(
            f"Model provider request failed: {exc}",
        ) from exc

    if not response.choices:
        raise LlmRequestError("Model provider returned an empty response.")

    content = response.choices[0].message.content
    if isinstance(content, str) and content.strip():
        return content.strip()

    raise LlmRequestError("Model provider returned an empty response.")


async def _async_complete_openai_chat(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
) -> str:
    """Call an OpenAI-compatible chat completion endpoint asynchronously."""

    try:
        response = await _async_client(config).chat.completions.create(
            **_chat_completion_params(config, messages, stream=False),
        )
    except APIStatusError as exc:
        raise LlmRequestError(_provider_error_excerpt(exc)) from exc
    except APITimeoutError as exc:
        raise LlmRequestError("Model provider request timed out.") from exc
    except APIConnectionError as exc:
        raise LlmRequestError(f"Model provider request failed: {exc}") from exc
    except APIError as exc:
        raise LlmRequestError(
            f"Model provider request failed: {exc}",
        ) from exc

    if not response.choices:
        raise LlmRequestError("Model provider returned an empty response.")

    content = response.choices[0].message.content
    if isinstance(content, str) and content.strip():
        return content.strip()

    raise LlmRequestError("Model provider returned an empty response.")


def _delta_text(delta: object, field_names: tuple[str, ...]) -> str:
    """Read streamed SDK delta fields, including provider-specific extras."""

    for field_name in field_names:
        value = getattr(delta, field_name, None)
        if value is None and hasattr(delta, "model_extra"):
            extra = delta.model_extra
            if isinstance(extra, dict):
                value = extra.get(field_name)

        if isinstance(value, str) and value:
            return value

    return ""


def _complete_openai_chat_stream(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
) -> Iterator[LlmStreamDelta]:
    """Stream an OpenAI-compatible chat completion as provider deltas."""

    stream = None
    try:
        stream = _client(config).chat.completions.create(
            **_chat_completion_params(config, messages, stream=True),
        )
        for chunk in stream:
            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta
            content = _delta_text(delta, ("content",))
            if content:
                yield LlmStreamDelta(kind="text", delta=content)
    except APIStatusError as exc:
        raise LlmRequestError(_provider_error_excerpt(exc)) from exc
    except APITimeoutError as exc:
        raise LlmRequestError("Model provider request timed out.") from exc
    except APIConnectionError as exc:
        raise LlmRequestError(f"Model provider request failed: {exc}") from exc
    except APIError as exc:
        raise LlmRequestError(
            f"Model provider request failed: {exc}",
        ) from exc
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            close()


async def _async_complete_openai_chat_stream(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
) -> AsyncIterator[LlmStreamDelta]:
    """Stream an OpenAI-compatible chat completion asynchronously."""

    stream = None
    try:
        stream = await _async_client(config).chat.completions.create(
            **_chat_completion_params(config, messages, stream=True),
        )
        async for chunk in stream:
            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta
            content = _delta_text(delta, ("content",))
            if content:
                yield LlmStreamDelta(kind="text", delta=content)
    except APIStatusError as exc:
        raise LlmRequestError(_provider_error_excerpt(exc)) from exc
    except APITimeoutError as exc:
        raise LlmRequestError("Model provider request timed out.") from exc
    except APIConnectionError as exc:
        raise LlmRequestError(f"Model provider request failed: {exc}") from exc
    except APIError as exc:
        raise LlmRequestError(
            f"Model provider request failed: {exc}",
        ) from exc
    finally:
        if stream is not None:
            await _close_async_stream(stream)


def _parsed_tool_arguments(raw_arguments: str) -> dict[str, Any]:
    """Parse model-generated tool arguments as a JSON object."""

    if not raw_arguments.strip():
        return {}

    try:
        parsed = json.loads(raw_arguments)
    except json.JSONDecodeError:
        return {}

    return parsed if isinstance(parsed, dict) else {}


def _complete_openai_chat_tool_call(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> LlmToolCallResponse:
    """Ask the model to choose zero or more OpenAI-compatible function tools."""

    params = {
        **_chat_completion_params(config, messages, stream=False),
        "tools": tools,
        "tool_choice": "auto",
        "parallel_tool_calls": False,
    }
    try:
        response = _client(config).chat.completions.create(**params)
    except APIStatusError as exc:
        if not _unsupported_parallel_tool_calls(exc):
            raise LlmRequestError(_provider_error_excerpt(exc)) from exc

        params.pop("parallel_tool_calls", None)
        try:
            response = _client(config).chat.completions.create(**params)
        except APIStatusError as fallback_exc:
            raise LlmRequestError(
                _provider_error_excerpt(fallback_exc),
            ) from fallback_exc
        except APITimeoutError as fallback_exc:
            raise LlmRequestError("Model provider request timed out.") from fallback_exc
        except APIConnectionError as fallback_exc:
            raise LlmRequestError(
                f"Model provider request failed: {fallback_exc}",
            ) from fallback_exc
        except APIError as fallback_exc:
            raise LlmRequestError(
                f"Model provider request failed: {fallback_exc}",
            ) from fallback_exc
    except APITimeoutError as exc:
        raise LlmRequestError("Model provider request timed out.") from exc
    except APIConnectionError as exc:
        raise LlmRequestError(f"Model provider request failed: {exc}") from exc
    except APIError as exc:
        raise LlmRequestError(
            f"Model provider request failed: {exc}",
        ) from exc

    if not response.choices:
        raise LlmRequestError("Model provider returned an empty response.")

    message = response.choices[0].message
    content = message.content if isinstance(message.content, str) else ""
    tool_calls: list[LlmToolCall] = []
    for tool_call in message.tool_calls or []:
        function = getattr(tool_call, "function", None)
        name = getattr(function, "name", "")
        raw_arguments = getattr(function, "arguments", "") or ""
        if not name:
            continue

        tool_calls.append(
            LlmToolCall(
                id=tool_call.id,
                name=name,
                arguments=_parsed_tool_arguments(raw_arguments),
                raw_arguments=raw_arguments,
            ),
        )

    return LlmToolCallResponse(
        content=content.strip(),
        tool_calls=tool_calls,
        reasoning="",
    )


async def _async_complete_openai_chat_tool_call(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> LlmToolCallResponse:
    """Ask the model to choose tools through the async SDK."""

    params = {
        **_chat_completion_params(config, messages, stream=False),
        "tools": tools,
        "tool_choice": "auto",
        "parallel_tool_calls": False,
    }
    try:
        response = await _async_client(config).chat.completions.create(**params)
    except APIStatusError as exc:
        if not _unsupported_parallel_tool_calls(exc):
            raise LlmRequestError(_provider_error_excerpt(exc)) from exc

        params.pop("parallel_tool_calls", None)
        try:
            response = await _async_client(config).chat.completions.create(**params)
        except APIStatusError as fallback_exc:
            raise LlmRequestError(
                _provider_error_excerpt(fallback_exc),
            ) from fallback_exc
        except APITimeoutError as fallback_exc:
            raise LlmRequestError("Model provider request timed out.") from fallback_exc
        except APIConnectionError as fallback_exc:
            raise LlmRequestError(
                f"Model provider request failed: {fallback_exc}",
            ) from fallback_exc
        except APIError as fallback_exc:
            raise LlmRequestError(
                f"Model provider request failed: {fallback_exc}",
            ) from fallback_exc
    except APITimeoutError as exc:
        raise LlmRequestError("Model provider request timed out.") from exc
    except APIConnectionError as exc:
        raise LlmRequestError(f"Model provider request failed: {exc}") from exc
    except APIError as exc:
        raise LlmRequestError(
            f"Model provider request failed: {exc}",
        ) from exc

    if not response.choices:
        raise LlmRequestError("Model provider returned an empty response.")

    message = response.choices[0].message
    content = message.content if isinstance(message.content, str) else ""
    tool_calls: list[LlmToolCall] = []
    for tool_call in message.tool_calls or []:
        function = getattr(tool_call, "function", None)
        name = getattr(function, "name", "")
        raw_arguments = getattr(function, "arguments", "") or ""
        if not name:
            continue

        tool_calls.append(
            LlmToolCall(
                id=tool_call.id,
                name=name,
                arguments=_parsed_tool_arguments(raw_arguments),
                raw_arguments=raw_arguments,
            ),
        )

    return LlmToolCallResponse(
        content=content.strip(),
        tool_calls=tool_calls,
        reasoning="",
    )


def _provider_base_url(base_url: str) -> str:
    return base_url.strip().rstrip("/")


def _request_max_output_tokens(config: AgentLlmConfig) -> int:
    return config.max_tokens or DEFAULT_MAX_OUTPUT_TOKENS


def _http_error_message(exc: httpx.HTTPStatusError) -> str:
    text = exc.response.text.strip()
    if not text:
        return f"Model provider returned HTTP {exc.response.status_code}."

    return f"Model provider returned HTTP {exc.response.status_code}: {text[:240]}"


def _post_json(
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    try:
        response = httpx.post(
            url,
            headers=headers,
            json=payload,
            timeout=max(5, timeout_seconds),
        )
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPStatusError as exc:
        raise LlmRequestError(_http_error_message(exc)) from exc
    except httpx.TimeoutException as exc:
        raise LlmRequestError("Model provider request timed out.") from exc
    except httpx.HTTPError as exc:
        raise LlmRequestError(f"Model provider request failed: {exc}") from exc
    except ValueError as exc:
        raise LlmRequestError("Model provider returned invalid JSON.") from exc

    if not isinstance(data, dict):
        raise LlmRequestError("Model provider returned an unsupported response.")

    return data


async def _async_post_json(
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=max(5, timeout_seconds)) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        raise LlmRequestError(_http_error_message(exc)) from exc
    except httpx.TimeoutException as exc:
        raise LlmRequestError("Model provider request timed out.") from exc
    except httpx.HTTPError as exc:
        raise LlmRequestError(f"Model provider request failed: {exc}") from exc
    except ValueError as exc:
        raise LlmRequestError("Model provider returned invalid JSON.") from exc

    if not isinstance(data, dict):
        raise LlmRequestError("Model provider returned an unsupported response.")

    return data


def _tool_function(tool: dict[str, Any]) -> dict[str, Any]:
    value = tool.get("function")
    return value if isinstance(value, dict) else {}


def _responses_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    response_tools: list[dict[str, Any]] = []
    for tool in tools:
        function = _tool_function(tool)
        name = str(function.get("name") or "").strip()
        if not name:
            continue

        response_tools.append(
            {
                "type": "function",
                "name": name,
                "description": str(function.get("description") or ""),
                "parameters": function.get("parameters") or {
                    "type": "object",
                    "properties": {},
                },
                "strict": False,
            },
        )

    return response_tools


def _anthropic_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    anthropic_tools: list[dict[str, Any]] = []
    for tool in tools:
        function = _tool_function(tool)
        name = str(function.get("name") or "").strip()
        if not name:
            continue

        anthropic_tools.append(
            {
                "name": name,
                "description": str(function.get("description") or ""),
                "input_schema": function.get("parameters") or {
                    "type": "object",
                    "properties": {},
                },
            },
        )

    return anthropic_tools


def _message_content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if content is None:
        return ""

    return str(content)


def _system_and_messages(
    messages: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    system_parts: list[str] = []
    non_system: list[dict[str, Any]] = []
    for message in messages:
        if message.get("role") == "system":
            text = _message_content_text(message.get("content")).strip()
            if text:
                system_parts.append(text)
        else:
            non_system.append(message)

    return "\n\n".join(system_parts), non_system


def _responses_input(
    messages: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    system, non_system = _system_and_messages(messages)
    input_items: list[dict[str, Any]] = []
    for message in non_system:
        role = message.get("role")
        if role == "tool":
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": str(message.get("tool_call_id") or ""),
                    "output": _message_content_text(message.get("content")),
                },
            )
            continue

        if role == "assistant":
            content = _message_content_text(message.get("content")).strip()
            if content:
                input_items.append({"role": "assistant", "content": content})
            for tool_call in message.get("tool_calls") or []:
                function = _tool_function(tool_call)
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

        if role in {"user", "developer"}:
            input_items.append(
                {
                    "role": role,
                    "content": _message_content_text(message.get("content")),
                },
            )

    return system, input_items


def _openai_responses_params(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    stream: bool = False,
) -> dict[str, Any]:
    instructions, input_items = _responses_input(messages)
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
    if config.max_tokens:
        params["max_output_tokens"] = config.max_tokens
    if config.supports_thinking and config.thinking_enabled:
        params["reasoning"] = {"effort": "medium"}
    if tools:
        params["tools"] = _responses_tools(tools)
        params["tool_choice"] = "auto"
        params["parallel_tool_calls"] = False

    return params


def _output_item_dict(item: object) -> dict[str, Any]:
    if isinstance(item, dict):
        return item

    model_dump = getattr(item, "model_dump", None)
    if callable(model_dump):
        value = model_dump()
        if isinstance(value, dict):
            return value

    return {}


def _response_output_text(response: object) -> str:
    output_text = getattr(response, "output_text", "")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    output = getattr(response, "output", None)
    if not isinstance(output, list):
        return ""

    parts: list[str] = []
    for item in output:
        data = _output_item_dict(item)
        if data.get("type") != "message":
            continue
        for block in data.get("content") or []:
            if not isinstance(block, dict):
                continue
            text = block.get("text") or block.get("output_text")
            if isinstance(text, str):
                parts.append(text)

    return "".join(parts).strip()


def _response_tool_calls(response: object) -> list[LlmToolCall]:
    output = getattr(response, "output", None)
    if not isinstance(output, list):
        return []

    tool_calls: list[LlmToolCall] = []
    for item in output:
        data = _output_item_dict(item)
        if data.get("type") != "function_call":
            continue

        name = str(data.get("name") or "").strip()
        call_id = str(data.get("call_id") or data.get("id") or "").strip()
        raw_arguments = str(data.get("arguments") or "{}")
        if not name or not call_id:
            continue

        tool_calls.append(
            LlmToolCall(
                id=call_id,
                name=name,
                arguments=_parsed_tool_arguments(raw_arguments),
                raw_arguments=raw_arguments,
            ),
        )

    return tool_calls


def _complete_openai_responses(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
) -> str:
    try:
        response = _client(config).responses.create(
            **_openai_responses_params(config, messages),
        )
    except APIStatusError as exc:
        raise LlmRequestError(_provider_error_excerpt(exc)) from exc
    except APITimeoutError as exc:
        raise LlmRequestError("Model provider request timed out.") from exc
    except APIConnectionError as exc:
        raise LlmRequestError(f"Model provider request failed: {exc}") from exc
    except APIError as exc:
        raise LlmRequestError(f"Model provider request failed: {exc}") from exc

    text = _response_output_text(response)
    if text:
        return text

    raise LlmRequestError("Model provider returned an empty response.")


async def _async_complete_openai_responses(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
) -> str:
    try:
        response = await _async_client(config).responses.create(
            **_openai_responses_params(config, messages),
        )
    except APIStatusError as exc:
        raise LlmRequestError(_provider_error_excerpt(exc)) from exc
    except APITimeoutError as exc:
        raise LlmRequestError("Model provider request timed out.") from exc
    except APIConnectionError as exc:
        raise LlmRequestError(f"Model provider request failed: {exc}") from exc
    except APIError as exc:
        raise LlmRequestError(f"Model provider request failed: {exc}") from exc

    text = _response_output_text(response)
    if text:
        return text

    raise LlmRequestError("Model provider returned an empty response.")


def _complete_openai_responses_tool_call(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> LlmToolCallResponse:
    try:
        response = _client(config).responses.create(
            **_openai_responses_params(config, messages, tools=tools),
        )
    except APIStatusError as exc:
        raise LlmRequestError(_provider_error_excerpt(exc)) from exc
    except APITimeoutError as exc:
        raise LlmRequestError("Model provider request timed out.") from exc
    except APIConnectionError as exc:
        raise LlmRequestError(f"Model provider request failed: {exc}") from exc
    except APIError as exc:
        raise LlmRequestError(f"Model provider request failed: {exc}") from exc

    return LlmToolCallResponse(
        content=_response_output_text(response),
        tool_calls=_response_tool_calls(response),
        reasoning="",
    )


async def _async_complete_openai_responses_tool_call(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> LlmToolCallResponse:
    try:
        response = await _async_client(config).responses.create(
            **_openai_responses_params(config, messages, tools=tools),
        )
    except APIStatusError as exc:
        raise LlmRequestError(_provider_error_excerpt(exc)) from exc
    except APITimeoutError as exc:
        raise LlmRequestError("Model provider request timed out.") from exc
    except APIConnectionError as exc:
        raise LlmRequestError(f"Model provider request failed: {exc}") from exc
    except APIError as exc:
        raise LlmRequestError(f"Model provider request failed: {exc}") from exc

    return LlmToolCallResponse(
        content=_response_output_text(response),
        tool_calls=_response_tool_calls(response),
        reasoning="",
    )


def _anthropic_messages(
    messages: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    system, non_system = _system_and_messages(messages)
    converted: list[dict[str, Any]] = []

    for message in non_system:
        role = message.get("role")
        if role == "tool":
            tool_use_id = str(message.get("tool_call_id") or "")
            converted.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": _message_content_text(message.get("content")),
                        },
                    ],
                },
            )
            continue

        if role == "assistant":
            blocks: list[dict[str, Any]] = []
            text = _message_content_text(message.get("content")).strip()
            if text:
                blocks.append({"type": "text", "text": text})
            for tool_call in message.get("tool_calls") or []:
                function = _tool_function(tool_call)
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
                        "input": _parsed_tool_arguments(raw_arguments),
                    },
                )
            if blocks:
                converted.append({"role": "assistant", "content": blocks})
            continue

        if role == "user":
            converted.append(
                {
                    "role": "user",
                    "content": _message_content_text(message.get("content")),
                },
            )

    return system, converted


def _anthropic_payload(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    system, provider_messages = _anthropic_messages(messages)
    max_tokens = _request_max_output_tokens(config)
    payload: dict[str, Any] = {
        "model": config.model,
        "max_tokens": max_tokens,
        "messages": provider_messages,
    }
    if system:
        payload["system"] = system
    if config.supports_thinking and config.thinking_enabled:
        payload["thinking"] = {
            "type": "enabled",
            "budget_tokens": min(1024, max(128, max_tokens // 2)),
        }
    else:
        if config.temperature is not None:
            payload["temperature"] = config.temperature
        if config.top_p is not None:
            payload["top_p"] = config.top_p
    if tools:
        payload["tools"] = _anthropic_tools(tools)
        payload["tool_choice"] = {"type": "auto"}

    return payload


def _anthropic_headers(config: AgentLlmConfig) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "x-api-key": config.api_key,
        "anthropic-version": ANTHROPIC_VERSION,
    }


def _anthropic_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for block in payload.get("content") or []:
        if not isinstance(block, dict) or block.get("type") != "text":
            continue
        text = block.get("text")
        if isinstance(text, str):
            parts.append(text)

    return "".join(parts).strip()


def _anthropic_tool_calls(payload: dict[str, Any]) -> list[LlmToolCall]:
    tool_calls: list[LlmToolCall] = []
    for block in payload.get("content") or []:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        tool_id = str(block.get("id") or "")
        name = str(block.get("name") or "").strip()
        arguments = block.get("input")
        if not isinstance(arguments, dict) or not tool_id or not name:
            continue
        raw_arguments = json.dumps(arguments, ensure_ascii=False)
        tool_calls.append(
            LlmToolCall(
                id=tool_id,
                name=name,
                arguments=arguments,
                raw_arguments=raw_arguments,
            ),
        )

    return tool_calls


def _complete_anthropic(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
) -> str:
    payload = _post_json(
        f"{_provider_base_url(config.base_url)}/messages",
        headers=_anthropic_headers(config),
        payload=_anthropic_payload(config, messages),
        timeout_seconds=config.timeout_seconds,
    )
    text = _anthropic_text(payload)
    if text:
        return text

    raise LlmRequestError("Model provider returned an empty response.")


async def _async_complete_anthropic(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
) -> str:
    payload = await _async_post_json(
        f"{_provider_base_url(config.base_url)}/messages",
        headers=_anthropic_headers(config),
        payload=_anthropic_payload(config, messages),
        timeout_seconds=config.timeout_seconds,
    )
    text = _anthropic_text(payload)
    if text:
        return text

    raise LlmRequestError("Model provider returned an empty response.")


def _complete_anthropic_tool_call(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> LlmToolCallResponse:
    payload = _post_json(
        f"{_provider_base_url(config.base_url)}/messages",
        headers=_anthropic_headers(config),
        payload=_anthropic_payload(config, messages, tools),
        timeout_seconds=config.timeout_seconds,
    )
    return LlmToolCallResponse(
        content=_anthropic_text(payload),
        tool_calls=_anthropic_tool_calls(payload),
        reasoning="",
    )


async def _async_complete_anthropic_tool_call(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> LlmToolCallResponse:
    payload = await _async_post_json(
        f"{_provider_base_url(config.base_url)}/messages",
        headers=_anthropic_headers(config),
        payload=_anthropic_payload(config, messages, tools),
        timeout_seconds=config.timeout_seconds,
    )
    return LlmToolCallResponse(
        content=_anthropic_text(payload),
        tool_calls=_anthropic_tool_calls(payload),
        reasoning="",
    )


def _gemini_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    system, non_system = _system_and_messages(messages)
    input_items: list[dict[str, Any]] = []
    tool_call_names: dict[str, str] = {}

    for message in non_system:
        role = message.get("role")
        if role == "tool":
            tool_call_id = str(message.get("tool_call_id") or "")
            input_items.append(
                {
                    "type": "function_result",
                    "name": tool_call_names.get(tool_call_id, "tool_result"),
                    "call_id": tool_call_id,
                    "result": [
                        {
                            "type": "text",
                            "text": _message_content_text(message.get("content")),
                        },
                    ],
                },
            )
            continue

        if role == "assistant":
            provider_steps = message.get("provider_steps")
            if isinstance(provider_steps, list):
                appended_provider_step = False
                for step in provider_steps:
                    if not isinstance(step, dict):
                        continue
                    input_items.append(step)
                    appended_provider_step = True
                    if step.get("type") == "function_call":
                        call_id = str(step.get("id") or step.get("call_id") or "")
                        name = str(step.get("name") or "").strip()
                        if call_id and name:
                            tool_call_names[call_id] = name
                if appended_provider_step:
                    continue

            for tool_call in message.get("tool_calls") or []:
                function = _tool_function(tool_call)
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
                        "arguments": _parsed_tool_arguments(raw_arguments),
                    },
                )
            continue

        if role == "user":
            text = _message_content_text(message.get("content"))
            if system:
                text = f"System instructions:\n{system}\n\nUser input:\n{text}"
                system = ""
            input_items.append(
                {
                    "type": "user_input",
                    "content": [{"type": "text", "text": text}],
                },
            )

    return input_items


def _gemini_payload(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": config.model,
        "store": False,
        "input": _gemini_input(messages),
    }
    if tools:
        payload["tools"] = _responses_tools(tools)

    return payload


def _gemini_headers(config: AgentLlmConfig) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "x-goog-api-key": config.api_key,
    }


def _gemini_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text") or payload.get("outputText")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    parts: list[str] = []
    for step in payload.get("steps") or []:
        if not isinstance(step, dict):
            continue
        text = step.get("text")
        if isinstance(text, str):
            parts.append(text)
        for block in step.get("content") or []:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])

    return "".join(parts).strip()


def _gemini_tool_calls(payload: dict[str, Any]) -> list[LlmToolCall]:
    tool_calls: list[LlmToolCall] = []
    for step in payload.get("steps") or []:
        if not isinstance(step, dict) or step.get("type") != "function_call":
            continue
        call_id = str(step.get("id") or step.get("call_id") or "")
        name = str(step.get("name") or "").strip()
        arguments = step.get("arguments")
        if not isinstance(arguments, dict) or not call_id or not name:
            continue
        raw_arguments = json.dumps(arguments, ensure_ascii=False)
        tool_calls.append(
            LlmToolCall(
                id=call_id,
                name=name,
                arguments=arguments,
                raw_arguments=raw_arguments,
            ),
        )

    return tool_calls


def _gemini_provider_steps(payload: dict[str, Any]) -> list[dict[str, Any]]:
    steps = payload.get("steps")
    if not isinstance(steps, list):
        return []

    return [dict(step) for step in steps if isinstance(step, dict)]


def _complete_gemini(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
) -> str:
    payload = _post_json(
        f"{_provider_base_url(config.base_url)}/interactions",
        headers=_gemini_headers(config),
        payload=_gemini_payload(config, messages),
        timeout_seconds=config.timeout_seconds,
    )
    text = _gemini_text(payload)
    if text:
        return text

    raise LlmRequestError("Model provider returned an empty response.")


async def _async_complete_gemini(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
) -> str:
    payload = await _async_post_json(
        f"{_provider_base_url(config.base_url)}/interactions",
        headers=_gemini_headers(config),
        payload=_gemini_payload(config, messages),
        timeout_seconds=config.timeout_seconds,
    )
    text = _gemini_text(payload)
    if text:
        return text

    raise LlmRequestError("Model provider returned an empty response.")


def _complete_gemini_tool_call(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> LlmToolCallResponse:
    payload = _post_json(
        f"{_provider_base_url(config.base_url)}/interactions",
        headers=_gemini_headers(config),
        payload=_gemini_payload(config, messages, tools),
        timeout_seconds=config.timeout_seconds,
    )
    return LlmToolCallResponse(
        content=_gemini_text(payload),
        tool_calls=_gemini_tool_calls(payload),
        reasoning="",
        provider_steps=_gemini_provider_steps(payload),
    )


async def _async_complete_gemini_tool_call(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> LlmToolCallResponse:
    payload = await _async_post_json(
        f"{_provider_base_url(config.base_url)}/interactions",
        headers=_gemini_headers(config),
        payload=_gemini_payload(config, messages, tools),
        timeout_seconds=config.timeout_seconds,
    )
    return LlmToolCallResponse(
        content=_gemini_text(payload),
        tool_calls=_gemini_tool_calls(payload),
        reasoning="",
        provider_steps=_gemini_provider_steps(payload),
    )


def complete_chat(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
) -> str:
    """Call the configured provider family and return visible text."""

    if config.api_family == "openai_responses":
        return _complete_openai_responses(config, messages)
    if config.api_family == "anthropic_messages":
        return _complete_anthropic(config, messages)
    if config.api_family == "google_gemini":
        return _complete_gemini(config, messages)

    return _complete_openai_chat(config, messages)


async def async_complete_chat(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
) -> str:
    """Call the configured provider family asynchronously."""

    if config.api_family == "openai_responses":
        return await _async_complete_openai_responses(config, messages)
    if config.api_family == "anthropic_messages":
        return await _async_complete_anthropic(config, messages)
    if config.api_family == "google_gemini":
        return await _async_complete_gemini(config, messages)

    return await _async_complete_openai_chat(config, messages)


def complete_chat_stream(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
) -> Iterator[LlmStreamDelta]:
    """Stream visible text when supported, otherwise yield one text delta."""

    if config.api_family == "openai_compatible_chat":
        yield from _complete_openai_chat_stream(config, messages)
        return

    text = complete_chat(config, messages)
    if text:
        yield LlmStreamDelta(kind="text", delta=text)


async def async_complete_chat_stream(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
) -> AsyncIterator[LlmStreamDelta]:
    """Async streaming facade over provider adapters."""

    if config.api_family == "openai_compatible_chat":
        async for delta in _async_complete_openai_chat_stream(config, messages):
            yield delta
        return

    text = await async_complete_chat(config, messages)
    if text:
        yield LlmStreamDelta(kind="text", delta=text)


def complete_chat_tool_call(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> LlmToolCallResponse:
    """Ask the selected provider family to choose zero or more tools."""

    if config.api_family == "openai_responses":
        return _complete_openai_responses_tool_call(config, messages, tools)
    if config.api_family == "anthropic_messages":
        return _complete_anthropic_tool_call(config, messages, tools)
    if config.api_family == "google_gemini":
        return _complete_gemini_tool_call(config, messages, tools)

    return _complete_openai_chat_tool_call(config, messages, tools)


async def async_complete_chat_tool_call(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> LlmToolCallResponse:
    """Async tool-choice facade over provider adapters."""

    if config.api_family == "openai_responses":
        return await _async_complete_openai_responses_tool_call(
            config,
            messages,
            tools,
        )
    if config.api_family == "anthropic_messages":
        return await _async_complete_anthropic_tool_call(config, messages, tools)
    if config.api_family == "google_gemini":
        return await _async_complete_gemini_tool_call(config, messages, tools)

    return await _async_complete_openai_chat_tool_call(config, messages, tools)
