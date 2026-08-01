import hashlib
import json
import re
import secrets
import shutil
from datetime import UTC, datetime
from pathlib import Path
from sqlite3 import Connection, Row
from typing import Any, cast

from fastapi import HTTPException, status

from app.config import get_settings
from app.db.connection import connect
from app.services.agent.attachments import delete_agent_session_attachments
from app.services.workspace_state import (
    DEFAULT_TEMPLATE_ID,
    WORKSPACE_DATA_LOCALE,
    load_default_template_id,
)

SUPPORTED_LOCALES = {"zh", "en"}
RESUME_COPY_LABELS = {"zh": "副本", "en": "Copy"}
RESUME_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
RESUME_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
RESUME_ID_LENGTH = 16
DEFAULT_TYPOGRAPHY = {"fontFamily": "inter", "fontSize": 16}
RESUME_VERSION_EXCLUDED_KEYS = {"deletedAt"}
VOLATILE_HASH_KEYS = {"savedAt", "updatedAt"}


def _normalize_locale(locale: str) -> str:
    """Return a supported locale, falling back to English."""

    return locale if locale in SUPPORTED_LOCALES else "en"


def generate_resume_id() -> str:
    """Generate a compact backend-owned resume id."""

    return "".join(secrets.choice(RESUME_ID_ALPHABET) for _ in range(RESUME_ID_LENGTH))


def _generate_document_id(prefix: str) -> str:
    """Generate a compact id for nested resume document nodes."""

    return f"{prefix}-{secrets.token_hex(4)}"


def _create_empty_resume() -> dict[str, Any]:
    """Create the default editable resume document."""

    def create_item() -> dict[str, Any]:
        return {
            "id": _generate_document_id("item"),
            "title": "",
            "subtitle": "",
            "meta": "",
            "period": "",
            "description": "",
            "highlights": [],
        }

    def create_section(kind: str) -> dict[str, Any]:
        return {
            "id": _generate_document_id("section"),
            "kind": kind,
            "layout": "timeline",
            "customTitle": "",
            "items": [create_item()],
        }

    return {
        "basic": {
            "name": "",
            "headline": "",
            "phone": "",
            "email": "",
            "location": "",
            "avatar": "",
            "summary": "",
            "customFields": [],
        },
        "sections": [
            create_section("education"),
            create_section("internship"),
            create_section("project"),
        ],
    }


def _allocate_resume_id(conn: Connection) -> str:
    """Generate a resume id that does not currently exist in storage."""

    for _ in range(20):
        resume_id = generate_resume_id()
        row = conn.execute(
            "SELECT 1 FROM resumes WHERE id = ?",
            (resume_id,),
        ).fetchone()
        if row is None:
            return resume_id

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Failed to allocate a resume id.",
    )


def _utc_now() -> str:
    """Return the current UTC time in frontend-compatible ISO format."""

    return (
        datetime.now(UTC)
        .isoformat(timespec="milliseconds")
        .replace(
            "+00:00",
            "Z",
        )
    )


def _validate_resume_id(resume_id: str) -> str:
    """Validate that a resume id is safe for database and path use."""

    if not RESUME_ID_PATTERN.fullmatch(resume_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Resume id may only contain letters, numbers, dot, dash, or underscore."
            ),
        )

    return resume_id


def _resume_version_path(resume_id: str, version_id: int) -> Path:
    """Build the storage path for one resume version JSON file."""

    safe_resume_id = _validate_resume_id(resume_id)
    return (
        get_settings().storage_dir
        / "resumes"
        / safe_resume_id
        / "versions"
        / f"{version_id}.json"
    )


def _resume_storage_dir(resume_id: str) -> Path:
    """Build the storage directory for all files belonging to one resume."""

    safe_resume_id = _validate_resume_id(resume_id)
    return get_settings().storage_dir / "resumes" / safe_resume_id


def _canonical_json(value: Any) -> str:
    """Serialize JSON deterministically for hashing and persistence."""

    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _strip_volatile_hash_fields(value: Any) -> Any:
    """Remove timestamp fields that should not create new resume versions."""

    if isinstance(value, list):
        return [_strip_volatile_hash_fields(item) for item in value]

    if not isinstance(value, dict):
        return value

    return {
        key: _strip_volatile_hash_fields(entry_value)
        for key, entry_value in value.items()
        if key not in VOLATILE_HASH_KEYS
    }


def _resume_content_hash(resume_item: dict[str, Any]) -> str:
    """Calculate the stable content hash for a resume item."""

    stable_payload = _strip_volatile_hash_fields(resume_item)
    return hashlib.sha256(_canonical_json(stable_payload).encode("utf-8")).hexdigest()


def _resume_version_payload(resume_item: dict[str, Any]) -> dict[str, Any]:
    """Return the part of a resume item that belongs in content versions."""

    return {
        key: value
        for key, value in resume_item.items()
        if key not in RESUME_VERSION_EXCLUDED_KEYS
    }


def _ensure_resume_document(value: Any) -> dict[str, Any]:
    """Validate the stored resume document shape expected by the frontend."""

    if not isinstance(value, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Resume document is required.",
        )

    basic = value.get("basic")
    sections = value.get("sections")
    if not isinstance(basic, dict) or not isinstance(sections, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Resume document must include basic info and sections.",
        )

    return value


def _write_resume_json(
    resume_id: str, version_id: int, resume_item: dict[str, Any]
) -> None:
    """Write one resume version JSON file atomically."""

    path = _resume_version_path(resume_id, version_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = _canonical_json(resume_item)
    temp_path = path.with_suffix(".json.tmp")
    temp_path.write_text(content, encoding="utf-8")
    temp_path.replace(path)


def _read_resume_json(resume_id: str, version_id: int) -> dict[str, Any]:
    """Load one stored resume version JSON file."""

    path = _resume_version_path(resume_id, version_id)
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Resume version JSON is missing.",
        )

    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _resume_title(resume_item: dict[str, Any]) -> str:
    """Derive a stable display title for a resume row."""

    title = resume_item.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()

    resume = resume_item.get("resume")
    basic = resume.get("basic") if isinstance(resume, dict) else None
    name = basic.get("name") if isinstance(basic, dict) else None
    if isinstance(name, str) and name.strip():
        return name.strip()

    resume_id = resume_item.get("id")
    return resume_id if isinstance(resume_id, str) else "Untitled"


def _duplicate_resume_title(
    conn: Connection,
    *,
    source_title: str,
    locale: str,
) -> str:
    """Return the first available localized copy title."""

    copy_label = RESUME_COPY_LABELS[_normalize_locale(locale)]
    base_title = source_title.strip() or "Untitled"
    first_title = f"{base_title} - {copy_label}"
    existing_titles = {
        str(row["title"])
        for row in conn.execute(
            """
            SELECT title
            FROM resumes
            WHERE locale = ? AND purged = 0
            """,
            (WORKSPACE_DATA_LOCALE,),
        ).fetchall()
    }
    if first_title not in existing_titles:
        return first_title

    copy_index = 2
    while f"{first_title} {copy_index}" in existing_titles:
        copy_index += 1
    return f"{first_title} {copy_index}"


def _current_resume_version_row(
    conn: Connection,
    resume_id: str,
    current_version_id: int,
) -> Row | None:
    """Fetch metadata for the current version of a resume."""

    if current_version_id <= 0:
        return None

    return cast(
        Row | None,
        conn.execute(
            """
            SELECT content_hash
            FROM resume_versions
            WHERE resume_id = ? AND version_id = ?
            """,
            (resume_id, current_version_id),
        ).fetchone(),
    )


def _save_resume_item(
    conn: Connection,
    *,
    locale: str,
    resume_item: dict[str, Any],
    saved_at: str,
    deleted: bool,
    deleted_at: str | None = None,
) -> tuple[str, int]:
    """Persist one resume item and create a new version when content changed."""

    resume_item = _resume_version_payload(resume_item)
    resume_id = resume_item.get("id")
    if not isinstance(resume_id, str) or not resume_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Resume id is required.",
        )
    resume_id = _validate_resume_id(resume_id.strip())

    existing = conn.execute(
        """
        SELECT current_version_id
        FROM resumes
        WHERE id = ?
        """,
        (resume_id,),
    ).fetchone()
    current_version_id = int(existing["current_version_id"]) if existing else 0
    if existing is None:
        conn.execute(
            """
            INSERT INTO resumes (
                id,
                locale,
                current_version_id,
                title,
                saved_at,
                deleted,
                deleted_at,
                purged
            )
            VALUES (?, ?, 0, ?, ?, ?, ?, 0)
            """,
            (
                resume_id,
                locale,
                _resume_title(resume_item),
                saved_at,
                int(deleted),
                deleted_at,
            ),
        )

    content_hash = _resume_content_hash(resume_item)
    current_version = _current_resume_version_row(
        conn,
        resume_id,
        current_version_id,
    )
    should_write_version = (
        current_version is None or current_version["content_hash"] != content_hash
    )

    next_version_id = (
        current_version_id + 1 if should_write_version else current_version_id
    )
    if should_write_version:
        _write_resume_json(resume_id, next_version_id, resume_item)
        conn.execute(
            """
            INSERT INTO resume_versions (
                resume_id,
                version_id,
                content_hash,
                saved_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (resume_id, next_version_id, content_hash, saved_at),
        )
    else:
        _write_resume_json(resume_id, next_version_id, resume_item)

    conn.execute(
        """
        INSERT INTO resumes (
            id,
            locale,
            current_version_id,
            title,
            saved_at,
            deleted,
            deleted_at,
            purged,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 0, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            locale = excluded.locale,
            current_version_id = excluded.current_version_id,
            title = excluded.title,
            saved_at = excluded.saved_at,
            deleted = excluded.deleted,
            deleted_at = excluded.deleted_at,
            purged = 0,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            resume_id,
            locale,
            next_version_id,
            _resume_title(resume_item),
            saved_at,
            int(deleted),
            deleted_at,
        ),
    )

    return resume_id, next_version_id


def _version_for_resume(
    conn: Connection,
    *,
    resume_id: str,
    requested_version: int | None,
    current_version: int,
) -> int | None:
    """Choose the newest available resume version at or before a target."""

    if requested_version is None:
        return current_version

    row = conn.execute(
        """
        SELECT MAX(version_id) AS version_id
        FROM resume_versions
        WHERE resume_id = ? AND version_id <= ?
        """,
        (resume_id, requested_version),
    ).fetchone()
    if row is None or row["version_id"] is None:
        return None

    return int(row["version_id"])


def _deleted_resume_preview(
    row: Row,
    resume_item: dict[str, Any],
) -> dict[str, Any]:
    """Build the limited payload shown in the recycle bin."""

    resume = resume_item.get("resume") if isinstance(resume_item, dict) else None
    basic = resume.get("basic") if isinstance(resume, dict) else None
    deleted_at = row["deleted_at"] or row["saved_at"]

    preview: dict[str, Any] = {
        "id": row["id"],
        "title": row["title"] or _resume_title(resume_item),
        "updatedAt": row["saved_at"],
        "resume": {
            "basic": basic if isinstance(basic, dict) else {},
            "sections": [],
        },
        "jobBrief": "",
        "deletedAt": deleted_at,
    }

    typography = resume_item.get("typography")
    if isinstance(typography, dict):
        preview["typography"] = typography

    template_id = resume_item.get("template")
    if isinstance(template_id, str) and template_id:
        preview["template"] = template_id

    template_settings = resume_item.get("templateSettings")
    if isinstance(template_settings, dict):
        preview["templateSettings"] = template_settings

    return preview


def _load_resume_items(
    conn: Connection,
    *,
    locale: str,
    deleted: bool,
    requested_version: int | None = None,
) -> list[dict[str, Any]]:
    """Load active or deleted resume items for a locale and optional version."""

    rows = conn.execute(
        """
        SELECT id, current_version_id, title, saved_at, deleted_at
        FROM resumes
        WHERE locale = ? AND deleted = ? AND purged = 0
        ORDER BY saved_at DESC, updated_at DESC
        """,
        (locale, int(deleted)),
    ).fetchall()
    items: list[dict[str, Any]] = []

    for row in rows:
        version_id = _version_for_resume(
            conn,
            resume_id=row["id"],
            requested_version=requested_version,
            current_version=int(row["current_version_id"]),
        )
        if version_id is None:
            continue

        resume_item = _read_resume_json(row["id"], version_id)
        items.append(
            _deleted_resume_preview(row, resume_item) if deleted else resume_item
        )

    return items


def _resume_row(conn: Connection, resume_id: str) -> Row | None:
    """Fetch a non-purged resume row."""

    safe_resume_id = _validate_resume_id(resume_id.strip())
    return cast(
        Row | None,
        conn.execute(
            """
            SELECT
                id,
                locale,
                current_version_id,
                title,
                saved_at,
                deleted,
                deleted_at
            FROM resumes
            WHERE id = ? AND purged = 0
            """,
            (safe_resume_id,),
        ).fetchone(),
    )


def _require_resume_row(conn: Connection, resume_id: str) -> Row:
    """Return a resume row or raise a public 404."""

    row = _resume_row(conn, resume_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resume not found.",
        )

    return row


def _version_id_from_string(version_id: str) -> int:
    """Parse a public resume version id."""

    try:
        parsed = int(version_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resume version not found.",
        ) from exc

    if parsed < 1:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resume version not found.",
        )

    return parsed


def _resume_version_row(
    conn: Connection,
    *,
    resume_id: str,
    version_id: int,
) -> Row:
    """Fetch one resume version row or raise 404."""

    row = conn.execute(
        """
        SELECT version_id, saved_at
        FROM resume_versions
        WHERE resume_id = ? AND version_id = ?
        """,
        (resume_id, version_id),
    ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resume version not found.",
        )

    return cast(Row, row)


def _load_resume_detail(
    conn: Connection,
    *,
    resume_id: str,
    version_id: str | None = None,
    include_deleted: bool = False,
) -> dict[str, Any]:
    """Load one resume detail payload from current or historical storage."""

    row = _require_resume_row(conn, resume_id)
    if row["deleted"] and not include_deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resume not found.",
        )

    if version_id is None:
        current_version_id = int(row["current_version_id"])
        if current_version_id < 1:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resume version not found.",
            )

        item = _read_resume_json(row["id"], current_version_id)
        return {
            "resume": item,
            "savedAt": row["saved_at"],
            "versionId": str(current_version_id),
        }

    requested_version_id = _version_id_from_string(version_id)
    version_row = _resume_version_row(
        conn,
        resume_id=row["id"],
        version_id=requested_version_id,
    )

    return {
        "resume": _read_resume_json(row["id"], requested_version_id),
        "savedAt": version_row["saved_at"],
        "versionId": str(version_row["version_id"]),
    }


def _normalize_resume_item_payload(
    *,
    resume_id: str,
    payload: dict[str, Any],
    saved_at: str,
    fallback_item: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize an API payload into the versioned resume item shape."""

    fallback_item = fallback_item or {}
    raw_resume = payload.get("resume", fallback_item.get("resume"))
    resume_document = _ensure_resume_document(raw_resume)
    title = payload.get("title", fallback_item.get("title"))
    job_brief = payload.get("jobBrief", fallback_item.get("jobBrief", ""))
    typography = payload.get("typography", fallback_item.get("typography"))
    template_id = payload.get("template", fallback_item.get("template"))

    normalized: dict[str, Any] = {
        "id": _validate_resume_id(resume_id.strip()),
        "title": title.strip()
        if isinstance(title, str) and title.strip()
        else _resume_title({"id": resume_id, "resume": resume_document}),
        "updatedAt": saved_at,
        "resume": resume_document,
        "jobBrief": job_brief if isinstance(job_brief, str) else "",
        "typography": (
            typography if isinstance(typography, dict) else DEFAULT_TYPOGRAPHY
        ),
        "template": template_id.strip()
        if isinstance(template_id, str) and template_id.strip()
        else DEFAULT_TEMPLATE_ID,
    }

    if "templateSettings" in payload:
        template_settings = payload.get("templateSettings")
        if isinstance(template_settings, dict):
            normalized["templateSettings"] = template_settings
    else:
        template_settings = fallback_item.get("templateSettings")
        if isinstance(template_settings, dict):
            normalized["templateSettings"] = template_settings

    return normalized


def list_resumes(status_filter: str = "active") -> dict[str, Any]:
    """Return active resume items or deleted resume previews."""

    deleted = status_filter == "deleted"
    if status_filter not in {"active", "deleted"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported resume status filter.",
        )

    data_locale = WORKSPACE_DATA_LOCALE
    with connect() as conn:
        return {
            "resumes": _load_resume_items(
                conn,
                locale=data_locale,
                deleted=deleted,
            )
        }


def create_resume(payload: dict[str, Any]) -> dict[str, Any]:
    """Create a backend-owned empty resume and initial version."""

    data_locale = WORKSPACE_DATA_LOCALE
    saved_at = _utc_now()

    with connect() as conn:
        conn.execute("BEGIN")
        resume_id = _allocate_resume_id(conn)
        count_row = conn.execute(
            """
            SELECT COUNT(*) AS resume_count
            FROM resumes
            WHERE locale = ? AND purged = 0 AND deleted = 0
            """,
            (data_locale,),
        ).fetchone()
        default_title = f"Untitled Resume {int(count_row['resume_count']) + 1}"
        template_id = payload.get("template")
        if not isinstance(template_id, str) or not template_id.strip():
            template_id = load_default_template_id(conn)

        resume_item = _normalize_resume_item_payload(
            resume_id=resume_id,
            payload={
                "title": payload.get("title", default_title),
                "resume": payload.get("resume", _create_empty_resume()),
                "jobBrief": payload.get("jobBrief", ""),
                "typography": payload.get("typography", DEFAULT_TYPOGRAPHY),
                "template": template_id,
                "templateSettings": payload.get("templateSettings"),
            },
            saved_at=saved_at,
        )
        _, version_id = _save_resume_item(
            conn,
            locale=data_locale,
            resume_item=resume_item,
            saved_at=saved_at,
            deleted=False,
            deleted_at=None,
        )
        conn.execute("COMMIT")

    return {
        "resume": resume_item,
        "savedAt": saved_at,
        "versionId": str(version_id),
    }


def duplicate_resume(resume_id: str, locale: str) -> dict[str, Any]:
    """Create an independent resume from the source's current content."""

    saved_at = _utc_now()
    with connect() as conn:
        row = _require_resume_row(conn, resume_id)
        if row["deleted"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Deleted resumes cannot be duplicated.",
            )

        current_version_id = int(row["current_version_id"])
        if current_version_id < 1:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resume version not found.",
            )

        source_item = _read_resume_json(row["id"], current_version_id)
        conn.execute("BEGIN")
        duplicate_id = _allocate_resume_id(conn)
        duplicate_title = _duplicate_resume_title(
            conn,
            source_title=_resume_title(source_item),
            locale=locale,
        )

        # Keep this whitelist explicit: job context, Agent sessions, drafts, and
        # version history belong to the source resume and must not cross IDs.
        duplicate_item = _normalize_resume_item_payload(
            resume_id=duplicate_id,
            payload={
                "title": duplicate_title,
                "resume": source_item.get("resume"),
                "jobBrief": "",
                "typography": source_item.get("typography"),
                "template": source_item.get("template"),
                "templateSettings": source_item.get("templateSettings"),
            },
            saved_at=saved_at,
        )
        _, version_id = _save_resume_item(
            conn,
            locale=WORKSPACE_DATA_LOCALE,
            resume_item=duplicate_item,
            saved_at=saved_at,
            deleted=False,
            deleted_at=None,
        )
        conn.execute("COMMIT")

    return {
        "resume": duplicate_item,
        "savedAt": saved_at,
        "versionId": str(version_id),
    }


def load_resume(resume_id: str) -> dict[str, Any]:
    """Load the current detail for one active resume."""

    with connect() as conn:
        return _load_resume_detail(conn, resume_id=resume_id)


def save_resume(resume_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Persist a full resume update and create a version when content changed."""

    saved_at = _utc_now()
    with connect() as conn:
        row = _require_resume_row(conn, resume_id)
        if row["deleted"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Deleted resumes cannot be saved.",
            )

        current_version_id = int(row["current_version_id"])
        fallback_item = (
            _read_resume_json(row["id"], current_version_id)
            if current_version_id > 0
            else None
        )
        resume_item = _normalize_resume_item_payload(
            resume_id=row["id"],
            payload=payload,
            saved_at=saved_at,
            fallback_item=fallback_item,
        )

        conn.execute("BEGIN")
        _, version_id = _save_resume_item(
            conn,
            locale=WORKSPACE_DATA_LOCALE,
            resume_item=resume_item,
            saved_at=saved_at,
            deleted=False,
            deleted_at=None,
        )
        conn.execute("COMMIT")

    return {
        "resume": resume_item,
        "savedAt": saved_at,
        "versionId": str(version_id),
    }


def list_resume_versions(resume_id: str) -> dict[str, Any]:
    """List versions for one resume."""

    with connect() as conn:
        row = _require_resume_row(conn, resume_id)
        rows = conn.execute(
            """
            SELECT version_id, saved_at
            FROM resume_versions
            WHERE resume_id = ?
            ORDER BY version_id DESC
            """,
            (row["id"],),
        ).fetchall()

    return {
        "versions": [
            {
                "versionId": str(row["version_id"]),
                "savedAt": row["saved_at"],
            }
            for row in rows
        ]
    }


def load_resume_version(resume_id: str, version_id: str) -> dict[str, Any]:
    """Load one historical resume version."""

    with connect() as conn:
        return _load_resume_detail(
            conn,
            resume_id=resume_id,
            version_id=version_id,
            include_deleted=True,
        )


def trash_resume(resume_id: str) -> dict[str, Any]:
    """Move an active resume into the recycle bin without creating a version."""

    deleted_at = _utc_now()
    with connect() as conn:
        row = _require_resume_row(conn, resume_id)
        current_version_id = int(row["current_version_id"])
        if current_version_id < 1:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resume version not found.",
            )

        resume_item = _read_resume_json(row["id"], current_version_id)
        if not row["deleted"]:
            conn.execute("BEGIN")
            conn.execute(
                """
                UPDATE resumes
                SET deleted = 1,
                    deleted_at = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (deleted_at, row["id"]),
            )
            conn.execute("COMMIT")
            row = _require_resume_row(conn, resume_id)

        return {"resume": _deleted_resume_preview(row, resume_item)}


def restore_resume(resume_id: str) -> dict[str, Any]:
    """Restore a deleted resume without creating a version."""

    with connect() as conn:
        row = _require_resume_row(conn, resume_id)
        if not row["deleted"]:
            return _load_resume_detail(conn, resume_id=row["id"])

        conn.execute("BEGIN")
        conn.execute(
            """
            UPDATE resumes
            SET deleted = 0,
                deleted_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (row["id"],),
        )
        conn.execute("COMMIT")

        return _load_resume_detail(conn, resume_id=row["id"])


def _delete_resume_rows(conn: Connection, resume_ids: list[str]) -> None:
    """Physically delete resume rows and their attached agent sessions."""

    for resume_id in resume_ids:
        conn.execute(
            """
            DELETE FROM agent_sessions
            WHERE resume_id = ? OR id = ?
            """,
            (resume_id, resume_id),
        )
        conn.execute(
            """
            DELETE FROM resumes
            WHERE id = ?
            """,
            (resume_id,),
        )


def delete_resume_forever(resume_id: str) -> dict[str, Any]:
    """Physically delete one already-deleted resume."""

    with connect() as conn:
        row = _require_resume_row(conn, resume_id)
        if not row["deleted"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only deleted resumes can be permanently deleted.",
            )

        conn.execute("BEGIN")
        _delete_resume_rows(conn, [row["id"]])
        conn.execute("COMMIT")

    shutil.rmtree(_resume_storage_dir(row["id"]), ignore_errors=True)
    delete_agent_session_attachments(row["id"])
    return {"id": row["id"]}


def empty_resume_trash() -> dict[str, Any]:
    """Physically delete every resume currently in the recycle bin."""

    data_locale = WORKSPACE_DATA_LOCALE
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id
            FROM resumes
            WHERE locale = ? AND deleted = 1 AND purged = 0
            """,
            (data_locale,),
        ).fetchall()
        resume_ids = [row["id"] for row in rows]
        if resume_ids:
            conn.execute("BEGIN")
            _delete_resume_rows(conn, resume_ids)
            conn.execute("COMMIT")

    for deleted_resume_id in resume_ids:
        shutil.rmtree(_resume_storage_dir(deleted_resume_id), ignore_errors=True)
        delete_agent_session_attachments(deleted_resume_id)

    return {"deletedCount": len(resume_ids)}
