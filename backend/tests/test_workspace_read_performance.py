from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.connection import connect
from app.services import template_publications, templates
from tests.template_fixtures import portable_template


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/workspace/pages/resumes",
        "/api/workspace/pages/resume-editor",
        "/api/workspace/pages/templates",
        "/api/workspace/pages/trash",
        "/api/templates",
        "/api/templates?status=deleted",
    ],
)
def test_template_reads_do_not_sync_an_unchanged_publication_directory(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, endpoint: str
) -> None:
    created = templates.create_template(portable_template("Current"))["template"]
    directory = get_settings().storage_dir / ".template-publications"
    assert directory.is_dir()
    assert list(directory.iterdir()) == []
    path = templates._template_path(created["id"])
    content = path.read_bytes()
    synchronizations = []
    original_sync = template_publications._sync_directory

    def record_sync(path: Path) -> None:
        synchronizations.append(path)
        original_sync(path)

    monkeypatch.setattr(template_publications, "_sync_directory", record_sync)
    response = client.get(endpoint)
    assert response.status_code == 200
    assert path.read_bytes() == content
    assert list(directory.iterdir()) == []
    assert synchronizations == []


def test_recovery_syncs_removed_temporary_publications(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = get_settings().storage_dir / ".template-publications"
    directory.mkdir(parents=True)
    abandoned = [directory / ".first.tmp", directory / ".second.tmp"]
    for path in abandoned:
        path.write_bytes(b"incomplete publication")
    synchronizations = []
    original_sync = template_publications._sync_directory

    def record_sync(path: Path) -> None:
        assert all(not temporary.exists() for temporary in abandoned)
        synchronizations.append(path)
        original_sync(path)

    monkeypatch.setattr(template_publications, "_sync_directory", record_sync)
    with closing(connect()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        template_publications.recover_template_publications(conn)
    assert synchronizations == [directory]
    with closing(connect()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        template_publications.recover_template_publications(conn)
    assert synchronizations == [directory]


def test_workspace_template_pages_reflect_each_completed_change(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/templates", json={"template": portable_template("Before")}
    ).json()["data"]["template"]
    identity = created["id"]
    updated = client.put(
        f"/api/templates/{identity}",
        json={"template": portable_template("After")},
    ).json()["data"]["template"]
    for endpoint in ("resumes", "resume-editor", "templates", "trash"):
        data = client.get(f"/api/workspace/pages/{endpoint}").json()["data"]
        assert data["customTemplates"] == [updated]
    client.post(f"/api/templates/{identity}/trash").raise_for_status()
    data = client.get("/api/workspace/pages/trash").json()["data"]
    assert data["customTemplates"] == []
    assert data["deletedTemplates"][0]["id"] == identity
    assert data["deletedTemplates"][0]["name"] == "After"
    client.post(f"/api/templates/{identity}/restore").raise_for_status()
    data = client.get("/api/workspace/pages/trash").json()["data"]
    assert data["customTemplates"][0]["id"] == identity
    assert data["customTemplates"][0]["name"] == "After"
    assert data["deletedTemplates"] == []
