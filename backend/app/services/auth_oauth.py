import secrets
import time
from hmac import compare_digest
from typing import Any, cast
from urllib.parse import urlencode

import httpx2
from authlib.integrations.base_client import OAuthError
from authlib.integrations.starlette_client import OAuth, StarletteOAuth2App
from fastapi import Request
from starlette.concurrency import run_in_threadpool

from app.schemas.common import (
    APP_MESSAGE_OAUTH_ALREADY_BOUND,
    APP_MESSAGE_OAUTH_ALREADY_CONFIGURED,
    APP_MESSAGE_OAUTH_CANCELLED,
    APP_MESSAGE_OAUTH_INVALID_IDENTITY,
    APP_MESSAGE_OAUTH_INVALID_ORIGIN,
    APP_MESSAGE_OAUTH_INVALID_STATE,
    APP_MESSAGE_OAUTH_NOT_BOUND,
    APP_MESSAGE_OAUTH_NOT_CONFIGURED,
    APP_MESSAGE_OAUTH_OWNER_CHANGED,
    APP_MESSAGE_OAUTH_PROVIDER_ERROR,
    APP_MESSAGE_OAUTH_SETUP_FAILED,
)
from app.services.auth_github_app import (
    GITHUB_API_HEADERS,
    GitHubAppConfig,
    convert_github_manifest,
    get_github_app,
    github_app_configured,
    github_app_manifest,
    save_github_app,
    validate_public_origin,
)
from app.services.auth_identities import (
    OAuthFlowError,
    OAuthIdentity,
    OAuthIntent,
    create_oauth_code,
    get_owner_revision,
    list_identities,
)

OAUTH_SESSION_TTL_SECONDS = 10 * 60


def create_oauth_client(config: GitHubAppConfig) -> StarletteOAuth2App:
    oauth = OAuth()
    oauth.register(
        "github",
        client_id=config.client_id,
        client_secret=config.client_secret,
        authorize_url="https://github.com/login/oauth/authorize",
        access_token_url="https://github.com/login/oauth/access_token",
        api_base_url="https://api.github.com/",
        client_kwargs={
            "code_challenge_method": "S256",
            "token_endpoint_auth_method": "client_secret_post",
            "timeout": 15,
            "headers": GITHUB_API_HEADERS,
        },
    )
    return cast(StarletteOAuth2App, oauth.create_client("github"))


async def _configured_app() -> GitHubAppConfig:
    config = await run_in_threadpool(get_github_app)
    if config is None:
        raise OAuthFlowError(APP_MESSAGE_OAUTH_NOT_CONFIGURED)
    return config


def _new_session(request: Request, public_base_url: str) -> None:
    request.session.clear()
    request.session["browser"] = secrets.token_urlsafe(32)
    request.session["public_base_url"] = public_base_url


def _take_flow(request: Request, kind: str) -> dict[str, Any]:
    flow = request.session.pop("flow", None)
    state = request.query_params.get("state", "")
    if (
        not isinstance(flow, dict)
        or flow.get("kind") != kind
        or not isinstance(flow.get("state"), str)
        or not compare_digest(flow["state"].encode(), state.encode())
        or not isinstance(flow.get("owner_revision"), str)
        or not isinstance(request.session.get("browser"), str)
        or not isinstance(request.session.get("public_base_url"), str)
        or int(time.time()) - flow.get("created_at", 0) >= OAUTH_SESSION_TTL_SECONDS
    ):
        raise OAuthFlowError(APP_MESSAGE_OAUTH_INVALID_STATE)
    return flow


async def _authorize(
    request: Request,
    config: GitHubAppConfig,
    intent: OAuthIntent,
    owner_revision: str,
) -> str:
    client = create_oauth_client(config)
    redirect_uri = f"{config.public_base_url}/api/auth/oauth/github/callback"
    try:
        authorization = await client.create_authorization_url(redirect_uri)
        _new_session(request, config.public_base_url)
        request.session["flow"] = {
            "kind": "oauth",
            "intent": intent,
            "owner_revision": owner_revision,
            "state": authorization["state"],
            "created_at": int(time.time()),
        }
        await client.save_authorize_data(
            request, redirect_uri=redirect_uri, **authorization
        )
    except (OAuthError, httpx2.HTTPError, ValueError) as exc:
        request.session.clear()
        raise OAuthFlowError(APP_MESSAGE_OAUTH_PROVIDER_ERROR) from exc
    return str(authorization["url"])


async def start_oauth(request: Request, intent: OAuthIntent) -> str:
    config = await _configured_app()
    bound = bool(await run_in_threadpool(list_identities))
    if intent == "login" and not bound:
        raise OAuthFlowError(APP_MESSAGE_OAUTH_NOT_BOUND)
    if intent == "bind" and bound:
        raise OAuthFlowError(APP_MESSAGE_OAUTH_ALREADY_BOUND)
    owner_revision = (
        request.state.auth_payload.auth_revision
        if intent == "bind"
        else await run_in_threadpool(get_owner_revision)
    )
    return await _authorize(request, config, intent, owner_revision)


async def _identity(client: StarletteOAuth2App, request: Request) -> OAuthIdentity:
    token = await client.authorize_access_token(request)
    scope = token.get("scope", "")
    if not isinstance(scope, str) or scope.strip():
        raise OAuthFlowError(APP_MESSAGE_OAUTH_INVALID_IDENTITY)
    response = await client.get("user", token=token)
    response.raise_for_status()
    user = response.json()
    if not isinstance(user, dict):
        raise OAuthFlowError(APP_MESSAGE_OAUTH_INVALID_IDENTITY)
    subject = user.get("id")
    label = user.get("login")
    if (
        type(subject) is not int
        or subject <= 0
        or not isinstance(label, str)
        or not label
    ):
        raise OAuthFlowError(APP_MESSAGE_OAUTH_INVALID_IDENTITY)
    return OAuthIdentity(provider="github", subject=str(subject), label=label)


async def finish_oauth(request: Request) -> tuple[str, OAuthIntent]:
    flow = _take_flow(request, "oauth")
    if flow.get("intent") not in {"login", "bind"}:
        raise OAuthFlowError(APP_MESSAGE_OAUTH_INVALID_STATE)
    config = await _configured_app()
    try:
        identity = await _identity(create_oauth_client(config), request)
    except OAuthError as exc:
        message = (
            APP_MESSAGE_OAUTH_CANCELLED
            if exc.error == "access_denied"
            else APP_MESSAGE_OAUTH_PROVIDER_ERROR
        )
        raise OAuthFlowError(message) from exc
    except (httpx2.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise OAuthFlowError(APP_MESSAGE_OAUTH_PROVIDER_ERROR) from exc
    intent = cast(OAuthIntent, flow["intent"])
    code = await run_in_threadpool(
        create_oauth_code,
        identity,
        intent,
        flow["owner_revision"],
        request.session["browser"],
    )
    return code, intent


async def start_github_setup(
    request: Request,
    public_base_url: str,
) -> tuple[str, dict[str, object]]:
    public_base_url = validate_public_origin(public_base_url)
    origin = request.headers.get("origin")
    if origin is not None and origin != public_base_url:
        raise OAuthFlowError(APP_MESSAGE_OAUTH_INVALID_ORIGIN)
    if await run_in_threadpool(github_app_configured):
        raise OAuthFlowError(APP_MESSAGE_OAUTH_ALREADY_CONFIGURED)
    state = secrets.token_urlsafe(32)
    _new_session(request, public_base_url)
    request.session["flow"] = {
        "kind": "setup",
        "owner_revision": request.state.auth_payload.auth_revision,
        "state": state,
        "created_at": int(time.time()),
    }
    return (
        f"https://github.com/settings/apps/new?{urlencode({'state': state})}",
        github_app_manifest(public_base_url),
    )


async def finish_github_setup(request: Request) -> str:
    flow = _take_flow(request, "setup")
    owner_revision = flow["owner_revision"]
    if not compare_digest(await run_in_threadpool(get_owner_revision), owner_revision):
        raise OAuthFlowError(APP_MESSAGE_OAUTH_OWNER_CHANGED)
    if await run_in_threadpool(github_app_configured):
        raise OAuthFlowError(APP_MESSAGE_OAUTH_ALREADY_CONFIGURED)
    error = request.query_params.get("error")
    if error:
        raise OAuthFlowError(
            APP_MESSAGE_OAUTH_CANCELLED
            if error == "access_denied"
            else APP_MESSAGE_OAUTH_SETUP_FAILED
        )
    code = request.query_params.get("code")
    if not code or len(code) > 256:
        raise OAuthFlowError(APP_MESSAGE_OAUTH_SETUP_FAILED)
    config = await convert_github_manifest(code, request.session["public_base_url"])
    await run_in_threadpool(save_github_app, config, owner_revision)
    return await _authorize(request, config, "bind", owner_revision)
