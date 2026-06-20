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
from app.services.model_configs import list_llm_configs

SUPPORTED_LOCALES = {"zh", "en"}
THEME_MODES = {"light", "dark", "system"}
WORKSPACE_DATA_LOCALE = "__workspace__"
RESUME_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
RESUME_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
RESUME_ID_LENGTH = 16
DEFAULT_TEMPLATE_ID = "minimal"
BUILT_IN_TEMPLATE_IDS = {"minimal", "modern", "compact"}
DEFAULT_TYPOGRAPHY = {"fontFamily": "inter", "fontSize": 16}
RESUME_VERSION_EXCLUDED_KEYS = {"deletedAt"}
USER_SETTINGS_KEYS = {"agentSettings", "theme"}
VOLATILE_HASH_KEYS = {"savedAt", "updatedAt"}
DEFAULT_AGENT_SETTINGS = {
    "defaultModelId": "",
    "responseLanguage": "follow",
    "behaviorMode": "balanced",
    "confirmationMode": "always",
}
AGENT_RESPONSE_LANGUAGES = {"follow", "zh", "en"}
AGENT_BEHAVIOR_MODES = {"balanced", "strict", "aggressive"}
AGENT_CONFIRMATION_MODES = {"always", "lowRiskAuto", "suggestOnly"}


def normalize_locale(locale: str) -> str:
    """Return a supported locale, falling back to English."""

    return locale if locale in SUPPORTED_LOCALES else "en"


def workspace_data_locale() -> str:
    """Return the locale column value used for language-independent workspace data."""

    return WORKSPACE_DATA_LOCALE


def generate_resume_id() -> str:
    """Generate a compact backend-owned resume id."""

    return "".join(
        secrets.choice(RESUME_ID_ALPHABET) for _ in range(RESUME_ID_LENGTH)
    )


def generate_template_id() -> str:
    """Generate a backend-owned custom template id."""

    return f"template-{generate_resume_id()}"


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


def allocate_resume_id() -> str:
    """Generate a resume id that does not currently exist in storage."""

    with connect() as conn:
        return _allocate_resume_id(conn)


def utc_now() -> str:
    """Return the current UTC time in frontend-compatible ISO format."""

    return (
        datetime.now(UTC)
        .isoformat(timespec="milliseconds")
        .replace(
            "+00:00",
            "Z",
        )
    )


def _attach_model_configs(
    conn: Connection,
    workspace: dict[str, Any],
) -> dict[str, Any]:
    # Model API keys live in llm_configs, so workspace responses only receive
    # backend-sanitized config previews at response time.
    return {
        **workspace,
        "modelConfigs": [
            item.model_dump(by_alias=True) for item in list_llm_configs(conn)
        ],
    }


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


def _validate_template_id(template_id: str) -> str:
    """Validate that a template id is safe for database and path use."""

    if not RESUME_ID_PATTERN.fullmatch(template_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Template id may only contain letters, numbers, dot, dash, "
                "or underscore."
            ),
        )

    return template_id


def _template_path(template_id: str) -> Path:
    """Build the storage path for one template JSON file."""

    safe_template_id = _validate_template_id(template_id)
    return get_settings().storage_dir / "templates" / safe_template_id / "current.json"


def _template_storage_dir(template_id: str) -> Path:
    """Build the storage directory for all files belonging to one template."""

    safe_template_id = _validate_template_id(template_id)
    return get_settings().storage_dir / "templates" / safe_template_id


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


def _write_template_json(template_id: str, template_item: dict[str, Any]) -> None:
    """Write one template JSON file atomically."""

    path = _template_path(template_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = _canonical_json(template_item)
    temp_path = path.with_suffix(".json.tmp")
    temp_path.write_text(content, encoding="utf-8")
    temp_path.replace(path)


def _read_template_json(template_id: str) -> dict[str, Any]:
    """Load one stored template JSON file."""

    path = _template_path(template_id)
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Template JSON is missing.",
        )

    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _normalize_agent_settings(value: Any) -> dict[str, str]:
    """Keep only supported Agent settings, tolerating older settings payloads."""

    settings = dict(DEFAULT_AGENT_SETTINGS)
    if not isinstance(value, dict):
        return settings

    default_model_id = value.get("defaultModelId")
    if isinstance(default_model_id, str):
        settings["defaultModelId"] = default_model_id

    response_language = value.get("responseLanguage")
    if (
        isinstance(response_language, str)
        and response_language in AGENT_RESPONSE_LANGUAGES
    ):
        settings["responseLanguage"] = response_language

    behavior_mode = value.get("behaviorMode")
    if isinstance(behavior_mode, str) and behavior_mode in AGENT_BEHAVIOR_MODES:
        settings["behaviorMode"] = behavior_mode

    confirmation_mode = value.get("confirmationMode")
    if (
        isinstance(confirmation_mode, str)
        and confirmation_mode in AGENT_CONFIRMATION_MODES
    ):
        settings["confirmationMode"] = confirmation_mode

    return settings


def _normalize_theme(value: Any) -> str | None:
    """Return a persisted theme value when it is supported."""

    return value if isinstance(value, str) and value in THEME_MODES else None


def _normalize_user_settings(value: Any) -> dict[str, Any]:
    """Normalize settings-page preferences loaded from the JSON settings file."""

    if not isinstance(value, dict):
        return {}

    settings: dict[str, Any] = {}

    locale = value.get("locale")
    if isinstance(locale, str) and locale in SUPPORTED_LOCALES:
        settings["locale"] = locale

    theme = _normalize_theme(value.get("theme"))
    if theme is not None:
        settings["theme"] = theme

    if "agentSettings" in value:
        settings["agentSettings"] = _normalize_agent_settings(
            value.get("agentSettings")
        )

    return settings


def _load_user_settings() -> dict[str, Any]:
    """Load persisted settings-page preferences from the configured JSON path."""

    path = get_settings().user_settings_path
    if not path.exists():
        return {}

    try:
        return _normalize_user_settings(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_user_settings(settings: dict[str, Any]) -> None:
    """Write settings-page preferences atomically."""

    path = get_settings().user_settings_path
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    temp_path.write_text(_canonical_json(settings), encoding="utf-8")
    temp_path.replace(path)


def save_user_settings(locale: str, settings: dict[str, Any]) -> dict[str, Any]:
    """Persist settings-page preferences without saving the whole workspace."""

    normalized_locale = normalize_locale(locale)
    next_settings = _load_user_settings()
    next_settings["locale"] = normalized_locale

    theme = _normalize_theme(settings.get("theme"))
    if theme is not None:
        next_settings["theme"] = theme

    if "agentSettings" in settings:
        next_settings["agentSettings"] = _normalize_agent_settings(
            settings.get("agentSettings")
        )

    next_settings = _normalize_user_settings(next_settings)
    _write_user_settings(next_settings)
    return next_settings


def _apply_user_settings(state: dict[str, Any]) -> dict[str, Any]:
    """Merge JSON-backed settings into a workspace response."""

    settings = _load_user_settings()
    workspace = {
        key: value for key, value in state.items() if key not in USER_SETTINGS_KEYS
    }

    workspace["agentSettings"] = _normalize_agent_settings(
        settings.get("agentSettings")
    )

    theme = _normalize_theme(settings.get("theme"))
    if theme is not None:
        workspace["theme"] = theme

    return workspace


def _load_workspace_state(conn: Connection) -> dict[str, Any]:
    """Load explicit workspace state with sensible defaults."""

    row = conn.execute(
        """
        SELECT default_template_id
        FROM workspace_state
        WHERE id = 1
        """,
    ).fetchone()

    if row is None:
        return {
            "defaultTemplateId": DEFAULT_TEMPLATE_ID,
        }

    return {"defaultTemplateId": row["default_template_id"] or DEFAULT_TEMPLATE_ID}


def _save_workspace_default_template(conn: Connection, template_id: str) -> None:
    """Persist the workspace default template id."""

    conn.execute(
        """
        INSERT INTO workspace_state (
            id,
            default_template_id,
            updated_at
        )
        VALUES (1, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            default_template_id = excluded.default_template_id,
            updated_at = CURRENT_TIMESTAMP
        """,
        (template_id,),
    )


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


def _template_name(template_item: dict[str, Any]) -> str:
    """Derive a stable display name for a template row."""

    name = template_item.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()

    template_id = template_item.get("id")
    return template_id if isinstance(template_id, str) else "Untitled"


def _save_template_item(
    conn: Connection,
    *,
    locale: str,
    template_item: dict[str, Any],
    saved_at: str,
    deleted: bool,
    deleted_at: str | None = None,
) -> str:
    """Persist one template item without creating versions."""

    template_id = template_item.get("id")
    if not isinstance(template_id, str) or not template_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Template id is required.",
        )
    template_id = _validate_template_id(template_id.strip())
    _write_template_json(template_id, template_item)

    conn.execute(
        """
        INSERT INTO templates (
            id,
            locale,
            name,
            saved_at,
            deleted,
            deleted_at,
            purged,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, 0, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            locale = excluded.locale,
            name = excluded.name,
            saved_at = excluded.saved_at,
            deleted = excluded.deleted,
            deleted_at = excluded.deleted_at,
            purged = 0,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            template_id,
            locale,
            _template_name(template_item),
            saved_at,
            int(deleted),
            deleted_at,
        ),
    )

    return template_id


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

    return {
        "id": row["id"],
        "title": row["title"] or _resume_title(resume_item),
        "updatedAt": row["saved_at"],
        "resume": {
            "basic": basic if isinstance(basic, dict) else {},
            "sections": [],
        },
        "jobBrief": "",
        "typography": resume_item.get("typography"),
        "template": resume_item.get("template"),
        "templateSettings": resume_item.get("templateSettings"),
        "deletedAt": deleted_at,
    }


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


def _load_template_items(
    conn: Connection,
    *,
    locale: str,
    deleted: bool,
) -> list[dict[str, Any]]:
    """Load active or deleted templates for a locale."""

    rows = conn.execute(
        """
        SELECT id, deleted_at, saved_at
        FROM templates
        WHERE locale = ? AND deleted = ? AND purged = 0
        ORDER BY saved_at DESC, updated_at DESC
        """,
        (locale, int(deleted)),
    ).fetchall()

    items: list[dict[str, Any]] = []
    for row in rows:
        item = _read_template_json(row["id"])
        if deleted:
            item = {
                **item,
                "deletedAt": row["deleted_at"] or row["saved_at"],
            }
        items.append(item)

    return items


def load_workspace(locale: str) -> dict[str, Any]:
    """Load the current workspace payload for a locale."""

    data_locale = workspace_data_locale()

    with connect() as conn:
        state = _apply_user_settings(_load_workspace_state(conn))
        workspace = {
            **state,
            "customTemplates": _load_template_items(
                conn,
                locale=data_locale,
                deleted=False,
            ),
            "deletedTemplates": _load_template_items(
                conn,
                locale=data_locale,
                deleted=True,
            ),
        }

        return _attach_model_configs(conn, workspace)


def _default_template_id(state: dict[str, Any]) -> str:
    """Read the current default template id from workspace state."""

    template_id = state.get("defaultTemplateId")
    return (
        template_id.strip()
        if isinstance(template_id, str) and template_id.strip()
        else DEFAULT_TEMPLATE_ID
    )


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

    return row


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

    data_locale = workspace_data_locale()
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

    data_locale = workspace_data_locale()
    saved_at = utc_now()

    with connect() as conn:
        conn.execute("BEGIN")
        state = _load_workspace_state(conn)
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
            template_id = _default_template_id(state)

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


def load_resume(resume_id: str) -> dict[str, Any]:
    """Load the current detail for one active resume."""

    with connect() as conn:
        return _load_resume_detail(conn, resume_id=resume_id)


def save_resume(resume_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Persist a full resume update and create a version when content changed."""

    saved_at = utc_now()
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
            locale=workspace_data_locale(),
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

    deleted_at = utc_now()
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
    return {"id": row["id"]}


def empty_resume_trash() -> dict[str, Any]:
    """Physically delete every resume currently in the recycle bin."""

    data_locale = workspace_data_locale()
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

    return {"deletedCount": len(resume_ids)}


def _allocate_template_id(conn: Connection) -> str:
    """Generate a custom template id that does not currently exist."""

    for _ in range(20):
        template_id = generate_template_id()
        row = conn.execute(
            "SELECT 1 FROM templates WHERE id = ?",
            (template_id,),
        ).fetchone()
        if row is None:
            return template_id

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Failed to allocate a template id.",
    )


def _template_row(
    conn: Connection,
    template_id: str,
    *,
    include_deleted: bool = False,
) -> Row | None:
    """Fetch one custom template row."""

    safe_template_id = _validate_template_id(template_id.strip())
    deleted_clause = "" if include_deleted else "AND deleted = 0"
    return cast(
        Row | None,
        conn.execute(
            f"""
            SELECT id, name, saved_at, deleted, deleted_at
            FROM templates
            WHERE id = ? AND purged = 0 {deleted_clause}
            """,
            (safe_template_id,),
        ).fetchone(),
    )


def _require_custom_template_row(
    conn: Connection,
    template_id: str,
    *,
    include_deleted: bool = False,
) -> Row:
    """Return a custom template row or raise a public error."""

    safe_template_id = _validate_template_id(template_id.strip())
    if safe_template_id in BUILT_IN_TEMPLATE_IDS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Built-in templates cannot be changed.",
        )

    row = _template_row(conn, safe_template_id, include_deleted=include_deleted)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found.",
        )

    return row


def _is_visible_template(conn: Connection, template_id: str) -> bool:
    """Return whether a template id can currently be selected."""

    safe_template_id = _validate_template_id(template_id.strip())
    if safe_template_id in BUILT_IN_TEMPLATE_IDS:
        return True

    return _template_row(conn, safe_template_id) is not None


def _normalize_template_payload(
    *,
    template_id: str,
    payload: dict[str, Any],
    saved_at: str,
) -> dict[str, Any]:
    """Normalize custom template payload while preserving internal ids."""

    preset = payload.get("preset")
    name = payload.get("name")
    description = payload.get("description")
    layout = payload.get("layout")
    typography = payload.get("typography")
    settings = payload.get("settings")

    return {
        "id": _validate_template_id(template_id.strip()),
        "preset": preset if isinstance(preset, str) and preset.strip() else "minimal",
        "name": name.strip()
        if isinstance(name, str) and name.strip()
        else "Custom Template",
        "description": description.strip() if isinstance(description, str) else "",
        "layout": layout if isinstance(layout, dict) else {"images": []},
        "typography": (
            typography if isinstance(typography, dict) else DEFAULT_TYPOGRAPHY
        ),
        "settings": settings if isinstance(settings, dict) else {},
        "updatedAt": saved_at,
        "isBuiltIn": False,
    }


def list_templates(status_filter: str = "active") -> dict[str, Any]:
    """Return active or deleted custom templates."""

    if status_filter not in {"active", "deleted"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported template status filter.",
        )

    with connect() as conn:
        return {
            "templates": _load_template_items(
                conn,
                locale=workspace_data_locale(),
                deleted=status_filter == "deleted",
            )
        }


def create_template(payload: dict[str, Any]) -> dict[str, Any]:
    """Create a backend-owned custom template."""

    saved_at = utc_now()
    with connect() as conn:
        conn.execute("BEGIN")
        template_id = _allocate_template_id(conn)
        template_item = _normalize_template_payload(
            template_id=template_id,
            payload=payload,
            saved_at=saved_at,
        )
        _save_template_item(
            conn,
            locale=workspace_data_locale(),
            template_item=template_item,
            saved_at=saved_at,
            deleted=False,
            deleted_at=None,
        )
        conn.execute("COMMIT")

    return {"template": template_item}


def update_template(template_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Replace one active custom template."""

    saved_at = utc_now()
    with connect() as conn:
        row = _require_custom_template_row(conn, template_id)
        template_item = _normalize_template_payload(
            template_id=row["id"],
            payload=payload,
            saved_at=saved_at,
        )

        conn.execute("BEGIN")
        _save_template_item(
            conn,
            locale=workspace_data_locale(),
            template_item=template_item,
            saved_at=saved_at,
            deleted=False,
            deleted_at=None,
        )
        conn.execute("COMMIT")

    return {"template": template_item}


def trash_template(template_id: str) -> dict[str, Any]:
    """Move a custom template into the recycle bin."""

    deleted_at = utc_now()
    with connect() as conn:
        row = _require_custom_template_row(conn, template_id)
        template_item = _read_template_json(row["id"])
        state = _load_workspace_state(conn)

        conn.execute("BEGIN")
        if state["defaultTemplateId"] == row["id"]:
            _save_workspace_default_template(conn, DEFAULT_TEMPLATE_ID)
        conn.execute(
            """
            UPDATE templates
            SET deleted = 1,
                deleted_at = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (deleted_at, row["id"]),
        )
        conn.execute("COMMIT")

    return {
        "template": {
            **template_item,
            "deletedAt": deleted_at,
        }
    }


def restore_template(template_id: str) -> dict[str, Any]:
    """Restore one deleted custom template."""

    with connect() as conn:
        row = _require_custom_template_row(
            conn,
            template_id,
            include_deleted=True,
        )
        if not row["deleted"]:
            return {"template": _read_template_json(row["id"])}

        conn.execute("BEGIN")
        conn.execute(
            """
            UPDATE templates
            SET deleted = 0,
                deleted_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (row["id"],),
        )
        conn.execute("COMMIT")

        return {"template": _read_template_json(row["id"])}


def delete_template_forever(template_id: str) -> dict[str, Any]:
    """Physically delete one already-deleted custom template."""

    with connect() as conn:
        row = _require_custom_template_row(
            conn,
            template_id,
            include_deleted=True,
        )
        if not row["deleted"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only deleted templates can be permanently deleted.",
            )

        conn.execute("BEGIN")
        conn.execute("DELETE FROM templates WHERE id = ?", (row["id"],))
        conn.execute("COMMIT")

    shutil.rmtree(_template_storage_dir(row["id"]), ignore_errors=True)
    return {"id": row["id"]}


def empty_template_trash() -> dict[str, Any]:
    """Physically delete every custom template currently in the recycle bin."""

    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id
            FROM templates
            WHERE locale = ? AND deleted = 1 AND purged = 0
            """,
            (workspace_data_locale(),),
        ).fetchall()
        template_ids = [row["id"] for row in rows]
        if template_ids:
            conn.execute("BEGIN")
            conn.executemany(
                "DELETE FROM templates WHERE id = ?",
                [(template_id,) for template_id in template_ids],
            )
            conn.execute("COMMIT")

    for deleted_template_id in template_ids:
        shutil.rmtree(_template_storage_dir(deleted_template_id), ignore_errors=True)

    return {"deletedCount": len(template_ids)}


def save_default_template(template_id: str) -> dict[str, Any]:
    """Persist the workspace default template after validating the reference."""

    safe_template_id = _validate_template_id(template_id.strip())
    with connect() as conn:
        if not _is_visible_template(conn, safe_template_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Template not found.",
            )

        conn.execute("BEGIN")
        _save_workspace_default_template(conn, safe_template_id)
        conn.execute("COMMIT")

    return {"defaultTemplateId": safe_template_id}
