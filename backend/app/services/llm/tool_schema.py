from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from typing import Any

# Provider function-calling APIs implement overlapping, but not identical,
# subsets of JSON Schema. These composition/object-cardinality keywords occur
# in the agent's canonical schemas and are rejected by some otherwise
# OpenAI-compatible endpoints. Local validation keeps the canonical schema;
# only the request payload receives this portable projection.
_COMPOSITION_KEYWORDS = ("oneOf", "anyOf")
_UNSUPPORTED_KEYWORDS = frozenset(
    {
        "minProperties",
        "maxProperties",
    },
)


def portable_tool_schema(schema: object) -> dict[str, Any]:
    """Project a canonical tool schema onto a portable provider subset.

    The returned value never shares mutable dictionaries or lists with the
    input. Union branches are flattened into one permissive object shape:
    properties and enum values are combined, while only requirements shared by
    every branch remain required. The backend still validates returned tool
    arguments against the original strict schema.
    """

    if not isinstance(schema, Mapping):
        return {"type": "object", "properties": {}}

    projected = _project_mapping(schema)
    if not projected:
        return {"type": "object", "properties": {}}
    return projected


def _project_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _project_mapping(value)
    if isinstance(value, list):
        return [_project_value(item) for item in value]
    return deepcopy(value)


def _project_mapping(schema: Mapping[object, Any]) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    for raw_key, value in schema.items():
        key = str(raw_key)
        if key in _COMPOSITION_KEYWORDS or key in _UNSUPPORTED_KEYWORDS:
            continue
        if key == "const":
            # `enum` is supported more consistently than `const` across the
            # provider families while preserving the same single-value hint.
            projected.setdefault("enum", [deepcopy(value)])
            continue
        projected[key] = _project_value(value)

    for keyword in _COMPOSITION_KEYWORDS:
        branches = schema.get(keyword)
        if not isinstance(branches, list):
            continue
        projected_branches = [
            _project_mapping(branch)
            for branch in branches
            if isinstance(branch, Mapping)
        ]
        if projected_branches:
            projected = _merge_union(projected, projected_branches)

    return projected


def _merge_union(
    base: dict[str, Any],
    branches: list[dict[str, Any]],
) -> dict[str, Any]:
    """Merge union branches without claiming branch-specific requirements."""

    merged = deepcopy(base)

    branch_types = [branch.get("type") for branch in branches]
    if "type" not in merged and branch_types:
        first_type = branch_types[0]
        if first_type is not None and all(
            value == first_type for value in branch_types
        ):
            merged["type"] = deepcopy(first_type)

    property_names = _ordered_unique(
        name for branch in branches for name in _schema_properties(branch)
    )
    base_properties = _schema_properties(merged)
    property_names = _ordered_unique([*base_properties, *property_names])
    if property_names:
        merged_properties: dict[str, Any] = {}
        for name in property_names:
            variants: list[dict[str, Any]] = []
            base_variant = base_properties.get(name)
            if isinstance(base_variant, Mapping):
                variants.append(dict(base_variant))
            variants.extend(
                dict(candidate)
                for branch in branches
                if isinstance(
                    candidate := _schema_properties(branch).get(name),
                    Mapping,
                )
            )
            if variants:
                merged_properties[name] = _merge_schema_variants(variants)
        merged["properties"] = merged_properties

    base_required = _required_names(merged)
    branch_required = [_required_names(branch) for branch in branches]
    common_required = (
        [
            name
            for name in branch_required[0]
            if all(name in required for required in branch_required[1:])
        ]
        if branch_required
        else []
    )
    required = _ordered_unique([*base_required, *common_required])
    if required:
        merged["required"] = required
    else:
        merged.pop("required", None)

    if "enum" not in merged:
        branch_enums: list[list[Any]] = []
        for branch in branches:
            enum_values = branch.get("enum")
            if isinstance(enum_values, list):
                branch_enums.append(enum_values)
        if len(branch_enums) == len(branches):
            merged["enum"] = _ordered_unique(
                value for values in branch_enums for value in values
            )

    if "description" not in merged:
        description = next(
            (
                value
                for branch in branches
                if isinstance((value := branch.get("description")), str) and value
            ),
            None,
        )
        if description:
            merged["description"] = description

    # Preserve branch metadata when every branch agrees. Divergent constraints
    # cannot be represented portably without restoring a composition keyword.
    handled = {"type", "properties", "required", "enum", "description"}
    common_keys = set.intersection(*(set(branch) for branch in branches))
    for key in common_keys - handled:
        if key in merged:
            continue
        first_value = branches[0][key]
        if all(branch[key] == first_value for branch in branches[1:]):
            merged[key] = deepcopy(first_value)

    return merged


def _merge_schema_variants(variants: list[dict[str, Any]]) -> dict[str, Any]:
    if len(variants) == 1:
        return deepcopy(variants[0])
    return _merge_union({}, variants)


def _schema_properties(schema: Mapping[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties")
    return dict(properties) if isinstance(properties, Mapping) else {}


def _required_names(schema: Mapping[str, Any]) -> list[str]:
    required = schema.get("required")
    if not isinstance(required, list):
        return []
    return [value for value in required if isinstance(value, str)]


def _ordered_unique(values: Iterable[Any]) -> list[Any]:
    unique: list[Any] = []
    for value in values:
        if value not in unique:
            unique.append(value)
    return unique
