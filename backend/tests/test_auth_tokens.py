import time

import jwt
import pytest
from fastapi.testclient import TestClient

from app.services import auth_tokens


def test_access_tokens_and_refresh_have_a_36_hour_lifetime(client: TestClient) -> None:
    token, claims = auth_tokens.create_access_token("admin", "revision")
    assert claims.expires_at - claims.issued_at == 36 * 60 * 60
    refreshed, refreshed_claims = auth_tokens.refresh_access_token(token)
    assert refreshed_claims.expires_at - refreshed_claims.issued_at == 36 * 60 * 60
    assert auth_tokens.decode_access_token(refreshed).subject == "admin"
    with pytest.raises(auth_tokens.AuthTokenError, match="revoked"):
        auth_tokens.decode_access_token(token)


def test_access_token_expires_at_the_36_hour_boundary(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime

    token, claims = auth_tokens.create_access_token("admin", "revision")

    class Clock(datetime):
        current = claims.expires_at - 1

        @classmethod
        def now(cls, tz=UTC):
            return datetime.fromtimestamp(cls.current, tz)

    monkeypatch.setattr(jwt.api_jwt, "datetime", Clock)
    assert auth_tokens.decode_access_token(token).expires_at == claims.expires_at
    Clock.current = claims.expires_at
    with pytest.raises(auth_tokens.AuthTokenError):
        auth_tokens.decode_access_token(token)


def _encode_test_token(payload: dict[str, object]) -> str:
    return jwt.encode(
        payload,
        auth_tokens._get_jwt_secret(),
        algorithm="HS256",
        headers={"typ": "JWT"},
    )


def test_access_token_requires_resumate_issuer_and_audience(
    client: TestClient,
) -> None:
    now = int(time.time())
    token = _encode_test_token(
        {
            "sub": "admin",
            "rev": "test-revision",
            "iat": now,
            "exp": now + 60,
            "jti": "test-jwt-id",
        }
    )

    with pytest.raises(auth_tokens.AuthTokenError):
        auth_tokens.decode_access_token(token)


def test_access_token_rejects_a_future_issued_at_claim(
    client: TestClient,
) -> None:
    now = int(time.time())
    token = _encode_test_token(
        {
            "sub": "admin",
            "rev": "test-revision",
            "iat": now + 60,
            "exp": now + 120,
            "jti": "test-jwt-id",
            "iss": "resumate",
            "aud": "resumate-api",
        }
    )

    with pytest.raises(auth_tokens.AuthTokenError):
        auth_tokens.decode_access_token(token)


def test_access_token_requires_one_exact_audience(
    client: TestClient,
) -> None:
    now = int(time.time())
    token = _encode_test_token(
        {
            "sub": "admin",
            "rev": "test-revision",
            "iat": now,
            "exp": now + 60,
            "jti": "test-jwt-id",
            "iss": "resumate",
            "aud": ["resumate-api", "another-service"],
        }
    )

    with pytest.raises(auth_tokens.AuthTokenError):
        auth_tokens.decode_access_token(token)


def test_access_token_normalizes_malformed_time_claim_errors(
    client: TestClient,
) -> None:
    now = int(time.time())
    token = _encode_test_token(
        {
            "sub": "admin",
            "rev": "test-revision",
            "iat": [],
            "exp": now + 60,
            "jti": "test-jwt-id",
            "iss": "resumate",
            "aud": "resumate-api",
        }
    )

    with pytest.raises(auth_tokens.AuthTokenError):
        auth_tokens.decode_access_token(token)


def test_refreshed_token_stays_revoked_until_its_original_expiry(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = int(time.time())
    monkeypatch.setattr(auth_tokens.time, "time", lambda: now)
    monkeypatch.setattr(auth_tokens, "_revoked_token_hashes", {})
    token, original_payload = auth_tokens.create_access_token(
        "admin",
        "test-revision",
    )

    auth_tokens.refresh_access_token(token)
    now += 4 * 60 * 60 + 1

    assert now < original_payload.expires_at
    with pytest.raises(auth_tokens.AuthTokenError, match="revoked"):
        auth_tokens.decode_access_token(token)
