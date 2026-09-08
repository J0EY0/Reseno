import base64
import json
import logging
import os
import tempfile
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from sqlite3 import Connection

from app.config import get_settings
from app.db.connection import connect

_LOGGER = logging.getLogger(__name__)


def atomic_write_bytes(path: Path, content: bytes) -> None:
    """Publish a complete file and persist its directory entry."""

    missing = []
    directory = path.parent
    while not directory.exists():
        missing.append(directory)
        directory = directory.parent
    path.parent.mkdir(parents=True, exist_ok=True)
    for directory in reversed(missing):
        _sync_directory(directory.parent)
    descriptor, temp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _journal_directory() -> Path:
    return get_settings().storage_dir / ".template-publications"


def _paths(template_id: str) -> tuple[Path, Path]:
    if (
        not template_id
        or Path(template_id).name != template_id
        or template_id in {".", ".."}
    ):
        raise ValueError("Invalid template storage identity.")
    root = get_settings().storage_dir
    return (
        root / "templates" / template_id / "current.json",
        _journal_directory() / f"{template_id}.json",
    )


def restore_template_bytes(path: Path, content: bytes | None) -> None:
    if content is None:
        path.unlink(missing_ok=True)
        if path.parent.exists():
            _sync_directory(path.parent)
    else:
        atomic_write_bytes(path, content)


def _remove_journal(journal: Path) -> None:
    journal.unlink()
    _sync_directory(journal.parent)


def recover_template_publications(
    conn: Connection, template_id: str | None = None
) -> None:
    """Resolve pending publications against committed template row identities."""

    if not conn.in_transaction:
        raise RuntimeError("Template recovery requires a write transaction.")
    directory = _journal_directory()
    if not directory.exists():
        return
    for temporary in directory.glob(".*.tmp"):
        temporary.unlink()
    _sync_directory(directory)
    if template_id is None:
        journals = sorted(directory.glob("*.json"))
    else:
        journal = _paths(template_id)[1]
        journals = [journal] if journal.exists() else []
    for journal in journals:
        identity = journal.name.removesuffix(".json")
        path, _ = _paths(identity)
        data = json.loads(journal.read_bytes())
        target = data["savedAt"]
        previous = data["previous"]
        if not isinstance(target, str) or not (
            previous is None or isinstance(previous, str)
        ):
            raise ValueError("Invalid template publication journal.")
        row = conn.execute(
            "SELECT saved_at FROM templates WHERE id = ?", (identity,)
        ).fetchone()
        if row is None or row["saved_at"] != target:
            restore_template_bytes(
                path,
                base64.b64decode(previous, validate=True)
                if previous is not None
                else None,
            )
        _remove_journal(journal)


def publish_template(
    conn: Connection,
    *,
    template_id: str,
    saved_at: str,
    publish: Callable[[], None],
    restore: Callable[[bytes | None], None],
) -> None:
    """Commit a file publication with a durable rollback record."""

    if not conn.in_transaction:
        raise RuntimeError("Template publication requires a write transaction.")
    recover_template_publications(conn, template_id)
    path, journal = _paths(template_id)
    previous = path.read_bytes() if path.exists() else None
    atomic_write_bytes(
        journal,
        json.dumps(
            {
                "savedAt": saved_at,
                "previous": base64.b64encode(previous).decode("ascii")
                if previous is not None
                else None,
            },
            separators=(",", ":"),
        ).encode("utf-8"),
    )
    try:
        publish()
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            try:
                restore(previous)
                _remove_journal(journal)
            finally:
                conn.rollback()
        else:
            conn.execute("BEGIN IMMEDIATE")
            recover_template_publications(conn, template_id)
        raise
    try:
        with closing(connect()) as cleanup_conn, cleanup_conn:
            cleanup_conn.execute("BEGIN IMMEDIATE")
            recover_template_publications(cleanup_conn, template_id)
    except Exception:
        _LOGGER.warning("Template publication cleanup is pending.")


def recover_pending_template_publications() -> None:
    """Recover interrupted template writes before serving persisted templates."""

    if not _journal_directory().exists():
        return
    with closing(connect()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        recover_template_publications(conn)
