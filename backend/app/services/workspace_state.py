"""Persist workspace-wide state inside caller-owned SQLite transactions."""

from sqlite3 import Connection

from app.document_locales import DOCUMENT_LOCALES, DocumentLocale

DEFAULT_TEMPLATE_ID = "minimal"


def load_default_template_ids(conn: Connection) -> dict[DocumentLocale, str]:
    """Load the default template selected for each document language."""

    row = conn.execute(
        """
        SELECT default_template_zh, default_template_en
        FROM workspace_state
        WHERE id = 1
        """,
    ).fetchone()
    if row is None:
        return {locale: DEFAULT_TEMPLATE_ID for locale in DOCUMENT_LOCALES}

    return {
        "zh": str(row["default_template_zh"]),
        "en": str(row["default_template_en"]),
    }


def load_default_template_id(
    conn: Connection,
    document_locale: DocumentLocale,
) -> str:
    """Load the default template selected for one document language."""

    return load_default_template_ids(conn)[document_locale]


def store_default_template_id(
    conn: Connection,
    document_locale: DocumentLocale,
    template_id: str,
) -> None:
    """Persist one language's default template in the caller's transaction."""

    column = {
        "zh": "default_template_zh",
        "en": "default_template_en",
    }[document_locale]

    conn.execute(
        f"""
        INSERT INTO workspace_state (
            id,
            {column},
            updated_at
        )
        VALUES (1, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            {column} = excluded.{column},
            updated_at = CURRENT_TIMESTAMP
        """,
        (template_id,),
    )
