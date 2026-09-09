from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from app.routers import auth as auth_router
from app.services import auth_accounts, auth_tokens
from app.services.auth_accounts import OwnerAccount, OwnerChangedError
from app.services.auth_identities import (
    OAuthIdentity,
    consume_oauth_code,
    create_oauth_code,
)


def _owner_snapshot() -> dict:
    with closing(auth_accounts.connect_auth_database()) as connection:
        row = connection.execute("SELECT * FROM auth_owner WHERE id = 1").fetchone()
    assert row is not None
    return dict(row)


def _identity_snapshot() -> list[dict]:
    with closing(auth_accounts.connect_auth_database()) as connection:
        return [
            dict(row) for row in connection.execute("SELECT * FROM auth_identities")
        ]


def test_username_update_preserves_password_github_binding_and_resume(
    client: TestClient,
) -> None:
    before = _owner_snapshot()
    identity = OAuthIdentity(provider="github", subject="12345", label="researcher")
    binding = create_oauth_code(identity, "bind", before["auth_revision"], "browser")
    consume_oauth_code(binding, "browser")
    identities = _identity_snapshot()
    created = client.post(
        "/api/resumes", json={"documentLocale": "en", "title": "Existing resume"}
    )
    assert created.status_code == 200
    resume = created.json()["data"]["resume"]

    response = client.post(
        "/api/auth/username",
        json={
            "newUsername": " research_owner-1 ",
            "currentPassword": "TestPassword2026",
        },
    )

    assert response.status_code == 200
    credentials = response.json()["data"]
    assert set(credentials) == {"username", "accessToken", "expiresAt", "tokenType"}
    assert credentials["username"] == "research_owner-1"
    assert credentials["tokenType"] == "bearer"
    claims = auth_tokens.authenticate_access_token(credentials["accessToken"])
    assert claims.subject == "research_owner-1"
    assert credentials["expiresAt"] == auth_tokens.format_token_expiry(
        claims.expires_at
    )
    after = _owner_snapshot()
    assert after["auth_revision"] == claims.auth_revision != before["auth_revision"]
    for field in ("id", "password_hash", "created_at"):
        assert after[field] == before[field]
    assert _identity_snapshot() == identities
    assert client.get("/api/resumes").status_code == 401
    client.headers["Authorization"] = f"Bearer {credentials['accessToken']}"
    loaded = client.get(f"/api/resumes/{resume['id']}")
    assert loaded.status_code == 200
    assert loaded.json()["data"]["resume"] == resume
    assert (
        client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "TestPassword2026"},
        ).status_code
        == 401
    )
    login = client.post(
        "/api/auth/login",
        json={"username": "research_owner-1", "password": "TestPassword2026"},
    )
    assert login.status_code == 200
    assert login.json()["data"]["username"] == "research_owner-1"
    code = create_oauth_code(identity, "login", after["auth_revision"], "browser")
    _, intent, owner = consume_oauth_code(code, "browser")
    assert intent == "login"
    assert owner.username == "research_owner-1"
    assert owner.auth_revision == after["auth_revision"]
    assert _identity_snapshot() == identities


@pytest.mark.parametrize(
    ("username", "message"),
    [
        ("", "USERNAME_REQUIRED"),
        ("  ", "USERNAME_REQUIRED"),
        ("ab", "USERNAME_INVALID"),
        ("invalid name", "USERNAME_INVALID"),
        ("owner!", "USERNAME_INVALID"),
        ("用户名", "USERNAME_INVALID"),
    ],
)
def test_username_update_rejects_invalid_names_without_writes(
    client: TestClient,
    username: str,
    message: str,
) -> None:
    before = _owner_snapshot()
    response = client.post(
        "/api/auth/username",
        json={"newUsername": username, "currentPassword": "TestPassword2026"},
    )
    assert response.status_code == 400
    assert response.json()["message"] == message
    assert _owner_snapshot() == before
    assert client.get("/api/resumes").status_code == 200


@pytest.mark.parametrize("username", ["admin", "new_owner"])
@pytest.mark.parametrize("password", ["wrong-password", " TestPassword2026 "])
def test_username_update_checks_current_password_even_for_unchanged_name(
    client: TestClient,
    username: str,
    password: str,
) -> None:
    before = _owner_snapshot()
    response = client.post(
        "/api/auth/username",
        json={"newUsername": username, "currentPassword": password},
    )
    assert response.status_code == 400
    assert response.json()["message"] == "INVALID_CREDENTIALS"
    assert _owner_snapshot() == before
    assert client.get("/api/resumes").status_code == 200


@pytest.mark.parametrize("authorization", ["", "Bearer invalid-token"])
def test_username_update_requires_authentication_without_writes(
    client: TestClient,
    authorization: str,
) -> None:
    before = _owner_snapshot()
    response = client.post(
        "/api/auth/username",
        headers={"Authorization": authorization},
        json={"newUsername": "new_owner", "currentPassword": "TestPassword2026"},
    )
    assert response.status_code == 401
    assert response.json()["message"] == "UNAUTHORIZED_REQUEST"
    assert _owner_snapshot() == before


@pytest.mark.parametrize(
    "payload",
    [{"newUsername": "new_owner"}, {"newUsername": 123, "currentPassword": "valid"}],
)
def test_username_update_validates_request_shape_without_writes(
    client: TestClient,
    payload: dict,
) -> None:
    before = _owner_snapshot()
    response = client.post("/api/auth/username", json=payload)
    assert response.status_code == 422
    assert response.json()["message"] == "VALIDATION_ERROR"
    assert _owner_snapshot() == before


def test_unchanged_username_preserves_revision_and_existing_sessions(
    client: TestClient,
) -> None:
    before = _owner_snapshot()
    original = client.headers["Authorization"].removeprefix("Bearer ")
    response = client.post(
        "/api/auth/username",
        json={"newUsername": " admin ", "currentPassword": "TestPassword2026"},
    )
    assert response.status_code == 200
    credentials = response.json()["data"]
    assert credentials["username"] == "admin"
    assert credentials["accessToken"] != original
    assert _owner_snapshot() == before
    for token in (original, credentials["accessToken"]):
        assert (
            auth_tokens.authenticate_access_token(token).auth_revision
            == (before["auth_revision"])
        )


def test_username_roundtrip_does_not_restore_old_tokens(client: TestClient) -> None:
    tokens = [client.headers["Authorization"].removeprefix("Bearer ")]
    revisions = [_owner_snapshot()["auth_revision"]]
    for username in ("renamed_owner", "admin"):
        response = client.post(
            "/api/auth/username",
            json={"newUsername": username, "currentPassword": "TestPassword2026"},
        )
        assert response.status_code == 200
        tokens.append(response.json()["data"]["accessToken"])
        revisions.append(_owner_snapshot()["auth_revision"])
        client.headers["Authorization"] = f"Bearer {tokens[-1]}"
    assert len(set(revisions)) == 3
    for token in tokens[:-1]:
        response = client.get(
            "/api/resumes", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 401
        assert response.json()["data"]["reason"] == "owner_missing_or_changed"
    assert client.get("/api/resumes").status_code == 200
    assert _owner_snapshot()["username"] == "admin"


def test_concurrent_username_updates_reject_the_stale_request(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    barrier = Barrier(2)
    update = auth_accounts.update_owner_username

    @contextmanager
    def concurrent_update(
        expected_owner: OwnerAccount,
        current_password: str,
        new_username: str,
    ) -> Iterator[OwnerAccount]:
        barrier.wait(timeout=5)
        with update(expected_owner, current_password, new_username) as owner:
            yield owner

    monkeypatch.setattr(auth_router, "update_owner_username", concurrent_update)
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(
                lambda username: client.post(
                    "/api/auth/username",
                    json={
                        "newUsername": username,
                        "currentPassword": "TestPassword2026",
                    },
                ),
                ("first_owner", "second_owner"),
            )
        )
    assert sorted(response.status_code for response in responses) == [200, 401]
    winner = next(
        response.json()["data"] for response in responses if response.status_code == 200
    )
    rejected = next(response for response in responses if response.status_code == 401)
    assert rejected.json()["message"] == "UNAUTHORIZED_REQUEST"
    assert _owner_snapshot()["username"] == winner["username"]
    assert (
        auth_tokens.authenticate_access_token(winner["accessToken"]).subject
        == (winner["username"])
    )
    assert client.get("/api/resumes").status_code == 401


@pytest.mark.parametrize("change", ["password", "username"])
def test_username_update_rejects_stale_owner_after_credential_roundtrip(
    client: TestClient,
    change: str,
) -> None:
    before = _owner_snapshot()
    expected_owner = OwnerAccount(before["username"], before["auth_revision"])
    if change == "password":
        assert (
            auth_accounts.update_owner_password(
                "admin", "TestPassword2026", "ChangedPassword2026"
            )
            is not None
        )
        assert (
            auth_accounts.update_owner_password(
                "admin", "ChangedPassword2026", "TestPassword2026"
            )
            is not None
        )
    else:
        with auth_accounts.update_owner_username(
            expected_owner, "TestPassword2026", "temporary_owner"
        ) as temporary:
            pass
        with auth_accounts.update_owner_username(
            temporary, "TestPassword2026", "admin"
        ):
            pass
    current = _owner_snapshot()
    assert current["username"] == before["username"]
    assert current["auth_revision"] != before["auth_revision"]
    with (
        pytest.raises(OwnerChangedError),
        auth_accounts.update_owner_username(
            expected_owner, "TestPassword2026", "stale_owner"
        ),
    ):
        pytest.fail("A stale request entered the username transaction")
    assert _owner_snapshot() == current


def test_username_update_signing_failure_rolls_back_and_preserves_session(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = _owner_snapshot()

    def fail_signing(*args, **kwargs):
        assert _owner_snapshot() == before
        raise RuntimeError("Synthetic username signing failure")

    with monkeypatch.context() as failing:
        failing.setattr(auth_router, "create_access_token", fail_signing)
        with pytest.raises(RuntimeError, match="Synthetic username signing failure"):
            client.post(
                "/api/auth/username",
                json={
                    "newUsername": "new_owner",
                    "currentPassword": "TestPassword2026",
                },
            )
    assert _owner_snapshot() == before
    assert client.get("/api/resumes").status_code == 200
    assert (
        client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "TestPassword2026"},
        ).status_code
        == 200
    )
