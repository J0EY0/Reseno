from collections.abc import Awaitable, Callable

from fastapi import Request
from fastapi.responses import Response

from app.config import get_settings
from app.exceptions import app_error_response
from app.schemas.common import APP_CODE_UNAUTHORIZED, APP_MESSAGE_UNAUTHORIZED
from app.services.auth_tokens import AuthTokenError, decode_access_token

PUBLIC_API_PATHS = {
    "/api/auth/login",
}
LOGIN_URL = "/login"


def extract_bearer_token(authorization: str | None) -> str | None:
    """Extract a Bearer token from an Authorization header."""

    if not authorization:
        return None

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None

    return token.strip()


def unauthorized_response(reason: str) -> Response:
    """Build the standard unauthorized API envelope."""

    return app_error_response(
        code=APP_CODE_UNAUTHORIZED,
        message=APP_MESSAGE_UNAUTHORIZED,
        data={
            "loginUrl": LOGIN_URL,
            "reason": reason,
        },
    )


async def jwt_auth_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Validate JWTs for protected API routes when production auth is enabled."""

    path = request.url.path

    if (
        request.method == "OPTIONS"
        or not path.startswith("/api/")
        or not get_settings().auth_required
        or path in PUBLIC_API_PATHS
    ):
        return await call_next(request)

    token = extract_bearer_token(request.headers.get("Authorization"))
    if not token:
        return unauthorized_response("missing_token")

    try:
        payload = decode_access_token(token)
    except AuthTokenError:
        return unauthorized_response("invalid_or_expired_token")

    request.state.auth_token = token
    request.state.auth_payload = payload

    return await call_next(request)
