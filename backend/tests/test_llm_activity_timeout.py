import asyncio

import anyio
import pytest

from app.services.llm.activity import iter_with_activity_timeout
from app.services.llm.errors import LlmTimeoutError
from app.services.llm.types import LlmAssistantMessage, LlmStreamEvent


def test_active_provider_stream_can_outlive_each_timeout_window() -> None:
    async def scenario() -> list[LlmStreamEvent]:
        async def active_stream():
            await anyio.sleep(0.02)
            yield LlmStreamEvent(type="reasoning_delta", delta="thinking")
            await anyio.sleep(0.02)
            yield LlmStreamEvent(type="activity")
            await anyio.sleep(0.02)
            yield LlmStreamEvent(type="activity")
            await anyio.sleep(0.02)
            yield LlmStreamEvent(
                type="done",
                message=LlmAssistantMessage(content="done", stop_reason="stop"),
            )

        return [
            event
            async for event in iter_with_activity_timeout(
                active_stream(),
                first_event_timeout_seconds=0.06,
                idle_timeout_seconds=0.06,
            )
        ]

    events = asyncio.run(scenario())

    assert [event.type for event in events] == [
        "reasoning_delta",
        "activity",
        "activity",
        "done",
    ]


@pytest.mark.parametrize("emit_first_event", [False, True])
def test_provider_stream_times_out_only_after_activity_stops(
    emit_first_event: bool,
) -> None:
    class BlockingStream:
        def __init__(self) -> None:
            self._first_event_pending = emit_first_event
            self.close_count = 0

        def __aiter__(self) -> "BlockingStream":
            return self

        async def __anext__(self) -> LlmStreamEvent:
            if self._first_event_pending:
                self._first_event_pending = False
                return LlmStreamEvent(type="activity")
            await anyio.sleep_forever()
            raise AssertionError("unreachable")

        async def aclose(self) -> None:
            self.close_count += 1

    async def scenario() -> BlockingStream:
        stream = BlockingStream()
        with pytest.raises(LlmTimeoutError, match="timed out"):
            async for _ in iter_with_activity_timeout(
                stream,
                first_event_timeout_seconds=0.02,
                idle_timeout_seconds=0.02,
            ):
                pass
        return stream

    stream = asyncio.run(scenario())

    assert stream.close_count == 1
