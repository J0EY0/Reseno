import json
import logging
import os
import shutil
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from sqlite3 import Connection
from typing import Literal

from fastapi import HTTPException

from app.config import get_settings
from app.db.connection import connect
from app.services.agent.attachments import (
    ATTACHMENT_STORAGE_DIRNAME,
    locked_agent_attachment_storage,
)

StorageKind = Literal["resumes", "templates"]
_STORAGE_KINDS: tuple[StorageKind, ...] = ("resumes", "templates")
_LOGGER = logging.getLogger(__name__)


def _journal_path(kind: StorageKind, entity_id: str) -> Path:
    if not entity_id or Path(entity_id).name != entity_id or entity_id in {".", ".."}:
        raise ValueError("Invalid storage identity.")
    return get_settings().storage_dir / ".deletions" / kind / entity_id


def _storage_paths(kind: StorageKind, entity_id: str) -> tuple[Path, ...]:
    root = get_settings().storage_dir
    primary = root / kind / entity_id
    if kind == "resumes":
        return primary, root / ATTACHMENT_STORAGE_DIRNAME / entity_id
    return (primary,)


def storage_id_reserved(kind: StorageKind, entity_id: str) -> bool:
    """Reserve identities until their files and deletion journals are gone."""

    return _journal_path(kind, entity_id).exists() or any(
        path.exists() for path in _storage_paths(kind, entity_id)
    )


def _row_exists(conn: Connection, kind: StorageKind, entity_id: str) -> bool:
    return (
        conn.execute(f"SELECT 1 FROM {kind} WHERE id = ?", (entity_id,)).fetchone()
        is not None
    )


def _prepare_journal(kind: StorageKind, entity_id: str) -> Path:
    journal = _journal_path(kind, entity_id)
    journal.mkdir(parents=True)
    present = []
    for index, source in enumerate(_storage_paths(kind, entity_id)):
        present.append(source.exists())
        if source.exists():
            shutil.copytree(
                source, journal / str(index), copy_function=os.link, symlinks=True
            )
    temporary = journal / "ready.tmp"
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(present, file)
        file.flush()
        os.fsync(file.fileno())
    temporary.replace(journal / "ready.json")
    return journal


def _restore_file(source: str, destination: str) -> str:
    if not os.path.exists(destination):
        os.link(source, destination)
    return destination


def _restore_journal(kind: StorageKind, entity_id: str, journal: Path) -> None:
    ready_path = journal / "ready.json"
    if not ready_path.exists():
        return
    present = json.loads(ready_path.read_text(encoding="utf-8"))
    destinations = _storage_paths(kind, entity_id)
    if (
        not isinstance(present, list)
        or len(present) != len(destinations)
        or any(type(value) is not bool for value in present)
    ):
        raise RuntimeError("Invalid storage deletion journal.")
    for index, (destination, existed) in enumerate(
        zip(destinations, present, strict=True)
    ):
        if existed:
            shutil.copytree(
                journal / str(index),
                destination,
                copy_function=_restore_file,
                dirs_exist_ok=True,
                symlinks=True,
            )


def recover_storage_deletion(
    conn: Connection, kind: StorageKind, entity_id: str
) -> bool:
    """Recover one journal under a write transaction; report committed deletion."""

    if not conn.in_transaction:
        raise RuntimeError("Storage recovery requires a write transaction.")
    journal = _journal_path(kind, entity_id)
    if not journal.exists():
        return False
    with locked_agent_attachment_storage():
        deleted = not _row_exists(conn, kind, entity_id)
        if not deleted:
            _restore_journal(kind, entity_id, journal)
            (journal / "ready.json").unlink(missing_ok=True)
        try:
            shutil.rmtree(journal)
        except OSError as exc:
            if deleted:
                raise HTTPException(
                    status_code=503, detail="STORAGE_DELETE_CLEANUP_PENDING"
                ) from exc
            raise
        return deleted


def delete_storage(
    conn: Connection,
    kind: StorageKind,
    entity_id: str,
    *,
    delete_files: Callable[[], None],
    delete_rows: Callable[[], None],
) -> None:
    """Commit file and row deletion with recoverable snapshots on disk."""

    if not conn.in_transaction:
        raise RuntimeError("Storage deletion requires a write transaction.")
    journal = _journal_path(kind, entity_id)
    with locked_agent_attachment_storage():
        try:
            _prepare_journal(kind, entity_id)
            delete_files()
            delete_rows()
            conn.commit()
        except BaseException:
            restore = conn.in_transaction
            if not restore:
                conn.execute("BEGIN IMMEDIATE")
                restore = _row_exists(conn, kind, entity_id)
            if restore:
                _restore_journal(kind, entity_id, journal)
                (journal / "ready.json").unlink(missing_ok=True)
            if journal.exists():
                try:
                    shutil.rmtree(journal)
                except OSError:
                    _LOGGER.warning("Storage deletion journal cleanup is pending.")
            raise
        try:
            shutil.rmtree(journal)
        except OSError as exc:
            raise HTTPException(
                status_code=503, detail="STORAGE_DELETE_CLEANUP_PENDING"
            ) from exc


def recover_storage_deletions(conn: Connection, kind: StorageKind) -> None:
    """Recover pending deletions for one resource kind under a write transaction."""

    directory = get_settings().storage_dir / ".deletions" / kind
    if directory.exists():
        for journal in directory.iterdir():
            recover_storage_deletion(conn, kind, journal.name)


def recover_pending_storage_deletions() -> None:
    """Restore uncommitted deletes and finish committed cleanup before serving."""

    root = get_settings().storage_dir / ".deletions"
    if not root.exists():
        return
    with closing(connect()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        for kind in _STORAGE_KINDS:
            recover_storage_deletions(conn, kind)
