import os
import secrets
import tempfile
from io import StringIO
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import dotenv_values, set_key
from filelock import FileLock

MASTER_KEY_ENV_NAME = "RESENO_MASTER_KEY"
JWT_SECRET_ENV_NAME = "RESENO_JWT_SECRET"
SECRET_ENV_NAMES = (MASTER_KEY_ENV_NAME, JWT_SECRET_ENV_NAME)
_SECRET_KEY_WARNING = (
    '# WARNING: Do not delete or change these keys after initialization.\n'
    '# RESENO_MASTER_KEY: losing it prevents decryption of saved credentials.\n'
    '# RESENO_JWT_SECRET: changing it invalidates login and OAuth sessions.\n'
    '# Missing keys prevent startup when data already exists.\n'
    '# Back up this .env together with your database and storage.\n'
)


def _validate_secret(name: str, value: str) -> str:
    try:
        if name == MASTER_KEY_ENV_NAME:
            Fernet(value.encode("ascii"))
        elif len(value.encode("utf-8")) < 32:
            raise ValueError
    except (TypeError, ValueError):
        raise RuntimeError(f"Invalid {name}.") from None
    return value


def _read_env(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except UnicodeError:
        raise RuntimeError("Invalid UTF-8 in the environment file.") from None


def _resolve_secrets(text: str, configured: dict[str, str]) -> dict[str, str]:
    values = dotenv_values(stream=StringIO(text), interpolate=False)
    return {
        name: _validate_secret(name, value)
        for name in SECRET_ENV_NAMES
        if (value := configured.get(name) or values.get(name))
    }


def _persist_secrets(path: Path, text: str, pair: dict[str, str]) -> None:
    if _SECRET_KEY_WARNING not in text:
        text = _SECRET_KEY_WARNING + text
    with tempfile.TemporaryDirectory(
        prefix=f"{path.name}.", dir=path.parent
    ) as temporary_directory:
        temporary_path = Path(temporary_directory) / "env"
        temporary_path.touch(mode=0o600)
        temporary_path.write_text(text, encoding="utf-8")
        for name, value in pair.items():
            set_key(temporary_path, name, value.replace("\\", "\\\\"))
        if _resolve_secrets(_read_env(temporary_path), {}) != pair:
            raise RuntimeError("Unable to persist the configured environment keys.")
        with temporary_path.open("rb") as output:
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
        if os.name != "nt":
            directory_descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)


def ensure_env_secrets(
    env_file_path: Path,
    configured: dict[str, str],
    *,
    existing_data_paths: tuple[Path, ...] = (),
) -> dict[str, str]:
    """Read configured keys or atomically persist a complete pair in the env file."""

    explicit = {
        name: _validate_secret(name, value)
        for name in SECRET_ENV_NAMES
        if (value := configured.get(name))
    }
    if len(explicit) == len(SECRET_ENV_NAMES):
        return explicit
    resolved = _resolve_secrets(_read_env(env_file_path), explicit)
    if len(resolved) == len(SECRET_ENV_NAMES):
        return resolved

    env_file_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with FileLock(f"{env_file_path}.lock", timeout=10, mode=0o600):
        text = _read_env(env_file_path)
        resolved = _resolve_secrets(text, explicit)
        if len(resolved) == len(SECRET_ENV_NAMES):
            return resolved
        if any(
            path.is_file() and path.stat().st_size > 0 for path in existing_data_paths
        ):
            raise RuntimeError(
                "Environment keys are missing for existing data. Restore "
                "RESENO_MASTER_KEY and RESENO_JWT_SECRET in the environment file "
                "or provide both through environment variables."
            )
        pair = {
            MASTER_KEY_ENV_NAME: resolved.get(MASTER_KEY_ENV_NAME)
            or Fernet.generate_key().decode("ascii"),
            JWT_SECRET_ENV_NAME: resolved.get(JWT_SECRET_ENV_NAME)
            or secrets.token_urlsafe(48),
        }
        _persist_secrets(env_file_path, text, pair)
        return pair
