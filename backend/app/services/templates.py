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
            name,
            saved_at,
            deleted,
            deleted_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            saved_at = excluded.saved_at,
            deleted = excluded.deleted,
            deleted_at = excluded.deleted_at,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            template_id,
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
        WHERE deleted = ?
        ORDER BY saved_at DESC, updated_at DESC
        """,
        (int(deleted),),
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
            WHERE id = ? {deleted_clause}
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


def is_visible_template(conn: Connection, template_id: str) -> bool:
    """Return whether a template can be selected by a resume."""

    safe_template_id = _validate_template_id(template_id.strip())
    if safe_template_id in BUILT_IN_TEMPLATE_IDS:
        return True

    return _template_row(conn, safe_template_id) is not None


def is_deleted_template(conn: Connection, template_id: str) -> bool:
    """Return whether a custom template exists in the recycle bin."""

    safe_template_id = _validate_template_id(template_id.strip())
    if safe_template_id in BUILT_IN_TEMPLATE_IDS:
        return False

    row = _template_row(conn, safe_template_id, include_deleted=True)
    return row is not None and bool(row["deleted"])


def _build_template_item(
    *,
    template_id: str,
    payload: dict[str, Any],
    saved_at: str,
) -> dict[str, Any]:
    return {
        **payload,
        "id": _validate_template_id(template_id.strip()),
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
        template_item = _build_template_item(
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
        template_item = _build_template_item(
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

    # Imported locally because resume commands validate templates through this
    # module. The lifecycle command owns both updates in one SQLite transaction.
    from app.services.resumes import (
        cleanup_resume_version_files,
        rebind_current_resume_template_references,
    )

    deleted_at = _utc_now()
    rebind_result = None
    try:
        with connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = _require_custom_template_row(conn, template_id)
            template_item = _read_template_json(row["id"])
            default_template_id = load_default_template_id(conn)
            fallback_template_id = (
                DEFAULT_TEMPLATE_ID
                if default_template_id == row["id"]
                else default_template_id
            )

            rebind_result = rebind_current_resume_template_references(
                conn,
                source_template_id=row["id"],
                target_template_id=fallback_template_id,
                saved_at=deleted_at,
            )
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
    except Exception:
        if rebind_result is not None:
            cleanup_resume_version_files(rebind_result.created_versions)
        raise

    assert rebind_result is not None
    cleanup_resume_version_files(rebind_result.obsolete_autosaves)
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
            WHERE deleted = 1
            """,
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
        if not is_visible_template(conn, safe_template_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Template not found.",
            )

        conn.execute("BEGIN")
        store_default_template_id(conn, safe_template_id)
        conn.execute("COMMIT")

    return {"defaultTemplateId": safe_template_id}
