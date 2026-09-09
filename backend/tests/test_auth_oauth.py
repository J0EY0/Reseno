import base64
import hashlib
import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from html.parser import HTMLParser
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import httpx2
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.services import auth_github_app, auth_oauth
from app.services.auth_accounts import (
    connect_auth_database,
    get_auth_db_path,
    update_owner_password,
)
from app.services.auth_github_app import (
    GitHubAppConfig,
    get_github_app,
    github_app_configured,
    save_github_app,
)
from app.services.auth_identities import (
    OAuthFlowError,
    OAuthIdentity,
    consume_oauth_code,
    create_oauth_code,
    delete_identity,
    get_owner_revision,
    list_identities,
)
from app.services.auth_oauth_callback import oauth_callback_response
from app.services.auth_tokens import decode_access_token

PUBLIC_ORIGIN = "http://127.0.0.1:5173"


def test_oauth_import_has_no_deprecated_httpx_warning() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import warnings; "
            "from authlib.deprecate import AuthlibDeprecationWarning; "
            "warnings.simplefilter('error', AuthlibDeprecationWarning); "
            "from app.services import auth_oauth",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


class GitHub:
    def __init__(self) -> None:
        self.authorization: dict[str, list[str]] = {}
        self.origin = PUBLIC_ORIGIN
        self.scope: str | None = ""
        self.user_id = 42
        self.requests: list[httpx2.Request] = []
        self.used_codes: set[str] = set()
        self.manifest_overrides: dict[str, Any] = {}
        self.fail_conversion = False
        self.fail_user = False
        self.change_owner_during_conversion = False

    def request(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if request.url.path.startswith("/app-manifests/"):
            assert request.method == "POST"
            assert "Authorization" not in request.headers
            if self.fail_conversion:
                raise httpx2.ConnectError("network unavailable", request=request)
            if self.change_owner_during_conversion:
                update_owner_password("admin", "TestPassword2026", "NewPassword2026")
            return httpx2.Response(
                201,
                json={
                    "client_id": "github-app-client",
                    "client_secret": "github-app-secret",
                    "external_url": self.origin,
                    "permissions": {},
                    "events": [],
                    "pem": "unused-private-key",
                    "webhook_secret": "unused-webhook-secret",
                    **self.manifest_overrides,
                },
            )
        if request.url.path == "/user":
            assert request.headers["Authorization"] == "Bearer github-user-token"
            if self.fail_user:
                return httpx2.Response(503, json={"message": "provider unavailable"})
            return httpx2.Response(200, json={"id": self.user_id, "login": "octocat"})
        if request.url.path == "/login/oauth/access_token":
            assert request.headers["Accept"] == "application/json"
            body = parse_qs(request.content.decode())
            code = body["code"][0]
            if code in self.used_codes:
                return httpx2.Response(400, json={"error": "invalid_grant"})
            self.used_codes.add(code)
            assert body["redirect_uri"] == self.authorization["redirect_uri"]
            challenge = (
                base64.urlsafe_b64encode(
                    hashlib.sha256(body["code_verifier"][0].encode()).digest()
                )
                .rstrip(b"=")
                .decode()
            )
            assert challenge == self.authorization["code_challenge"][0]
            assert body["client_id"] == ["github-app-client"]
            assert body["client_secret"] == ["github-app-secret"]
            token: dict[str, Any] = {
                "access_token": "github-user-token",
                "refresh_token": "unused-refresh-token",
                "token_type": "bearer",
            }
            if self.scope is not None:
                token["scope"] = self.scope
            return httpx2.Response(200, json=token)
        raise AssertionError(
            f"Unexpected GitHub request: {request.method} {request.url}"
        )


@pytest.fixture
def github(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> GitHub:
    remote = GitHub()
    create_oauth_client = auth_oauth.create_oauth_client
    async_client = httpx2.AsyncClient

    def oauth_client(config: GitHubAppConfig):
        result = create_oauth_client(config)
        result.client_kwargs["transport"] = httpx2.MockTransport(remote.request)
        return result

    def manifest_client(**kwargs: Any):
        return async_client(transport=httpx2.MockTransport(remote.request), **kwargs)

    monkeypatch.setattr(auth_oauth, "create_oauth_client", oauth_client)
    monkeypatch.setattr(
        auth_github_app,
        "httpx2",
        SimpleNamespace(
            AsyncClient=manifest_client,
            HTTPError=httpx2.HTTPError,
        ),
    )
    return remote


@pytest.fixture
def configured(client: TestClient, github: GitHub) -> GitHub:
    save_github_app(
        GitHubAppConfig("github-app-client", "github-app-secret", PUBLIC_ORIGIN),
        get_owner_revision(),
    )
    return github


def assert_cookie(response: httpx.Response, secure: bool = False) -> None:
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "max-age=600" in cookie
    assert "path=/api/auth/oauth" in cookie
    assert ("; secure" in cookie) == secure


def authorization(github: GitHub, url: str, intent: str = "bind") -> None:
    github.authorization = parse_qs(urlsplit(url).query, keep_blank_values=True)
    assert urlsplit(url).netloc == "github.com"
    if intent == "bind":
        assert github.authorization["prompt"] == ["select_account"]
    else:
        assert "prompt" not in github.authorization
    assert github.authorization["state"][0]
    assert len(github.authorization["code_challenge"][0]) == 43
    assert github.authorization["code_challenge_method"] == ["S256"]
    assert github.authorization["redirect_uri"] == [
        f"{github.origin}/api/auth/oauth/github/callback"
    ]
    assert "scope" not in github.authorization


def start(client: TestClient, github: GitHub, intent: str = "bind") -> None:
    response = client.post(f"/api/auth/oauth/github/{intent}")
    assert response.status_code == 200, response.text
    authorization(github, response.json()["data"]["authorizationUrl"], intent)
    assert_cookie(response, secure=github.origin.startswith("https://"))


def bridge_data(response: httpx.Response) -> dict[str, Any]:
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "location" not in response.headers
    match = re.search(r"const config = (.*);", response.text)
    assert match is not None
    data = json.loads(match[1])
    assert data["result"]["type"] == "reseno:oauth:result"
    assert set(data["result"]) in ({"type", "code", "intent"}, {"type", "error"})
    return data


def bridge_result(response: httpx.Response) -> dict[str, list[str]]:
    result = bridge_data(response)["result"]
    for secret in (
        "github-app-secret",
        "github-user-token",
        "unused-refresh-token",
        "private-provider-details",
    ):
        assert secret not in response.text
    return {key: [value] for key, value in result.items() if key != "type"}


def test_callback_bridge_serializes_script_data_without_html_injection() -> None:
    class Document(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.tags: list[tuple[str, dict[str, str | None]]] = []

        def handle_starttag(
            self, tag: str, attrs: list[tuple[str, str | None]]
        ) -> None:
            self.tags.append((tag, dict(attrs)))

    code = '</script><img src=x onerror="alert(1)">&\u2028\u2029'
    response = oauth_callback_response(PUBLIC_ORIGIN, {"code": code, "intent": "bind"})
    http_response = httpx.Response(
        response.status_code, headers=response.headers, content=response.body
    )
    assert bridge_data(http_response) == {
        "origin": PUBLIC_ORIGIN,
        "result": {
            "type": "reseno:oauth:result",
            "code": code,
            "intent": "bind",
        },
        "errorUrl": f"{PUBLIC_ORIGIN}/auth/callback#error=OAUTH_INVALID_STATE",
    }
    document = Document()
    document.feed(http_response.text)
    scripts = [attrs for tag, attrs in document.tags if tag == "script"]
    styles = [attrs for tag, attrs in document.tags if tag == "style"]
    assert len(scripts) == len(styles) == 1
    assert "src" not in scripts[0]
    assert not any(tag in {"img", "iframe", "link"} for tag, _ in document.tags)
    nonce = scripts[0]["nonce"]
    assert nonce and styles[0]["nonce"] == nonce
    policy = response.headers["Content-Security-Policy"]
    assert set(policy.split("; ")) == {
        "default-src 'none'",
        f"script-src 'nonce-{nonce}'",
        f"style-src 'nonce-{nonce}'",
        "base-uri 'none'",
        "frame-ancestors 'none'",
        "form-action 'none'",
    }


def test_callback_bridge_nonce_is_unique_per_response() -> None:
    responses = [
        oauth_callback_response(PUBLIC_ORIGIN, {"error": "OAUTH_CANCELLED"})
        for _ in range(2)
    ]
    assert (
        responses[0].headers["Content-Security-Policy"]
        != responses[1].headers["Content-Security-Policy"]
    )


def callback(
    client: TestClient,
    github: GitHub,
    *,
    expected_intent: str = "bind",
    **query: str,
) -> dict[str, list[str]]:
    query = {
        "state": github.authorization["state"][0],
        "code": f"provider-code-{len(github.used_codes)}",
        **query,
    }
    response = client.get(
        f"/api/auth/oauth/github/callback?{urlencode(query)}",
        follow_redirects=False,
    )
    if expected_intent == "bind":
        return bridge_result(response)
    assert response.status_code == 303
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    location = urlsplit(response.headers["Location"])
    assert location.path == "/login"
    assert not location.query
    assert location.netloc in {"", urlsplit(github.origin).netloc}
    result = parse_qs(location.fragment)
    assert set(result) in ({"oauth_code"}, {"oauth_error"})
    assert "access_token" not in response.headers["Location"]
    return result


def bind(client: TestClient, github: GitHub) -> None:
    start(client, github)
    result = callback(client, github)
    assert result["intent"] == ["bind"]
    code = result["code"][0]
    assert list_identities() == []
    response = client.post("/api/auth/oauth/complete", json={"code": code})
    assert response.status_code == 200, response.text
    assert response.json()["data"] == {
        "provider": "github",
        "intent": "bind",
        "auth": None,
    }


def setup(client: TestClient, github: GitHub) -> str:
    response = client.post(
        "/api/auth/oauth/github/setup",
        json={"publicBaseUrl": github.origin},
        headers={"Origin": github.origin},
    )
    assert response.status_code == 200, response.text
    assert_cookie(response, secure=github.origin.startswith("https://"))
    data = response.json()["data"]
    manifest = data["manifest"]
    assert manifest["public"] is False
    assert manifest["default_permissions"] == {}
    assert manifest["default_events"] == []
    assert manifest["request_oauth_on_install"] is False
    assert "hook_attributes" not in manifest
    assert manifest["name"].startswith("Reseno-")
    assert manifest["url"] == github.origin
    assert (
        manifest["redirect_url"]
        == f"{github.origin}/api/auth/oauth/github/setup/callback"
    )
    assert manifest["callback_urls"] == [
        f"{github.origin}/api/auth/oauth/github/callback"
    ]
    registration = urlsplit(data["registrationUrl"])
    assert registration.scheme == "https"
    assert registration.netloc == "github.com"
    assert registration.path == "/settings/apps/new"
    return parse_qs(registration.query)["state"][0]


def setup_callback(client: TestClient, state: str, **query: str) -> httpx.Response:
    response = client.get(
        "/api/auth/oauth/github/setup/callback",
        params={"state": state, "code": "manifest-code", **query},
        follow_redirects=False,
    )
    assert response.status_code in {200, 303}
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    return response


def test_manifest_setup_automatically_binds_and_persists_across_app_restarts(
    client: TestClient,
    github: GitHub,
) -> None:
    from app.main import create_app

    state = setup(client, github)
    response = setup_callback(client, state)
    authorization(github, response.headers["Location"])
    assert list_identities() == []
    assert github_app_configured()
    callback_result = callback(client, github)
    assert callback_result["intent"] == ["bind"]
    code = callback_result["code"][0]
    assert client.post("/api/auth/oauth/complete", json={"code": code}).json()[
        "data"
    ] == {"provider": "github", "intent": "bind", "auth": None}
    client.__exit__(None, None, None)
    get_settings.cache_clear()
    with TestClient(create_app()) as restarted:
        start(restarted, github, "login")
        callback_result = callback(restarted, github, expected_intent="login")
        code = callback_result["oauth_code"][0]
        result = restarted.post("/api/auth/oauth/complete", json={"code": code})
        assert result.status_code == 200, result.text
        claims = decode_access_token(result.json()["data"]["auth"]["accessToken"])
        assert claims.subject == "admin"
        assert claims.expires_at - claims.issued_at == 36 * 60 * 60
    raw_database = get_auth_db_path().read_bytes()
    for secret in [
        b"github-app-secret",
        b"unused-private-key",
        b"unused-webhook-secret",
        b"github-user-token",
        b"unused-refresh-token",
    ]:
        assert secret not in raw_database
    with closing(connect_auth_database()) as conn:
        row = conn.execute("SELECT * FROM auth_github_app").fetchone()
        assert set(row.keys()) == {
            "id",
            "client_id",
            "client_secret",
            "public_base_url",
        }
        assert row["client_secret"] != "github-app-secret"
        assert conn.execute("SELECT COUNT(*) FROM auth_owner").fetchone()[0] == 1
    assert get_github_app().client_secret == "github-app-secret"


def test_setup_cancel_during_binding_keeps_configuration(
    client: TestClient, github: GitHub
) -> None:
    state = setup(client, github)
    response = setup_callback(client, state)
    authorization(github, response.headers["Location"])
    assert callback(client, github, error="access_denied") == {
        "error": ["OAUTH_CANCELLED"]
    }
    assert github_app_configured()
    assert list_identities() == []
    bind(client, github)


@pytest.mark.parametrize(
    "problem",
    ["state", "unicode_state", "cookie", "expired", "owner", "cancel", "network"],
)
def test_setup_rejects_untrusted_or_failed_callbacks(
    client: TestClient,
    github: GitHub,
    monkeypatch: pytest.MonkeyPatch,
    problem: str,
) -> None:
    state = setup(client, github)
    expected = "OAUTH_INVALID_STATE"
    query: dict[str, str] = {}
    if problem == "state":
        state = "attacker-state"
    if problem == "unicode_state":
        state = "你好"
    if problem == "cookie":
        client.cookies.clear()
    if problem == "expired":
        now = time.time()
        monkeypatch.setattr(auth_oauth.time, "time", lambda: now + 600)
    if problem == "owner":
        update_owner_password("admin", "TestPassword2026", "NewPassword2026")
        expected = "OAUTH_OWNER_CHANGED"
    if problem == "cancel":
        query["error"] = "access_denied"
        query["error_description"] = "private-provider-details"
        expected = "OAUTH_CANCELLED"
    if problem == "network":
        github.fail_conversion = True
        expected = "OAUTH_SETUP_FAILED"
    response = setup_callback(client, state, **query)
    assert bridge_result(response) == {"error": [expected]}
    data = bridge_data(response)
    if problem in {"cookie", "expired"}:
        assert data["origin"] == ""
        assert data["errorUrl"] == "/auth/callback#error=OAUTH_INVALID_STATE"
    else:
        assert data["origin"] == github.origin
    assert not github_app_configured()
    assert list_identities() == []
    if problem != "network":
        assert not github.requests


@pytest.mark.parametrize(
    "overrides",
    [
        {"permissions": {"contents": "read"}},
        {"permissions": {"emails": "read"}},
        {"permissions": {"metadata": "write"}},
        {"events": ["push"]},
        {"external_url": "https://attacker.example"},
        {"external_url": []},
        {"client_secret": ""},
        {"client_id": None},
    ],
)
def test_setup_validates_converted_manifest_before_persisting(
    client: TestClient,
    github: GitHub,
    overrides: dict[str, Any],
) -> None:
    state = setup(client, github)
    github.manifest_overrides = overrides
    response = setup_callback(client, state)
    assert bridge_result(response) == {"error": ["OAUTH_SETUP_FAILED"]}
    assert not github_app_configured()


def test_setup_accepts_github_automatic_metadata_permission(
    client: TestClient, github: GitHub
) -> None:
    state = setup(client, github)
    github.manifest_overrides["permissions"] = {"metadata": "read"}
    assert (
        urlsplit(setup_callback(client, state).headers["Location"]).netloc
        == "github.com"
    )
    assert github_app_configured()


def test_setup_rechecks_owner_in_configuration_transaction(
    client: TestClient, github: GitHub
) -> None:
    state = setup(client, github)
    github.change_owner_during_conversion = True
    response = setup_callback(client, state)
    assert bridge_result(response) == {"error": ["OAUTH_OWNER_CHANGED"]}
    assert not github_app_configured()


def test_setup_replay_cannot_overwrite_saved_configuration(
    client: TestClient, github: GitHub
) -> None:
    state = setup(client, github)
    cookies = dict(client.cookies)
    setup_callback(client, state)
    original = get_github_app()
    request_count = len(github.requests)
    client.cookies.update(cookies)
    response = setup_callback(client, state)
    assert bridge_result(response) == {"error": ["OAUTH_ALREADY_CONFIGURED"]}
    assert get_github_app() == original
    assert len(github.requests) == request_count
    assert (
        client.post(
            "/api/auth/oauth/github/setup",
            json={
                "publicBaseUrl": PUBLIC_ORIGIN,
            },
        ).json()["message"]
        == "OAUTH_ALREADY_CONFIGURED"
    )


def test_concurrent_setup_cannot_replace_first_configuration(
    client: TestClient,
) -> None:
    revision = get_owner_revision()

    def configure(client_id: str) -> str:
        try:
            save_github_app(
                GitHubAppConfig(client_id, "secret", PUBLIC_ORIGIN), revision
            )
            return "success"
        except OAuthFlowError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(configure, ("first", "second")))
    assert sorted(result) == ["OAUTH_ALREADY_CONFIGURED", "success"]


@pytest.mark.parametrize(
    "origin",
    [
        "http://resume.example.com",
        "http://192.168.1.10",
        "https://@example.com",
        "https://owner:secret@example.com",
        "https://example.com/",
        "https://example.com/path",
        "https://example.com?query=value",
        "https://example.com?",
        "https://example.com#fragment",
        "https://example.com#",
        "https://example.com:",
        "https://example.com:99999",
        "javascript:alert(1)",
        "\x00https://example.com",
        "https://exam\x7fple.com",
        "https://example.com\\evil",
        " https://example.com",
    ],
)
def test_setup_rejects_unsafe_origin(client: TestClient, origin: str) -> None:
    response = client.post(
        "/api/auth/oauth/github/setup", json={"publicBaseUrl": origin}
    )
    assert response.status_code == 400
    assert response.json()["message"] == "OAUTH_INVALID_ORIGIN"
    assert not github_app_configured()


def test_setup_requires_matching_origin_header_and_ignores_host(
    client: TestClient,
) -> None:
    result = client.post(
        "/api/auth/oauth/github/setup",
        json={"publicBaseUrl": PUBLIC_ORIGIN},
        headers={"Origin": "https://attacker.example", "Host": "ignored.example"},
    )
    assert result.json()["message"] == "OAUTH_INVALID_ORIGIN"
    accepted = client.post(
        "/api/auth/oauth/github/setup",
        json={"publicBaseUrl": PUBLIC_ORIGIN},
        headers={"Origin": PUBLIC_ORIGIN, "Host": "ignored.example"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["data"]["manifest"]["url"] == PUBLIC_ORIGIN


def test_secure_cookie_follows_each_validated_origin_without_shared_flags(
    client: TestClient,
    github: GitHub,
) -> None:
    github.origin = "https://resume.example.com"
    setup(client, github)
    github.origin = PUBLIC_ORIGIN
    setup(client, github)
    github.origin = "https://resume.example.com"
    setup(client, github)


def test_public_paths_only_allow_authentication_not_setup_or_binding(
    unauthenticated_client: TestClient,
) -> None:
    assert unauthenticated_client.get("/api/auth/setup").json()["data"] == {
        "setupRequired": False,
        "githubLoginAvailable": False,
    }
    for method, path in [
        ("GET", "/api/auth/oauth/identities"),
        ("POST", "/api/auth/oauth/github/bind"),
        ("POST", "/api/auth/oauth/github/setup"),
        ("DELETE", "/api/auth/oauth/github/binding"),
    ]:
        assert unauthenticated_client.request(method, path).status_code == 401
    response = unauthenticated_client.post("/api/auth/oauth/github/login")
    assert response.json()["message"] == "OAUTH_NOT_CONFIGURED"


def test_google_is_not_a_supported_provider(client: TestClient) -> None:
    assert client.post("/api/auth/oauth/google/bind").status_code == 422
    providers = client.get("/api/auth/oauth/identities").json()["data"]["providers"]
    assert providers == [{"provider": "github", "configured": False}]


def test_unbound_github_cannot_log_in(client: TestClient, configured: GitHub) -> None:
    assert client.get("/api/auth/setup").json()["data"] == {
        "setupRequired": False,
        "githubLoginAvailable": False,
    }
    response = client.post("/api/auth/oauth/github/login")
    assert response.json()["message"] == "OAUTH_NOT_BOUND"
    assert not configured.requests


@pytest.mark.parametrize("scope", ["", None])
def test_bind_and_login_validate_stable_identity_and_one_use_exchange(
    client: TestClient,
    configured: GitHub,
    scope: str | None,
) -> None:
    configured.scope = scope
    bind(client, configured)
    listed = client.get("/api/auth/oauth/identities").json()["data"]
    assert listed["identities"][0]["label"] == "octocat"
    assert listed["identities"][0]["createdAt"].endswith("Z")
    client.headers.pop("Authorization")
    assert client.get("/api/auth/setup").json()["data"] == {
        "setupRequired": False,
        "githubLoginAvailable": True,
    }
    start(client, configured, "login")
    callback_result = callback(client, configured, expected_intent="login")
    code = callback_result["oauth_code"][0]
    result = client.post("/api/auth/oauth/complete", json={"code": code})
    assert result.status_code == 200
    claims = decode_access_token(result.json()["data"]["auth"]["accessToken"])
    assert claims.subject == "admin"
    assert claims.expires_at - claims.issued_at == 36 * 60 * 60
    assert (
        client.post("/api/auth/oauth/complete", json={"code": code}).status_code == 400
    )


@pytest.mark.parametrize(
    "problem", ["state", "unicode_state", "cookie", "cancel", "expired"]
)
def test_oauth_callback_rejects_invalid_browser_flow(
    client: TestClient,
    configured: GitHub,
    monkeypatch: pytest.MonkeyPatch,
    problem: str,
) -> None:
    start(client, configured)
    query: dict[str, str] = {}
    if problem == "state":
        query["state"] = "attacker-state"
    if problem == "unicode_state":
        query["state"] = "你好"
    if problem == "cookie":
        client.cookies.clear()
    if problem == "cancel":
        query["error"] = "access_denied"
    if problem == "expired":
        now = time.time()
        monkeypatch.setattr(auth_oauth.time, "time", lambda: now + 600)
    expected = "OAUTH_CANCELLED" if problem == "cancel" else "OAUTH_INVALID_STATE"
    expected_intent = "login" if problem in {"cookie", "expired"} else "bind"
    error_key = "oauth_error" if expected_intent == "login" else "error"
    assert callback(client, configured, expected_intent=expected_intent, **query) == {
        error_key: [expected]
    }
    assert list_identities() == []


@pytest.mark.parametrize("intent", ["login", "bind"])
@pytest.mark.parametrize("problem", ["cancel", "state"])
def test_callback_errors_follow_session_intent_not_query_parameters(
    client: TestClient,
    configured: GitHub,
    intent: str,
    problem: str,
) -> None:
    if intent == "login":
        bind(client, configured)
    start(client, configured, intent)
    query = {"intent": "bind" if intent == "login" else "login"}
    if problem == "cancel":
        query["error"] = "access_denied"
        query["error_description"] = "private-provider-details"
    else:
        query["state"] = "attacker-state"
    expected = "OAUTH_CANCELLED" if problem == "cancel" else "OAUTH_INVALID_STATE"
    error_key = "oauth_error" if intent == "login" else "error"
    assert callback(client, configured, expected_intent=intent, **query) == {
        error_key: [expected]
    }


def test_callback_without_session_returns_relative_login_error(
    client: TestClient,
) -> None:
    client.cookies.clear()
    response = client.get(
        "/api/auth/oauth/github/callback",
        params={"state": "untrusted", "code": "untrusted", "intent": "bind"},
        headers={"Host": "attacker.example"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["Location"] == "/login#oauth_error=OAUTH_INVALID_STATE"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_oauth_rejects_broad_scopes_and_provider_network_errors(
    client: TestClient,
    configured: GitHub,
) -> None:
    start(client, configured)
    configured.scope = "repo, user"
    assert callback(client, configured) == {"error": ["OAUTH_INVALID_IDENTITY"]}
    configured.scope = ""
    configured.fail_user = True
    start(client, configured)
    assert callback(client, configured) == {"error": ["OAUTH_PROVIDER_ERROR"]}


def test_login_matches_github_id_not_display_name(
    client: TestClient, configured: GitHub
) -> None:
    bind(client, configured)
    start(client, configured, "login")
    configured.user_id = 99
    assert callback(client, configured, expected_intent="login") == {
        "oauth_error": ["OAUTH_NOT_BOUND"]
    }


def test_exchange_is_bound_to_browser_cookie(
    client: TestClient, configured: GitHub
) -> None:
    start(client, configured)
    code = callback(client, configured)["code"][0]
    cookies = dict(client.cookies)
    client.cookies.clear()
    assert (
        client.post("/api/auth/oauth/complete", json={"code": code}).status_code == 400
    )
    assert list_identities() == []
    client.cookies.update(cookies)
    assert (
        client.post("/api/auth/oauth/complete", json={"code": code}).status_code == 200
    )


@pytest.mark.parametrize("change", ["password", "expiry"])
def test_bind_exchange_rechecks_revision_and_expiry(
    client: TestClient,
    configured: GitHub,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    from app.services import auth_identities

    start(client, configured)
    code = callback(client, configured)["code"][0]
    if change == "password":
        update_owner_password("admin", "TestPassword2026", "NewPassword2026")
    else:
        now = time.time()
        monkeypatch.setattr(auth_identities.time, "time", lambda: now + 60)
    result = client.post("/api/auth/oauth/complete", json={"code": code})
    assert result.json()["message"] == (
        "OAUTH_OWNER_CHANGED" if change == "password" else "OAUTH_EXCHANGE_EXPIRED"
    )
    assert list_identities() == []


def test_unbinding_invalidates_pending_login_and_preserves_password_login(
    client: TestClient,
    configured: GitHub,
) -> None:
    bind(client, configured)
    start(client, configured, "login")
    code = callback(client, configured, expected_intent="login")["oauth_code"][0]
    assert client.delete("/api/auth/oauth/github/binding").json()["data"] == {
        "deleted": True
    }
    assert (
        client.post("/api/auth/oauth/complete", json={"code": code}).status_code == 400
    )
    assert list_identities() == []
    assert github_app_configured()
    assert client.get("/api/auth/setup").json()["data"] == {
        "setupRequired": False,
        "githubLoginAvailable": False,
    }
    assert (
        client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "TestPassword2026"},
        ).status_code
        == 200
    )


def test_exchange_and_binding_are_atomic_under_concurrency(client: TestClient) -> None:
    code = create_oauth_code(
        OAuthIdentity("github", "42", "octocat"),
        "bind",
        get_owner_revision(),
        "browser",
    )

    def exchange() -> str:
        try:
            consume_oauth_code(code, "browser")
            return "success"
        except OAuthFlowError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: exchange(), range(2)))
    assert sorted(results) == ["OAUTH_EXCHANGE_EXPIRED", "success"]
    assert len(list_identities()) == 1


def test_two_binding_flows_cannot_replace_each_other(client: TestClient) -> None:
    codes = [
        create_oauth_code(
            OAuthIdentity("github", subject, subject),
            "bind",
            get_owner_revision(),
            "browser",
        )
        for subject in ("42", "99")
    ]
    consume_oauth_code(codes[0], "browser")
    with pytest.raises(OAuthFlowError, match="OAUTH_ALREADY_BOUND"):
        consume_oauth_code(codes[1], "browser")
    assert list_identities()[0].subject == "42"
    delete_identity("github")
    with pytest.raises(OAuthFlowError, match="OAUTH_EXCHANGE_EXPIRED"):
        consume_oauth_code(codes[1], "browser")


def test_https_setup_and_binding_keep_secure_cookies_through_completion(
    client: TestClient,
    github: GitHub,
) -> None:
    github.origin = "https://resume.example.com"
    client.base_url = httpx.URL(github.origin)
    state = setup(client, github)
    result = setup_callback(client, state)
    assert_cookie(result, secure=True)
    authorization(github, result.headers["Location"])
    code = callback(client, github)["code"][0]
    completed = client.post("/api/auth/oauth/complete", json={"code": code})
    assert completed.status_code == 200
    assert "; secure" in completed.headers["set-cookie"].lower()


def test_oauth_provider_code_cannot_be_replayed(
    client: TestClient, configured: GitHub
) -> None:
    start(client, configured)
    original_cookie = dict(client.cookies)
    assert "code" in callback(client, configured, code="one-use-code")
    client.cookies.update(original_cookie)
    assert callback(client, configured, code="one-use-code") == {
        "error": ["OAUTH_PROVIDER_ERROR"]
    }
