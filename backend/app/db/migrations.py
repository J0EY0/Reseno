from pathlib import Path
from sqlite3 import Connection

from app.db.connection import connect

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
LLM_CONFIG_REQUIRED_COLUMNS = {
    "id",
    "client_id",
    "name",
    "provider",
    "provider_kind",
    "api_family",
    "model",
    "base_url",
    "encrypted_api_key",
    "api_key_preview",
    "temperature",
    "top_p",
    "max_tokens",
    "context_window_tokens",
    "supports_image",
    "supports_thinking",
    "supports_tools",
    "supports_streaming",
    "thinking_enabled",
    "timeout_seconds",
    "enabled",
    "is_default",
    "created_at",
    "updated_at",
}


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


def _ensure_resume_version_kind_column(conn: Connection) -> None:
    """Mark existing immutable versions as checkpoints."""

    columns = _table_columns(conn, "resume_versions")
    if "kind" not in columns:
        conn.execute(
            """
            ALTER TABLE resume_versions
            ADD COLUMN kind TEXT NOT NULL DEFAULT 'checkpoint'
                CHECK (kind IN ('autosave', 'checkpoint'))
            """
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


def _ensure_current_llm_config_schema(conn: Connection) -> None:
    """Discard development-era model configs when the table shape is obsolete."""

    columns = _table_columns(conn, "llm_configs")
    if not columns or LLM_CONFIG_REQUIRED_COLUMNS.issubset(columns):
        return

    conn.execute("DROP TABLE llm_configs")


def migrate_db() -> None:
    """Apply the current schema and safe data migrations."""

    schema = SCHEMA_PATH.read_text(encoding="utf-8")

    with connect() as conn:
        _ensure_current_llm_config_schema(conn)
        conn.executescript(schema)
        _ensure_resume_lifecycle_columns(conn)
        _ensure_resume_version_kind_column(conn)
        _ensure_template_lifecycle_columns(conn)
        _ensure_workspace_state_schema(conn)
