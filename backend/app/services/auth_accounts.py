import secrets
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from hmac import compare_digest
from pathlib import Path
from sqlite3 import Connection, Row
from threading import Lock
from typing import cast

from cryptography.exceptions import InvalidKey
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

from app.config import get_settings

ARGON2_LENGTH = 32
ARGON2_ITERATIONS = 2
ARGON2_LANES = 1
ARGON2_MEMORY_COST_KIB = 19 * 1024
ARGON2_SALT_LENGTH = 16
AUTH_DB_FILENAME = "auth.db"
AUTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS auth_owner (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    auth_revision TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""
OAUTH_SCHEMAS = (
    """
    CREATE TABLE IF NOT EXISTS auth_identities (
        provider TEXT PRIMARY KEY CHECK (provider = 'github'),
        subject TEXT NOT NULL,
        label TEXT NOT NULL,
        revision TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS auth_oauth_codes (
        code_hash TEXT PRIMARY KEY,
        browser_hash TEXT NOT NULL,
        provider TEXT NOT NULL,
        subject TEXT NOT NULL,
        label TEXT NOT NULL,
        intent TEXT NOT NULL CHECK (intent IN ('login', 'bind')),
        owner_revision TEXT NOT NULL,
        identity_revision TEXT,
        expires_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS auth_github_app (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        client_id TEXT NOT NULL,
        client_secret TEXT NOT NULL,
        public_base_url TEXT NOT NULL
    )
    """,
)
_initialized_auth_db_paths: set[Path] = set()
_auth_db_init_lock = Lock()


class OwnerAlreadyExistsError(RuntimeError):
    """Raised when setup is attempted after the owner has been created."""


@dataclass(frozen=True)
class OwnerAccount:
    """The single account that owns a Reseno instance."""

    username: str
    auth_revision: str


def get_auth_db_path() -> Path:
    """Return the dedicated authentication database path."""

    settings = get_settings()
    auth_db_path = (settings.data_dir / AUTH_DB_FILENAME).resolve()
    if auth_db_path == settings.db_path:
        raise RuntimeError("APP_DB_PATH must not point to APP_DATA_DIR/auth.db.")

    return auth_db_path


def ensure_auth_database() -> None:
    """Initialize one authentication database once per process and data path."""

    auth_db_path = get_auth_db_path()
    with _auth_db_init_lock:
        if auth_db_path in _initialized_auth_db_paths:
            return

        auth_db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(
            sqlite3.connect(
                auth_db_path,
                timeout=5.0,
                isolation_level=None,
            )
        ) as conn:
            conn.execute("PRAGMA busy_timeout = 5000")
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(AUTH_SCHEMA)
                for schema in OAUTH_SCHEMAS:
                    conn.execute(schema)
                conn.commit()
            except Exception:
                if conn.in_transaction:
                    conn.rollback()
                raise

        auth_db_path.chmod(0o600)
        _initialized_auth_db_paths.add(auth_db_path)


def connect_auth_database() -> Connection:
    ensure_auth_database()
    conn = sqlite3.connect(
        get_auth_db_path(),
        timeout=5.0,
        isolation_level=None,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _owner_row(conn: Connection) -> Row | None:
    return cast(
        Row | None,
        conn.execute(
            """
            SELECT username, password_hash, auth_revision
            FROM auth_owner
            WHERE id = 1
            """,
        ).fetchone(),
    )


def _hash_password(password: str) -> str:
    kdf = Argon2id(
        salt=secrets.token_bytes(ARGON2_SALT_LENGTH),
        length=ARGON2_LENGTH,
        iterations=ARGON2_ITERATIONS,
        lanes=ARGON2_LANES,
        memory_cost=ARGON2_MEMORY_COST_KIB,
    )
    return kdf.derive_phc_encoded(password.encode("utf-8"))


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        Argon2id.verify_phc_encoded(password.encode("utf-8"), password_hash)
    except InvalidKey:
        return False

    return True


def _new_auth_revision() -> str:
    return secrets.token_urlsafe(32)


def _account_from_row(row: Row) -> OwnerAccount:
    return OwnerAccount(
        username=str(row["username"]),
        auth_revision=str(row["auth_revision"]),
    )


def is_setup_required() -> bool:
    """Return whether this instance still needs its owner account."""

    with closing(connect_auth_database()) as conn:
        return _owner_row(conn) is None


def create_owner(username: str, password: str) -> OwnerAccount:
    """Atomically create the one owner account for a fresh instance."""

    password_hash = _hash_password(password)
    auth_revision = _new_auth_revision()

    with closing(connect_auth_database()) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            if _owner_row(conn) is not None:
                raise OwnerAlreadyExistsError

            conn.execute(
                """
                INSERT INTO auth_owner (
                    id,
                    username,
                    password_hash,
                    auth_revision
                )
                VALUES (1, ?, ?, ?)
                """,
                (username, password_hash, auth_revision),
            )
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise

    return OwnerAccount(username=username, auth_revision=auth_revision)


def authenticate_owner(username: str, password: str) -> OwnerAccount | None:
    """Validate submitted credentials against the stored owner account."""

    with closing(connect_auth_database()) as conn:
        row = _owner_row(conn)

    if row is None:
        return None

    password_matches = _verify_password(password, str(row["password_hash"]))
    username_matches = compare_digest(
        str(row["username"]).encode("utf-8"), username.encode("utf-8")
    )
    if not username_matches or not password_matches:
        return None

    return _account_from_row(row)


def owner_identity_matches(username: str, auth_revision: str) -> bool:
    """Return whether token identity matches the current owner revision."""

    with closing(connect_auth_database()) as conn:
        row = _owner_row(conn)

    return (
        row is not None
        and compare_digest(
            str(row["username"]).encode("utf-8"), username.encode("utf-8")
        )
        and compare_digest(str(row["auth_revision"]), auth_revision)
    )


def update_owner_password(
    username: str,
    current_password: str,
    new_password: str,
) -> OwnerAccount | None:
    """Replace the password and revision in one authentication transaction."""

    with closing(connect_auth_database()) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = _owner_row(conn)
            if row is None:
                conn.rollback()
                return None

            password_matches = _verify_password(
                current_password,
                str(row["password_hash"]),
            )
            username_matches = compare_digest(
                str(row["username"]).encode("utf-8"), username.encode("utf-8")
            )
            if not username_matches or not password_matches:
                conn.rollback()
                return None

            password_hash = _hash_password(new_password)
            auth_revision = _new_auth_revision()
            conn.execute(
                """
                UPDATE auth_owner
                SET
                    password_hash = ?,
                    auth_revision = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
                """,
                (password_hash, auth_revision),
            )
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise

    return OwnerAccount(username=username, auth_revision=auth_revision)
