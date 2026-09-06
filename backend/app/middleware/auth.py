from collections.abc import Awaitable, Callable

from fastapi import Request, status
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from app.exceptions import app_error_response
from app.schemas.common import APP_CODE_UNAUTHORIZED, APP_MESSAGE_UNAUTHORIZED
from app.services.auth_accounts import owner_identity_matches
from app.services.auth_tokens import AuthTokenError, decode_access_token

PUBLIC_API_PATHS = {
    "/api/auth/login",
    "/api/auth/setup",
    "/api/auth/oauth/complete",
    "/api/auth/oauth/github/login",
    "/api/auth/oauth/github/callback",
    "/api/auth/oauth/github/setup/callback",
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
        status_code=status.HTTP_401_UNAUTHORIZED,
        code=APP_CODE_UNAUTHORIZED,
        message=APP_MESSAGE_UNAUTHORIZED,
        data={
            "loginUrl": LOGIN_URL,
            "reason": reason,
        },
        headers={"WWW-Authenticate": "Bearer"},
    )


async def jwt_auth_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Validate JWTs for every protected API route."""

    path = request.url.path

    if (
        request.method == "OPTIONS"
        or not path.startswith("/api/")
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

    identity_matches = await run_in_threadpool(
        owner_identity_matches,
        payload.subject,
        payload.auth_revision,
    )
    if not identity_matches:
        return unauthorized_response("owner_missing_or_changed")

    request.state.auth_token = token
    request.state.auth_payload = payload

    return await call_next(request)
