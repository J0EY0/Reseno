from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Any

# jsonschema ships without typed stubs in this environment. Keep the ignore at
# the import boundary so validation internals remain checked by strict mypy.
from jsonschema import Draft7Validator  # type: ignore[import-untyped]
from jsonschema.exceptions import best_match  # type: ignore[import-untyped]

from .common import tool_function
from .types import LlmToolCall, LlmToolValidationError


def validate_tool_calls(
    tool_calls: list[LlmToolCall],
    tools: list[dict[str, Any]],
) -> tuple[list[LlmToolCall], list[LlmToolValidationError]]:
    """Validate model-selected tool arguments against the supplied schemas.

    The LLM layer validates mechanical JSON-schema correctness only. It does
    not know whether an edit is desirable; the tool environment and its domain
    engine own authorization and business execution.
    """

    schemas = _tool_parameter_schemas(tools)
    valid: list[LlmToolCall] = []
    errors: list[LlmToolValidationError] = []
    call_id_counts = Counter(tool_call.id for tool_call in tool_calls)

    for tool_call in tool_calls:
        if not tool_call.id.strip():
            errors.append(
                LlmToolValidationError(
                    tool_call=tool_call,
                    message="Tool call id must be non-empty.",
                ),
            )
            continue
        if call_id_counts[tool_call.id] > 1:
            errors.append(
                LlmToolValidationError(
                    tool_call=tool_call,
                    message="Tool call ids must be unique within one response.",
                ),
            )
            continue
        if tool_call.parse_error:
            errors.append(
                LlmToolValidationError(
                    tool_call=tool_call,
                    message=(
                        f"Tool arguments are not valid JSON: {tool_call.parse_error}"
                    ),
                ),
            )
            continue

        schema = schemas.get(tool_call.name)
        if schema is None:
            errors.append(
                LlmToolValidationError(
                    tool_call=tool_call,
                    message=f"Unknown tool `{tool_call.name}`.",
                ),
            )
            continue

        validator = Draft7Validator(schema)
        validation_error = best_match(validator.iter_errors(tool_call.arguments))
        if validation_error is not None:
            errors.append(
                LlmToolValidationError(
                    tool_call=tool_call,
                    message=validation_error.message,
                    path=_error_path(validation_error.path),
                ),
            )
            continue

        valid.append(tool_call)

    return valid, errors


def validation_error_observation(error: LlmToolValidationError) -> dict[str, Any]:
    """Return a synthetic tool observation that asks the model to repair args."""

    path = f" at `{error.path}`" if error.path else ""
    return {
        "ok": False,
        "error": "TOOL_ARGUMENT_VALIDATION_FAILED",
        "message": (
            f"Tool `{error.tool_call.name}` arguments failed validation{path}: "
            f"{error.message}. Return corrected arguments for the same tool."
        ),
    }


def _tool_parameter_schemas(
    tools: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    schemas: dict[str, dict[str, Any]] = {}
    for tool in tools:
        function = tool_function(tool)
        name = str(function.get("name") or "").strip()
        parameters = function.get("parameters")
        if name and isinstance(parameters, dict):
            schemas[name] = parameters

    return schemas


def _error_path(path: Iterable[object]) -> str:
    parts = [str(part) for part in path]
    return ".".join(parts)
