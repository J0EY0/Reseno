import sqlite3
from pathlib import Path

from app.config import get_settings


def get_db_path() -> Path:
    """Return the configured SQLite database path."""

    return get_settings().db_path


def connect() -> sqlite3.Connection:
    """Open a SQLite connection with project-required pragmas enabled."""

    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(
        db_path,
        timeout=5.0,
        isolation_level=None,
    )
    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")

    return conn
