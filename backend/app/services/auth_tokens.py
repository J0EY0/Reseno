import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from app.config import JWT_SECRET_ENV_NAME, get_settings

ACCESS_TOKEN_TTL_SECONDS = 8 * 60 * 60
REFRESH_REVOKE_TTL_SECONDS = 4 * 60 * 60

_revoked_token_hashes: dict[str, int] = {}
_revoked_token_lock = Lock()


class AuthTokenError(Exception):
    """Raised when an access token cannot be trusted."""

    pass


@dataclass(frozen=True)
class AuthTokenPayload:
    """Validated claims extracted from a browser access token."""

    subject: str
    expires_at: int
    issued_at: int
    jwt_id: str


def _base64url_encode(value: bytes) -> str:
    """Encode bytes using unpadded Base64URL."""

    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    """Decode unpadded Base64URL text into bytes."""

    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))


def _json_dumps(value: dict[str, Any]) -> bytes:
    """Serialize JSON deterministically for JWT signing."""

    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _get_jwt_secret() -> bytes:
    """Return the configured JWT signing secret as bytes."""

    get_settings()
    secret = os.getenv(JWT_SECRET_ENV_NAME)
    if not secret:
        raise RuntimeError(f"Missing {JWT_SECRET_ENV_NAME}.")

    return secret.encode("utf-8")


def _sign(value: str) -> str:
    """Sign a JWT header and payload string with HMAC-SHA256."""

    signature = hmac.new(
        _get_jwt_secret(),
        value.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return _base64url_encode(signature)


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
    *,
    ttl_seconds: int = ACCESS_TOKEN_TTL_SECONDS,
) -> tuple[str, AuthTokenPayload]:
    """Create a signed access token and return it with its parsed payload."""

    now = int(time.time())
    expires_at = now + ttl_seconds
    payload = {
        "sub": subject,
        "iat": now,
        "exp": expires_at,
        "jti": secrets.token_urlsafe(16),
    }
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = ".".join(
        (
            _base64url_encode(_json_dumps(header)),
            _base64url_encode(_json_dumps(payload)),
        ),
    )
    token = f"{signing_input}.{_sign(signing_input)}"

    return (
        token,
        AuthTokenPayload(
            subject=subject,
            expires_at=expires_at,
            issued_at=now,
            jwt_id=str(payload["jti"]),
        ),
    )


def revoke_access_token(
    token: str, *, ttl_seconds: int = REFRESH_REVOKE_TTL_SECONDS
) -> None:
    """Mark a token as unusable until its revocation entry expires."""

    now = int(time.time())
    with _revoked_token_lock:
        _cleanup_revoked_tokens(now)
        _revoked_token_hashes[_hash_token(token)] = now + ttl_seconds


def is_access_token_revoked(token: str) -> bool:
    """Return whether a token is currently revoked."""

    now = int(time.time())
    with _revoked_token_lock:
        _cleanup_revoked_tokens(now)
        return _hash_token(token) in _revoked_token_hashes


def decode_access_token(token: str) -> AuthTokenPayload:
    """Validate a token and return its trusted payload."""

    try:
        header_segment, payload_segment, signature_segment = token.split(".", 2)
    except ValueError as exc:
        raise AuthTokenError("Malformed access token.") from exc

    signing_input = f"{header_segment}.{payload_segment}"
    expected_signature = _sign(signing_input)
    if not hmac.compare_digest(signature_segment, expected_signature):
        raise AuthTokenError("Invalid access token signature.")

    try:
        header = json.loads(_base64url_decode(header_segment))
        payload = json.loads(_base64url_decode(payload_segment))
    except (ValueError, json.JSONDecodeError) as exc:
        raise AuthTokenError("Invalid access token payload.") from exc

    if header.get("alg") != "HS256" or header.get("typ") != "JWT":
        raise AuthTokenError("Unsupported access token header.")

    subject = payload.get("sub")
    expires_at = payload.get("exp")
    issued_at = payload.get("iat")
    jwt_id = payload.get("jti")

    if (
        not isinstance(subject, str)
        or not subject.strip()
        or not isinstance(expires_at, int)
        or not isinstance(issued_at, int)
        or not isinstance(jwt_id, str)
    ):
        raise AuthTokenError("Incomplete access token payload.")

    if expires_at <= int(time.time()):
        raise AuthTokenError("Access token expired.")

    if is_access_token_revoked(token):
        raise AuthTokenError("Access token has been revoked.")

    return AuthTokenPayload(
        subject=subject,
        expires_at=expires_at,
        issued_at=issued_at,
        jwt_id=jwt_id,
    )


def refresh_access_token(token: str) -> tuple[str, AuthTokenPayload]:
    """Revoke the current token and issue a replacement for the same subject."""

    payload = decode_access_token(token)
    revoke_access_token(token)
    return create_access_token(payload.subject)
