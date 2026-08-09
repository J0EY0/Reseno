import sqlite3
from contextlib import closing
from pathlib import Path
from sqlite3 import Connection

from app.db.connection import connect, get_db_path

CURRENT_SCHEMA_VERSION = 1
SCHEMA_PATH = Path(__file__).with_name("schema.sql")

SchemaObjectKey = tuple[str, str]
SchemaObjectSignature = dict[SchemaObjectKey, tuple[str, str]]


class UnsupportedDatabaseSchemaError(RuntimeError):
    """The database is not compatible with this application release."""


def _user_version(conn: Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _schema_signature(conn: Connection) -> SchemaObjectSignature:
    """Return the exact public schema, including constraints and indexes."""

    rows = conn.execute(
        """
        SELECT type, name, tbl_name, sql
        FROM sqlite_schema
        WHERE sql IS NOT NULL
          AND name NOT LIKE 'sqlite_%'
        ORDER BY type, name
        """
    ).fetchall()
    return {
        (str(row["type"]), str(row["name"])): (
            str(row["tbl_name"]),
            " ".join(str(row["sql"]).split()),
        )
        for row in rows
    }


def _expected_schema() -> SchemaObjectSignature:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.row_factory = sqlite3.Row
        conn.executescript(schema)
        return _schema_signature(conn)


def _unsupported_schema_error() -> UnsupportedDatabaseSchemaError:
    db_path = get_db_path()
    return UnsupportedDatabaseSchemaError(
        f"The database at {db_path} is not compatible with ResuMate schema "
        f"v{CURRENT_SCHEMA_VERSION}. Move or delete it to create a fresh "
        f"schema v{CURRENT_SCHEMA_VERSION} database."
    )


def _validate_current_schema(conn: Connection) -> None:
    if _schema_signature(conn) != _expected_schema():
        raise _unsupported_schema_error()


def _initialize_fresh_database(conn: Connection) -> None:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    try:
        conn.executescript(
            "BEGIN IMMEDIATE;\n"
            f"{schema}\n"
            f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION};\n"
            "COMMIT;"
        )
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def ensure_database_schema() -> None:
    """Initialize an empty database or verify the current schema exactly."""

    with closing(connect()) as conn:
        version = _user_version(conn)
        signature = _schema_signature(conn)
        if not signature and version == 0:
            _initialize_fresh_database(conn)
            return

        if version != CURRENT_SCHEMA_VERSION:
            raise _unsupported_schema_error()

        _validate_current_schema(conn)
