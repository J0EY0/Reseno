import sqlite3
from collections.abc import Callable
from threading import Event, Thread, current_thread
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.services import resumes


@pytest.mark.parametrize("reader", ["detail", "list", "version", "duplicate"])
def test_resume_reader_retains_its_snapshot_during_autosave(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    reader: str,
) -> None:
    created = resumes.create_resume({"documentLocale": "en"})
    resume_id = created["resume"]["id"]
    first = resumes.save_resume(
        resume_id,
        {**created["resume"], "title": "Autosave A"},
        save_mode="autosave",
    )
    readers: dict[str, Callable[[], Any]] = {
        "detail": lambda: resumes.load_resume(resume_id),
        "list": lambda: resumes.list_resumes().model_dump(mode="json", by_alias=True),
        "version": lambda: resumes.load_resume_version(resume_id, first["versionId"]),
        "duplicate": lambda: resumes.duplicate_resume(resume_id),
    }
    read_started = Event()
    release_read = Event()
    write_started = Event()
    write_finished = Event()
    results: dict[str, Any] = {}
    errors: list[BaseException] = []
    original_read = resumes._read_resume_bytes

    def paused_read(saved_resume_id: str, version_id: int) -> bytes:
        if current_thread().name == "resume-reader":
            read_started.set()
            if not release_read.wait(timeout=5):
                raise TimeoutError("Resume reader was not released")
        return original_read(saved_resume_id, version_id)

    def read() -> None:
        try:
            results["read"] = readers[reader]()
        except BaseException as exc:
            errors.append(exc)

    def write() -> None:
        write_started.set()
        try:
            results["write"] = resumes.save_resume(
                resume_id,
                {**first["resume"], "title": "Autosave B"},
                save_mode="autosave",
            )
        except BaseException as exc:
            errors.append(exc)
        finally:
            write_finished.set()

    monkeypatch.setattr(resumes, "_read_resume_bytes", paused_read)
    reader_thread = Thread(target=read, name="resume-reader")
    writer_thread = Thread(target=write, name="resume-writer")
    reader_thread.start()
    try:
        assert read_started.wait(timeout=5)
        writer_thread.start()
        assert write_started.wait(timeout=5)
        writer_waited_for_reader = not write_finished.wait(timeout=0.2)
    finally:
        release_read.set()
        reader_thread.join(timeout=5)
        if writer_thread.ident is not None:
            writer_thread.join(timeout=5)

    assert not reader_thread.is_alive()
    assert not writer_thread.is_alive()
    assert not errors
    assert writer_waited_for_reader
    read_item = (
        results["read"]["resumes"][0]
        if reader == "list"
        else results["read"]["resume"]
    )
    assert read_item["title"].startswith("Autosave A")
    assert results["write"]["resume"]["title"] == "Autosave B"
    assert resumes.load_resume(resume_id)["resume"]["title"] == "Autosave B"


def test_resume_commands_close_connections_on_success_and_failure(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connections: list[sqlite3.Connection] = []
    original_connect = resumes.connect

    def tracked_connect() -> sqlite3.Connection:
        conn = original_connect()
        connections.append(conn)
        return conn

    monkeypatch.setattr(resumes, "connect", tracked_connect)
    try:
        created = resumes.create_resume({"documentLocale": "en"})
        resume_id = created["resume"]["id"]
        resumes.list_resumes()
        resumes.load_resume(resume_id)
        resumes.list_resume_versions(resume_id)
        resumes.load_resume_version(resume_id, created["versionId"])
        resumes.save_resume(resume_id, {**created["resume"], "title": "Updated"})
        resumes.duplicate_resume(resume_id)
        resumes.trash_resume(resume_id)
        resumes.restore_resume(resume_id)
        resumes.trash_resume(resume_id)
        resumes.delete_resume_forever(resume_id)
        resumes.empty_resume_trash()
        with pytest.raises(HTTPException):
            resumes.load_resume(resume_id)

        for conn in connections:
            with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
                conn.execute("SELECT 1")
    finally:
        for conn in connections:
            conn.close()
