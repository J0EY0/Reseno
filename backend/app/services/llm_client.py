import json
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from inspect import isawaitable
from sqlite3 import Connection
from typing import Any, Literal

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
    temperature: float
    top_p: float
    max_tokens: int | None
    timeout_seconds: int
    system_prompt: str
    context_window_tokens: int | None = None


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
                model,
                base_url,
                encrypted_api_key,
                temperature,
                top_p,
                max_tokens,
                context_window_tokens,
                timeout_seconds,
                system_prompt
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
                model,
                base_url,
                encrypted_api_key,
                temperature,
                top_p,
                max_tokens,
                context_window_tokens,
                timeout_seconds,
                system_prompt
            FROM llm_configs
            WHERE enabled = 1
            ORDER BY is_default DESC, updated_at DESC, id DESC
            LIMIT 1
            """,
        ).fetchone()

    if row is None or not row["encrypted_api_key"]:
        return None

    return AgentLlmConfig(
        client_id=row["client_id"],
        name=row["name"],
        provider=row["provider"],
        model=row["model"],
        base_url=row["base_url"] or DEFAULT_OPENAI_BASE_URL,
        api_key=decrypt_api_key(row["encrypted_api_key"]),
        temperature=float(row["temperature"]),
        top_p=float(row["top_p"]),
        max_tokens=row["max_tokens"],
        timeout_seconds=int(row["timeout_seconds"] or REQUEST_TIMEOUT_SECONDS),
        system_prompt=row["system_prompt"] or "",
        context_window_tokens=row["context_window_tokens"],
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
        "temperature": config.temperature,
        "top_p": config.top_p,
        "stream": stream,
    }
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
        api_key=config.api_key,
        base_url=_openai_base_url(config.base_url),
        timeout=max(5, config.timeout_seconds),
    )


def _async_client(config: AgentLlmConfig) -> AsyncOpenAI:
    """Build an async SDK client for one request-scoped model config."""

    return AsyncOpenAI(
        api_key=config.api_key,
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


def complete_chat(
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


async def async_complete_chat(
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


def complete_chat_stream(
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
            reasoning = _delta_text(delta, ("reasoning_content", "reasoning"))
            if reasoning:
                yield LlmStreamDelta(kind="reasoning", delta=reasoning)

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


async def async_complete_chat_stream(
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
            reasoning = _delta_text(delta, ("reasoning_content", "reasoning"))
            if reasoning:
                yield LlmStreamDelta(kind="reasoning", delta=reasoning)

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


def complete_chat_tool_call(
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
    reasoning = _delta_text(message, ("reasoning_content", "reasoning"))
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
        reasoning=reasoning,
    )


async def async_complete_chat_tool_call(
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
    reasoning = _delta_text(message, ("reasoning_content", "reasoning"))
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
        reasoning=reasoning,
    )
