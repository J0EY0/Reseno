import json
import re
from functools import cache, lru_cache
from pathlib import Path
from typing import Any

from app.agent_locales import SUPPORTED_AGENT_LOCALES, normalize_agent_locale

INTENT_PATTERN_FILE = Path(__file__).with_name("intent_patterns.json")


def matches_intent_pattern(
    value: str,
    pattern_name: str,
    *,
    locale: str | None = None,
) -> bool:
    """Return whether text matches one configured language pattern group."""

    pattern = _compiled_pattern(pattern_name, _cache_locale_key(locale))
    return bool(pattern.search(value))


@lru_cache(maxsize=1)
def _pattern_groups() -> dict[str, Any]:
    return json.loads(INTENT_PATTERN_FILE.read_text(encoding="utf-8"))


@cache
def _compiled_pattern(pattern_name: str, locale_key: str) -> re.Pattern[str]:
    group = _pattern_groups().get(pattern_name)
    if not isinstance(group, dict):
        raise KeyError(f"Unknown agent intent pattern group: {pattern_name}")

    fragments = _pattern_fragments(pattern_name, group, locale_key)
    if not fragments:
        raise ValueError(f"Empty agent intent pattern group: {pattern_name}")

    return re.compile("|".join(f"(?:{fragment})" for fragment in fragments), re.I)


def _cache_locale_key(locale: str | None) -> str:
    if locale == "all":
        return "all"
    return normalize_agent_locale(locale) if locale else "all"


def _pattern_fragments(
    pattern_name: str,
    group: dict[str, Any],
    locale_key: str,
) -> list[str]:
    expected_keys = ("common", *SUPPORTED_AGENT_LOCALES)
    selected_keys = (
        expected_keys
        if locale_key == "all"
        else ("common", normalize_agent_locale(locale_key))
    )
    fragments = [
        fragment
        for key in selected_keys
        for fragment in _string_patterns(group.get(key))
    ]
    if fragments:
        return fragments

    raise ValueError(f"Empty agent intent pattern group: {pattern_name}")


def _string_patterns(value: Any) -> list[str]:
    if isinstance(value, str) and value:
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    return []
