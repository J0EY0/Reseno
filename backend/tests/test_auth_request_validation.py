import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services import auth_accounts, auth_tokens


@pytest.mark.parametrize("refresh", [False, True])
def test_authenticated_request_uses_one_auth_state_connection(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    refresh: bool,
) -> None:
    assert isinstance(client.app, FastAPI)
    client.app.add_api_route("/api/auth-test", lambda: {"authenticated": True})
    auth_db_path = auth_accounts.get_auth_db_path()
    connect = sqlite3.connect

    class TrackedConnection(sqlite3.Connection):
        closed = False

        def close(self) -> None:
            super().close()
            self.closed = True

    connections: list[TrackedConnection] = []
    statements: list[str] = []

    def counted_connect(database, *args, **kwargs):
        if Path(database).resolve() != auth_db_path:
            return connect(database, *args, **kwargs)
        connection = connect(database, *args, factory=TrackedConnection, **kwargs)
        connections.append(connection)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(sqlite3, "connect", counted_connect)

    response = (
        client.post("/api/auth/refresh") if refresh else client.get("/api/auth-test")
    )

    assert response.status_code == 200
    assert len(connections) == (2 if refresh else 1)
    reads = [
        query for query in statements if query.lstrip().upper().startswith("SELECT")
    ]
    assert len(reads) == 1
    assert "auth_owner" in reads[0]
    assert "auth_revoked_tokens" in reads[0]
    assert all(connection.closed for connection in connections)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("revoked", "invalid_or_expired_token"),
        ("owner_changed", "owner_missing_or_changed"),
        ("owner_deleted", "owner_missing_or_changed"),
        ("revoked_owner_deleted", "invalid_or_expired_token"),
    ],
)
def test_auth_state_changes_apply_to_the_next_request(
    client: TestClient,
    change: str,
    reason: str,
) -> None:
    assert isinstance(client.app, FastAPI)
    client.app.add_api_route("/api/auth-test", lambda: {"authenticated": True})
    token = client.headers["Authorization"].removeprefix("Bearer ")
    payload = auth_tokens.decode_access_token(token)
    assert client.get("/api/auth-test").status_code == 200

    with closing(auth_accounts.connect_auth_database()) as connection:
        if change.startswith("revoked"):
            connection.execute(
                "INSERT INTO auth_revoked_tokens (jwt_id, expires_at) VALUES (?, ?)",
                (payload.jwt_id, payload.expires_at),
            )
        if change == "owner_changed":
            connection.execute(
                "UPDATE auth_owner SET auth_revision = 'changed' WHERE id = 1"
            )
        if change.endswith("owner_deleted"):
            connection.execute("DELETE FROM auth_owner WHERE id = 1")

    response = client.get("/api/auth-test")

    assert response.status_code == 401
    assert response.json()["data"]["reason"] == reason
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize("authenticated", [False, True])
@pytest.mark.parametrize(
    "path", ["/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"]
)
def test_api_documentation_is_not_exposed_over_http(
    client: TestClient,
    authenticated: bool,
    path: str,
) -> None:
    if not authenticated:
        client.headers.pop("Authorization")

    assert client.get(path).status_code == 404


def test_openapi_schema_remains_available_in_process(
    uninitialized_client: TestClient,
) -> None:
    assert isinstance(uninitialized_client.app, FastAPI)
    schema = uninitialized_client.app.openapi()

    assert schema["openapi"]
    assert "/api/auth/refresh" in schema["paths"]
