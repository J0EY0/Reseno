from functools import cache
from pathlib import Path

from app.agent_locales import (
    DEFAULT_AGENT_LOCALE,
    SUPPORTED_AGENT_LOCALES,
    locale_display_order,
)

from ..section_registry import section_kind_values, section_label_lines

PROMPT_DIR = Path(__file__).resolve().parent


@cache
def load_prompt(filename: str) -> str:
    """Load a checked-in prompt file once per process."""

    return (PROMPT_DIR / filename).read_text(encoding="utf-8").strip()


SYSTEM_PROMPTS = {
    locale: load_prompt(f"system.{locale}.md") for locale in SUPPORTED_AGENT_LOCALES
}

FINAL_RESPONSE_PROMPTS = {
    locale: load_prompt(f"final_response.{locale}.md")
    for locale in SUPPORTED_AGENT_LOCALES
}

STREAMING_FINAL_RESPONSE_PROMPTS = {
    locale: load_prompt(f"streaming_final_response.{locale}.md")
    for locale in SUPPORTED_AGENT_LOCALES
}

def _render_edit_operation_guide(
    filename: str,
    *,
    label_locale_order: tuple[str, ...],
) -> str:
    return load_prompt(filename).replace(
        "{section_kind_values}",
        section_kind_values(),
    ).replace(
        "{section_label_lines}",
        section_label_lines(label_locale_order),
    )


EDIT_OPERATION_GUIDES = {
    locale: _render_edit_operation_guide(
        f"edit_operation_guide.{locale}.md",
        label_locale_order=locale_display_order(locale),
    )
    for locale in SUPPORTED_AGENT_LOCALES
}
EDIT_OPERATION_GUIDE = EDIT_OPERATION_GUIDES[DEFAULT_AGENT_LOCALE]

DEFAULT_REACT_MAX_ITERATIONS = 5
MIN_REACT_MAX_ITERATIONS = 1
MAX_REACT_MAX_ITERATIONS = 8
