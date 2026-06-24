from pathlib import Path
from sqlite3 import Connection

from app.db.connection import connect

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _table_columns(conn: Connection, table_name: str) -> set[str]:
    """Return the column names currently defined on a SQLite table."""

    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def _ensure_resume_lifecycle_columns(conn: Connection) -> None:
    """Add resume lifecycle metadata introduced after soft delete support."""

    columns = _table_columns(conn, "resumes")
    if "deleted_at" not in columns:
        conn.execute("ALTER TABLE resumes ADD COLUMN deleted_at TEXT")
        conn.execute(
            """
            UPDATE resumes
            SET deleted_at = saved_at
            WHERE deleted != 0 AND deleted_at IS NULL
            """,
        )


def _ensure_template_lifecycle_columns(conn: Connection) -> None:
    """Add template lifecycle metadata introduced after soft delete support."""

    columns = _table_columns(conn, "templates")
    if "deleted_at" not in columns:
        conn.execute("ALTER TABLE templates ADD COLUMN deleted_at TEXT")
        conn.execute(
            """
            UPDATE templates
            SET deleted_at = saved_at
            WHERE deleted != 0 AND deleted_at IS NULL
            """,
        )


def _ensure_workspace_state_schema(conn: Connection) -> None:
    """Replace legacy JSON workspace state with explicit current columns."""

    columns = _table_columns(conn, "workspace_state")
    if columns and "default_template_id" not in columns:
        conn.execute("DROP TABLE workspace_state")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workspace_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                default_template_id TEXT NOT NULL DEFAULT 'minimal',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
        )


def _clear_llm_default_flags(conn: Connection) -> None:
    """Clear legacy default-model preference stored on model config rows."""

    columns = _table_columns(conn, "llm_configs")
    if "is_default" not in columns:
        return

    conn.execute(
        """
        UPDATE llm_configs
        SET is_default = 0
        WHERE is_default != 0
        """,
    )


def migrate_db() -> None:
    """Apply the current schema and safe data migrations."""

    schema = SCHEMA_PATH.read_text(encoding="utf-8")

    with connect() as conn:
        conn.executescript(schema)
        _ensure_resume_lifecycle_columns(conn)
        _ensure_template_lifecycle_columns(conn)
        _ensure_workspace_state_schema(conn)
        _clear_llm_default_flags(conn)
