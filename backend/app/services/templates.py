import json
import os
import re
import secrets
import shutil
import tempfile
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from sqlite3 import Connection, Row
from typing import Any, cast

from fastapi import HTTPException, status

from app.config import get_settings
from app.db.connection import connect
from app.document_locales import DOCUMENT_LOCALES, DocumentLocale
from app.services.storage_deletions import (
    delete_storage,
    recover_storage_deletion,
    recover_storage_deletions,
    storage_id_reserved,
)
from app.services.template_presets import (
    BUILT_IN_TEMPLATE_IDS,
    get_builtin_template_preset,
)
from app.services.workspace_state import (
    DEFAULT_TEMPLATE_ID,
    load_default_template_ids,
    store_default_template_id,
)

TEMPLATE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
TEMPLATE_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
TEMPLATE_ID_LENGTH = 16


@dataclass(frozen=True)
class TemplateCatalog:
    """Active templates together with the currently selected default."""

    default_template_ids: dict[DocumentLocale, str]
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


def _delete_template_storage(template_id: str) -> None:
    """Delete template files while treating an absent directory as deleted."""

    try:
        shutil.rmtree(_template_storage_dir(template_id))
    except FileNotFoundError:
        pass


def _write_template_json(template_id: str, template_item: dict[str, Any]) -> None:
    """Write one template JSON file atomically."""

    path = _template_path(template_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(
        template_item,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    _replace_template_json(path, content)


def _replace_template_json(path: Path, content: bytes) -> None:
    """Atomically replace one template JSON file without sharing temp paths."""

    descriptor, temp_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as temp_file:
            temp_file.write(content)
        os.replace(temp_path, path)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def _restore_template_json(template_id: str, content: bytes | None) -> None:
    """Restore the file state captured before an uncommitted template write."""

    path = _template_path(template_id)
    if content is None:
        path.unlink(missing_ok=True)
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    _replace_template_json(path, content)


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
) -> None:
    """Persist one template item without creating versions."""

    template_id = template_item.get("id")
    if not isinstance(template_id, str) or not template_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Template id is required.",
        )
    template_id = _validate_template_id(template_id.strip())
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
        VALUES (?, ?, ?, 0, NULL, CURRENT_TIMESTAMP)
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
        ),
    )
    _write_template_json(template_id, template_item)


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
        if row is None and not storage_id_reserved("templates", template_id):
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


def resolve_visible_template(
    conn: Connection,
    template_id: str,
) -> dict[str, Any]:
    """Resolve one selectable template inside the caller's transaction."""

    safe_template_id = _validate_template_id(template_id.strip())
    if safe_template_id in BUILT_IN_TEMPLATE_IDS:
        return {
            "id": safe_template_id,
            "preset": safe_template_id,
            **get_builtin_template_preset(safe_template_id),
        }

    if _template_row(conn, safe_template_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="TEMPLATE_NOT_FOUND",
        )

    return _read_template_json(safe_template_id)


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

    with closing(connect()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        catalog = TemplateCatalog(
            default_template_ids=load_default_template_ids(conn),
            templates=_load_template_items(conn, deleted=False),
        )
        conn.execute("COMMIT")

    return catalog


def list_templates(status_filter: str = "active") -> dict[str, Any]:
    """Return active or deleted custom templates."""

    if status_filter not in {"active", "deleted"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported template status filter.",
        )

    with closing(connect()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        result = {
            "templates": _load_template_items(
                conn,
                deleted=status_filter == "deleted",
            )
        }
        conn.execute("COMMIT")

    return result


def create_template(payload: dict[str, Any]) -> dict[str, Any]:
    """Create a backend-owned custom template."""

    with closing(connect()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        saved_at = _utc_now()
        template_id = _allocate_template_id(conn)
        path = _template_path(template_id)
        previous_content = path.read_bytes() if path.exists() else None
        template_item = _build_template_item(
            template_id=template_id,
            payload=payload,
            saved_at=saved_at,
        )
        try:
            _save_template_item(
                conn,
                template_item=template_item,
                saved_at=saved_at,
            )
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                _restore_template_json(template_id, previous_content)
            raise

    return {"template": template_item}


def update_template(template_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Replace one active custom template."""

    safe_template_id = _validate_template_id(template_id.strip())
    path = _template_path(safe_template_id)
    with closing(connect()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        saved_at = _utc_now()
        previous_content = path.read_bytes() if path.exists() else None
        try:
            row = _require_custom_template_row(conn, safe_template_id)
            template_item = _build_template_item(
                template_id=row["id"],
                payload=payload,
                saved_at=saved_at,
            )

            _save_template_item(
                conn,
                template_item=template_item,
                saved_at=saved_at,
            )
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                _restore_template_json(safe_template_id, previous_content)
            raise

    return {"template": template_item}


def trash_template(template_id: str) -> dict[str, Any]:
    """Move a custom template into the recycle bin."""

    # Imported locally because resume commands validate templates through this
    # module. The lifecycle command owns both updates in one SQLite transaction.
    from app.services.resumes import (
        cleanup_resume_version_files,
        rebind_current_resume_template_references,
    )

    rebind_result = None
    try:
        with closing(connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            deleted_at = _utc_now()
            row = _require_custom_template_row(conn, template_id)
            template_item = _read_template_json(row["id"])
            default_template_ids = load_default_template_ids(conn)
            fallback_template_ids = {
                locale: (
                    DEFAULT_TEMPLATE_ID
                    if default_template_ids[locale] == row["id"]
                    else default_template_ids[locale]
                )
                for locale in DOCUMENT_LOCALES
            }

            rebind_result = rebind_current_resume_template_references(
                conn,
                source_template_id=row["id"],
                target_template_ids=fallback_template_ids,
                saved_at=deleted_at,
            )
            for locale in DOCUMENT_LOCALES:
                selected_default_template_id = default_template_ids[locale]
                if selected_default_template_id == row["id"]:
                    store_default_template_id(conn, locale, DEFAULT_TEMPLATE_ID)
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

    with closing(connect()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _require_custom_template_row(
            conn,
            template_id,
            include_deleted=True,
        )
        if not row["deleted"]:
            template_item = _read_template_json(row["id"])
            conn.execute("COMMIT")
            return {"template": template_item}

        cursor = conn.execute(
            """
            UPDATE templates
            SET deleted = 0,
                deleted_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND deleted = 1
            """,
            (row["id"],),
        )
        if cursor.rowcount != 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Template state changed during restore.",
            )
        template_item = _read_template_json(row["id"])
        conn.execute("COMMIT")

    return {"template": template_item}


def delete_template_forever(template_id: str) -> dict[str, Any]:
    """Physically delete one already-deleted custom template."""

    with closing(connect()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        safe_template_id = _validate_template_id(template_id.strip())
        if recover_storage_deletion(conn, "templates", safe_template_id):
            return {"id": safe_template_id}
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

        def delete_rows() -> None:
            conn.execute("DELETE FROM templates WHERE id = ?", (row["id"],))

        delete_storage(
            conn,
            "templates",
            row["id"],
            delete_files=lambda: _delete_template_storage(row["id"]),
            delete_rows=delete_rows,
        )

    return {"id": row["id"]}


def empty_template_trash() -> dict[str, Any]:
    """Physically delete every custom template currently in the recycle bin."""

    with closing(connect()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        recover_storage_deletions(conn, "templates")
        rows = conn.execute(
            """
            SELECT id
            FROM templates
            WHERE deleted = 1
            """,
        ).fetchall()
        template_ids = [row["id"] for row in rows]
        conn.execute("COMMIT")

    for template_id in template_ids:
        delete_template_forever(template_id)

    return {"deletedCount": len(template_ids)}


def save_default_template(
    document_locale: DocumentLocale,
    template_id: str,
) -> dict[str, Any]:
    """Persist the workspace default template after validating the reference."""

    safe_template_id = _validate_template_id(template_id.strip())
    with closing(connect()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        if not is_visible_template(conn, safe_template_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Template not found.",
            )

        store_default_template_id(conn, document_locale, safe_template_id)
        default_template_ids = load_default_template_ids(conn)
        conn.execute("COMMIT")

    return {"defaultTemplateIds": default_template_ids}
