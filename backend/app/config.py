import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values

from app.env_secrets import (
    JWT_SECRET_ENV_NAME as JWT_SECRET_ENV_NAME,
)
from app.env_secrets import (
    MASTER_KEY_ENV_NAME as MASTER_KEY_ENV_NAME,
)
from app.env_secrets import (
    SECRET_ENV_NAMES,
    ensure_env_secrets,
)

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = Path("~/.reseno")
DEFAULT_ENV_PATH = BASE_DIR / ".env"


@dataclass(frozen=True)
class Settings:
    """Runtime settings resolved from environment variables and .env files."""

    app_name: str
    app_version: str
    data_dir: Path
    db_path: Path
    storage_dir: Path
    export_dir: Path
    user_settings_path: Path
    env_file_path: Path
    frontend_render_base_url: str
    pdf_render_timeout_ms: int
    cors_origins: tuple[str, ...]


def expand_path(value: str | Path) -> Path:
    """Expand user-relative paths and return an absolute resolved path."""

    return Path(value).expanduser().resolve()


def _path_from_env(key: str, default: str | Path) -> Path:
    """Read a filesystem path from the environment with a fallback."""

    value = os.getenv(key)
    if not value:
        return expand_path(default)

    return expand_path(value)


def load_env_file(path: Path) -> None:
    """Read optional startup configuration without replacing environment values."""

    for key, value in dotenv_values(path, interpolate=False).items():
        if value is not None and key not in SECRET_ENV_NAMES:
            os.environ.setdefault(key, value)


def _parse_origins(value: str | None) -> tuple[str, ...]:
    """Parse the comma-separated CORS origin list."""

    if not value:
        return (
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        )

    return tuple(origin.strip() for origin in value.split(",") if origin.strip())


def _parse_int(value: str | None, default: int) -> int:
    """Parse an integer environment value with a safe fallback."""

    if not value:
        return default

    try:
        return int(value)
    except ValueError:
        return default


@lru_cache
def get_settings() -> Settings:
    """Resolve and cache runtime settings for the backend process."""

    env_file_path = _path_from_env("APP_ENV_FILE", DEFAULT_ENV_PATH)
    load_env_file(env_file_path)

    data_dir = _path_from_env("APP_DATA_DIR", DEFAULT_DATA_DIR)
    db_path = _path_from_env("APP_DB_PATH", data_dir / "app.db")
    storage_dir = _path_from_env("APP_STORAGE_DIR", data_dir / "storage")
    os.environ.update(
        ensure_env_secrets(
            env_file_path,
            {key: os.getenv(key, "") for key in SECRET_ENV_NAMES},
            existing_data_paths=(db_path, data_dir / "auth.db"),
        )
    )

    return Settings(
        app_name="Reseno Backend",
        app_version="0.1.0",
        data_dir=data_dir,
        db_path=db_path,
        storage_dir=storage_dir,
        export_dir=_path_from_env("EXPORT_DIR", storage_dir / "exports"),
        user_settings_path=_path_from_env(
            "APP_USER_SETTINGS_PATH",
            data_dir / "user_settings.json",
        ),
        env_file_path=env_file_path,
        frontend_render_base_url=os.getenv(
            "FRONTEND_RENDER_BASE_URL",
            "http://127.0.0.1:5173",
        ).rstrip("/"),
        pdf_render_timeout_ms=_parse_int(os.getenv("PDF_RENDER_TIMEOUT_MS"), 30000),
        cors_origins=_parse_origins(os.getenv("BACKEND_CORS_ORIGINS")),
    )
