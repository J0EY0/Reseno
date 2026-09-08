import os
import secrets
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime

import jwt

from app.config import JWT_SECRET_ENV_NAME, get_settings
from app.services.auth_accounts import connect_auth_database

ACCESS_TOKEN_TTL_SECONDS = 36 * 60 * 60
JWT_ALGORITHM = "HS256"
JWT_ISSUER = "reseno"
JWT_AUDIENCE = "reseno-api"
JWT_REQUIRED_CLAIMS = ("sub", "rev", "iat", "exp", "jti", "iss", "aud")


class AuthTokenError(Exception):
    """Raised when an access token cannot be trusted."""

    pass


@dataclass(frozen=True)
class AuthTokenPayload:
    """Validated claims extracted from a browser access token."""

    subject: str
    auth_revision: str
    expires_at: int
    issued_at: int
    jwt_id: str


def _get_jwt_secret() -> bytes:
    """Return the configured JWT signing secret as bytes."""

    get_settings()
    secret = os.getenv(JWT_SECRET_ENV_NAME)
    if not secret:
        raise RuntimeError(f"Missing {JWT_SECRET_ENV_NAME}.")

    return secret.encode("utf-8")


def format_token_expiry(expires_at: int) -> str:
    """Format a token expiry timestamp as an ISO UTC string."""

    return datetime.fromtimestamp(expires_at, UTC).isoformat().replace("+00:00", "Z")


def create_access_token(
    subject: str,
    auth_revision: str,
    *,
    ttl_seconds: int = ACCESS_TOKEN_TTL_SECONDS,
) -> tuple[str, AuthTokenPayload]:
    """Create a signed access token and return it with its parsed payload."""

    now = int(time.time())
    expires_at = now + ttl_seconds
    payload = {
        "sub": subject,
        "rev": auth_revision,
        "iat": now,
        "exp": expires_at,
        "jti": secrets.token_urlsafe(16),
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
    }
    token = jwt.encode(
        payload,
        _get_jwt_secret(),
        algorithm=JWT_ALGORITHM,
        headers={"typ": "JWT"},
    )

    return (
        token,
        AuthTokenPayload(
            subject=subject,
            auth_revision=auth_revision,
            expires_at=expires_at,
            issued_at=now,
            jwt_id=str(payload["jti"]),
        ),
    )


def is_access_token_revoked(jwt_id: str) -> bool:
    """Return whether a verified token identity has been revoked."""

    with closing(connect_auth_database()) as conn:
        return conn.execute(
            "SELECT 1 FROM auth_revoked_tokens WHERE jwt_id = ?",
            (jwt_id,),
        ).fetchone() is not None


def decode_access_token(token: str) -> AuthTokenPayload:
    """Validate a token and return its trusted payload."""

    try:
        decoded = jwt.decode_complete(
            token,
            _get_jwt_secret(),
            algorithms=[JWT_ALGORITHM],
            audience=JWT_AUDIENCE,
            issuer=JWT_ISSUER,
            options={
                "require": list(JWT_REQUIRED_CLAIMS),
                "strict_aud": True,
            },
        )
    except (jwt.InvalidTokenError, TypeError, OverflowError) as exc:
        raise AuthTokenError("Invalid access token.") from exc

    header = decoded["header"]
    payload = decoded["payload"]

    if header.get("alg") != JWT_ALGORITHM or header.get("typ") != "JWT":
        raise AuthTokenError("Unsupported access token header.")

    subject = payload.get("sub")
    auth_revision = payload.get("rev")
    expires_at = payload.get("exp")
    issued_at = payload.get("iat")
    jwt_id = payload.get("jti")

    if (
        not isinstance(subject, str)
        or not subject.strip()
        or not isinstance(auth_revision, str)
        or not auth_revision
        or type(expires_at) is not int
        or type(issued_at) is not int
        or not isinstance(jwt_id, str)
        or not jwt_id
    ):
        raise AuthTokenError("Incomplete access token payload.")

    if is_access_token_revoked(jwt_id):
        raise AuthTokenError("Access token has been revoked.")

    return AuthTokenPayload(
        subject=subject,
        auth_revision=auth_revision,
        expires_at=expires_at,
        issued_at=issued_at,
        jwt_id=jwt_id,
    )


def refresh_access_token(token: str) -> tuple[str, AuthTokenPayload]:
    """Revoke the current token and issue a replacement for the same subject."""

    payload = decode_access_token(token)
    with closing(connect_auth_database()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "DELETE FROM auth_revoked_tokens WHERE expires_at <= ?",
            (int(time.time()),),
        )
        inserted = conn.execute(
            "INSERT OR IGNORE INTO auth_revoked_tokens (jwt_id, expires_at) "
            "VALUES (?, ?)",
            (payload.jwt_id, payload.expires_at),
        )
        if inserted.rowcount != 1:
            raise AuthTokenError("Access token has been revoked.")
        replacement = create_access_token(payload.subject, payload.auth_revision)
    return replacement
