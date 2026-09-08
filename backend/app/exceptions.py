import logging
from collections.abc import Mapping
from math import isfinite
from typing import Any

from fastapi import Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.schemas.common import (
    APP_CODE_BAD_REQUEST,
    APP_CODE_INTERNAL_ERROR,
    APP_CODE_NOT_FOUND,
    APP_CODE_UNAUTHORIZED,
    APP_CODE_VALIDATION_ERROR,
    APP_MESSAGE_BAD_REQUEST,
    APP_MESSAGE_INTERNAL_ERROR,
    APP_MESSAGE_NOT_FOUND,
    APP_MESSAGE_UNAUTHORIZED,
    APP_MESSAGE_VALIDATION_ERROR,
    error_response,
)

logger = logging.getLogger(__name__)


def app_error_payload(
    *,
    code: int,
    message: str,
    data: object | None = None,
) -> dict[str, Any]:
    """Serialize a business error response with API aliases."""

    return error_response(code=code, message=message, data=data).model_dump(
        mode="json",
        by_alias=True,
    )


def app_error_response(
    *,
    status_code: int,
    code: int,
    message: str,
    data: object | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Return an HTTP error response carrying the business error payload."""

    return JSONResponse(
        status_code=status_code,
        content=app_error_payload(code=code, message=message, data=data),
        headers=headers,
    )


def _http_status_to_app_code(status_code: int) -> int:
    """Map HTTP exceptions onto stable application error codes."""

    if status_code == status.HTTP_401_UNAUTHORIZED:
        return APP_CODE_UNAUTHORIZED

    if status_code == status.HTTP_404_NOT_FOUND:
        return APP_CODE_NOT_FOUND

    if status_code >= 500:
        return APP_CODE_INTERNAL_ERROR

    return APP_CODE_BAD_REQUEST


def _detail_to_message_key(detail: object, fallback: str) -> str:
    """Use stable uppercase details as i18n keys when available."""

    if (
        isinstance(detail, str)
        and detail.strip()
        and detail.upper() == detail
        and all(char.isalnum() or char == "_" for char in detail)
    ):
        return detail

    return fallback


async def http_exception_handler(
    request: Request,
    exc: HTTPException,
) -> JSONResponse:
    """Convert API HTTP exceptions into the unified response envelope."""

    if not request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers,
        )

    code = _http_status_to_app_code(exc.status_code)
    if code == APP_CODE_UNAUTHORIZED:
        headers = dict(exc.headers or {})
        headers.setdefault("WWW-Authenticate", "Bearer")
        return app_error_response(
            status_code=exc.status_code,
            code=APP_CODE_UNAUTHORIZED,
            message=_detail_to_message_key(exc.detail, APP_MESSAGE_UNAUTHORIZED),
            data={"loginUrl": "/login"},
            headers=headers,
        )

    fallback_message = {
        APP_CODE_BAD_REQUEST: APP_MESSAGE_BAD_REQUEST,
        APP_CODE_NOT_FOUND: APP_MESSAGE_NOT_FOUND,
        APP_CODE_INTERNAL_ERROR: APP_MESSAGE_INTERNAL_ERROR,
    }.get(code, APP_MESSAGE_BAD_REQUEST)

    return app_error_response(
        status_code=exc.status_code,
        code=code,
        message=_detail_to_message_key(exc.detail, fallback_message),
        data=None,
        headers=exc.headers,
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Convert request validation failures into the API envelope."""

    errors = jsonable_encoder(
        exc.errors(),
        custom_encoder={
            Exception: str,
            float: lambda value: value if isfinite(value) else str(value),
        },
    )
    if not request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": errors},
        )

    return app_error_response(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code=APP_CODE_VALIDATION_ERROR,
        message=APP_MESSAGE_VALIDATION_ERROR,
        data={"errors": errors},
    )


async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Hide unhandled API exceptions behind a stable internal-error key."""

    if not request.url.path.startswith("/api/"):
        raise exc

    logger.exception(
        "Unhandled API exception for %s %s",
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return app_error_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code=APP_CODE_INTERNAL_ERROR,
        message=APP_MESSAGE_INTERNAL_ERROR,
        data=None,
    )
