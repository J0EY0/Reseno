import json
import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient


def _equivalent_token(token: str, encoding: str) -> str:
    if encoding == "padding":
        return token + "="
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    return token[:-1] + alphabet[alphabet.index(token[-1]) ^ 1]


@pytest.mark.parametrize("encoding", ["padding", "unused_signature_bits"])
def test_refresh_revokes_every_encoding_of_the_same_signed_token(
    client: TestClient,
    encoding: str,
) -> None:
    original = client.headers["Authorization"].removeprefix("Bearer ")
    equivalent = _equivalent_token(original, encoding)
    assert client.get(
        "/api/resumes", headers={"Authorization": f"Bearer {equivalent}"}
    ).status_code == 200

    refreshed = client.post("/api/auth/refresh")
    assert refreshed.status_code == 200
    replacement = refreshed.json()["data"]["accessToken"]
    assert client.get(
        "/api/resumes", headers={"Authorization": f"Bearer {replacement}"}
    ).status_code == 200
    for token in (original, equivalent):
        rejected = client.get(
            "/api/resumes", headers={"Authorization": f"Bearer {token}"}
        )
        assert rejected.status_code == 401
        assert rejected.json()["data"]["reason"] == "invalid_or_expired_token"


def test_revocation_survives_a_fresh_backend_process(client: TestClient) -> None:
    from app.config import get_settings
    from app.services.llm_secrets import encrypt_api_key

    env_file = get_settings().env_file_path
    original_env = env_file.read_bytes()
    encrypted = encrypt_api_key("sk-synthetic-persisted")
    original = client.headers["Authorization"].removeprefix("Bearer ")
    refreshed = client.post("/api/auth/refresh")
    assert refreshed.status_code == 200
    replacement = refreshed.json()["data"]["accessToken"]
    assert client.get("/api/resumes").status_code == 401
    program = """
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock
from app.services import model_metadata
model_metadata.MODEL_METADATA_SNAPSHOT_PATH = (
    Path(os.environ['APP_DATA_DIR']) / 'absent.json'
)
model_metadata._fetch_catalog = AsyncMock(return_value={})
model_metadata._fetch_reasoning_catalog = AsyncMock(return_value={})
from app.main import create_app
from fastapi.testclient import TestClient
from app.services.llm_secrets import decrypt_api_key
payload = json.load(sys.stdin)
with TestClient(create_app(), client=('127.0.0.1', 50001)) as client:
    statuses = [
        client.get(
            '/api/resumes', headers={'Authorization': 'Bearer ' + token}
        ).status_code
        for token in payload["tokens"]
    ]
    decrypted = decrypt_api_key(payload["encrypted"])
print(json.dumps({"statuses": statuses, "decrypted": decrypted}))
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        input=json.dumps({"tokens": [original, replacement], "encrypted": encrypted}),
        env={**os.environ, "RESENO_MASTER_KEY": "", "RESENO_JWT_SECRET": ""},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "statuses": [401, 200], "decrypted": "sk-synthetic-persisted",
    }
    assert env_file.read_bytes() == original_env


def test_concurrent_refresh_has_one_winner_and_one_unauthorized_response(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from app.services import auth_tokens

    barrier = Barrier(2)
    decode = auth_tokens.decode_access_token

    def decode_before_rotation(token: str) -> auth_tokens.AuthTokenPayload:
        payload = decode(token)
        barrier.wait(timeout=5)
        return payload

    with monkeypatch.context() as racing:
        racing.setattr(auth_tokens, "decode_access_token", decode_before_rotation)
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(
                executor.map(lambda _: client.post("/api/auth/refresh"), range(2))
            )

    assert sorted(response.status_code for response in responses) == [200, 401]
    replacement = next(
        response.json()["data"]["accessToken"]
        for response in responses
        if response.status_code == 200
    )
    assert client.get("/api/resumes").status_code == 401
    assert client.get(
        "/api/resumes", headers={"Authorization": f"Bearer {replacement}"}
    ).status_code == 200


def test_expired_revocations_are_pruned_without_reviving_tokens(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time
    from contextlib import closing
    from datetime import UTC, datetime

    import jwt

    from app.services import auth_tokens
    from app.services.auth_accounts import connect_auth_database

    now = int(time.time())

    class Clock(datetime):
        @classmethod
        def now(cls, tz=UTC):
            return datetime.fromtimestamp(now, tz)

    monkeypatch.setattr(auth_tokens.time, "time", lambda: now)
    monkeypatch.setattr(jwt.api_jwt, "datetime", Clock)
    expiring, expiring_claims = auth_tokens.create_access_token(
        "admin", "revision", ttl_seconds=60
    )
    unexpired, unexpired_claims = auth_tokens.create_access_token(
        "admin", "revision", ttl_seconds=120
    )
    auth_tokens.refresh_access_token(expiring)
    auth_tokens.refresh_access_token(unexpired)

    now += 60
    fresh, _ = auth_tokens.create_access_token("admin", "revision")
    replacement, _ = auth_tokens.refresh_access_token(fresh)

    with closing(connect_auth_database()) as conn:
        retained = {
            row["jwt_id"]
            for row in conn.execute("SELECT jwt_id FROM auth_revoked_tokens")
        }
    assert expiring_claims.jwt_id not in retained
    assert unexpired_claims.jwt_id in retained
    with pytest.raises(auth_tokens.AuthTokenError):
        auth_tokens.decode_access_token(expiring)
    with pytest.raises(auth_tokens.AuthTokenError, match="revoked"):
        auth_tokens.decode_access_token(unexpired)
    assert auth_tokens.decode_access_token(replacement).subject == "admin"


def test_failed_replacement_signing_preserves_the_current_session(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import auth_tokens

    original = client.headers["Authorization"].removeprefix("Bearer ")

    def fail_signing(*args, **kwargs):
        raise RuntimeError("Synthetic signing failure")

    monkeypatch.setattr(auth_tokens, "create_access_token", fail_signing)
    with pytest.raises(RuntimeError, match="Synthetic signing failure"):
        auth_tokens.refresh_access_token(original)
    assert client.get("/api/resumes").status_code == 200


def test_auth_initialization_preserves_existing_owner_and_oauth_data(
    client: TestClient,
) -> None:
    from contextlib import closing

    from app.services.auth_accounts import connect_auth_database
    from app.services.auth_github_app import GitHubAppConfig, save_github_app
    from app.services.auth_identities import (
        OAuthIdentity,
        consume_oauth_code,
        create_oauth_code,
        get_owner_revision,
    )

    owner_revision = get_owner_revision()
    save_github_app(
        GitHubAppConfig("synthetic-client", "synthetic-secret", "https://resume.example"),
        owner_revision,
    )
    code = create_oauth_code(
        OAuthIdentity("github", "42", "synthetic-owner"),
        "bind",
        owner_revision,
        "synthetic-browser",
    )
    consume_oauth_code(code, "synthetic-browser")
    tables = ("auth_owner", "auth_identities", "auth_oauth_codes", "auth_github_app")
    with closing(connect_auth_database()) as conn:
        original = {
            table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table}")]
            for table in tables
        }
        conn.execute("DROP TABLE auth_revoked_tokens")

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.services.auth_accounts import ensure_auth_database; "
            "ensure_auth_database()",
        ],
        env={**os.environ, "RESENO_MASTER_KEY": "", "RESENO_JWT_SECRET": ""},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    with closing(connect_auth_database()) as conn:
        assert {
            table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table}")]
            for table in tables
        } == original
        assert conn.execute("SELECT * FROM auth_revoked_tokens").fetchall() == []
    assert client.get("/api/resumes").status_code == 200
    login = client.post(
        "/api/auth/login", json={"username": "admin", "password": "TestPassword2026"}
    )
    assert login.status_code == 200
    identities = client.get("/api/auth/oauth/identities").json()["data"]
    assert identities["identities"][0]["label"] == "synthetic-owner"
    assert identities["providers"] == [{"provider": "github", "configured": True}]
