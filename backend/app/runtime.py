from collections.abc import Iterator
from contextlib import ExitStack, contextmanager

from filelock import FileLock, Timeout

from app.config import Settings


@contextmanager
def backend_instance(settings: Settings) -> Iterator[None]:
    """Hold exclusive ownership of the workspace for the application lifetime."""

    paths = {
        settings.db_path.with_name(f".{settings.db_path.name}.backend.lock"),
        settings.data_dir / ".auth.db.backend.lock",
        settings.storage_dir / ".backend.lock",
    }
    with ExitStack() as locks:
        try:
            for path in sorted(paths):
                path.parent.mkdir(parents=True, exist_ok=True)
                locks.enter_context(FileLock(path, timeout=0))
        except Timeout:
            raise RuntimeError(
                "A backend is already running for this workspace. "
                "Use one worker and one replica per workspace."
            ) from None
        yield
