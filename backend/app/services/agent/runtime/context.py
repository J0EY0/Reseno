from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from hashlib import sha256
from typing import Any, TypeVar

import anyio

from app.schemas.agent import AgentChatRequest
from app.services.llm import (
    AgentLlmConfig,
    LlmRequestContext,
    LlmRequestError,
)

DEFAULT_BLOCKING_TIMEOUT_SECONDS = 30.0

T = TypeVar("T")


class AgentRunAborted(Exception):
    """Raised when the user has explicitly cancelled the active Agent run."""


@dataclass(frozen=True)
class AgentRuntimeContext:
    """Runtime controls shared across Agent streaming, tool calls, and tools."""

    is_aborted: Callable[[], Awaitable[bool]] | None = None
    blocking_timeout_seconds: float = DEFAULT_BLOCKING_TIMEOUT_SECONDS
    llm_request_context: LlmRequestContext | None = None

    def with_llm_request_context(
        self,
        request_context: LlmRequestContext | None,
    ) -> "AgentRuntimeContext":
        """Bind one provider request identity to every call in this run."""

        return replace(self, llm_request_context=request_context)

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
    """Derive one opaque cache identity for an official OpenAI resume run."""

    resume_id = (request.resume_id or "").strip()
    if config.provider != "openai" or config.provider_kind != "cloud" or not resume_id:
        return None

    cache_key = sha256(
        f"resumate-agent-prompt-cache:{resume_id}".encode(),
    ).hexdigest()
    return LlmRequestContext(cache_key=cache_key)
