import json
import re
from functools import cache, lru_cache
from pathlib import Path
from typing import Any

from app.agent_locales import SUPPORTED_AGENT_LOCALES, normalize_agent_locale

PARSING_PATTERN_FILE = Path(__file__).with_name("parsing_patterns.json")


def agent_pattern(pattern_name: str, *, locale: str | None = None) -> str:
    """Return one configured regex pattern string."""

    return _agent_pattern_for_key(pattern_name, _cache_locale_key(locale))


def _agent_pattern_for_key(pattern_name: str, locale_key: str) -> str:
    value = _pattern_values().get(pattern_name)
    fragments = _pattern_fragments(pattern_name, value, locale_key)
    return "|".join(f"(?:{fragment})" for fragment in fragments)


def agent_patterns(pattern_name: str, *, locale: str | None = None) -> tuple[str, ...]:
    """Return one configured list of literal markers or regex patterns."""

    value = _pattern_values().get(pattern_name)
    return tuple(_pattern_fragments(pattern_name, value, _cache_locale_key(locale)))


def matches_agent_pattern(
    value: str,
    pattern_name: str,
    *,
    locale: str | None = None,
) -> bool:
    """Return whether text matches one configured parsing pattern."""

    pattern = _compiled_pattern(pattern_name, _cache_locale_key(locale))
    return bool(pattern.search(value))


def compiled_agent_pattern(
    pattern_name: str,
    *,
    locale: str | None = None,
) -> re.Pattern[str]:
    """Return a compiled regex for one configured parsing pattern."""

    return _compiled_pattern(pattern_name, _cache_locale_key(locale))


@lru_cache(maxsize=1)
def _pattern_values() -> dict[str, Any]:
    return json.loads(PARSING_PATTERN_FILE.read_text(encoding="utf-8"))


@cache
def _compiled_pattern(pattern_name: str, locale_key: str) -> re.Pattern[str]:
    return re.compile(
        _agent_pattern_for_key(pattern_name, locale_key),
        re.IGNORECASE,
    )


def _cache_locale_key(locale: str | None) -> str:
    if locale == "all":
        return "all"
    return normalize_agent_locale(locale) if locale else "all"


def _pattern_fragments(pattern_name: str, value: Any, locale_key: str) -> list[str]:
    if isinstance(value, str) and value:
        return [value]
    if isinstance(value, list):
        fragments = [item for item in value if isinstance(item, str) and item]
        if fragments:
            return fragments
    if isinstance(value, dict):
        selected_keys = (
            ("common", *SUPPORTED_AGENT_LOCALES)
            if locale_key == "all"
            else ("common", normalize_agent_locale(locale_key))
        )
        fragments = [
            fragment
            for key in selected_keys
            for fragment in _string_patterns(value.get(key))
        ]
        if fragments:
            return fragments
    raise ValueError(f"Empty or unknown agent parsing pattern: {pattern_name}")


def _string_patterns(value: Any) -> list[str]:
    if isinstance(value, str) and value:
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    return []
