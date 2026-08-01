import json
import re
import secrets
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from sqlite3 import Connection, Row
from typing import Any, cast

from fastapi import HTTPException, status

from app.config import get_settings
from app.db.connection import connect
from app.services.workspace_state import (
    DEFAULT_TEMPLATE_ID,
    WORKSPACE_DATA_LOCALE,
    load_default_template_id,
    store_default_template_id,
)

TEMPLATE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
TEMPLATE_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
TEMPLATE_ID_LENGTH = 16
BUILT_IN_TEMPLATE_IDS = {
    "minimal",
    "modern",
    "compact",
    "classic",
    "executive",
    "academic",
}
DEFAULT_TYPOGRAPHY = {"fontFamily": "inter", "fontSize": 16}


@dataclass(frozen=True)
class TemplateCatalog:
    """Active templates together with the currently selected default."""

    default_template_id: str
    templates: list[dict[str, Any]]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _generate_template_id() -> str:
    suffix = "".join(
        secrets.choice(TEMPLATE_ID_ALPHABET) for _ in range(TEMPLATE_ID_LENGTH)
    )
    return f"template-{suffix}"


def _validate_template_id(template_id: str) -> str:
    """Validate that a template id is safe for database and path use."""

    if not TEMPLATE_ID_PATTERN.fullmatch(template_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Template id may only contain letters, numbers, dot, dash, "
                "or underscore."
            ),
        )

    return template_id


def _template_path(template_id: str) -> Path:
    safe_template_id = _validate_template_id(template_id)
    return get_settings().storage_dir / "templates" / safe_template_id / "current.json"


def _template_storage_dir(template_id: str) -> Path:
    safe_template_id = _validate_template_id(template_id)
    return get_settings().storage_dir / "templates" / safe_template_id


def _write_template_json(template_id: str, template_item: dict[str, Any]) -> None:
    """Write one template JSON file atomically."""

    path = _template_path(template_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(
        template_item,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
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


def _template_name(template_item: dict[str, Any]) -> str:
    name = template_item.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()

    template_id = template_item.get("id")
    return template_id if isinstance(template_id, str) else "Untitled"


def _save_template_item(
    conn: Connection,
    *,
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
            WORKSPACE_DATA_LOCALE,
            _template_name(template_item),
            saved_at,
            int(deleted),
            deleted_at,
        ),
    )

    return template_id


def _load_template_items(
    conn: Connection,
    *,
    deleted: bool,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, deleted_at, saved_at
        FROM templates
        WHERE locale = ? AND deleted = ? AND purged = 0
        ORDER BY saved_at DESC, updated_at DESC
        """,
        (WORKSPACE_DATA_LOCALE, int(deleted)),
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


def _allocate_template_id(conn: Connection) -> str:
    for _ in range(20):
        template_id = _generate_template_id()
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


def load_template_catalog() -> TemplateCatalog:
    """Load the active template catalog and its default selection."""

    with connect() as conn:
        return TemplateCatalog(
            default_template_id=load_default_template_id(conn),
            templates=_load_template_items(conn, deleted=False),
        )


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
                deleted=status_filter == "deleted",
            )
        }


def create_template(payload: dict[str, Any]) -> dict[str, Any]:
    """Create a backend-owned custom template."""

    saved_at = _utc_now()
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
            template_item=template_item,
            saved_at=saved_at,
            deleted=False,
            deleted_at=None,
        )
        conn.execute("COMMIT")

    return {"template": template_item}


def update_template(template_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Replace one active custom template."""

    saved_at = _utc_now()
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
            template_item=template_item,
            saved_at=saved_at,
            deleted=False,
            deleted_at=None,
        )
        conn.execute("COMMIT")

    return {"template": template_item}


def trash_template(template_id: str) -> dict[str, Any]:
    """Move a custom template into the recycle bin."""

    deleted_at = _utc_now()
    with connect() as conn:
        row = _require_custom_template_row(conn, template_id)
        template_item = _read_template_json(row["id"])
        default_template_id = load_default_template_id(conn)

        conn.execute("BEGIN")
        if default_template_id == row["id"]:
            store_default_template_id(conn, DEFAULT_TEMPLATE_ID)
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
            (WORKSPACE_DATA_LOCALE,),
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
        store_default_template_id(conn, safe_template_id)
        conn.execute("COMMIT")

    return {"defaultTemplateId": safe_template_id}
