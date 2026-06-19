import hashlib
import json
import re
import secrets
from datetime import UTC, datetime
from pathlib import Path
from sqlite3 import Connection, Row
from typing import Any, cast

from fastapi import HTTPException, status

from app.config import get_settings
from app.db.connection import connect
from app.services.llm_secrets import sanitize_workspace_payload
from app.services.model_configs import list_llm_configs, sync_llm_configs

SUPPORTED_LOCALES = {"zh", "en"}
THEME_MODES = {"light", "dark", "system"}
WORKSPACE_DATA_LOCALE = "__workspace__"
RESUME_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
RESUME_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
RESUME_ID_LENGTH = 16
USER_SETTINGS_KEYS = {"agentSettings", "theme"}
WORKSPACE_STATE_EXCLUDED_KEYS = {
    "resumes",
    "deletedResumes",
    "customTemplates",
    "deletedTemplates",
    "modelConfigs",
    "modelConfig",
    *USER_SETTINGS_KEYS,
}
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


def allocate_resume_id() -> str:
    """Generate a resume id that does not currently exist in storage."""

    with connect() as conn:
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


def _coerce_resume_items(value: Any) -> list[dict[str, Any]]:
    """Return only dictionary resume items from a possible list value."""

    if not isinstance(value, list):
        return []

    return [item for item in value if isinstance(item, dict)]


def _coerce_template_items(value: Any) -> list[dict[str, Any]]:
    """Return only dictionary template items from a possible list value."""

    if not isinstance(value, list):
        return []

    return [item for item in value if isinstance(item, dict)]


def _workspace_state_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Extract non-resume workspace state for SQLite storage."""

    return {
        key: value
        for key, value in snapshot.items()
        if key not in WORKSPACE_STATE_EXCLUDED_KEYS
    }


def _normalize_agent_settings(value: Any) -> dict[str, str]:
    """Keep only supported Agent settings, tolerating older workspace snapshots."""

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


def _load_workspace_state(conn: Connection, locale: str) -> dict[str, Any]:
    """Load shared workspace state for a locale with sensible defaults."""

    row = conn.execute(
        """
        SELECT state_json
        FROM workspace_state
        WHERE locale = ?
        """,
        (locale,),
    ).fetchone()

    if row is None:
        return {
            "defaultTemplateId": "minimal",
            "savedAt": "",
        }

    state = cast(dict[str, Any], json.loads(row["state_json"]))
    return {key: value for key, value in state.items() if key not in USER_SETTINGS_KEYS}


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
) -> tuple[str, int]:
    """Persist one resume item and create a new version when content changed."""

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
                purged
            )
            VALUES (?, ?, 0, ?, ?, ?, 0)
            """,
            (
                resume_id,
                locale,
                _resume_title(resume_item),
                saved_at,
                int(deleted),
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
    elif not _resume_version_path(resume_id, next_version_id).exists():
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
            purged,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, 0, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            locale = excluded.locale,
            current_version_id = excluded.current_version_id,
            title = excluded.title,
            saved_at = excluded.saved_at,
            deleted = excluded.deleted,
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
            purged,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, 0, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            locale = excluded.locale,
            name = excluded.name,
            saved_at = excluded.saved_at,
            deleted = excluded.deleted,
            purged = 0,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            template_id,
            locale,
            _template_name(template_item),
            saved_at,
            int(deleted),
        ),
    )

    return template_id


def _mark_missing_resumes_purged(
    conn: Connection,
    *,
    locale: str,
    seen_resume_ids: set[str],
) -> None:
    """Mark resumes absent from the latest snapshot as purged."""

    if not seen_resume_ids:
        conn.execute(
            """
            UPDATE resumes
            SET purged = 1, updated_at = CURRENT_TIMESTAMP
            WHERE locale = ?
            """,
            (locale,),
        )
        return

    placeholders = ",".join("?" for _ in seen_resume_ids)
    conn.execute(
        f"""
        UPDATE resumes
        SET purged = 1, updated_at = CURRENT_TIMESTAMP
        WHERE locale = ? AND id NOT IN ({placeholders})
        """,
        (locale, *seen_resume_ids),
    )


def _mark_missing_templates_purged(
    conn: Connection,
    *,
    locale: str,
    seen_template_ids: set[str],
) -> None:
    """Mark templates absent from the latest snapshot as purged."""

    if not seen_template_ids:
        conn.execute(
            """
            UPDATE templates
            SET purged = 1, updated_at = CURRENT_TIMESTAMP
            WHERE locale = ?
            """,
            (locale,),
        )
        return

    placeholders = ",".join("?" for _ in seen_template_ids)
    conn.execute(
        f"""
        UPDATE templates
        SET purged = 1, updated_at = CURRENT_TIMESTAMP
        WHERE locale = ? AND id NOT IN ({placeholders})
        """,
        (locale, *seen_template_ids),
    )


def _save_workspace_rows(
    conn: Connection,
    *,
    data_locale: str,
    snapshot: dict[str, Any],
    saved_at: str,
) -> dict[str, str]:
    """Persist workspace state, resumes, versions, and model config metadata."""

    persisted_snapshot = {
        **snapshot,
        "savedAt": saved_at,
    }
    model_configs = persisted_snapshot.get("modelConfigs")

    if isinstance(model_configs, list):
        # Keep llm_configs queryable without duplicating any API key values.
        sync_llm_configs(
            conn,
            model_configs,
            disable_missing=True,
        )

    state_snapshot, _ = sanitize_workspace_payload(persisted_snapshot)
    state = _workspace_state_from_snapshot(state_snapshot)
    conn.execute(
        """
        INSERT INTO workspace_state (
            locale,
            state_json,
            saved_at,
            updated_at
        )
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(locale) DO UPDATE SET
            state_json = excluded.state_json,
            saved_at = excluded.saved_at,
            updated_at = CURRENT_TIMESTAMP
        """,
        (data_locale, _canonical_json(state), saved_at),
    )

    seen_resume_ids: set[str] = set()
    max_version_id = 0
    for resume_item in _coerce_resume_items(persisted_snapshot.get("resumes")):
        resume_id, version_id = _save_resume_item(
            conn,
            locale=data_locale,
            resume_item=resume_item,
            saved_at=saved_at,
            deleted=False,
        )
        seen_resume_ids.add(resume_id)
        max_version_id = max(max_version_id, version_id)

    for resume_item in _coerce_resume_items(persisted_snapshot.get("deletedResumes")):
        resume_id, version_id = _save_resume_item(
            conn,
            locale=data_locale,
            resume_item=resume_item,
            saved_at=saved_at,
            deleted=True,
        )
        seen_resume_ids.add(resume_id)
        max_version_id = max(max_version_id, version_id)

    seen_template_ids: set[str] = set()
    for template_item in _coerce_template_items(
        persisted_snapshot.get("customTemplates")
    ):
        template_id = _save_template_item(
            conn,
            locale=data_locale,
            template_item=template_item,
            saved_at=saved_at,
            deleted=False,
        )
        seen_template_ids.add(template_id)

    for template_item in _coerce_template_items(
        persisted_snapshot.get("deletedTemplates")
    ):
        template_id = _save_template_item(
            conn,
            locale=data_locale,
            template_item=template_item,
            saved_at=saved_at,
            deleted=True,
        )
        seen_template_ids.add(template_id)

    _mark_missing_resumes_purged(
        conn,
        locale=data_locale,
        seen_resume_ids=seen_resume_ids,
    )
    _mark_missing_templates_purged(
        conn,
        locale=data_locale,
        seen_template_ids=seen_template_ids,
    )

    if max_version_id == 0:
        max_version_id = _max_resume_version(conn, data_locale)

    return {
        "savedAt": saved_at,
        "versionId": str(max_version_id),
    }


def _max_resume_version(conn: Connection, locale: str) -> int:
    """Return the highest current resume version for a locale."""

    row = conn.execute(
        """
        SELECT COALESCE(MAX(current_version_id), 0) AS max_version
        FROM resumes
        WHERE locale = ? AND purged = 0
        """,
        (locale,),
    ).fetchone()

    return int(row["max_version"] or 0)


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
        SELECT id, current_version_id
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

        items.append(_read_resume_json(row["id"], version_id))

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
        SELECT id
        FROM templates
        WHERE locale = ? AND deleted = ? AND purged = 0
        ORDER BY saved_at DESC, updated_at DESC
        """,
        (locale, int(deleted)),
    ).fetchall()

    return [_read_template_json(row["id"]) for row in rows]


def _version_saved_at(conn: Connection, locale: str, version_id: int) -> str | None:
    """Return the saved timestamp associated with a workspace version."""

    row = conn.execute(
        """
        SELECT MAX(rv.saved_at) AS saved_at
        FROM resume_versions rv
        INNER JOIN resumes r ON r.id = rv.resume_id
        WHERE r.locale = ? AND r.purged = 0 AND rv.version_id = ?
        """,
        (locale, version_id),
    ).fetchone()
    if row is None or row["saved_at"] is None:
        return None

    return str(row["saved_at"])


def load_workspace(locale: str) -> dict[str, Any]:
    """Load the current workspace payload for a locale."""

    data_locale = workspace_data_locale()

    with connect() as conn:
        state = _apply_user_settings(_load_workspace_state(conn, data_locale))
        workspace = {
            **state,
            "resumes": _load_resume_items(
                conn,
                locale=data_locale,
                deleted=False,
            ),
            "deletedResumes": _load_resume_items(
                conn,
                locale=data_locale,
                deleted=True,
            ),
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


def save_workspace(_locale: str, snapshot: dict[str, Any]) -> dict[str, str]:
    """Save a workspace snapshot and return save metadata."""

    data_locale = workspace_data_locale()
    saved_at = snapshot.get("savedAt")
    if not isinstance(saved_at, str) or not saved_at.strip():
        saved_at = utc_now()

    with connect() as conn:
        conn.execute("BEGIN")
        result = _save_workspace_rows(
            conn,
            data_locale=data_locale,
            snapshot=snapshot,
            saved_at=saved_at,
        )
        conn.execute("COMMIT")

    return result


def list_workspace_versions(locale: str) -> list[dict[str, str]]:
    """List workspace version numbers available for a locale."""

    data_locale = workspace_data_locale()

    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
                rv.version_id,
                MAX(rv.saved_at) AS saved_at
            FROM resume_versions rv
            INNER JOIN resumes r ON r.id = rv.resume_id
            WHERE r.locale = ? AND r.purged = 0
            GROUP BY rv.version_id
            ORDER BY rv.version_id DESC
            """,
            (data_locale,),
        ).fetchall()

    return [
        {
            "versionId": str(row["version_id"]),
            "savedAt": row["saved_at"],
        }
        for row in rows
    ]


def load_workspace_version(locale: str, version_id: str) -> dict[str, Any]:
    """Load a workspace snapshot reconstructed from a specific version."""

    data_locale = workspace_data_locale()

    try:
        requested_version = int(version_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace version not found.",
        ) from exc

    if requested_version < 1:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace version not found.",
        )

    with connect() as conn:
        if requested_version > _max_resume_version(conn, data_locale):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workspace version not found.",
            )

        saved_at = _version_saved_at(conn, data_locale, requested_version)
        state = _apply_user_settings(
            {
                **_load_workspace_state(conn, data_locale),
                "savedAt": saved_at or "",
            }
        )
        workspace = {
            **state,
            "resumes": _load_resume_items(
                conn,
                locale=data_locale,
                deleted=False,
                requested_version=requested_version,
            ),
            "deletedResumes": _load_resume_items(
                conn,
                locale=data_locale,
                deleted=True,
                requested_version=requested_version,
            ),
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


def migrate_legacy_workspace_snapshots(conn: Connection) -> None:
    """Move legacy whole-workspace snapshots into versioned resume storage."""

    tables = {
        row["name"]
        for row in conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            """,
        ).fetchall()
    }
    if "workspace_snapshots" not in tables and "workspace_versions" not in tables:
        return

    if conn.execute("SELECT 1 FROM resumes LIMIT 1").fetchone() is not None:
        return

    legacy_rows: list[Row] = []
    if "workspace_versions" in tables:
        legacy_rows.extend(
            conn.execute(
                """
                SELECT locale, snapshot_json, saved_at
                FROM workspace_versions
                ORDER BY saved_at ASC, created_at ASC
                """,
            ).fetchall()
        )

    if not legacy_rows and "workspace_snapshots" in tables:
        legacy_rows.extend(
            conn.execute(
                """
                SELECT locale, snapshot_json, saved_at
                FROM workspace_snapshots
                ORDER BY saved_at ASC, created_at ASC
                """,
            ).fetchall()
        )

    for row in legacy_rows:
        snapshot = json.loads(row["snapshot_json"])
        if not isinstance(snapshot, dict):
            continue

        _save_workspace_rows(
            conn,
            data_locale=workspace_data_locale(),
            snapshot=snapshot,
            saved_at=row["saved_at"],
        )


def migrate_workspace_templates(conn: Connection) -> None:
    """Move templates out of workspace_state into template storage."""

    rows = conn.execute(
        """
        SELECT locale, state_json, saved_at
        FROM workspace_state
        """
    ).fetchall()

    for row in rows:
        state = json.loads(row["state_json"])
        if not isinstance(state, dict):
            continue

        has_templates = "customTemplates" in state or "deletedTemplates" in state
        if not has_templates:
            continue

        data_locale = workspace_data_locale()
        saved_at = row["saved_at"]
        seen_template_ids: set[str] = set()
        for template_item in _coerce_template_items(state.get("customTemplates")):
            seen_template_ids.add(
                _save_template_item(
                    conn,
                    locale=data_locale,
                    template_item=template_item,
                    saved_at=saved_at,
                    deleted=False,
                )
            )

        for template_item in _coerce_template_items(state.get("deletedTemplates")):
            seen_template_ids.add(
                _save_template_item(
                    conn,
                    locale=data_locale,
                    template_item=template_item,
                    saved_at=saved_at,
                    deleted=True,
                )
            )

        _mark_missing_templates_purged(
            conn,
            locale=data_locale,
            seen_template_ids=seen_template_ids,
        )
        conn.execute(
            """
            UPDATE workspace_state
            SET state_json = ?, updated_at = CURRENT_TIMESTAMP
            WHERE locale = ?
            """,
            (_canonical_json(_workspace_state_from_snapshot(state)), row["locale"]),
        )


def find_resume(workspace: dict[str, Any], resume_id: str) -> dict[str, Any] | None:
    """Find one resume item in a workspace payload by id."""

    resumes = workspace.get("resumes")
    if not isinstance(resumes, list):
        return None

    for item in resumes:
        if isinstance(item, dict) and item.get("id") == resume_id:
            return item

    return None
