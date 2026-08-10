import hashlib
import json
import re
import secrets
import shutil
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from sqlite3 import Connection, Row
from typing import Any, Literal, NamedTuple, cast

from fastapi import HTTPException, status
from pydantic import ValidationError

from app.config import get_settings
from app.db.connection import connect
from app.schemas.imports import TemplateSettingsOverrides, TypographySettings
from app.schemas.resumes import MAX_RESUME_TITLE_LENGTH, ResumeWorkspaceItemResponse
from app.services.agent.attachments import delete_agent_session_attachments
from app.services.resume_document_contract import (
    ResumeDocumentContractError,
    validate_resume_document,
)
from app.services.templates import is_deleted_template, is_visible_template
from app.services.workspace_state import load_default_template_id

SUPPORTED_LOCALES = {"zh", "en"}
RESUME_COPY_LABELS = {"zh": "副本", "en": "Copy"}
RESUME_COPY_SUFFIX_PATTERN = re.compile(
    r"\s+-\s+(?:(?P<en_label>Copy)(?:\((?P<en_index>\d+)\))?"
    r"|(?P<zh_label>副本)(?:（(?P<zh_index>\d+)）)?)$"
)
RESUME_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
RESUME_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
RESUME_ID_LENGTH = 16
DEFAULT_TYPOGRAPHY = {"fontFamily": "inter", "fontSize": 16}
RESUME_VERSION_EXCLUDED_KEYS = {"deletedAt"}
VOLATILE_HASH_KEYS = {"savedAt", "updatedAt"}
ResumeVersionKind = Literal["autosave", "checkpoint"]
ResumeVersionFile = tuple[str, int]


class ResumeTemplateRebindResult(NamedTuple):
    """Version files created or superseded by one template rebind command."""

    created_versions: tuple[ResumeVersionFile, ...]
    obsolete_autosaves: tuple[ResumeVersionFile, ...]


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

    item_defaults: dict[str, dict[str, Any]] = {
        "education": {
            "school": "",
            "degree": "",
            "major": "",
            "gpa": "",
            "location": "",
            "period": "",
            "description": "",
            "highlights": [],
        },
        "experience": {
            "company": "",
            "position": "",
            "location": "",
            "period": "",
            "description": "",
            "highlights": [],
        },
        "project": {
            "name": "",
            "role": "",
            "techStack": [],
            "period": "",
            "url": "",
            "description": "",
            "highlights": [],
        },
    }

    def create_section(kind: str) -> dict[str, Any]:
        # The title is intentionally empty. Clients localize the default label,
        # while an explicit non-empty value remains a user-owned override.
        return {
            "id": _generate_document_id("section"),
            "kind": kind,
            "title": "",
            "items": [
                {
                    "id": _generate_document_id("item"),
                    **item_defaults[kind],
                }
            ],
        }

    return {
        "schemaVersion": 2,
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
            create_section("experience"),
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

    try:
        return validate_resume_document(value)
    except ResumeDocumentContractError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.code,
        ) from exc


def _validate_stored_resume_item(value: Any) -> dict[str, Any]:
    """Validate one persisted item against the only supported V1/V2 contract."""

    if not isinstance(value, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="RESUME_DOCUMENT_INVALID",
        )

    resume_document = _ensure_resume_document(value.get("resume"))
    try:
        item = ResumeWorkspaceItemResponse.model_validate(
            {**value, "resume": resume_document}
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="RESUME_DOCUMENT_INVALID",
        ) from exc

    return item.model_dump(mode="json", by_alias=True)


def _write_resume_json(
    resume_id: str, version_id: int, resume_item: dict[str, Any]
) -> None:
    """Write one resume version JSON file atomically."""

    path = _resume_version_path(resume_id, version_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = _canonical_json(resume_item)
    temp_path = path.with_suffix(".json.tmp")
    try:
        temp_path.write_text(content, encoding="utf-8")
        temp_path.replace(path)
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _delete_resume_json(resume_id: str, version_id: int) -> None:
    """Best-effort cleanup for one resume version file."""

    try:
        _resume_version_path(resume_id, version_id).unlink(missing_ok=True)
    except OSError:
        # A stale version file is harmless and can be removed with the resume.
        pass


def _read_resume_json(resume_id: str, version_id: int) -> dict[str, Any]:
    """Load one stored resume version JSON file."""

    path = _resume_version_path(resume_id, version_id)
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Resume version JSON is missing.",
        )

    return _validate_stored_resume_item(
        cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    )


def _resume_title(resume_item: dict[str, Any]) -> str:
    """Derive a stable display title for a resume row."""

    title = resume_item.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()[:MAX_RESUME_TITLE_LENGTH]

    resume = resume_item.get("resume")
    basic = resume.get("basic") if isinstance(resume, dict) else None
    name = basic.get("name") if isinstance(basic, dict) else None
    if isinstance(name, str) and name.strip():
        return name.strip()[:MAX_RESUME_TITLE_LENGTH]

    resume_id = resume_item.get("id")
    fallback = resume_id if isinstance(resume_id, str) else "Untitled"
    return fallback[:MAX_RESUME_TITLE_LENGTH]


def _resume_copy_base_title(title: str) -> str:
    """Remove generated copy suffixes without discarding the whole title."""

    base_title = title.strip()
    while suffix_match := RESUME_COPY_SUFFIX_PATTERN.search(base_title):
        next_base_title = base_title[: suffix_match.start()].rstrip()
        if not next_base_title:
            break
        base_title = next_base_title
    return base_title


def _duplicate_resume_title(
    conn: Connection,
    *,
    source_title: str,
    locale: str,
) -> str:
    """Return the first available localized copy title."""

    normalized_locale = _normalize_locale(locale)
    copy_label = RESUME_COPY_LABELS[normalized_locale]
    normalized_source_title = source_title.strip() or "Untitled"
    source_suffix_match = RESUME_COPY_SUFFIX_PATTERN.search(normalized_source_title)
    base_title = _resume_copy_base_title(normalized_source_title) or "Untitled"
    existing_titles = {
        str(row["title"])
        for row in conn.execute(
            """
            SELECT title
            FROM resumes
            """
        ).fetchall()
    }

    copy_suffix = f" - {copy_label}"

    def title_with_suffix(suffix: str) -> str:
        available_base_length = MAX_RESUME_TITLE_LENGTH - len(suffix)
        return f"{base_title[:available_base_length].rstrip()}{suffix}"

    def copy_title(copy_index: int | None = None) -> str:
        if copy_index is not None:
            suffix = (
                f"{copy_suffix}（{copy_index}）"
                if normalized_locale == "zh"
                else f"{copy_suffix}({copy_index})"
            )
            return title_with_suffix(suffix)
        return title_with_suffix(copy_suffix)

    def copy_title_exists(copy_index: int | None = None) -> bool:
        return copy_title(copy_index) in existing_titles

    # A longer numbered suffix can shorten a 50-character title. Continue from
    # the source index so that truncated descendants cannot restart at “Copy”.
    source_copy_label = None
    if source_suffix_match:
        source_copy_label = source_suffix_match.group(
            "en_label"
        ) or source_suffix_match.group("zh_label")
    if source_suffix_match and source_copy_label == copy_label:
        source_index = int(
            source_suffix_match.group("en_index")
            or source_suffix_match.group("zh_index")
            or 0
        )
        copy_index = source_index + 1
        while copy_title_exists(copy_index):
            copy_index += 1
        return copy_title(copy_index)

    first_title = copy_title()
    if not copy_title_exists():
        return first_title

    copy_index = 1
    while copy_title_exists(copy_index):
        copy_index += 1
    return copy_title(copy_index)


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
            SELECT content_hash, kind
            FROM resume_versions
            WHERE resume_id = ? AND version_id = ?
            """,
            (resume_id, current_version_id),
        ).fetchone(),
    )


def _save_resume_item(
    conn: Connection,
    *,
    resume_item: dict[str, Any],
    saved_at: str,
    deleted: bool,
    deleted_at: str | None = None,
    version_kind: ResumeVersionKind = "checkpoint",
) -> tuple[str, int, int | None]:
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
                current_version_id,
                title,
                saved_at,
                deleted,
                deleted_at
            )
            VALUES (?, 0, ?, ?, ?, ?)
            """,
            (
                resume_id,
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
    current_version_kind = (
        str(current_version["kind"]) if current_version is not None else None
    )
    obsolete_autosave_version_id: int | None = None

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
                kind,
                saved_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                resume_id,
                next_version_id,
                content_hash,
                version_kind,
                saved_at,
            ),
        )
        if current_version_kind == "autosave":
            conn.execute(
                """
                DELETE FROM resume_versions
                WHERE resume_id = ? AND version_id = ?
                """,
                (resume_id, current_version_id),
            )
            obsolete_autosave_version_id = current_version_id
    elif current_version_kind == "autosave":
        # Autosaves are mutable until a manual save/export promotes the latest
        # snapshot to an immutable history checkpoint.
        _write_resume_json(resume_id, next_version_id, resume_item)
        conn.execute(
            """
            UPDATE resume_versions
            SET kind = ?, saved_at = ?
            WHERE resume_id = ? AND version_id = ?
            """,
            (version_kind, saved_at, resume_id, next_version_id),
        )

    conn.execute(
        """
        INSERT INTO resumes (
            id,
            current_version_id,
            title,
            saved_at,
            deleted,
            deleted_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            current_version_id = excluded.current_version_id,
            title = excluded.title,
            saved_at = excluded.saved_at,
            deleted = excluded.deleted,
            deleted_at = excluded.deleted_at,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            resume_id,
            next_version_id,
            _resume_title(resume_item),
            saved_at,
            int(deleted),
            deleted_at,
        ),
    )

    return resume_id, next_version_id, obsolete_autosave_version_id


def rebind_current_resume_template_references(
    conn: Connection,
    *,
    source_template_id: str,
    target_template_id: str,
    saved_at: str,
) -> ResumeTemplateRebindResult:
    """Rebind current resume snapshots while the caller owns the transaction."""

    if source_template_id == target_template_id:
        return ResumeTemplateRebindResult((), ())
    if not is_visible_template(conn, target_template_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="TEMPLATE_NOT_FOUND",
        )

    rows = conn.execute(
        """
        SELECT id, current_version_id, deleted, deleted_at
        FROM resumes
        WHERE current_version_id > 0
        """
    ).fetchall()
    created_versions: list[ResumeVersionFile] = []
    obsolete_autosaves: list[ResumeVersionFile] = []

    try:
        for row in rows:
            current_version_id = int(row["current_version_id"])
            resume_item = _read_resume_json(row["id"], current_version_id)
            if resume_item["template"] != source_template_id:
                continue

            # A template change necessarily changes the content hash, so the
            # command owns the next version file until the transaction commits.
            created_versions.append((row["id"], current_version_id + 1))
            _, _, obsolete_autosave_version_id = _save_resume_item(
                conn,
                resume_item={
                    **resume_item,
                    "template": target_template_id,
                    "updatedAt": saved_at,
                },
                saved_at=saved_at,
                deleted=bool(row["deleted"]),
                deleted_at=row["deleted_at"],
                version_kind="checkpoint",
            )
            if obsolete_autosave_version_id is not None:
                obsolete_autosaves.append((row["id"], obsolete_autosave_version_id))
    except Exception:
        cleanup_resume_version_files(created_versions)
        raise

    return ResumeTemplateRebindResult(
        tuple(created_versions),
        tuple(obsolete_autosaves),
    )


def cleanup_resume_version_files(version_files: Iterable[ResumeVersionFile]) -> None:
    """Best-effort cleanup after a multi-resume command succeeds or rolls back."""

    for resume_id, version_id in version_files:
        _delete_resume_json(resume_id, version_id)


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

    resume = resume_item["resume"]
    deleted_at = row["deleted_at"] or row["saved_at"]

    return {
        "id": row["id"],
        "title": resume_item["title"],
        "updatedAt": row["saved_at"],
        "resume": {
            "schemaVersion": 2,
            "basic": resume["basic"],
            "sections": [],
        },
        "jobBrief": "",
        "typography": resume_item["typography"],
        "template": resume_item["template"],
        "templateSettings": resume_item["templateSettings"],
        "deletedAt": deleted_at,
    }


def _load_resume_items(
    conn: Connection,
    *,
    deleted: bool,
    requested_version: int | None = None,
) -> list[dict[str, Any]]:
    """Load active or deleted resume items for an optional version."""

    rows = conn.execute(
        """
        SELECT id, current_version_id, title, saved_at, deleted_at
        FROM resumes
        WHERE deleted = ?
        ORDER BY saved_at DESC, updated_at DESC
        """,
        (int(deleted),),
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
    """Fetch one resume row."""

    safe_resume_id = _validate_resume_id(resume_id.strip())
    return cast(
        Row | None,
        conn.execute(
            """
            SELECT
                id,
                current_version_id,
                title,
                saved_at,
                deleted,
                deleted_at
            FROM resumes
            WHERE id = ?
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
) -> dict[str, Any]:
    """Normalize an API payload into the versioned resume item shape."""

    raw_resume = payload.get("resume")
    resume_document = _ensure_resume_document(raw_resume)
    title = payload.get("title")
    job_brief = payload.get("jobBrief")
    typography = payload.get("typography")
    template_id = payload.get("template")

    if not isinstance(template_id, str) or not template_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="RESUME_DOCUMENT_INVALID",
        )

    try:
        normalized_typography = TypographySettings.model_validate(
            typography
        ).model_dump(by_alias=True)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="RESUME_DOCUMENT_INVALID",
        ) from exc

    if "templateSettings" not in payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="RESUME_DOCUMENT_INVALID",
        )
    template_settings = payload.get("templateSettings")

    if template_settings is None:
        normalized_template_settings = None
    else:
        try:
            normalized_template_settings = TemplateSettingsOverrides.model_validate(
                template_settings
            ).model_dump(by_alias=True, exclude_unset=True)
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="RESUME_DOCUMENT_INVALID",
            ) from exc

    normalized: dict[str, Any] = {
        "id": _validate_resume_id(resume_id.strip()),
        "title": title.strip()[:MAX_RESUME_TITLE_LENGTH]
        if isinstance(title, str) and title.strip()
        else _resume_title({"id": resume_id, "resume": resume_document}),
        "updatedAt": saved_at,
        "resume": resume_document,
        "jobBrief": job_brief if isinstance(job_brief, str) else "",
        "typography": normalized_typography,
        "template": template_id.strip(),
        "templateSettings": normalized_template_settings,
    }

    return normalized


def list_resumes(status_filter: str = "active") -> dict[str, Any]:
    """Return active resume items or deleted resume previews."""

    deleted = status_filter == "deleted"
    if status_filter not in {"active", "deleted"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported resume status filter.",
        )

    with connect() as conn:
        return {
            "resumes": _load_resume_items(
                conn,
                deleted=deleted,
            )
        }


def create_resume(payload: dict[str, Any]) -> dict[str, Any]:
    """Create a backend-owned empty resume and initial version."""

    saved_at = _utc_now()

    with connect() as conn:
        conn.execute("BEGIN")
        resume_id = _allocate_resume_id(conn)
        count_row = conn.execute(
            """
            SELECT COUNT(*) AS resume_count
            FROM resumes
            WHERE deleted = 0
            """,
        ).fetchone()
        default_title = f"Untitled Resume {int(count_row['resume_count']) + 1}"
        template_id = payload.get("template")
        if not isinstance(template_id, str) or not template_id.strip():
            template_id = load_default_template_id(conn)
        template_id = template_id.strip()
        if not is_visible_template(conn, template_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="TEMPLATE_NOT_FOUND",
            )

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
        _, version_id, _ = _save_resume_item(
            conn,
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
        # Name allocation and insert must share the write lock; otherwise two
        # simultaneous duplicate requests can choose the same available title.
        conn.execute("BEGIN IMMEDIATE")
        duplicate_id = _allocate_resume_id(conn)
        duplicate_title = _duplicate_resume_title(
            conn,
            source_title=_resume_title(source_item),
            locale=locale,
        )

        source_template_id = source_item.get("template")
        if not isinstance(source_template_id, str) or not source_template_id.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="RESUME_DOCUMENT_INVALID",
            )
        source_template_id = source_template_id.strip()
        if not is_visible_template(conn, source_template_id):
            if not is_deleted_template(conn, source_template_id):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="TEMPLATE_NOT_FOUND",
                )
            # A template in the recycle bin is no longer selectable. A copy is
            # a new resume, so bind it to the current visible workspace default.
            source_template_id = load_default_template_id(conn)

        # Keep this whitelist explicit: job context, Agent sessions, drafts, and
        # version history belong to the source resume and must not cross IDs.
        duplicate_item = _normalize_resume_item_payload(
            resume_id=duplicate_id,
            payload={
                "title": duplicate_title,
                "resume": source_item.get("resume"),
                "jobBrief": "",
                "typography": source_item.get("typography"),
                "template": source_template_id,
                "templateSettings": source_item.get("templateSettings"),
            },
            saved_at=saved_at,
        )
        _, version_id, _ = _save_resume_item(
            conn,
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


def save_resume(
    resume_id: str,
    payload: dict[str, Any],
    *,
    save_mode: ResumeVersionKind = "checkpoint",
) -> dict[str, Any]:
    """Persist the latest snapshot and retain only explicit checkpoints."""

    saved_at = _utc_now()
    obsolete_autosave_version_id: int | None = None
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _require_resume_row(conn, resume_id)
        if row["deleted"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Deleted resumes cannot be saved.",
            )

        submitted_template_id = payload["template"]
        if not is_visible_template(conn, submitted_template_id.strip()):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="TEMPLATE_NOT_FOUND",
            )
        resume_item = _normalize_resume_item_payload(
            resume_id=row["id"],
            payload=payload,
            saved_at=saved_at,
        )

        _, version_id, obsolete_autosave_version_id = _save_resume_item(
            conn,
            resume_item=resume_item,
            saved_at=saved_at,
            deleted=False,
            deleted_at=None,
            version_kind=save_mode,
        )
        conn.execute("COMMIT")

    if obsolete_autosave_version_id is not None:
        _delete_resume_json(resume_id, obsolete_autosave_version_id)

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
            WHERE resume_id = ? AND kind = 'checkpoint'
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


def _delete_resume_storage(resume_id: str) -> None:
    """Delete resume files while treating an absent directory as deleted."""

    try:
        shutil.rmtree(_resume_storage_dir(resume_id))
    except FileNotFoundError:
        pass


def _reject_running_agent_turns(conn: Connection, resume_ids: list[str]) -> None:
    """Keep durable running turns intact until their terminal state is persisted."""

    if not resume_ids:
        return
    placeholders = ", ".join("?" for _ in resume_ids)
    running_row = conn.execute(
        f"""
        SELECT 1
        FROM agent_turn_executions AS execution
        JOIN agent_sessions AS session
          ON session.id = execution.session_id
        WHERE execution.status = 'running'
          AND (
            session.resume_id IN ({placeholders})
            OR session.id IN ({placeholders})
          )
        LIMIT 1
        """,
        (*resume_ids, *resume_ids),
    ).fetchone()
    if running_row is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="AGENT_RUN_CONFLICT",
        )


def delete_resume_forever(resume_id: str) -> dict[str, Any]:
    """Physically delete one already-deleted resume."""

    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _require_resume_row(conn, resume_id)
        if not row["deleted"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only deleted resumes can be permanently deleted.",
            )

        _reject_running_agent_turns(conn, [row["id"]])
        delete_agent_session_attachments(row["id"])
        _delete_resume_storage(row["id"])
        _delete_resume_rows(conn, [row["id"]])
        conn.execute("COMMIT")

    return {"id": row["id"]}


def empty_resume_trash() -> dict[str, Any]:
    """Physically delete every resume currently in the recycle bin."""

    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            """
            SELECT id
            FROM resumes
            WHERE deleted = 1
            """
        ).fetchall()
        resume_ids = [row["id"] for row in rows]
        _reject_running_agent_turns(conn, resume_ids)
        conn.execute("COMMIT")

    for resume_id in resume_ids:
        delete_resume_forever(resume_id)

    return {"deletedCount": len(resume_ids)}
