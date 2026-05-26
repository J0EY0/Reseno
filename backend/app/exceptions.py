from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

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
    code: int,
    message: str,
    data: object | None = None,
) -> JSONResponse:
    """Return an HTTP 200 response carrying the business error payload."""

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=app_error_payload(code=code, message=message, data=data),
    )


def _http_status_to_app_code(status_code: int) -> int:
    """Map FastAPI HTTP exceptions onto stable application error codes."""

    if status_code in {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN}:
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
        return app_error_response(
            code=APP_CODE_UNAUTHORIZED,
            message=_detail_to_message_key(exc.detail, APP_MESSAGE_UNAUTHORIZED),
            data={"loginUrl": "/login"},
        )

    fallback_message = {
        APP_CODE_BAD_REQUEST: APP_MESSAGE_BAD_REQUEST,
        APP_CODE_NOT_FOUND: APP_MESSAGE_NOT_FOUND,
        APP_CODE_INTERNAL_ERROR: APP_MESSAGE_INTERNAL_ERROR,
    }.get(code, APP_MESSAGE_BAD_REQUEST)

    return app_error_response(
        code=code,
        message=_detail_to_message_key(exc.detail, fallback_message),
        data=None,
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Convert request validation failures into the API envelope."""

    if not request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": exc.errors()},
        )

    return app_error_response(
        code=APP_CODE_VALIDATION_ERROR,
        message=APP_MESSAGE_VALIDATION_ERROR,
        data={"errors": exc.errors()},
    )


async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Hide unhandled API exceptions behind a stable internal-error key."""

    if not request.url.path.startswith("/api/"):
        raise exc

    return app_error_response(
        code=APP_CODE_INTERNAL_ERROR,
        message=APP_MESSAGE_INTERNAL_ERROR,
        data=None,
    )
