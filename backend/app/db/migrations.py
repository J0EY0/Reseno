import json
import os
from pathlib import Path
from sqlite3 import Connection

from app.db.connection import connect
from app.services.llm_secrets import (
    encrypt_api_key,
    mask_api_key,
    sanitize_workspace_payload,
)
from app.services.model_configs import sync_llm_configs

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
USER_SETTINGS_KEYS = {"agentSettings", "theme"}


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


def _hydrate_legacy_model_config(config: object) -> object:
    """Attach a plaintext key from env only for one-time legacy migration."""

    if not isinstance(config, dict):
        return config

    if isinstance(config.get("apiKey"), str) and config["apiKey"].strip():
        return config

    env_name = config.get("apiKeyEnvName") or config.get("api_key_env_name")
    if not isinstance(env_name, str) or not env_name.strip():
        return config

    api_key = os.getenv(env_name.strip())
    if not api_key:
        return config

    return {
        **config,
        "apiKey": api_key,
    }


def _purge_workspace_model_secrets(conn: Connection, table_name: str) -> None:
    """Move legacy workspace model keys into llm_configs and scrub snapshots."""

    table = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table_name,),
    ).fetchone()
    if table is None:
        return

    rows = conn.execute(
        f"""
        SELECT rowid, snapshot_json
        FROM {table_name}
        """,
    ).fetchall()

    for row in rows:
        snapshot = json.loads(row["snapshot_json"])
        if not isinstance(snapshot, dict):
            continue

        model_configs = snapshot.get("modelConfigs")
        if isinstance(model_configs, list):
            hydrated_model_configs = [
                _hydrate_legacy_model_config(config) for config in model_configs
            ]
            sync_llm_configs(
                conn,
                hydrated_model_configs,
            )

        sanitized, changed = sanitize_workspace_payload(snapshot)
        if not changed:
            continue

        conn.execute(
            f"""
            UPDATE {table_name}
            SET snapshot_json = ?
            WHERE rowid = ?
            """,
            (
                json.dumps(sanitized, ensure_ascii=False, separators=(",", ":")),
                row["rowid"],
            ),
        )


def _purge_workspace_user_settings(conn: Connection, table_name: str) -> None:
    """Remove settings-page preferences from legacy workspace snapshot tables."""

    table = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table_name,),
    ).fetchone()
    if table is None:
        return

    rows = conn.execute(
        f"""
        SELECT rowid, snapshot_json
        FROM {table_name}
        """,
    ).fetchall()

    for row in rows:
        snapshot = json.loads(row["snapshot_json"])
        if not isinstance(snapshot, dict):
            continue

        sanitized = {
            key: value
            for key, value in snapshot.items()
            if key not in USER_SETTINGS_KEYS
        }
        if sanitized == snapshot:
            continue

        conn.execute(
            f"""
            UPDATE {table_name}
            SET snapshot_json = ?
            WHERE rowid = ?
            """,
            (
                json.dumps(sanitized, ensure_ascii=False, separators=(",", ":")),
                row["rowid"],
            ),
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
        from app.services.workspace import (
            migrate_legacy_workspace_snapshots,
            migrate_workspace_templates,
        )

        migrate_legacy_workspace_snapshots(conn)
        migrate_workspace_templates(conn)
        _purge_workspace_model_secrets(conn, "workspace_snapshots")
        _purge_workspace_model_secrets(conn, "workspace_versions")
        _purge_workspace_user_settings(conn, "workspace_snapshots")
        _purge_workspace_user_settings(conn, "workspace_versions")
        _clear_llm_default_flags(conn)
