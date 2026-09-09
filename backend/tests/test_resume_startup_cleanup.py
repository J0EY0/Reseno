import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from threading import Event, Thread

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.connection import connect
from app.services import resumes

_CRASH_PROGRAM = """
import json
import os
import sys
from contextlib import closing
from pathlib import Path
from unittest.mock import AsyncMock
from app.services import model_metadata, resumes
model_metadata.MODEL_METADATA_SNAPSHOT_PATH = (
    Path(os.environ['APP_DATA_DIR']) / 'absent.json'
)
model_metadata._fetch_catalog = AsyncMock(return_value={})
model_metadata._fetch_reasoning_catalog = AsyncMock(return_value={})
from app.main import create_app
from fastapi.testclient import TestClient
payload = json.load(sys.stdin)
with TestClient(create_app()):
    current = payload['current']
    resume_id = current['resume']['id']
    mode = payload['mode']
    candidate = {**current['resume'], 'title': 'Crash candidate'}
    if mode in ('save', 'create', 'agent_apply'):
        write = resumes._write_resume_json
        def crash_after_write(*args):
            write(*args)
            os._exit(71)
        resumes._write_resume_json = crash_after_write
    elif mode == 'temporary':
        replace = Path.replace
        def crash_before_replace(path, target):
            if path.name.endswith('.json.tmp') and path.parent.name == 'versions':
                os._exit(71)
            return replace(path, target)
        Path.replace = crash_before_replace
    elif mode == 'after_commit':
        resumes.cleanup_resume_version_files = lambda _: os._exit(71)
    if mode == 'create':
        resumes.create_resume({'documentLocale': 'en'})
    elif mode == 'agent_apply':
        from app.db.connection import connect
        from app.services import agent_sessions
        from tests.test_agent_turn_protocol import (
            _committed_review_item_id, _persist_committed_draft,
        )
        message_id = 'crash-test-draft'
        with closing(connect()) as conn:
            _persist_committed_draft(conn, resume_id=resume_id, message_id=message_id)
            revision = agent_sessions.load_agent_session(conn, resume_id).revision
            document = {
                **current['resume']['resume'],
                'basic': {
                    **current['resume']['resume']['basic'], 'headline': 'Crash edit',
                },
            }
            agent_sessions.apply_agent_draft_decision(
                conn, resume_id, message_id=message_id,
                review_item_ids=[_committed_review_item_id(message_id)],
                resume=document, revision=revision,
                expected_version_id=current['versionId'],
            )
    else:
        resumes.save_resume(resume_id, candidate, save_mode='autosave')
raise AssertionError('The requested crash point was not reached.')
"""


def _referenced_files() -> dict[Path, bytes]:
    with closing(connect()) as conn:
        rows = conn.execute(
            "SELECT resume_id, version_id FROM resume_versions "
            "UNION SELECT id, current_version_id FROM resumes"
        ).fetchall()
    return {
        path: path.read_bytes()
        for row in rows
        if (path := resumes._resume_version_path(row[0], row[1])).is_file()
    }


@pytest.mark.parametrize(
    "mode", ["save", "create", "temporary", "after_commit", "agent_apply"]
)
def test_startup_removes_crash_files_and_preserves_committed_versions(
    uninitialized_client: TestClient,
    mode: str,
) -> None:
    from app.main import create_app

    current = resumes.create_resume({"documentLocale": "en"})
    resume_id = current["resume"]["id"]
    if mode == "after_commit":
        current = resumes.save_resume(
            resume_id, {**current["resume"], "title": "Autosave"}, save_mode="autosave"
        )
    committed = _referenced_files()
    uninitialized_client.__exit__(None, None, None)

    result = subprocess.run(
        [sys.executable, "-c", _CRASH_PROGRAM],
        input=json.dumps({"mode": mode, "current": current}),
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 71, result.stderr
    referenced_after_crash = _referenced_files()
    root = get_settings().storage_dir / "resumes"
    leftovers = set(root.glob("*/versions/*")) - set(referenced_after_crash)
    assert len(leftovers) == 1
    for path, content in committed.items():
        assert path.read_bytes() == content

    with TestClient(create_app()):
        assert all(not path.exists() for path in leftovers)
        assert _referenced_files() == referenced_after_crash
        actual = resumes.load_resume(resume_id)
        if mode == "after_commit":
            assert actual["resume"]["title"] == "Crash candidate"
            assert int(actual["versionId"]) == int(current["versionId"]) + 1
        else:
            assert actual == current
        if mode == "agent_apply":
            from app.services import agent_sessions

            with closing(connect()) as conn:
                session = agent_sessions.load_agent_session(conn, resume_id)
            assert (
                session.messages[-1].response.draft.review_items[0].status == "pending"
            )


def test_startup_cleanup_preserves_references_unknown_files_and_symlinks(
    uninitialized_client: TestClient,
    tmp_path: Path,
) -> None:
    current = resumes.create_resume({"documentLocale": "en"})
    resume_id = current["resume"]["id"]
    current = resumes.save_resume(
        resume_id, {**current["resume"], "title": "Checkpoint"}
    )
    current = resumes.save_resume(
        resume_id, {**current["resume"], "title": "Autosave"}, save_mode="autosave"
    )
    deleted = resumes.create_resume({"documentLocale": "en"})
    resumes.trash_resume(deleted["resume"]["id"])
    pointer_only = resumes.create_resume({"documentLocale": "en"})
    with closing(connect()) as conn:
        conn.execute(
            "DELETE FROM resume_versions WHERE resume_id = ?",
            (pointer_only["resume"]["id"],),
        )
    referenced = _referenced_files()
    versions = resumes._resume_version_path(resume_id, 1).parent
    orphan = resumes._resume_version_path(resume_id, 4)
    resumes._write_resume_json(resume_id, 4, current["resume"])
    temporary = versions / "5.json.tmp"
    temporary.write_text('{"incomplete":')
    referenced_temporary = versions / "1.json.tmp"
    referenced_temporary.write_text("incomplete")
    unknown = [
        versions / name
        for name in (
            "0.json",
            "01.json",
            "-1.json",
            "7.JSON",
            "notes.json",
            "notes.tmp",
        )
    ]
    storage = get_settings().storage_dir
    unknown.append(storage / "agent-attachments" / resume_id / "attachment.txt")
    unknown.append(storage / "resumes" / "invalid-id" / "versions" / "1.json")
    for path in unknown:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"preserve unknown content")
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "1.json"
    target.write_bytes(b"preserve symlink target")
    symlink_file = versions / "9.json"
    symlink_file.symlink_to(target)
    symlink_resume = storage / "resumes" / "LinkedResume"
    symlink_resume.symlink_to(outside, target_is_directory=True)
    linked_versions = storage / "resumes" / "LinkedVersions" / "versions"
    linked_versions.parent.mkdir()
    linked_versions.symlink_to(outside, target_is_directory=True)
    directory = versions / "8.json"
    directory.mkdir()

    resumes.recover_unreferenced_resume_version_files()

    assert not orphan.exists()
    assert not temporary.exists()
    assert not referenced_temporary.exists()
    assert _referenced_files() == referenced
    assert all(path.read_bytes() == b"preserve unknown content" for path in unknown)
    assert target.read_bytes() == b"preserve symlink target"
    assert all(
        path.is_symlink() for path in (symlink_file, symlink_resume, linked_versions)
    )
    assert directory.is_dir()


def test_startup_cleanup_waits_for_inflight_version_commit(
    uninitialized_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = resumes.create_resume({"documentLocale": "en"})
    resume_id = current["resume"]["id"]
    opened = Event()
    finished = Event()
    errors: list[BaseException] = []
    original_connect = resumes.connect

    def cleanup_connect() -> sqlite3.Connection:
        conn = original_connect()
        opened.set()
        return conn

    def cleanup() -> None:
        try:
            resumes.recover_unreferenced_resume_version_files()
        except BaseException as exc:
            errors.append(exc)
        finally:
            finished.set()

    with closing(connect()) as writer, writer:
        writer.execute("BEGIN IMMEDIATE")
        result = resumes.save_resume_in_transaction(
            writer,
            resume_id,
            {**current["resume"], "title": "In flight"},
            save_mode="checkpoint",
        )
        monkeypatch.setattr(resumes, "connect", cleanup_connect)
        worker = Thread(target=cleanup)
        worker.start()
        try:
            assert opened.wait(timeout=5)
            assert not finished.wait(timeout=0.2)
        finally:
            writer.commit()
            worker.join(timeout=5)

    assert finished.is_set()
    assert errors == []
    assert resumes.load_resume(resume_id) == result.detail
