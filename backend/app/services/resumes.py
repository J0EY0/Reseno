import hashlib
import json
import re
import secrets
import shutil
from collections import OrderedDict
from collections.abc import Iterable
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from sqlite3 import Connection, Row
from sqlite3 import Error as SqliteError
from threading import Lock
from typing import Any, Literal, NamedTuple, cast

from fastapi import HTTPException, status
from pydantic import ValidationError

from app.config import get_settings
from app.db.connection import connect
from app.document_locales import DocumentLocale
from app.schemas.imports import TemplateSettingsOverrides, TypographySettings
from app.schemas.resume_document_generated import ResumeDocument
from app.schemas.resumes import (
    MAX_RESUME_TITLE_LENGTH,
    DeletedResumeWorkspaceItemResponse,
    ResumeListResponse,
    ResumeWorkspaceItemResponse,
    is_valid_resume_id,
)
from app.services.agent.attachments import delete_agent_session_attachments
from app.services.resume_document_contract import (
    ResumeDocumentContractError,
    validate_resume_document,
)
from app.services.resume_rich_text import resume_text_content
from app.services.resume_starters import create_empty_resume
from app.services.storage_deletions import (
    delete_storage,
    recover_storage_deletion,
    recover_storage_deletions,
    storage_id_reserved,
)
from app.services.template_presets import get_builtin_template_preset
from app.services.templates import (
    is_deleted_template,
    is_visible_template,
    resolve_visible_template,
)
from app.services.workspace_state import load_default_template_id

RESUME_COPY_LABELS: dict[DocumentLocale, str] = {"zh": "副本", "en": "Copy"}
RESUME_COPY_SUFFIX_PATTERN = re.compile(
    r"\s+-\s+(?:(?P<en_label>Copy)(?:\((?P<en_index>\d+)\))?"
    r"|(?P<zh_label>副本)(?:（(?P<zh_index>\d+)）)?)$"
)
RESUME_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
RESUME_ID_LENGTH = 16
RESUME_VERSION_FILENAME_PATTERN = re.compile(
    r"(?P<version_id>[1-9][0-9]*)\.json(?P<temporary>\.tmp)?"
)
RESUME_VERSION_EXCLUDED_KEYS = {"deletedAt"}
VOLATILE_HASH_KEYS = {"savedAt", "updatedAt"}
ResumeVersionKind = Literal["autosave", "checkpoint"]
ResumeVersionFile = tuple[str, int]

_MAX_VALIDATED_SNAPSHOTS = 1024
_VALIDATED_SNAPSHOTS: OrderedDict[bytes, None] = OrderedDict()
_VALIDATED_SNAPSHOTS_LOCK = Lock()


@dataclass
class ResumeTemplateRebindResult:
    """Version files created or superseded by one template rebind command."""

    created_versions: list[ResumeVersionFile] = field(default_factory=list)
    obsolete_autosaves: list[ResumeVersionFile] = field(default_factory=list)


class ResumeSaveTransaction(NamedTuple):
    """Resume write metadata needed by a caller-owned transaction."""

    detail: dict[str, Any]
    created_version: ResumeVersionFile | None
    obsolete_autosave: ResumeVersionFile | None


def generate_resume_id() -> str:
    """Generate a compact backend-owned resume id."""

    return "".join(secrets.choice(RESUME_ID_ALPHABET) for _ in range(RESUME_ID_LENGTH))


def _allocate_resume_id(conn: Connection) -> str:
    """Generate a resume id that does not currently exist in storage."""

    for _ in range(20):
        resume_id = generate_resume_id()
        row = conn.execute(
            "SELECT 1 FROM resumes WHERE id = ?",
            (resume_id,),
        ).fetchone()
        if row is None and not storage_id_reserved("resumes", resume_id):
            return resume_id

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="RESUME_ID_ALLOCATION_FAILED",
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

    if not is_valid_resume_id(resume_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="RESUME_ID_INVALID",
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


def _ensure_resume_document(value: object) -> ResumeDocument:
    """Validate the stored resume document shape expected by the frontend."""

    try:
        return validate_resume_document(value)
    except ResumeDocumentContractError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.code,
        ) from exc


def _validate_stored_resume_item(value: object) -> ResumeWorkspaceItemResponse:
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

    return item


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


def _read_resume_bytes(resume_id: str, version_id: int) -> bytes:
    """Capture a version's file contents while its database pointer is locked."""

    path = _resume_version_path(resume_id, version_id)
    try:
        return path.read_bytes()
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="RESUME_VERSION_STORAGE_MISSING",
        ) from exc


def _parse_resume_bytes(content: bytes) -> ResumeWorkspaceItemResponse:
    """Parse a fresh item, validating each distinct snapshot's document once."""

    value = json.loads(content.decode("utf-8"))
    digest = hashlib.sha256(content).digest()
    with _VALIDATED_SNAPSHOTS_LOCK:
        validated = digest in _VALIDATED_SNAPSHOTS
        if validated:
            _VALIDATED_SNAPSHOTS.move_to_end(digest)
    if validated:
        return ResumeWorkspaceItemResponse.model_validate(value)

    item = _validate_stored_resume_item(value)
    with _VALIDATED_SNAPSHOTS_LOCK:
        _VALIDATED_SNAPSHOTS[digest] = None
        _VALIDATED_SNAPSHOTS.move_to_end(digest)
        if len(_VALIDATED_SNAPSHOTS) > _MAX_VALIDATED_SNAPSHOTS:
            _VALIDATED_SNAPSHOTS.popitem(last=False)
    return item


def _read_resume_json(resume_id: str, version_id: int) -> dict[str, Any]:
    """Load one stored resume version JSON file."""

    return _parse_resume_bytes(_read_resume_bytes(resume_id, version_id)).model_dump(
        mode="json", by_alias=True
    )


def _resume_title(resume_item: dict[str, Any]) -> str:
    """Derive a stable display title for a resume row."""

    title = resume_item.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()[:MAX_RESUME_TITLE_LENGTH]

    resume = resume_item.get("resume")
    basic = resume.get("basic") if isinstance(resume, dict) else None
    name = basic.get("name") if isinstance(basic, dict) else None
    if isinstance(name, str) and (plain_name := resume_text_content(name).strip()):
        return plain_name[:MAX_RESUME_TITLE_LENGTH]

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
    document_locale: DocumentLocale,
) -> str:
    """Return the first available localized copy title."""

    copy_label = RESUME_COPY_LABELS[document_locale]
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
                if document_locale == "zh"
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
) -> tuple[int, int | None]:
    """Persist one resume item and create a new version when content changed."""

    resume_item = _resume_version_payload(resume_item)
    resume_id = resume_item.get("id")
    if not isinstance(resume_id, str) or not resume_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="RESUME_ID_REQUIRED",
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

    return next_version_id, obsolete_autosave_version_id


def rebind_current_resume_template_references(
    conn: Connection,
    *,
    source_template_id: str,
    target_template_ids: dict[DocumentLocale, str],
    saved_at: str,
    writes: ResumeTemplateRebindResult,
) -> None:
    """Rebind current resume snapshots while the caller owns the transaction."""

    if not conn.in_transaction:
        raise RuntimeError("A template rebind requires a caller-owned transaction.")

    for target_template_id in set(target_template_ids.values()):
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
    for row in rows:
        current_version_id = int(row["current_version_id"])
        resume_item = _read_resume_json(row["id"], current_version_id)
        if resume_item["template"] != source_template_id:
            continue
        target_template_id = target_template_ids[
            cast(DocumentLocale, resume_item["documentLocale"])
        ]

        writes.created_versions.append((row["id"], current_version_id + 1))
        _, obsolete_autosave_version_id = _save_resume_item(
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
            writes.obsolete_autosaves.append((row["id"], obsolete_autosave_version_id))


def cleanup_resume_version_files(version_files: Iterable[ResumeVersionFile]) -> None:
    """Remove unreferenced version files while excluding concurrent readers/writers."""

    files = tuple(version_files)
    if not files:
        return
    try:
        with closing(connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            for resume_id, version_id in files:
                referenced = conn.execute(
                    """
                    SELECT 1 FROM resume_versions
                    WHERE resume_id = ? AND version_id = ?
                    UNION ALL
                    SELECT 1 FROM resumes
                    WHERE id = ? AND current_version_id = ?
                    LIMIT 1
                    """,
                    (resume_id, version_id, resume_id, version_id),
                ).fetchone()
                if referenced is None:
                    _delete_resume_json(resume_id, version_id)
    except (OSError, SqliteError):
        return


def recover_unreferenced_resume_version_files() -> None:
    """Remove abandoned version files while protecting committed references."""

    root = get_settings().storage_dir / "resumes"
    if root.is_symlink() or not root.is_dir():
        return

    try:
        with closing(connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            referenced = {
                (str(row["resume_id"]), str(row["version_id"]))
                for row in conn.execute(
                    """
                    SELECT resume_id, version_id FROM resume_versions
                    UNION
                    SELECT id, current_version_id FROM resumes
                    """
                )
            }
            for resume_dir in root.iterdir():
                if (
                    resume_dir.is_symlink()
                    or not resume_dir.is_dir()
                    or not is_valid_resume_id(resume_dir.name)
                ):
                    continue
                versions = resume_dir / "versions"
                if versions.is_symlink() or not versions.is_dir():
                    continue
                for path in versions.iterdir():
                    if path.is_symlink() or not path.is_file():
                        continue
                    match = RESUME_VERSION_FILENAME_PATTERN.fullmatch(path.name)
                    if match is None:
                        continue
                    if (
                        match["temporary"]
                        or (resume_dir.name, match["version_id"]) not in referenced
                    ):
                        path.unlink(missing_ok=True)
    except (OSError, SqliteError):
        return


def _deleted_resume_preview(
    row: Row,
    item: ResumeWorkspaceItemResponse,
) -> DeletedResumeWorkspaceItemResponse:
    """Build the recycle-bin preview without editor-only job context."""

    return DeletedResumeWorkspaceItemResponse(
        id=row["id"],
        title=item.title,
        updatedAt=row["saved_at"],
        documentLocale=item.document_locale,
        resume=item.resume,
        jobBrief="",
        typography=item.typography,
        template=item.template,
        templateSettings=item.template_settings,
        deletedAt=row["deleted_at"] or row["saved_at"],
    )


def _load_resume_snapshots(
    conn: Connection,
    *,
    deleted: bool,
) -> list[tuple[Row, bytes]]:
    """Capture active or deleted rows with the exact version bytes they reference."""

    rows = conn.execute(
        """
        SELECT id, current_version_id, title, saved_at, deleted_at
        FROM resumes
        WHERE deleted = ?
        ORDER BY saved_at DESC, updated_at DESC
        """,
        (int(deleted),),
    ).fetchall()
    return [
        (row, _read_resume_bytes(row["id"], int(row["current_version_id"])))
        for row in rows
    ]


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
            detail="RESUME_NOT_FOUND",
        )

    return row


def _version_id_from_string(version_id: str) -> int:
    """Parse a public resume version id."""

    try:
        parsed = int(version_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="RESUME_VERSION_NOT_FOUND",
        ) from exc

    if parsed < 1:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="RESUME_VERSION_NOT_FOUND",
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
            detail="RESUME_VERSION_NOT_FOUND",
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
            detail="RESUME_NOT_FOUND",
        )

    if version_id is None:
        current_version_id = int(row["current_version_id"])
        if current_version_id < 1:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="RESUME_VERSION_NOT_FOUND",
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

    item = _read_resume_json(row["id"], requested_version_id)
    if not is_visible_template(conn, item["template"]):
        item = {
            **item,
            "template": load_default_template_id(conn, item["documentLocale"]),
        }
    return {
        "resume": item,
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
    document_locale = payload.get("documentLocale")

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
        "documentLocale": document_locale,
        "resume": resume_document,
        "jobBrief": job_brief if isinstance(job_brief, str) else "",
        "typography": normalized_typography,
        "template": template_id.strip(),
        "templateSettings": normalized_template_settings,
    }

    return normalized


def list_resumes(status_filter: str = "active") -> ResumeListResponse:
    """Return active resume items or deleted resume previews."""

    deleted = status_filter == "deleted"
    if status_filter not in {"active", "deleted"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="RESUME_STATUS_INVALID",
        )

    with closing(connect()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        snapshots = _load_resume_snapshots(conn, deleted=deleted)

    items = []
    for row, content in snapshots:
        item = _parse_resume_bytes(content)
        items.append(_deleted_resume_preview(row, item) if deleted else item)
    return ResumeListResponse(resumes=items)


def create_resume(payload: dict[str, Any]) -> dict[str, Any]:
    """Create a backend-owned resume and initial version."""

    saved_at = _utc_now()

    with closing(connect()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        resume_id = _allocate_resume_id(conn)
        count_row = conn.execute(
            """
            SELECT COUNT(*) AS resume_count
            FROM resumes
            WHERE deleted = 0
            """,
        ).fetchone()
        document_locale = cast(DocumentLocale, payload["documentLocale"])
        resume_number = int(count_row["resume_count"]) + 1
        default_title = (
            f"未命名简历 {resume_number}"
            if document_locale == "zh"
            else f"Untitled Resume {resume_number}"
        )
        template_id = payload.get("template")
        if not isinstance(template_id, str) or not template_id.strip():
            template_id = load_default_template_id(conn, document_locale)
        template_id = template_id.strip()
        template = resolve_visible_template(conn, template_id)
        typography = payload.get("typography")
        if typography is None:
            typography = template.get("typography")
        if "resume" in payload:
            resume_document = payload["resume"]
        else:
            preset = template["preset"]
            starter_id = get_builtin_template_preset(preset)["starter"]
            resume_document = create_empty_resume(starter_id, document_locale)

        resume_item = _normalize_resume_item_payload(
            resume_id=resume_id,
            payload={
                "title": payload.get("title", default_title),
                "documentLocale": document_locale,
                "resume": resume_document,
                "jobBrief": payload.get("jobBrief", ""),
                "typography": typography,
                "template": template_id,
                "templateSettings": payload.get("templateSettings"),
            },
            saved_at=saved_at,
        )
        version_id, _ = _save_resume_item(
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


def duplicate_resume(resume_id: str) -> dict[str, Any]:
    """Create an independent resume from the source's current content."""

    saved_at = _utc_now()
    with closing(connect()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _require_resume_row(conn, resume_id)
        if row["deleted"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="RESUME_DELETED",
            )

        current_version_id = int(row["current_version_id"])
        if current_version_id < 1:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="RESUME_VERSION_NOT_FOUND",
            )

        source_item = _read_resume_json(row["id"], current_version_id)
        document_locale = cast(DocumentLocale, source_item["documentLocale"])
        duplicate_id = _allocate_resume_id(conn)
        duplicate_title = _duplicate_resume_title(
            conn,
            source_title=_resume_title(source_item),
            document_locale=document_locale,
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
            source_template_id = load_default_template_id(conn, document_locale)

        # Keep this whitelist explicit: job context, Agent sessions, drafts, and
        # version history belong to the source resume and must not cross IDs.
        duplicate_item = _normalize_resume_item_payload(
            resume_id=duplicate_id,
            payload={
                "title": duplicate_title,
                "documentLocale": document_locale,
                "resume": source_item.get("resume"),
                "jobBrief": "",
                "typography": source_item.get("typography"),
                "template": source_template_id,
                "templateSettings": source_item.get("templateSettings"),
            },
            saved_at=saved_at,
        )
        version_id, _ = _save_resume_item(
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

    with closing(connect()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        return _load_resume_detail(conn, resume_id=resume_id)


def load_resume_in_transaction(
    conn: Connection,
    resume_id: str,
) -> dict[str, Any]:
    """Load the formal resume while a wider command owns the transaction."""

    if not conn.in_transaction:
        raise RuntimeError("A transactional resume load requires a transaction.")
    return _load_resume_detail(conn, resume_id=resume_id)


def save_resume_in_transaction(
    conn: Connection,
    resume_id: str,
    payload: dict[str, Any],
    *,
    save_mode: ResumeVersionKind,
) -> ResumeSaveTransaction:
    """Persist one full snapshot while the caller owns the SQLite transaction."""

    if not conn.in_transaction:
        raise RuntimeError("A resume save requires a caller-owned transaction.")

    saved_at = _utc_now()
    row = _require_resume_row(conn, resume_id)
    if row["deleted"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="RESUME_DELETED",
        )

    submitted_template_id = payload["template"]
    if not is_visible_template(conn, submitted_template_id.strip()):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="TEMPLATE_NOT_FOUND",
        )

    previous_version_id = int(row["current_version_id"])
    resume_item = _normalize_resume_item_payload(
        resume_id=row["id"],
        payload=payload,
        saved_at=saved_at,
    )
    version_id, obsolete_autosave_version_id = _save_resume_item(
        conn,
        resume_item=resume_item,
        saved_at=saved_at,
        deleted=False,
        deleted_at=None,
        version_kind=save_mode,
    )

    return ResumeSaveTransaction(
        detail={
            "resume": resume_item,
            "savedAt": saved_at,
            "versionId": str(version_id),
        },
        created_version=(resume_id, version_id)
        if version_id > previous_version_id
        else None,
        obsolete_autosave=(resume_id, obsolete_autosave_version_id)
        if obsolete_autosave_version_id is not None
        else None,
    )


def save_resume_document_in_transaction(
    conn: Connection,
    resume_id: str,
    resume: dict[str, Any],
    *,
    save_mode: ResumeVersionKind,
) -> ResumeSaveTransaction:
    """Persist a document edit while preserving current workspace metadata."""

    current_item = _load_resume_detail(conn, resume_id=resume_id)["resume"]
    return save_resume_in_transaction(
        conn,
        resume_id,
        {
            "title": current_item["title"],
            "documentLocale": current_item["documentLocale"],
            "resume": resume,
            "jobBrief": current_item["jobBrief"],
            "typography": current_item["typography"],
            "template": current_item["template"],
            "templateSettings": current_item.get("templateSettings"),
        },
        save_mode=save_mode,
    )


def save_resume(
    resume_id: str,
    payload: dict[str, Any],
    *,
    save_mode: ResumeVersionKind = "checkpoint",
) -> dict[str, Any]:
    """Persist the latest snapshot and retain only explicit checkpoints."""

    result: ResumeSaveTransaction | None = None
    with closing(connect()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            result = save_resume_in_transaction(
                conn,
                resume_id,
                payload,
                save_mode=save_mode,
            )
            conn.commit()
        except BaseException:
            if conn.in_transaction:
                conn.rollback()
            if result is not None and result.created_version is not None:
                cleanup_resume_version_files((result.created_version,))
            raise

    if result.obsolete_autosave is not None:
        cleanup_resume_version_files((result.obsolete_autosave,))

    return result.detail


def list_resume_versions(resume_id: str) -> dict[str, Any]:
    """List versions for one resume."""

    with closing(connect()) as conn, conn:
        conn.execute("BEGIN")
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

    with closing(connect()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        return _load_resume_detail(
            conn,
            resume_id=resume_id,
            version_id=version_id,
            include_deleted=True,
        )


def trash_resume(resume_id: str) -> dict[str, Any]:
    """Move an active resume into the recycle bin without creating a version."""

    deleted_at = _utc_now()
    with closing(connect()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _require_resume_row(conn, resume_id)
        current_version_id = int(row["current_version_id"])
        if current_version_id < 1:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="RESUME_VERSION_NOT_FOUND",
            )

        resume_item = _parse_resume_bytes(
            _read_resume_bytes(row["id"], current_version_id)
        )
        if not row["deleted"]:
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
            row = _require_resume_row(conn, resume_id)

        return {
            "resume": _deleted_resume_preview(row, resume_item).model_dump(
                mode="json", by_alias=True
            )
        }


def restore_resume(resume_id: str) -> dict[str, Any]:
    """Restore a deleted resume without creating a version."""

    with closing(connect()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _require_resume_row(conn, resume_id)
        if not row["deleted"]:
            return _load_resume_detail(conn, resume_id=row["id"])

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

    with closing(connect()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        safe_resume_id = _validate_resume_id(resume_id.strip())
        if recover_storage_deletion(conn, "resumes", safe_resume_id):
            return {"id": safe_resume_id}
        row = _require_resume_row(conn, resume_id)
        if not row["deleted"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="RESUME_NOT_DELETED",
            )

        _reject_running_agent_turns(conn, [row["id"]])

        def delete_files() -> None:
            delete_agent_session_attachments(row["id"])
            _delete_resume_storage(row["id"])

        delete_storage(
            conn,
            "resumes",
            row["id"],
            delete_files=delete_files,
            delete_rows=lambda: _delete_resume_rows(conn, [row["id"]]),
        )

    return {"id": row["id"]}


def empty_resume_trash() -> dict[str, Any]:
    """Physically delete every resume currently in the recycle bin."""

    with closing(connect()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        recover_storage_deletions(conn, "resumes")
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
