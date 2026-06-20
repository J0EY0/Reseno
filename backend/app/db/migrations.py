import os
from pathlib import Path
from sqlite3 import Connection

from app.db.connection import connect
from app.services.llm_secrets import (
    encrypt_api_key,
    mask_api_key,
)

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _table_columns(conn: Connection, table_name: str) -> set[str]:
    """Return the column names currently defined on a SQLite table."""

    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def _migrate_llm_configs_schema(conn: Connection) -> None:
    """Upgrade legacy LLM config rows into the encrypted-key schema."""

    columns = _table_columns(conn, "llm_configs")
    required_columns = {
        "client_id",
        "encrypted_api_key",
        "api_key_preview",
        "top_p",
        "system_prompt",
    }
    if not columns or required_columns.issubset(columns):
        return

    legacy_rows = conn.execute(
        """
        SELECT *
        FROM llm_configs
        ORDER BY id ASC
        """,
    ).fetchall()

    conn.execute("ALTER TABLE llm_configs RENAME TO llm_configs_legacy")
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    for row in legacy_rows:
        env_name = row["api_key_env_name"] if "api_key_env_name" in columns else None
        api_key = os.getenv(env_name) if isinstance(env_name, str) else None
        encrypted_api_key = encrypt_api_key(api_key) if api_key else None
        api_key_preview = mask_api_key(api_key) if api_key else ""
        client_id = f"llm-db-{row['id']}"

        conn.execute(
            """
            INSERT INTO llm_configs (
                client_id,
                name,
                provider,
                model,
                base_url,
                encrypted_api_key,
                api_key_preview,
                temperature,
                max_tokens,
                timeout_seconds,
                enabled,
                is_default,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                client_id,
                row["name"],
                row["provider"],
                row["model"],
                row["base_url"],
                encrypted_api_key,
                api_key_preview,
                row["temperature"],
                row["max_tokens"],
                row["timeout_seconds"],
                row["enabled"],
                row["is_default"],
                row["created_at"],
                row["updated_at"],
            ),
        )

    conn.execute("DROP TABLE llm_configs_legacy")


def _ensure_llm_configs_token_columns(conn: Connection) -> None:
    """Add token-limit columns introduced after the encrypted-key schema."""

    columns = _table_columns(conn, "llm_configs")
    if "context_window_tokens" not in columns:
        conn.execute(
            "ALTER TABLE llm_configs ADD COLUMN context_window_tokens INTEGER",
        )


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
        _migrate_llm_configs_schema(conn)
        _ensure_llm_configs_token_columns(conn)
        _ensure_resume_lifecycle_columns(conn)
        _ensure_template_lifecycle_columns(conn)
        _ensure_workspace_state_schema(conn)
        _clear_llm_default_flags(conn)
