import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.connection import connect
from app.services import resumes, storage_deletions, templates
from app.services.agent.attachments import store_resume_agent_attachment
from app.services.storage_deletions import StorageKind
from tests.template_fixtures import portable_template


def _create_deleted(kind: StorageKind) -> str:
    if kind == "resumes":
        item = resumes.create_resume({"documentLocale": "en"})["resume"]
        store_resume_agent_attachment(
            resume_id=item["id"],
            filename="source.txt",
            media_type="text/plain",
            payload=b"Original attachment",
        )
        resumes.trash_resume(item["id"])
    else:
        item = templates.create_template(portable_template())["template"]
        templates.trash_template(item["id"])
    return str(item["id"])


def _files(kind: StorageKind, entity_id: str) -> dict[str, bytes]:
    root = get_settings().storage_dir
    paths = [root / kind / entity_id]
    if kind == "resumes":
        paths.append(root / "agent-attachments" / entity_id)
    return {
        str(file.relative_to(root)): file.read_bytes()
        for path in paths
        for file in path.rglob("*")
        if file.is_file()
    }


def _delete(kind: StorageKind, entity_id: str) -> dict:
    if kind == "resumes":
        return resumes.delete_resume_forever(entity_id)
    return templates.delete_template_forever(entity_id)


def _row_exists(kind: StorageKind, entity_id: str) -> bool:
    with closing(connect()) as conn:
        return (
            conn.execute(f"SELECT 1 FROM {kind} WHERE id = ?", (entity_id,)).fetchone()
            is not None
        )


@pytest.mark.parametrize("kind", ["resumes", "templates"])
@pytest.mark.parametrize("failure", ["delete", "commit"])
def test_failed_database_deletion_restores_all_files(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    kind: StorageKind,
    failure: str,
) -> None:
    entity_id = _create_deleted(kind)
    original_files = _files(kind, entity_id)
    if failure == "delete":
        with closing(connect()) as conn:
            conn.execute(
                f"CREATE TRIGGER reject_delete BEFORE DELETE ON {kind} "
                "BEGIN SELECT RAISE(ABORT, 'forced SQL failure'); END"
            )
    else:

        def reject_commit_connect() -> sqlite3.Connection:
            conn = connect()
            conn.set_authorizer(
                lambda action, operation, *_args: (
                    sqlite3.SQLITE_DENY
                    if action == sqlite3.SQLITE_TRANSACTION and operation == "COMMIT"
                    else sqlite3.SQLITE_OK
                )
            )
            return conn

        monkeypatch.setattr(
            resumes if kind == "resumes" else templates,
            "connect",
            reject_commit_connect,
        )

    with pytest.raises(sqlite3.DatabaseError):
        _delete(kind, entity_id)

    if failure == "commit":
        monkeypatch.setattr(
            resumes if kind == "resumes" else templates, "connect", connect
        )

    assert _row_exists(kind, entity_id)
    assert _files(kind, entity_id) == original_files
    assert not storage_deletions._journal_path(kind, entity_id).exists()
    assert client.get("/api/workspace/pages/trash").status_code == 200


def test_partial_file_deletion_restores_resume_and_attachments(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    entity_id = _create_deleted("resumes")
    original_files = _files("resumes", entity_id)

    def partial_delete(resume_id: str) -> None:
        path = resumes._resume_storage_dir(resume_id)
        next(path.rglob("*.json")).unlink()
        raise PermissionError("forced partial deletion")

    monkeypatch.setattr(resumes, "_delete_resume_storage", partial_delete)
    with pytest.raises(PermissionError, match="partial deletion"):
        resumes.delete_resume_forever(entity_id)

    assert _row_exists("resumes", entity_id)
    assert _files("resumes", entity_id) == original_files
    assert client.get("/api/workspace/pages/trash").status_code == 200


@pytest.mark.parametrize("kind", ["resumes", "templates"])
def test_backup_failure_never_deletes_original_files(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, kind: StorageKind
) -> None:
    entity_id = _create_deleted(kind)
    original_files = _files(kind, entity_id)

    def reject_link(*_args: object, **_kwargs: object) -> None:
        raise OSError("forced backup failure")

    monkeypatch.setattr(storage_deletions.os, "link", reject_link)
    with pytest.raises(OSError, match="backup failure"):
        _delete(kind, entity_id)

    assert _row_exists(kind, entity_id)
    assert _files(kind, entity_id) == original_files


@pytest.mark.parametrize("kind", ["resumes", "templates"])
@pytest.mark.parametrize("retry", ["single", "empty_trash"])
def test_committed_cleanup_failure_is_retryable(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    kind: StorageKind,
    retry: str,
) -> None:
    entity_id = _create_deleted(kind)
    journal = storage_deletions._journal_path(kind, entity_id)
    original_rmtree = storage_deletions.shutil.rmtree

    def fail_cleanup(path: Path, *args: object, **kwargs: object) -> None:
        if path == journal:
            raise PermissionError("forced journal cleanup failure")
        original_rmtree(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(storage_deletions.shutil, "rmtree", fail_cleanup)
        with pytest.raises(HTTPException) as raised:
            _delete(kind, entity_id)
        assert raised.value.status_code == 503
        assert raised.value.detail == "STORAGE_DELETE_CLEANUP_PENDING"
        with pytest.raises(HTTPException) as retry_raised:
            _delete(kind, entity_id)
        assert retry_raised.value.detail == "STORAGE_DELETE_CLEANUP_PENDING"

    assert not _row_exists(kind, entity_id)
    assert not _files(kind, entity_id)
    assert journal.exists()
    assert storage_deletions.storage_id_reserved(kind, entity_id)

    if retry == "single":
        assert _delete(kind, entity_id) == {"id": entity_id}
    elif kind == "resumes":
        resumes.empty_resume_trash()
    else:
        templates.empty_template_trash()
    assert not journal.exists()
    assert not storage_deletions.storage_id_reserved(kind, entity_id)


@pytest.mark.parametrize("kind", ["resumes", "templates"])
@pytest.mark.parametrize("phase", ["before_commit", "after_commit"])
def test_process_interruption_recovers_from_durable_database_state(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    kind: StorageKind,
    phase: str,
) -> None:
    entity_id = _create_deleted(kind)
    original_files = _files(kind, entity_id)
    program = """
import os
import sys
from pathlib import Path
from app.services import resumes, templates, storage_deletions
kind, entity_id, phase = sys.argv[1:]
service = resumes if kind == 'resumes' else templates
original_delete = storage_deletions.delete_storage
original_rmtree = storage_deletions.shutil.rmtree
if phase == 'before_commit':
    def interrupted_delete(conn, kind, entity_id, *, delete_files, delete_rows):
        def interrupted_rows():
            delete_rows()
            os._exit(23)
        original_delete(conn, kind, entity_id,
            delete_files=delete_files, delete_rows=interrupted_rows)
    service.delete_storage = interrupted_delete
else:
    def interrupted_cleanup(path, *args, **kwargs):
        if '.deletions' in Path(path).parts:
            os._exit(23)
        original_rmtree(path, *args, **kwargs)
    storage_deletions.shutil.rmtree = interrupted_cleanup
if kind == 'resumes':
    resumes.delete_resume_forever(entity_id)
else:
    templates.delete_template_forever(entity_id)
"""
    result = subprocess.run(
        [sys.executable, "-c", program, kind, entity_id, phase],
        cwd=Path(__file__).parents[1],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 23, result.stderr
    assert not _files(kind, entity_id)
    assert storage_deletions._journal_path(kind, entity_id).exists()
    assert _row_exists(kind, entity_id) == (phase == "before_commit")

    if phase == "after_commit":
        candidates = iter([entity_id, "NewStorageIdentity"])
        if kind == "resumes":
            monkeypatch.setattr(resumes, "generate_resume_id", lambda: next(candidates))
            created = resumes.create_resume({"documentLocale": "en"})["resume"]
        else:
            monkeypatch.setattr(
                templates, "_generate_template_id", lambda: next(candidates)
            )
            created = templates.create_template(portable_template("New template"))[
                "template"
            ]
        assert created["id"] == "NewStorageIdentity"

    storage_deletions.recover_pending_storage_deletions()
    assert not storage_deletions._journal_path(kind, entity_id).exists()
    assert _files(kind, entity_id) == (
        original_files if phase == "before_commit" else {}
    )
    if phase == "after_commit":
        assert _files(kind, "NewStorageIdentity")
    assert client.get("/api/workspace/pages/trash").status_code == 200
