import sqlite3
from contextlib import closing
from threading import Event, Thread
from types import TracebackType
from typing import Any, Self

import pytest
from fastapi.testclient import TestClient

from app.db.connection import connect
from app.services import agent_sessions, resumes
from tests.test_agent_turn_protocol import (
    _committed_review_item_id,
    _persist_committed_draft,
)


class _FailingCommitConnection:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

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

    def commit(self) -> None:
        raise sqlite3.OperationalError("injected resume commit failure")


@pytest.mark.parametrize("command", ["save", "agent_apply"])
@pytest.mark.parametrize("competing_save", [False, True])
def test_failed_resume_commit_cleans_only_unreferenced_files(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    competing_save: bool,
) -> None:
    created = resumes.create_resume({"documentLocale": "en"})
    resume_id = created["resume"]["id"]
    candidate = {**created["resume"], "title": "Failed candidate"}
    candidate["resume"] = {
        **created["resume"]["resume"],
        "basic": {**created["resume"]["resume"]["basic"], "headline": "Candidate"},
    }
    message_id = "assistant-cleanup-test"
    original_connect = resumes.connect
    original_cleanup = resumes.cleanup_resume_version_files
    cleanup_calls: list[tuple[resumes.ResumeVersionFile, ...]] = []
    competing_results: list[dict[str, Any]] = []

    def delayed_cleanup(files: Any) -> None:
        cleanup_calls.append(tuple(files))
        if competing_save:
            competing_results.append(
                resumes.save_resume(
                    resume_id,
                    {**created["resume"], "title": "Successful competing save"},
                ),
            )
        original_cleanup(cleanup_calls[-1])

    with closing(connect()) as conn:
        if command == "agent_apply":
            _persist_committed_draft(conn, resume_id=resume_id, message_id=message_id)
            revision = agent_sessions.load_agent_session(conn, resume_id).revision
            monkeypatch.setattr(
                agent_sessions, "cleanup_resume_version_files", delayed_cleanup
            )
        else:
            failed_connection_returned = False

            def failing_connect() -> Any:
                nonlocal failed_connection_returned
                opened = original_connect()
                if not failed_connection_returned:
                    failed_connection_returned = True
                    return _FailingCommitConnection(opened)
                return opened

            monkeypatch.setattr(resumes, "connect", failing_connect)
            monkeypatch.setattr(
                resumes, "cleanup_resume_version_files", delayed_cleanup
            )

        with pytest.raises(sqlite3.OperationalError, match="injected resume commit"):
            if command == "agent_apply":
                agent_sessions.apply_agent_draft_decision(
                    _FailingCommitConnection(conn),
                    resume_id,
                    message_id=message_id,
                    review_item_ids=[_committed_review_item_id(message_id)],
                    resume=candidate["resume"],
                    revision=revision,
                    expected_version_id=created["versionId"],
                )
            else:
                resumes.save_resume(resume_id, candidate)

        if command == "agent_apply":
            session = agent_sessions.load_agent_session(conn, resume_id)
            assert session.messages[-1].response.draft.review_items[0].status == (
                "pending"
            )

    expected_file = (resume_id, int(created["versionId"]) + 1)
    assert cleanup_calls == [(expected_file,)]
    actual = resumes.load_resume(resume_id)
    if competing_save:
        assert actual == competing_results[0]
        assert actual["resume"]["title"] == "Successful competing save"
        assert resumes._resume_version_path(*expected_file).is_file()
    else:
        assert actual == created
        assert not resumes._resume_version_path(*expected_file).exists()


def test_version_cleanup_holds_write_lock_until_unlink_finishes(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = resumes.create_resume({"documentLocale": "en"})
    resume_id = created["resume"]["id"]
    orphan_version = int(created["versionId"]) + 1
    resumes._write_resume_json(resume_id, orphan_version, created["resume"])
    unlink_started = Event()
    release_unlink = Event()
    write_started = Event()
    write_finished = Event()
    errors: list[BaseException] = []
    original_delete = resumes._delete_resume_json

    def paused_delete(saved_resume_id: str, version_id: int) -> None:
        unlink_started.set()
        if not release_unlink.wait(timeout=5):
            raise TimeoutError("Version cleanup was not released")
        original_delete(saved_resume_id, version_id)

    def cleanup() -> None:
        try:
            resumes.cleanup_resume_version_files(((resume_id, orphan_version),))
        except BaseException as exc:
            errors.append(exc)

    def save() -> None:
        write_started.set()
        try:
            resumes.save_resume(
                resume_id, {**created["resume"], "title": "Saved after cleanup"}
            )
        except BaseException as exc:
            errors.append(exc)
        finally:
            write_finished.set()

    monkeypatch.setattr(resumes, "_delete_resume_json", paused_delete)
    cleanup_thread = Thread(target=cleanup)
    save_thread = Thread(target=save)
    cleanup_thread.start()
    try:
        assert unlink_started.wait(timeout=5)
        save_thread.start()
        assert write_started.wait(timeout=5)
        writer_waited = not write_finished.wait(timeout=0.2)
    finally:
        release_unlink.set()
        cleanup_thread.join(timeout=5)
        if save_thread.ident is not None:
            save_thread.join(timeout=5)

    assert not cleanup_thread.is_alive()
    assert not save_thread.is_alive()
    assert not errors
    assert writer_waited
    assert resumes.load_resume(resume_id)["resume"]["title"] == "Saved after cleanup"


def test_cleanup_preserves_current_and_historical_versions(
    client: TestClient,
) -> None:
    original = resumes.create_resume({"documentLocale": "en"})
    resume_id = original["resume"]["id"]
    current = resumes.save_resume(
        resume_id, {**original["resume"], "title": "Current checkpoint"}
    )
    resumes.cleanup_resume_version_files(
        (
            (resume_id, int(original["versionId"])),
            (resume_id, int(current["versionId"])),
        )
    )
    assert resumes.load_resume(resume_id) == current
    assert resumes.load_resume_version(resume_id, original["versionId"]) == original


def test_cleanup_database_failure_keeps_unreferenced_file_retryable(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = resumes.create_resume({"documentLocale": "en"})
    resume_id = created["resume"]["id"]
    orphan_version = int(created["versionId"]) + 1
    resumes._write_resume_json(resume_id, orphan_version, created["resume"])
    orphan_path = resumes._resume_version_path(resume_id, orphan_version)

    def unavailable_connection() -> sqlite3.Connection:
        raise sqlite3.OperationalError("cleanup database unavailable")

    with monkeypatch.context() as unavailable:
        unavailable.setattr(resumes, "connect", unavailable_connection)
        resumes.cleanup_resume_version_files(((resume_id, orphan_version),))

    assert orphan_path.is_file()
    assert resumes.load_resume(resume_id) == created
    resumes.cleanup_resume_version_files(((resume_id, orphan_version),))
    assert not orphan_path.exists()
