import os
import secrets
from dataclasses import dataclass
from functools import lru_cache
from json import JSONDecodeError, dumps, loads
from pathlib import Path

from cryptography.fernet import Fernet

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = Path("~/.resumate")
DEFAULT_ENV_EXAMPLE_PATH = BASE_DIR / ".env.example"
MASTER_KEY_ENV_NAME = "RESUMATE_MASTER_KEY"
MASTER_KEY_COMMENT = (
    "# DO NOT CHANGE: RESUMATE_MASTER_KEY decrypts secrets stored in SQLite."
)
JWT_SECRET_ENV_NAME = "RESUMATE_JWT_SECRET"
JWT_SECRET_COMMENT = "# DO NOT CHANGE: RESUMATE_JWT_SECRET signs browser JWTs."


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
    host: str
    port: int
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


def _parse_env_value(value: str) -> str:
    """Parse the limited .env value syntax used by this project."""

    trimmed = value.strip()

    if len(trimmed) >= 2 and trimmed[0] == trimmed[-1] and trimmed[0] in {"'", '"'}:
        if trimmed[0] == '"':
            try:
                return str(loads(trimmed))
            except JSONDecodeError:
                pass

        return trimmed[1:-1]

    comment_index = trimmed.find(" #")
    if comment_index >= 0:
        return trimmed[:comment_index].rstrip()

    return trimmed


def _format_env_value(value: str) -> str:
    """Format a single-line value so it can be safely written to .env."""

    if "\n" in value or "\r" in value:
        raise ValueError("Environment values must be single-line strings.")

    if (
        value
        and value == value.strip()
        and not any(char.isspace() for char in value)
        and "#" not in value
        and not any(char in value for char in {'"', "'"})
    ):
        return value

    return dumps(value)


def load_env_file(path: Path) -> None:
    """Load local .env values without overriding real environment variables."""

    if not path.exists() or not path.is_file():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        env_name = key.strip()
        if not env_name or env_name in os.environ:
            continue

        os.environ[env_name] = _parse_env_value(value)


def _write_env_from_example(path: Path) -> None:
    """Create a runtime .env from the project template."""

    if not DEFAULT_ENV_EXAMPLE_PATH.exists():
        path.touch()
        return

    template = DEFAULT_ENV_EXAMPLE_PATH.read_text(encoding="utf-8")
    path.write_text(template.rstrip() + "\n", encoding="utf-8")


def _ensure_env_file(path: Path) -> None:
    """Create the runtime .env once; never overwrite an existing file."""

    if path.exists():
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    _write_env_from_example(path)


def _append_env_value(path: Path, key: str, value: str, comment: str) -> None:
    """Append a commented key-value entry to a .env file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = "\n" if path.exists() and path.stat().st_size else ""
    content = f"{prefix}{comment}\n{key}={_format_env_value(value)}\n"

    with path.open("a", encoding="utf-8") as env_file:
        env_file.write(content)


def _write_env_value(path: Path, key: str, value: str, comment: str) -> None:
    """Replace an empty template value or append a missing one without duplicates."""

    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    target_index: int | None = None

    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        env_name, _ = stripped.split("=", 1)
        if env_name.strip() == key:
            target_index = index
            break

    if target_index is None:
        _append_env_value(path, key, value, comment)
        return

    lines[target_index] = f"{key}={_format_env_value(value)}"
    if comment not in lines:
        insert_index = target_index
        previous_index = target_index - 1
        if (
            previous_index >= 0
            and lines[previous_index].lstrip().startswith("#")
            and key in lines[previous_index]
        ):
            lines[previous_index] = comment
        else:
            lines.insert(insert_index, comment)

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _read_env_file_value(path: Path, key: str) -> str | None:
    """Return one non-empty value from a .env file."""

    if not path.exists() or not path.is_file():
        return None

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        env_name, value = stripped.split("=", 1)
        if env_name.strip() != key:
            continue

        parsed = _parse_env_value(value)
        return parsed if parsed else None

    return None


def _validate_master_key(value: str) -> str:
    """Validate that a value is usable as a Fernet master key."""

    try:
        Fernet(value.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise RuntimeError("Invalid RESUMATE_MASTER_KEY in .env.") from exc

    return value


def _validate_jwt_secret(value: str) -> str:
    """Validate the minimum entropy needed for JWT signing."""

    if len(value.encode("utf-8")) < 32:
        raise RuntimeError("Invalid RESUMATE_JWT_SECRET in .env.")

    return value


def ensure_master_key(path: Path) -> str:
    """Load or create the master key used to encrypt stored API keys."""

    persisted_key = _read_env_file_value(path, MASTER_KEY_ENV_NAME)
    if persisted_key:
        persisted_key = _validate_master_key(persisted_key)
        os.environ[MASTER_KEY_ENV_NAME] = persisted_key
        return persisted_key

    environment_key = os.getenv(MASTER_KEY_ENV_NAME)
    if environment_key:
        environment_key = _validate_master_key(environment_key)
        _write_env_value(path, MASTER_KEY_ENV_NAME, environment_key, MASTER_KEY_COMMENT)
        return environment_key

    # First initialization only: create the master key once and never overwrite
    # it on later starts. Losing or changing this key makes stored API keys
    # undecryptable.
    generated = Fernet.generate_key().decode("ascii")
    _write_env_value(path, MASTER_KEY_ENV_NAME, generated, MASTER_KEY_COMMENT)
    os.environ[MASTER_KEY_ENV_NAME] = generated

    return generated


def ensure_jwt_secret(path: Path) -> str:
    """Load or create the secret used to sign browser JWTs."""

    persisted_secret = _read_env_file_value(path, JWT_SECRET_ENV_NAME)
    if persisted_secret:
        persisted_secret = _validate_jwt_secret(persisted_secret)
        os.environ[JWT_SECRET_ENV_NAME] = persisted_secret
        return persisted_secret

    environment_secret = os.getenv(JWT_SECRET_ENV_NAME)
    if environment_secret:
        environment_secret = _validate_jwt_secret(environment_secret)
        _write_env_value(
            path, JWT_SECRET_ENV_NAME, environment_secret, JWT_SECRET_COMMENT
        )
        return environment_secret

    generated = secrets.token_urlsafe(48)
    _write_env_value(path, JWT_SECRET_ENV_NAME, generated, JWT_SECRET_COMMENT)
    os.environ[JWT_SECRET_ENV_NAME] = generated

    return generated


def _parse_origins(value: str | None) -> tuple[str, ...]:
    """Parse the comma-separated CORS origin list."""

    if not value:
        return (
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:5174",
            "http://localhost:5174",
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

    explicit_env_file_path = os.getenv("APP_ENV_FILE")
    if explicit_env_file_path:
        env_file_path = expand_path(explicit_env_file_path)
    else:
        env_file_path = _path_from_env("APP_DATA_DIR", DEFAULT_DATA_DIR) / ".env"

    _ensure_env_file(env_file_path)
    load_env_file(env_file_path)
    ensure_master_key(env_file_path)
    ensure_jwt_secret(env_file_path)

    # Runtime data defaults outside the repository so project updates do not
    # overwrite user databases, uploads, or exports.
    data_dir = _path_from_env("APP_DATA_DIR", DEFAULT_DATA_DIR)
    storage_dir = _path_from_env("APP_STORAGE_DIR", data_dir / "storage")

    return Settings(
        app_name="ResuMate Backend",
        app_version="0.1.0",
        data_dir=data_dir,
        db_path=_path_from_env("APP_DB_PATH", data_dir / "app.db"),
        storage_dir=storage_dir,
        export_dir=_path_from_env("EXPORT_DIR", storage_dir / "exports"),
        user_settings_path=_path_from_env(
            "APP_USER_SETTINGS_PATH",
            data_dir / "user_settings.json",
        ),
        env_file_path=env_file_path,
        host=os.getenv("APP_HOST", "127.0.0.1"),
        port=_parse_int(os.getenv("APP_PORT"), 8000),
        frontend_render_base_url=os.getenv(
            "FRONTEND_RENDER_BASE_URL",
            "http://127.0.0.1:5173",
        ).rstrip("/"),
        pdf_render_timeout_ms=_parse_int(os.getenv("PDF_RENDER_TIMEOUT_MS"), 30000),
        cors_origins=_parse_origins(os.getenv("BACKEND_CORS_ORIGINS")),
    )
