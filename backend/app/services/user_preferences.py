import json
from threading import Lock
from typing import Any
from uuid import uuid4

from app.config import get_settings
from app.schemas.agent_settings import AgentSettings, normalize_agent_settings
from app.schemas.workspace import ThemeMode

SUPPORTED_LOCALES = {"zh", "en"}
_USER_SETTINGS_LOCK = Lock()


def normalize_theme(value: Any) -> ThemeMode | None:
    """Return a persisted theme value when it is supported."""

    if value == "light":
        return "light"
    if value == "dark":
        return "dark"
    if value == "system":
        return "system"
    return None


def _normalized_agent_settings(value: Any) -> dict[str, str]:
    """Keep only supported Agent settings, tolerating older payloads."""

    return normalize_agent_settings(value).model_dump(
        mode="json",
        by_alias=True,
    )


def _normalize_user_settings(value: Any) -> dict[str, Any]:
    """Normalize preferences loaded from the JSON settings file."""

    if not isinstance(value, dict):
        return {}

    settings: dict[str, Any] = {}
    locale = value.get("locale")
    if isinstance(locale, str) and locale in SUPPORTED_LOCALES:
        settings["locale"] = locale

    theme = normalize_theme(value.get("theme"))
    if theme is not None:
        settings["theme"] = theme

    if "agentSettings" in value:
        settings["agentSettings"] = _normalized_agent_settings(
            value.get("agentSettings")
        )

    return settings


def load_user_settings() -> dict[str, Any]:
    """Load backend-owned user preferences from the configured JSON path."""

    path = get_settings().user_settings_path
    if not path.exists():
        return {}

    try:
        return _normalize_user_settings(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return {}


def load_agent_settings() -> AgentSettings:
    """Load the backend-authoritative Agent preferences."""

    return normalize_agent_settings(load_user_settings().get("agentSettings"))


def _write_user_settings(settings: dict[str, Any]) -> None:
    """Write preferences atomically."""

    path = get_settings().user_settings_path
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    content = json.dumps(
        settings,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    try:
        temp_path.write_text(content, encoding="utf-8")
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def save_user_settings(locale: str, settings: dict[str, Any]) -> dict[str, Any]:
    """Persist settings-page preferences as one read-modify-write transaction."""

    with _USER_SETTINGS_LOCK:
        next_settings = load_user_settings()
        next_settings["locale"] = locale if locale in SUPPORTED_LOCALES else "en"

        theme = normalize_theme(settings.get("theme"))
        if theme is not None:
            next_settings["theme"] = theme

        if "agentSettings" in settings:
            next_settings["agentSettings"] = _normalized_agent_settings(
                settings.get("agentSettings")
            )

        next_settings = _normalize_user_settings(next_settings)
        _write_user_settings(next_settings)
        return next_settings
