import os
import shutil
import sqlite3
from pathlib import Path
from threading import Event, Thread, current_thread
from types import TracebackType
from typing import Self

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.connection import connect
from app.services import resumes, templates
from app.services.template_presets import get_builtin_template_preset


class _CommitThenRaiseConnection:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @property
    def in_transaction(self) -> bool:
        return self._conn.in_transaction

    def execute(
        self,
        sql: str,
        parameters: tuple[object, ...] = (),
    ) -> sqlite3.Cursor:
        cursor = self._conn.execute(sql, parameters)
        if sql.strip().upper() == "COMMIT":
            raise sqlite3.OperationalError("forced failure after commit")
        return cursor

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Self:
        self._conn.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        return self._conn.__exit__(exc_type, exc_value, traceback)


def _stored_template_path(template_id: str) -> Path:
    return get_settings().storage_dir / "templates" / template_id / "current.json"


def test_failed_template_create_compensates_before_releasing_the_lock(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template_id = "template-create-failure"
    original_write_template_json = templates._write_template_json
    original_restore_template_json = templates._restore_template_json
    restore_started = Event()
    release_restore = Event()
    contender_acquired_lock = Event()
    create_errors: list[BaseException] = []
    contender_errors: list[BaseException] = []

    def publish_then_fail(
        saved_template_id: str,
        template_item: dict[str, object],
    ) -> None:
        original_write_template_json(saved_template_id, template_item)
        raise OSError("forced failure after publication")

    def pause_restore(saved_template_id: str, content: bytes | None) -> None:
        restore_started.set()
        if not release_restore.wait(timeout=2):
            raise TimeoutError("test did not release compensation")
        original_restore_template_json(saved_template_id, content)

    def create() -> None:
        try:
            templates.create_template({"name": "Uncommitted"})
        except BaseException as exc:
            create_errors.append(exc)

    def contend_for_lock() -> None:
        try:
            with connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                contender_acquired_lock.set()
                conn.execute("COMMIT")
        except BaseException as exc:
            contender_errors.append(exc)

    monkeypatch.setattr(templates, "_generate_template_id", lambda: template_id)
    monkeypatch.setattr(templates, "_write_template_json", publish_then_fail)
    monkeypatch.setattr(templates, "_restore_template_json", pause_restore)
    create_thread = Thread(target=create)
    create_thread.start()
    assert restore_started.wait(timeout=2)

    contender_thread = Thread(target=contend_for_lock)
    contender_thread.start()
    contender_was_blocked = not contender_acquired_lock.wait(timeout=0.2)
    release_restore.set()
    create_thread.join(timeout=2)
    contender_thread.join(timeout=2)

    assert contender_was_blocked
    assert not create_thread.is_alive()
    assert not contender_thread.is_alive()
    assert len(create_errors) == 1
    assert isinstance(create_errors[0], OSError)
    assert not contender_errors
    assert not _stored_template_path(template_id).exists()
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM templates WHERE id = ?",
            (template_id,),
        ).fetchone()
    assert row is None


def test_failed_template_update_restores_the_committed_json(
    client: TestClient,
) -> None:
    created = templates.create_template({"name": "Before"})["template"]
    template_id = created["id"]
    with connect() as conn:
        conn.execute(
            """
            CREATE TRIGGER reject_template_update
            BEFORE UPDATE ON templates
            BEGIN
                SELECT RAISE(ABORT, 'forced update failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="forced update failure"):
        templates.update_template(template_id, {"name": "After"})

    assert templates._read_template_json(template_id)["name"] == "Before"


@pytest.mark.parametrize("reader_name", ["catalog", "list"])
def test_template_readers_do_not_read_uncommitted_template_json(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    reader_name: str,
) -> None:
    created = templates.create_template({"name": "Before"})["template"]
    template_id = created["id"]
    original_write_template_json = templates._write_template_json
    published = Event()
    release_update = Event()
    reader_finished = Event()
    writer_errors: list[BaseException] = []
    reader_errors: list[BaseException] = []
    reader_results: list[list[dict[str, object]]] = []

    def publish_then_fail(
        saved_template_id: str,
        template_item: dict[str, object],
    ) -> None:
        original_write_template_json(saved_template_id, template_item)
        published.set()
        if not release_update.wait(timeout=2):
            raise TimeoutError("test did not release the update")
        raise OSError("forced failure after publication")

    def update_template() -> None:
        try:
            templates.update_template(template_id, {"name": "After"})
        except BaseException as exc:
            writer_errors.append(exc)

    def read_templates() -> None:
        try:
            if reader_name == "catalog":
                reader_results.append(templates.load_template_catalog().templates)
            else:
                reader_results.append(templates.list_templates()["templates"])
        except BaseException as exc:
            reader_errors.append(exc)
        finally:
            reader_finished.set()

    monkeypatch.setattr(templates, "_write_template_json", publish_then_fail)
    writer = Thread(target=update_template)
    writer.start()
    assert published.wait(timeout=2)

    reader = Thread(target=read_templates)
    reader.start()
    reader_was_blocked = not reader_finished.wait(timeout=0.2)
    release_update.set()
    writer.join(timeout=2)
    reader.join(timeout=2)

    assert reader_was_blocked
    assert not writer.is_alive()
    assert not reader.is_alive()
    assert len(writer_errors) == 1
    assert isinstance(writer_errors[0], OSError)
    assert not reader_errors
    assert reader_results == [[created]]


def test_resume_creation_does_not_read_uncommitted_template_json(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before_typography = {"fontFamily": "plex", "fontSize": 14}
    minimal_preset = get_builtin_template_preset("minimal")
    created = templates.create_template(
        {
            "preset": "minimal",
            "name": "Before",
            "description": "",
            "layout": minimal_preset["layout"],
            "typography": before_typography,
            "settings": minimal_preset["settings"],
        }
    )["template"]
    template_id = created["id"]
    original_write_template_json = templates._write_template_json
    published = Event()
    release_update = Event()
    creator_finished = Event()
    writer_errors: list[BaseException] = []
    creator_errors: list[BaseException] = []
    creator_results: list[dict[str, object]] = []

    def publish_then_fail(
        saved_template_id: str,
        template_item: dict[str, object],
    ) -> None:
        original_write_template_json(saved_template_id, template_item)
        published.set()
        if not release_update.wait(timeout=2):
            raise TimeoutError("test did not release the update")
        raise OSError("forced failure after publication")

    def update_template() -> None:
        try:
            templates.update_template(
                template_id,
                {
                    "name": "After",
                    "typography": {"fontFamily": "serif", "fontSize": 18},
                },
            )
        except BaseException as exc:
            writer_errors.append(exc)

    def create_resume() -> None:
        try:
            creator_results.append(
                resumes.create_resume(
                    {
                        "documentLocale": "en",
                        "title": "Concurrent template read",
                        "template": template_id,
                    }
                )["resume"]
            )
        except BaseException as exc:
            creator_errors.append(exc)
        finally:
            creator_finished.set()

    monkeypatch.setattr(templates, "_write_template_json", publish_then_fail)
    writer = Thread(target=update_template)
    writer.start()
    assert published.wait(timeout=2)

    creator = Thread(target=create_resume)
    creator.start()
    creator_was_blocked = not creator_finished.wait(timeout=0.2)
    release_update.set()
    writer.join(timeout=2)
    creator.join(timeout=2)

    assert creator_was_blocked
    assert not writer.is_alive()
    assert not creator.is_alive()
    assert len(writer_errors) == 1
    assert isinstance(writer_errors[0], OSError)
    assert not creator_errors
    assert creator_results[0]["typography"] == before_typography


def test_update_does_not_restore_json_after_commit_succeeds(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = templates.create_template({"name": "Before"})["template"]
    template_id = created["id"]

    with monkeypatch.context() as commit_failure:
        commit_failure.setattr(
            templates,
            "connect",
            lambda: _CommitThenRaiseConnection(connect()),
        )
        with pytest.raises(
            sqlite3.OperationalError,
            match="forced failure after commit",
        ):
            templates.update_template(template_id, {"name": "After"})

    stored = templates.list_templates()["templates"]
    assert stored[0]["name"] == "After"
    with connect() as conn:
        row = conn.execute(
            "SELECT name FROM templates WHERE id = ?",
            (template_id,),
        ).fetchone()
    assert row is not None
    assert row["name"] == "After"


def test_temp_cleanup_failure_does_not_mask_publish_failure(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = templates.create_template({"name": "Before"})["template"]
    template_id = created["id"]
    original_replace = os.replace
    original_unlink = Path.unlink
    replace_calls = 0
    cleanup_failed = False

    def fail_first_replace(source: Path, destination: Path) -> None:
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls == 1:
            raise OSError("forced publish failure")
        original_replace(source, destination)

    def fail_first_temp_cleanup(
        path: Path,
        *,
        missing_ok: bool = False,
    ) -> None:
        nonlocal cleanup_failed
        original_unlink(path, missing_ok=missing_ok)
        if path.name.endswith(".tmp") and not cleanup_failed:
            cleanup_failed = True
            raise OSError("forced cleanup failure")

    monkeypatch.setattr(os, "replace", fail_first_replace)
    monkeypatch.setattr(Path, "unlink", fail_first_temp_cleanup)

    with pytest.raises(OSError, match="forced publish failure"):
        templates.update_template(template_id, {"name": "After"})

    assert templates.list_templates()["templates"] == [created]


def test_restore_and_delete_recheck_template_state_under_the_same_lock(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = templates.create_template({"name": "Private"})["template"]
    template_id = created["id"]
    templates.trash_template(template_id)
    original_require_template = templates._require_custom_template_row
    restore_row_loaded = Event()
    release_restore = Event()
    delete_finished = Event()
    restore_results: list[dict[str, object]] = []
    restore_errors: list[BaseException] = []
    delete_errors: list[BaseException] = []

    def pause_restore_after_reading_row(
        conn: sqlite3.Connection,
        requested_template_id: str,
        *,
        include_deleted: bool = False,
    ) -> sqlite3.Row:
        row = original_require_template(
            conn,
            requested_template_id,
            include_deleted=include_deleted,
        )
        if current_thread().name == "restore-template":
            restore_row_loaded.set()
            if not release_restore.wait(timeout=2):
                raise TimeoutError("test did not release restore")
        return row

    def restore() -> None:
        try:
            restore_results.append(templates.restore_template(template_id))
        except BaseException as exc:
            restore_errors.append(exc)

    def delete() -> None:
        try:
            templates.delete_template_forever(template_id)
        except BaseException as exc:
            delete_errors.append(exc)
        finally:
            delete_finished.set()

    monkeypatch.setattr(
        templates,
        "_require_custom_template_row",
        pause_restore_after_reading_row,
    )
    restore_thread = Thread(target=restore, name="restore-template")
    restore_thread.start()
    assert restore_row_loaded.wait(timeout=2)

    delete_thread = Thread(target=delete, name="delete-template")
    delete_thread.start()
    delete_was_blocked = not delete_finished.wait(timeout=0.2)
    release_restore.set()
    restore_thread.join(timeout=2)
    delete_thread.join(timeout=2)

    assert delete_was_blocked
    assert not restore_thread.is_alive()
    assert not delete_thread.is_alive()
    assert not restore_errors
    assert restore_results == [{"template": created}]
    assert len(delete_errors) == 1
    assert isinstance(delete_errors[0], HTTPException)
    assert delete_errors[0].status_code == 409
    assert templates.list_templates()["templates"] == [created]


def test_failed_template_file_deletion_keeps_the_database_reference(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = templates.create_template({"name": "Private"})["template"]
    template_id = created["id"]
    templates.trash_template(template_id)

    def reject_file_deletion(*args: object, **kwargs: object) -> None:
        raise PermissionError("forced file deletion failure")

    monkeypatch.setattr(shutil, "rmtree", reject_file_deletion)

    with pytest.raises(PermissionError, match="forced file deletion failure"):
        templates.delete_template_forever(template_id)

    with connect() as conn:
        row = conn.execute(
            "SELECT deleted FROM templates WHERE id = ?",
            (template_id,),
        ).fetchone()

    assert row is not None
    assert row["deleted"] == 1


def test_partially_failed_empty_template_trash_is_retryable(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template_ids = [
        templates.create_template({"name": name})["template"]["id"]
        for name in ("First private", "Second private")
    ]
    for template_id in template_ids:
        templates.trash_template(template_id)
    original_rmtree = shutil.rmtree
    deletion_calls = 0
    completed_path: Path | None = None

    def delete_first_then_fail(path: Path) -> None:
        nonlocal completed_path, deletion_calls
        deletion_calls += 1
        if deletion_calls == 2:
            raise PermissionError("forced file deletion failure")
        original_rmtree(path)
        completed_path = path

    with monkeypatch.context() as partial_failure:
        partial_failure.setattr(
            shutil,
            "rmtree",
            delete_first_then_fail,
        )
        with pytest.raises(PermissionError, match="forced file deletion failure"):
            templates.empty_template_trash()

    with connect() as conn:
        rows = conn.execute(
            "SELECT id FROM templates WHERE deleted = 1 ORDER BY id",
        ).fetchall()

    assert completed_path is not None
    completed_id = completed_path.name
    pending_id = next(item for item in template_ids if item != completed_id)
    assert [row["id"] for row in rows] == [pending_id]
    assert not _stored_template_path(completed_id).exists()
    assert _stored_template_path(pending_id).exists()

    assert templates.empty_template_trash() == {"deletedCount": 1}
    assert templates.list_templates("deleted") == {"templates": []}
    assert not any(_stored_template_path(item).exists() for item in template_ids)
