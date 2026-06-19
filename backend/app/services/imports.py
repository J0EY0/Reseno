import json
from typing import Any

from fastapi import HTTPException, UploadFile, status

from app.services.workspace import generate_resume_id


async def load_json_upload(file: UploadFile) -> Any:
    """Read an uploaded file as UTF-8 JSON."""

    raw_body = await file.read()

    try:
        return json.loads(raw_body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must be valid UTF-8 JSON.",
        ) from exc


def unwrap_api_payload(payload: Any) -> Any:
    """Unwrap a successful ApiResponse payload when a file contains one."""

    if isinstance(payload, dict) and payload.get("code") == 0 and "data" in payload:
        return payload["data"]

    return payload


def coerce_resume_import(payload: Any) -> list[dict[str, Any]]:
    """Normalize supported resume import JSON shapes into resume items."""

    data = unwrap_api_payload(payload)

    if isinstance(data, dict) and isinstance(data.get("resumes"), list):
        return [
            _with_resume_id(item)
            for item in data["resumes"]
            if isinstance(item, dict)
        ]

    if isinstance(data, list):
        return [_with_resume_id(item) for item in data if isinstance(item, dict)]

    if isinstance(data, dict):
        return [_with_resume_id(data)]

    return []


def _with_resume_id(item: dict[str, Any]) -> dict[str, Any]:
    """Return an imported resume item with a backend-generated id."""

    if _looks_like_resume_data(item):
        return {"id": generate_resume_id(), "resume": item}

    return {**item, "id": generate_resume_id()}


def _looks_like_resume_data(item: dict[str, Any]) -> bool:
    return isinstance(item.get("basic"), dict) and isinstance(
        item.get("sections"),
        list,
    )


def coerce_template_import(payload: Any) -> list[dict[str, Any]]:
    """Normalize supported template import JSON shapes into templates."""

    data = unwrap_api_payload(payload)

    if isinstance(data, dict) and isinstance(data.get("templates"), list):
        return [item for item in data["templates"] if isinstance(item, dict)]

    if isinstance(data, dict) and isinstance(data.get("customTemplates"), list):
        return [item for item in data["customTemplates"] if isinstance(item, dict)]

    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]

    if isinstance(data, dict):
        return [data]

    return []
