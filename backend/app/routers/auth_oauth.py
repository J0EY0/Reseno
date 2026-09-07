from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from app.schemas.auth import (
    AuthLoginResponse,
    OAuthCompleteRequest,
    OAuthCompleteResponse,
    OAuthDeleteResponse,
    OAuthIdentitiesResponse,
    OAuthIdentityResponse,
    OAuthProviderConfiguration,
    OAuthSetupRequest,
    OAuthSetupResponse,
    OAuthStartResponse,
)
from app.schemas.common import (
    APP_MESSAGE_OAUTH_EXCHANGE_EXPIRED,
    ApiResponse,
    ok_response,
)
from app.services.auth_github_app import github_app_configured
from app.services.auth_identities import (
    OAUTH_PROVIDERS,
    OAuthFlowError,
    OAuthProvider,
    consume_oauth_code,
    delete_identity,
    list_identities,
)
from app.services.auth_oauth import (
    finish_github_setup,
    finish_oauth,
    start_github_setup,
    start_oauth,
)
from app.services.auth_oauth_callback import oauth_callback_response
from app.services.auth_tokens import create_access_token, format_token_expiry

router = APIRouter(prefix="/api/auth/oauth", tags=["auth"])


def _callback_origin(request: Request) -> str:
    origin = request.session.get("public_base_url", "")
    request.state.oauth_public_base_url = origin
    return str(origin)


@router.get("/identities", response_model=ApiResponse[OAuthIdentitiesResponse])
def get_oauth_identities(response: Response) -> ApiResponse[OAuthIdentitiesResponse]:
    response.headers["Cache-Control"] = "no-store"
    configured = github_app_configured()
    return ok_response(
        OAuthIdentitiesResponse(
            identities=[
                OAuthIdentityResponse(
                    provider=identity.provider,
                    label=identity.label,
                    createdAt=identity.created_at,
                )
                for identity in list_identities()
            ],
            providers=[
                OAuthProviderConfiguration(
                    provider=provider,
                    configured=configured,
                )
                for provider in OAUTH_PROVIDERS
            ],
        )
    )


@router.post("/{provider}/login", response_model=ApiResponse[OAuthStartResponse])
async def post_oauth_login(
    request: Request,
    response: Response,
    provider: OAuthProvider,
) -> ApiResponse[OAuthStartResponse]:
    response.headers["Cache-Control"] = "no-store"
    try:
        url = await start_oauth(request, "login")
    except OAuthFlowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok_response(OAuthStartResponse(authorizationUrl=url))


@router.post("/{provider}/bind", response_model=ApiResponse[OAuthStartResponse])
async def post_oauth_bind(
    request: Request,
    response: Response,
    provider: OAuthProvider,
) -> ApiResponse[OAuthStartResponse]:
    response.headers["Cache-Control"] = "no-store"
    try:
        url = await start_oauth(request, "bind")
    except OAuthFlowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok_response(OAuthStartResponse(authorizationUrl=url))


@router.get("/{provider}/callback")
async def get_oauth_callback(request: Request, provider: OAuthProvider) -> Response:
    origin = _callback_origin(request)
    flow = request.session.get("flow")
    is_binding = (
        isinstance(flow, dict)
        and flow.get("kind") == "oauth"
        and flow.get("intent") == "bind"
    )
    try:
        code, intent = await finish_oauth(request)
    except OAuthFlowError as exc:
        request.session.clear()
        if is_binding:
            return oauth_callback_response(origin, {"error": str(exc)})
        fragment = urlencode({"oauth_error": str(exc)})
    else:
        if intent == "bind":
            return oauth_callback_response(origin, {"code": code, "intent": intent})
        fragment = urlencode({"oauth_code": code})
    return RedirectResponse(
        f"{origin}/login#{fragment}",
        status_code=303,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


@router.post("/complete", response_model=ApiResponse[OAuthCompleteResponse])
def post_oauth_complete(
    request: Request,
    response: Response,
    payload: OAuthCompleteRequest,
) -> ApiResponse[OAuthCompleteResponse]:
    response.headers["Cache-Control"] = "no-store"
    _callback_origin(request)
    browser = request.session.get("browser")
    if not isinstance(browser, str):
        raise HTTPException(status_code=400, detail=APP_MESSAGE_OAUTH_EXCHANGE_EXPIRED)
    try:
        provider, intent, owner = consume_oauth_code(payload.code, browser)
    except OAuthFlowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        request.session.clear()
    auth = None
    if intent == "login":
        token, claims = create_access_token(owner.username, owner.auth_revision)
        auth = AuthLoginResponse(
            username=owner.username,
            accessToken=token,
            expiresAt=format_token_expiry(claims.expires_at),
        )
    return ok_response(
        OAuthCompleteResponse(provider=provider, intent=intent, auth=auth)
    )


@router.delete("/{provider}/binding", response_model=ApiResponse[OAuthDeleteResponse])
def delete_oauth_binding(
    provider: OAuthProvider,
    response: Response,
) -> ApiResponse[OAuthDeleteResponse]:
    response.headers["Cache-Control"] = "no-store"
    delete_identity(provider)
    return ok_response(OAuthDeleteResponse())


@router.post("/github/setup", response_model=ApiResponse[OAuthSetupResponse])
async def post_github_setup(
    request: Request,
    response: Response,
    payload: OAuthSetupRequest,
) -> ApiResponse[OAuthSetupResponse]:
    response.headers["Cache-Control"] = "no-store"
    try:
        registration_url, manifest = await start_github_setup(
            request, payload.public_base_url
        )
    except OAuthFlowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok_response(
        OAuthSetupResponse(registrationUrl=registration_url, manifest=manifest)
    )


@router.get("/github/setup/callback")
async def get_github_setup_callback(request: Request) -> Response:
    origin = _callback_origin(request)
    try:
        destination = await finish_github_setup(request)
    except OAuthFlowError as exc:
        request.session.clear()
        return oauth_callback_response(origin, {"error": str(exc)})
    return RedirectResponse(
        destination,
        status_code=303,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )
