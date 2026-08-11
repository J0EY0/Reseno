from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, NotRequired, Required, TypedDict


class LlmTextPart(TypedDict):
    """Provider-neutral text inside one user message."""

    type: Literal["text"]
    text: str


class LlmImagePart(TypedDict):
    """Base64 image data before an Adapter projects its provider wire shape."""

    type: Literal["image"]
    media_type: str
    data: str
    filename: NotRequired[str]


class LlmFilePart(TypedDict):
    """Base64 file data before an Adapter projects its provider wire shape."""

    type: Literal["file"]
    filename: str
    media_type: str
    data: str


LlmContentPart = LlmTextPart | LlmImagePart | LlmFilePart
LlmContent = str | list[LlmContentPart]


class LlmInputFunction(TypedDict):
    """One replayable function selection in the neutral transcript."""

    name: str
    arguments: str


class LlmInputToolCall(TypedDict):
    """OpenAI-style function identity shared by all Adapter projections."""

    id: str
    type: Literal["function"]
    function: LlmInputFunction


class LlmSystemMessage(TypedDict):
    role: Literal["system"]
    content: str


class LlmUserMessage(TypedDict):
    role: Literal["user"]
    content: LlmContent


class LlmAssistantInputMessage(TypedDict, total=False):
    role: Required[Literal["assistant"]]
    content: str | None
    tool_calls: list[LlmInputToolCall]
    reasoning_content: str
    # Continuation state is created and interpreted only by the matching
    # Adapter. The Agent may replay it unchanged, but must not inspect, build,
    # or assume it is portable across providers or models. Provider cache wire
    # fields are deliberately absent from every neutral message type.
    provider_state: dict[str, Any]


class LlmToolMessage(TypedDict):
    role: Literal["tool"]
    tool_call_id: str
    content: str


LlmInputMessage = (
    LlmSystemMessage | LlmUserMessage | LlmAssistantInputMessage | LlmToolMessage
)

LlmStopReason = Literal[
    "stop",
    "tool_calls",
    "length",
    "content_filter",
    "error",
    "unknown",
]

LlmStreamEventType = Literal[
    "activity",
    "text_delta",
    "reasoning_delta",
    "done",
]


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
class LlmRequestContext:
    """Opaque request identity for provider-owned request optimizations."""

    cache_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.cache_key, str):
            raise TypeError("cache_key must be a string.")

        cache_key = self.cache_key.strip()
        if not cache_key or len(cache_key) > 64:
            raise ValueError("cache_key must contain 1 to 64 characters.")

        object.__setattr__(self, "cache_key", cache_key)


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

    `provider_state` contains only Adapter-owned continuation material required
    by the next request, such as Gemini interaction steps or OpenAI encrypted
    reasoning items. It is never a raw provider response, display reasoning,
    prompt-cache metadata, or state that another Adapter may interpret.
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
