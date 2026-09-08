import asyncio
import json
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile, status
from fastapi.testclient import TestClient

from app.services.imports import load_json_upload
from app.services.resume_starters import create_empty_resume
from tests.template_fixtures import portable_template

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


@pytest.mark.parametrize(
    ("invalid_document", "expected_message"),
    [
        ("schema_version", "RESUME_DOCUMENT_INVALID"),
        ("duplicate_section", "RESUME_DOCUMENT_DUPLICATE_ID"),
        ("duplicate_item", "RESUME_DOCUMENT_DUPLICATE_ID"),
    ],
)
def test_import_resume_rejects_invalid_document(
    client: TestClient,
    invalid_document: str,
    expected_message: str,
) -> None:
    resume = create_empty_resume("earlyCareer", "en")
    if invalid_document == "schema_version":
        resume["schemaVersion"] = 1
    elif invalid_document == "duplicate_section":
        resume["sections"][1]["id"] = resume["sections"][0]["id"]
    else:
        resume["sections"][1]["items"][0]["id"] = resume["sections"][0]["items"][0][
            "id"
        ]

    payload = {
        "format": "reseno.resume",
        "formatVersion": 1,
        "templates": [],
        "resumes": [
            {
                "title": "Imported resume",
                "documentLocale": "en",
                "resume": resume,
                "jobBrief": "",
                "typography": {"fontFamily": "inter", "fontSize": 16},
                "template": "minimal",
                "templateSettings": None,
            }
        ],
    }
    response = client.post(
        "/api/import/resume",
        files={"file": ("resume.json", json.dumps(payload), "application/json")},
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["code"] == 40000
    assert response.json()["message"] == expected_message


@pytest.mark.parametrize("line_height", [1.1, 1.25])
def test_compact_serif_template_survives_save_and_resume_import(
    client: TestClient,
    line_height: float,
) -> None:
    template = portable_template("Compact serif")
    template["typography"] = {"fontFamily": "times", "fontSize": 14}
    template["layout"]["section"] = "underlined"
    template["settings"]["bodyLineHeight"] = line_height

    saved = client.post("/api/templates", json={"template": template})
    assert saved.status_code == status.HTTP_200_OK
    template_id = saved.json()["data"]["template"]["id"]
    listed = client.get("/api/templates")
    stored = next(
        item
        for item in listed.json()["data"]["templates"]
        if item["id"] == template_id
    )
    definition = {key: stored[key] for key in template}
    assert definition == template

    imported_resume = {
        "title": "Compact serif resume",
        "documentLocale": "en",
        "resume": create_empty_resume("earlyCareer", "en"),
        "jobBrief": "",
        "typography": template["typography"],
        "template": "custom:0",
        "templateSettings": {"bodyLineHeight": line_height},
    }
    payload = {
        "format": "reseno.resume",
        "formatVersion": 1,
        "templates": [{"ref": "custom:0", "definition": definition}],
        "resumes": [imported_resume],
    }
    imported = client.post(
        "/api/import/resume",
        files={"file": ("resume.json", json.dumps(payload), "application/json")},
    )

    assert imported.status_code == status.HTTP_200_OK
    assert imported.json()["data"] == {
        "templates": payload["templates"],
        "resumes": payload["resumes"],
    }
