"""Canonical protocol for normalized resume edit operations.

Model-facing tool schemas intentionally accept a friendlier input shape, such
as ``section_type`` and omitted generated IDs. Operations are normalized before
crossing the API boundary; this module validates that stable wire format and
guards the adapter's top-level variants against drift.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

# jsonschema has no bundled stubs in this environment. Keep the suppression at
# the dependency boundary so the rest of the protocol module remains strict.
from jsonschema import Draft7Validator  # type: ignore[import-untyped]
from jsonschema.exceptions import best_match  # type: ignore[import-untyped]

_SCHEMA_PATH = Path(__file__).with_name("resume_edit_operation.schema.json")


@lru_cache(maxsize=1)
def resume_edit_operation_schema() -> dict[str, Any]:
    """Load and validate the packaged operation schema once."""

    payload = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Resume edit operation schema must be a JSON object.")
    Draft7Validator.check_schema(payload)
    return payload


@lru_cache(maxsize=1)
def _resume_edit_operation_validator() -> Draft7Validator:
    return Draft7Validator(resume_edit_operation_schema())


def resume_edit_operation_error(operation: object) -> str | None:
    """Return the most useful protocol validation error, if one exists."""

    error = best_match(_resume_edit_operation_validator().iter_errors(operation))
    if error is None:
        return None
    path = ".".join(str(part) for part in error.absolute_path)
    return f"{path}: {error.message}" if path else error.message


def _operation_signatures(schema: dict[str, Any]) -> dict[str, frozenset[str]]:
    """Return operation type -> required top-level fields for a union schema."""

    signatures: dict[str, frozenset[str]] = {}
    branches = schema.get("oneOf")
    if not isinstance(branches, list):
        return signatures

    for branch in branches:
        if not isinstance(branch, dict):
            continue
        properties = branch.get("properties")
        if not isinstance(properties, dict):
            continue
        type_schema = properties.get("type")
        if not isinstance(type_schema, dict):
            continue
        operation_type = type_schema.get("const")
        if not isinstance(operation_type, str):
            enum = type_schema.get("enum")
            operation_type = (
                enum[0]
                if isinstance(enum, list)
                and len(enum) == 1
                and isinstance(enum[0], str)
                else None
            )
        required = branch.get("required")
        if isinstance(operation_type, str) and isinstance(required, list):
            signatures[operation_type] = frozenset(
                value for value in required if isinstance(value, str)
            )

    return signatures


def assert_model_operation_adapter_compatible(
    model_operation_schema: dict[str, Any],
) -> None:
    """Fail fast when model and application operation variants drift.

    Nested model payloads remain permissive because normalization is part of
    the adapter. Operation names and required top-level fields must remain
    identical to the application protocol.
    """

    expected = _operation_signatures(resume_edit_operation_schema())
    actual = _operation_signatures(model_operation_schema)
    if actual != expected:
        raise RuntimeError(
            "Model operation schema does not match the canonical operation "
            f"protocol: expected {expected!r}, received {actual!r}."
        )
