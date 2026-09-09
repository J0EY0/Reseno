import sqlite3
from contextlib import closing
from unittest.mock import AsyncMock, create_autospec
from urllib.parse import urlsplit

import anyio
import pytest
from fastapi.testclient import TestClient

from app.db.connection import connect
from app.routers import resumes as resumes_router
from app.routers.dependencies import get_agent_run_manager
from app.services.agent_runs import AgentRunConflictError, AgentRunManager


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/auth/setup"),
        ("POST", "/api/auth/setup"),
        ("POST", "/api/auth/login"),
        ("POST", "/api/auth/oauth/complete"),
        ("POST", "/api/auth/oauth/github/login"),
        ("GET", "/api/auth/oauth/github/callback"),
        ("GET", "/api/auth/oauth/github/setup/callback"),
    ],
)
def test_public_routes_preserve_trailing_slash_redirects(
    uninitialized_client: TestClient,
    method: str,
    path: str,
) -> None:
    response = uninitialized_client.request(
        method, f"{path}/?state=synthetic", follow_redirects=False
    )

    assert response.status_code == 307
    location = urlsplit(response.headers["Location"])
    assert location.path == path
    assert location.query == "state=synthetic"


def test_login_redirect_preserves_the_post_body(
    unauthenticated_client: TestClient,
) -> None:
    response = unauthenticated_client.post(
        "/api/auth/login/",
        json={"username": "admin", "password": "TestPassword2026"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["accessToken"]


@pytest.mark.parametrize(
    "path",
    [
        "/api/resumes",
        "/api/resumes/",
        "/api/auth/refresh/",
        "/api/auth/oauth/identities/",
        "/api/auth/oauth/github/bind/",
        "/api/auth/login/private/",
        "/api/auth/login//",
        "/api/auth/login///",
    ],
)
def test_private_routes_require_authentication_before_redirecting(
    uninitialized_client: TestClient,
    path: str,
) -> None:
    response = uninitialized_client.get(path, follow_redirects=False)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["message"] == "UNAUTHORIZED_REQUEST"


def test_missing_run_manager_prevents_resume_deletion(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = client.post("/api/resumes", json={"documentLocale": "en"})
    resume_id = created.json()["data"]["resume"]["id"]
    route = f"/api/resumes/{resume_id}"
    assert client.post(f"{route}/trash").status_code == 200

    with monkeypatch.context() as missing_runtime:
        missing_runtime.setattr(client.app.state, "agent_runs", None)
        with pytest.raises(RuntimeError, match="Agent run manager is not initialized"):
            client.delete(route)

    trashed = client.get("/api/resumes", params={"status": "deleted"})
    assert [item["id"] for item in trashed.json()["data"]["resumes"]] == [resume_id]


def test_agent_and_resume_routes_share_the_overridden_run_manager(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = create_autospec(AgentRunManager, instance=True)
    manager.start.side_effect = AgentRunConflictError()
    monkeypatch.setitem(
        client.app.dependency_overrides, get_agent_run_manager, lambda: manager
    )
    chat = client.post(
        "/api/agent/chat",
        json={"message": {"id": "current", "role": "user", "text": "Hello"}},
    )
    assert chat.status_code == 409
    assert chat.json()["message"] == "AGENT_RUN_CONFLICT"
    manager.start.assert_awaited_once()

    created = client.post("/api/resumes", json={"documentLocale": "en"})
    resume_id = created.json()["data"]["resume"]["id"]
    route = f"/api/resumes/{resume_id}"
    assert client.post(f"{route}/trash").status_code == 200
    assert client.delete(route).status_code == 200
    manager.purge_missing_resume_runs.assert_awaited_once_with()


@pytest.mark.parametrize("all_resumes", [False, True])
def test_resume_deletion_purges_runtime_even_when_storage_fails(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    all_resumes: bool,
) -> None:
    created = client.post("/api/resumes", json={"documentLocale": "en"})
    resume_id = created.json()["data"]["resume"]["id"]
    route = f"/api/resumes/{resume_id}"
    assert client.post(f"{route}/trash").status_code == 200
    purge = AsyncMock()
    monkeypatch.setattr(client.app.state.agent_runs, "purge_missing_resume_runs", purge)
    with closing(connect()) as conn:
        conn.execute(
            """
            CREATE TRIGGER reject_resume_delete
            BEFORE DELETE ON resumes
            BEGIN
                SELECT RAISE(ABORT, 'synthetic deletion failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="synthetic deletion failure"):
        client.delete("/api/resumes/trash" if all_resumes else route)

    purge.assert_awaited_once_with()
    trashed = client.get("/api/resumes", params={"status": "deleted"})
    assert [item["id"] for item in trashed.json()["data"]["resumes"]] == [resume_id]


@pytest.mark.parametrize("all_resumes", [False, True])
def test_cancelled_resume_deletion_finishes_runtime_cleanup(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    all_resumes: bool,
) -> None:
    cleaned = False

    async def purge() -> None:
        nonlocal cleaned
        await anyio.sleep(0)
        cleaned = True

    manager = client.app.state.agent_runs
    monkeypatch.setattr(manager, "purge_missing_resume_runs", purge)

    async def cancel_delete() -> None:
        with anyio.CancelScope() as scope:
            scope.cancel()
            if all_resumes:
                await resumes_router.delete_resume_trash(manager)
            else:
                await resumes_router.delete_resume("missing", manager)

    anyio.run(cancel_delete)
    assert cleaned
