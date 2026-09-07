import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest

from app.services.llm import common, dispatch
from app.services.llm.errors import LlmRequestError
from app.services.llm.types import AgentLlmConfig, LlmPrompt


class ResponseBody(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.read_count = 0
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            self.read_count += 1
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.parametrize("api_family", ["anthropic_messages", "google_gemini"])
@pytest.mark.parametrize("status_code", [302, 400, 401, 403, 429, 500])
def test_native_provider_stream_preserves_safe_http_error(
    monkeypatch: pytest.MonkeyPatch,
    api_family: str,
    status_code: int,
) -> None:
    body = ResponseBody([b'{"error":{"message":"secret-provider-detail"}}'])
    response = httpx.Response(status_code, stream=body)
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response))
    monkeypatch.setattr(common.httpx, "AsyncClient", lambda **_: client)
    config = AgentLlmConfig(
        client_id="native-stream-test",
        name="Native stream",
        provider="test",
        api_family=api_family,
        model="test-model",
        base_url="https://provider.invalid",
        api_key="test-only",
        temperature=None,
        top_p=None,
        max_tokens=None,
        timeout_seconds=10,
        supports_streaming=True,
    )

    async def run() -> None:
        async for _ in dispatch.async_stream_tool_call(
            config,
            LlmPrompt(messages=[{"role": "user", "content": "Hello"}]),
            [],
        ):
            pass

    with pytest.raises(LlmRequestError) as error:
        asyncio.run(run())

    assert error.value.status_code == status_code
    assert str(error.value) == f"Model provider returned HTTP {status_code}."
    assert response.is_stream_consumed
    assert body.closed
    assert client.is_closed


@pytest.mark.parametrize("status_code", [400, 415])
def test_stream_preserves_unsupported_attachment_classification(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    body = ResponseBody([b'{"error":{"message":"Unsupported PDF attachment"}}'])
    response = httpx.Response(status_code, stream=body)
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response))
    monkeypatch.setattr(common.httpx, "AsyncClient", lambda **_: client)

    async def run() -> None:
        async for _ in common.async_stream_json(
            "https://provider.invalid",
            headers={},
            payload={},
            timeout_seconds=10,
        ):
            pass

    with pytest.raises(LlmRequestError) as error:
        asyncio.run(run())

    assert error.value.status_code == status_code
    assert str(error.value) == (
        f"Model provider returned HTTP {status_code}: unsupported attachment."
    )
    assert body.closed
    assert client.is_closed


def test_successful_stream_yields_before_reading_the_remaining_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = ResponseBody(
        [
            b'data: {"index": 1}\n\n',
            b'data: {"index": 2}\n\n',
        ]
    )
    response = httpx.Response(200, stream=body)
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response))
    monkeypatch.setattr(common.httpx, "AsyncClient", lambda **_: client)

    async def run() -> None:
        stream = common.async_stream_json(
            "https://provider.invalid",
            headers={},
            payload={},
            timeout_seconds=10,
        )
        try:
            assert await anext(stream) == {"index": 1}
            assert body.read_count == 1
        finally:
            await stream.aclose()

    asyncio.run(run())

    assert body.closed
    assert client.is_closed
