from typing import Literal

type AgentLocale = Literal["zh", "en"]

SUPPORTED_AGENT_LOCALES: tuple[AgentLocale, ...] = ("zh", "en")
SUPPORTED_AGENT_LOCALE_KEYS = frozenset(SUPPORTED_AGENT_LOCALES)
DEFAULT_AGENT_LOCALE: AgentLocale = "en"


def normalize_agent_locale(value: str | None) -> AgentLocale:
    """Return a supported agent locale, falling back to the default."""

    return value if value in SUPPORTED_AGENT_LOCALE_KEYS else DEFAULT_AGENT_LOCALE


def locale_display_order(locale: str | None) -> tuple[AgentLocale, ...]:
    """Return one locale first, followed by the other supported locales."""

    preferred = normalize_agent_locale(locale)
    return (preferred, *[item for item in SUPPORTED_AGENT_LOCALES if item != preferred])
