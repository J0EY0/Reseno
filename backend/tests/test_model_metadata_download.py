import asyncio
import gzip

import httpx
import pytest

from app.services import model_metadata


@pytest.mark.parametrize(
    ("status", "payload", "expected"),
    [
        (
            200,
            b'{"model": {"max_input_tokens": 128000}}',
            {"model": {"max_input_tokens": 128000}},
        ),
        (200, b"[]", {}),
        (200, b"not json", {}),
        (503, b'{"error": "unavailable"}', {}),
    ],
)
def test_download_validates_complete_response(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    payload: bytes,
    expected: dict,
) -> None:
    client_type = httpx.AsyncClient

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["user-agent"] == "Reseno/0.1 model metadata"
        return httpx.Response(
            status,
            headers={"content-encoding": "gzip"},
            content=gzip.compress(payload),
        )

    monkeypatch.setattr(
        model_metadata.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(
            **kwargs,
            transport=httpx.MockTransport(respond),
        ),
    )

    assert (
        asyncio.run(model_metadata._fetch_json("https://catalog.invalid/api.json"))
        == expected
    )


def test_download_deadline_covers_response_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed = False

    class WaitingBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"model":'
            await asyncio.Event().wait()

        async def aclose(self) -> None:
            nonlocal closed
            closed = True

    client_type = httpx.AsyncClient
    monkeypatch.setattr(model_metadata, "MODEL_METADATA_FETCH_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr(
        model_metadata.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(
            **kwargs,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, stream=WaitingBody()),
            ),
        ),
    )

    assert (
        asyncio.run(model_metadata._fetch_json("https://catalog.invalid/api.json"))
        == {}
    )
    assert closed


def test_download_limits_decoded_payload_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_type = httpx.AsyncClient
    monkeypatch.setattr(model_metadata, "MODEL_METADATA_MAX_DOWNLOAD_BYTES", 100)
    monkeypatch.setattr(
        model_metadata.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(
            **kwargs,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    headers={"content-encoding": "gzip"},
                    content=gzip.compress(b'{"model": "' + b"a" * 1000 + b'"}'),
                ),
            ),
        ),
    )

    assert (
        asyncio.run(model_metadata._fetch_json("https://catalog.invalid/api.json"))
        == {}
    )


def test_unavailable_proxy_dependency_does_not_break_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_dependency(**kwargs):
        raise ImportError("SOCKS dependency is unavailable")

    monkeypatch.setattr(model_metadata.httpx, "AsyncClient", missing_dependency)
    assert (
        asyncio.run(model_metadata._fetch_json("https://catalog.invalid/api.json"))
        == {}
    )
