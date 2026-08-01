"""Persist workspace-wide state inside caller-owned SQLite transactions."""

from sqlite3 import Connection

DEFAULT_TEMPLATE_ID = "minimal"
WORKSPACE_DATA_LOCALE = "__workspace__"


def load_default_template_id(conn: Connection) -> str:
    """Load the selected template id, falling back to the built-in default."""

    row = conn.execute(
        """
        SELECT default_template_id
        FROM workspace_state
        WHERE id = 1
        """,
    ).fetchone()
    if row is None:
        return DEFAULT_TEMPLATE_ID

    template_id = row["default_template_id"]
    return (
        template_id.strip()
        if isinstance(template_id, str) and template_id.strip()
        else DEFAULT_TEMPLATE_ID
    )


def store_default_template_id(conn: Connection, template_id: str) -> None:
    """Persist the selected template id inside the caller's transaction."""

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
