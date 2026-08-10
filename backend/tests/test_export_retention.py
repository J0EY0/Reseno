import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.schemas.exports import (
    ExportResumeImagesRequest,
    ExportResumePdfRequest,
    ExportResumePdfResponse,
)
from app.services.pdf import ResumeImageExportResult


def _create_resume(client: TestClient) -> str:
    response = client.post(
        "/api/resumes",
        json={
            "title": "Export retention",
            "resume": {
                "schemaVersion": 2,
                "basic": {
                    "name": "Export retention",
                    "headline": "",
                    "phone": "",
                    "email": "",
                    "location": "",
                    "avatar": "",
                    "summary": "",
                    "customFields": [],
                },
                "sections": [],
            },
            "template": "minimal",
        },
    )
    return str(response.json()["data"]["resume"]["id"])


def test_export_response_contract_requires_expiry() -> None:
    schema = ExportResumePdfResponse.model_json_schema(by_alias=True)

    assert "expiresAt" in schema["required"]


def test_pdf_export_returns_one_hour_expiry(
    client: TestClient,
    monkeypatch,
) -> None:
    def write_test_pdf(
        export_id: str,
        _request: ExportResumePdfRequest,
        **_: object,
    ) -> Path:
        from app.services.pdf import get_export_path

        export_path = get_export_path(export_id)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_bytes(b"%PDF-1.4\n")
        return export_path

    monkeypatch.setattr("app.routers.exports.write_resume_pdf", write_test_pdf)
    resume_id = _create_resume(client)
    before_generation = datetime.now(UTC)

    response = client.post(
        "/api/exports/resume-pdf",
        json={
            "resumeId": resume_id,
            "locale": "en",
            "fileNameSeed": "resume",
            "savedAt": "2026-08-09T00:00:00.000Z",
        },
    )
    after_generation = datetime.now(UTC)

    assert response.status_code == 200
    expires_at = datetime.fromisoformat(
        response.json()["data"]["expiresAt"].replace("Z", "+00:00")
    )
    assert before_generation + timedelta(hours=1) <= expires_at
    assert expires_at <= after_generation + timedelta(hours=1)


@pytest.mark.parametrize("is_archive", [False, True])
def test_image_export_returns_one_hour_expiry(
    client: TestClient,
    monkeypatch,
    is_archive: bool,
) -> None:
    from app.services.pdf import get_image_export_path

    def write_test_image(
        export_id: str,
        _request: ExportResumeImagesRequest,
        **_: object,
    ) -> ResumeImageExportResult:
        export_path = get_image_export_path(export_id, is_archive=is_archive)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_bytes(b"artifact")
        return ResumeImageExportResult(
            path=export_path,
            page_count=2 if is_archive else 1,
            is_archive=is_archive,
        )

    monkeypatch.setattr("app.routers.exports.write_resume_images", write_test_image)
    resume_id = _create_resume(client)
    before_generation = datetime.now(UTC)

    response = client.post(
        "/api/exports/resume-images",
        json={
            "resumeId": resume_id,
            "locale": "en",
            "fileNameSeed": "resume",
            "savedAt": "2026-08-09T00:00:00.000Z",
        },
    )
    after_generation = datetime.now(UTC)

    assert response.status_code == 200
    expires_at = datetime.fromisoformat(
        response.json()["data"]["expiresAt"].replace("Z", "+00:00")
    )
    assert before_generation + timedelta(hours=1) <= expires_at
    assert expires_at <= after_generation + timedelta(hours=1)


def test_startup_removes_only_expired_export_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.config import get_settings
    from app.main import create_app

    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    expired_paths = [
        export_dir / "export-old.pdf",
        export_dir / "export-old.png",
        export_dir / "export-old.zip",
    ]
    fresh_exports = [
        export_dir / "export-fresh.pdf",
        export_dir / "export-fresh.png",
        export_dir / "export-fresh.zip",
    ]
    unrelated_paths = [
        export_dir / "report.pdf",
        export_dir / "export-old.txt",
    ]
    for path in [*expired_paths, *fresh_exports, *unrelated_paths]:
        path.write_bytes(b"artifact")
    expired_at = (datetime.now(UTC) - timedelta(hours=1, seconds=5)).timestamp()
    for path in expired_paths:
        os.utime(path, (expired_at, expired_at))

    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("APP_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("APP_ENV_FILE", str(tmp_path / ".env"))
    monkeypatch.setenv("EXPORT_DIR", str(export_dir))
    get_settings.cache_clear()

    try:
        with TestClient(create_app()):
            pass
    finally:
        get_settings.cache_clear()

    assert all(not path.exists() for path in expired_paths)
    assert all(path.exists() for path in fresh_exports)
    assert all(path.exists() for path in unrelated_paths)


def test_cleanup_skips_unremovable_export_without_aborting(
    client: TestClient,
    monkeypatch,
) -> None:
    from app.config import get_settings
    from app.services.pdf import cleanup_expired_exports

    export_dir = get_settings().export_dir
    export_dir.mkdir(parents=True, exist_ok=True)
    blocked_path = export_dir / "export-blocked.pdf"
    removable_path = export_dir / "export-removable.pdf"
    for path in (blocked_path, removable_path):
        path.write_bytes(b"artifact")
    expired_at = (datetime.now(UTC) - timedelta(hours=1, seconds=5)).timestamp()
    for path in (blocked_path, removable_path):
        os.utime(path, (expired_at, expired_at))
    original_unlink = Path.unlink

    def reject_one_export(path: Path, *, missing_ok: bool = False) -> None:
        if path == blocked_path:
            raise PermissionError("forced cleanup failure")
        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", reject_one_export)

    cleanup_expired_exports()

    assert blocked_path.exists()
    assert not removable_path.exists()


def test_pdf_generation_removes_expired_export_artifacts(
    client: TestClient,
    monkeypatch,
) -> None:
    from app.config import get_settings
    from app.services.pdf import get_export_path

    export_dir = get_settings().export_dir
    export_dir.mkdir(parents=True, exist_ok=True)
    expired_paths = [
        export_dir / "export-old.pdf",
        export_dir / "export-old.png",
        export_dir / "export-old.zip",
    ]
    unrelated_path = export_dir / "keep.pdf"
    for path in [*expired_paths, unrelated_path]:
        path.write_bytes(b"artifact")
    expired_at = (datetime.now(UTC) - timedelta(hours=1, seconds=5)).timestamp()
    for path in expired_paths:
        os.utime(path, (expired_at, expired_at))

    def write_test_pdf(
        export_id: str,
        _request: ExportResumePdfRequest,
        **_: object,
    ) -> Path:
        export_path = get_export_path(export_id)
        export_path.write_bytes(b"%PDF-1.4\n")
        return export_path

    monkeypatch.setattr("app.routers.exports.write_resume_pdf", write_test_pdf)
    resume_id = _create_resume(client)

    response = client.post(
        "/api/exports/resume-pdf",
        json={
            "resumeId": resume_id,
            "locale": "en",
            "fileNameSeed": "resume",
            "savedAt": "2026-08-09T00:00:00.000Z",
        },
    )

    assert response.status_code == 200
    assert all(not path.exists() for path in expired_paths)
    assert unrelated_path.exists()


def test_image_generation_removes_expired_export_artifacts(
    client: TestClient,
    monkeypatch,
) -> None:
    from app.config import get_settings
    from app.services.pdf import get_image_export_path

    export_dir = get_settings().export_dir
    export_dir.mkdir(parents=True, exist_ok=True)
    expired_path = export_dir / "export-old.pdf"
    expired_path.write_bytes(b"artifact")
    expired_at = (datetime.now(UTC) - timedelta(hours=1, seconds=5)).timestamp()
    os.utime(expired_path, (expired_at, expired_at))

    def write_test_image(
        export_id: str,
        _request: ExportResumeImagesRequest,
        **_: object,
    ) -> ResumeImageExportResult:
        export_path = get_image_export_path(export_id, is_archive=False)
        export_path.write_bytes(b"\x89PNG\r\n\x1a\n")
        return ResumeImageExportResult(
            path=export_path,
            page_count=1,
            is_archive=False,
        )

    monkeypatch.setattr("app.routers.exports.write_resume_images", write_test_image)
    resume_id = _create_resume(client)

    response = client.post(
        "/api/exports/resume-images",
        json={
            "resumeId": resume_id,
            "locale": "en",
            "fileNameSeed": "resume",
            "savedAt": "2026-08-09T00:00:00.000Z",
        },
    )

    assert response.status_code == 200
    assert not expired_path.exists()


def test_expired_pdf_download_deletes_artifact_before_404(
    client: TestClient,
) -> None:
    from app.services.pdf import get_export_path

    export_id = "export-expired-pdf"
    export_path = get_export_path(export_id)
    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_bytes(b"%PDF-1.4\n")
    expired_at = (datetime.now(UTC) - timedelta(hours=1, seconds=5)).timestamp()
    os.utime(export_path, (expired_at, expired_at))

    response = client.get(f"/api/exports/download/{export_id}")

    assert response.status_code == 404
    assert response.json()["message"] == "NOT_FOUND"
    assert not export_path.exists()


@pytest.mark.parametrize("is_archive", [False, True])
def test_expired_image_download_deletes_artifact_before_404(
    client: TestClient,
    is_archive: bool,
) -> None:
    from app.services.pdf import get_image_export_path

    export_id = f"export-expired-{'zip' if is_archive else 'png'}"
    export_path = get_image_export_path(export_id, is_archive=is_archive)
    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_bytes(b"artifact")
    expired_at = (datetime.now(UTC) - timedelta(hours=1, seconds=5)).timestamp()
    os.utime(export_path, (expired_at, expired_at))

    response = client.get(f"/api/exports/image-download/{export_id}")

    assert response.status_code == 404
    assert response.json()["message"] == "NOT_FOUND"
    assert not export_path.exists()
