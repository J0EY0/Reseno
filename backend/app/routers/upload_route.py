from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.params import Form
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException
from starlette.formparsers import MultiPartException
from starlette.types import Message

from app.schemas.common import APP_MESSAGE_BAD_REQUEST

MAX_MULTIPART_BODY_BYTES = 10 * 1024 * 1024 + 64 * 1024


class LimitedUploadRoute(APIRoute):
    """Limit multipart streams before parsing and allow one uploaded file."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()
        if not any(
            isinstance(field.field_info, Form) for field in self.dependant.body_params
        ):
            return handler
        message = (
            "JSON_UPLOAD_TOO_LARGE"
            if self.path.startswith("/api/import/")
            else APP_MESSAGE_BAD_REQUEST
        )

        async def limited_handler(request: Request) -> Response:
            content_length = request.headers.get("content-length")
            if content_length and content_length.isdecimal():
                if int(content_length) > MAX_MULTIPART_BODY_BYTES:
                    raise HTTPException(status_code=413, detail=message)
            received = 0

            async def receive() -> Message:
                nonlocal received
                event = await request.receive()
                if event["type"] == "http.request":
                    received += len(event.get("body", b""))
                    if received > MAX_MULTIPART_BODY_BYTES:
                        raise MultiPartException(message)
                return event

            limited_request = Request(request.scope, receive=receive)
            try:
                try:
                    await limited_request.form(
                        max_files=1, max_fields=1, max_part_size=1024
                    )
                except MultiPartException as exc:
                    raise HTTPException(status_code=413, detail=message) from exc
                except HTTPException as exc:
                    if exc.detail == message:
                        raise HTTPException(status_code=413, detail=message) from exc
                    raise
                except Exception as exc:
                    raise HTTPException(
                        status_code=400,
                        detail=APP_MESSAGE_BAD_REQUEST,
                    ) from exc
                return await handler(limited_request)
            finally:
                await limited_request.close()

        return limited_handler
