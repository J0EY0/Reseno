from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

import anyio

from app.services.llm import LlmRequestError

DEFAULT_BLOCKING_TIMEOUT_SECONDS = 30.0

T = TypeVar("T")


class AgentRunAborted(Exception):
    """Raised when the client has cancelled the active Agent run."""


@dataclass(frozen=True)
class AgentRuntimeContext:
    """Runtime controls shared across Agent streaming, tool calls, and tools."""

    is_aborted: Callable[[], Awaitable[bool]] | None = None
    blocking_timeout_seconds: float = DEFAULT_BLOCKING_TIMEOUT_SECONDS

    async def checkpoint(self) -> None:
        """Yield control and stop if the client has already gone away."""

        if self.is_aborted and await self.is_aborted():
            raise AgentRunAborted

        await anyio.sleep(0)

    async def run_sync(
        self,
        func: Callable[..., T],
        *args: Any,
        timeout_seconds: float | None = None,
    ) -> T:
        """Run sync work without pinning the event loop after cancellation."""

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
