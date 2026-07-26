from functools import cache
from pathlib import Path

from ..section_registry import section_kind_values, section_label_lines

PROMPT_DIR = Path(__file__).resolve().parent


@cache
def load_prompt(filename: str) -> str:
    """Load a checked-in prompt file once per process."""

    return (PROMPT_DIR / filename).read_text(encoding="utf-8").strip()


CORE_POLICY_PROMPT = load_prompt("core_policy.md")
TOOL_POLICY_PROMPT = load_prompt("system.md")
RESUME_EDITING_PLAYBOOK_PROMPT = load_prompt("resume_editing_playbook.md")
SYSTEM_PROMPT = "\n\n".join(
    (
        CORE_POLICY_PROMPT,
        TOOL_POLICY_PROMPT,
        RESUME_EDITING_PLAYBOOK_PROMPT,
    ),
)
FINAL_RESPONSE_PROMPT = load_prompt("final_response.md")
STREAMING_FINAL_RESPONSE_PROMPT = load_prompt("streaming_final_response.md")


def _render_edit_operation_guide(
    filename: str,
) -> str:
    return (
        load_prompt(filename)
        .replace(
            "{section_kind_values}",
            section_kind_values(),
        )
        .replace(
            "{section_label_lines}",
            section_label_lines(("en",)),
        )
    )


EDIT_OPERATION_GUIDE = _render_edit_operation_guide("edit_operation_guide.md")

DEFAULT_REACT_MAX_ITERATIONS = 5
MIN_REACT_MAX_ITERATIONS = 1
MAX_REACT_MAX_ITERATIONS = 8
