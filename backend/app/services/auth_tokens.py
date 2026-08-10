import hashlib
import os
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock

import jwt

from app.config import JWT_SECRET_ENV_NAME, get_settings

ACCESS_TOKEN_TTL_SECONDS = 8 * 60 * 60
JWT_ALGORITHM = "HS256"
JWT_ISSUER = "resumate"
JWT_AUDIENCE = "resumate-api"
JWT_REQUIRED_CLAIMS = ("sub", "rev", "iat", "exp", "jti", "iss", "aud")

_revoked_token_hashes: dict[str, int] = {}
_revoked_token_lock = Lock()


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


def _hash_token(token: str) -> str:
    """Hash a token before storing it in the in-memory revocation cache."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _cleanup_revoked_tokens(now: int) -> None:
    """Remove expired token hashes from the revocation cache."""

    expired_hashes = [
        token_hash
        for token_hash, expires_at in _revoked_token_hashes.items()
        if expires_at <= now
    ]
    for token_hash in expired_hashes:
        _revoked_token_hashes.pop(token_hash, None)


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


def revoke_access_token(token: str, *, expires_at: int) -> None:
    """Mark a token as unusable until its revocation entry expires."""

    now = int(time.time())
    with _revoked_token_lock:
        _cleanup_revoked_tokens(now)
        _revoked_token_hashes[_hash_token(token)] = expires_at


def is_access_token_revoked(token: str) -> bool:
    """Return whether a token is currently revoked."""

    now = int(time.time())
    with _revoked_token_lock:
        _cleanup_revoked_tokens(now)
        return _hash_token(token) in _revoked_token_hashes


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

    if is_access_token_revoked(token):
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
    revoke_access_token(token, expires_at=payload.expires_at)
    return create_access_token(payload.subject, payload.auth_revision)
