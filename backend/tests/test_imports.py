import asyncio
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile, status
from fastapi.testclient import TestClient

from app.services.imports import load_json_upload

JSON_UPLOAD_LIMIT_BYTES = 10 * 1024 * 1024


def _padded_json(size: int) -> bytes:
    return b"{}" + (b" " * (size - 2))


def test_load_json_upload_rejects_before_reading_past_the_size_limit() -> None:
    upload = UploadFile(
        BytesIO(_padded_json(JSON_UPLOAD_LIMIT_BYTES + 8192)),
        filename="oversized.json",
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(load_json_upload(upload))

    assert exc_info.value.status_code == status.HTTP_413_CONTENT_TOO_LARGE
    assert exc_info.value.detail == "JSON_UPLOAD_TOO_LARGE"
    assert upload.file.tell() == JSON_UPLOAD_LIMIT_BYTES + 1


def test_load_json_upload_accepts_json_at_the_size_limit() -> None:
    upload = UploadFile(
        BytesIO(_padded_json(JSON_UPLOAD_LIMIT_BYTES)),
        filename="at-limit.json",
    )

    payload = asyncio.run(load_json_upload(upload))

    assert payload == {}
    assert upload.file.tell() == JSON_UPLOAD_LIMIT_BYTES


@pytest.mark.parametrize("endpoint", ["/api/import/resume", "/api/import/templates"])
def test_import_endpoint_rejects_json_above_the_size_limit(
    client: TestClient,
    endpoint: str,
) -> None:
    response = client.post(
        endpoint,
        files={
            "file": (
                "oversized.json",
                _padded_json(JSON_UPLOAD_LIMIT_BYTES + 1),
                "application/json",
            ),
        },
    )

    assert response.status_code == status.HTTP_413_CONTENT_TOO_LARGE
    assert response.json()["code"] == 40000
    assert response.json()["message"] == "JSON_UPLOAD_TOO_LARGE"
