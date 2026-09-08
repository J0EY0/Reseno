import re
from ipaddress import ip_address

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.middleware.auth import extract_bearer_token
from app.schemas.auth import (
    AuthLoginRequest,
    AuthLoginResponse,
    AuthPasswordUpdateRequest,
    AuthPasswordUpdateResponse,
    AuthSetupRequest,
    AuthSetupStatusResponse,
)
from app.schemas.common import (
    APP_MESSAGE_INVALID_CREDENTIALS,
    APP_MESSAGE_PASSWORD_COMPLEXITY_REQUIRED,
    APP_MESSAGE_PASSWORD_CONFIRMATION_MISMATCH,
    APP_MESSAGE_PASSWORD_REQUIRED,
    APP_MESSAGE_PASSWORD_TOO_SHORT,
    APP_MESSAGE_SETUP_ALREADY_COMPLETED,
    APP_MESSAGE_SETUP_LOCAL_ONLY,
    APP_MESSAGE_UNAUTHORIZED,
    APP_MESSAGE_USERNAME_INVALID,
    APP_MESSAGE_USERNAME_REQUIRED,
    ApiResponse,
    ok_response,
)
from app.services.auth_accounts import (
    OwnerAccount,
    OwnerAlreadyExistsError,
    authenticate_owner,
    create_owner,
    is_setup_required,
    update_owner_password,
)
from app.services.auth_github_app import github_app_configured
from app.services.auth_identities import list_identities
from app.services.auth_tokens import (
    AuthTokenError,
    create_access_token,
    format_token_expiry,
    refresh_access_token,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
USERNAME_PATTERN = re.compile(r"[A-Za-z0-9_-]+")


def _token_response(owner: OwnerAccount) -> AuthLoginResponse:
    """Create the standard login response for a username."""

    token, payload = create_access_token(owner.username, owner.auth_revision)
    return AuthLoginResponse(
        username=owner.username,
        accessToken=token,
        expiresAt=format_token_expiry(payload.expires_at),
        tokenType="bearer",
    )


def _validate_username(value: str) -> str:
    username = value.strip()
    if not username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=APP_MESSAGE_USERNAME_REQUIRED,
        )
    if len(username) < 3 or USERNAME_PATTERN.fullmatch(username) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=APP_MESSAGE_USERNAME_INVALID,
        )

    return username


def _validate_new_password(password: str, confirmation: str) -> str:
    if not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=APP_MESSAGE_PASSWORD_REQUIRED,
        )
    if len(password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=APP_MESSAGE_PASSWORD_TOO_SHORT,
        )
    has_letter = re.search(r"[A-Za-z]", password) is not None
    has_digit = re.search(r"[0-9]", password) is not None
    if not has_letter or not has_digit:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=APP_MESSAGE_PASSWORD_COMPLEXITY_REQUIRED,
        )
    if password != confirmation:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=APP_MESSAGE_PASSWORD_CONFIRMATION_MISMATCH,
        )

    return password


def _request_is_loopback(request: Request) -> bool:
    if request.client is None:
        return False

    try:
        return ip_address(request.client.host).is_loopback
    except ValueError:
        return False


@router.get("/setup", response_model=ApiResponse[AuthSetupStatusResponse])
def get_auth_setup(response: Response) -> ApiResponse[AuthSetupStatusResponse]:
    """Report owner setup and GitHub sign-in availability."""

    response.headers["Cache-Control"] = "no-store"
    setup_required = is_setup_required()
    return ok_response(
        AuthSetupStatusResponse(
            setupRequired=setup_required,
            githubLoginAvailable=(
                not setup_required
                and github_app_configured()
                and bool(list_identities())
            ),
        )
    )


@router.post("/setup", response_model=ApiResponse[AuthLoginResponse])
def post_auth_setup(
    request: Request,
    payload: AuthSetupRequest,
) -> ApiResponse[AuthLoginResponse]:
    """Create the owner once from the local machine and sign it in."""

    if not _request_is_loopback(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=APP_MESSAGE_SETUP_LOCAL_ONLY,
        )

    username = _validate_username(payload.username)
    password = _validate_new_password(payload.password, payload.confirm_password)
    try:
        owner = create_owner(username, password)
    except OwnerAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=APP_MESSAGE_SETUP_ALREADY_COMPLETED,
        ) from exc

    return ok_response(_token_response(owner))


@router.post("/login", response_model=ApiResponse[AuthLoginResponse])
def post_auth_login(
    request: AuthLoginRequest,
) -> ApiResponse[AuthLoginResponse]:
    """Validate credentials and issue an access token."""

    username = request.username.strip()
    owner = authenticate_owner(username, request.password)
    if owner is not None:
        return ok_response(_token_response(owner))

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

    try:
        refreshed_token, payload = refresh_access_token(token)
    except AuthTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=APP_MESSAGE_UNAUTHORIZED,
        ) from exc

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
    """Change the stored owner password after verifying the current one."""

    auth_payload = getattr(request.state, "auth_payload", None)
    username = getattr(auth_payload, "subject", "")
    next_password = _validate_new_password(
        payload.new_password,
        payload.confirm_password,
    )
    owner = update_owner_password(
        username,
        payload.current_password,
        next_password,
    )
    if owner is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=APP_MESSAGE_INVALID_CREDENTIALS,
        )

    return ok_response(AuthPasswordUpdateResponse(username=owner.username))
