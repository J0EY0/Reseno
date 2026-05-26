from hmac import compare_digest

from fastapi import APIRouter, HTTPException, Request, status

from app.config import get_settings, update_auth_password
from app.middleware.auth import extract_bearer_token
from app.schemas.auth import (
    AuthLoginRequest,
    AuthLoginResponse,
    AuthPasswordUpdateRequest,
    AuthPasswordUpdateResponse,
)
from app.schemas.common import (
    APP_MESSAGE_INVALID_CREDENTIALS,
    APP_MESSAGE_PASSWORD_CONFIRMATION_MISMATCH,
    APP_MESSAGE_PASSWORD_REQUIRED,
    APP_MESSAGE_PASSWORD_TOO_SHORT,
    APP_MESSAGE_UNAUTHORIZED,
    ApiResponse,
    ok_response,
)
from app.services.auth_tokens import (
    create_access_token,
    format_token_expiry,
    refresh_access_token,
    revoke_access_token,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _token_response(username: str) -> AuthLoginResponse:
    """Create the standard login response for a username."""

    token, payload = create_access_token(username)
    return AuthLoginResponse(
        username=username,
        accessToken=token,
        expiresAt=format_token_expiry(payload.expires_at),
        tokenType="bearer",
    )


@router.post("/login", response_model=ApiResponse[AuthLoginResponse])
def post_auth_login(
    request: AuthLoginRequest,
) -> ApiResponse[AuthLoginResponse]:
    """Validate credentials and issue an access token."""

    username = request.username.strip()
    settings = get_settings()

    for credential in settings.auth_credentials:
        if compare_digest(credential.username, username) and compare_digest(
            credential.password,
            request.password,
        ):
            return ok_response(_token_response(username))

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=APP_MESSAGE_INVALID_CREDENTIALS,
    )


@router.post("/refresh", response_model=ApiResponse[AuthLoginResponse])
def post_auth_refresh(request: Request) -> ApiResponse[AuthLoginResponse]:
    """Refresh a valid access token and revoke the previous token."""

    token = getattr(request.state, "auth_token", None) or extract_bearer_token(
        request.headers.get("Authorization"),
    )
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=APP_MESSAGE_UNAUTHORIZED,
        )

    refreshed_token, payload = refresh_access_token(token)

    return ok_response(
        AuthLoginResponse(
            username=payload.subject,
            accessToken=refreshed_token,
            expiresAt=format_token_expiry(payload.expires_at),
            tokenType="bearer",
        ),
    )


@router.post("/password", response_model=ApiResponse[AuthPasswordUpdateResponse])
def post_auth_password(
    request: Request,
    payload: AuthPasswordUpdateRequest,
) -> ApiResponse[AuthPasswordUpdateResponse]:
    """Change the configured login password after verifying the current one."""

    settings = get_settings()
    auth_payload = getattr(request.state, "auth_payload", None)
    username = getattr(auth_payload, "subject", "")
    if not username and not settings.auth_required and settings.auth_credentials:
        username = settings.auth_credentials[0].username

    credential = next(
        (item for item in settings.auth_credentials if item.username == username),
        None,
    )

    if credential is None or not compare_digest(
        credential.password,
        payload.current_password,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=APP_MESSAGE_INVALID_CREDENTIALS,
        )

    next_password = payload.new_password.strip()
    if not next_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=APP_MESSAGE_PASSWORD_REQUIRED,
        )

    if len(next_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=APP_MESSAGE_PASSWORD_TOO_SHORT,
        )

    if next_password != payload.confirm_password.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=APP_MESSAGE_PASSWORD_CONFIRMATION_MISMATCH,
        )

    update_auth_password(settings.env_file_path, next_password)
    token = getattr(request.state, "auth_token", None) or extract_bearer_token(
        request.headers.get("Authorization"),
    )
    if token:
        revoke_access_token(token)

    return ok_response(AuthPasswordUpdateResponse(username=username))
