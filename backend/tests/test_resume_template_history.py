import sqlite3
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from app.db.connection import connect
from app.services import resumes, templates
from tests.template_fixtures import portable_template


@pytest.mark.parametrize("document_locale", ["en", "zh"])
@pytest.mark.parametrize("permanent", [False, True])
def test_historical_template_reference_remains_editable_without_rewriting_snapshot(
    client: TestClient, permanent: bool, document_locale: str
) -> None:
    template = templates.create_template(portable_template())["template"]
    original = resumes.create_resume(
        {
            "documentLocale": document_locale,
            "template": template["id"],
            "typography": {"fontFamily": "plex", "fontSize": 14},
            "templateSettings": {"headingColor": "#123456"},
        }
    )
    resume_id = original["resume"]["id"]
    original_path = resumes._resume_version_path(resume_id, int(original["versionId"]))
    original_bytes = original_path.read_bytes()
    templates.save_default_template(document_locale, "academic")
    templates.trash_template(template["id"])
    if permanent:
        templates.delete_template_forever(template["id"])
    historical = client.get(
        f"/api/resumes/{resume_id}/versions/{original['versionId']}"
    ).json()["data"]
    assert historical["versionId"] == original["versionId"]
    assert historical["savedAt"] == original["savedAt"]
    assert historical["resume"] == {**original["resume"], "template": "academic"}
    assert original_path.read_bytes() == original_bytes
    payload = {
        key: historical["resume"][key]
        for key in (
            "title",
            "documentLocale",
            "resume",
            "jobBrief",
            "typography",
            "template",
            "templateSettings",
        )
    }
    payload["title"] = "Edited historical version"
    response = client.put(f"/api/resumes/{resume_id}", json=payload)
    assert response.status_code == 200
    assert response.json()["data"]["resume"]["resume"] == original["resume"]["resume"]
    assert original_path.read_bytes() == original_bytes
    invalid = client.put(
        f"/api/resumes/{resume_id}",
        json={**payload, "template": "template-never-existed"},
    )
    assert invalid.status_code == 404
    assert invalid.json()["message"] == "TEMPLATE_NOT_FOUND"


@pytest.mark.parametrize("competing_save", [False, True])
def test_template_rebind_cleanup_respects_committed_versions_after_sqlite_rollback(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, competing_save: bool
) -> None:
    template = templates.create_template(portable_template())["template"]
    original = resumes.create_resume(
        {"documentLocale": "en", "template": template["id"]}
    )
    resume_id = original["resume"]["id"]
    with closing(connect()) as conn:
        page_cap = conn.execute("PRAGMA page_count").fetchone()[0] + 1

    def capped_connection():
        conn = connect()
        conn.execute(f"PRAGMA max_page_count={page_cap}")
        return conn

    latest = original
    with monkeypatch.context() as full:
        full.setattr(resumes, "connect", capped_connection)
        for index in range(1000):
            try:
                latest = resumes.save_resume(
                    resume_id, {**original["resume"], "title": f"History {index:04}"}
                )
            except sqlite3.OperationalError as exc:
                assert exc.sqlite_errorcode == sqlite3.SQLITE_FULL
                break
        else:
            pytest.fail("The test database did not reach its page limit.")

    original_save = resumes._save_resume_item
    successful = []
    failed_versions = []

    def save_after_rollback(conn, **kwargs):
        try:
            return original_save(conn, **kwargs)
        except sqlite3.OperationalError as exc:
            assert exc.sqlite_errorcode == sqlite3.SQLITE_FULL
            assert not conn.in_transaction
            failed_versions.append(int(latest["versionId"]) + 1)
            if competing_save:
                with monkeypatch.context() as competitor:
                    competitor.setattr(resumes, "_save_resume_item", original_save)
                    successful.append(
                        resumes.save_resume(
                            resume_id,
                            {**latest["resume"], "title": "Committed competing save"},
                        )
                    )
            raise

    with monkeypatch.context() as failing_rebind:
        failing_rebind.setattr(templates, "connect", capped_connection)
        failing_rebind.setattr(resumes, "_save_resume_item", save_after_rollback)
        with pytest.raises(sqlite3.OperationalError, match="full"):
            templates.trash_template(template["id"])

    assert len(failed_versions) == 1
    current = resumes.load_resume(resume_id)
    assert current == (successful[0] if competing_save else latest)
    assert (
        resumes._resume_version_path(resume_id, failed_versions[0]).exists()
        == competing_save
    )
    with closing(connect()) as conn:
        assert templates.is_visible_template(conn, template["id"])
