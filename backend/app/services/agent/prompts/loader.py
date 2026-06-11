from functools import cache
from pathlib import Path

from ..section_registry import section_kind_values, section_label_lines

PROMPT_DIR = Path(__file__).resolve().parent


@cache
def load_prompt(filename: str) -> str:
    """Load a checked-in prompt file once per process."""

    return (PROMPT_DIR / filename).read_text(encoding="utf-8").strip()


SYSTEM_PROMPTS = {
    "zh": load_prompt("system.zh.md"),
    "en": load_prompt("system.en.md"),
}

FINAL_RESPONSE_PROMPTS = {
    "zh": load_prompt("final_response.zh.md"),
    "en": load_prompt("final_response.en.md"),
}

STREAMING_FINAL_RESPONSE_PROMPTS = {
    "zh": load_prompt("streaming_final_response.zh.md"),
    "en": load_prompt("streaming_final_response.en.md"),
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
    "zh": _render_edit_operation_guide(
        "edit_operation_guide.zh.md",
        label_locale_order=("zh", "en"),
    ),
    "en": _render_edit_operation_guide(
        "edit_operation_guide.en.md",
        label_locale_order=("en", "zh"),
    ),
}
EDIT_OPERATION_GUIDE = EDIT_OPERATION_GUIDES["en"]

DEFAULT_REACT_MAX_ITERATIONS = 5
MIN_REACT_MAX_ITERATIONS = 1
MAX_REACT_MAX_ITERATIONS = 8
