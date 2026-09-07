from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from hashlib import sha256
from typing import TYPE_CHECKING, Any, TypeVar

import anyio

from app.schemas.agent import (
    AgentChatRequest,
    AgentConversationCheckpoint,
    AgentToolInvocation,
)
from app.services.llm import (
    AgentLlmConfig,
    LlmAssistantMessage,
    LlmRequestContext,
    LlmRequestError,
    LlmUsage,
)
from app.services.llm.common import supports_prompt_cache_key
from app.services.llm.types import LlmStopReason

if TYPE_CHECKING:
    from .loop import AgentToolLoopEvent

DEFAULT_BLOCKING_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_MODEL_TURNS = 16

T = TypeVar("T")


class AgentRunAborted(Exception):
    """Raised when the user has explicitly cancelled the active Agent run."""


class AgentContextWindowError(LlmRequestError):
    """Raised when local prompt compilation cannot fit the selected model."""


@dataclass
class AgentConversationState:
    """Mutable prompt-compiler state shared by every phase of one accepted turn.

    Conversation checkpoints are durable backend state, not client request
    data. Keeping both boundaries here makes the state transition explicit:
    compaction advances ``active_checkpoint`` while terminal persistence can
    compare it with the checkpoint loaded when the turn was accepted.
    """

    loaded_checkpoint: AgentConversationCheckpoint | None = None
    active_checkpoint: AgentConversationCheckpoint | None = None


@dataclass(frozen=True)
class AgentRuntimeContext:
    """Runtime controls shared across Agent streaming, tool calls, and tools."""

    is_aborted: Callable[[], Awaitable[bool]] | None = None
    conversation_state: AgentConversationState = field(
        default_factory=AgentConversationState,
    )
    blocking_timeout_seconds: float = DEFAULT_BLOCKING_TIMEOUT_SECONDS
    max_model_turns: int = DEFAULT_MAX_MODEL_TURNS
    llm_request_context: LlmRequestContext | None = None
    on_llm_attempt: Callable[[], None] | None = None
    on_llm_response: Callable[[LlmUsage | None, LlmStopReason], None] | None = None
    on_tool_loop_event: Callable[["AgentToolLoopEvent"], None] | None = None
    on_tool_result: Callable[[AgentToolInvocation], None] | None = None

    def with_llm_request_context(
        self,
        request_context: LlmRequestContext | None,
    ) -> "AgentRuntimeContext":
        """Bind one provider request identity to every call in this run."""

        return replace(self, llm_request_context=request_context)

    def record_llm_response(self, message: LlmAssistantMessage) -> None:
        """Publish provider-neutral response metadata to an optional observer."""

        if self.on_llm_response is not None:
            self.on_llm_response(message.usage, message.stop_reason)

    def record_llm_attempt(self) -> None:
        """Record one provider transport attempt before it begins."""

        if self.on_llm_attempt is not None:
            self.on_llm_attempt()

    def record_tool_loop_event(self, event: "AgentToolLoopEvent") -> None:
        """Publish one tool-loop event to an optional request observer."""

        if self.on_tool_loop_event is not None:
            self.on_tool_loop_event(event)

    def record_tool_result(self, tool: AgentToolInvocation) -> None:
        """Observe one tool outcome, including writes deferred before execution."""

        if self.on_tool_result is not None:
            self.on_tool_result(tool)

    async def checkpoint(self) -> None:
        """Yield control and stop after an explicit cancellation request."""

        if self.is_aborted and await self.is_aborted():
            raise AgentRunAborted

        await anyio.sleep(0)

    async def run_sync(
        self,
        func: Callable[..., T],
        *args: Any,
        timeout_seconds: float | None = None,
    ) -> T:
        """Run sync work without pinning the event loop after cancellation.

        An abandoned worker may finish in the background, so callers must pass
        isolated state when the function can mutate request-scoped data.
        """

        await self.checkpoint()
        try:
            with anyio.fail_after(timeout_seconds or self.blocking_timeout_seconds):
                result = await anyio.to_thread.run_sync(
                    func,
                    *args,
                    abandon_on_cancel=True,
                )
        except TimeoutError as exc:
            raise LlmRequestError("Agent operation timed out.") from exc

        await self.checkpoint()
        return result

    async def run_async(
        self,
        func: Callable[..., Awaitable[T]],
        *args: Any,
        timeout_seconds: float | None = None,
    ) -> T:
        """Run async work inside the same cancellation and timeout budget."""

        await self.checkpoint()
        try:
            if timeout_seconds is None:
                result = await func(*args)
            else:
                with anyio.fail_after(timeout_seconds):
                    result = await func(*args)
        except TimeoutError as exc:
            raise LlmRequestError("Agent operation timed out.") from exc

        await self.checkpoint()
        return result


def agent_llm_request_context(
    request: AgentChatRequest,
    config: AgentLlmConfig,
) -> LlmRequestContext | None:
    """Derive one opaque cache identity for an official cache-aware resume run."""

    resume_id = (request.resume_id or "").strip()
    if not supports_prompt_cache_key(config) or not resume_id:
        return None

    cache_key = sha256(
        f"reseno-agent-prompt-cache:{resume_id}".encode(),
    ).hexdigest()
    return LlmRequestContext(cache_key=cache_key)
