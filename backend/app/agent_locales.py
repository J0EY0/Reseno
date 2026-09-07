from typing import Literal

type AgentLocale = Literal["zh", "en"]

SUPPORTED_AGENT_LOCALES: tuple[AgentLocale, ...] = ("zh", "en")
SUPPORTED_AGENT_LOCALE_KEYS = frozenset(SUPPORTED_AGENT_LOCALES)
DEFAULT_AGENT_LOCALE: AgentLocale = "en"


def normalize_agent_locale(value: str | None) -> AgentLocale:
    """Return a supported agent locale, falling back to the default."""

    return value if value in SUPPORTED_AGENT_LOCALE_KEYS else DEFAULT_AGENT_LOCALE
