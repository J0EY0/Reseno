import os
from dataclasses import dataclass, field
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
    chromium_executable: str | None
    master_key: str = field(repr=False)
    jwt_secret: str = field(repr=False)


def expand_path(value: str | Path) -> Path:
    """Expand user-relative paths and return an absolute resolved path."""

    return Path(value).expanduser().resolve()


def _configuration_values(path: Path) -> dict[str, str]:
    values = {
        key: value
        for key, value in dotenv_values(path, interpolate=False).items()
        if value is not None
    }
    for key, value in os.environ.items():
        if key not in SECRET_ENV_NAMES or value:
            values[key] = value
    return values


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

    env_file_path = expand_path(os.getenv("APP_ENV_FILE") or DEFAULT_ENV_PATH)
    values = _configuration_values(env_file_path)
    data_dir = expand_path(values.get("APP_DATA_DIR") or DEFAULT_DATA_DIR)
    db_path = expand_path(values.get("APP_DB_PATH") or data_dir / "app.db")
    storage_dir = expand_path(values.get("APP_STORAGE_DIR") or data_dir / "storage")

    return Settings(
        app_name="Reseno Backend",
        app_version="0.1.0",
        data_dir=data_dir,
        db_path=db_path,
        storage_dir=storage_dir,
        export_dir=expand_path(values.get("EXPORT_DIR") or storage_dir / "exports"),
        user_settings_path=expand_path(
            values.get("APP_USER_SETTINGS_PATH") or data_dir / "user_settings.json",
        ),
        env_file_path=env_file_path,
        frontend_render_base_url=values.get(
            "FRONTEND_RENDER_BASE_URL",
            "http://127.0.0.1:5173",
        ).rstrip("/"),
        pdf_render_timeout_ms=_parse_int(values.get("PDF_RENDER_TIMEOUT_MS"), 30000),
        cors_origins=_parse_origins(values.get("BACKEND_CORS_ORIGINS")),
        chromium_executable=values.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE") or None,
        master_key=values.get(MASTER_KEY_ENV_NAME, ""),
        jwt_secret=values.get(JWT_SECRET_ENV_NAME, ""),
    )


def initialize_settings() -> Settings:
    """Validate startup keys and persist missing keys for a fresh workspace."""

    settings = get_settings()
    ensure_env_secrets(
        settings.env_file_path,
        {
            MASTER_KEY_ENV_NAME: settings.master_key,
            JWT_SECRET_ENV_NAME: settings.jwt_secret,
        },
        existing_data_paths=(settings.db_path, settings.data_dir / "auth.db"),
    )
    get_settings.cache_clear()
    return get_settings()
