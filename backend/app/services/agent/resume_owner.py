from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from sqlite3 import Connection


class AgentResumeUnavailableError(RuntimeError):
    """Raised when a persistent Agent write has no active resume owner."""


def require_active_resume(conn: Connection, resume_id: str) -> None:
    """Reject a persistent Agent write whose resume is missing or trashed."""

    owner = conn.execute(
        "SELECT 1 FROM resumes WHERE id = ? AND deleted = 0",
        (resume_id,),
    ).fetchone()
    if owner is None:
        raise AgentResumeUnavailableError(
            "The Agent resume owner is unavailable.",
        )


@contextmanager
def active_resume_transaction(
    conn: Connection,
    resume_id: str,
) -> Iterator[None]:
    """Serialize one Agent write with resume trash and permanent deletion."""

    conn.execute("BEGIN IMMEDIATE")
    try:
        require_active_resume(conn, resume_id)
        yield
    except BaseException:
        conn.rollback()
        raise
    else:
        try:
            conn.commit()
        except BaseException:
            if conn.in_transaction:
                conn.rollback()
            raise
