from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

LlmStopReason = Literal[
    "stop",
    "tool_calls",
    "length",
    "content_filter",
    "error",
    "unknown",
]

LlmStreamEventType = Literal["text_delta", "reasoning_delta", "done"]


@dataclass(frozen=True)
class AgentLlmConfig:
    """Runtime-only model config; plaintext keys never leave backend memory."""

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
    supports_tools: bool = True
    supports_streaming: bool = True
    thinking_enabled: bool = False


@dataclass(frozen=True)
class LlmUsage:
    """Provider-normalized token usage without pricing or persistence concerns."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cached_input_tokens: int | None = None
    reasoning_tokens: int | None = None


@dataclass(frozen=True)
class LlmToolCall:
    """One model-selected function call in the provider-independent shape."""

    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str
    parse_error: str = ""


@dataclass(frozen=True)
class LlmToolValidationError:
    """A tool call that must be sent back to the model instead of executed."""

    tool_call: LlmToolCall
    message: str
    path: str = ""


@dataclass(frozen=True)
class LlmAssistantMessage:
    """The internal LLM contract consumed by the agent runtime.

    `provider_state` intentionally stays small: it is for provider-specific
    continuation state such as Gemini interaction steps, not raw responses.
    """

    content: str = ""
    tool_calls: list[LlmToolCall] = field(default_factory=list)
    validation_errors: list[LlmToolValidationError] = field(default_factory=list)
    reasoning: str = ""
    usage: LlmUsage | None = None
    stop_reason: LlmStopReason = "unknown"
    response_id: str | None = None
    provider_state: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LlmStreamEvent:
    """One provider stream event; the final event carries the unified message."""

    type: LlmStreamEventType
    delta: str = ""
    message: LlmAssistantMessage | None = None
