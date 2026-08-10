from collections.abc import AsyncIterator

import anyio

from .common import close_async_stream
from .errors import LlmTimeoutError
from .types import LlmStreamEvent


async def iter_with_activity_timeout(
    events: AsyncIterator[LlmStreamEvent],
    *,
    first_event_timeout_seconds: float,
    idle_timeout_seconds: float,
) -> AsyncIterator[LlmStreamEvent]:
    """Guard first-event and idle gaps without imposing a total deadline.

    Every normalized semantic event starts a fresh idle window. Provider
    adapters deliberately omit transport pings and empty chunks from this
    stream, so those cannot keep a stalled request alive.
    """

    iterator = events.__aiter__()
    timeout_seconds = first_event_timeout_seconds
    try:
        while True:
            try:
                with anyio.fail_after(timeout_seconds) as timeout_scope:
                    event = await anext(iterator)
            except StopAsyncIteration:
                return
            except TimeoutError as exc:
                if not timeout_scope.cancel_called:
                    raise
                raise LlmTimeoutError(
                    "Model provider request timed out.",
                ) from exc

            yield event
            timeout_seconds = idle_timeout_seconds
    finally:
        await close_async_stream(iterator)
