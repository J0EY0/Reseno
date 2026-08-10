import json
from typing import Any

from fastapi import HTTPException, UploadFile, status
from pydantic import ValidationError

from app.schemas.imports import (
    ResumeArtifactV1,
    TemplateArtifactItem,
    TemplateArtifactV1,
)
from app.services.resume_document_contract import (
    ResumeDocumentContractError,
    validate_resume_document,
)

ARTIFACT_FORMAT_VERSION = 1
RESUME_ARTIFACT_FORMAT = "resumate.resume"
TEMPLATE_ARTIFACT_FORMAT = "resumate.template"
MAX_JSON_UPLOAD_BYTES = 10 * 1024 * 1024


async def load_json_upload(file: UploadFile) -> Any:
    """Read an uploaded file as UTF-8 JSON."""

    raw_body = await file.read(MAX_JSON_UPLOAD_BYTES + 1)
    if len(raw_body) > MAX_JSON_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="JSON_UPLOAD_TOO_LARGE",
        )

    try:
        return json.loads(raw_body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="JSON_UPLOAD_INVALID",
        ) from exc


def _validate_artifact_version(
    payload: Any,
    *,
    artifact_format: str,
    unsupported_version_detail: str,
) -> None:
    if (
        isinstance(payload, dict)
        and payload.get("format") == artifact_format
        and type(payload.get("formatVersion")) is int
        and payload["formatVersion"] != ARTIFACT_FORMAT_VERSION
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=unsupported_version_detail,
        )


def parse_resume_artifact(payload: Any) -> ResumeArtifactV1:
    """Validate and return a portable ResumeArtifactV1 bundle."""

    _validate_artifact_version(
        payload,
        artifact_format=RESUME_ARTIFACT_FORMAT,
        unsupported_version_detail="RESUME_ARTIFACT_VERSION_UNSUPPORTED",
    )
    try:
        artifact = ResumeArtifactV1.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="RESUME_ARTIFACT_INVALID",
        ) from exc

    for item in artifact.resumes:
        try:
            validate_resume_document(item.resume)
        except ResumeDocumentContractError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=exc.code,
            ) from exc

    return artifact


def parse_template_artifact(payload: Any) -> list[TemplateArtifactItem]:
    """Validate and return the portable entries from a TemplateArtifactV1."""

    _validate_artifact_version(
        payload,
        artifact_format=TEMPLATE_ARTIFACT_FORMAT,
        unsupported_version_detail="TEMPLATE_ARTIFACT_VERSION_UNSUPPORTED",
    )
    try:
        artifact = TemplateArtifactV1.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="TEMPLATE_ARTIFACT_INVALID",
        ) from exc

    return artifact.templates
