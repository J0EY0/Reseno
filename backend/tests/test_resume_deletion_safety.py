import pytest
from fastapi.testclient import TestClient

from app.db.connection import connect
from app.services import resumes
from app.services.agent.attachments import (
    load_agent_attachment,
    store_resume_agent_attachment,
)


def _create_deleted_resume(client: TestClient, title: str) -> str:
    resume_id = client.post(
        "/api/resumes",
        json={"documentLocale": "en", "title": title},
    ).json()["data"]["resume"]["id"]
    response = client.post(f"/api/resumes/{resume_id}/trash")
    assert response.status_code == 200
    return resume_id


def _reject_file_deletion(
    path: object,
    *args: object,
    **kwargs: object,
) -> None:
    raise PermissionError("forced file deletion failure")


def _create_running_turn(resume_id: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO agent_sessions (id, resume_id, locale, title)
            VALUES (?, ?, 'en', 'Running session')
            """,
            (resume_id, resume_id),
        )
        conn.execute(
            """
            INSERT INTO agent_turn_executions (
                run_id,
                session_id,
                turn_id,
                status,
                started_at,
                updated_at
            )
            VALUES (?, ?, ?, 'running', ?, ?)
            """,
            (
                f"run-{resume_id}",
                resume_id,
                f"turn-{resume_id}",
                "2026-08-10T00:00:00Z",
                "2026-08-10T00:00:00Z",
            ),
        )


def test_failed_resume_file_deletion_keeps_resume_and_session_rows(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resume_id = _create_deleted_resume(client, "Private resume")
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO agent_sessions (id, resume_id, locale, title)
            VALUES (?, ?, 'en', 'Private session')
            """,
            (resume_id, resume_id),
        )

    monkeypatch.setattr(
        resumes,
        "_delete_resume_storage",
        _reject_file_deletion,
    )

    with pytest.raises(PermissionError, match="forced file deletion failure"):
        resumes.delete_resume_forever(resume_id)

    with connect() as conn:
        resume_row = conn.execute(
            "SELECT deleted FROM resumes WHERE id = ?",
            (resume_id,),
        ).fetchone()
        session_row = conn.execute(
            "SELECT id FROM agent_sessions WHERE id = ?",
            (resume_id,),
        ).fetchone()

    assert resume_row is not None
    assert resume_row["deleted"] == 1
    assert session_row is not None


def test_failed_empty_resume_trash_keeps_all_database_references(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resume_ids = [
        _create_deleted_resume(client, title)
        for title in ("First private", "Second private")
    ]
    monkeypatch.setattr(
        resumes,
        "_delete_resume_storage",
        _reject_file_deletion,
    )

    with pytest.raises(PermissionError, match="forced file deletion failure"):
        resumes.empty_resume_trash()

    with connect() as conn:
        rows = conn.execute(
            "SELECT id FROM resumes WHERE deleted = 1 ORDER BY id",
        ).fetchall()

    assert [row["id"] for row in rows] == sorted(resume_ids)


def test_partially_failed_empty_resume_trash_commits_completed_items(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resume_ids = [
        _create_deleted_resume(client, title)
        for title in ("First private", "Second private")
    ]
    original_delete_storage = resumes._delete_resume_storage
    deleted_ids: list[str] = []

    def delete_first_then_fail(resume_id: str) -> None:
        if deleted_ids:
            raise PermissionError("forced file deletion failure")
        original_delete_storage(resume_id)
        deleted_ids.append(resume_id)

    monkeypatch.setattr(
        resumes,
        "_delete_resume_storage",
        delete_first_then_fail,
    )

    with pytest.raises(PermissionError, match="forced file deletion failure"):
        resumes.empty_resume_trash()

    completed_id = deleted_ids[0]
    pending_id = next(item for item in resume_ids if item != completed_id)
    with connect() as conn:
        remaining_ids = {
            row["id"]
            for row in conn.execute(
                "SELECT id FROM resumes WHERE deleted = 1",
            ).fetchall()
        }

    assert remaining_ids == {pending_id}
    assert not resumes._resume_storage_dir(completed_id).exists()
    assert resumes._resume_storage_dir(pending_id).is_dir()


def test_running_agent_turn_blocks_permanent_resume_deletion(
    client: TestClient,
) -> None:
    resume_id = client.post(
        "/api/resumes",
        json={"documentLocale": "en", "title": "Running private resume"},
    ).json()["data"]["resume"]["id"]
    attachment = store_resume_agent_attachment(
        resume_id=resume_id,
        filename="private.txt",
        media_type="text/plain",
        payload=b"private",
    )
    _create_running_turn(resume_id)
    response = client.post(f"/api/resumes/{resume_id}/trash")
    assert response.status_code == 200

    response = client.delete(f"/api/resumes/{resume_id}")

    assert response.status_code == 409
    assert response.json()["message"] == "AGENT_RUN_CONFLICT"
    assert resumes._resume_storage_dir(resume_id).is_dir()
    assert load_agent_attachment(resume_id, attachment.id) is not None
    with connect() as conn:
        assert conn.execute(
            "SELECT 1 FROM resumes WHERE id = ?",
            (resume_id,),
        ).fetchone()
        assert conn.execute(
            "SELECT 1 FROM agent_turn_executions WHERE session_id = ?",
            (resume_id,),
        ).fetchone()


def test_running_agent_turn_blocks_empty_trash_before_any_file_deletion(
    client: TestClient,
) -> None:
    resume_ids = [
        client.post(
            "/api/resumes",
            json={"documentLocale": "en", "title": title},
        ).json()["data"]["resume"]["id"]
        for title in ("First private resume", "Running private resume")
    ]
    attachments = [
        store_resume_agent_attachment(
            resume_id=resume_id,
            filename=f"private-{index}.txt",
            media_type="text/plain",
            payload=b"private",
        )
        for index, resume_id in enumerate(resume_ids)
    ]
    _create_running_turn(resume_ids[1])
    for resume_id in resume_ids:
        response = client.post(f"/api/resumes/{resume_id}/trash")
        assert response.status_code == 200

    response = client.delete("/api/resumes/trash")

    assert response.status_code == 409
    assert response.json()["message"] == "AGENT_RUN_CONFLICT"
    for resume_id, attachment in zip(resume_ids, attachments, strict=True):
        assert resumes._resume_storage_dir(resume_id).is_dir()
        assert load_agent_attachment(resume_id, attachment.id) is not None
    with connect() as conn:
        remaining_ids = {
            row["id"]
            for row in conn.execute(
                "SELECT id FROM resumes WHERE deleted = 1",
            ).fetchall()
        }
    assert remaining_ids == set(resume_ids)
