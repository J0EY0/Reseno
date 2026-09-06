import os
import secrets
from contextlib import closing
from dataclasses import dataclass, field
from hmac import compare_digest
from ipaddress import ip_address
from urllib.parse import quote, urlsplit

import httpx2
from cryptography.fernet import Fernet

from app.config import MASTER_KEY_ENV_NAME, get_settings
from app.schemas.common import (
    APP_MESSAGE_OAUTH_ALREADY_CONFIGURED,
    APP_MESSAGE_OAUTH_INVALID_ORIGIN,
    APP_MESSAGE_OAUTH_OWNER_CHANGED,
    APP_MESSAGE_OAUTH_SETUP_FAILED,
)
from app.services.auth_accounts import connect_auth_database
from app.services.auth_identities import OAuthFlowError

GITHUB_API_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2026-03-10",
}


@dataclass(frozen=True)
class GitHubAppConfig:
    client_id: str
    client_secret: str = field(repr=False)
    public_base_url: str


def validate_public_origin(value: str) -> str:
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
        loopback = hostname == "localhost"
        if hostname and not loopback:
            try:
                loopback = ip_address(hostname).is_loopback
            except ValueError:
                loopback = False
        valid = (
            value == value.strip()
            and not any(
                ord(character) < 33 or ord(character) == 127 for character in value
            )
            and "\\" not in value
            and parsed.scheme in {"http", "https"}
            and value == f"{parsed.scheme}://{parsed.netloc}"
            and not parsed.netloc.endswith(":")
            and bool(hostname)
            and parsed.username is None
            and parsed.password is None
            and not parsed.path
            and not parsed.query
            and not parsed.fragment
            and (port is None or 0 < port <= 65535)
            and (parsed.scheme == "https" or loopback)
        )
    except ValueError:
        valid = False
    if not valid:
        raise OAuthFlowError(APP_MESSAGE_OAUTH_INVALID_ORIGIN)
    return value


def _cipher() -> Fernet:
    get_settings()
    return Fernet(os.environ[MASTER_KEY_ENV_NAME].encode())


def github_app_configured() -> bool:
    with closing(connect_auth_database()) as conn:
        return (
            conn.execute("SELECT 1 FROM auth_github_app WHERE id = 1").fetchone()
            is not None
        )


def get_github_app() -> GitHubAppConfig | None:
    with closing(connect_auth_database()) as conn:
        row = conn.execute("SELECT * FROM auth_github_app WHERE id = 1").fetchone()
    if row is None:
        return None
    return GitHubAppConfig(
        client_id=row["client_id"],
        client_secret=_cipher().decrypt(row["client_secret"].encode()).decode(),
        public_base_url=row["public_base_url"],
    )


def save_github_app(config: GitHubAppConfig, owner_revision: str) -> None:
    encrypted_secret = _cipher().encrypt(config.client_secret.encode()).decode()
    with closing(connect_auth_database()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        owner = conn.execute(
            "SELECT auth_revision FROM auth_owner WHERE id = 1"
        ).fetchone()
        if owner is None or not compare_digest(owner["auth_revision"], owner_revision):
            raise OAuthFlowError(APP_MESSAGE_OAUTH_OWNER_CHANGED)
        if conn.execute("SELECT 1 FROM auth_github_app WHERE id = 1").fetchone():
            raise OAuthFlowError(APP_MESSAGE_OAUTH_ALREADY_CONFIGURED)
        conn.execute(
            """
            INSERT INTO auth_github_app (id, client_id, client_secret, public_base_url)
            VALUES (1, ?, ?, ?)
            """,
            (config.client_id, encrypted_secret, config.public_base_url),
        )


def github_app_manifest(public_base_url: str) -> dict[str, object]:
    return {
        "name": f"ResuMate-{secrets.token_hex(4)}",
        "url": public_base_url,
        "redirect_url": f"{public_base_url}/api/auth/oauth/github/setup/callback",
        "callback_urls": [f"{public_base_url}/api/auth/oauth/github/callback"],
        "description": "Private GitHub sign-in for your ResuMate workspace.",
        "public": False,
        "default_permissions": {},
        "default_events": [],
        "request_oauth_on_install": False,
    }


async def convert_github_manifest(code: str, public_base_url: str) -> GitHubAppConfig:
    endpoint = (
        f"https://api.github.com/app-manifests/{quote(code, safe='')}/conversions"
    )
    try:
        async with httpx2.AsyncClient(timeout=15, headers=GITHUB_API_HEADERS) as client:
            response = await client.post(endpoint)
            response.raise_for_status()
            data = response.json()
    except (httpx2.HTTPError, ValueError) as exc:
        raise OAuthFlowError(APP_MESSAGE_OAUTH_SETUP_FAILED) from exc
    if not isinstance(data, dict):
        raise OAuthFlowError(APP_MESSAGE_OAUTH_SETUP_FAILED)
    client_id = data.get("client_id")
    client_secret = data.get("client_secret")
    permissions = data.get("permissions")
    external_url = data.get("external_url")
    if (
        not isinstance(client_id, str)
        or not client_id.strip()
        or not isinstance(client_secret, str)
        or not client_secret.strip()
        or permissions not in ({}, {"metadata": "read"})
        or data.get("events") != []
        or not isinstance(external_url, str)
        or external_url not in {public_base_url, f"{public_base_url}/"}
    ):
        raise OAuthFlowError(APP_MESSAGE_OAUTH_SETUP_FAILED)
    return GitHubAppConfig(client_id, client_secret, public_base_url)
